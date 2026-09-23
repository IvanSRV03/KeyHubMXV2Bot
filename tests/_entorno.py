"""Prepara un entorno aislado para las pruebas: base de datos temporal y
variables de entorno falsas, para no tocar nunca la base de producción."""
import os
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def preparar(nombre: str) -> str:
    ruta = os.path.join(tempfile.mkdtemp(prefix=f"keyhub-{nombre}-"), "prueba.db")
    os.environ.update(
        BOT_TOKEN="123456789:AAFakeTokenParaPruebasLocalesNoReal12345",
        PROVIDER_TOKEN="token-falso-de-prueba",
        ADMIN_IDS="999",
        DB_PATH=ruta,
    )
    if RAIZ not in sys.path:
        sys.path.insert(0, RAIZ)
    return ruta
