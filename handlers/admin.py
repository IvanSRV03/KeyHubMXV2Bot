from telegram import Update
from telegram.ext import ContextTypes

import db
import provider_api as api
from handlers.common import is_admin

# Según lo que confirmaste: C008 = clave válida, C060 = clave no válida.
# Cualquier otro código se muestra tal cual para que lo revises manualmente,
# ya que no confirmaste el significado de otros códigos (por ejemplo C003).
KNOWN_CODES = {
    "0xC004C008": "✅ Válida",
    "0xC004C060": "❌ No válida (bloqueada/agotada)",
}


async def _guard(update: Update) -> bool:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Este comando es solo para administradores.")
        return False
    return True


async def checkkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /checkkey CLAVE1 CLAVE2 ...")
        return
    keys = ",".join(context.args)
    try:
        data = api.check_keys(keys)
    except api.ProviderError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    lines = []
    for r in data.get("results", []):
        code = r.get("ErrorCode", "")
        estado = KNOWN_CODES.get(code, "ℹ️ Código no catalogado, revisa manualmente")
        lines.append(
            f"🔑 {r.get('Key')}\n📝 {r.get('Description')}\n⚠️ {code} — {estado}\n⏰ {r.get('Time')}"
        )
    lines.append(f"\nUsadas hoy: {data.get('used')} / {data.get('limit')} (restantes: {data.get('remaining')})")
    await update.message.reply_text("\n\n".join(lines))


async def checkredeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /checkredeem CLAVE1 CLAVE2 ...")
        return
    keys = ",".join(context.args)
    try:
        data = api.check_redeem(keys)
    except api.ProviderError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    lines = []
    for r in data.get("results", []):
        lines.append(
            f"🔑 {r.get('Key')}\n📝 {r.get('Description')}\n🎁 {r.get('ErrorCode')}\n⏰ {r.get('Time')}"
        )
    lines.append(f"\nUsadas hoy: {data.get('used')} / {data.get('limit')} (restantes: {data.get('remaining')})")
    await update.message.reply_text("\n\n".join(lines))


async def admincid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtiene un CID sin cargarlo a la cuenta de ningún cliente (uso interno)."""
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /admincid INSTALLATION_ID")
        return
    iid = " ".join(context.args)
    try:
        data = api.get_cid(iid)
    except api.ProviderError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    await update.message.reply_text(f"🆔 CID: {data.get('data')}")


async def refresh_products_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    try:
        data = api.key_products()
    except api.ProviderError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    # La documentación que me pasaste no incluye un ejemplo del JSON exacto de
    # /key-products, así que este parser cubre la forma más común (categorías
    # con lista de productos). Si el catálogo sale vacío o mal, mándame la
    # respuesta cruda de esta llamada y ajusto el parseo.
    raw = data.get("data") or data.get("categories") or []
    count = 0

    def handle_product(p, cat_name):
        nonlocal count
        code = p.get("code") or p.get("id") or p.get("productId")
        name = p.get("name") or p.get("title") or code
        cost = p.get("price") or p.get("cost") or 0
        if code:
            db.upsert_product(str(code), str(name), str(cat_name), float(cost))
            count += 1

    if isinstance(raw, dict):
        for cat_name, cat_data in raw.items():
            products = cat_data.get("products", cat_data) if isinstance(cat_data, dict) else cat_data
            if isinstance(products, list):
                for p in products:
                    if isinstance(p, dict):
                        handle_product(p, cat_name)
    elif isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            cat_name = entry.get("category") or entry.get("name") or "Otros"
            products = entry.get("products")
            if isinstance(products, list):
                for p in products:
                    if isinstance(p, dict):
                        handle_product(p, cat_name)
            elif entry.get("code") or entry.get("id"):
                handle_product(entry, cat_name)

    await update.message.reply_text(
        f"Catálogo actualizado: {count} productos guardados.\n"
        f"Usa /precio CODIGO PRECIO para asignarle un precio de venta a cada uno — "
        f"solo los productos con precio asignado aparecen en /productos para los clientes."
    )


async def set_price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /precio CODIGO PRECIO")
        return
    code, price_str = context.args[0], context.args[1]
    try:
        price = float(price_str)
    except ValueError:
        await update.message.reply_text("El precio debe ser un número.")
        return
    product = db.get_product(code)
    if not product:
        await update.message.reply_text("Ese código no existe todavía. Corre /refrescarproductos primero.")
        return
    db.set_product_price(code, price)
    await update.message.reply_text(f"Precio actualizado: {code} → ${price:.2f}")


async def set_cid_price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if not context.args:
        current = db.get_setting("cid_price", "0")
        await update.message.reply_text(
            f"Precio actual por CID a clientes: ${float(current):.2f}\nUso: /preciocid PRECIO"
        )
        return
    try:
        price = float(context.args[0])
    except ValueError:
        await update.message.reply_text("El precio debe ser un número.")
        return
    db.set_setting("cid_price", price)
    await update.message.reply_text(f"Precio por CID actualizado a ${price:.2f}")


async def clientes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    rows = db.list_customers()
    if not rows:
        await update.message.reply_text("No hay clientes registrados todavía.")
        return
    lines = []
    for r in rows:
        nombre = r["username"] or r["first_name"] or str(r["telegram_id"])
        lines.append(f"@{nombre} (ID {r['telegram_id']}) — ${r['balance']:.2f}")
    await update.message.reply_text("\n".join(lines))


async def cliente_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /cliente TELEGRAM_ID  (usa /clientes para ver la lista de IDs)")
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El ID debe ser numérico.")
        return
    c = db.get_customer(tid)
    if not c:
        await update.message.reply_text("Cliente no encontrado.")
        return
    hist = db.get_history(tid, limit=10)
    lines = [
        f"Cliente: @{c['username'] or c['first_name']} (ID {tid})",
        f"Saldo: ${c['balance']:.2f}",
        "\nÚltimos movimientos:",
    ]
    for h in hist:
        lines.append(f"{h['created_at'][:19]} — {h['type']} — ${h['amount']:.2f}")
    await update.message.reply_text("\n".join(lines))


async def cobrar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /cobrar TELEGRAM_ID MONTO [concepto]")
        return
    try:
        tid = int(context.args[0])
        monto = float(context.args[1])
    except ValueError:
        await update.message.reply_text("El ID y el monto deben ser numéricos.")
        return
    concepto = " ".join(context.args[2:]) or "cargo manual"
    db.add_charge(tid, "charge", {"concepto": concepto}, monto)
    await update.message.reply_text(f"Se agregó ${monto:.2f} al saldo de {tid} ({concepto}).")


async def pagar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /pagar TELEGRAM_ID MONTO")
        return
    try:
        tid = int(context.args[0])
        monto = float(context.args[1])
    except ValueError:
        await update.message.reply_text("El ID y el monto deben ser numéricos.")
        return
    db.add_payment(tid, monto, note="pago registrado por admin")
    c = db.get_customer(tid)
    saldo = c["balance"] if c else 0
    await update.message.reply_text(f"Pago registrado. Nuevo saldo de {tid}: ${saldo:.2f}")


async def buy_stock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Compra claves al proveedor sin asignarlas a ningún cliente (para tener inventario propio)."""
    if not await _guard(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /comprarstock CODIGO CANTIDAD")
        return
    code, qty_str = context.args[0], context.args[1]
    try:
        qty = int(qty_str)
    except ValueError:
        await update.message.reply_text("La cantidad debe ser un número entero.")
        return
    order_id = api.make_order_id()
    try:
        data = api.buy_key(code, qty, order_id)
    except api.ProviderError as e:
        await update.message.reply_text(
            f"❌ {e}\nOrden: {order_id} — si el proveedor la sigue procesando, puedes "
            f"consultarla después llamando a buy-key/order con este mismo orderId."
        )
        return
    await update.message.reply_text(
        f"✅ Compra al proveedor completada.\nOrden: {order_id}\n\n{data.get('data') or data.get('keys')}"
    )
