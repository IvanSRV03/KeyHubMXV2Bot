# -*- coding: utf-8 -*-
"""Comprueba que una llamada lenta al proveedor ya no congela al bot.

Antes, `requests` bloqueaba el event loop: mientras el proveedor respondía
(hasta 900s según su documentación), el bot no atendía a nadie más.

Correr con:  python tests/test_concurrencia.py
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _entorno import preparar

preparar("concurrencia")

import provider_api as api  # noqa: E402

# Un proveedor que tarda 1 segundo en contestar.
api.get_cid = lambda iid: (time.sleep(1.0), {"success": True, "data": "CID"})[1]


async def otros_clientes(marcas):
    for _ in range(10):
        await asyncio.sleep(0.05)
        marcas.append(time.monotonic())


async def main():
    marcas = []
    inicio = time.monotonic()
    await asyncio.gather(api.a_get_cid("1" * 54), otros_clientes(marcas))
    atendidos = sum(1 for m in marcas if m - inicio < 1.0)
    print(f"Mientras el proveedor tardaba 1s, el bot atendió {atendidos} eventos más.")
    assert atendidos >= 8, "el bot se quedó bloqueado esperando al proveedor"
    print("\nTODO BIEN (concurrencia): el bot sigue respondiendo durante una llamada lenta")


asyncio.run(main())
