from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import db
import provider_api as api
from handlers import customer
from handlers.common import is_admin, reply_long

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
        data = await api.a_check_keys(keys)
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
    await reply_long(update, lines)


async def checkredeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /checkredeem CLAVE1 CLAVE2 ...")
        return
    keys = ",".join(context.args)
    try:
        data = await api.a_check_redeem(keys)
    except api.ProviderError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    lines = []
    for r in data.get("results", []):
        lines.append(
            f"🔑 {r.get('Key')}\n📝 {r.get('Description')}\n🎁 {r.get('ErrorCode')}\n⏰ {r.get('Time')}"
        )
    lines.append(f"\nUsadas hoy: {data.get('used')} / {data.get('limit')} (restantes: {data.get('remaining')})")
    await reply_long(update, lines)


async def admincid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obtiene un CID sin cargarlo a la cuenta de ningún cliente (uso interno)."""
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /admincid INSTALLATION_ID")
        return
    iid = " ".join(context.args)
    try:
        data = await api.a_get_cid(iid)
    except api.ProviderError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    await update.message.reply_text(f"🆔 CID: {data.get('data')}")


async def refresh_products_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    try:
        data = await api.a_key_products()
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


async def catalogo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista TODOS los productos guardados (tengan precio de venta o no), para que el admin decida precios."""
    if not await _guard(update):
        return
    rows = db.list_products()
    if not rows:
        await update.message.reply_text("No hay productos guardados. Corre /refrescarproductos primero.")
        return

    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"] or "Otros", []).append(r)

    chunks = []
    current = ""
    for cat, items in by_cat.items():
        block = f"\n📁 {cat}\n"
        for it in items:
            precio = f"${it['price']:.2f}" if it["price"] is not None else "sin precio"
            costo = f"${it['cost']:.2f}" if it["cost"] is not None else "?"
            atajo = f"/{it['shortcut']} " if it["shortcut"] else "    "
            block += f"  {atajo}{it['code']} — {it['name']} (costo prov.: {costo}, venta: {precio})\n"
        if len(current) + len(block) > 3500:
            chunks.append(current)
            current = block
        else:
            current += block
    if current:
        chunks.append(current)

    for i, c in enumerate(chunks):
        header = f"Catálogo ({i + 1}/{len(chunks)}):\n" if len(chunks) > 1 else "Catálogo:\n"
        await update.message.reply_text(header + c)


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
    n = db.set_product_price(code, price)
    await update.message.reply_text(
        f"Precio actualizado: {code} → ${price:.2f}\n"
        f"Tus clientes ya lo pueden comprar mandando /{n}"
    )


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
        marca = {db.PENDIENTE: "⏳", db.BLOQUEADO: "⛔"}.get(r["status"], "✅")
        lines.append(f"{marca} @{nombre} (ID {r['telegram_id']}) — ${r['balance']:.2f}")
    await reply_long(update, lines, header="Clientes")


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
    if not context.args:
        await _lista_para_cobrar(
            update, "chg", "¿A quién le vas a cobrar? Toca su nombre:", solo_con_adeudo=False
        )
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Manda /cobrar solo, sin nada más, y te muestro la lista de clientes."
        )
        return
    try:
        tid = int(context.args[0])
        monto = float(context.args[1])
    except ValueError:
        await update.message.reply_text("El ID y el monto deben ser numéricos.")
        return
    concepto = " ".join(context.args[2:]) or "cargo manual"
    if not db.add_charge(tid, "charge", {"concepto": concepto}, monto):
        await update.message.reply_text(
            f"❌ No hay ningún cliente con el ID {tid}, así que no se hizo el cargo.\n"
            "Revisa el ID con /clientes."
        )
        return
    c = db.get_customer(tid)
    await update.message.reply_text(
        f"Se agregó ${monto:.2f} al saldo de {tid} ({concepto}). Nuevo saldo: ${c['balance']:.2f}"
    )


async def pagar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if not context.args:
        await _lista_para_cobrar(
            update, "pay", "¿Quién te pagó? Toca su nombre:", solo_con_adeudo=True
        )
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Manda /pagar solo, sin nada más, y te muestro la lista de quién te debe."
        )
        return
    try:
        tid = int(context.args[0])
        monto = float(context.args[1])
    except ValueError:
        await update.message.reply_text("El ID y el monto deben ser numéricos.")
        return
    if not db.add_payment(tid, monto, note="pago registrado por admin"):
        await update.message.reply_text(
            f"❌ No hay ningún cliente con el ID {tid}, así que no se registró el pago.\n"
            "Revisa el ID con /clientes."
        )
        return
    c = db.get_customer(tid)
    await update.message.reply_text(f"Pago registrado. Nuevo saldo de {tid}: ${c['balance']:.2f}")


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
    if qty <= 0:
        await update.message.reply_text("La cantidad debe ser mayor a 0.")
        return

    order_id = api.make_order_id()
    db.create_order(order_id, None, code, qty, 0.0)
    await update.message.reply_text(f"⏳ Comprando al proveedor... (orden {order_id})")
    try:
        data = await api.a_buy_key(code, qty, order_id)
    except api.ProviderError as e:
        db.update_order(order_id, db.ORDEN_PENDIENTE, error=str(e), charged=False)
        await update.message.reply_text(
            f"❌ {e}\nOrden: {order_id} — el proveedor pudo haberla surtido de todos "
            f"modos. Revísala con /orden {order_id}"
        )
        return

    keys = data.get("data") or data.get("keys")
    db.update_order(order_id, db.ORDEN_COMPLETADA, keys=keys, charged=False)
    await update.message.reply_text(
        f"✅ Compra al proveedor completada.\nOrden: {order_id}\n\n{keys}"
    )


# --------------------------------------------------------------------------
# Control de acceso de clientes
# --------------------------------------------------------------------------

async def _avisar_cliente(context: ContextTypes.DEFAULT_TYPE, telegram_id: int, texto: str):
    """Le avisa al cliente de un cambio en su cuenta, sin romperse si bloqueó al bot."""
    try:
        await context.bot.send_message(telegram_id, texto)
        return True
    except Exception:
        return False


async def pendientes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista las solicitudes de acceso que faltan por resolver."""
    if not await _guard(update):
        return
    rows = db.list_customers(status=db.PENDIENTE)
    if not rows:
        await update.message.reply_text("No hay solicitudes pendientes. ✅")
        return
    lines = []
    for r in rows:
        nombre = r["username"] or r["first_name"] or str(r["telegram_id"])
        lines.append(f"⏳ @{nombre} (ID {r['telegram_id']}) — desde {r['created_at'][:10]}")
    lines.append("\nPara aprobar: /aprobar ID    Para rechazar: /bloquear ID")
    await reply_long(update, lines, header="Solicitudes pendientes")


async def aprobar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /aprobar TELEGRAM_ID  (usa /pendientes para ver las solicitudes)")
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El ID debe ser numérico.")
        return

    if not db.set_customer_status(tid, db.APROBADO):
        await update.message.reply_text(
            f"No hay ningún cliente con el ID {tid}. Tiene que mandarle /start al bot primero."
        )
        return

    avisado = await _avisar_cliente(
        context,
        tid,
        "✅ Tu cuenta fue aprobada. Ya puedes usar el bot:\n"
        "/productos para ver el catálogo\n"
        "/comprar CODIGO CANTIDAD para comprar\n"
        "/cid para obtener un Confirmation ID",
    )
    extra = "" if avisado else "\n(No le pude avisar por Telegram — quizá bloqueó al bot.)"
    await update.message.reply_text(f"Cliente {tid} aprobado.{extra}")


async def bloquear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /bloquear TELEGRAM_ID")
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El ID debe ser numérico.")
        return

    if not db.set_customer_status(tid, db.BLOQUEADO):
        await update.message.reply_text(f"No hay ningún cliente con el ID {tid}.")
        return

    c = db.get_customer(tid)
    aviso = ""
    if c and c["balance"] > 0:
        aviso = f"\n⚠️ Ojo: ese cliente todavía te debe ${c['balance']:.2f}."
    await update.message.reply_text(f"Cliente {tid} bloqueado. Ya no puede comprar ni pedir CIDs.{aviso}")


async def limite_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fija el límite de crédito de un cliente. 'global' lo regresa al límite general."""
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Uso: /limite TELEGRAM_ID MONTO\n"
            "     /limite TELEGRAM_ID global   → que use el límite general"
        )
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El ID debe ser numérico.")
        return

    c = db.get_customer(tid)
    if not c:
        await update.message.reply_text(f"No hay ningún cliente con el ID {tid}.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            f"Límite actual de {tid}: ${db.effective_credit_limit(c):.2f}"
            + (" (usa el límite general)" if c["credit_limit"] is None else " (propio)")
        )
        return

    valor = context.args[1].lower()
    if valor in ("global", "general", "default"):
        db.set_credit_limit(tid, None)
        await update.message.reply_text(
            f"Cliente {tid} ahora usa el límite general (${db.get_float_setting('credit_limit_default', db.DEFAULT_CREDIT_LIMIT):.2f})."
        )
        return

    try:
        monto = float(valor)
    except ValueError:
        await update.message.reply_text("El monto debe ser un número (o la palabra 'global').")
        return
    if monto < 0:
        await update.message.reply_text("El límite no puede ser negativo.")
        return

    db.set_credit_limit(tid, monto)
    await update.message.reply_text(f"Límite de crédito de {tid} → ${monto:.2f}")


async def limite_global_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Límite de crédito que aplica a los clientes que no tienen uno propio."""
    if not await _guard(update):
        return
    actual = db.get_float_setting("credit_limit_default", db.DEFAULT_CREDIT_LIMIT)
    if not context.args:
        await update.message.reply_text(
            f"Límite de crédito general: ${actual:.2f}\nUso: /limiteglobal MONTO"
        )
        return
    try:
        monto = float(context.args[0])
    except ValueError:
        await update.message.reply_text("El monto debe ser un número.")
        return
    if monto < 0:
        await update.message.reply_text("El límite no puede ser negativo.")
        return
    db.set_setting("credit_limit_default", monto)
    await update.message.reply_text(f"Límite de crédito general → ${monto:.2f}")


async def max_cantidad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tope de unidades que un cliente puede pedir en una sola compra."""
    if not await _guard(update):
        return
    actual = db.get_int_setting("max_qty", db.DEFAULT_MAX_QTY)
    if not context.args:
        await update.message.reply_text(
            f"Máximo de unidades por compra: {actual}\nUso: /maxcantidad NUMERO"
        )
        return
    try:
        n = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Tiene que ser un número entero.")
        return
    if n < 1:
        await update.message.reply_text("El máximo tiene que ser al menos 1.")
        return
    db.set_setting("max_qty", n)
    await update.message.reply_text(f"Máximo por compra → {n} unidades")


# --------------------------------------------------------------------------
# Órdenes al proveedor
# --------------------------------------------------------------------------

def _resumen_orden(o) -> str:
    quien = f"cliente {o['telegram_id']}" if o["telegram_id"] else "stock propio"
    marca = {
        db.ORDEN_PENDIENTE: "⏳",
        db.ORDEN_COMPLETADA: "✅",
        db.ORDEN_FALLIDA: "❌",
    }.get(o["status"], "•")
    linea = f"{marca} {o['order_id']} — {o['code']} x{o['qty']} — {quien} — {o['created_at'][:19]}"
    if o["status"] == db.ORDEN_PENDIENTE and o["error"]:
        linea += f"\n    error: {o['error'][:120]}"
    return linea


async def ordenes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Órdenes que quedaron sin confirmar (o las últimas, con /ordenes todas)."""
    if not await _guard(update):
        return

    todas = bool(context.args) and context.args[0].lower() in ("todas", "all")
    rows = db.list_orders(status=None if todas else db.ORDEN_PENDIENTE, limit=30)

    if not rows:
        await update.message.reply_text(
            "No hay órdenes sin confirmar. ✅" if not todas else "No hay órdenes registradas."
        )
        return

    lines = [_resumen_orden(o) for o in rows]
    lines.append("\nPara consultarla con el proveedor: /orden ORDER_ID")
    await reply_long(update, lines, header="Órdenes" if todas else "Órdenes sin confirmar")


async def orden_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Consulta con el proveedor qué pasó con una orden y actualiza su estado."""
    if not await _guard(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /orden ORDER_ID  (usa /ordenes para ver las pendientes)")
        return

    order_id = context.args[0]
    local = db.get_order(order_id)

    await update.message.reply_text("⏳ Consultando la orden con el proveedor...")
    try:
        data = await api.a_buy_key_order_status(order_id)
    except api.ProviderError as e:
        aviso = f"❌ El proveedor no pudo darme el estado: {e}"
        if local:
            aviso += f"\n\nLo que tengo guardado:\n{_resumen_orden(local)}"
        await update.message.reply_text(aviso)
        return

    keys = data.get("keys") or data.get("data")
    lines = [f"Orden {order_id}", f"Respuesta del proveedor: {keys}"]

    if local:
        lines.append("")
        lines.append(_resumen_orden(local))
        if local["status"] == db.ORDEN_PENDIENTE and keys:
            # El proveedor si la surtio: se marca como completada. El cobro al
            # cliente no se hace automatico a proposito — decides tu, porque
            # ya le dijimos que no se le habia cobrado.
            db.update_order(order_id, db.ORDEN_COMPLETADA, keys=keys)
            lines.append("")
            lines.append("✅ Marcada como completada.")
            if local["telegram_id"] and not local["charged"]:
                lines.append(
                    f"⚠️ A este cliente NO se le cobró (se le avisó que la compra había fallado).\n"
                    f"Si le vas a pasar las claves, cóbraselo con:\n"
                    f"/cobrar {local['telegram_id']} {local['total']:.2f} orden {order_id}"
                )
    else:
        lines.append("\n(No tengo esa orden registrada localmente.)")

    await reply_long(update, lines)


# --------------------------------------------------------------------------
# Reposiciones de clave
# --------------------------------------------------------------------------

async def reposiciones_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Solicitudes de reposición sin resolver."""
    if not await _guard(update):
        return
    rows = db.list_reposiciones(status=db.REPO_SOLICITADA)
    if not rows:
        await update.message.reply_text("No hay reposiciones pendientes. ✅")
        return
    for r in rows:
        c = db.get_customer(r["telegram_id"])
        quien = (c["username"] or c["first_name"]) if c else r["telegram_id"]
        await update.message.reply_text(
            f"⚠️ Reposición #{r['id']}\n"
            f"Cliente: @{quien} (ID {r['telegram_id']})\n"
            f"Producto: {r['code']}\n"
            f"Compra: {r['order_id']}\n\n"
            f"Motivo: {r['motivo']}",
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton("✅ Aprobar", callback_data=f"repook:{r['id']}"),
                    InlineKeyboardButton("❌ Rechazar", callback_data=f"repono:{r['id']}"),
                ]]
            ),
        )


async def reposicion_resolver_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Aprobar o rechazar una reposición desde el botón del aviso."""
    query = update.callback_query
    await query.answer()

    if not is_admin(update.effective_user.id):
        await query.edit_message_text("⛔ Solo un administrador puede resolver reposiciones.")
        return

    accion, repo_id = query.data.split(":")
    repo = db.get_reposicion(int(repo_id))
    if not repo:
        await query.edit_message_text("No encontré esa solicitud.")
        return
    if repo["status"] != db.REPO_SOLICITADA:
        await query.edit_message_text(f"Esa reposición ya estaba {repo['status']}.")
        return

    if accion == "repono":
        db.resolver_reposicion(repo["id"], db.REPO_RECHAZADA)
        await query.edit_message_text(f"Reposición #{repo['id']} rechazada.")
        await _avisar_cliente(
            context,
            repo["telegram_id"],
            f"Tu solicitud de reposición de {repo['code']} fue rechazada. "
            "Si tienes dudas, escríbele al administrador.",
        )
        return

    # Aprobada: se le compra otra clave al proveedor, sin cargo para el cliente.
    order_id = api.make_order_id()
    db.create_order(order_id, repo["telegram_id"], repo["code"], 1, 0.0)
    await query.edit_message_text(
        f"⏳ Reposición #{repo['id']} aprobada. Comprando la clave de reemplazo..."
    )

    try:
        data = await api.a_buy_key(repo["code"], 1, order_id)
    except api.ProviderError as e:
        db.update_order(order_id, db.ORDEN_PENDIENTE, error=str(e), charged=False)
        await query.edit_message_text(
            f"❌ No se pudo comprar la clave de reemplazo: {e}\n"
            f"La reposición #{repo['id']} sigue pendiente. Orden: {order_id}\n"
            f"Revísala con /orden {order_id} y vuelve a intentar con /reposiciones."
        )
        return

    keys = data.get("keys") or data.get("data")
    db.update_order(order_id, db.ORDEN_COMPLETADA, keys=keys, charged=False)
    db.resolver_reposicion(repo["id"], db.REPO_APROBADA, nueva_order_id=order_id)
    # No se le cobra nada al cliente: la reposición va por tu cuenta.
    db.add_charge(
        repo["telegram_id"],
        "reposicion",
        {"repo_id": repo["id"], "code": repo["code"], "order_id": order_id},
        0.0,
    )

    entregada = await _avisar_cliente(
        context,
        repo["telegram_id"],
        f"✅ Tu reposición de {repo['code']} fue aprobada. Aquí está tu clave nueva:\n\n"
        f"{customer._formatear_claves(keys)}\n\n"
        "Sin costo — no se te hizo ningún cargo.",
    )
    extra = "" if entregada else "\n⚠️ No le pude entregar la clave por Telegram, pásasela tú."
    await query.edit_message_text(
        f"✅ Reposición #{repo['id']} resuelta.\nOrden: {order_id}\n\n{keys}{extra}"
    )


# --------------------------------------------------------------------------
# Cobros y pagos con botones
# --------------------------------------------------------------------------

async def _lista_para_cobrar(update: Update, prefijo: str, titulo: str, solo_con_adeudo: bool):
    rows = db.clientes_con_adeudo() if solo_con_adeudo else db.list_customers()
    if not rows:
        await update.message.reply_text(
            "Ningún cliente te debe nada. 🎉" if solo_con_adeudo else "No hay clientes registrados."
        )
        return
    botones = [
        [InlineKeyboardButton(
            f"@{r['username'] or r['first_name'] or r['telegram_id']} — ${r['balance']:.2f}",
            callback_data=f"{prefijo}:{r['telegram_id']}",
        )]
        for r in rows[:20]
    ]
    await update.message.reply_text(titulo, reply_markup=InlineKeyboardMarkup(botones))


async def pagar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registrar un pago sin tener que escribir IDs ni montos a mano."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        await query.edit_message_text("⛔ Solo para administradores.")
        return

    partes = query.data.split(":")
    tid = int(partes[1])
    c = db.get_customer(tid)
    if not c:
        await query.edit_message_text("Ese cliente ya no existe.")
        return
    nombre = c["username"] or c["first_name"] or tid

    # Paso 1: se eligió al cliente, se ofrecen las opciones de pago.
    if len(partes) == 2:
        await query.edit_message_text(
            f"@{nombre} debe ${c['balance']:.2f}\n¿Cuánto te pagó?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton(
                        f"💵 Liquidó todo (${c['balance']:.2f})",
                        callback_data=f"pay:{tid}:todo",
                    )],
                    [InlineKeyboardButton("✏️ Otro monto", callback_data=f"pay:{tid}:otro")],
                ]
            ),
        )
        return

    # Paso 2: monto.
    if partes[2] == "otro":
        context.user_data["pago_pendiente_de"] = tid
        await query.edit_message_text(
            f"Escríbeme cuánto te pagó @{nombre} (solo el número, por ejemplo 250.50)."
        )
        return

    monto = c["balance"]
    if monto <= 0:
        await query.edit_message_text(f"@{nombre} no debe nada.")
        return
    db.add_payment(tid, monto, note="liquidación registrada por admin")
    nuevo = db.get_customer(tid)["balance"]
    await query.edit_message_text(
        f"✅ Pago de ${monto:.2f} registrado.\n@{nombre} ahora debe ${nuevo:.2f}"
    )
    await _avisar_cliente(
        context, tid, f"✅ Se registró tu pago de ${monto:.2f}. Tu saldo ahora es ${nuevo:.2f}"
    )


async def monto_texto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Si el admin está escribiendo el monto de un pago, lo procesa.

    Devuelve True si consumió el mensaje, para que el manejador de texto
    libre no lo trate como otra cosa.
    """
    es_pago = "pago_pendiente_de" in context.user_data
    es_cobro = "cobro_pendiente_de" in context.user_data
    if not (es_pago or es_cobro):
        return False

    clave = "pago_pendiente_de" if es_pago else "cobro_pendiente_de"
    tid = context.user_data[clave]

    try:
        monto = float(update.message.text.strip().replace("$", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("No le entendí. Mándame solo el número, por ejemplo 250.50")
        return True

    context.user_data.pop(clave, None)
    if monto <= 0:
        await update.message.reply_text("El monto tiene que ser mayor a 0.")
        return True

    if es_pago:
        aplicado = db.add_payment(tid, monto, note="pago registrado por admin")
    else:
        aplicado = db.add_charge(tid, "charge", {"concepto": "cargo manual"}, monto)

    if not aplicado:
        await update.message.reply_text("Ese cliente ya no existe.")
        return True

    c = db.get_customer(tid)
    nombre = c["username"] or c["first_name"] or tid
    if es_pago:
        await update.message.reply_text(
            f"✅ Pago de ${monto:.2f} registrado.\n@{nombre} ahora debe ${c['balance']:.2f}"
        )
        await _avisar_cliente(
            context, tid,
            f"✅ Se registró tu pago de ${monto:.2f}. Tu saldo ahora es ${c['balance']:.2f}",
        )
    else:
        await update.message.reply_text(
            f"✅ Cargo de ${monto:.2f} aplicado.\n@{nombre} ahora debe ${c['balance']:.2f}"
        )
        await _avisar_cliente(
            context, tid,
            f"Se agregó un cargo de ${monto:.2f} a tu cuenta. Tu saldo ahora es ${c['balance']:.2f}",
        )
    return True


async def cobrar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Elegir al cliente al que se le va a cobrar, sin escribir su ID."""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        await query.edit_message_text("⛔ Solo para administradores.")
        return

    tid = int(query.data.split(":")[1])
    c = db.get_customer(tid)
    if not c:
        await query.edit_message_text("Ese cliente ya no existe.")
        return

    context.user_data["cobro_pendiente_de"] = tid
    nombre = c["username"] or c["first_name"] or tid
    await query.edit_message_text(
        f"@{nombre} debe ${c['balance']:.2f}\n"
        "¿Cuánto le vas a cobrar? Mándame solo el número."
    )
