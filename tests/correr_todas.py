# -*- coding: utf-8 -*-
"""Corre todas las pruebas de una. Úsalo antes de hacer merge a main,
porque Railway despliega solo en cuanto main cambia.

    python tests/correr_todas.py
"""
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
PRUEBAS = [
    "test_db.py",
    "test_compra.py",
    "test_practicidad.py",
    "test_arranque.py",
    "test_concurrencia.py",
]

fallaron = []
for nombre in PRUEBAS:
    print(f"\n{'=' * 60}\n{nombre}\n{'=' * 60}")
    r = subprocess.run([sys.executable, os.path.join(AQUI, nombre)])
    if r.returncode != 0:
        fallaron.append(nombre)

print(f"\n{'=' * 60}")
if fallaron:
    print("FALLARON: " + ", ".join(fallaron))
    sys.exit(1)
print(f"Las {len(PRUEBAS)} pruebas pasaron. Listo para desplegar.")
