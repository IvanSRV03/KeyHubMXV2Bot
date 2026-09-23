import sqlite3
import json
from datetime import datetime, timezone
from contextlib import contextmanager

from config import DB_PATH

# Estados posibles de un cliente.
PENDIENTE = "pendiente"
APROBADO = "aprobado"
BLOQUEADO = "bloqueado"

# Estados de una orden de compra al proveedor.
ORDEN_PENDIENTE = "pendiente"    # se mando, todavia no se confirma que llegaron las claves
ORDEN_COMPLETADA = "completada"  # el proveedor devolvio las claves y se le cobro al cliente
ORDEN_FALLIDA = "fallida"        # confirmado que no se surtio; no se cobro nada

# Estados de una solicitud de reposicion de clave.
REPO_SOLICITADA = "solicitada"
REPO_APROBADA = "aprobada"
REPO_RECHAZADA = "rechazada"

# Valores por defecto de los ajustes globales, usados cuando el admin todavia
# no los configuro. Son conservadores a proposito: mas vale que el bot diga
# "no" de mas y el admin lo suba, a que alguien compre de mas a tu costo.
DEFAULT_CREDIT_LIMIT = 1000.0
DEFAULT_MAX_QTY = 5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    # timeout: si otra escritura tiene la base tomada, espera en vez de
    # reventar con "database is locked".
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
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
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                telegram_id INTEGER,
                code TEXT,
                qty INTEGER,
                total REAL,
                status TEXT,
                keys TEXT,
                error TEXT,
                charged INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS reposiciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                order_id TEXT,
                code TEXT,
                motivo TEXT,
                status TEXT,
                nueva_order_id TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tx_customer ON transactions (telegram_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status, created_at DESC);
            """
        )
        _migrate(conn)


def _migrate(conn):
    """Agrega columnas nuevas a bases que ya existian, sin perder datos."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(customers)")}

    if "status" not in cols:
        conn.execute("ALTER TABLE customers ADD COLUMN status TEXT")
        # Los clientes que ya existian venian de la version sin control de
        # acceso: si les dejaramos 'pendiente' dejarian de poder comprar de
        # golpe, asi que se respetan como aprobados.
        conn.execute("UPDATE customers SET status=?", (APROBADO,))

    if "credit_limit" not in cols:
        # NULL = usa el limite global configurado en settings.
        conn.execute("ALTER TABLE customers ADD COLUMN credit_limit REAL")

    pcols = {r["name"] for r in conn.execute("PRAGMA table_info(products)")}
    if "shortcut" not in pcols:
        # Numero corto para comprar con /1, /2, ... Solo lo tienen los
        # productos con precio de venta, que son los que el cliente ve.
        conn.execute("ALTER TABLE products ADD COLUMN shortcut INTEGER")

    if "display_name" not in pcols:
        # Nombre que ve el cliente. Los del proveedor vienen con cosas como
        # "Win10/11 Pro OEM 1PC 97% (Warranty: 30 day)", que no le dicen nada
        # a un cliente. Este campo sobrevive a /refrescarproductos.
        conn.execute("ALTER TABLE products ADD COLUMN display_name TEXT")

    _asignar_atajos_faltantes(conn)


def _asignar_atajos_faltantes(conn):
    """Le pone numero corto a todo producto con precio que no tenga uno.

    Corre en cada arranque, no solo al crear la columna: los productos a los
    que ya les habias puesto precio antes de que existieran los atajos se
    quedaban sin numero y aparecian como "/None" en el catalogo.
    """
    sin_numero = conn.execute(
        "SELECT code FROM products WHERE price IS NOT NULL AND shortcut IS NULL"
        " ORDER BY category, name"
    ).fetchall()
    if not sin_numero:
        return

    usados = {
        r["shortcut"]
        for r in conn.execute("SELECT shortcut FROM products WHERE shortcut IS NOT NULL")
    }
    n = 1
    for row in sin_numero:
        while n in usados:
            n += 1
        conn.execute("UPDATE products SET shortcut=? WHERE code=?", (n, row["code"]))
        usados.add(n)


# --------------------------------------------------------------------------
# Clientes
# --------------------------------------------------------------------------

def ensure_customer(telegram_id: int, username: str, first_name: str, status: str = PENDIENTE):
    """Da de alta al cliente si no existe. Devuelve True si es nuevo.

    A un cliente que ya existe solo se le refrescan nombre y username: su
    estado nunca se toca aqui, para no re-aprobar a alguien bloqueado.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT telegram_id FROM customers WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO customers (telegram_id, username, first_name, balance, created_at, status)"
                " VALUES (?,?,?,0,?,?)",
                (telegram_id, username, first_name, _now(), status),
            )
            return True
        conn.execute(
            "UPDATE customers SET username=?, first_name=? WHERE telegram_id=?",
            (username, first_name, telegram_id),
        )
        return False


def get_customer(telegram_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM customers WHERE telegram_id=?", (telegram_id,)
        ).fetchone()


def list_customers(status: str = None):
    with get_conn() as conn:
        if status:
            return conn.execute(
                "SELECT * FROM customers WHERE status=? ORDER BY balance DESC", (status,)
            ).fetchall()
        return conn.execute("SELECT * FROM customers ORDER BY balance DESC").fetchall()


def set_customer_status(telegram_id: int, status: str) -> bool:
    """Devuelve False si ese cliente no existe."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE customers SET status=? WHERE telegram_id=?", (status, telegram_id)
        )
        return cur.rowcount > 0


def set_credit_limit(telegram_id: int, limit) -> bool:
    """limit=None hace que el cliente use el limite global."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE customers SET credit_limit=? WHERE telegram_id=?", (limit, telegram_id)
        )
        return cur.rowcount > 0


def effective_credit_limit(customer) -> float:
    """El limite del cliente, o el global si no tiene uno propio."""
    if customer is not None and customer["credit_limit"] is not None:
        return float(customer["credit_limit"])
    return get_float_setting("credit_limit_default", DEFAULT_CREDIT_LIMIT)


# --------------------------------------------------------------------------
# Movimientos
# --------------------------------------------------------------------------

def add_charge(telegram_id: int, type_: str, detail: dict, amount: float) -> bool:
    """amount positivo = cargo (aumenta lo que debe el cliente); negativo = abono.

    Devuelve False (sin escribir nada) si ese cliente no existe, para que el
    cargo no quede huerfano con el saldo sin actualizar.
    """
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM customers WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        if not exists:
            return False
        conn.execute(
            "INSERT INTO transactions (telegram_id, type, detail, amount, created_at) VALUES (?,?,?,?,?)",
            (telegram_id, type_, json.dumps(detail, ensure_ascii=False, default=str), amount, _now()),
        )
        conn.execute(
            "UPDATE customers SET balance = balance + ? WHERE telegram_id=?",
            (amount, telegram_id),
        )
        return True


def add_payment(telegram_id: int, amount: float, note: str = "") -> bool:
    return add_charge(telegram_id, "payment", {"note": note}, -abs(amount))


def get_history(telegram_id: int, limit: int = 10):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM transactions WHERE telegram_id=? ORDER BY id DESC LIMIT ?",
            (telegram_id, limit),
        ).fetchall()


# --------------------------------------------------------------------------
# Productos
# --------------------------------------------------------------------------

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


def set_product_price(code: str, price: float) -> int:
    """Fija el precio y le asigna un numero corto (/1, /2, ...) si no tenia.

    Devuelve el numero corto del producto. El numero se conserva una vez
    asignado, para que un cliente que ya se aprendio "/3 es Office 2021" no
    acabe comprando otra cosa cuando cambie el catalogo.
    """
    with get_conn() as conn:
        conn.execute("UPDATE products SET price=? WHERE code=?", (price, code))
        row = conn.execute("SELECT shortcut FROM products WHERE code=?", (code,)).fetchone()
        if row and row["shortcut"] is not None:
            return row["shortcut"]
        usados = {
            r["shortcut"]
            for r in conn.execute("SELECT shortcut FROM products WHERE shortcut IS NOT NULL")
        }
        n = 1
        while n in usados:
            n += 1
        conn.execute("UPDATE products SET shortcut=? WHERE code=?", (n, code))
        return n


def set_display_name(code: str, nombre) -> bool:
    """Cambia el nombre que ve el cliente. None regresa al del proveedor."""
    with get_conn() as conn:
        cur = conn.execute("UPDATE products SET display_name=? WHERE code=?", (nombre, code))
        return cur.rowcount > 0


def ocultar_producto(code: str) -> bool:
    """Lo saca del catalogo del cliente sin borrarlo.

    Se le conserva el numero corto: si mas adelante le vuelves a poner
    precio, recupera el mismo /N que ya conocian tus clientes.
    """
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE products SET price=NULL WHERE code=? AND price IS NOT NULL", (code,)
        )
        return cur.rowcount > 0


def nombre_visible(row) -> str:
    """El nombre que se le muestra al cliente."""
    return row["display_name"] or row["name"]


def _siguiente_atajo_libre(conn, excepto=None) -> int:
    usados = {
        r["shortcut"]
        for r in conn.execute("SELECT shortcut FROM products WHERE shortcut IS NOT NULL")
    }
    usados.discard(excepto)
    n = 1
    while n in usados:
        n += 1
    return n


def set_shortcut(code: str, n: int):
    """Le cambia el numero corto a un producto.

    Devuelve (que_paso, codigo_del_otro) o None si el producto no existe:

      "sin_cambio"     ya tenia ese numero
      "asignado"       el numero estaba libre
      "liberado"       lo tenia un producto oculto, que se queda sin numero
      "intercambiado"  lo tenia otro producto a la venta; se cambian entre si
    """
    with get_conn() as conn:
        prod = conn.execute(
            "SELECT code, shortcut FROM products WHERE code=?", (code,)
        ).fetchone()
        if prod is None:
            return None
        actual = prod["shortcut"]
        if actual == n:
            return ("sin_cambio", None)

        ocupante = conn.execute(
            "SELECT code, price FROM products WHERE shortcut=? AND code<>?", (n, code)
        ).fetchone()

        if ocupante is None:
            conn.execute("UPDATE products SET shortcut=? WHERE code=?", (n, code))
            return ("asignado", None)

        # Se libera primero el numero para no dejar dos productos con el mismo.
        conn.execute("UPDATE products SET shortcut=NULL WHERE code=?", (ocupante["code"],))
        conn.execute("UPDATE products SET shortcut=? WHERE code=?", (n, code))

        if ocupante["price"] is None:
            # Estaba oculto: no vale la pena darle otro numero.
            return ("liberado", ocupante["code"])

        # Los dos se venden, asi que se intercambian en vez de dejar hueco.
        suyo = actual if actual is not None else _siguiente_atajo_libre(conn, excepto=n)
        conn.execute("UPDATE products SET shortcut=? WHERE code=?", (suyo, ocupante["code"]))
        return ("intercambiado", ocupante["code"])


def get_product_by_shortcut(n: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM products WHERE shortcut=? AND price IS NOT NULL", (n,)
        ).fetchone()


def list_products_a_la_venta():
    """Solo los que el cliente puede comprar, en orden de numero corto."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM products WHERE price IS NOT NULL ORDER BY shortcut"
        ).fetchall()


def clientes_con_adeudo():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM customers WHERE balance > 0 ORDER BY balance DESC"
        ).fetchall()


def list_products():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM products ORDER BY category, name").fetchall()


def get_product(code: str):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM products WHERE code=?", (code,)).fetchone()


# --------------------------------------------------------------------------
# Ordenes al proveedor
# --------------------------------------------------------------------------

def create_order(order_id: str, telegram_id, code: str, qty: int, total: float):
    """Deja registrada la orden ANTES de llamar al proveedor.

    Si la llamada se cuelga o el bot se reinicia a media compra, la orden
    queda guardada y se puede consultar despues con su orderId, en vez de
    vivir unicamente en un mensaje de chat.
    """
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO orders (order_id, telegram_id, code, qty, total, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (order_id, telegram_id, code, qty, total, ORDEN_PENDIENTE, _now(), _now()),
        )


def update_order(order_id: str, status: str, keys=None, error: str = None, charged: bool = None):
    sets = ["status=?", "updated_at=?"]
    vals = [status, _now()]
    if keys is not None:
        sets.append("keys=?")
        vals.append(json.dumps(keys, ensure_ascii=False, default=str))
    if error is not None:
        sets.append("error=?")
        vals.append(error)
    if charged is not None:
        sets.append("charged=?")
        vals.append(1 if charged else 0)
    vals.append(order_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE orders SET {', '.join(sets)} WHERE order_id=?", vals)


def get_order(order_id: str):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()


def list_orders(status: str = None, limit: int = 20):
    with get_conn() as conn:
        if status:
            return conn.execute(
                "SELECT * FROM orders WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()


# --------------------------------------------------------------------------
# Reposiciones de clave
# --------------------------------------------------------------------------

def crear_reposicion(telegram_id: int, order_id: str, code: str, motivo: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO reposiciones (telegram_id, order_id, code, motivo, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (telegram_id, order_id, code, motivo, REPO_SOLICITADA, _now(), _now()),
        )
        return cur.lastrowid


def get_reposicion(repo_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM reposiciones WHERE id=?", (repo_id,)).fetchone()


def resolver_reposicion(repo_id: int, status: str, nueva_order_id: str = None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE reposiciones SET status=?, nueva_order_id=?, updated_at=? WHERE id=?",
            (status, nueva_order_id, _now(), repo_id),
        )


def list_reposiciones(status: str = None, limit: int = 20):
    with get_conn() as conn:
        if status:
            return conn.execute(
                "SELECT * FROM reposiciones WHERE status=? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM reposiciones ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def compras_del_cliente(telegram_id: int, limit: int = 10):
    """Compras completadas del cliente, para que elija cual reponer."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM orders
               WHERE telegram_id=? AND status=?
               ORDER BY created_at DESC LIMIT ?""",
            (telegram_id, ORDEN_COMPLETADA, limit),
        ).fetchall()


# --------------------------------------------------------------------------
# Ajustes
# --------------------------------------------------------------------------

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


def get_float_setting(key: str, default: float) -> float:
    """Lee un ajuste numerico sin tronar si quedo guardado algo raro."""
    try:
        return float(get_setting(key, default))
    except (TypeError, ValueError):
        return default


def get_int_setting(key: str, default: int) -> int:
    try:
        return int(float(get_setting(key, default)))
    except (TypeError, ValueError):
        return default
