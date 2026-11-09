"""Adaptadores de lectura aislados: preparan y validan, sin llamar ni reservar gasto."""

from datetime import datetime
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4, uuid5

from pydantic import BaseModel, Field, JsonValue, StrictInt, StrictStr, model_validator

from prospecting.contacts import fold_words
from prospecting.models import Contact, Contract, Text
from prospecting.providers.apollo import (
    ApolloEnrichmentResponse, ApolloSearchResponse, enrichment_request, parse_enrichment,
    parse_search, people_search_request,
)

from .contracts import BenchmarkCompany, BenchmarkPerson, Provider, company_model


TOKEN_PATTERN = r"[A-Za-z0-9_-]{1,512}"
TaskToken = Annotated[StrictStr, Field(pattern=f"^{TOKEN_PATTERN}$")]
SNOV_SEARCH = "/v2/database-search/prospects"
SNOV_REVEAL = SNOV_SEARCH + "/search-emails"


class RequestSpec(Contract):
    provider: Provider
    operation: Text
    method: Literal["GET", "POST"]
    path: Text
    payload: dict[str, JsonValue] | None = None
    params: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_secrets(self):
        forbidden = {"access_token", "client_id", "client_secret", "authorization", "api_key", "x-api-key"}

        def check(value):
            if isinstance(value, dict):
                if any(key.lower() in forbidden for key in value):
                    raise ValueError("Las credenciales no pertenecen al descriptor persistible.")
                for item in value.values():
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)

        check(self.payload)
        check(self.params)
        return self


class SnovSearchResult(Contract):
    status: Literal["in_progress", "completed"]
    candidates: list[BenchmarkPerson] = Field(default_factory=list)
    total_pages: Annotated[StrictInt, Field(ge=0)] | None = None


class SnovRevealResult(Contract):
    status: Literal["in_progress", "completed"]
    person: BenchmarkPerson | None = None


class _TaskMeta(BaseModel):
    task_hash: TaskToken


class _TaskResponse(BaseModel):
    meta: _TaskMeta


class _SnovOrganization(BaseModel):
    name: StrictStr | None = None
    domain: StrictStr | None = None


class _SnovProspect(BaseModel):
    first_name: StrictStr | None = None
    last_name: StrictStr | None = None
    job_title: StrictStr | None = None
    company: _SnovOrganization
    email_and_hidden_info_reveal: StrictStr


class _SnovSearchData(BaseModel):
    prospects: Annotated[list[_SnovProspect], Field(max_length=20)]
    total_pages: Annotated[StrictInt, Field(ge=0)] | None = None


class _SnovResult(BaseModel):
    status: Literal["in_progress", "completed"]
    data: dict[str, JsonValue] | list[JsonValue]


class _SnovEmail(BaseModel):
    email: StrictStr
    smtp_status: Literal["valid", "unknown", "invalid"]


class _SnovRevealData(BaseModel):
    first_name: StrictStr | None = None
    last_name: StrictStr | None = None
    emails: Annotated[list[_SnovEmail], Field(max_length=100)] = Field(default_factory=list)


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _task_token(value):
    if not isinstance(value, str) or not re.fullmatch(TOKEN_PATTERN, value):
        raise ValueError("El proveedor devolvió un identificador de tarea inválido.")
    return value


def reveal_token(url):
    """El contenido externo solo aporta el token; nunca decide el destino HTTP."""
    parts = urlsplit(url)
    prefix = SNOV_REVEAL + "/start/"
    if (parts.scheme != "https" or parts.netloc != "api.snov.io" or parts.query or parts.fragment
            or not parts.path.startswith(prefix)):
        raise ValueError("La URL de revelado no pertenece al endpoint Snov permitido.")
    return _task_token(parts.path[len(prefix):])


def snov_auth_request() -> RequestSpec:
    return RequestSpec(provider="snov", operation="oauth", method="POST", path="/v1/oauth/access_token")


def snov_search_request(company: BenchmarkCompany, page: int = 1) -> RequestSpec:
    company = BenchmarkCompany.model_validate(company)
    if type(page) is not int or page < 1:
        raise ValueError("La página debe ser un entero positivo.")
    return RequestSpec(provider="snov", operation="people_search", method="POST", path=SNOV_SEARCH + "/start",
                       payload={"page": page, "filters": {
                           "company": {"name": {"include": [company.name]}},
                           "prospect": {"job_titles": {"include": company.roles}},
                       }})


def snov_poll_request(task_hash: str, reveal: bool = False) -> RequestSpec:
    prefix = SNOV_REVEAL if reveal else SNOV_SEARCH
    operation = "people_enrichment_result" if reveal else "people_search_result"
    return RequestSpec(provider="snov", operation=operation, method="GET",
                       path=f"{prefix}/result/{_task_token(task_hash)}")


def snov_reveal_request(reveal_url: str) -> RequestSpec:
    return RequestSpec(provider="snov", operation="people_enrichment", method="POST",
                       path=f"{SNOV_REVEAL}/start/{reveal_token(reveal_url)}")


def parse_snov_task(raw: dict) -> str:
    return _TaskResponse.model_validate(raw).meta.task_hash


def parse_snov_search(raw: dict, company: BenchmarkCompany, retrieved_at: datetime) -> SnovSearchResult:
    result = _SnovResult.model_validate(raw)
    if result.status == "in_progress":
        return SnovSearchResult(status="in_progress")
    data = _SnovSearchData.model_validate(result.data)
    people, seen = [], set()
    for person in data.prospects:
        identifier = reveal_token(person.email_and_hidden_info_reveal)
        if identifier in seen:
            continue
        seen.add(identifier)
        people.append(BenchmarkPerson(
            id=identifier, first_name=_text(person.first_name), last_name=_text(person.last_name),
            title=_text(person.job_title), domain=_text(person.company.domain),
            source_reference=person.email_and_hidden_info_reveal, retrieved_at=retrieved_at,
        ))
    return SnovSearchResult(status="completed", candidates=people, total_pages=data.total_pages)


def parse_snov_reveal(raw: dict, person: BenchmarkPerson, retrieved_at: datetime) -> SnovRevealResult:
    result = _SnovResult.model_validate(raw)
    if result.status == "in_progress":
        return SnovRevealResult(status="in_progress")
    data = _SnovRevealData.model_validate(result.data)
    first, last = _text(data.first_name), _text(data.last_name)
    if first and person.first_name and fold_words(first) != fold_words(person.first_name):
        raise ValueError("Snov devolvió otra identidad al revelar el contacto.")
    if last and person.last_name:
        previous = person.last_name.split("*", 1)[0].strip()
        matches = (fold_words(last).startswith(fold_words(previous)) if "*" in person.last_name
                   else fold_words(last) == fold_words(previous))
        if previous and not matches:
            raise ValueError("Snov devolvió un apellido incompatible con el candidato.")
    # Una persona se cuenta una vez: priorizamos correo del dominio y después su estado observado.
    emails = sorted(data.emails, key=lambda item: (
        item.email.rpartition("@")[2].lower() != person.domain,
        {"valid": 0, "unknown": 1, "invalid": 2}[item.smtp_status], item.email,
    ))
    email = emails[0] if emails else None
    values = person.model_dump() | {
        "first_name": first or person.first_name, "last_name": last or person.last_name,
        "email": email.email if email else None, "email_status": email.smtp_status if email else "missing",
        "email_verified_at": None, "retrieved_at": retrieved_at, "enriched": True,
    }
    # searching_date solo fecha el inicio de búsqueda; no verifica correo ni empleo.
    return SnovRevealResult(status="completed", person=BenchmarkPerson.model_validate(values))


def apollo_search_request(company: BenchmarkCompany, page: int = 1) -> RequestSpec:
    if type(page) is not int or page < 1:
        raise ValueError("La página debe ser un entero positivo.")
    model, _ = company_model(company)
    request = people_search_request(model, company.roles, "benchmark-adapter", by_roles=True)
    payload = request.payload | {"page": page}
    return RequestSpec(provider="apollo", operation=request.operation, method="POST",
                       path="/api/v1/mixed_people/api_search", payload=payload)


def apollo_reveal_request(person: BenchmarkPerson) -> RequestSpec:
    request = enrichment_request(person.id, "benchmark-adapter")
    return RequestSpec(provider="apollo", operation=request.operation, method="POST",
                       path="/api/v1/people/match", payload=request.payload)


def parse_apollo_search(raw: dict, company: BenchmarkCompany, retrieved_at: datetime) -> list[BenchmarkPerson]:
    response = ApolloSearchResponse.model_validate(raw)
    model, _ = company_model(company)
    parsed = parse_search(model, response, uuid4(), retrieved_at)
    by_id = {uuid5(company.company_id, f"apollo:{person.id}"): person for person in response.people}
    return [BenchmarkPerson(
        id=by_id[contact.id].id, first_name=_text(by_id[contact.id].first_name),
        last_name=_text(by_id[contact.id].last_name_obfuscated), title=contact.title,
        domain=_text(by_id[contact.id].organization.primary_domain) if by_id[contact.id].organization else None,
        source_reference=f"https://api.apollo.io/api/v1/mixed_people/api_search#{by_id[contact.id].id}",
        retrieved_at=retrieved_at,
    ) for contact, _ in parsed]


def parse_apollo_reveal(raw: dict, company: BenchmarkCompany, person: BenchmarkPerson,
                        retrieved_at: datetime) -> BenchmarkPerson | None:
    response = ApolloEnrichmentResponse.model_validate(raw)
    if response.person is None:
        return None
    model, _ = company_model(company)
    contact = Contact(id=uuid5(company.company_id, f"apollo:{person.id}"), company_id=company.company_id)
    parsed, _ = parse_enrichment(contact, model, response, uuid4(), retrieved_at)
    source = response.person
    first, last = _text(source.first_name), _text(source.last_name)
    if (first is None or last is None) and parsed.name:
        parts = parsed.name.split(maxsplit=1)
        first, last = parts[0], parts[1] if len(parts) == 2 else None
    status = {"verified": "valid", "valid": "valid", "invalid": "invalid", "bounced": "invalid"}.get(
        source.email_status, "unknown") if source.email else "missing"
    return BenchmarkPerson(
        id=person.id, first_name=first, last_name=last, title=parsed.title,
        domain=source.organization.primary_domain, email=source.email, email_status=status,
        source_reference=f"https://api.apollo.io/api/v1/people/match#{person.id}",
        retrieved_at=retrieved_at, enriched=True,
    )
