"""Apollo sin red: solicitudes acotadas y candidatos con procedencia verificable."""

from datetime import datetime
from decimal import Decimal
import re
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr, StringConstraints, model_validator

from prospecting.contacts import (
    ContactError, complete_name, fold_words, full_name, merge_contact,
    organization_matches, professional_email,
)
from prospecting.models import (
    Channel, ChannelStatus, Company, Contact, Contract, Evidence, IdentityStatus,
    Money, Text, UtcDatetime, utc_now,
)
from prospecting.providers.http import OperationSpec, ProviderError, ProviderRequest
from prospecting.sources import validate_public_url


PROVIDER = "apollo"
ApolloOperation = Literal["people_search", "people_enrichment"]
ApolloId = Annotated[Text, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
APOLLO_OPERATIONS = [
    OperationSpec(
        provider=PROVIDER, operation=operation,
        endpoint=f"https://api.apollo.io/api/v1/{path}", api_key_env="APOLLO_API_KEY",
        auth_header="x-api-key", auth_prefix="", headers={"Cache-Control": "no-cache"},
    )
    for operation, path in (
        ("people_search", "mixed_people/api_search"),
        ("people_enrichment", "people/match"),
    )
]


class ApolloRateLimit(Contract):
    """Solicitudes por endpoint y equipo en cada ventana; se aplican localmente antes de reservar (T17)."""

    per_minute: Annotated[StrictInt, Field(ge=1)]
    per_hour: Annotated[StrictInt, Field(ge=1)]
    per_day: Annotated[StrictInt, Field(ge=1)]

    @model_validator(mode="after")
    def validate_order(self):
        if not self.per_minute <= self.per_hour <= self.per_day:
            raise ValueError("Los límites de Apollo deben crecer de minuto a hora y a día.")
        return self


# Límites publicados para el plan Free, por equipo y endpoint (https://docs.apollo.io/reference/rate-limits,
# consultado el 2026-11-07): Search y Enrichment individual, 50 por minuto, 200 por hora y 600 por día.
FREE_RATE_LIMITS = {
    "people_search": ApolloRateLimit(per_minute=50, per_hour=200, per_day=600),
    "people_enrichment": ApolloRateLimit(per_minute=50, per_hour=200, per_day=600),
}


class ApolloAccess(Contract):
    """Comprobación de cuenta; no sustituye cupo ni autorización de sesión."""

    account_ref: Text
    enabled_operations: list[ApolloOperation] = Field(default_factory=lambda: ["people_search", "people_enrichment"])
    funding_source: Literal["free_credit", "prepaid", "new_outlay"] = "free_credit"
    source_reference: Text
    observed_at: UtcDatetime
    work_email_verified: StrictBool = False
    access_verified: StrictBool = False
    enrichment_credit_bound: Annotated[Money, Field(ge=1, le=1)] = Decimal("1")
    plan: Literal["free"] = "free"
    # Valores del panel o de la documentación del plan; con `free` solo se admiten límites iguales o más estrictos.
    rate_limits: dict[ApolloOperation, ApolloRateLimit] = Field(default_factory=lambda: dict(FREE_RATE_LIMITS))

    @model_validator(mode="after")
    def validate_access(self):
        if self.observed_at > utc_now():
            raise ValueError("La comprobación de Apollo no puede tener fecha futura.")
        if len(self.enabled_operations) != len(set(self.enabled_operations)):
            raise ValueError("No se pueden habilitar operaciones duplicadas.")
        if any(operation not in self.rate_limits for operation in self.enabled_operations):
            raise ValueError("Cada operación habilitada de Apollo necesita sus límites de solicitudes.")
        if self.plan == "free" and any(
                getattr(limit, window) > getattr(FREE_RATE_LIMITS[operation], window)
                for operation, limit in self.rate_limits.items() for window in ("per_minute", "per_hour", "per_day")):
            raise ValueError("Los límites de Apollo no pueden superar los publicados para el plan Free.")
        return self


class ApolloOrganization(BaseModel):
    id: ApolloId | None = None
    name: StrictStr | None = None
    primary_domain: StrictStr | None = None


class ApolloSearchPerson(BaseModel):
    id: ApolloId
    first_name: StrictStr | None = None
    last_name_obfuscated: StrictStr | None = None
    title: StrictStr | None = None
    last_refreshed_at: UtcDatetime | None = None
    has_email: StrictBool | None = None
    organization: ApolloOrganization | None = None


class ApolloSearchResponse(BaseModel):
    total_entries: Annotated[StrictInt, Field(ge=0)]
    people: Annotated[list[ApolloSearchPerson], Field(max_length=10)]


class ApolloEmployment(BaseModel):
    current: StrictBool | None = None
    organization_id: ApolloId | None = None
    organization_name: StrictStr | None = None
    title: StrictStr | None = None
    start_date: StrictStr | None = None
    end_date: StrictStr | None = None


class ApolloPerson(BaseModel):
    id: ApolloId
    first_name: StrictStr | None = None
    last_name: StrictStr | None = None
    name: StrictStr | None = None
    title: StrictStr | None = None
    email: StrictStr | None = None
    email_status: StrictStr | None = None
    linkedin_url: StrictStr | None = None
    organization_id: ApolloId | None = None
    organization: ApolloOrganization | None = None
    employment_history: Annotated[list[ApolloEmployment], Field(max_length=100)] = Field(default_factory=list)
    match_confidence: Literal["high", "medium", "low", "none"] | None = None


class ApolloEnrichmentResponse(BaseModel):
    person: ApolloPerson | None


def people_search_request(company: Company, roles: list[str], account_ref: str, *,
                          by_roles: bool = False, seniorities: list[str] | None = None) -> ProviderRequest:
    if company.identity_status != IdentityStatus.CONFIRMED or company.domain is None:
        raise ContactError("identity_unconfirmed", "Apollo necesita el dominio de una entidad confirmada.")
    payload = {"q_organization_domains_list": [company.domain], "page": 1, "per_page": 10}
    if seniorities is not None and not roles:
        raise ContactError("no_target_roles", "La búsqueda por catálogo requiere títulos específicos.")
    if (by_roles or seniorities is not None) and roles:
        payload["person_titles"] = list(dict.fromkeys(roles))
        payload["include_similar_titles"] = False
        if len(payload["person_titles"]) >= 100:
            raise ContactError("invalid_role_filters", "Apollo admite menos de cien títulos por búsqueda.")
        if seniorities:
            allowed = {"owner", "founder", "c_suite", "partner", "vp", "head", "director", "manager", "senior", "entry", "intern"}
            if not set(seniorities) <= allowed:
                raise ContactError("invalid_role_filters", "Apollo recibió un nivel de seniority no admitido.")
            payload["person_seniorities"] = list(dict.fromkeys(seniorities))
    return ProviderRequest(provider=PROVIDER, operation="people_search", account_ref=account_ref, payload=payload)


def enrichment_request(person_id: str, account_ref: str) -> ProviderRequest:
    if not isinstance(person_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", person_id):
        raise ContactError("identity_unconfirmed", "Enriquecer requiere un identificador observado de Apollo.")
    return ProviderRequest(provider=PROVIDER, operation="people_enrichment", account_ref=account_ref,
                           payload={"id": person_id, "reveal_personal_emails": False,
                                    "reveal_phone_number": False, "run_waterfall_email": False,
                                    "run_waterfall_phone": False})


# Motivos propios de Apollo (T17): cualquiera de ellos detiene la pasada de contactos, porque el mismo fallo
# se repetiría en todas las empresas. Apollo no documenta la respuesta de créditos agotados: un 400/422 o un
# error no documentado también detiene la pasada (fail closed). `permission_denied` y `rate_limited` se conservan.
APOLLO_STOP_REASONS = frozenset({
    "apollo_access_unverified", "apollo_api_inaccessible", "permission_denied", "rate_limited",
    "apollo_invalid_input", "apollo_not_found", "apollo_provider_error", "apollo_timeout",
    "apollo_transport_error", "apollo_invalid_response",
})


def classify_apollo_error(error: ProviderError) -> str:
    """Motivo estable de un fallo de Apollo; el mensaje literal (código y Retry-After) queda en el error."""
    if error.kind == "http":
        if error.http_status == 403 and getattr(error, "provider_code", None) == "API_INACCESSIBLE":
            return "apollo_api_inaccessible"
        return {400: "apollo_invalid_input", 401: "permission_denied", 403: "permission_denied",
                404: "apollo_not_found", 422: "apollo_invalid_input", 429: "rate_limited"}.get(
                    error.http_status, "apollo_provider_error")
    return {"timeout": "apollo_timeout", "transport": "apollo_transport_error", "local": "local_error",
            "redirect": "apollo_provider_error"}.get(error.kind, "apollo_invalid_response")


def _fact(company: Company, contact_id: UUID, identifier: str, request_id: UUID,
          retrieved_at: datetime, field: str, value: str) -> Evidence:
    return Evidence(company_id=company.id, contact_id=contact_id,
                    claim=f"Apollo informa {field}: {value}", excerpt=value[:800],
                    provider=PROVIDER, external_reference=f"apollo_v1:{identifier}:{request_id}#{field}",
                    retrieved_at=retrieved_at, kind="observed", source_type="provider")


def person_id(contact: Contact, evidence: list[Evidence]) -> str | None:
    identifiers = set()
    for fact in evidence:
        if (fact.provider != PROVIDER or fact.source_type != "provider" or fact.kind != "observed"
                or fact.contact_id != contact.id or fact.company_id != contact.company_id):
            continue
        match = re.fullmatch(r"apollo_v1:([A-Za-z0-9_-]{1,128}):[0-9a-f-]{36}#[\w:]+", fact.external_reference or "")
        if match and uuid5(contact.company_id, f"apollo:{match[1]}") == contact.id:
            identifiers.add(match[1])
    return next(iter(identifiers)) if len(identifiers) == 1 else None


def parse_search(company: Company, data: ApolloSearchResponse, request_id: UUID,
                 retrieved_at: datetime) -> list[tuple[Contact, list[Evidence]]]:
    data = ApolloSearchResponse.model_validate(data)
    results = []
    seen = set()
    for person in data.people:
        if person.id in seen:
            continue
        seen.add(person.id)
        contact_id = uuid5(company.id, f"apollo:{person.id}")
        name, _ = full_name(person.first_name, person.last_name_obfuscated)
        evidence, provenance = [], {}
        for field, value in (("name", name), ("title", person.title)):
            if value and value.strip():
                fact = _fact(company, contact_id, person.id, request_id, retrieved_at, field, value)
                evidence.append(fact)
                provenance[field] = [fact.id]
        organization = person.organization.name if person.organization else None
        evidence.append(_fact(company, contact_id, person.id, request_id, retrieved_at, "search",
                              f"id={person.id}; empresa={organization}; cargo={person.title}; "
                              f"last_refreshed_at={person.last_refreshed_at}; identidad y empleo pendientes."))
        contact = Contact(id=contact_id, company_id=company.id, name=name, name_complete=False if name else None,
                          title=person.title if person.title and person.title.strip() else None,
                          provenance=provenance)
        results.append((contact, evidence))
    return results


# Condición de entidad que People Enrichment no confirmó (T17). Solo el código se guarda, en la clave
# `contacts:apollo_rejected:<código>:<contact_id>`, sin datos de la persona ni de la respuesta.
ENTITY_MISMATCH_CODES = (
    "entity_mismatch_no_organization", "entity_mismatch_domain", "entity_mismatch_organization_id",
    "entity_mismatch_name", "entity_mismatch_not_current",
)


def _entity_mismatch(company: Company, person: ApolloPerson) -> str | None:
    """Primera condición de entidad que falla, en el orden en que se comprueban; None si todas se cumplen.

    `entity_mismatch` a secas queda para una empresa sin identidad confirmada, que nunca llega a Apollo.
    """
    organization = person.organization
    if company.identity_status != IdentityStatus.CONFIRMED or company.domain is None:
        return "entity_mismatch"
    if organization is None or organization.id is None:
        return "entity_mismatch_no_organization"
    if organization.primary_domain != company.domain:
        return "entity_mismatch_domain"
    if person.organization_id != organization.id:
        return "entity_mismatch_organization_id"
    if not organization_matches(company, organization.name):
        return "entity_mismatch_name"
    if not any(item.current is True and not item.end_date and item.organization_id == organization.id
               for item in person.employment_history):
        return "entity_mismatch_not_current"
    return None


def parse_enrichment(contact: Contact, company: Company, data: ApolloEnrichmentResponse,
                     request_id: UUID, retrieved_at: datetime) -> tuple[Contact, list[Evidence]]:
    data = ApolloEnrichmentResponse.model_validate(data)
    person = data.person
    if person is None:
        return contact, []
    if contact.company_id != company.id or contact.id != uuid5(company.id, f"apollo:{person.id}"):
        raise ContactError("identity_mismatch", "Apollo devolvió otra persona; no se asignaron sus datos.")
    if person.match_confidence != "high":
        raise ContactError("identity_unconfirmed", "Apollo no confirmó una coincidencia de identidad alta.")
    organization = person.organization
    mismatch = _entity_mismatch(company, person)
    if mismatch is not None:
        raise ContactError(mismatch, "Apollo no confirmó la entidad actual; no se asignaron sus datos.")
    name, complete = full_name(person.first_name, person.last_name)
    if name is None and person.name and person.name.strip():
        name = person.name.strip()
        complete = complete_name(name)
    if person.name and complete and fold_words(person.name) != fold_words(name):
        raise ContactError("identity_mismatch", "Apollo devolvió nombres contradictorios.")
    complete = complete and "*" not in (name or "")
    evidence, provenance = [], {}
    for field, value in (("name", name), ("title", person.title)):
        if value and value.strip():
            fact = _fact(company, contact.id, person.id, request_id, retrieved_at, field, value)
            evidence.append(fact)
            provenance[field] = [fact.id]
    employment = _fact(company, contact.id, person.id, request_id, retrieved_at, "enrichment",
                       f"id={person.id}; nombre={name}; cargo={person.title}; empresa={organization.name}; "
                       f"dominio={organization.primary_domain}; empleo actual declarado por Apollo, sin fecha del puesto.")
    evidence.append(employment)
    channels = []
    if person.email:
        fact = _fact(company, contact.id, person.id, request_id, retrieved_at, "email",
                     f"{person.email}; estado={person.email_status}; fecha de verificación no informada.")
        evidence.append(fact)
        status = {"invalid": ChannelStatus.INVALID, "bounced": ChannelStatus.INVALID,
                  "catch_all": ChannelStatus.ACCEPT_ALL, "catch-all": ChannelStatus.ACCEPT_ALL,
                  "verified": ChannelStatus.PROVIDER_VERIFIED}.get(person.email_status, ChannelStatus.UNKNOWN)
        try:
            professional = professional_email(person.email, company.domain)
            channels.append(Channel(contact_id=contact.id, type="email", value=person.email, evidence_ids=[fact.id],
                                    provider_status=person.email_status or None, normalized_status=status,
                                    retrieved_at=retrieved_at, professional=professional,
                                    direct=professional and complete,
                                    warnings=["Apollo no informa la fecha de verificación del correo; sin "
                                              "channel_policy_v2 queda pendiente."]))
        except ValueError:
            pass
    if person.linkedin_url and validate_public_url(person.linkedin_url):
        fact = _fact(company, contact.id, person.id, request_id, retrieved_at, "linkedin", person.linkedin_url)
        evidence.append(fact)
        try:
            channels.append(Channel(contact_id=contact.id, type="linkedin", value=person.linkedin_url,
                                    evidence_ids=[fact.id], retrieved_at=retrieved_at, professional=True,
                                    warnings=["Falta confirmación de acceso a mensajería desde la cuenta de ventas."]))
        except ValueError:
            pass
    update = Contact(id=contact.id, company_id=company.id, name=name, name_complete=complete if name else None,
                     title=person.title if person.title and person.title.strip() else None,
                     identity_status="confirmed" if complete else "pending", provenance=provenance,
                     employment_evidence_ids=[employment.id], channels=channels)
    return merge_contact(contact, update, evidence), evidence
