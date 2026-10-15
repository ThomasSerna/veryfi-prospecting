"""Adaptador de Hunter: acceso comprobado, operaciones, solicitudes, respuestas, créditos y errores.

Sin red ni base de datos: convierte respuestas no confiables en Contact, Channel y Evidence
con procedencia de proveedor; las reglas de listo están en `prospecting.contacts`.
"""

from datetime import datetime
import re
from typing import Annotated, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import (
    AfterValidator, BaseModel, Field, StrictBool, StrictInt, StrictStr, model_validator,
)

from prospecting.contacts import (
    ContactError, fold_words, full_name, merge_contact, organization_matches, parse_source_date,
    phone_country_of, professional_email,
)
from prospecting.models import (
    Channel, ChannelStatus, ChannelType, Company, Contact, Contract, Evidence, IdentityStatus, Text,
    UtcDatetime, utc_now,
)
from prospecting.providers.http import OperationSpec, ProviderError, ProviderRequest
from prospecting.sources import validate_public_url


PROVIDER = "hunter"
HunterOperation = Literal["domain_search", "email_finder", "email_verifier"]


HUNTER_OPERATIONS = [
    OperationSpec(provider=PROVIDER, operation=operation, endpoint=f"https://api.hunter.io/v2/{path}",
                  method="GET", api_key_env="HUNTER_API_KEY", timeout_seconds=timeout)
    for operation, path, timeout in (
        ("domain_search", "domain-search", 10.0),
        ("email_finder", "email-finder", 10.0),
        ("email_verifier", "email-verifier", 25.0),
    )
]


class HunterAccess(Contract):
    """Acceso comprobado; el saldo y su valoración pertenecen a AccountAllowance."""

    search_account_ref: Text
    verification_account_ref: Text | None = None
    enabled_operations: list[HunterOperation]
    unified_credits: StrictBool = True
    automatic_lead_saving_disabled: StrictBool = False
    funding_source: Literal["free_credit", "prepaid", "new_outlay"]
    source_reference: Text
    checked_at: UtcDatetime

    @model_validator(mode="after")
    def validate_pools(self):
        if self.checked_at > utc_now():
            raise ValueError("La comprobación de acceso a Hunter no puede tener fecha futura.")
        if len(self.enabled_operations) != len(set(self.enabled_operations)):
            raise ValueError("No se pueden habilitar operaciones duplicadas.")
        if self.unified_credits and self.verification_account_ref not in (None, self.search_account_ref):
            raise ValueError("Los créditos unificados necesitan una sola cuenta de consumo.")
        if not self.unified_credits and "email_verifier" in self.enabled_operations:
            if self.verification_account_ref in (None, self.search_account_ref):
                raise ValueError("Las cuotas separadas necesitan referencias de consumo distintas.")
        return self


def _source_date(value: str) -> str:
    parse_source_date(value)
    return value


SourceDate = Annotated[StrictStr, AfterValidator(_source_date)]


class HunterSource(BaseModel):
    uri: StrictStr | None = None
    domain: StrictStr | None = None
    extracted_on: SourceDate | None = None
    last_seen_on: SourceDate | None = None
    still_on_page: StrictBool | None = None


class HunterVerification(BaseModel):
    date: SourceDate | None = None
    status: StrictStr | None = None


class HunterPerson(BaseModel):
    id: StrictInt | StrictStr | None = None
    value: StrictStr | None = None
    type: StrictStr | None = None
    first_name: StrictStr | None = None
    last_name: StrictStr | None = None
    position: StrictStr | None = None
    position_raw: StrictStr | None = None
    department: StrictStr | None = None
    linkedin: StrictStr | None = None
    phone_number: StrictStr | None = None
    verification: HunterVerification | None = None
    sources: Annotated[list[HunterSource], Field(max_length=20)] = Field(default_factory=list)


class HunterDomainData(BaseModel):
    domain: StrictStr | None = None
    organization: StrictStr | None = None
    webmail: StrictBool | None = None
    disposable: StrictBool | None = None
    accept_all: StrictBool | None = None
    emails: Annotated[list[HunterPerson], Field(max_length=10)] = Field(default_factory=list)


class HunterDomainSearchResponse(BaseModel):
    data: HunterDomainData | None = None


class HunterFinderData(BaseModel):
    id: StrictInt | StrictStr | None = None
    first_name: StrictStr | None = None
    last_name: StrictStr | None = None
    email: StrictStr | None = None
    domain: StrictStr | None = None
    company: StrictStr | None = None
    position: StrictStr | None = None
    linkedin_url: StrictStr | None = None
    phone_number: StrictStr | None = None
    verification: HunterVerification | None = None
    sources: Annotated[list[HunterSource], Field(max_length=20)] = Field(default_factory=list)


class HunterFinderResponse(BaseModel):
    data: HunterFinderData | None = None


class HunterVerifierData(BaseModel):
    email: StrictStr | None = None
    status: StrictStr | None = None
    webmail: StrictBool | None = None
    disposable: StrictBool | None = None
    verification: HunterVerification | None = None
    sources: Annotated[list[HunterSource], Field(max_length=20)] = Field(default_factory=list)


class HunterVerifierResponse(BaseModel):
    data: HunterVerifierData | None = None


def _confirmed_domain(company: Company) -> str:
    if company.identity_status != IdentityStatus.CONFIRMED or company.domain is None:
        raise ContactError("identity_unconfirmed", "Hunter necesita el dominio de una entidad confirmada.")
    return company.domain


def domain_search_request(company: Company, roles: list[str], account_ref: str, *,
                          by_roles: bool = False) -> ProviderRequest:
    """Sin `by_roles`, todas las personas nominales del dominio; con él, solo los cargos objetivo.

    En el plan Free `limit + offset` no puede superar 10: no hay paginación posible.
    """
    params = {"domain": _confirmed_domain(company), "type": "personal", "limit": 10, "offset": 0}
    if by_roles and roles:
        params["job_titles"] = ",".join(dict.fromkeys(roles))
    return ProviderRequest(provider=PROVIDER, operation="domain_search", account_ref=account_ref, params=params)


def finder_request(contact: Contact, company: Company, account_ref: str) -> ProviderRequest:
    if contact.company_id != company.id or contact.name_complete is not True or contact.name is None:
        raise ContactError("identity_unconfirmed", "Finder requiere una persona identificada, sin inventar apellidos.")
    return ProviderRequest(provider=PROVIDER, operation="email_finder", account_ref=account_ref,
                           params={"domain": _confirmed_domain(company), "full_name": contact.name, "max_duration": 6})


def verifier_request(email: str, account_ref: str) -> ProviderRequest:
    if not re.fullmatch(r"[^@\s<>(),;:\"]+@[^@\s]+\.[^@\s]+", email):
        raise ContactError("invalid_email", "Verifier requiere un correo observado con formato válido.")
    return ProviderRequest(provider=PROVIDER, operation="email_verifier", account_ref=account_ref, params={"email": email})


def classify_hunter_error(error: ProviderError) -> str:
    if error.kind == "http":
        return {400: "invalid_input", 401: "permission_denied", 403: "rate_limited",
                404: "not_found", 422: "invalid_input", 429: "quota_exceeded",
                451: "privacy_restricted", 222: "verification_failed"}.get(error.http_status, "provider_error")
    return {"timeout": "timeout", "transport": "transport_error", "local": "local_error"}.get(error.kind, "invalid_response")


def _provider_fact(company: Company, contact_id: UUID, request_id: UUID, now: datetime,
                   field: str, value: str, *, published_at=None, updated_at=None, url=None) -> Evidence:
    return Evidence(company_id=company.id, contact_id=contact_id, claim=f"Hunter informa {field}: {value}",
                    provider=PROVIDER, external_reference=f"{request_id}#{field}", url=url,
                    excerpt=value[:800], retrieved_at=now, published_at=published_at, updated_at=updated_at,
                    kind="observed", source_type="provider")


def _channel_status(verification: HunterVerification | None) -> tuple[ChannelStatus, str | None, datetime | None]:
    raw = None if verification is None else verification.status
    date = None if verification is None else parse_source_date(verification.date)
    status = {"valid": ChannelStatus.VERIFIED, "invalid": ChannelStatus.INVALID,
              "accept_all": ChannelStatus.ACCEPT_ALL}.get(raw, ChannelStatus.UNKNOWN)
    if status == ChannelStatus.VERIFIED and date is None:
        status = ChannelStatus.UNKNOWN
    return status, raw, date


def _hunter_channels(contact: Contact, company: Company, email: str | None, verification,
                     linkedin: str | None, phone: str | None, request_id: UUID, now: datetime,
                     professional: bool) -> tuple[list[Channel], list[Evidence]]:
    channels, evidence = [], []
    if email:
        status, raw, verified_at = _channel_status(verification)
        fact = _provider_fact(company, contact.id, request_id, now, "email", f"{email}; estado={raw or 'unknown'}")
        evidence.append(fact)
        try:
            channels.append(Channel(contact_id=contact.id, type="email", value=email, evidence_ids=[fact.id],
                                    provider_status=raw, normalized_status=status, retrieved_at=now,
                                    verified_at=verified_at, professional=professional and professional_email(email, company.domain),
                                    direct=professional and professional_email(email, company.domain) and contact.name_complete is True,
                                    warnings=["Hunter verifica el correo, no demuestra vigencia del empleo."]))
        except ValueError:
            pass
    if linkedin and validate_public_url(linkedin) is not None:
        fact = _provider_fact(company, contact.id, request_id, now, "linkedin", linkedin)
        evidence.append(fact)
        try:
            channels.append(Channel(contact_id=contact.id, type="linkedin", value=linkedin, evidence_ids=[fact.id],
                                    retrieved_at=now, professional=professional, direct=None,
                                    warnings=["Falta confirmación de acceso a mensajería desde la cuenta de ventas."]))
        except ValueError:
            pass
    if phone:
        fact = _provider_fact(company, contact.id, request_id, now, "phone", phone)
        evidence.append(fact)
        # shortcut: solo prefijos CO/MX comprobables, ampliar con tabla internacional si el piloto lo necesita.
        country = phone_country_of(phone)
        if country is not None and re.fullmatch(r"\+[1-9][0-9]{1,14}", phone):
            channels.append(Channel(contact_id=contact.id, type="phone", value=phone, evidence_ids=[fact.id],
                                    retrieved_at=now, phone_country=country, professional=professional,
                                    direct=professional and contact.name_complete is True,
                                    warnings=["El formato y asociación del teléfono no garantizan que atienda."]))
    return channels, evidence


def parse_domain_search(company: Company, response: HunterDomainSearchResponse, request_id: UUID,
                        now: datetime) -> list[tuple[Contact, list[Evidence]]]:
    if response.data is None:
        return []
    data = response.data
    domain_matches = data.domain == company.domain
    entity_matches = domain_matches and organization_matches(company, data.organization)
    result = []
    for index, person in enumerate(data.emails):
        if person.type == "generic":
            continue
        name, complete = full_name(person.first_name, person.last_name)
        identifier = str(person.id) if person.id is not None else person.value or person.linkedin
        contact_id = uuid5(company.id, f"hunter:{identifier}") if identifier else uuid4()
        provenance, evidence = {}, []
        for field, value in (("name", name), ("title", person.position_raw or person.position)):
            if value:
                fact = _provider_fact(company, contact_id, request_id, now, f"{index}:{field}", value)
                evidence.append(fact)
                provenance[field] = [fact.id]
        employment = _provider_fact(company, contact_id, request_id, now, f"{index}:employment",
                                    f"{name or 'Nombre incompleto'}; empresa={data.organization}; dominio={data.domain}; cargo={person.position}. Vigencia no comprobada.")
        evidence.append(employment)
        for source_index, source in enumerate(person.sources):
            evidence.append(_provider_fact(company, contact_id, request_id, now, f"{index}:source:{source_index}",
                                          f"Fuente del correo; still_on_page={source.still_on_page}; no fecha de empleo.",
                                          url=validate_public_url(source.uri), published_at=parse_source_date(source.extracted_on),
                                          updated_at=parse_source_date(source.last_seen_on)))
        contact = Contact(id=contact_id, company_id=company.id, name=name, title=person.position_raw or person.position or None,
                          name_complete=complete if name else None, provenance=provenance,
                          employment_evidence_ids=[employment.id],
                          identity_status="confirmed" if complete and entity_matches else "pending")
        professional = bool(entity_matches and not data.webmail and not data.disposable and person.type == "personal")
        channels, facts = _hunter_channels(contact, company, person.value, person.verification, person.linkedin,
                                          person.phone_number, request_id, now, professional)
        result.append((contact.model_copy(update={"channels": channels}), evidence + facts))
    return result


def parse_finder(contact: Contact, company: Company, response: HunterFinderResponse,
                 request_id: UUID, now: datetime) -> tuple[Contact, list[Evidence]]:
    if response.data is None or response.data.email is None:
        return contact, []
    data = response.data
    name, complete = full_name(data.first_name, data.last_name)
    if not complete or fold_words(name or "") != fold_words(contact.name or "") or data.domain != company.domain:
        raise ContactError("identity_mismatch", "Finder devolvió otra persona o dominio; no se asignó el correo.")
    if data.company is not None and not organization_matches(company, data.company):
        raise ContactError("entity_mismatch", "Finder devolvió otra entidad; no se asignó el correo.")
    channels, evidence = _hunter_channels(contact, company, data.email, data.verification, data.linkedin_url,
                                         data.phone_number, request_id, now,
                                         professional_email(data.email, company.domain))
    update = contact.model_copy(update={"channels": channels})
    return merge_contact(contact, update, evidence), evidence


def parse_verifier(contact: Contact, company: Company, response: HunterVerifierResponse,
                   request_id: UUID, now: datetime) -> tuple[Contact, list[Evidence]]:
    if response.data is None:
        return contact, []
    data = response.data
    if data.email is None or data.status is None:
        raise ContactError("incomplete_verification", "La respuesta final de Verifier no identifica correo y estado.")
    previous = next((item for item in contact.channels if item.type == ChannelType.EMAIL and item.value == data.email), None)
    if previous is None:
        raise ContactError("channel_mismatch", "Verifier devolvió un correo que no pertenece al candidato.")
    verification = data.verification or HunterVerification(status=data.status)
    if verification.status != data.status:
        raise ContactError("verification_mismatch", "Hunter devolvió estados de verificación contradictorios.")
    status, raw, verified_at = _channel_status(verification)
    fact = _provider_fact(company, contact.id, request_id, now, "verification", f"{data.email}; estado={raw}; fecha={verification.date}")
    channel = previous.model_copy(update={"provider_status": raw, "normalized_status": status,
                                          "verified_at": verified_at, "retrieved_at": now,
                                          "professional": False if data.webmail or data.disposable else previous.professional,
                                          "evidence_ids": list(dict.fromkeys(previous.evidence_ids + [fact.id]))})
    return merge_contact(contact, contact.model_copy(update={"channels": [channel]}), [fact]), [fact]
