import logging

from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
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


# Lo que ve el cliente al tocar el botón de menú en Telegram. Se deja corto
# a propósito: entre menos opciones, menos dudas.
COMANDOS_CLIENTE = [
    BotCommand("productos", "Ver el catálogo y comprar"),
    BotCommand("cid", "Sacar mi Confirmation ID"),
    BotCommand("saldo", "Ver cuánto debo"),
    BotCommand("reposicion", "Una clave no me sirvió"),
    BotCommand("historial", "Mis últimos movimientos"),
]

COMANDOS_ADMIN = COMANDOS_CLIENTE + [
    BotCommand("pendientes", "Solicitudes de acceso"),
    BotCommand("reposiciones", "Reposiciones por resolver"),
    BotCommand("clientes", "Quién me debe"),
    BotCommand("pagar", "Registrar un pago"),
    BotCommand("cobrar", "Cargo manual"),
    BotCommand("catalogo", "Catálogo con costos"),
    BotCommand("ordenes", "Compras sin confirmar"),
    BotCommand("help", "Todos mis comandos"),
]


async def _publicar_menu(app):
    """Registra el menú de comandos que Telegram le muestra a cada quien.

    Así el cliente no tiene que aprenderse nada: toca el botón de menú y ve
    lo que puede hacer.
    """
    try:
        await app.bot.set_my_commands(COMANDOS_CLIENTE, scope=BotCommandScopeDefault())
        for admin_id in config.ADMIN_IDS:
            await app.bot.set_my_commands(
                COMANDOS_ADMIN, scope=BotCommandScopeChat(chat_id=admin_id)
            )
        logger.info("Menú de comandos publicado")
    except Exception:
        # Que falle el menú no debe impedir que el bot arranque.
        logger.warning("No se pudo publicar el menú de comandos", exc_info=True)


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

    app = ApplicationBuilder().token(config.BOT_TOKEN).post_init(_publicar_menu).build()

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
    app.add_handler(CommandHandler("ocultar", admin.ocultar_cmd))
    app.add_handler(CommandHandler("nombre", admin.nombre_cmd))
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

    # Ordenes al proveedor
    app.add_handler(CommandHandler("ordenes", admin.ordenes_cmd))
    app.add_handler(CommandHandler("orden", admin.orden_cmd))

    # Reposiciones
    app.add_handler(CommandHandler("reposicion", customer.reposicion_cmd))
    app.add_handler(CommandHandler("reposiciones", admin.reposiciones_cmd))

    # Botones inline
    app.add_handler(CallbackQueryHandler(customer.buy_confirm_callback, pattern=r"^buy:"))
    app.add_handler(CallbackQueryHandler(customer.pick_callback, pattern=r"^pick:"))
    app.add_handler(CallbackQueryHandler(customer.reposicion_pick_callback, pattern=r"^repo:"))
    app.add_handler(CallbackQueryHandler(admin.reposicion_resolver_callback, pattern=r"^repo(ok|no):"))
    app.add_handler(CallbackQueryHandler(admin.pagar_callback, pattern=r"^pay:"))
    app.add_handler(CallbackQueryHandler(admin.cobrar_callback, pattern=r"^chg:"))
    app.add_handler(CallbackQueryHandler(customer.cid_confirm_callback, pattern=r"^cid:"))

    # Atajos numericos: el cliente manda /1, /2, ... para comprar directo.
    # Va como MessageHandler porque los numeros de producto son dinamicos.
    app.add_handler(MessageHandler(filters.Regex(r"^/\d{1,3}(\s+\d{1,3})?$"), customer.atajo_handler))

    # Mensajes libres (para el flujo de /cid cuando se espera el Installation ID)
    app.add_handler(MessageHandler(filters.PHOTO, customer.generic_photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, customer.generic_text_handler))

    app.add_error_handler(error_handler)

    logger.info("Bot iniciado, esperando mensajes...")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
