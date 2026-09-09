import re
import io
from typing import Optional

from PIL import Image
import pytesseract

# Un Installation ID de Office/Windows normalmente son 7-9 grupos de 6-7 dígitos.
# Aquí no asumimos un formato exacto: juntamos todos los dígitos que OCR detecte
# línea por línea (para no mezclar renglones de la interfaz que no son el ID)
# y los reagrupamos de 6 en 6, que es el formato más común.


def extract_installation_id(image_bytes: bytes) -> Optional[str]:
    try:
        image = Image.open(io.BytesIO(image_bytes))
    except Exception:
        return None

    text = pytesseract.image_to_string(image)

    candidate_lines = []
    for line in text.splitlines():
        digits = re.sub(r"[^\d]", "", line)
        if len(digits) >= 6:
            candidate_lines.append(digits)

    all_digits = "".join(candidate_lines)
    if len(all_digits) < 30:
        # Muy pocos dígitos detectados como para ser un Installation ID real
        return None

    groups = [all_digits[i : i + 6] for i in range(0, len(all_digits), 6)]
    # Descarta un último grupo incompleto muy corto (ruido de OCR)
    if len(groups[-1]) < 4:
        groups = groups[:-1]

    return "-".join(groups)
