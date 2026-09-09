import os

# Token del bot de Telegram (te lo da @BotFather)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Token de la API del proveedor (mspidpro)
PROVIDER_TOKEN = os.environ.get("PROVIDER_TOKEN", "")

# IDs de Telegram de los administradores (tú y quien más quieras), separados por coma
ADMIN_IDS = set(
    int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x
)

# Ruta del archivo de base de datos SQLite.
# En Railway, monta un Volume en /data y deja esta ruta apuntando ahí,
# o la base de datos se borrará cada vez que se redeploy el bot.
DB_PATH = os.environ.get("DB_PATH", "bot.db")

PROVIDER_BASE_URL = "https://www.mspidpro.com/api"
