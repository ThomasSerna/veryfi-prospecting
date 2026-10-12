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
    Campaign, Company, Contract, CountryCode, Evidence, IdentityStatus, Segment, Text, UtcDatetime, _domain,
)
from prospecting.sources import domain_label, within_domain
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
