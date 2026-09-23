# -*- coding: utf-8 -*-
"""Lectura del Installation ID por foto y el flujo de /cid.

Correr con:  python tests/test_cid.py

Si tesseract no está instalado, la parte de lectura se salta con aviso
(el resto del flujo sí se prueba).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _entorno import preparar

preparar("cid")

import db  # noqa: E402
import ocr  # noqa: E402
import provider_api as api  # noqa: E402
from _dobles import FakeContext, FakeMessage, FakeQuery, FakeUpdate, FakeUser, correr  # noqa: E402
from _pantallas import banco, como_bytes, id_al_azar, pantalla  # noqa: E402
from handlers import customer  # noqa: E402

ADMIN = 999
db.init_db()
db.ensure_customer(1, "ana", "Ana", status=db.APROBADO)

# --------------------------------------------------------------------------
# 1) Qué tan bien lee las fotos
# --------------------------------------------------------------------------
hay_tesseract = True
try:
    ocr.extract_installation_id(como_bytes(pantalla(id_al_azar(9, 6, 0), 6)))
except ocr.OcrUnavailable:
    hay_tesseract = False

if not hay_tesseract:
    print("⚠️  tesseract no está instalado: se salta la medición de lectura.")
    print("   (En Mac: brew install tesseract)")
else:
    casos = banco()
    aciertos = 0
    for desc, datos, esperado in casos:
        leido = ocr.extract_installation_id(datos)
        bien = leido == esperado
        aciertos += bien
        print(f"  {'✓' if bien else '✗'} {desc}")
    print(f"\n  Lectura correcta en {aciertos}/{len(casos)} pantallas")
    # El umbral es deliberadamente holgado: si alguien vuelve a meter
    # tessedit_char_whitelist (que tumba esto a 0/10) o rompe el
    # preprocesamiento, la prueba lo caza.
    assert aciertos >= 8, f"el lector empeoró: solo {aciertos}/{len(casos)}"
    print("OK el lector de fotos mantiene su nivel")


# --------------------------------------------------------------------------
# 2) El flujo: foto -> confirmar -> proveedor
# --------------------------------------------------------------------------
IID = "1" * 54


class FakeFile:
    def __init__(self, datos):
        self._datos = datos

    async def download_as_bytearray(self):
        return bytearray(self._datos)


class FakePhoto:
    def __init__(self, datos):
        self._datos = datos

    async def get_file(self):
        return FakeFile(self._datos)


class MensajeConFoto(FakeMessage):
    def __init__(self, datos, mid=10):
        super().__init__(mid)
        self.photo = [FakePhoto(datos)]


llamadas = []


async def proveedor_cid(iid):
    llamadas.append(iid)
    return {"success": True, "data": "CID-123456"}


api.a_get_cid = proveedor_cid

# --- la foto se lee y se pide confirmación, sin llamar al proveedor todavía ---
grupos = id_al_azar(9, 6, semilla=42)
datos = como_bytes(pantalla(grupos, 6, semilla=42))
ocr_real = ocr.extract_installation_id
ocr.extract_installation_id = lambda b: "-".join(grupos)  # lectura determinista

msg = MensajeConFoto(datos)
ctx = FakeContext()
correr(customer.generic_photo_handler(FakeUpdate(message=msg, user=FakeUser(1, "ana", "Ana")), ctx))
assert llamadas == [], "llamó al proveedor antes de que el cliente confirmara"
assert "¿Está bien?" in msg.respuestas[-1], msg.respuestas
assert set(msg.botones()) == {"cid:ok", "cid:no"}
assert ctx.user_data["iid_leido"] == "".join(grupos)
print("OK la foto se lee y se pide confirmación antes de gastar una consulta")

# --- al confirmar, sí se consulta y se avisa al admin ---
q = FakeQuery("cid:ok")
correr(customer.cid_confirm_callback(FakeUpdate(query=q, user=FakeUser(1, "ana", "Ana")), ctx))
assert llamadas == ["".join(grupos)], llamadas
assert "CID-123456" in q.message.respuestas[-1], q.message.respuestas
assert any("CID generado" in t for t in ctx.bot.textos_a(ADMIN)), "no se le avisó al admin"
print("OK al confirmar se obtiene el CID y le llega el aviso al admin")

# --- "lo escribo yo" deja al bot esperando el texto ---
ctx2 = FakeContext()
ctx2.user_data["iid_leido"] = IID
q2 = FakeQuery("cid:no")
correr(customer.cid_confirm_callback(FakeUpdate(query=q2, user=FakeUser(1, "ana", "Ana")), ctx2))
assert ctx2.user_data.get("awaiting_iid") is True
assert "iid_leido" not in ctx2.user_data
print("OK el botón de corregir deja al bot esperando el número escrito")

# --- una lectura incompleta NO se manda al proveedor ---
ocr.extract_installation_id = lambda b: "123456-123456-123456"  # solo 18 dígitos
llamadas.clear()
msg3 = MensajeConFoto(datos, mid=11)
correr(customer.generic_photo_handler(
    FakeUpdate(message=msg3, user=FakeUser(1, "ana", "Ana")), FakeContext()))
assert llamadas == [], "mandó una lectura incompleta al proveedor (gasta cupo)"
assert "incompleto" in msg3.respuestas[-1] and "18 dígitos" in msg3.respuestas[-1]
print("OK una lectura incompleta se rechaza sin gastar consulta del proveedor")

# --- si no se lee nada, se explica qué hacer ---
ocr.extract_installation_id = lambda b: None
msg4 = MensajeConFoto(datos, mid=12)
correr(customer.generic_photo_handler(
    FakeUpdate(message=msg4, user=FakeUser(1, "ana", "Ana")), FakeContext()))
assert "No pude leer" in msg4.respuestas[-1]
assert "sombra" in msg4.respuestas[-1], "no se le dice al cliente cómo tomar mejor la foto"
print("OK si no se lee nada, se le explica al cliente cómo mejorar la foto")

ocr.extract_installation_id = ocr_real

# --- pegar el Installation ID sin mandar /cid antes también funciona ---
llamadas.clear()
msg5 = FakeMessage(mid=13, text="111111-111111-111111-111111-111111-111111-111111-111111-111111")
correr(customer.generic_text_handler(
    FakeUpdate(message=msg5, user=FakeUser(1, "ana", "Ana")), FakeContext()))
assert llamadas == [IID], f"no reconoció un Installation ID pegado directo: {llamadas}"
print("OK pegar el Installation ID sin /cid también funciona")

# --- un texto cualquiera no dispara nada ---
llamadas.clear()
msg6 = FakeMessage(mid=14, text="hola, tienes office?")
correr(customer.generic_text_handler(
    FakeUpdate(message=msg6, user=FakeUser(1, "ana", "Ana")), FakeContext()))
assert llamadas == [] and msg6.respuestas == []
print("OK un mensaje normal no se confunde con un Installation ID")

print("\nTODO BIEN (CID)")
