"""Consultas, lectura y selección de candidatos de Tavily; sin red ni base de datos.

Los resultados del buscador son datos no confiables: solo localizan fuentes y
nunca modifican límites, consultas ni instrucciones del flujo.
"""

from datetime import datetime
import ipaddress
import re
from typing import Annotated
import unicodedata
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from prospecting.models import (
    Campaign, Company, Contract, Count, CountryCode, DiscoveryLimits, Evidence,
    Segment, Text, UtcDatetime, _domain,
)
from prospecting.providers import OperationSpec, ProviderError, ProviderRequest


TEMPLATE_VERSION = "discovery_queries_v1"
PROVIDER = "tavily"
SEARCH_OPERATION = "search"
EXTRACT_OPERATION = "extract"
SEARCH_CREDITS = 1
URLS_PER_EXTRACT_CREDIT = 5
EXTRACT_CHUNKS_PER_SOURCE = 3
EXTRACT_TIMEOUT_SECONDS = 6.0
MAX_HITS_PER_CANDIDATE = 5
SNIPPET_CHARS = 300
CHUNK_CHARS = 800
TITLE_CHARS = 160

TAVILY_OPERATIONS = [
    OperationSpec(
        provider=PROVIDER, operation=SEARCH_OPERATION,
        endpoint="https://api.tavily.com/search", api_key_env="TAVILY_API_KEY",
    ),
    OperationSpec(
        provider=PROVIDER, operation=EXTRACT_OPERATION,
        endpoint="https://api.tavily.com/extract", api_key_env="TAVILY_API_KEY",
    ),
]

# Nombre para la consulta y valor del enum `country` de Tavily (sin tildes).
COUNTRIES = {"CO": ("Colombia", "colombia"), "MX": ("México", "mexico")}

# Dos plantillas por perfil: país + perfil + señal de necesidad (§7.1).
QUERY_TEMPLATES = {
    "expense_reimbursement": (
        "software de gestión de gastos empresariales que escanea recibos en {country}",
        "app de reembolsos de gastos con foto del recibo para empresas en {country}",
    ),
    "payments_ap_erp": (
        "plataforma de cuentas por pagar que procesa facturas de proveedores en {country}",
        "software de pagos a proveedores con captura de facturas en {country}",
    ),
    "cpg_brands": (
        "promoción registra tu ticket de compra y gana premios {country}",
        "programa de puntos por compra sube tu factura marca de consumo {country}",
    ),
    "loyalty_platforms_agencies": (
        "plataforma de fidelización para marcas que valida tickets de compra {country}",
        "agencia de promociones y lealtad con registro de facturas de compra {country}",
    ),
}

# Hosts que no representan a la empresa buscada: redes, directorios, tiendas y gobierno.
NON_BUSINESS_DOMAINS = (
    "linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com",
    "tiktok.com", "youtube.com", "youtu.be", "pinterest.com", "reddit.com",
    "wikipedia.org", "medium.com", "blogspot.com", "wordpress.com",
    "apps.apple.com", "play.google.com", "google.com", "crunchbase.com",
    "glassdoor.com", "indeed.com", "computrabajo.com", "gov.co", "gob.mx",
)

_GENERIC_LABELS = {
    "www", "app", "web", "m", "es", "com", "co", "mx", "net", "org", "io", "la",
    "lat", "ai", "online", "site", "store", "shop", "info", "biz",
}
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet")
_TITLE_SEPARATORS = re.compile(r"\s+[|\-–—:·»]\s+")


class _ProviderModel(BaseModel):
    """Respuesta externa: ignora campos nuevos y valida estrictamente los usados."""

    model_config = ConfigDict(extra="ignore")


Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
NonNegativeNumber = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]


class TavilyUsage(_ProviderModel):
    credits: NonNegativeNumber | None = None


class TavilySearchResult(_ProviderModel):
    url: StrictStr
    title: StrictStr | None = None
    content: StrictStr | None = None
    score: Number | None = None


class TavilySearchResponse(_ProviderModel):
    results: Annotated[list[TavilySearchResult], Field(max_length=20)]
    usage: TavilyUsage | None = None
    request_id: StrictStr | None = None


class TavilyExtractResult(_ProviderModel):
    url: StrictStr
    raw_content: StrictStr | None = None


class TavilyFailedResult(_ProviderModel):
    url: StrictStr
    error: StrictStr | None = None


class TavilyExtractResponse(_ProviderModel):
    results: Annotated[list[TavilyExtractResult], Field(max_length=20)]
    failed_results: Annotated[list[TavilyFailedResult], Field(max_length=20)] = Field(default_factory=list)
    usage: TavilyUsage | None = None
    request_id: StrictStr | None = None


class PlannedQuery(Contract):
    country: CountryCode
    segment: Segment
    profile_id: Text
    template_version: Text
    query: Text


class SearchHit(Contract):
    url: Text
    host: Text
    title: Text | None = None
    snippet: Text | None = None
    rank: Annotated[StrictInt, Field(ge=1)]
    query: PlannedQuery
    query_index: Count
    local_request_id: UUID
    provider_request_id: Text | None = None
    retrieved_at: UtcDatetime


class Candidate(Contract):
    host: Text
    name: Text
    hits: Annotated[list[SearchHit], Field(min_length=1)]


class CombinationReport(Contract):
    country: CountryCode
    segment: Segment
    candidates: Count
    selected: Count
    insufficient: StrictBool


def _clip(value: str | None, limit: int) -> str | None:
    """Colapsa espacios y controles y acota la longitud de un texto externo."""
    if value is None:
        return None
    text = re.sub(r"[\x00-\x1f\x7f\s]+", " ", value).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    return re.sub(r"[^a-z0-9]", "", "".join(char for char in text if not unicodedata.combining(char)))


def is_non_business(host: str) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in NON_BUSINESS_DOMAINS)


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


def build_search_queries(campaign: Campaign) -> list[PlannedQuery]:
    """Consultas de plantilla solo para países y segmentos de la campaña."""
    profiles = {
        segment: [
            profile for profile in campaign.config_snapshot.profiles
            if profile.segment == segment and profile.id in QUERY_TEMPLATES
        ]
        for segment in campaign.segments
    }
    depth = max((len(items) for items in profiles.values()), default=0)
    keywords = " ".join(campaign.filters.keywords)
    planned = []
    # Cada combinación país/segmento recibe turno antes de repetir otra.
    for template_index in range(2):
        for rank in range(depth):
            for country in campaign.countries:
                for segment in campaign.segments:
                    if country not in COUNTRIES or rank >= len(profiles[segment]):
                        continue
                    profile = profiles[segment][rank]
                    query = QUERY_TEMPLATES[profile.id][template_index].format(country=COUNTRIES[country][0])
                    planned.append(PlannedQuery(
                        country=country, segment=segment, profile_id=profile.id,
                        template_version=TEMPLATE_VERSION,
                        query=f"{query} {keywords}".strip(),
                    ))
    return planned[: campaign.limits.discovery.web_queries]


def search_request(planned: PlannedQuery, account_ref: str, limits: DiscoveryLimits) -> ProviderRequest:
    return ProviderRequest(
        provider=PROVIDER, operation=SEARCH_OPERATION, account_ref=account_ref,
        payload={
            "query": planned.query,
            "search_depth": "basic",
            "topic": "general",
            "country": COUNTRIES[planned.country][1],
            "max_results": limits.results_per_query,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_usage": True,
            "exclude_domains": list(NON_BUSINESS_DOMAINS),
        },
    )


def parse_search(planned: PlannedQuery, query_index: int, response: TavilySearchResponse,
                 local_request_id: UUID, retrieved_at: datetime) -> tuple[list[SearchHit], dict[str, int]]:
    """Convierte resultados en hits con procedencia y cuenta los descartes."""
    hits, discarded = [], {}
    for rank, result in enumerate(response.results, start=1):
        host = url_host(result.url)
        reason = None
        if host is None:
            reason = "unsafe_url"
        elif is_non_business(host):
            reason = "non_business_domain"
        if reason is not None:
            discarded[reason] = discarded.get(reason, 0) + 1
            continue
        hits.append(SearchHit(
            url=result.url.strip(), host=host,
            title=_clip(result.title, TITLE_CHARS), snippet=_clip(result.content, SNIPPET_CHARS),
            rank=rank, query=planned, query_index=query_index,
            local_request_id=local_request_id,
            provider_request_id=_clip(response.request_id, 120),
            retrieved_at=retrieved_at,
        ))
    return hits, discarded


def infer_name(title: str | None, host: str) -> str:
    """Nombre aparente a partir del título o del dominio; siempre es una inferencia."""
    labels = host.split(".")[:-1]
    while len(labels) > 1 and labels[-1] in _GENERIC_LABELS:
        labels.pop()
    label = labels[-1]
    if title:
        matching = [
            segment.strip() for segment in _TITLE_SEPARATORS.split(title)
            if segment.strip() and len(segment.strip()) <= 60 and _fold(label) in _fold(segment)
        ]
        if matching:
            return min(matching, key=len)
    return label.replace("-", " ").title()


def group_candidates(hits: list[SearchHit], raw_limit: int) -> tuple[list[Candidate], int]:
    """Acota los resultados brutos en rondas por posición y agrupa por host exacto."""
    ordered = sorted(hits, key=lambda hit: (hit.rank, hit.query_index))
    kept, dropped = ordered[:raw_limit], len(ordered) - min(len(ordered), raw_limit)
    groups: dict[str, list[SearchHit]] = {}
    for hit in kept:
        groups.setdefault(hit.host, []).append(hit)
    candidates = [
        Candidate(host=host, name=infer_name(group[0].title, host), hits=group[:MAX_HITS_PER_CANDIDATE])
        for host, group in groups.items()
    ]
    return candidates, dropped


def select_candidates(candidates: list[Candidate], campaign: Campaign) -> tuple[list[Candidate], list[CombinationReport]]:
    """Reparte la selección por país/segmento sin rellenar con datos inventados."""
    combos = [(country, segment) for country in campaign.countries for segment in campaign.segments]
    queues = {combo: [] for combo in combos}
    for candidate in candidates:
        first = candidate.hits[0].query
        queues.setdefault((first.country, first.segment), []).append(candidate)
    available = {combo: len(queue) for combo, queue in queues.items()}
    target = campaign.limits.discovery.target_per_country_segment
    selected: list[Candidate] = []
    chosen = {combo: 0 for combo in queues}

    def take(cap):
        progress = True
        while progress and len(selected) < campaign.max_companies:
            progress = False
            for combo, queue in queues.items():
                if queue and chosen[combo] < cap and len(selected) < campaign.max_companies:
                    selected.append(queue.pop(0))
                    chosen[combo] += 1
                    progress = True

    take(target)
    take(campaign.max_companies)
    report = [
        CombinationReport(
            country=country, segment=segment, candidates=available[(country, segment)],
            selected=chosen[(country, segment)], insufficient=available[(country, segment)] < target,
        )
        for country, segment in combos
    ]
    return selected, report


def build_company(candidate: Candidate) -> tuple[Company, list[Evidence]]:
    """Empresa pendiente de identidad, respaldada por los resultados que la localizaron."""
    company_id = uuid4()
    hit_evidence = []
    for hit in candidate.hits:
        title = f" Título: {hit.title}." if hit.title else ""
        hit_evidence.append(Evidence(
            company_id=company_id,
            claim=_clip(
                f"Tavily devolvió esta página en el puesto {hit.rank} para la consulta "
                f"«{hit.query.query}» (perfil {hit.query.profile_id}, país {hit.query.country}).{title}",
                600,
            ),
            url=hit.url, provider=PROVIDER,
            external_reference=f"{hit.provider_request_id or hit.local_request_id}#{hit.rank}",
            excerpt=hit.snippet, retrieved_at=hit.retrieved_at,
            kind="observed", source_type="secondary",
        ))
    first = candidate.hits[0]
    name_evidence = Evidence(
        company_id=company_id,
        claim=f"Nombre «{candidate.name}» inferido del título o del dominio {candidate.host}; no confirmado.",
        url=first.url, provider=PROVIDER,
        external_reference=f"{first.provider_request_id or first.local_request_id}#{first.rank}",
        retrieved_at=first.retrieved_at, kind="inference", source_type="secondary",
    )
    company = Company(
        id=company_id, name=candidate.name, domain=candidate.host,
        provenance={"name": [name_evidence.id], "domain": [item.id for item in hit_evidence]},
    )
    return company, [*hit_evidence, name_evidence]


def extract_query(campaign: Campaign) -> str:
    """Consulta de reordenación con las señales de los perfiles de la campaña."""
    signals = [
        signal for profile in campaign.config_snapshot.profiles
        if profile.segment in campaign.segments for signal in profile.signals
    ]
    return _clip("; ".join(dict.fromkeys(signals)), 400)


def extract_credits(url_count: int) -> int:
    return -(-url_count // URLS_PER_EXTRACT_CREDIT)


def extract_request(urls: list[str], query: str, account_ref: str) -> ProviderRequest:
    return ProviderRequest(
        provider=PROVIDER, operation=EXTRACT_OPERATION, account_ref=account_ref,
        payload={
            "urls": urls, "query": query, "chunks_per_source": EXTRACT_CHUNKS_PER_SOURCE,
            "extract_depth": "basic", "format": "text",
            "timeout": EXTRACT_TIMEOUT_SECONDS, "include_usage": True,
        },
    )


def parse_extract(company: Company, requested: list[str], response: TavilyExtractResponse,
                  local_request_id: UUID, retrieved_at: datetime) -> tuple[list[Evidence], list[tuple[str, str]]]:
    """Fragmentos mínimos de las URLs solicitadas; los fallos no crean evidencia."""
    requested_set = {url.strip() for url in requested}
    reference = _clip(response.request_id, 120) or str(local_request_id)
    evidence = []
    for index, result in enumerate(response.results, start=1):
        url = result.url.strip()
        if url not in requested_set or url_host(url) is None:
            continue
        host = url_host(url)
        primary = company.domain is not None and (host == company.domain or host.endswith("." + company.domain))
        chunks = [_clip(chunk, CHUNK_CHARS) for chunk in (result.raw_content or "").split("[...]")]
        for chunk_index, chunk in enumerate([chunk for chunk in chunks if chunk][:EXTRACT_CHUNKS_PER_SOURCE], start=1):
            evidence.append(Evidence(
                company_id=company.id,
                claim="Texto publicado en la página, extraído por Tavily.",
                url=url, provider=PROVIDER,
                external_reference=f"{reference}#{index}.{chunk_index}",
                excerpt=chunk, retrieved_at=retrieved_at, kind="observed",
                source_type="primary" if primary else "secondary",
            ))
    failures = [
        (item.url.strip(), _clip(item.error, 200) or "Fallo sin detalle del proveedor.")
        for item in response.failed_results if item.url.strip() in requested_set
    ]
    return evidence, failures


STOPPING_REASONS = {"permission_denied", "quota_exceeded", "rate_limited", "local_error"}


def classify_tavily_error(error: ProviderError) -> str:
    """Motivo de parada según la semántica documentada de Tavily, sin reintentar."""
    if error.kind == "http":
        status = error.http_status
        if status in (401, 403):
            return "permission_denied"
        if status in (432, 433):
            return "quota_exceeded"
        if status == 429:
            return "rate_limited"
        if status in (400, 422):
            return "invalid_input"
        return "provider_error"
    return {
        "timeout": "timeout", "transport": "transport_error", "local": "local_error",
        "json": "invalid_response", "schema": "invalid_response",
        "content_type": "invalid_response", "response_limit": "invalid_response",
    }.get(error.kind, "provider_error")
