# -*- coding: utf-8 -*-
"""Genera pantallas de activación sintéticas para probar el lector de
Installation ID, sin necesidad de guardar fotos reales de clientes."""
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


def _fuente(tam):
    for ruta in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        if os.path.exists(ruta):
            try:
                return ImageFont.truetype(ruta, tam)
            except Exception:
                pass
    return ImageFont.load_default()


def id_al_azar(grupos=9, largo=6, semilla=None):
    r = random.Random(semilla)
    return ["".join(r.choice("0123456789") for _ in range(largo)) for _ in range(grupos)]


def pantalla(grupos, largo, ancho=1400, oscuro=False, ruido=0.0, borroso=0.0,
             escala=1.0, rotacion=0.0, sombra=0.0, semilla=0):
    """Dibuja una pantalla de activación telefónica con su ruido típico:
    pasos numerados y números de teléfono que confunden a un lector ingenuo."""
    r = random.Random(semilla)
    fondo = (32, 32, 38) if oscuro else (245, 245, 247)
    tinta = (235, 235, 240) if oscuro else (20, 20, 25)
    gris = (150, 150, 155) if oscuro else (110, 110, 115)
    alto = 620

    img = Image.new("RGB", (ancho, alto), fondo)
    d = ImageDraw.Draw(img)
    f_tit, f_txt, f_id = _fuente(30), _fuente(21), _fuente(30)

    d.text((60, 40), "Activación telefónica", font=f_tit, fill=tinta)
    d.text((60, 100), "Paso 1: Llame a un número de Centro de activación:", font=f_txt, fill=gris)
    d.text((80, 135), "800 000 1234    o    01 55 4321 9876", font=f_txt, fill=gris)
    d.text((60, 180), "Paso 2: Proporcione el Id. de instalación:", font=f_txt, fill=gris)

    ancho_grupo = int(d.textlength("0" * largo, font=f_id))
    paso = ancho_grupo + 45
    x, y = 70, 240
    for i, g in enumerate(grupos):
        d.text((x, y), chr(ord("A") + i), font=f_txt, fill=gris)
        d.text((x, y + 30), g, font=f_id, fill=tinta)
        x += paso
        if x + ancho_grupo > ancho - 60:
            x, y = 70, y + 110

    d.text((60, 520), "Paso 3: Escriba el Id. de confirmación: 8 grupos", font=f_txt, fill=gris)

    if sombra:
        capa = Image.new("L", img.size, 255)
        ImageDraw.Draw(capa).polygon(
            [(0, 0), (int(ancho * 0.55), 0), (int(ancho * 0.30), alto), (0, alto)],
            fill=int(255 * (1 - sombra)),
        )
        capa = capa.filter(ImageFilter.GaussianBlur(ancho * 0.05))
        img = Image.composite(img, Image.new("RGB", img.size, (0, 0, 0)), capa)

    if escala != 1.0:
        img = img.resize((int(img.size[0] * escala), int(img.size[1] * escala)), Image.LANCZOS)
    if rotacion:
        img = img.rotate(rotacion, expand=True, fillcolor=fondo)
    if borroso:
        img = img.filter(ImageFilter.GaussianBlur(borroso))
    if ruido:
        px = img.load()
        for _ in range(int(img.size[0] * img.size[1] * ruido)):
            xx, yy = r.randrange(img.size[0]), r.randrange(img.size[1])
            delta = r.randint(-55, 55)
            cr, cg, cb = px[xx, yy]
            px[xx, yy] = (
                max(0, min(255, cr + delta)),
                max(0, min(255, cg + delta)),
                max(0, min(255, cb + delta)),
            )
    return img


def como_bytes(img) -> bytes:
    import io
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def banco():
    """Los casos que se miden. Cada uno: (descripción, bytes, id esperado)."""
    casos = []

    def agregar(desc, largo, semilla, **kw):
        grupos = id_al_azar(9, largo, semilla=semilla)
        img = pantalla(grupos, largo, semilla=semilla, **kw)
        casos.append((desc, como_bytes(img), "-".join(grupos)))

    agregar("limpia, 54 dígitos", 6, 1)
    agregar("limpia, 63 dígitos", 7, 2)
    agregar("foto chica", 6, 3, escala=0.45)
    agregar("pantalla en modo oscuro", 6, 4, oscuro=True)
    agregar("con ruido de cámara", 6, 5, ruido=0.06)
    agregar("ligeramente borrosa", 6, 6, borroso=1.1)
    agregar("chica + ruido", 7, 7, escala=0.55, ruido=0.04)
    agregar("un poco inclinada", 6, 8, rotacion=1.5)
    agregar("con sombra encima", 6, 9, sombra=0.5)
    agregar("chica + sombra", 6, 10, escala=0.6, sombra=0.4)
    return casos
