import sqlite3
import json
from datetime import datetime, timezone
from contextlib import contextmanager

from config import DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance REAL NOT NULL DEFAULT 0,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                type TEXT,
                detail TEXT,
                amount REAL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS products (
                code TEXT PRIMARY KEY,
                name TEXT,
                category TEXT,
                cost REAL,
                price REAL,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )


def ensure_customer(telegram_id: int, username: str, first_name: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT telegram_id FROM customers WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO customers (telegram_id, username, first_name, balance, created_at) VALUES (?,?,?,0,?)",
                (telegram_id, username, first_name, _now()),
            )
        else:
            conn.execute(
                "UPDATE customers SET username=?, first_name=? WHERE telegram_id=?",
                (username, first_name, telegram_id),
            )


def get_customer(telegram_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM customers WHERE telegram_id=?", (telegram_id,)
        ).fetchone()


def list_customers():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM customers ORDER BY balance DESC").fetchall()


def add_charge(telegram_id: int, type_: str, detail: dict, amount: float):
    """amount positivo = cargo (aumenta lo que debe el cliente); negativo = abono."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO transactions (telegram_id, type, detail, amount, created_at) VALUES (?,?,?,?,?)",
            (telegram_id, type_, json.dumps(detail, ensure_ascii=False, default=str), amount, _now()),
        )
        conn.execute(
            "UPDATE customers SET balance = balance + ? WHERE telegram_id=?",
            (amount, telegram_id),
        )


def add_payment(telegram_id: int, amount: float, note: str = ""):
    add_charge(telegram_id, "payment", {"note": note}, -abs(amount))


def get_history(telegram_id: int, limit: int = 10):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM transactions WHERE telegram_id=? ORDER BY id DESC LIMIT ?",
            (telegram_id, limit),
        ).fetchall()


def upsert_product(code: str, name: str, category: str, cost: float, price=None):
    with get_conn() as conn:
        existing = conn.execute("SELECT price FROM products WHERE code=?", (code,)).fetchone()
        keep_price = existing["price"] if existing and price is None else price
        conn.execute(
            """INSERT INTO products (code, name, category, cost, price, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(code) DO UPDATE SET
                 name=excluded.name, category=excluded.category,
                 cost=excluded.cost, updated_at=excluded.updated_at""",
            (code, name, category, cost, keep_price, _now()),
        )


def set_product_price(code: str, price: float):
    with get_conn() as conn:
        conn.execute("UPDATE products SET price=? WHERE code=?", (price, code))


def list_products():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM products ORDER BY category, name").fetchall()


def get_product(code: str):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM products WHERE code=?", (code,)).fetchone()


def set_setting(key: str, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


def get_setting(key: str, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default
