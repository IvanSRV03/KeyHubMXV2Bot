import asyncio
import time
import requests

from config import PROVIDER_TOKEN, PROVIDER_BASE_URL


class ProviderError(Exception):
    """Se lanza cuando el proveedor responde con un error o algo no se pudo interpretar."""


def _get(path: str, params: dict, timeout: int = 30) -> dict:
    params = dict(params)
    params["token"] = PROVIDER_TOKEN
    url = f"{PROVIDER_BASE_URL}/{path}"
    try:
        resp = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as e:
        raise ProviderError(f"No se pudo conectar con el proveedor: {e}")

    try:
        data = resp.json()
    except ValueError:
        raise ProviderError(
            f"El proveedor respondió algo que no es JSON (status {resp.status_code}): {resp.text[:200]}"
        )

    if not data.get("success", False):
        raise ProviderError(data.get("message") or data.get("error") or "El proveedor devolvió un error sin detalle.")

    return data


def check_keys(keys: str) -> dict:
    """keys: una o varias claves separadas por coma."""
    return _get("check-keys", {"keys": keys})


def check_redeem(keys: str) -> dict:
    return _get("redeem-keys", {"keys": keys})


def get_cid(iid: str) -> dict:
    return _get("get-cid", {"iid": iid})


def key_products() -> dict:
    return _get("key-products", {})


def buy_key(product_code: str, quantity: int, order_id: str) -> dict:
    # El proveedor documenta que una compra puede tardar bastante en resolverse,
    # asi que se le da mas margen que a las consultas normales.
    return _get(
        "buy-key",
        {"code": product_code, "quantity": quantity, "orderId": order_id},
        timeout=120,
    )


def buy_key_order_status(order_id: str) -> dict:
    return _get("buy-key/order", {"orderId": order_id})


def make_order_id() -> str:
    """Formato requerido por el proveedor: KP + timestamp de 13 dígitos (milisegundos)."""
    return f"KP{int(time.time() * 1000)}"


# ---------------------------------------------------------------------------
# Versiones async
#
# `requests` es bloqueante: llamarlo directo desde un handler async congela
# TODO el bot mientras el proveedor responde — y segun su documentacion una
# compra puede tardar hasta 900 segundos. Con esto la llamada se va a un hilo
# aparte y el bot sigue atendiendo a los demas clientes mientras tanto.
# ---------------------------------------------------------------------------

async def a_check_keys(keys: str) -> dict:
    return await asyncio.to_thread(check_keys, keys)


async def a_check_redeem(keys: str) -> dict:
    return await asyncio.to_thread(check_redeem, keys)


async def a_get_cid(iid: str) -> dict:
    return await asyncio.to_thread(get_cid, iid)


async def a_key_products() -> dict:
    return await asyncio.to_thread(key_products)


async def a_buy_key(product_code: str, quantity: int, order_id: str) -> dict:
    return await asyncio.to_thread(buy_key, product_code, quantity, order_id)


async def a_buy_key_order_status(order_id: str) -> dict:
    return await asyncio.to_thread(buy_key_order_status, order_id)
