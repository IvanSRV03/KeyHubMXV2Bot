import re
import io
from typing import List, Optional

from PIL import Image
import pytesseract


class OcrUnavailable(Exception):
    """El binario de tesseract-ocr no está instalado/disponible en el servidor."""


# Un Installation ID de Office/Windows viene en 7 a 9 grupos, todos del mismo
# tamaño (6 o 7 dígitos cada uno), sumando 42-63 dígitos en total. El proveedor
# solo acepta exactamente 54 (9x6) o 63 (9x7) dígitos.
#
# La pantalla de activación también trae ruido que confunde a un lector de
# texto ingenuo: números de teléfono, pasos numerados ("1:", "2:"), montos,
# etc. Por eso no basta con juntar todos los dígitos que aparezcan — hay que
# encontrar específicamente la corrida (runs) de tokens del mismo tamaño que
# forman el ID real, e ignorar el resto.


def _total_digits(run: List[str]) -> int:
    return sum(len(t) for t in run)


def _find_digit_runs(tokens: List[str]) -> List[List[str]]:
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


def extract_installation_id(image_bytes: bytes) -> Optional[str]:
    try:
        image = Image.open(io.BytesIO(image_bytes))
    except Exception:
        return None

    try:
        text = pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError as e:
        raise OcrUnavailable(str(e))
    except Exception:
        return None

    tokens = re.findall(r"\d+", text)
    if not tokens:
        return None

    runs = _find_digit_runs(tokens)
    if not runs:
        return None

    # Prioriza cualquier corrida que sume exactamente 54 o 63 dígitos (lo que
    # exige el proveedor). Si hay varias, toma la más larga.
    exact_matches = [r for r in runs if _total_digits(r) in (54, 63)]
    if exact_matches:
        best = max(exact_matches, key=_total_digits)
    else:
        # Nada calzó exacto (foto imperfecta) — toma la corrida más plausible
        # como mejor intento, con un número razonable de grupos.
        plausible = [r for r in runs if 6 <= len(r) <= 10]
        if not plausible:
            return None
        best = max(plausible, key=len)

    group_len = len(best[0])
    digits = "".join(best)
    groups = [digits[k : k + group_len] for k in range(0, len(digits), group_len)]
    return "-".join(groups)
