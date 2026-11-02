"""Consultas de plantilla, candidatos y selección del descubrimiento (§7.1); sin red ni base de datos.

Los resultados del buscador son datos no confiables: solo localizan fuentes y
nunca modifican límites, consultas ni instrucciones del flujo.
"""

from pathlib import Path
import re
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import Field, StrictBool, StrictInt

from prospecting.models import (
    Campaign,
    Company,
    Contract,
    Count,
    CountryCode,
    Evidence,
    IcpEnterpriseConfig,
    Segment,
    Text,
    UtcDatetime,
)
from prospecting.sources import (
    SEARCH_HIT_CLAIM,
    SEARCH_PROVIDER,
    domain_label,
    is_search_hit,
    url_host,
    within_domain,
)
from prospecting.text import clip, compact, plain


LEGACY_TEMPLATE_VERSION = "discovery_queries_v1"
ENTERPRISE_TEMPLATE_VERSION = "discovery_queries_v2"
TEMPLATE_VERSION = ENTERPRISE_TEMPLATE_VERSION
MAX_HITS_PER_CANDIDATE = 5

# Nombre para la consulta y valor del enum `country` de Tavily (sin tildes).
COUNTRIES = {"CO": ("Colombia", "colombia"), "MX": ("México", "mexico")}

# Plantillas iniciales v1 conservadas para reproducibilidad histórica y comparación (§7.1, T13).
QUERY_TEMPLATES_V1 = {
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

# Plantillas calibradas v2 orientadas a cuentas grandes/enterprise con señal documental (T13).
QUERY_TEMPLATES_V2 = {
    "expense_reimbursement": (
        "plataforma corporativa de tarjetas empresariales y control de gastos que escanea recibos en {country}",
        "software enterprise de reembolsos y viáticos con captura OCR de comprobantes para corporativos en {country}",
    ),
    "payments_ap_erp": (
        "plataforma enterprise de cuentas por pagar y ERP que automatiza facturas de proveedores en {country}",
        "software corporativo de tesorería y pagos B2B con recepción y lectura de facturas en {country}",
    ),
    "cpg_brands": (
        "empresa de consumo masivo alimentos bebidas cuidado personal promoción registra tu factura o ticket en {country}",
        "grupo empresarial consumo masivo programa de lealtad sube tu ticket de compra y gana premios en {country}",
    ),
    "loyalty_platforms_agencies": (
        "plataforma enterprise de fidelización y shopper marketing que valida tickets y facturas de compra en {country}",
        "agencia corporativa de promociones B2B y lealtad para grandes marcas con lectura de recibos en {country}",
    ),
}

QUERY_TEMPLATES = QUERY_TEMPLATES_V2
TEMPLATE_REGISTRY = {
    LEGACY_TEMPLATE_VERSION: QUERY_TEMPLATES_V1,
    ENTERPRISE_TEMPLATE_VERSION: QUERY_TEMPLATES_V2,
}

_TITLE_SEPARATORS = re.compile(r"\s+[|\-–—:·»]\s+")
_PROMO_SUBDOMAIN_PREFIXES = ("promo.", "promociones.", "gana.", "puntos.", "recompensas.")
_DOCUMENT_SIGNAL_KEYWORDS = (
    "recibo", "recibos", "factura", "facturas", "ticket", "tickets", "comprobante", "comprobantes",
    "ocr", "escanea", "captura", "reembolso", "reembolsos", "cuentas por pagar", "fidelizacion",
    "lealtad", "promocion", "promociones", "puntos", "recompensa", "recompensas", "receipt", "invoice",
)
_ENTERPRISE_SIGNAL_KEYWORDS = (
    "corporativo", "corporativa", "corporativos", "enterprise", "empresarial", "empresariales",
    "multinacional", "grupo empresarial", "consumo masivo", "cpg", "erp", "tesoreria", "b2b",
    "grandes empresas", "grandes marcas", "tarjetas corporativas",
)
_NO_FIT_CONGLOMERATE_KEYWORDS = (
    "mineria", "petroleo", "cementera", "siderurgica", "infraestructura vial",
    "generacion electrica", "constructora pesada", "exploracion petrolera",
)


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


class CandidateSignals(Contract):
    host: Text
    has_document_signal: StrictBool
    has_enterprise_signal: StrictBool
    has_no_fit_signal: StrictBool
    is_promo_subdomain: StrictBool


class CombinationReport(Contract):
    country: CountryCode
    segment: Segment
    candidates: Count
    selected: Count
    insufficient: StrictBool


class DiscoveryComparison(Contract):
    """Comparación reproducible entre plantillas de descubrimiento v1 y v2 sin red ni proveedores extra."""

    v1_template_version: Text
    v2_template_version: Text
    v1_selected_hosts: list[Text]
    v2_selected_hosts: list[Text]
    v1_enterprise_candidates: Count
    v2_enterprise_candidates: Count
    v1_document_candidates: Count
    v2_document_candidates: Count
    v1_no_fit_candidates: Count
    v2_no_fit_candidates: Count
    shared_hosts: list[Text]
    added_in_v2: list[Text]
    removed_in_v2: list[Text]


def load_icp_enterprise(path: Path = Path("config/icp_enterprise.json")) -> IcpEnterpriseConfig:
    """Carga y valida el catálogo versionado de calibración ICP enterprise (T13)."""
    return IcpEnterpriseConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _resolve_template_version(campaign: Campaign, template_version: str | None) -> str:
    if template_version is not None:
        if template_version not in TEMPLATE_REGISTRY:
            raise ValueError(f"Versión de plantillas de descubrimiento desconocida: {template_version}.")
        return template_version
    if campaign.config_snapshot.people_provider is None:
        return LEGACY_TEMPLATE_VERSION
    return ENTERPRISE_TEMPLATE_VERSION


def build_search_queries(campaign: Campaign, *, template_version: str | None = None) -> list[PlannedQuery]:
    """Consultas de plantilla solo para países y segmentos de la campaña."""
    version = _resolve_template_version(campaign, template_version)
    templates = TEMPLATE_REGISTRY[version]
    profiles = {
        segment: [
            profile for profile in campaign.config_snapshot.profiles
            if profile.segment == segment and profile.id in templates
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
                    query = templates[profile.id][template_index].format(country=COUNTRIES[country][0])
                    planned.append(PlannedQuery(
                        country=country, segment=segment, profile_id=profile.id,
                        template_version=version,
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


def candidate_signals(candidate: Candidate) -> CandidateSignals:
    """Evalúa señales observables de necesidad documental, escala enterprise y no-fit en un candidato."""
    combined = plain(" ".join(
        f"{hit.title or ''} {hit.snippet or ''}" for hit in candidate.hits
    ))
    has_doc = any(re.search(rf"\b{re.escape(term)}\b", combined) for term in _DOCUMENT_SIGNAL_KEYWORDS)
    has_ent = any(re.search(rf"\b{re.escape(term)}\b", combined) for term in _ENTERPRISE_SIGNAL_KEYWORDS)
    has_no_fit = (not has_doc) and any(
        re.search(rf"\b{re.escape(term)}\b", combined) for term in _NO_FIT_CONGLOMERATE_KEYWORDS
    )
    is_promo = candidate.host.startswith(_PROMO_SUBDOMAIN_PREFIXES)
    return CandidateSignals(
        host=candidate.host,
        has_document_signal=has_doc,
        has_enterprise_signal=has_ent,
        has_no_fit_signal=has_no_fit,
        is_promo_subdomain=is_promo,
    )


def _candidate_priority_key(candidate: Candidate) -> tuple[int, int, int, int, int]:
    signals = candidate_signals(candidate)
    return (
        1 if signals.has_no_fit_signal else 0,
        0 if (signals.has_document_signal and signals.has_enterprise_signal) else 1,
        0 if signals.has_document_signal else 1,
        1 if signals.is_promo_subdomain else 0,
        0 if signals.has_enterprise_signal else 1,
    )


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
    """Reparte la selección por país/segmento priorizando encaje documental + enterprise en v2."""
    combos = [(country, segment) for country in campaign.countries for segment in campaign.segments]
    queues: dict[tuple[CountryCode, Segment], list[Candidate]] = {combo: [] for combo in combos}
    for candidate in candidates:
        first = candidate.hits[0].query
        queues.setdefault((first.country, first.segment), []).append(candidate)
    for combo, queue in queues.items():
        if queue and any(item.hits[0].query.template_version != LEGACY_TEMPLATE_VERSION for item in queue):
            queue.sort(key=_candidate_priority_key)
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


def compare_discovery_versions(
    campaign: Campaign,
    hits_v1: list[SearchHit],
    hits_v2: list[SearchHit],
    *,
    excluded_domains: list[str] | set[str] = (),
) -> DiscoveryComparison:
    """Compara de forma reproducible los candidatos seleccionados por v1 y v2 bajo los mismos topes."""
    raw_limit = campaign.limits.discovery.raw_candidates
    excluded = [domain.lower() for domain in excluded_domains]

    def _run_selection(hits: list[SearchHit]) -> list[Candidate]:
        grouped, _ = group_candidates(hits, raw_limit)
        kept = [
            item for item in grouped
            if not any(within_domain(item.host, domain) for domain in excluded)
        ]
        selected, _ = select_candidates(kept, campaign)
        return selected

    selected_v1 = _run_selection(hits_v1)
    selected_v2 = _run_selection(hits_v2)
    signals_v1 = [candidate_signals(item) for item in selected_v1]
    signals_v2 = [candidate_signals(item) for item in selected_v2]
    hosts_v1 = [item.host for item in selected_v1]
    hosts_v2 = [item.host for item in selected_v2]
    set_v1, set_v2 = set(hosts_v1), set(hosts_v2)

    return DiscoveryComparison(
        v1_template_version=LEGACY_TEMPLATE_VERSION,
        v2_template_version=ENTERPRISE_TEMPLATE_VERSION,
        v1_selected_hosts=hosts_v1,
        v2_selected_hosts=hosts_v2,
        v1_enterprise_candidates=sum(s.has_document_signal and s.has_enterprise_signal for s in signals_v1),
        v2_enterprise_candidates=sum(s.has_document_signal and s.has_enterprise_signal for s in signals_v2),
        v1_document_candidates=sum(s.has_document_signal for s in signals_v1),
        v2_document_candidates=sum(s.has_document_signal for s in signals_v2),
        v1_no_fit_candidates=sum(s.has_no_fit_signal for s in signals_v1),
        v2_no_fit_candidates=sum(s.has_no_fit_signal for s in signals_v2),
        shared_hosts=[host for host in hosts_v2 if host in set_v1],
        added_in_v2=[host for host in hosts_v2 if host not in set_v1],
        removed_in_v2=[host for host in hosts_v1 if host not in set_v2],
    )


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


# Análisis inicial y ampliación de evidencia de una empresa ya descubierta (§7, §9).

RESEARCH_QUERY_VERSION = "research_queries_v1"
RESEARCH_TERMS = {
    Segment.FINTECH_SOFTWARE: "recibos facturas comprobantes gastos",
    Segment.CPG_LOYALTY: "promoción ticket factura de compra premios",
}


def initial_urls(company: Company, evidence: list[Evidence], limit: int) -> list[str]:
    """Páginas propias que el buscador ya localizó y, si queda cupo, la portada con el host observado."""
    if company.domain is None or limit <= 0:
        return []
    own = [str(item.url) for item in evidence if is_search_hit(item) and item.url is not None
           and url_host(str(item.url)) is not None and within_domain(url_host(str(item.url)), company.domain)]
    first = urlsplit(own[0]) if own else None
    home = f"{first.scheme}://{first.netloc}/" if first else f"https://{company.domain}/"
    return list(dict.fromkeys([*own, home]))[:limit]


def expansion_query(company: Company, campaign: Campaign) -> str:
    """Consulta de plantilla de la ampliación; se restringe al dominio de la empresa al buscar."""
    segments = [segment for segment in campaign.segments if segment in (company.segments or campaign.segments)]
    countries = [COUNTRIES[country][0] for country in campaign.countries if country in COUNTRIES]
    return clip(" ".join([company.name, *(RESEARCH_TERMS[segment] for segment in segments), *countries]), 400)
