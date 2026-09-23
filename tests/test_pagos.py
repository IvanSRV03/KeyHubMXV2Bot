# -*- coding: utf-8 -*-
"""El cliente ve cómo pagarte, manda el comprobante y tú lo apruebas.

Correr con:  python tests/test_pagos.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _entorno import preparar

preparar("pagos")

import db  # noqa: E402
from _dobles import FakeContext, FakeMessage, FakeQuery, FakeUpdate, FakeUser, correr  # noqa: E402
from handlers import admin, customer  # noqa: E402

ADMIN = 999
db.init_db()
db.ensure_customer(1, "ana", "Ana", status=db.APROBADO)
db.add_charge(1, "charge", {"concepto": "compras"}, 300.0)


class MensajeConFoto(FakeMessage):
    def __init__(self, file_id="FOTO123", mid=10):
        super().__init__(mid)
        self.photo = [type("P", (), {"file_id": file_id})()]


# --- 1) /saldo muestra cuánto debe y cómo pagar ---
msg = FakeMessage()
correr(customer.saldo_cmd(FakeUpdate(message=msg, user=FakeUser(1, "ana", "Ana")), FakeContext()))
texto = msg.respuestas[-1]
assert "$300.00" in texto
assert "CLABE" in texto and "012180015972489513" in texto, texto
assert "comp:enviar" in msg.botones()
print("OK /saldo muestra el saldo, la CLABE y el botón para mandar comprobante")

# --- al corriente: no le enseña la CLABE ni el botón ---
msg_ok = FakeMessage()
db.ensure_customer(2, "beto", "Beto", status=db.APROBADO)
correr(customer.saldo_cmd(FakeUpdate(message=msg_ok, user=FakeUser(2, "beto", "Beto")), FakeContext()))
assert "al corriente" in msg_ok.respuestas[-1]
assert "CLABE" not in msg_ok.respuestas[-1], "le enseña datos de pago a quien no debe nada"
assert msg_ok.botones() == []
print("OK a quien no debe nada no se le enseñan datos de pago")

# --- 2) el cliente toca el botón y manda la foto ---
ctx_cli = FakeContext()
q = FakeQuery("comp:enviar")
correr(customer.comprobante_enviar_callback(
    FakeUpdate(query=q, user=FakeUser(1, "ana", "Ana")), ctx_cli))
assert ctx_cli.user_data["awaiting_comprobante"] is True

foto = MensajeConFoto("COMPROBANTE_ABC")
correr(customer.generic_photo_handler(
    FakeUpdate(message=foto, user=FakeUser(1, "ana", "Ana")), ctx_cli))
assert "Recibí tu comprobante" in foto.respuestas[-1]
assert ("awaiting_comprobante" not in ctx_cli.user_data)
assert ctx_cli.bot.fotos == [(ADMIN, "COMPROBANTE_ABC")], "la foto no le llegó al admin"
aviso = [t for cid, t, _ in ctx_cli.bot.enviados if cid == ADMIN][0]
assert "Comprobante de pago #1" in aviso and "$300.00" in aviso, aviso
print("OK el cliente manda la foto y te llega con su saldo y botones")

# --- la misma foto NO se confunde con un Installation ID ---
comp = db.get_comprobante(1)
assert comp["status"] == db.COMP_ENVIADO and comp["file_id"] == "COMPROBANTE_ABC"
print("OK la foto de comprobante no se intenta leer como Installation ID")

# --- 3) apruebas «liquidó todo» y se borra el saldo ---
ctx_admin = FakeContext()
q_ok = FakeQuery("comp:1:todo")
correr(admin.comprobante_callback(
    FakeUpdate(query=q_ok, user=FakeUser(ADMIN, "jefe", "Jefe")), ctx_admin))
assert db.get_customer(1)["balance"] == 0.0, db.get_customer(1)["balance"]
assert db.get_comprobante(1)["status"] == db.COMP_APROBADO
assert db.get_comprobante(1)["monto_aplicado"] == 300.0
avisos = [t for cid, t, _ in ctx_admin.bot.enviados if cid == 1]
assert any("Confirmé tu pago de $300.00" in t for t in avisos), avisos
assert any("al corriente" in t for t in avisos)
print("OK al aprobar se liquida el saldo y el cliente recibe confirmación")

# --- no se puede aprobar dos veces ---
q_dup = FakeQuery("comp:1:todo")
correr(admin.comprobante_callback(
    FakeUpdate(query=q_dup, user=FakeUser(ADMIN, "jefe", "Jefe")), FakeContext()))
assert "ya estaba" in q_dup.ediciones[-1], q_dup.ediciones
assert db.get_customer(1)["balance"] == 0.0, "se aplicó el pago dos veces"
print("OK un comprobante ya resuelto no se aplica de nuevo")

# --- 4) pago parcial ---
db.add_charge(1, "charge", {"concepto": "más compras"}, 500.0)
ctx2 = FakeContext()
foto2 = MensajeConFoto("COMP2", mid=20)
ctx2.user_data["awaiting_comprobante"] = True
correr(customer.generic_photo_handler(
    FakeUpdate(message=foto2, user=FakeUser(1, "ana", "Ana")), ctx2))
comp2 = db.list_comprobantes(status=db.COMP_ENVIADO)[0]

ctx_admin2 = FakeContext()
q_otro = FakeQuery(f"comp:{comp2['id']}:otro")
correr(admin.comprobante_callback(
    FakeUpdate(query=q_otro, user=FakeUser(ADMIN, "jefe", "Jefe")), ctx_admin2))
assert ctx_admin2.user_data["comprobante_pendiente"] == comp2["id"]

msg_monto = FakeMessage(text="$200")
consumido = correr(admin.monto_texto_handler(
    FakeUpdate(message=msg_monto, user=FakeUser(ADMIN, "jefe", "Jefe")), ctx_admin2))
assert consumido is True
assert db.get_customer(1)["balance"] == 300.0, db.get_customer(1)["balance"]
assert db.get_comprobante(comp2["id"])["monto_aplicado"] == 200.0
print("OK un abono parcial deja el resto pendiente ($500 - $200 = $300)")

# --- 5) rechazar ---
ctx3 = FakeContext()
foto3 = MensajeConFoto("COMP3", mid=30)
ctx3.user_data["awaiting_comprobante"] = True
correr(customer.generic_photo_handler(
    FakeUpdate(message=foto3, user=FakeUser(1, "ana", "Ana")), ctx3))
comp3 = db.list_comprobantes(status=db.COMP_ENVIADO)[0]

saldo_antes = db.get_customer(1)["balance"]
ctx_admin3 = FakeContext()
q_no = FakeQuery(f"comp:{comp3['id']}:no")
correr(admin.comprobante_callback(
    FakeUpdate(query=q_no, user=FakeUser(ADMIN, "jefe", "Jefe")), ctx_admin3))
assert db.get_customer(1)["balance"] == saldo_antes, "un rechazo movió el saldo"
assert db.get_comprobante(comp3["id"])["status"] == db.COMP_RECHAZADO
assert any("No pude confirmar" in t for cid, t, _ in ctx_admin3.bot.enviados if cid == 1)
print("OK rechazar no mueve el saldo y se le avisa al cliente")

# --- 6) un cliente no puede aprobarse su propio comprobante ---
ctx4 = FakeContext()
foto4 = MensajeConFoto("COMP4", mid=40)
ctx4.user_data["awaiting_comprobante"] = True
correr(customer.generic_photo_handler(
    FakeUpdate(message=foto4, user=FakeUser(1, "ana", "Ana")), ctx4))
comp4 = db.list_comprobantes(status=db.COMP_ENVIADO)[0]

saldo_antes = db.get_customer(1)["balance"]
q_falso = FakeQuery(f"comp:{comp4['id']}:todo")
correr(admin.comprobante_callback(
    FakeUpdate(query=q_falso, user=FakeUser(1, "ana", "Ana")), FakeContext()))
assert db.get_customer(1)["balance"] == saldo_antes, "¡un cliente se borró su propia deuda!"
assert db.get_comprobante(comp4["id"])["status"] == db.COMP_ENVIADO
print("OK un cliente NO puede aprobarse su propio comprobante")

# --- 7) los datos bancarios se pueden cambiar sin redesplegar ---
msg = FakeMessage()
correr(admin.datos_bancarios_cmd(
    FakeUpdate(message=msg, user=FakeUser(ADMIN, "jefe", "Jefe")),
    FakeContext(args=["Banorte", "—", "Otro", "Nombre", "/", "CLABE:", "072..."]),
))
assert "Banorte" in db.datos_pago() and "\n" in db.datos_pago()
msg2 = FakeMessage()
db.add_charge(2, "charge", {}, 10.0)
correr(customer.saldo_cmd(FakeUpdate(message=msg2, user=FakeUser(2, "beto", "Beto")), FakeContext()))
assert "Banorte" in msg2.respuestas[-1], "el cliente sigue viendo los datos viejos"
print("OK /datosbancarios cambia lo que ve el cliente, sin tocar el código")

print("\nTODO BIEN (pagos)")
