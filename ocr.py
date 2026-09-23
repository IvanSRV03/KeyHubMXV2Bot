# -*- coding: utf-8 -*-
"""Lectura del Installation ID a partir de una foto de la pantalla.

El proveedor NO recibe imágenes: sus endpoints (`get-cid`, `check-keys`,
`redeem-keys`) esperan el Installation ID como texto. Convertir la foto en
dígitos es trabajo nuestro, y es la parte frágil de todo el flujo.

La versión anterior le pasaba la foto cruda a Tesseract y se quedaba con lo
que saliera, por eso fallaba tanto. Aquí se hace lo que de verdad mueve la
aguja con fotos de pantalla tomadas con celular:

1. Se prueban varias versiones de la misma imagen (escala de grises, más
   grande, con más contraste, binarizada, invertida por si la pantalla está
   en modo oscuro).
2. Se prueban varios modos de segmentación de página de Tesseract.
3. Se acepta el primer resultado que forme un Installation ID válido
   (54 o 63 dígitos, en grupos del mismo tamaño).
"""
import io
import logging
import re
from typing import List, Optional, Tuple

import pytesseract
from PIL import Image, ImageChops, ImageFilter, ImageOps

logger = logging.getLogger(__name__)


class OcrUnavailable(Exception):
    """El binario de tesseract-ocr no está instalado/disponible en el servidor."""


# A propósito NO se usa `tessedit_char_whitelist=0123456789`. Suena a la
# opción obvia ("solo va a haber dígitos"), pero el motor LSTM de Tesseract 4+
# la implementa mal y empeora muchísimo el reconocimiento: medido contra estas
# mismas pantallas, la lista blanca bajaba la lectura de 8/8 a 0/8. El ruido
# de letras se filtra después, al buscar las corridas de dígitos.
_CONFIG_BASE = ""

# 6 = un bloque de texto uniforme (el caso normal de la pantalla)
# 4 = columnas de texto de ancho variable
# 11 = texto disperso, sirve cuando la foto trae la tabla separada
_MODOS = (6, 4, 11)

# El proveedor solo acepta exactamente 54 (9x6) o 63 (9x7) dígitos.
_LARGOS_VALIDOS = (54, 63)


def _total_digits(run: List[str]) -> int:
    return sum(len(t) for t in run)


def _find_digit_runs(tokens: List[str]) -> List[List[str]]:
    """Agrupa tokens consecutivos del mismo tamaño (6 o 7 dígitos).

    La pantalla de activación trae ruido que confunde a un lector ingenuo:
    números de teléfono, pasos numerados ("1:", "2:"), etc. Por eso no basta
    con juntar todos los dígitos — hay que encontrar la corrida de grupos
    parejos que forma el ID real e ignorar el resto.
    """
    runs = []
    i = 0
    n = len(tokens)
    while i < n:
        tok_len = len(tokens[i])
        if tok_len in (6, 7):
            j = i
            while j < n and len(tokens[j]) == tok_len:
                j += 1
            runs.append(tokens[i:j])
            i = j
        else:
            i += 1
    return runs


def _candidato(texto: str) -> Tuple[Optional[str], bool]:
    """Saca el mejor Installation ID de un texto. Devuelve (id, es_exacto)."""
    tokens = re.findall(r"\d+", texto)
    if not tokens:
        return None, False

    runs = _find_digit_runs(tokens)
    if not runs:
        return None, False

    exactos = [r for r in runs if _total_digits(r) in _LARGOS_VALIDOS]
    if exactos:
        best = max(exactos, key=_total_digits)
        exacto = True
    else:
        plausibles = [r for r in runs if 6 <= len(r) <= 10]
        if not plausibles:
            return None, False
        best = max(plausibles, key=len)
        exacto = False

    group_len = len(best[0])
    digits = "".join(best)
    grupos = [digits[k : k + group_len] for k in range(0, len(digits), group_len)]
    return "-".join(grupos), exacto


def _variantes(img: Image.Image):
    """Versiones de la imagen, de la más probable a la menos.

    Se devuelven como (nombre, imagen) para poder registrar en los logs cuál
    funcionó y así afinar el orden con fotos reales.
    """
    gris = ImageOps.exif_transpose(img).convert("L")

    # Tesseract trabaja mucho mejor con texto grande: las fotos de pantalla
    # suelen traer los dígitos demasiado chicos.
    ancho, alto = gris.size
    if ancho < 1600:
        factor = min(3, max(2, 1600 // max(ancho, 1)))
        grande = gris.resize((ancho * factor, alto * factor), Image.LANCZOS)
    else:
        grande = gris

    contraste = ImageOps.autocontrast(grande, cutoff=2)

    # Una foto de pantalla casi nunca tiene luz pareja: hay sombra de la mano,
    # reflejo de la lámpara, un lado más oscuro. Un umbral global parte esas
    # fotos a la mitad. Restarle a la imagen su propio fondo desenfocado
    # (corrección de campo plano) empareja la iluminación antes de leerla.
    radio = max(8, max(grande.size) // 25)
    fondo = grande.filter(ImageFilter.GaussianBlur(radio))
    sin_sombra = ImageOps.autocontrast(
        ImageChops.subtract(grande, fondo, scale=1.0, offset=128), cutoff=1
    )

    # Contra fotos movidas o desenfocadas.
    realzada = contraste.filter(ImageFilter.UnsharpMask(radius=3, percent=180, threshold=2))

    umbral = contraste.point(lambda p: 255 if p > 128 else 0)

    return [
        ("contraste", contraste),
        ("sin_sombra", sin_sombra),
        ("realzada", realzada),
        ("binarizada", umbral),
        ("invertida", ImageOps.invert(umbral)),   # pantallas en modo oscuro
        ("original", gris),
    ]


def extract_installation_id(image_bytes: bytes) -> Optional[str]:
    """Devuelve el Installation ID con guiones, o None si no se pudo leer."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception:
        return None

    mejor_parcial = None

    for nombre, variante in _variantes(img):
        for psm in _MODOS:
            try:
                texto = pytesseract.image_to_string(
                    variante, config=f"--psm {psm} {_CONFIG_BASE}".strip()
                )
            except pytesseract.TesseractNotFoundError as e:
                raise OcrUnavailable(str(e))
            except Exception:
                continue

            candidato, exacto = _candidato(texto)
            if exacto:
                logger.info("Installation ID leído con variante=%s psm=%s", nombre, psm)
                return candidato
            if candidato and mejor_parcial is None:
                mejor_parcial = candidato

    if mejor_parcial:
        logger.info("Solo se logró una lectura parcial del Installation ID")
    return mejor_parcial
