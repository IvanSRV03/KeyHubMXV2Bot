import logging

from telegram import Update
from telegram.ext import ContextTypes

import db
from config import ADMIN_IDS

logger = logging.getLogger(__name__)

# Telegram rechaza mensajes de mas de 4096 caracteres. Se deja holgura para
# el encabezado que algunos comandos le anteponen a cada pedazo.
TELEGRAM_LIMIT = 3800


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def chunk_lines(lines, limit: int = TELEGRAM_LIMIT):
    """Parte una lista de lineas en bloques que quepan en un mensaje."""
    chunks = []
    current = []
    size = 0
    for line in lines:
        line_size = len(line) + 1
        if current and size + line_size > limit:
            chunks.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += line_size
    if current:
        chunks.append("\n".join(current))
    return chunks


async def reply_long(update: Update, lines, header: str = ""):
    """Responde una lista de lineas, partiendola en varios mensajes si hace falta."""
    chunks = chunk_lines(lines)
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        prefix = ""
        if header:
            prefix = f"{header} ({i + 1}/{total}):\n" if total > 1 else f"{header}:\n"
        elif total > 1:
            prefix = f"({i + 1}/{total})\n"
        await update.effective_message.reply_text(prefix + chunk)


async def notify_admins(context: ContextTypes.DEFAULT_TYPE, text: str):
    """Avisa a todos los admins. Un admin que bloqueo al bot no rompe el envio."""
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text)
        except Exception:
            logger.warning("No se pudo avisar al admin %s", admin_id, exc_info=True)


async def require_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deja pasar solo a clientes aprobados (los admins siempre pasan).

    Devuelve la fila del cliente, o None si no debe continuar. Cuando no
    pasa, ya le respondio al usuario explicandole por que.
    """
    user = update.effective_user
    message = update.effective_message

    if is_admin(user.id):
        db.ensure_customer(user.id, user.username, user.first_name, status=db.APROBADO)
        return db.get_customer(user.id)

    nuevo = db.ensure_customer(user.id, user.username, user.first_name)
    customer = db.get_customer(user.id)

    if nuevo:
        await _anunciar_solicitud(update, context)

    status = customer["status"]
    if status == db.APROBADO:
        return customer

    if status == db.BLOQUEADO:
        await message.reply_text(
            "⛔ Tu acceso está suspendido. Si crees que es un error, contacta al administrador."
        )
        return None

    await message.reply_text(
        "⏳ Tu solicitud está pendiente de aprobación.\n"
        "El administrador tiene que darte de alta antes de que puedas comprar. "
        "Te avisamos en cuanto esté listo."
    )
    return None


async def _anunciar_solicitud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    etiqueta = f"@{user.username}" if user.username else (user.first_name or "sin nombre")
    await notify_admins(
        context,
        "🆕 Nueva solicitud de acceso\n"
        f"{etiqueta} (ID {user.id})\n\n"
        f"Para darle acceso: /aprobar {user.id}\n"
        f"Para ignorarlo: /bloquear {user.id}",
    )
