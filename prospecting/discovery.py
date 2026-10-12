"""Consultas, lectura y selección de candidatos de Tavily; sin red ni base de datos.

Los resultados del buscador son datos no confiables: solo localizan fuentes y
nunca modifican límites, consultas ni instrucciones del flujo.
"""

from datetime import datetime
from pathlib import Path
import re
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import (
    AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator,
)

from prospecting.models import (
    Campaign, Company, Contract, Count, CountryCode, DiscoveryLimits, Evidence,
    IdentityStatus, Segment, Text, UtcDatetime, _domain,
)
from prospecting.providers import OperationSpec, ProviderError, ProviderRequest
from prospecting.sources import (
    NON_BUSINESS_DOMAINS, SEARCH_HIT_CLAIM, SEARCH_PROVIDER, domain_label, is_non_business, url_host,
    within_domain,
)
from prospecting.text import clip, compact, plain


TEMPLATE_VERSION = "discovery_queries_v1"
PROVIDER = SEARCH_PROVIDER
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
            title=clip(result.title, TITLE_CHARS), snippet=clip(result.content, SNIPPET_CHARS),
            rank=rank, query=planned, query_index=query_index,
            local_request_id=local_request_id,
            provider_request_id=clip(response.request_id, 120),
            retrieved_at=retrieved_at,
        ))
    return hits, discarded


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
            url=hit.url, provider=PROVIDER,
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
    return clip("; ".join(dict.fromkeys(signals)), 400)


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


# Identidad, duplicados y exclusiones: reglas deterministas; lo no comprobado queda pendiente.

EXCLUSION_PROVIDER = "veryfi_exclusions"
ExclusionStatus = Literal["missing", "pending", "validated"]

_COUNTRY_SUFFIXES = {"CO": (".com.co", ".net.co", ".org.co"), "MX": (".mx",)}
_COUNTRY_TEXT = {
    "CO": re.compile(r"\bcolombia(?:no|na|nos|nas)?\b"),
    "MX": re.compile(r"\bmexic(?:o|ano|ana|anos|anas)\b"),
}
_COUNTRY_PATH = {
    "CO": re.compile(r"/(?:colombia|co|es-co)(?:/|$)"),
    "MX": re.compile(r"/(?:mexico|mx|es-mx)(?:/|$)"),
}
_FOREIGN_SUFFIXES = (
    ".es", ".br", ".ar", ".cl", ".pe", ".ec", ".uy", ".py", ".bo", ".ve", ".gt", ".cr",
    ".pa", ".do", ".sv", ".hn", ".ni", ".us", ".ca", ".uk", ".pt", ".fr", ".de", ".it",
)
# Palabras clave derivadas de las señales de los perfiles de config/veryfi.json.
SEGMENT_KEYWORDS = {
    Segment.FINTECH_SOFTWARE: (
        "recibo", "recibos", "factura", "facturas", "gasto", "gastos", "reembolso", "reembolsos",
        "cuentas por pagar", "conciliacion", "receipt", "receipts", "invoice", "invoices",
        "expense", "expenses",
    ),
    Segment.CPG_LOYALTY: (
        "ticket", "tickets", "promocion", "promociones", "premio", "premios", "puntos",
        "fidelizacion", "lealtad", "recompensa", "recompensas", "loyalty", "rewards",
    ),
}

DomainName = Annotated[StrictStr, AfterValidator(_domain)]


class ExclusionEntry(Contract):
    """Cuenta suministrada por Veryfi; el alcance decide a qué entidades aplica."""

    id: Text
    name: Text
    domains: list[DomainName] = Field(default_factory=list)
    aliases: list[Text] = Field(default_factory=list)
    scope: Literal["entity", "country", "group"]
    countries: list[CountryCode] = Field(default_factory=list)
    reason: Literal["current_customer", "open_opportunity", "excluded"]
    detail: Text | None = None
    source_reference: Text

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if (self.scope == "country") != bool(self.countries):
            raise ValueError("Los países se indican solo, y siempre, en el alcance por país.")
        return self


class ExclusionList(Contract):
    version: Text
    validation_status: Literal["pending", "validated"]
    source_reference: Text
    observed_at: UtcDatetime
    entries: list[ExclusionEntry]

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        if len({entry.id for entry in self.entries}) != len(self.entries):
            raise ValueError("Cada exclusión necesita un identificador único.")
        return self


class ExclusionMatch(Contract):
    version: Text
    entry_id: Text
    scope: Literal["entity", "country", "group"]
    reason: Literal["current_customer", "open_opportunity", "excluded"]
    strength: Literal["confirmed", "ambiguous"]


class IdentityDecision(Contract):
    status: Literal["confirmed", "pending", "excluded"]
    stop_reason: Text | None = None
    identity_key: Text | None = None
    name: Text | None = None
    name_evidence_ids: list[UUID] = Field(default_factory=list)
    operating_countries: list[CountryCode] | None = None
    country_evidence_ids: list[UUID] = Field(default_factory=list)
    segments: list[Segment] | None = None
    segment_evidence_ids: list[UUID] = Field(default_factory=list)
    exclusion: ExclusionMatch | None = None
    warnings: list[Text] = Field(default_factory=list)


def load_exclusions(path: Path) -> ExclusionList | None:
    """None si el archivo no existe; un archivo inválido nunca equivale a lista vacía."""
    path = Path(path)
    if not path.exists():
        return None
    return ExclusionList.model_validate_json(path.read_text(encoding="utf-8"))


def exclusions_status(exclusions: ExclusionList | None) -> ExclusionStatus:
    """Todo lo que no sea `validated` se muestra como exclusiones comerciales no validadas."""
    return "missing" if exclusions is None else exclusions.validation_status


def match_exclusion(host: str | None, names, countries,
                    exclusions: ExclusionList | None) -> ExclusionMatch | None:
    """El dominio confirma la exclusión; el nombre solo, no (puede ser un homónimo)."""
    if exclusions is None:
        return None
    folded = {compact(name) for name in names if name and len(compact(name)) >= 3}
    countries = set(countries or ())
    ambiguous = None
    for entry in exclusions.entries:
        domain_hit = host is not None and any(within_domain(host, domain) for domain in entry.domains)
        name_hit = bool(folded & {compact(value) for value in (entry.name, *entry.aliases)})
        if not (domain_hit or name_hit):
            continue
        if entry.scope == "country":
            if countries and not countries & set(entry.countries):
                continue
            # Sin país conocido no se puede confirmar el alcance de la exclusión.
            domain_hit = domain_hit and bool(countries)
        match = ExclusionMatch(
            version=exclusions.version, entry_id=entry.id, scope=entry.scope, reason=entry.reason,
            strength="confirmed" if domain_hit else "ambiguous",
        )
        if domain_hit:
            return match
        ambiguous = ambiguous or match
    return ambiguous


def exclusion_evidence(company_id: UUID, match: ExclusionMatch, exclusions: ExclusionList) -> Evidence:
    """Hecho determinista: repetir la resolución no duplica evidencia inmutable."""
    confirmed = match.strength == "confirmed"
    claim = (
        f"La lista de exclusiones {match.version} ({exclusions.validation_status}) incluye el dominio "
        f"de esta empresa: motivo {match.reason}, alcance {match.scope}."
        if confirmed else
        f"El nombre coincide con la entrada {match.entry_id} de la lista de exclusiones "
        f"{match.version}, pero no el dominio; requiere revisión humana."
    )
    seed = ":".join(("veryfi-exclusion", str(company_id), match.version,
                     exclusions.validation_status, match.entry_id, match.strength))
    return Evidence(
        id=uuid5(NAMESPACE_URL, seed),
        company_id=company_id, claim=claim, provider=EXCLUSION_PROVIDER,
        external_reference=f"{match.version}:{match.entry_id}", retrieved_at=exclusions.observed_at,
        kind="observed" if confirmed else "inference", source_type="manual",
    )


def find_reusable(candidate: Candidate, companies: list[Company]) -> Company | None:
    """Solo una identidad confirmada con el mismo dominio, nombre y país se reutiliza."""
    country = candidate.hits[0].query.country
    name = compact(candidate.name)
    for company in companies:
        if (company.identity_status == IdentityStatus.CONFIRMED and company.domain == candidate.host
                and country in (company.operating_countries or [])
                and name in {compact(value) for value in (company.name, *(company.aliases or []))}):
            return company
    return None


def _mentions(pattern: re.Pattern, item: Evidence) -> bool:
    return bool(pattern.search(plain(item.excerpt or "")))


def assess_identity(company: Company, evidence: list[Evidence], campaign: Campaign,
                    exclusions: ExclusionList | None, confirmed: list[Company],
                    campaign_company_ids: set[UUID]) -> IdentityDecision:
    """Decide la identidad con la evidencia guardada; el contenido externo nunca es una orden."""
    facts = [item for item in evidence if item.company_id == company.id and item.contact_id is None]
    primary = [item for item in facts if item.source_type == "primary" and item.kind == "observed"]
    domain = company.domain
    countries, country_ids = [], []
    for country in campaign.countries:
        ids = []
        if domain and domain.endswith(_COUNTRY_SUFFIXES.get(country, ())):
            ids += company.provenance.get("domain", [])
        for item in primary:
            path = urlsplit(str(item.url)).path.lower() if item.url else ""
            if (country in _COUNTRY_TEXT and _mentions(_COUNTRY_TEXT[country], item)
                    or country in _COUNTRY_PATH and _COUNTRY_PATH[country].search(path)):
                ids.append(item.id)
        if ids:
            countries.append(country)
            country_ids += ids
    segments, segment_ids = [], []
    for segment in campaign.segments:
        patterns = [re.compile(rf"\b{re.escape(keyword)}\b") for keyword in SEGMENT_KEYWORDS.get(segment, ())]
        ids = [item.id for item in primary if any(_mentions(pattern, item) for pattern in patterns)]
        if ids:
            segments.append(segment)
            segment_ids += ids
    name = plain(company.name)
    name_ids = [
        item.id for item in primary
        if len(name.replace(" ", "")) >= 3 and _mentions(re.compile(rf"\b{re.escape(name)}\b"), item)
    ]
    observed_name = None
    if not name_ids and domain:
        # El nombre inferido no aparece: vale la etiqueta del dominio en su forma observada.
        label = domain_label(domain)
        pattern = re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, label.split("-"))) + r"(?!\w)", re.IGNORECASE)
        for item in primary:
            found = pattern.search(item.excerpt or "") if len(label.replace("-", "")) >= 3 else None
            if found:
                observed_name = observed_name or re.sub(r"\s+", " ", found.group(0))
                name_ids.append(item.id)
    warnings = []
    local = tuple(suffix for country in campaign.countries for suffix in _COUNTRY_SUFFIXES.get(country, ()))
    if domain and domain.endswith(_FOREIGN_SUFFIXES) and not domain.endswith(local):
        warnings.append("Dominio con ccTLD de otro país; el país de operación requiere confirmación.")
    base = {
        "operating_countries": countries or None,
        "country_evidence_ids": list(dict.fromkeys(country_ids)),
        "segments": segments or None,
        "segment_evidence_ids": list(dict.fromkeys(segment_ids)),
        "warnings": warnings,
        "name": observed_name if observed_name and compact(observed_name) != compact(company.name) else None,
        "name_evidence_ids": list(dict.fromkeys(name_ids)),
    }
    names = [company.name, *(company.aliases or []), *([observed_name] if observed_name else [])]
    match = match_exclusion(domain, names, countries, exclusions)
    if match is not None and match.strength == "confirmed":
        return IdentityDecision(status="excluded", stop_reason="excluded_account", exclusion=match, **base)
    for reason, failed in (
        ("domain_unknown", domain is None), ("identity_unverified", not primary),
        ("name_unconfirmed", not name_ids), ("country_unconfirmed", not countries),
        ("exclusion_review", match is not None),
    ):
        if failed:
            return IdentityDecision(status="pending", stop_reason=reason, exclusion=match, **base)
    key = f"{domain}|{compact(observed_name or company.name)}|{'+'.join(sorted(countries))}"
    for other in confirmed:
        if other.id != company.id and other.identity_key == key:
            if other.id in campaign_company_ids:
                return IdentityDecision(status="excluded", stop_reason=f"duplicate_of:{other.id}", **base)
            return IdentityDecision(status="pending", stop_reason=f"duplicate_review:{other.id}", **base)
    return IdentityDecision(status="confirmed", identity_key=key, **base)
