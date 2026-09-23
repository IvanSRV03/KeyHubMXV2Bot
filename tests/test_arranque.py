# -*- coding: utf-8 -*-
"""Arranca la aplicación igual que bot.py pero sin conectarse a Telegram.

Sirve para cachar un handler mal escrito o un import roto ANTES del deploy,
en vez de descubrirlo con el bot caído en Railway.

Correr con:  python tests/test_arranque.py
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _entorno import preparar

preparar("arranque")

import db  # noqa: E402
import bot  # noqa: E402
from telegram.ext import (  # noqa: E402
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

db.init_db()
app = ApplicationBuilder().token(os.environ["BOT_TOKEN"]).build()

# Se ejecutan las mismas líneas de registro que bot.main(), sin el run_polling.
ns = {
    "app": app,
    "customer": bot.customer,
    "admin": bot.admin,
    "CommandHandler": CommandHandler,
    "MessageHandler": MessageHandler,
    "CallbackQueryHandler": CallbackQueryHandler,
    "filters": filters,
}
for linea in inspect.getsource(bot.main).splitlines():
    if "add_handler" in linea:
        exec(linea.strip(), ns)

comandos = sorted(
    next(iter(h.commands))
    for grupo in app.handlers.values()
    for h in grupo
    if isinstance(h, CommandHandler)
)
print(f"{len(comandos)} comandos registrados:")
print("  " + ", ".join("/" + c for c in comandos))

esperados = {
    "start", "productos", "comprar", "cid", "saldo", "historial",
    "aprobar", "bloquear", "pendientes", "limite", "limiteglobal",
    "maxcantidad", "orden", "ordenes", "cobrar", "pagar",
}
faltan = esperados - set(comandos)
assert not faltan, f"faltan comandos: {faltan}"

app.add_error_handler(bot.error_handler)
assert app.error_handlers, "no se registró el manejador global de errores"

print("\nTODO BIEN (arranque): la app carga, todos los handlers existen")
