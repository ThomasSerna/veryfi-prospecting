"""Adaptador de Tavily Search/Extract: operaciones, solicitudes, respuestas, créditos y errores.

Sin red ni base de datos: convierte respuestas no confiables en SearchHit y Evidence;
solo `prospecting.pipeline` reserva y llama.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, StrictStr

from prospecting.discovery import COUNTRIES, RESEARCH_QUERY_VERSION, PlannedQuery, SearchHit
from prospecting.models import Company, DiscoveryLimits, Evidence, utc_now
from prospecting.providers.http import OperationSpec, ProviderError, ProviderRequest
from prospecting.sources import (
    CONTACT_SEARCH_REFERENCE, NON_BUSINESS_DOMAINS, SEARCH_HIT_CLAIM, SEARCH_PROVIDER, is_non_business, url_host,
    within_domain,
)
from prospecting.text import clip


PROVIDER = SEARCH_PROVIDER
SEARCH_OPERATION = "search"
EXTRACT_OPERATION = "extract"
SEARCH_CREDITS = 1
URLS_PER_EXTRACT_CREDIT = 5
EXTRACT_CHUNKS_PER_SOURCE = 3
EXTRACT_TIMEOUT_SECONDS = 6.0
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


Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
NonNegativeNumber = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]


class TavilyUsage(BaseModel):
    credits: NonNegativeNumber | None = None


class TavilySearchResult(BaseModel):
    url: StrictStr
    title: StrictStr | None = None
    content: StrictStr | None = None
    score: Number | None = None


class TavilySearchResponse(BaseModel):
    results: Annotated[list[TavilySearchResult], Field(max_length=20)]
    usage: TavilyUsage | None = None
    request_id: StrictStr | None = None


class TavilyExtractResult(BaseModel):
    url: StrictStr
    raw_content: StrictStr | None = None


class TavilyFailedResult(BaseModel):
    url: StrictStr
    error: StrictStr | None = None


class TavilyExtractResponse(BaseModel):
    results: Annotated[list[TavilyExtractResult], Field(max_length=20)]
    failed_results: Annotated[list[TavilyFailedResult], Field(max_length=20)] = Field(default_factory=list)
    usage: TavilyUsage | None = None
    request_id: StrictStr | None = None


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
            title=clip(result.title, TITLE_CHARS), snippet=clip(result.content, SNIPPET_CHARS),
            rank=rank, query=planned, query_index=query_index,
            local_request_id=local_request_id,
            provider_request_id=clip(response.request_id, 120),
            retrieved_at=retrieved_at,
        ))
    return hits, discarded


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
    reference = clip(response.request_id, 120) or str(local_request_id)
    evidence = []
    for index, result in enumerate(response.results, start=1):
        url = result.url.strip()
        if url not in requested_set or url_host(url) is None:
            continue
        host = url_host(url)
        primary = company.domain is not None and within_domain(host, company.domain)
        chunks = [clip(chunk, CHUNK_CHARS) for chunk in (result.raw_content or "").split("[...]")]
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
        (item.url.strip(), clip(item.error, 200) or "Fallo sin detalle del proveedor.")
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



COMPANY_SEARCH_RESULTS = 5


def company_search_request(company: Company, query: str, account_ref: str) -> ProviderRequest:
    """Búsqueda de la ampliación restringida al dominio; su payload forma parte de la huella persistida."""
    if company.domain is None:
        raise ValueError("La ampliación necesita el dominio de la empresa.")
    return ProviderRequest(provider=PROVIDER, operation=SEARCH_OPERATION, account_ref=account_ref,
                           payload={"query": query, "search_depth": "basic", "topic": "general",
                                    "max_results": COMPANY_SEARCH_RESULTS, "include_domains": [company.domain],
                                    "include_answer": False, "include_raw_content": False,
                                    "include_images": False, "include_usage": True})


def company_search_evidence(company: Company, response: TavilySearchResponse, local_request_id: UUID,
                            retrieved_at: datetime) -> list[Evidence]:
    """Resultados del propio dominio marcados como búsqueda: localizan páginas, nunca confirman hechos."""
    reference = clip(response.request_id, 120) or str(local_request_id)
    evidence = []
    for rank, result in enumerate(response.results, start=1):
        host = url_host(result.url)
        if host is None or company.domain is None or not within_domain(host, company.domain):
            continue
        title = f" Título: {clip(result.title, TITLE_CHARS)}." if clip(result.title, TITLE_CHARS) else ""
        evidence.append(Evidence(
            company_id=company.id,
            claim=clip(f"{SEARCH_HIT_CLAIM} en el puesto {rank} de la ampliación de evidencia "
                       f"({RESEARCH_QUERY_VERSION}).{title}", 600),
            url=result.url.strip(), provider=PROVIDER, external_reference=f"{reference}#{rank}",
            excerpt=clip(result.content, SNIPPET_CHARS), retrieved_at=retrieved_at,
            kind="observed", source_type="secondary",
        ))
    return evidence


def contact_search_request(query: str, account_ref: str) -> ProviderRequest:
    """Búsqueda pública de personas; su payload forma parte de la huella persistida (docs/persistence.md)."""
    return ProviderRequest(provider=PROVIDER, operation=SEARCH_OPERATION, account_ref=account_ref,
                           payload={"query": query, "search_depth": "basic", "topic": "general",
                                    "max_results": 10, "include_usage": True,
                                    "exclude_domains": ["linkedin.com"]})


def contact_search_evidence(company_id: UUID, response: TavilySearchResponse,
                            local_request_id: UUID) -> list[Evidence]:
    """Resultados públicos marcados como búsqueda: localizan una fuente, nunca prueban a una persona."""
    return [Evidence(company_id=company_id, claim=f"{SEARCH_HIT_CLAIM} en una búsqueda pública de contactos; requiere contraste.",
                     url=hit.url, provider=PROVIDER, external_reference=f"{CONTACT_SEARCH_REFERENCE}{local_request_id}:{index}",
                     excerpt=(hit.content or hit.title or "Resultado sin texto.")[:800],
                     retrieved_at=utc_now(), kind="observed", source_type="secondary")
            for index, hit in enumerate(response.results) if url_host(hit.url) is not None
            and not is_non_business(url_host(hit.url))]
