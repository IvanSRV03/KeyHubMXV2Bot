import logging

from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import config
import db
from handlers import admin, customer

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Registra cualquier excepcion no capturada y le avisa al usuario.

    Sin esto, un error inesperado dejaba al cliente esperando una respuesta
    que nunca llegaba, y el problema solo se veia en los logs de Railway.
    """
    logger.exception("Error no capturado procesando un update", exc_info=context.error)

    message = getattr(update, "effective_message", None)
    if message is None:
        return
    try:
        await message.reply_text(
            "❌ Algo salió mal de mi lado. Ya quedó registrado; intenta de nuevo en un momento."
        )
    except Exception:
        logger.warning("Tampoco se pudo avisar del error al usuario", exc_info=True)


def main():
    if not config.BOT_TOKEN:
        raise SystemExit("Falta la variable de entorno BOT_TOKEN.")
    if not config.PROVIDER_TOKEN:
        raise SystemExit("Falta la variable de entorno PROVIDER_TOKEN.")
    if not config.ADMIN_IDS:
        logger.warning("No configuraste ADMIN_IDS. Nadie va a poder usar los comandos de administrador.")

    db.init_db()

    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Comandos generales / clientes
    app.add_handler(CommandHandler("start", customer.start_cmd))
    app.add_handler(CommandHandler("help", customer.help_cmd))
    app.add_handler(CommandHandler("saldo", customer.saldo_cmd))
    app.add_handler(CommandHandler("historial", customer.historial_cmd))
    app.add_handler(CommandHandler("productos", customer.productos_cmd))
    app.add_handler(CommandHandler("comprar", customer.comprar_cmd))
    app.add_handler(CommandHandler("cid", customer.cid_cmd))

    # Comandos de administrador
    app.add_handler(CommandHandler("checkkey", admin.checkkey_cmd))
    app.add_handler(CommandHandler("checkredeem", admin.checkredeem_cmd))
    app.add_handler(CommandHandler("admincid", admin.admincid_cmd))
    app.add_handler(CommandHandler("refrescarproductos", admin.refresh_products_cmd))
    app.add_handler(CommandHandler("catalogo", admin.catalogo_cmd))
    app.add_handler(CommandHandler("precio", admin.set_price_cmd))
    app.add_handler(CommandHandler("preciocid", admin.set_cid_price_cmd))
    app.add_handler(CommandHandler("clientes", admin.clientes_cmd))
    app.add_handler(CommandHandler("cliente", admin.cliente_cmd))
    app.add_handler(CommandHandler("cobrar", admin.cobrar_cmd))
    app.add_handler(CommandHandler("pagar", admin.pagar_cmd))
    app.add_handler(CommandHandler("comprarstock", admin.buy_stock_cmd))

    # Control de acceso de clientes
    app.add_handler(CommandHandler("pendientes", admin.pendientes_cmd))
    app.add_handler(CommandHandler("aprobar", admin.aprobar_cmd))
    app.add_handler(CommandHandler("bloquear", admin.bloquear_cmd))
    app.add_handler(CommandHandler("limite", admin.limite_cmd))
    app.add_handler(CommandHandler("limiteglobal", admin.limite_global_cmd))
    app.add_handler(CommandHandler("maxcantidad", admin.max_cantidad_cmd))

    # Botones inline (confirmar/cancelar compra)
    app.add_handler(CallbackQueryHandler(customer.buy_confirm_callback, pattern=r"^buy:"))

    # Mensajes libres (para el flujo de /cid cuando se espera el Installation ID)
    app.add_handler(MessageHandler(filters.PHOTO, customer.generic_photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, customer.generic_text_handler))

    app.add_error_handler(error_handler)

    logger.info("Bot iniciado, esperando mensajes...")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
