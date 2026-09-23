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

print("\nTODO BIEN (base de datos)")
