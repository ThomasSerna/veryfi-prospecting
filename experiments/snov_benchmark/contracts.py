"""Contratos exclusivos del experimento; no amplían el producto ni sus identificadores."""

import hashlib
import json
import re
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import Field, HttpUrl, JsonValue, StrictBool, StrictInt, field_validator, model_validator

from prospecting.budget import SpendingAuthorization
from prospecting.models import Company, Contract, Evidence, Money, Segment, Text, UtcDatetime, utc_now
from prospecting.providers.apollo import ApolloRateLimit


Provider = Literal["apollo", "snov"]
Origin = Literal["synthetic", "real"]
PositiveCount = Annotated[StrictInt, Field(gt=0)]
PositiveSeconds = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class BenchmarkLimits(Contract):
    max_requests: PositiveCount
    max_pages: PositiveCount
    max_people: PositiveCount
    max_polls: PositiveCount
    timeout_seconds: PositiveSeconds
    max_seconds: PositiveSeconds
    poll_interval_seconds: PositiveSeconds


class EmploymentEvidence(Contract):
    full_name: Text
    title: Text
    domain: Text
    source_url: HttpUrl
    excerpt: Text
    observed_at: UtcDatetime
    published_at: UtcDatetime | None = None
    status: Literal["current", "ended", "ambiguous"]

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value):
        return Company.validate_domain(value)

    @model_validator(mode="after")
    def check_dates(self):
        if self.observed_at > utc_now() or self.published_at is not None and self.published_at > self.observed_at:
            raise ValueError("La evidencia no admite fechas futuras ni publicación posterior a la consulta.")
        return self


class BenchmarkCompany(Contract):
    company_id: UUID
    name: Text
    domain: Text
    country: Literal["CO", "MX"]
    segment: Segment
    source_reference: Text
    observed_at: UtcDatetime
    roles: Annotated[list[Text], Field(min_length=1)]
    role_families: dict[Text, Annotated[list[Text], Field(min_length=1)]]
    evidence: list[EmploymentEvidence] = Field(default_factory=list)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value):
        return Company.validate_domain(value)

    @model_validator(mode="after")
    def check_roles(self):
        aliases = [alias for values in self.role_families.values() for alias in values]
        if not aliases or len(self.roles) != len(set(self.roles)) or set(aliases) != set(self.roles):
            raise ValueError("Los cargos deben coincidir con los alias de las familias congeladas.")
        if len(aliases) != len(set(aliases)):
            raise ValueError("Un alias no puede representar varias funciones.")
        if self.observed_at > utc_now():
            raise ValueError("La identidad de empresa no puede tener fecha futura.")
        return self


class BenchmarkManifest(Contract):
    schema_version: Literal["snov_benchmark_manifest_v1"] = "snov_benchmark_manifest_v1"
    benchmark_id: UUID
    origin: Origin
    created_at: UtcDatetime
    source_reference: Text
    companies: Annotated[list[BenchmarkCompany], Field(min_length=1, max_length=20)]
    limits: BenchmarkLimits
    contact_days: PositiveCount
    config_versions: dict[Text, Text]

    @model_validator(mode="after")
    def check_sample(self):
        if len({company.company_id for company in self.companies}) != len(self.companies):
            raise ValueError("La muestra repite identificadores de empresas.")
        if len({company.domain for company in self.companies}) != len(self.companies):
            raise ValueError("La muestra repite dominios de empresas.")
        if not self.config_versions or self.created_at > utc_now():
            raise ValueError("El manifiesto necesita versiones congeladas y fecha no futura.")
        if any(company.observed_at > self.created_at for company in self.companies):
            raise ValueError("El manifiesto precede a la comprobación de identidad de una empresa.")
        if any(fact.observed_at > self.created_at for company in self.companies for fact in company.evidence):
            raise ValueError("La evidencia compartida debe existir antes de congelar el manifiesto.")
        return self


class OperationBound(Contract):
    cost_usd: Money
    credits: Money
    source_reference: Text
    observed_at: UtcDatetime

    @model_validator(mode="after")
    def check_date(self):
        if self.observed_at > utc_now():
            raise ValueError("La comprobación del costo no puede tener fecha futura.")
        return self


class ProviderAccess(Contract):
    provider: Provider
    account_ref: Text
    access_verified: StrictBool
    observed_at: UtcDatetime
    source_reference: Text
    funding_source: Literal["free_credit", "prepaid", "new_outlay"]
    credit_limit: Money
    cost_limit_usd: Money
    prior_credits_used: Money
    prior_cost_usd: Money
    usage_consolidated_verified: StrictBool
    usage_source_reference: Text
    operation_bounds: dict[Text, OperationBound]
    rate_limits: dict[Text, ApolloRateLimit]

    @model_validator(mode="after")
    def check_limits(self):
        if not self.operation_bounds or set(self.operation_bounds) != set(self.rate_limits):
            raise ValueError("Cada operación necesita costo acotado y límites de solicitudes.")
        if self.prior_credits_used > self.credit_limit or self.prior_cost_usd > self.cost_limit_usd:
            raise ValueError("El consumo previo no puede superar el cupo consolidado declarado.")
        if self.funding_source == "free_credit" and any(bound.cost_usd != 0 for bound in self.operation_bounds.values()):
            raise ValueError("El crédito gratuito reserva cero USD; su equivalente no es desembolso.")
        if self.observed_at > utc_now():
            raise ValueError("La comprobación de acceso no puede tener fecha futura.")
        return self


class BenchmarkApproval(Contract):
    schema_version: Literal["snov_benchmark_approval_v1"] = "snov_benchmark_approval_v1"
    benchmark_id: UUID
    manifest_sha256: Digest
    session_id: UUID
    responsible: Text
    approved_at: UtcDatetime
    approvals: Annotated[list[SpendingAuthorization], Field(min_length=1)]

    @model_validator(mode="after")
    def check_approvals(self):
        keys = [(item.provider, item.operation, item.account_ref) for item in self.approvals]
        if len(keys) != len(set(keys)):
            raise ValueError("La aprobación repite proveedor, operación y cuenta.")
        if self.approved_at > utc_now() or any(item.authorized_at != self.approved_at for item in self.approvals):
            raise ValueError("Las autorizaciones deben pertenecer a la misma sesión y fecha no futura.")
        if any(item.responsible != self.responsible for item in self.approvals):
            raise ValueError("Las autorizaciones deben identificar al mismo responsable.")
        return self


class BenchmarkPerson(Contract):
    id: Text
    first_name: Text | None = None
    last_name: Text | None = None
    title: Text | None = None
    domain: Text | None = None
    email: Text | None = None
    email_status: Literal["valid", "unknown", "invalid", "missing"] = "missing"
    email_verified_at: UtcDatetime | None = None
    source_reference: Text
    retrieved_at: UtcDatetime
    enriched: StrictBool = False

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value):
        return Company.validate_domain(value)

    @model_validator(mode="after")
    def check_email(self):
        if (self.email is None) != (self.email_status == "missing"):
            raise ValueError("La ausencia de correo necesita estado missing; un correo necesita estado observado.")
        if self.email is not None and not re.fullmatch(r"[^@\s<>(),;:\"]+@[^@\s]+\.[^@\s]+", self.email):
            raise ValueError("El proveedor devolvió un formato de correo inválido.")
        if self.email_verified_at is not None and (self.email is None or self.email_verified_at > self.retrieved_at):
            raise ValueError("La fecha de verificación requiere correo y no puede superar la consulta.")
        if self.retrieved_at > utc_now():
            raise ValueError("La consulta del contacto no puede tener fecha futura.")
        return self


class BenchmarkCapture(Contract):
    schema_version: Literal["snov_benchmark_capture_v1"] = "snov_benchmark_capture_v1"
    benchmark_id: UUID
    manifest_sha256: Digest
    provider: Provider
    company_id: UUID
    origin: Origin
    observed_at: UtcDatetime
    candidates: list[BenchmarkPerson] = Field(default_factory=list)
    requests: list[dict[str, JsonValue]] = Field(default_factory=list)
    errors: list[dict[str, JsonValue]] = Field(default_factory=list)
    status: Literal["pending", "completed", "blocked", "uncertain"] = "pending"

    @model_validator(mode="after")
    def check_candidates(self):
        if len({person.id for person in self.candidates}) != len(self.candidates):
            raise ValueError("La captura repite identificadores de personas.")
        if self.observed_at > utc_now() or any(person.retrieved_at > self.observed_at for person in self.candidates):
            raise ValueError("La fecha de corte debe incluir las consultas y no estar en el futuro.")
        return self


def manifest_digest(manifest: BenchmarkManifest) -> str:
    manifest = BenchmarkManifest.model_validate(manifest)
    data = json.dumps(manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def company_model(company: BenchmarkCompany) -> tuple[Company, list[Evidence]]:
    """Adapta únicamente nombre y dominio con la referencia de identidad del manifiesto."""
    company = BenchmarkCompany.model_validate(company)
    facts = [Evidence(
        id=uuid5(company.company_id, f"benchmark_identity:{field}:{company.source_reference}"),
        company_id=company.company_id, claim=f"Identidad de muestra: {field}={value}", excerpt=value,
        provider="benchmark_manifest", external_reference=company.source_reference, retrieved_at=company.observed_at,
        kind="observed", source_type="primary",
    ) for field, value in (("name", company.name), ("domain", company.domain))]
    model = Company(id=company.company_id, name=company.name, domain=company.domain,
                    provenance={field: [fact.id] for field, fact in zip(("name", "domain"), facts)},
                    identity_status="confirmed")
    return model, facts
