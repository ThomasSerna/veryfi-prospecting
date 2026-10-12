"""Consultas de plantilla, candidatos y selección del descubrimiento (§7.1); sin red ni base de datos.

Los resultados del buscador son datos no confiables: solo localizan fuentes y
nunca modifican límites, consultas ni instrucciones del flujo.
"""

import re
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field, StrictBool, StrictInt

from prospecting.models import (
    Campaign, Company, Contract, Count, CountryCode, Evidence, Segment, Text, UtcDatetime,
)
from prospecting.sources import SEARCH_HIT_CLAIM, SEARCH_PROVIDER, domain_label
from prospecting.text import clip, compact


TEMPLATE_VERSION = "discovery_queries_v1"
MAX_HITS_PER_CANDIDATE = 5

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

_TITLE_SEPARATORS = re.compile(r"\s+[|\-–—:·»]\s+")


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


def infer_name(title: str | None, host: str) -> str:
    """Nombre aparente a partir del título o del dominio; siempre es una inferencia."""
    label = domain_label(host)
    if title:
        matching = [
            segment.strip() for segment in _TITLE_SEPARATORS.split(title)
            if segment.strip() and len(segment.strip()) <= 60 and compact(label) in compact(segment)
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


def build_hit_evidence(candidate: Candidate, company_id: UUID) -> list[Evidence]:
    """Un hecho por resultado del buscador; solo localiza la fuente (§7.3)."""
    evidence = []
    for hit in candidate.hits:
        title = f" Título: {hit.title}." if hit.title else ""
        evidence.append(Evidence(
            company_id=company_id,
            claim=clip(
                f"{SEARCH_HIT_CLAIM} en el puesto {hit.rank} para la consulta "
                f"«{hit.query.query}» (perfil {hit.query.profile_id}, país {hit.query.country}).{title}",
                600,
            ),
            url=hit.url, provider=SEARCH_PROVIDER,
            external_reference=f"{hit.provider_request_id or hit.local_request_id}#{hit.rank}",
            excerpt=hit.snippet, retrieved_at=hit.retrieved_at,
            kind="observed", source_type="secondary",
        ))
    return evidence


def build_company(candidate: Candidate) -> tuple[Company, list[Evidence]]:
    """Empresa pendiente de identidad, respaldada por los resultados que la localizaron."""
    company_id = uuid4()
    hit_evidence = build_hit_evidence(candidate, company_id)
    first = candidate.hits[0]
    name_evidence = Evidence(
        company_id=company_id,
        claim=f"Nombre «{candidate.name}» inferido del título o del dominio {candidate.host}; no confirmado.",
        url=first.url, provider=SEARCH_PROVIDER,
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
    return clip("; ".join(dict.fromkeys(signals)), 400)


# Identidad, duplicados y exclusiones: reglas deterministas; lo no comprobado queda pendiente.


