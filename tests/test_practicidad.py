# -*- coding: utf-8 -*-
"""Lo que se agregó para que pedir y cobrar sea fácil:
atajos /1 /2, reposiciones y pagos con botones.

Correr con:  python tests/test_practicidad.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _entorno import preparar

preparar("practicidad")

import db  # noqa: E402
import provider_api as api  # noqa: E402
from _dobles import FakeContext, FakeMessage, FakeQuery, FakeUpdate, FakeUser, correr  # noqa: E402
from handlers import admin, customer  # noqa: E402

ADMIN = 999
db.init_db()
db.ensure_customer(1, "ana", "Ana", status=db.APROBADO)
db.upsert_product("OFF2021", "Office 2021", "Office", 8.0)
db.upsert_product("OFF2024", "Office 2024", "Office", 10.0)
db.upsert_product("WIN11", "Windows 11 Pro", "Windows", 5.0)


# --- 1) los números cortos se asignan solos al ponerle precio ---
n1 = db.set_product_price("OFF2021", 25.0)
n2 = db.set_product_price("OFF2024", 35.0)
assert (n1, n2) == (1, 2), f"numeracion inesperada: {n1}, {n2}"
assert db.set_product_price("OFF2021", 27.0) == 1, "el número cambió al actualizar el precio"
assert db.get_product_by_shortcut(1)["code"] == "OFF2021"
assert db.get_product_by_shortcut(3) is None, "WIN11 no tiene precio, no debe ser comprable"
print("OK /1 y /2 se asignan solos y no cambian al mover el precio")


# --- 2) el cliente manda /1 y recibe la confirmación de un toque ---
async def no_llamar(code, qty, order_id):
    raise AssertionError("no debió comprarse sin confirmar")


api.a_buy_key = no_llamar

msg = FakeMessage(text="/1")
correr(customer.atajo_handler(FakeUpdate(message=msg, user=FakeUser(1, "ana", "Ana")), FakeContext()))
assert "Office 2021" in msg.respuestas[-1], msg.respuestas
assert "buy:OFF2021:1" in msg.botones(), msg.botones()
assert "Tu saldo quedaría" in msg.respuestas[-1]
print("OK /1 muestra producto, precio y saldo con un solo botón de confirmar")

msg_malo = FakeMessage(text="/77")
correr(customer.atajo_handler(FakeUpdate(message=msg_malo, user=FakeUser(1, "ana", "Ana")), FakeContext()))
assert "número 77" in msg_malo.respuestas[-1]
print("OK un número que no existe avisa en vez de fallar")


# --- 3) el catálogo trae los números y los botones ---
msg_cat = FakeMessage()
correr(customer.productos_cmd(FakeUpdate(message=msg_cat, user=FakeUser(1, "ana", "Ana")), FakeContext()))
texto = msg_cat.respuestas[-1]
assert "/1 — Office 2021" in texto and "/2 — Office 2024" in texto, texto
assert "Windows 11" not in texto, "se mostró un producto sin precio"
assert set(msg_cat.botones()) == {"pick:1", "pick:2"}
print("OK /productos lista con números y un botón por producto")


# --- 4) reposición: el cliente pide, el admin aprueba, llega clave gratis ---
async def proveedor_ok(code, qty, order_id):
    return {"success": True, "keys": ["NUEVA-CLAVE-123"]}


api.a_buy_key = proveedor_ok

db.create_order("KP1", 1, "OFF2021", 1, 27.0)
db.update_order("KP1", db.ORDEN_COMPLETADA, keys=["VIEJA-CLAVE"], charged=True)
db.add_charge(1, "buy_key", {"order_id": "KP1"}, 27.0)
saldo_antes = db.get_customer(1)["balance"]

msg_r = FakeMessage()
correr(customer.reposicion_cmd(FakeUpdate(message=msg_r, user=FakeUser(1, "ana", "Ana")), FakeContext()))
assert "repo:KP1" in msg_r.botones(), msg_r.botones()

ctx_cli = FakeContext()
q = FakeQuery("repo:KP1")
correr(customer.reposicion_pick_callback(FakeUpdate(query=q, user=FakeUser(1, "ana", "Ana")), ctx_cli))
assert ctx_cli.user_data["repo_order_id"] == "KP1"

msg_motivo = FakeMessage(text="dice que la clave ya fue usada")
correr(customer.generic_text_handler(
    FakeUpdate(message=msg_motivo, user=FakeUser(1, "ana", "Ana")), ctx_cli))
assert "Solicitud enviada" in msg_motivo.respuestas[-1]
avisos = ctx_cli.bot.textos_a(ADMIN)
assert any("reposición" in a for a in avisos), avisos
assert any("ya fue usada" in a for a in avisos), "el motivo no le llegó al admin"
print("OK el cliente pide reposición y al admin le llega con el motivo")

repo = db.list_reposiciones(status=db.REPO_SOLICITADA)[0]
ctx_admin = FakeContext()
q_ok = FakeQuery(f"repook:{repo['id']}")
correr(admin.reposicion_resolver_callback(
    FakeUpdate(query=q_ok, user=FakeUser(ADMIN, "jefe", "Jefe")), ctx_admin))

assert db.get_reposicion(repo["id"])["status"] == db.REPO_APROBADA
assert db.get_customer(1)["balance"] == saldo_antes, "la reposición le costó dinero al cliente"
recibido = ctx_admin.bot.textos_a(1)
assert any("NUEVA-CLAVE-123" in t for t in recibido), recibido
assert any("Sin costo" in t for t in recibido)
print("OK al aprobar, el bot compra y entrega la clave nueva sin cobrarle al cliente")

# aprobar dos veces no compra dos veces
q_dup = FakeQuery(f"repook:{repo['id']}")
correr(admin.reposicion_resolver_callback(
    FakeUpdate(query=q_dup, user=FakeUser(ADMIN, "jefe", "Jefe")), FakeContext()))
assert "ya estaba" in q_dup.ediciones[-1], q_dup.ediciones
print("OK una reposición ya resuelta no se vuelve a surtir")

# un cliente no puede aprobarse su propia reposición
db.crear_reposicion(1, "KP1", "OFF2021", "otra vez")
r2 = db.list_reposiciones(status=db.REPO_SOLICITADA)[0]
q_cli = FakeQuery(f"repook:{r2['id']}")
correr(admin.reposicion_resolver_callback(
    FakeUpdate(query=q_cli, user=FakeUser(1, "ana", "Ana")), FakeContext()))
assert "administrador" in q_cli.ediciones[-1]
assert db.get_reposicion(r2["id"])["status"] == db.REPO_SOLICITADA
print("OK un cliente no puede aprobarse su propia reposición")


# --- 5) pagar con botones, sin escribir IDs ---
deuda = db.get_customer(1)["balance"]
assert deuda > 0

msg_p = FakeMessage()
ctx_p = FakeContext()
correr(admin.pagar_cmd(FakeUpdate(message=msg_p, user=FakeUser(ADMIN, "jefe", "Jefe")), ctx_p))
assert "pay:1" in msg_p.botones(), msg_p.botones()

q_sel = FakeQuery("pay:1")
correr(admin.pagar_callback(FakeUpdate(query=q_sel, user=FakeUser(ADMIN, "jefe", "Jefe")), ctx_p))
assert "Liquidó todo" in str(q_sel.message.botones()) or any(
    "pay:1:todo" in b for b in q_sel.message.botones()
), q_sel.message.botones()

q_todo = FakeQuery("pay:1:todo")
ctx_todo = FakeContext()
correr(admin.pagar_callback(FakeUpdate(query=q_todo, user=FakeUser(ADMIN, "jefe", "Jefe")), ctx_todo))
assert db.get_customer(1)["balance"] == 0.0, "no quedó liquidado"
assert any("registró tu pago" in t for t in ctx_todo.bot.textos_a(1)), "no se le avisó al cliente"
print(f"OK liquidar en dos toques: ${deuda:.2f} → $0.00, y el cliente recibe aviso")

# monto parcial escrito a mano
db.add_charge(1, "charge", {"concepto": "prueba"}, 100.0)
ctx_otro = FakeContext()
q_otro = FakeQuery("pay:1:otro")
correr(admin.pagar_callback(FakeUpdate(query=q_otro, user=FakeUser(ADMIN, "jefe", "Jefe")), ctx_otro))
assert ctx_otro.user_data["pago_pendiente_de"] == 1

msg_monto = FakeMessage(text="$40.50")
consumido = correr(admin.monto_texto_handler(
    FakeUpdate(message=msg_monto, user=FakeUser(ADMIN, "jefe", "Jefe")), ctx_otro))
assert consumido is True
assert db.get_customer(1)["balance"] == 59.50, db.get_customer(1)["balance"]
print("OK un abono parcial se escribe como '$40.50' y se aplica bien")

# un texto cualquiera del admin no se confunde con un monto
ctx_libre = FakeContext()
assert correr(admin.monto_texto_handler(
    FakeUpdate(message=FakeMessage(text="hola"), user=FakeUser(ADMIN)), ctx_libre)) is False
print("OK el texto normal del admin no se toma como monto")

# un no-admin no puede registrar pagos con los botones
q_falso = FakeQuery("pay:1:todo")
correr(admin.pagar_callback(FakeUpdate(query=q_falso, user=FakeUser(1, "ana", "Ana")), FakeContext()))
assert "administradores" in q_falso.ediciones[-1]
assert db.get_customer(1)["balance"] == 59.50, "un cliente se liquidó su propia deuda"
print("OK un cliente no puede liquidarse la deuda con los botones")

# --- 6) los comandos de catálogo aceptan código O número ---
db.upsert_product("WIN11PRO", "Win10/11 Pro OEM 1PC 97% (Warranty: 30 day)", "Windows", 5.0)
n_win = db.set_product_price("WIN11PRO", 50.0)

# por número, que es lo que se teclea de forma natural
msg = FakeMessage()
correr(admin.nombre_cmd(
    FakeUpdate(message=msg, user=FakeUser(ADMIN, "jefe", "Jefe")),
    FakeContext(args=[str(n_win), "Windows", "11", "Pro"]),
))
assert db.nombre_visible(db.get_product("WIN11PRO")) == "Windows 11 Pro", msg.respuestas
print(f"OK /nombre {n_win} Windows 11 Pro — funciona con el número")

# por código, como antes
msg = FakeMessage()
correr(admin.nombre_cmd(
    FakeUpdate(message=msg, user=FakeUser(ADMIN, "jefe", "Jefe")),
    FakeContext(args=["WIN11PRO", "Windows", "11", "Pro", "Retail"]),
))
assert db.nombre_visible(db.get_product("WIN11PRO")) == "Windows 11 Pro Retail"
print("OK /nombre WIN11PRO ... — sigue funcionando con el código")

# el cliente ve el nombre nuevo, no el del proveedor
msg_cat = FakeMessage()
correr(customer.productos_cmd(FakeUpdate(message=msg_cat, user=FakeUser(1, "ana", "Ana")), FakeContext()))
assert "Windows 11 Pro Retail" in msg_cat.respuestas[-1]
assert "OEM 1PC 97%" not in msg_cat.respuestas[-1], "el cliente sigue viendo el nombre feo"
print("OK el cliente ve el nombre bonito en /productos")

# /ocultar por número
msg = FakeMessage()
correr(admin.ocultar_cmd(
    FakeUpdate(message=msg, user=FakeUser(ADMIN, "jefe", "Jefe")),
    FakeContext(args=[str(n_win)]),
))
assert db.get_product_by_shortcut(n_win) is None, msg.respuestas
print(f"OK /ocultar {n_win} — funciona con el número")

# /precio por número lo revive con el mismo número
msg = FakeMessage()
correr(admin.set_price_cmd(
    FakeUpdate(message=msg, user=FakeUser(ADMIN, "jefe", "Jefe")),
    FakeContext(args=["WIN11PRO", "60"]),
))
assert db.get_product_by_shortcut(n_win)["code"] == "WIN11PRO"
assert f"/{n_win}" in msg.respuestas[-1], msg.respuestas
print(f"OK al revivirlo recupera su mismo número (/{n_win})")

# un producto que no existe avisa claro
msg = FakeMessage()
correr(admin.nombre_cmd(
    FakeUpdate(message=msg, user=FakeUser(ADMIN, "jefe", "Jefe")),
    FakeContext(args=["999", "Lo", "que", "sea"]),
))
assert "No encontré" in msg.respuestas[-1] and "/catalogo" in msg.respuestas[-1]
print("OK un número inexistente avisa y dice dónde buscar")

print("\nTODO BIEN (catálogo por número)")
