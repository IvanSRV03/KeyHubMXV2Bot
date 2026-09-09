import json
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import db
import provider_api as api
import ocr

WELCOME = (
    "👋 Bienvenido.\n\n"
    "Comandos disponibles:\n"
    "/productos - ver catálogo\n"
    "/comprar CODIGO CANTIDAD - comprar una licencia\n"
    "/cid - obtener tu Confirmation ID (envía tu Installation ID como texto o foto)\n"
    "/saldo - ver tu saldo pendiente\n"
    "/historial - ver tus últimos movimientos\n"
)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_customer(user.id, user.username, user.first_name)
    await update.message.reply_text(WELCOME)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


async def saldo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_customer(user.id, user.username, user.first_name)
    c = db.get_customer(user.id)
    await update.message.reply_text(f"💰 Tu saldo pendiente es: ${c['balance']:.2f}")


async def historial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    rows = db.get_history(user.id, limit=10)
    if not rows:
        await update.message.reply_text("No tienes movimientos todavía.")
        return
    lines = []
    for r in rows:
        detail = json.loads(r["detail"]) if r["detail"] else {}
        etiqueta = {
            "buy_key": "Compra de clave",
            "get_cid": "Confirmation ID",
            "charge": "Cargo",
            "payment": "Pago",
        }.get(r["type"], r["type"])
        lines.append(f"{r['created_at'][:19]} — {etiqueta} — ${r['amount']:.2f}")
    await update.message.reply_text("\n".join(lines))


async def productos_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.list_products()
    by_cat = {}
    for r in rows:
        if r["price"] is None:
            continue
        by_cat.setdefault(r["category"] or "Otros", []).append(r)

    if not by_cat:
        await update.message.reply_text("Todavía no hay productos disponibles. Vuelve a intentar más tarde.")
        return

    lines = []
    for cat, items in by_cat.items():
        lines.append(f"\n📁 {cat}")
        for it in items:
            lines.append(f"  {it['code']} — {it['name']} — ${it['price']:.2f}")
    lines.append("\nPara comprar: /comprar CODIGO CANTIDAD")
    await update.message.reply_text("\n".join(lines))


async def comprar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_customer(user.id, user.username, user.first_name)

    if len(context.args) < 2:
        await update.message.reply_text(
            "Uso: /comprar CODIGO CANTIDAD\nUsa /productos para ver el catálogo y los códigos."
        )
        return

    code, qty_str = context.args[0], context.args[1]
    try:
        qty = int(qty_str)
        assert qty > 0
    except (ValueError, AssertionError):
        await update.message.reply_text("La cantidad debe ser un número entero mayor a 0.")
        return

    product = db.get_product(code)
    if not product or product["price"] is None:
        await update.message.reply_text("Ese código no existe o no está disponible por ahora.")
        return

    total = product["price"] * qty
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirmar compra", callback_data=f"buy:{code}:{qty}"),
                InlineKeyboardButton("❌ Cancelar", callback_data="buy:cancel"),
            ]
        ]
    )
    await update.message.reply_text(
        f"📦 {product['name']}\nCantidad: {qty}\nTotal que se acumulará a tu cuenta: ${total:.2f}\n\n"
        f"¿Confirmas la compra?",
        reply_markup=keyboard,
    )


async def buy_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    if query.data == "buy:cancel":
        await query.edit_message_text("Compra cancelada.")
        return

    _, code, qty_str = query.data.split(":")
    qty = int(qty_str)
    product = db.get_product(code)
    if not product or product["price"] is None:
        await query.edit_message_text("Ese producto ya no está disponible.")
        return

    order_id = api.make_order_id()
    await query.edit_message_text("⏳ Procesando tu compra con el proveedor, un momento...")
    try:
        data = api.buy_key(code, qty, order_id)
    except api.ProviderError as e:
        await query.edit_message_text(
            f"❌ Hubo un problema al procesar la compra: {e}\n\n"
            f"Guarda este número de orden por si el administrador necesita revisarla: {order_id}"
        )
        return

    keys = data.get("keys") or data.get("data")
    total = product["price"] * qty
    db.add_charge(
        user.id,
        "buy_key",
        {"code": code, "qty": qty, "order_id": order_id, "keys": keys},
        total,
    )
    await query.edit_message_text(
        f"✅ Compra realizada.\n\n{keys}\n\n💰 Se agregaron ${total:.2f} a tu cuenta pendiente."
    )


async def cid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_customer(user.id, user.username, user.first_name)

    if context.args:
        iid = " ".join(context.args)
        await _process_cid(update, context, iid)
        return

    context.user_data["awaiting_iid"] = True
    await update.message.reply_text(
        "Envíame tu Installation ID (el que te dio Office/Windows al activar por teléfono).\n"
        "Puedes escribirlo directamente o mandar una foto clara de la pantalla."
    )


async def generic_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_iid"):
        context.user_data["awaiting_iid"] = False
        await _process_cid(update, context, update.message.text)


async def generic_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_iid"):
        return
    context.user_data["awaiting_iid"] = False

    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        image_bytes = await file.download_as_bytearray()
        iid = ocr.extract_installation_id(bytes(image_bytes))
    except ocr.OcrUnavailable:
        await update.message.reply_text(
            "⚠️ Todavía no puedo leer fotos en este servidor (falta configurar el lector de texto).\n"
            "Por favor escribe tu Installation ID directamente, así: /cid 123456-123456-123456-..."
        )
        return
    except Exception as e:
        logging.exception("Error procesando la foto del Installation ID")
        await update.message.reply_text(
            f"❌ Hubo un problema leyendo la foto ({e}).\n"
            "Por favor escribe tu Installation ID directamente, así: /cid 123456-123456-123456-..."
        )
        return

    if not iid:
        await update.message.reply_text(
            "No pude leer bien el Installation ID en la foto. Por favor escríbelo directamente con /cid NUMERO."
        )
        return

    await update.message.reply_text(
        f"Leí este Installation ID de la foto — revisa que esté correcto:\n{iid}\n\nBuscando tu Confirmation ID..."
    )
    await _process_cid(update, context, iid, already_announced=True)


async def _process_cid(update: Update, context: ContextTypes.DEFAULT_TYPE, iid: str, already_announced=False):
    user = update.effective_user
    iid_clean = iid.strip()

    if not already_announced:
        await update.message.reply_text("⏳ Consultando tu Confirmation ID...")

    try:
        data = api.get_cid(iid_clean)
    except api.ProviderError as e:
        await update.message.reply_text(f"❌ No se pudo obtener el CID: {e}")
        return

    cid = data.get("data")
    price = float(db.get_setting("cid_price", "0") or 0)
    db.add_charge(user.id, "get_cid", {"iid": iid_clean, "cid": cid}, price)

    extra = f"\n\n💰 Se agregaron ${price:.2f} a tu cuenta pendiente." if price > 0 else ""
    await update.message.reply_text(f"🆔 Tu Confirmation ID es:\n\n{cid}{extra}")
