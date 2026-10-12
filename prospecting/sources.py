"""Política de fuentes externas: URLs públicas, dominios no empresariales y resultados de buscador.

Sin red ni base de datos. Un resultado de buscador solo localiza una fuente; nunca
confirma un hecho de la empresa ni de una persona (§7.3, §15).
"""

import ipaddress
from urllib.parse import urlsplit

from prospecting.models import Evidence, _domain


# Hosts que no representan a la empresa buscada: redes, directorios, tiendas y gobierno.
NON_BUSINESS_DOMAINS = (
    "linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com",
    "tiktok.com", "youtube.com", "youtu.be", "pinterest.com", "reddit.com",
    "wikipedia.org", "medium.com", "blogspot.com", "wordpress.com",
    "apps.apple.com", "play.google.com", "google.com", "crunchbase.com",
    "glassdoor.com", "indeed.com", "computrabajo.com", "gov.co", "gob.mx",
    "getapp.com", "getapp.com.co", "getapp.com.mx", "capterra.com", "capterra.co",
    "capterra.mx", "g2.com", "softwareadvice.com", "trustradius.com",
)

_GENERIC_LABELS = {
    "www", "app", "web", "m", "es", "com", "co", "mx", "net", "org", "io", "la",
    "lat", "ai", "online", "site", "store", "shop", "info", "biz",
}
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet")

# Marcadores persistidos de resultados de buscador (docs/persistence.md).
SEARCH_PROVIDER = "tavily"
SEARCH_HIT_CLAIM = "Tavily devolvió esta página"
CONTACT_SEARCH_REFERENCE = "contacts_search:"


def within_domain(host: str, domain: str) -> bool:
    """El host es el dominio o uno de sus subdominios."""
    return host == domain or host.endswith("." + domain)


def is_non_business(host: str) -> bool:
    return any(within_domain(host, domain) for domain in NON_BUSINESS_DOMAINS)


def validate_public_url(value: object) -> str | None:
    """Devuelve la URL si es HTTP(S) pública por nombre; si no, None (§15)."""
    if not isinstance(value, str) or len(value) > 2048:
        return None
    url = value.strip()
    if any(ord(char) <= 32 or ord(char) == 127 for char in url):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        return None
    if port not in (None, 80, 443) or not parts.hostname:
        return None
    try:
        ipaddress.ip_address(parts.hostname.strip("[]"))
    except ValueError:
        pass
    else:
        return None
    try:
        host = _domain(parts.hostname)
    except ValueError:
        return None
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        return None
    return url


def url_host(url: str) -> str | None:
    """Host normalizado sin `www.`; None si la URL no es pública."""
    if validate_public_url(url) is None:
        return None
    host = _domain(urlsplit(url.strip()).hostname)
    return host[4:] if host.startswith("www.") and host.count(".") > 1 else host


def domain_label(host: str) -> str:
    """Etiqueta distintiva del dominio, sin TLD ni etiquetas genéricas (com, co, www…)."""
    labels = host.split(".")[:-1]
    while len(labels) > 1 and labels[-1] in _GENERIC_LABELS:
        labels.pop()
    return labels[-1]


def is_search_hit(item: Evidence) -> bool:
    """Resultado del buscador: localiza una fuente, pero no confirma hechos (§7.3)."""
    return (item.provider == SEARCH_PROVIDER and item.source_type == "secondary"
            and item.claim.startswith(SEARCH_HIT_CLAIM))


def is_search_evidence(item: Evidence) -> bool:
    """Cualquier resultado de búsqueda, incluida la pública de contactos; nunca prueba a una persona."""
    return is_search_hit(item) or (item.external_reference or "").startswith(CONTACT_SEARCH_REFERENCE)
