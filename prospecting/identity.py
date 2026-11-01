"""Identidad, duplicados y exclusiones (§7.2): reglas deterministas; lo no comprobado queda pendiente.

Decide con la evidencia guardada, sin red ni base de datos; el contenido externo nunca es una orden.
"""

from pathlib import Path
import re
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import AfterValidator, Field, StrictStr, model_validator

from prospecting.discovery import Candidate
from prospecting.models import (
    Campaign,
    Company,
    CompanySize,
    Contract,
    CountryCode,
    CustomerTier,
    EntityType,
    Evidence,
    IdentityStatus,
    ScaleScope,
    Segment,
    Text,
    UtcDatetime,
    _domain,
)
from prospecting.sources import domain_label, is_search_hit, within_domain
from prospecting.text import compact, plain


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

_LEGAL_SUFFIX_PATTERN = (
    r"(?:S\.?\s*A\.?\s*P\.?\s*I\.?\s+de\s+C\.?\s*V\.?"
    r"|S\.?\s*A\.?\s+de\s+C\.?\s*V\.?"
    r"|S\.?\s*de\s*R\.?\s*L\.?\s+de\s+C\.?\s*V\.?"
    r"|S\.?\s*A\.?\s*S\.?"
    r"|S\.?\s*A\.?"
    r"|Ltda\.?"
    r"|B\.?\s*V\.?"
    r"|Inc\.?"
    r"|Corp\.?"
    r"|L\.?\s*L\.?\s*C\.?)"
)
_PARENT_TOKEN = r"[A-ZÁÉÍÓÚÑ0-9][\wÁÉÍÓÚÑáéíóúñ.&'-]*"
_PARENT_STOPWORDS = r"(?!en\b|para\b|con\b|que\b|y\b|o\b|por\b|del\b|al\b|desde\b|opera\b|ayuda\b|cuenta\b)"
_BRAND_PARENT_RE = re.compile(
    rf"\b(?:una\s+)?marca(?:\s+comercial|\s+registrada)?\s+(?:de|del\s+grupo)\s+"
    rf"(?P<parent>{_PARENT_TOKEN}(?:\s+{_PARENT_STOPWORDS}{_PARENT_TOKEN}){{0,4}})"
)
_SUBSIDIARY_PARENT_RE = re.compile(
    rf"\b(?:una\s+)?(?:filial|subsidiaria|unidad\s+de\s+negocio|empresa)\s+(?:de|del\s+grupo)\s+"
    rf"(?P<parent>{_PARENT_TOKEN}(?:\s+{_PARENT_STOPWORDS}{_PARENT_TOKEN}){{0,4}})"
)

_EMPLOYEE_RANGE_RE = re.compile(
    r"\b(?:entre\s+(?P<min1>\d[\d.,]*)\s+y\s+(?P<max1>\d[\d.,]*)"
    r"|(?P<min2>\d[\d.,]*)\s*(?:-|a|to)\s*(?P<max2>\d[\d.,]*))\s+"
    r"(?:empleados|colaboradores|trabajadores|employees)\b",
    re.IGNORECASE,
)
_EMPLOYEE_MIN_RE = re.compile(
    r"\b(?:(?:más\s+de|mas\s+de|sobre|over|more\s+than)\s+(?P<min1>\d[\d.,]*)"
    r"|(?P<min2>\d[\d.,]*)\+)\s*"
    r"(?:empleados|colaboradores|trabajadores|employees)\b",
    re.IGNORECASE,
)
_EMPLOYEE_COUNT_RE = re.compile(
    r"\b(?P<count>\d[\d.,]*)\s+(?:empleados|colaboradores|trabajadores|employees)\b",
    re.IGNORECASE,
)
_PUBLIC_REVENUE_RE = re.compile(
    r"\b(?:ingresos(?:\s+anuales|\s+públicos|\s+publicos|\s+consolidados)?"
    r"|facturación(?:\s+anual)?|facturacion(?:\s+anual)?"
    r"|ventas(?:\s+anuales|\s+netas)?|revenue(?:\s+anual)?)\s+"
    r"(?:de\s+|por\s+|superiores\s+a\s+|of\s+)?"
    r"(?:USD|US\$|COP|MXN|\$)\s*\d[\d.,]*"
    r"(?:\s*(?:millones|miles\s+de\s+millones|billones|M|B|MM|bn|million|billion))?",
    re.IGNORECASE,
)
_GEO_COVERAGE_RE = re.compile(
    r"\b(?:presencia|operación|operaciones|operacion|cobertura)\s+"
    r"(?:en\s+(?:más\s+de\s+|mas\s+de\s+)?\d+\s+países(?:\s+de\s+Latinoamérica|\s+en\s+América\s+Latina)?"
    r"|(?:regional|nacional|multinacional)\s+en\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+"
    r"(?:\s*(?:,|y)\s*[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+)*)",
    re.IGNORECASE,
)
_USD_REVENUE_AMOUNT_RE = re.compile(
    r"(?:USD|US\$|\$)\s*(?P<amount>\d[\d.,]*)\s*(?P<unit>miles\s+de\s+millones|billones|billion|bn|B|millones|million|MM|M)?",
    re.IGNORECASE,
)


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
    entity_name: Text | None = None
    entity_name_evidence_ids: list[UUID] = Field(default_factory=list)
    entity_type: EntityType = EntityType.UNKNOWN
    entity_type_evidence_ids: list[UUID] = Field(default_factory=list)
    parent_company_id: UUID | None = None
    parent_evidence_ids: list[UUID] = Field(default_factory=list)
    size: CompanySize | None = None
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


def _parse_int(raw: str | None) -> int | None:
    """Convierte enteros con separadores de miles (`1.200`, `1,200`) sin inventar decimales."""
    if not raw:
        return None
    cleaned = raw.strip()
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", cleaned):
        cleaned = re.sub(r"[.,]", "", cleaned)
    elif not cleaned.isdigit():
        return None
    value = int(cleaned)
    return value if value > 0 else None


def _detect_scale_scope(excerpt: str) -> ScaleScope:
    """Determina el alcance de la señal de escala según el contexto literal del fragmento."""
    normalized = plain(excerpt)
    if re.search(r"\b(?:a nivel global|a nivel grupo|en el grupo|del grupo|consolidados|globalmente|worldwide)\b", normalized):
        return "group"
    if re.search(r"\b(?:en la filial|nuestra filial|como filial|como subsidiaria|en la subsidiaria)\b", normalized):
        return "subsidiary"
    if re.search(r"\b(?:en colombia|en mexico|a nivel nacional|en el pais)\b", normalized):
        return "country"
    return "entity"


def _derive_icp_tier(
    employee_count: int | None,
    employee_min: int | None,
    employee_max: int | None,
    public_revenue: str | None,
) -> CustomerTier:
    """Clasifica el nivel de cuenta según umbrales de How Veryfi Sells sin inventar estimaciones."""
    employees = employee_count if employee_count is not None else (employee_min if employee_min is not None else employee_max)
    usd_millions: float | None = None
    if public_revenue and not re.search(r"\b(?:COP|MXN)\b", public_revenue, re.IGNORECASE):
        match = _USD_REVENUE_AMOUNT_RE.search(public_revenue)
        if match:
            raw_amount = match.group("amount")
            unit = (match.group("unit") or "").lower()
            parsed_int = _parse_int(raw_amount)
            if parsed_int is not None:
                amount = float(parsed_int)
            else:
                try:
                    amount = float(raw_amount.replace(",", "."))
                except ValueError:
                    amount = 0.0
            if amount > 0:
                if unit in {"miles de millones", "billones", "billion", "bn", "b"}:
                    usd_millions = amount * 1000.0
                elif unit in {"millones", "million", "mm", "m"}:
                    usd_millions = amount
                elif amount >= 100_000_000:
                    usd_millions = amount / 1_000_000.0
    if (employees is not None and employees >= 1000) or (usd_millions is not None and usd_millions >= 1000):
        return "tier_1"
    if (employees is not None and 100 <= employees < 1000) or (usd_millions is not None and 100 <= usd_millions < 1000):
        return "tier_2"
    if employees is not None and employees < 100:
        return "tier_3"
    return "unknown"


def extract_company_size(facts: list[Evidence]) -> CompanySize | None:
    """Extrae señales explícitas de escala desde evidencia observada primaria o de proveedor.

    Nunca utiliza resúmenes de búsqueda (`search_result`) ni inventa cifras ausentes.
    """
    eligible = [
        item for item in facts
        if item.kind == "observed"
        and item.source_type in ("primary", "provider")
        and not is_search_hit(item)
        and item.excerpt
    ]
    employee_count: int | None = None
    employee_min: int | None = None
    employee_max: int | None = None
    public_revenue: str | None = None
    geographic_coverage: str | None = None
    scope: ScaleScope = "unknown"
    snippets: list[str] = []
    evidence_ids: list[UUID] = []

    for item in eligible:
        excerpt = item.excerpt or ""
        matched_here = False
        if employee_count is None and employee_min is None and employee_max is None:
            range_match = _EMPLOYEE_RANGE_RE.search(excerpt)
            if range_match:
                low = _parse_int(range_match.group("min1") or range_match.group("min2"))
                high = _parse_int(range_match.group("max1") or range_match.group("max2"))
                if low is not None and high is not None and high >= low:
                    employee_min, employee_max = low, high
                    snippets.append(re.sub(r"\s+", " ", range_match.group(0)).strip())
                    matched_here = True
            if not matched_here:
                min_match = _EMPLOYEE_MIN_RE.search(excerpt)
                if min_match:
                    low = _parse_int(min_match.group("min1") or min_match.group("min2"))
                    if low is not None:
                        employee_min = low
                        snippets.append(re.sub(r"\s+", " ", min_match.group(0)).strip())
                        matched_here = True
            if not matched_here:
                count_match = _EMPLOYEE_COUNT_RE.search(excerpt)
                if count_match:
                    exact = _parse_int(count_match.group("count"))
                    if exact is not None:
                        employee_count = exact
                        snippets.append(re.sub(r"\s+", " ", count_match.group(0)).strip())
                        matched_here = True

        if public_revenue is None:
            rev_match = _PUBLIC_REVENUE_RE.search(excerpt)
            if rev_match:
                public_revenue = re.sub(r"\s+", " ", rev_match.group(0)).strip()
                snippets.append(public_revenue)
                matched_here = True

        if geographic_coverage is None:
            geo_match = _GEO_COVERAGE_RE.search(excerpt)
            if geo_match:
                geographic_coverage = re.sub(r"\s+", " ", geo_match.group(0)).strip()
                snippets.append(geographic_coverage)
                matched_here = True

        if matched_here:
            evidence_ids.append(item.id)
            if scope == "unknown":
                scope = _detect_scale_scope(excerpt)

    if not evidence_ids:
        return None

    icp_tier = _derive_icp_tier(employee_count, employee_min, employee_max, public_revenue)
    return CompanySize(
        original_value="; ".join(dict.fromkeys(snippets)),
        public_revenue=public_revenue,
        geographic_coverage=geographic_coverage,
        scope=scope,
        icp_tier=icp_tier,
        employee_count=employee_count,
        employee_min=employee_min,
        employee_max=employee_max,
        evidence_ids=list(dict.fromkeys(evidence_ids)),
    )


def _clean_parent_name(raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw).strip(" .,;:()[]{}\"'")
    return cleaned


def extract_entity_structure(
    company: Company,
    observed_name: str | None,
    primary: list[Evidence],
    confirmed: list[Company],
) -> tuple[str | None, list[UUID], EntityType, list[UUID], UUID | None, list[UUID], str | None]:
    """Distingue razón social, marca, filial y matriz a partir de evidencia primaria observada."""
    candidate_names = [
        value for value in dict.fromkeys([observed_name or company.name, company.name, *(company.aliases or [])])
        if value and len(compact(value)) >= 3
    ]
    entity_name: str | None = None
    entity_name_ids: list[UUID] = []
    entity_type: EntityType = EntityType.UNKNOWN
    entity_type_ids: list[UUID] = []
    parent_company_id: UUID | None = None
    parent_ids: list[UUID] = []
    parent_name_detected: str | None = None

    for item in primary:
        excerpt = item.excerpt or ""
        if entity_name is None:
            for base_name in candidate_names:
                legal_re = re.compile(
                    rf"(?<!\w)({re.escape(base_name)}(?:,?\s+{_LEGAL_SUFFIX_PATTERN}))(?!\w)",
                    re.IGNORECASE,
                )
                found = legal_re.search(excerpt)
                if found:
                    entity_name = re.sub(r"\s+", " ", found.group(1)).strip()
                    entity_name_ids.append(item.id)
                    break

        brand_match = _BRAND_PARENT_RE.search(excerpt)
        if brand_match:
            candidate_parent = _clean_parent_name(brand_match.group("parent"))
            if len(compact(candidate_parent)) >= 3 and compact(candidate_parent) != compact(company.name):
                entity_type = EntityType.BRAND
                entity_type_ids.append(item.id)
                if parent_name_detected is None:
                    parent_name_detected = candidate_parent
                    parent_ids.append(item.id)
                continue

        subsidiary_match = _SUBSIDIARY_PARENT_RE.search(excerpt)
        if subsidiary_match:
            candidate_parent = _clean_parent_name(subsidiary_match.group("parent"))
            if len(compact(candidate_parent)) >= 3 and compact(candidate_parent) != compact(company.name):
                if entity_type != EntityType.BRAND:
                    entity_type = EntityType.SUBSIDIARY
                    entity_type_ids.append(item.id)
                if parent_name_detected is None:
                    parent_name_detected = candidate_parent
                    parent_ids.append(item.id)
                continue

    if entity_type == EntityType.UNKNOWN and entity_name is not None:
        entity_type = EntityType.LEGAL_ENTITY
        entity_type_ids = list(entity_name_ids)

    if parent_name_detected is not None:
        target = compact(parent_name_detected)
        for other in confirmed:
            if other.id == company.id or other.parent_company_id == company.id:
                continue
            other_names = {
                compact(value)
                for value in (other.name, *(other.aliases or []), *([other.entity_name] if other.entity_name else []))
                if value
            }
            if target in other_names:
                parent_company_id = other.id
                break

    return (
        entity_name,
        list(dict.fromkeys(entity_name_ids)),
        entity_type,
        list(dict.fromkeys(entity_type_ids)),
        parent_company_id,
        list(dict.fromkeys(parent_ids)) if parent_company_id is not None else [],
        parent_name_detected,
    )


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
    (
        entity_name,
        entity_name_ids,
        entity_type,
        entity_type_ids,
        parent_company_id,
        parent_ids,
        parent_name_detected,
    ) = extract_entity_structure(company, observed_name, primary, confirmed)
    size = extract_company_size(facts)
    warnings = []
    local = tuple(suffix for country in campaign.countries for suffix in _COUNTRY_SUFFIXES.get(country, ()))
    if domain and domain.endswith(_FOREIGN_SUFFIXES) and not domain.endswith(local):
        warnings.append("Dominio con ccTLD de otro país; el país de operación requiere confirmación.")
    if parent_name_detected is not None and parent_company_id is None:
        warnings.append(
            f"Relación con matriz o grupo detectada ({parent_name_detected}); entidad evaluada por separado."
        )
    base = {
        "operating_countries": countries or None,
        "country_evidence_ids": list(dict.fromkeys(country_ids)),
        "segments": segments or None,
        "segment_evidence_ids": list(dict.fromkeys(segment_ids)),
        "warnings": warnings,
        "name": observed_name if observed_name and compact(observed_name) != compact(company.name) else None,
        "name_evidence_ids": list(dict.fromkeys(name_ids)),
        "entity_name": entity_name,
        "entity_name_evidence_ids": entity_name_ids,
        "entity_type": entity_type,
        "entity_type_evidence_ids": entity_type_ids,
        "parent_company_id": parent_company_id,
        "parent_evidence_ids": parent_ids,
        "size": size,
    }
    names = [
        company.name,
        *(company.aliases or []),
        *([observed_name] if observed_name else []),
        *([entity_name] if entity_name else []),
        *([parent_name_detected] if parent_name_detected else []),
    ]
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
