import asyncio
import logging
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import db
import provider_api as api
import ocr
from handlers.common import require_approved, reply_long, notify_admins, is_admin

logger = logging.getLogger(__name__)

WELCOME = (
    "👋 Bienvenido.\n\n"
    "Comandos disponibles:\n"
    "/productos - ver catálogo\n"
    "/comprar CODIGO CANTIDAD - comprar una licencia\n"
    "/cid - obtener tu Confirmation ID (envía tu Installation ID como texto o foto)\n"
    "/saldo - ver tu saldo pendiente\n"
    "/historial - ver tus últimos movimientos\n"
)

PENDIENTE_MSG = (
    "👋 Hola. Ya registré tu solicitud.\n\n"
    "Este bot funciona con clientes autorizados, así que el administrador tiene "
    "que aprobarte antes de que puedas comprar. Te aviso en cuanto estés dado de alta."
)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if is_admin(user.id):
        db.ensure_customer(user.id, user.username, user.first_name, status=db.APROBADO)
        await update.message.reply_text(WELCOME + "\nEres administrador: usa /help para tus comandos.")
        return

    nuevo = db.ensure_customer(user.id, user.username, user.first_name)
    customer = db.get_customer(user.id)

    if nuevo:
        etiqueta = f"@{user.username}" if user.username else (user.first_name or "sin nombre")
        await notify_admins(
            context,
            "🆕 Nueva solicitud de acceso\n"
            f"{etiqueta} (ID {user.id})\n\n"
            f"Para darle acceso: /aprobar {user.id}\n"
            f"Para ignorarlo: /bloquear {user.id}",
        )

    if customer["status"] == db.APROBADO:
        await update.message.reply_text(WELCOME)
    elif customer["status"] == db.BLOQUEADO:
        await update.message.reply_text("⛔ Tu acceso está suspendido.")
    else:
        await update.message.reply_text(PENDIENTE_MSG)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


async def saldo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_customer(user.id, user.username, user.first_name)
    c = db.get_customer(user.id)
    limite = db.effective_credit_limit(c)
    disponible = max(limite - c["balance"], 0)
    await update.message.reply_text(
        f"💰 Tu saldo pendiente es: ${c['balance']:.2f}\n"
        f"🧾 Límite de crédito: ${limite:.2f} (disponible: ${disponible:.2f})"
    )


async def historial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    rows = db.get_history(user.id, limit=10)
    if not rows:
        await update.message.reply_text("No tienes movimientos todavía.")
        return
    lines = []
    for r in rows:
        etiqueta = {
            "buy_key": "Compra de clave",
            "get_cid": "Confirmation ID",
            "charge": "Cargo",
            "payment": "Pago",
        }.get(r["type"], r["type"])
        lines.append(f"{r['created_at'][:19]} — {etiqueta} — ${r['amount']:.2f}")
    await reply_long(update, lines)


async def productos_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_approved(update, context):
        return

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
    await reply_long(update, lines)


async def comprar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    customer = await require_approved(update, context)
    if not customer:
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Uso: /comprar CODIGO CANTIDAD\nUsa /productos para ver el catálogo y los códigos."
        )
        return

    code, qty_str = context.args[0], context.args[1]
    try:
        qty = int(qty_str)
    except ValueError:
        await update.message.reply_text("La cantidad debe ser un número entero mayor a 0.")
        return
    if qty <= 0:
        await update.message.reply_text("La cantidad debe ser un número entero mayor a 0.")
        return

    max_qty = db.get_int_setting("max_qty", db.DEFAULT_MAX_QTY)
    if qty > max_qty:
        await update.message.reply_text(
            f"⚠️ El máximo por compra es {max_qty} unidades. Si necesitas más, pídeselo al administrador."
        )
        return

    product = db.get_product(code)
    if not product or product["price"] is None:
        await update.message.reply_text("Ese código no existe o no está disponible por ahora.")
        return

    total = product["price"] * qty
    ok, aviso = _cabe_en_el_credito(customer, total)
    if not ok:
        await update.message.reply_text(aviso)
        return

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


def _formatear_claves(keys) -> str:
    """El proveedor no siempre devuelve las claves en el mismo formato, asi que
    se normaliza a algo legible en vez de volcarle un dict crudo al cliente."""
    if keys is None:
        return "(el proveedor no devolvió claves — avisa al administrador)"
    if isinstance(keys, str):
        return keys
    if isinstance(keys, list):
        partes = []
        for k in keys:
            if isinstance(k, dict):
                partes.append(str(k.get("key") or k.get("Key") or k))
            else:
                partes.append(str(k))
        return "\n".join(f"🔑 {p}" for p in partes)
    if isinstance(keys, dict):
        return str(keys.get("key") or keys.get("Key") or keys)
    return str(keys)


def _cabe_en_el_credito(customer, monto: float):
    """Revisa que el cargo no pase el limite de credito del cliente."""
    limite = db.effective_credit_limit(customer)
    nuevo_saldo = customer["balance"] + monto
    if nuevo_saldo > limite:
        disponible = max(limite - customer["balance"], 0)
        return False, (
            f"⚠️ Ese cargo de ${monto:.2f} pasa tu límite de crédito.\n\n"
            f"Saldo pendiente: ${customer['balance']:.2f}\n"
            f"Límite: ${limite:.2f}\n"
            f"Disponible: ${disponible:.2f}\n\n"
            "Liquida lo que debes o pídele al administrador que te suba el límite."
        )
    return True, ""


async def buy_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    if query.data == "buy:cancel":
        await query.edit_message_text("Compra cancelada.")
        return

    # Anti doble clic: dos toques rapidos al mismo boton llegan como dos
    # updates, y antes se procesaban ambos, cobrandole la compra dos veces
    # al cliente. El id del mensaje identifica a ese boton en concreto.
    procesadas = context.user_data.setdefault("compras_procesadas", set())
    msg_id = query.message.message_id
    if msg_id in procesadas:
        await query.answer("Esa compra ya se está procesando.", show_alert=True)
        return
    procesadas.add(msg_id)

    customer = await require_approved(update, context)
    if not customer:
        return

    _, code, qty_str = query.data.split(":")
    qty = int(qty_str)
    product = db.get_product(code)
    if not product or product["price"] is None:
        await query.edit_message_text("Ese producto ya no está disponible.")
        return

    total = product["price"] * qty
    # Se vuelve a revisar el credito con el saldo de este momento: entre que se
    # mostro el boton y se presiono, el cliente pudo haber hecho otros cargos.
    ok, aviso = _cabe_en_el_credito(customer, total)
    if not ok:
        await query.edit_message_text(aviso)
        return

    order_id = api.make_order_id()
    # La orden se registra ANTES de llamar al proveedor: si la llamada se
    # cuelga o el bot se reinicia a media compra, queda el rastro para
    # poder revisarla despues con /orden.
    db.create_order(order_id, user.id, code, qty, total)

    await query.edit_message_text("⏳ Procesando tu compra con el proveedor, un momento...")
    try:
        data = await api.a_buy_key(code, qty, order_id)
    except api.ProviderError as e:
        # Un error aqui NO garantiza que el proveedor no haya surtido las
        # claves (puede ser un timeout con la compra ya hecha de su lado),
        # asi que la orden queda pendiente de revision y no se cobra nada.
        db.update_order(order_id, db.ORDEN_PENDIENTE, error=str(e), charged=False)
        await query.edit_message_text(
            f"❌ Hubo un problema al procesar la compra: {e}\n\n"
            f"No se te hizo ningún cargo. El administrador ya fue avisado.\n"
            f"Número de orden: {order_id}"
        )
        await notify_admins(
            context,
            f"⚠️ Orden sin confirmar\n"
            f"Cliente: @{user.username or user.first_name} (ID {user.id})\n"
            f"Producto: {code} x{qty} — ${total:.2f}\n"
            f"Orden: {order_id}\nError: {e}\n\n"
            f"El proveedor pudo haberla surtido de todos modos. "
            f"Revísala con /orden {order_id}",
        )
        return

    keys = data.get("keys") or data.get("data")
    cobrado = db.add_charge(
        user.id,
        "buy_key",
        {"code": code, "qty": qty, "order_id": order_id, "keys": keys},
        total,
    )
    db.update_order(order_id, db.ORDEN_COMPLETADA, keys=keys, charged=cobrado)

    await query.edit_message_text(
        f"✅ Compra realizada.\n\n{_formatear_claves(keys)}\n\n"
        f"💰 Se agregaron ${total:.2f} a tu cuenta pendiente."
    )
    await notify_admins(
        context,
        f"🛒 Venta\nCliente: @{user.username or user.first_name} (ID {user.id})\n"
        f"Producto: {code} x{qty}\nTotal: ${total:.2f}\nOrden: {order_id}",
    )


async def cid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_approved(update, context):
        return

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
        # El OCR tambien es bloqueante (puede tardar segundos con una foto
        # grande), asi que se va a un hilo para no congelar al bot.
        iid = await asyncio.to_thread(ocr.extract_installation_id, bytes(image_bytes))
    except ocr.OcrUnavailable:
        await update.message.reply_text(
            "⚠️ Todavía no puedo leer fotos en este servidor (falta configurar el lector de texto).\n"
            "Por favor escribe tu Installation ID directamente, así: /cid 123456-123456-123456-..."
        )
        return
    except Exception as e:
        logger.exception("Error procesando la foto del Installation ID")
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
    customer = await require_approved(update, context)
    if not customer:
        return
    user = update.effective_user
    message = update.effective_message

    # El proveedor cuenta caracteres literales (debe ser exactamente 54 o 63),
    # así que le mandamos solo los dígitos, sin guiones ni espacios que el
    # usuario o el OCR hayan puesto para que se vea legible.
    iid_clean = re.sub(r"\D", "", iid)

    if len(iid_clean) not in (54, 63):
        await message.reply_text(
            f"⚠️ Ese Installation ID tiene {len(iid_clean)} dígitos, pero debe tener exactamente "
            f"54 o 63. Revísalo y vuelve a mandarlo con /cid NUMERO (puedes escribirlo con o sin guiones)."
        )
        return

    price = db.get_float_setting("cid_price", 0.0)
    if price > 0:
        ok, aviso = _cabe_en_el_credito(customer, price)
        if not ok:
            await message.reply_text(aviso)
            return

    if not already_announced:
        await message.reply_text("⏳ Consultando tu Confirmation ID...")

    try:
        data = await api.a_get_cid(iid_clean)
    except api.ProviderError as e:
        await message.reply_text(f"❌ No se pudo obtener el CID: {e}")
        return

    cid = data.get("data")
    if not cid:
        # Sin CID no hay servicio prestado, asi que tampoco hay cargo.
        await message.reply_text(
            "❌ El proveedor no devolvió un Confirmation ID. No se te hizo ningún cargo. "
            "Vuelve a intentarlo en un momento."
        )
        return

    db.add_charge(user.id, "get_cid", {"iid": iid_clean, "cid": cid}, price)

    extra = f"\n\n💰 Se agregaron ${price:.2f} a tu cuenta pendiente." if price > 0 else ""
    await message.reply_text(f"🆔 Tu Confirmation ID es:\n\n{cid}{extra}")
