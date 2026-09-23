import asyncio
import logging
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import db
import provider_api as api
import ocr
from config import ADMIN_IDS
from handlers.common import require_approved, reply_long, notify_admins, is_admin

logger = logging.getLogger(__name__)

WELCOME = (
    "👋 Bienvenido.\n\n"
    "Para comprar una clave, manda /productos y toca la que quieras.\n"
    "O más rápido todavía: manda el número del producto, por ejemplo /1\n\n"
    "Lo demás:\n"
    "/cid — sacar tu Confirmation ID\n"
    "/saldo — cuánto debes y cómo pagar\n"
    "/reposicion — si una clave no te sirvió\n"
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


AYUDA_ADMIN = (
    "🛠 Comandos de administrador\n\n"
    "Día a día:\n"
    "/pendientes — solicitudes de acceso por aprobar\n"
    "/reposiciones — reposiciones por resolver\n"
    "/clientes — quién te debe y cuánto\n"
    "/pagar — registrar un pago (te muestra la lista, sin escribir IDs)\n"
    "/cobrar — cargo manual (igual, con lista)\n\n"
    "Catálogo:\n"
    "/refrescarproductos — traer el catálogo del proveedor\n"
    "/catalogo — ver todo con costos y números\n"
    "/precio CODIGO PRECIO — poner precio (le asigna su /1, /2, ...)\n"
    "/preciocid PRECIO — cuánto cobras por un CID\n\n"
    "Clientes:\n"
    "/aprobar ID · /bloquear ID\n"
    "/limite ID MONTO · /limiteglobal MONTO · /maxcantidad N\n"
    "/cliente ID — detalle de uno\n\n"
    "Proveedor:\n"
    "/checkkey CLAVES · /checkredeem CLAVES\n"
    "/admincid IID — CID sin cargarlo a nadie\n"
    "/comprarstock CODIGO CANTIDAD — inventario propio\n"
    "/ordenes · /orden ORDER_ID — compras sin confirmar\n"
)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        await update.message.reply_text(AYUDA_ADMIN)
        return
    await update.message.reply_text(WELCOME)


async def saldo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_customer(user.id, user.username, user.first_name)
    c = db.get_customer(user.id)
    limite = db.effective_credit_limit(c)
    disponible = max(limite - c["balance"], 0)

    texto = (
        f"💰 Tu saldo pendiente es: ${c['balance']:.2f}\n"
        f"🧾 Límite de crédito: ${limite:.2f} (disponible: ${disponible:.2f})"
    )

    if c["balance"] <= 0:
        texto += "\n\n✅ Estás al corriente."

    # Los datos de pago se muestran siempre, aunque no deba nada: así el
    # cliente los tiene a la mano cuando quiera abonar o pagar por
    # adelantado, y no tiene que pedirlos.
    await update.message.reply_text(
        f"{texto}\n\nPara pagar:\n{db.datos_pago()}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("📤 Ya te transferí", callback_data="comp:enviar")]]
        ),
    )


async def comprobante_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """El cliente avisa que ya pagó y manda la foto del comprobante."""
    customer = await require_approved(update, context)
    if not customer:
        return
    context.user_data["awaiting_comprobante"] = True
    await update.message.reply_text(
        "Mándame la foto del comprobante de la transferencia.\n"
        "En cuanto la revise el administrador, se te descuenta del saldo."
    )


async def comprobante_enviar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botón «Ya te transferí» de /saldo."""
    query = update.callback_query
    await query.answer()
    if not await require_approved(update, context):
        return
    context.user_data["awaiting_comprobante"] = True
    await query.edit_message_text(
        "Mándame la foto del comprobante de la transferencia.\n"
        "En cuanto la revise el administrador, se te descuenta del saldo."
    )


async def _recibir_comprobante(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda el comprobante y se lo manda al admin con botones."""
    context.user_data.pop("awaiting_comprobante", None)
    user = update.effective_user
    c = db.get_customer(user.id)
    saldo = c["balance"] if c else 0.0

    file_id = update.message.photo[-1].file_id
    comp_id = db.crear_comprobante(user.id, file_id, saldo)

    await update.message.reply_text(
        "✅ Recibí tu comprobante. En cuanto lo revise el administrador se "
        "te descuenta del saldo y te aviso."
    )

    etiqueta = f"@{user.username}" if user.username else (user.first_name or user.id)
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                admin_id,
                file_id,
                caption=(
                    f"💸 Comprobante de pago #{comp_id}\n"
                    f"Cliente: {etiqueta} (ID {user.id})\n"
                    f"Saldo actual: ${saldo:.2f}"
                ),
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton(
                            f"✅ Liquidó todo (${saldo:.2f})",
                            callback_data=f"comp:{comp_id}:todo",
                        )],
                        [
                            InlineKeyboardButton("✏️ Otro monto", callback_data=f"comp:{comp_id}:otro"),
                            InlineKeyboardButton("❌ Rechazar", callback_data=f"comp:{comp_id}:no"),
                        ],
                    ]
                ),
            )
        except Exception:
            logger.warning("No se pudo mandar el comprobante al admin %s", admin_id, exc_info=True)


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

    rows = db.list_products_a_la_venta()
    if not rows:
        await update.message.reply_text("Todavía no hay productos disponibles. Vuelve a intentar más tarde.")
        return

    lines = ["Toca el producto que quieras, o manda su número (por ejemplo /1):", ""]
    botones = []
    fila = []
    for r in rows:
        n = r["shortcut"]
        nombre = db.nombre_visible(r)
        lines.append(f"/{n} — {nombre} — ${r['price']:.2f}")
        fila.append(InlineKeyboardButton(f"{n}. {nombre}"[:60], callback_data=f"pick:{n}"))
        if len(fila) == 2:
            botones.append(fila)
            fila = []
    if fila:
        botones.append(fila)

    await update.message.reply_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(botones)
    )


async def atajo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Compra por numero corto: el cliente manda /1 y ya.

    Es la forma mas rapida de pedir una clave: no hay que acordarse del
    codigo del proveedor ni escribir cantidades.
    """
    customer = await require_approved(update, context)
    if not customer:
        return

    texto = update.message.text.strip()
    match = re.match(r"^/(\d{1,3})(?:\s+(\d{1,3}))?$", texto)
    if not match:
        return
    n = int(match.group(1))
    qty = int(match.group(2)) if match.group(2) else 1

    product = db.get_product_by_shortcut(n)
    if not product:
        await update.message.reply_text(
            f"No tengo ningún producto con el número {n}. Manda /productos para ver la lista."
        )
        return

    await _pedir_confirmacion(update.message, customer, product, qty)


async def pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toque en un boton del catalogo."""
    query = update.callback_query
    await query.answer()
    customer = await require_approved(update, context)
    if not customer:
        return

    n = int(query.data.split(":")[1])
    product = db.get_product_by_shortcut(n)
    if not product:
        await query.edit_message_text("Ese producto ya no está disponible.")
        return

    await _pedir_confirmacion(query.message, customer, product, 1)


async def _pedir_confirmacion(message, customer, product, qty: int):
    """Muestra producto, precio y como le quedaria el saldo, con un solo boton."""
    max_qty = db.get_int_setting("max_qty", db.DEFAULT_MAX_QTY)
    if qty < 1:
        await message.reply_text("La cantidad debe ser al menos 1.")
        return
    if qty > max_qty:
        await message.reply_text(
            f"⚠️ El máximo por compra es {max_qty}. Si necesitas más, pídeselo al administrador."
        )
        return

    total = product["price"] * qty
    ok, aviso = _cabe_en_el_credito(customer, total)
    if not ok:
        await message.reply_text(aviso)
        return

    cantidad = f"\nCantidad: {qty}" if qty > 1 else ""
    await message.reply_text(
        f"📦 {db.nombre_visible(product)} — ${product['price']:.2f}{cantidad}\n"
        f"Total: ${total:.2f}\n"
        f"Tu saldo quedaría en ${customer['balance'] + total:.2f}",
        reply_markup=InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Sí, cómprala", callback_data=f"buy:{product['code']}:{qty}"),
                InlineKeyboardButton("❌ No", callback_data="buy:cancel"),
            ]]
        ),
    )


async def comprar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Compra por codigo o por numero corto. Se conserva por costumbre, pero
    lo normal es que el cliente use /productos o el atajo /1."""
    customer = await require_approved(update, context)
    if not customer:
        return

    if not context.args:
        await update.message.reply_text(
            "Manda /productos para ver la lista y tocar lo que quieras,\n"
            "o el número del producto directo, por ejemplo /1"
        )
        return

    pedido = context.args[0]
    qty = 1
    if len(context.args) > 1:
        try:
            qty = int(context.args[1])
        except ValueError:
            await update.message.reply_text("La cantidad debe ser un número entero.")
            return

    product = db.get_product(pedido)
    if not product and pedido.isdigit():
        product = db.get_product_by_shortcut(int(pedido))
    if not product or product["price"] is None:
        await update.message.reply_text(
            "No encontré ese producto. Manda /productos para ver la lista."
        )
        return

    await _pedir_confirmacion(update.message, customer, product, qty)


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
    """Texto suelto: solo significa algo si el bot esta esperando un dato."""
    # Import local para no crear un ciclo entre customer y admin.
    from handlers import admin

    if await admin.monto_texto_handler(update, context):
        return

    if context.user_data.get("awaiting_iid"):
        context.user_data["awaiting_iid"] = False
        await _process_cid(update, context, update.message.text)
        return

    if context.user_data.get("repo_order_id"):
        await _registrar_reposicion(update, context, update.message.text)
        return

    # Si pegan un Installation ID sin mandar /cid antes, se entiende igual.
    digitos = re.sub(r"\D", "", update.message.text or "")
    if len(digitos) in (54, 63):
        await _process_cid(update, context, digitos)


async def generic_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cualquier foto de un cliente aprobado se intenta leer como Installation ID.

    Antes había que mandar /cid primero y luego la foto; en la práctica el
    cliente manda la foto y ya. Ahora eso funciona.
    """
    customer = await require_approved(update, context)
    if not customer:
        return

    # Una foto puede ser dos cosas muy distintas: el comprobante de una
    # transferencia o la pantalla con el Installation ID. Se distingue por
    # lo que el cliente pidió justo antes.
    if context.user_data.get("awaiting_comprobante"):
        await _recibir_comprobante(update, context)
        return

    context.user_data.pop("awaiting_iid", None)

    aviso = await update.message.reply_text("🔍 Leyendo la foto...")

    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        image_bytes = await file.download_as_bytearray()
        # El OCR es bloqueante y puede tardar segundos con una foto grande,
        # así que se va a un hilo para no congelar al bot.
        iid = await asyncio.to_thread(ocr.extract_installation_id, bytes(image_bytes))
    except ocr.OcrUnavailable:
        await aviso.edit_text(
            "⚠️ No puedo leer fotos en este servidor (falta el lector de texto).\n"
            "Mándame el Installation ID escrito y listo."
        )
        return
    except Exception as e:
        logger.exception("Error procesando la foto del Installation ID")
        await aviso.edit_text(
            f"❌ Hubo un problema leyendo la foto ({e}).\n"
            "Mándame el Installation ID escrito y listo."
        )
        return

    if not iid:
        await aviso.edit_text(
            "😕 No pude leer los números en esa foto.\n\n"
            "Puedes mandar otra foto (de frente, sin sombra encima y que se "
            "vean los 9 grupos completos), o escribirme el Installation ID."
        )
        return

    digitos = re.sub(r"\D", "", iid)
    if len(digitos) not in (54, 63):
        # No se manda al proveedor una lectura incompleta: cada consulta gasta
        # cupo y de todos modos la rechazaría.
        await aviso.edit_text(
            f"😕 Leí algo, pero incompleto ({len(digitos)} dígitos de 54 o 63):\n\n"
            f"{iid}\n\n"
            "Manda otra foto más clara, o escríbeme el Installation ID."
        )
        return

    context.user_data["iid_leido"] = digitos
    await aviso.edit_text(
        f"Leí esto de la foto:\n\n{iid}\n\n¿Está bien?",
        reply_markup=InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Sí, es correcto", callback_data="cid:ok"),
                InlineKeyboardButton("✏️ Lo escribo yo", callback_data="cid:no"),
            ]]
        ),
    )


async def cid_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """El cliente confirma (o corrige) lo que se leyó de la foto."""
    query = update.callback_query
    await query.answer()
    if not await require_approved(update, context):
        return

    if query.data == "cid:no":
        context.user_data.pop("iid_leido", None)
        context.user_data["awaiting_iid"] = True
        await query.edit_message_text(
            "Va. Escríbeme el Installation ID (con guiones o sin ellos, como te sea más fácil)."
        )
        return

    iid = context.user_data.pop("iid_leido", None)
    if not iid:
        await query.edit_message_text("Se me perdió el número. Mándame la foto otra vez, por favor.")
        return

    await query.edit_message_text("⏳ Consultando tu Confirmation ID...")
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

    cargo = f" — ${price:.2f}" if price > 0 else " — sin cargo"
    await notify_admins(
        context,
        f"🆔 CID generado{cargo}\n"
        f"Cliente: @{user.username or user.first_name} (ID {user.id})\n"
        f"Saldo ahora: ${db.get_customer(user.id)['balance']:.2f}",
    )


# --------------------------------------------------------------------------
# Reposición de claves
# --------------------------------------------------------------------------

async def reposicion_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """El cliente pide el cambio de una clave que no le sirvio."""
    customer = await require_approved(update, context)
    if not customer:
        return

    compras = db.compras_del_cliente(update.effective_user.id, limit=8)
    if not compras:
        await update.message.reply_text(
            "No tengo compras tuyas registradas todavía, así que no hay nada que reponer."
        )
        return

    botones = [
        [InlineKeyboardButton(
            f"{o['code']} — {o['created_at'][:10]}",
            callback_data=f"repo:{o['order_id']}",
        )]
        for o in compras
    ]
    await update.message.reply_text(
        "¿Cuál clave no te sirvió? Toca la compra:",
        reply_markup=InlineKeyboardMarkup(botones),
    )


async def reposicion_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await require_approved(update, context):
        return

    order_id = query.data.split(":", 1)[1]
    orden = db.get_order(order_id)
    if not orden or orden["telegram_id"] != update.effective_user.id:
        await query.edit_message_text("No encontré esa compra.")
        return

    context.user_data["repo_order_id"] = order_id
    await query.edit_message_text(
        f"Compra: {orden['code']} del {orden['created_at'][:10]}\n\n"
        "Escríbeme qué pasó con la clave (por ejemplo: \"dice que ya fue usada\").\n"
        "Eso es lo que va a leer el administrador."
    )


async def _registrar_reposicion(update: Update, context: ContextTypes.DEFAULT_TYPE, motivo: str):
    """Guarda la solicitud y se la manda al admin con botones."""
    order_id = context.user_data.pop("repo_order_id", None)
    user = update.effective_user
    orden = db.get_order(order_id) if order_id else None
    if not orden:
        await update.message.reply_text("Se me perdió la referencia de la compra. Vuelve a mandar /reposicion.")
        return

    repo_id = db.crear_reposicion(user.id, order_id, orden["code"], motivo.strip())

    await update.message.reply_text(
        "✅ Solicitud enviada. El administrador la va a revisar y te avisa en cuanto la resuelva."
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"⚠️ Solicitud de reposición #{repo_id}\n"
                f"Cliente: @{user.username or user.first_name} (ID {user.id})\n"
                f"Producto: {orden['code']}\n"
                f"Compra: {order_id} ({orden['created_at'][:10]})\n\n"
                f"Motivo: {motivo.strip()}",
                reply_markup=InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton("✅ Aprobar", callback_data=f"repook:{repo_id}"),
                        InlineKeyboardButton("❌ Rechazar", callback_data=f"repono:{repo_id}"),
                    ]]
                ),
            )
        except Exception:
            logger.warning("No se pudo avisar al admin %s de la reposición", admin_id, exc_info=True)
