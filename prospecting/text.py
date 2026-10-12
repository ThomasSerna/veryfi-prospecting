"""Recorte y normalización de texto externo; sin red, base de datos ni proveedores."""

import re
import unicodedata


def clip(value: str | None, limit: int) -> str | None:
    """Colapsa espacios y controles y acota la longitud de un texto externo."""
    if value is None:
        return None
    text = re.sub(r"[\x00-\x1f\x7f\s]+", " ", value).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def plain(value: str) -> str:
    """Minúsculas sin tildes; todo lo que no es letra o dígito pasa a un espacio."""
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def compact(value: str) -> str:
    """`plain` sin espacios; forma parte de `Company.identity_key` (docs/persistence.md)."""
    return plain(value).replace(" ", "")
