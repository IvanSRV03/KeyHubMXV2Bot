# -*- coding: utf-8 -*-
"""Migración desde el esquema viejo, saldos, límites y fragmentado de mensajes.

Correr con:  python tests/test_db.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _entorno import preparar

DB = preparar("db")

# --- se crea una base con el esquema VIEJO, como la que corre en Railway ---
conn = sqlite3.connect(DB)
conn.executescript(
    """
    CREATE TABLE customers (telegram_id INTEGER PRIMARY KEY, username TEXT,
      first_name TEXT, balance REAL NOT NULL DEFAULT 0, created_at TEXT);
    CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER,
      type TEXT, detail TEXT, amount REAL, created_at TEXT);
    CREATE TABLE products (code TEXT PRIMARY KEY, name TEXT, category TEXT,
      cost REAL, price REAL, updated_at TEXT);
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
    """
)
conn.execute("INSERT INTO customers VALUES (111,'clienteviejo','Juan',250.50,'2025-09-01T00:00:00Z')")
conn.commit()
conn.close()

import db  # noqa: E402

db.init_db()
db.init_db()  # dos deploys seguidos no deben romper nada

c = db.get_customer(111)
assert c["balance"] == 250.50, "se perdió el saldo al migrar"
assert c["status"] == db.APROBADO, "un cliente que ya existía se quedaría sin poder comprar"
assert c["credit_limit"] is None
print("OK migración: el cliente viejo conserva $250.50 y queda aprobado")

assert db.ensure_customer(222, "nuevo", "Ana") is True
assert db.get_customer(222)["status"] == db.PENDIENTE
assert db.ensure_customer(222, "nuevo", "Ana") is False
print("OK un cliente nuevo entra como pendiente")

db.set_customer_status(222, db.BLOQUEADO)
db.ensure_customer(222, "nuevo", "Ana")
assert db.get_customer(222)["status"] == db.BLOQUEADO, "un bloqueado se re-aprobó con /start"
print("OK un cliente bloqueado no se re-aprueba solo con /start")

assert db.add_charge(99999, "charge", {}, 50.0) is False
assert db.get_history(99999) == [], "quedó un movimiento huérfano"
print("OK un cargo a un ID inexistente no escribe nada")

assert db.add_charge(111, "charge", {"concepto": "prueba"}, 10.0) is True
assert db.get_customer(111)["balance"] == 260.50
assert db.add_payment(111, 60.50) is True
assert db.get_customer(111)["balance"] == 200.00
print("OK cargos y pagos mueven el saldo")

assert db.effective_credit_limit(db.get_customer(111)) == db.DEFAULT_CREDIT_LIMIT
db.set_setting("credit_limit_default", 300)
assert db.effective_credit_limit(db.get_customer(111)) == 300.0
db.set_credit_limit(111, 5000)
assert db.effective_credit_limit(db.get_customer(111)) == 5000.0
db.set_credit_limit(111, None)
assert db.effective_credit_limit(db.get_customer(111)) == 300.0
print("OK el límite propio manda sobre el general, y 'global' lo regresa")

db.set_setting("cid_price", "dos pesos")
assert db.get_float_setting("cid_price", 0.0) == 0.0
print("OK un ajuste guardado mal no tumba el bot")

from handlers.common import chunk_lines  # noqa: E402

largo = [f"linea {i} con texto de relleno para llenar el mensaje" for i in range(300)]
pedazos = chunk_lines(largo)
assert len(pedazos) > 1, "no fragmentó un mensaje largo"
assert all(len(p) <= 3800 for p in pedazos), "un pedazo pasa el límite de Telegram"
assert sum(p.count("linea ") for p in pedazos) == 300, "se perdieron líneas al fragmentar"
print(f"OK un mensaje largo se parte en {len(pedazos)} pedazos sin perder líneas")

# --------------------------------------------------------------------------
# Caso real: productos que YA tenían precio antes de que existieran los
# números cortos aparecían como "/None" en el catálogo.
# --------------------------------------------------------------------------
import sqlite3 as _sq  # noqa: E402

conn = _sq.connect(DB)
conn.execute("UPDATE products SET shortcut=NULL")
conn.execute(
    "INSERT OR REPLACE INTO products (code, name, category, cost, price, updated_at, shortcut)"
    " VALUES ('WIN11PRO','Win10/11 Pro OEM 1PC 97%','Windows',5.0,50.0,'2025-09-01',NULL)"
)
conn.execute(
    "INSERT OR REPLACE INTO products (code, name, category, cost, price, updated_at, shortcut)"
    " VALUES ('OFF2019','Office2019 PP Phone','Office',8.0,50.0,'2025-09-01',NULL)"
)
conn.execute(
    "INSERT OR REPLACE INTO products (code, name, category, cost, price, updated_at, shortcut)"
    " VALUES ('SINPRECIO','Producto sin precio','Otros',3.0,NULL,'2025-09-01',NULL)"
)
conn.commit()
conn.close()

db.init_db()  # el arranque debe rellenar los números faltantes

vendibles = db.list_products_a_la_venta()
assert vendibles, "no quedó ningún producto vendible"
sin_numero = [v["code"] for v in vendibles if v["shortcut"] is None]
assert not sin_numero, f"quedaron productos sin número (saldrían como /None): {sin_numero}"
numeros = [v["shortcut"] for v in vendibles]
assert len(numeros) == len(set(numeros)), f"se repitieron números: {numeros}"
assert db.get_product("SINPRECIO")["shortcut"] is None, "se numeró un producto sin precio"
print(f"OK a los productos que ya tenían precio se les asigna número solos: {sorted(numeros)}")

antes = {v["code"]: v["shortcut"] for v in db.list_products_a_la_venta()}
db.init_db()
despues = {v["code"]: v["shortcut"] for v in db.list_products_a_la_venta()}
assert antes == despues, "los números cambiaron al reiniciar el bot"
print("OK los números no cambian al reiniciar")

# --- nombre visible y ocultar ---
assert db.nombre_visible(db.get_product("WIN11PRO")) == "Win10/11 Pro OEM 1PC 97%"
db.set_display_name("WIN11PRO", "Windows 11 Pro")
assert db.nombre_visible(db.get_product("WIN11PRO")) == "Windows 11 Pro"

# el nombre puesto por ti sobrevive a /refrescarproductos
db.upsert_product("WIN11PRO", "Win10/11 Pro OEM 1PC 97% (Warranty: 30 day)", "Windows", 5.0)
assert db.nombre_visible(db.get_product("WIN11PRO")) == "Windows 11 Pro", \
    "el nombre personalizado se perdió al refrescar el catálogo"
print("OK el nombre que le pongas sobrevive a /refrescarproductos")

n_win = db.get_product("WIN11PRO")["shortcut"]
assert db.ocultar_producto("WIN11PRO") is True
assert db.get_product_by_shortcut(n_win) is None, "sigue comprable después de ocultarlo"
assert db.ocultar_producto("WIN11PRO") is False, "ocultar dos veces debería avisar"
assert db.set_product_price("WIN11PRO", 60.0) == n_win, "al revivirlo cambió de número"
print(f"OK ocultar y revivir un producto conserva su número (/{n_win})")

db.set_display_name("WIN11PRO", None)
assert db.nombre_visible(db.get_product("WIN11PRO")).startswith("Win10/11"), "no regresó al nombre original"
print("OK se puede regresar al nombre del proveedor")

print("\nTODO BIEN (catálogo)")
