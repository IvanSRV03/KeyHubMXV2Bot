# -*- coding: utf-8 -*-
"""Flujo de compra completo con un proveedor simulado (no toca la red).

Cubre los casos que costaban dinero real: doble cobro, cobrar algo que el
proveedor no entregó, y comprar por encima del límite de crédito.

Correr con:  python tests/test_compra.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _entorno import preparar

preparar("compra")

import db  # noqa: E402
import provider_api as api  # noqa: E402
from handlers import customer  # noqa: E402
from _dobles import FakeContext, FakeQuery, FakeUpdate, correr  # noqa: E402

db.init_db()
db.ensure_customer(1, "cliente", "Ana", status=db.APROBADO)
db.upsert_product("OFF2021", "Office 2021", "Office", 8.0, price=25.0)


# --- 1) compra normal ---
llamadas = []


async def proveedor_ok(code, qty, order_id):
    llamadas.append(order_id)
    return {"success": True, "keys": ["AAAAA-BBBBB-CCCCC"]}


api.a_buy_key = proveedor_ok

q = FakeQuery("buy:OFF2021:1")
ctx = FakeContext()
correr(customer.buy_confirm_callback(FakeUpdate(query=q), ctx))
assert len(llamadas) == 1
assert db.get_customer(1)["balance"] == 25.0
orden = db.get_order(llamadas[0])
assert orden["status"] == db.ORDEN_COMPLETADA and orden["charged"] == 1
assert "AAAAA-BBBBB-CCCCC" in q.ediciones[-1]
assert any("Venta" in t for t in ctx.bot.textos_a(999)), "no se le avisó al admin de la venta"
print("OK compra normal: cobra $25.00, orden completada y admin avisado")

# --- 2) doble clic en el mismo botón ---
llamadas.clear()
q2 = FakeQuery("buy:OFF2021:1", mid=77)
ctx2 = FakeContext()
antes = db.get_customer(1)["balance"]
correr(customer.buy_confirm_callback(FakeUpdate(query=q2), ctx2))
correr(customer.buy_confirm_callback(FakeUpdate(query=q2), ctx2))
assert len(llamadas) == 1, f"se compró {len(llamadas)} veces con un solo botón"
assert db.get_customer(1)["balance"] == antes + 25.0, "se cobró doble"
assert q2.alertas, "no se le avisó al cliente del segundo toque"
print("OK doble clic: una sola compra y un solo cargo")

# --- 3) el proveedor se cae o se cuelga ---
llamadas.clear()


async def proveedor_caido(code, qty, order_id):
    llamadas.append(order_id)
    raise api.ProviderError("timeout del proveedor")


api.a_buy_key = proveedor_caido

antes = db.get_customer(1)["balance"]
q3 = FakeQuery("buy:OFF2021:2", mid=88)
ctx3 = FakeContext()
correr(customer.buy_confirm_callback(FakeUpdate(query=q3), ctx3))
assert db.get_customer(1)["balance"] == antes, "cobró una compra que falló"
orden3 = db.get_order(llamadas[0])
assert orden3["status"] == db.ORDEN_PENDIENTE and orden3["charged"] == 0
assert "ningún cargo" in q3.ediciones[-1]
assert any("sin confirmar" in t for t in ctx3.bot.textos_a(999))
assert db.list_orders(status=db.ORDEN_PENDIENTE), "la orden no quedó registrada para revisar"
print("OK proveedor caído: no cobra, deja la orden pendiente y avisa al admin")

# --- 4) límite de crédito ---
async def no_debe_llamarse(code, qty, order_id):
    raise AssertionError("no debió llamarse al proveedor")


api.a_buy_key = no_debe_llamarse
db.set_credit_limit(1, 60.0)
q4 = FakeQuery("buy:OFF2021:5", mid=99)
correr(customer.buy_confirm_callback(FakeUpdate(query=q4), FakeContext()))
assert "límite de crédito" in q4.ediciones[-1]
print("OK el límite de crédito frena la compra antes de llamar al proveedor")

# --- 5) un cliente no aprobado no puede confirmar ---
db.set_credit_limit(1, None)
db.set_customer_status(1, db.PENDIENTE)
q5 = FakeQuery("buy:OFF2021:1", mid=101)
correr(customer.buy_confirm_callback(FakeUpdate(query=q5), FakeContext()))
assert any("pendiente de aprobación" in r for r in q5.message.respuestas)
print("OK un cliente no aprobado no puede confirmar una compra")

# --- 6) las claves se muestran legibles vengan como vengan ---
f = customer._formatear_claves
assert "AAA-BBB" in f("AAA-BBB")
assert "🔑 K1" in f(["K1", "K2"])
assert "🔑 K9" in f([{"key": "K9"}])
assert "administrador" in f(None)
print("OK las claves se muestran legibles en todos los formatos")

print("\nTODO BIEN (compras)")
