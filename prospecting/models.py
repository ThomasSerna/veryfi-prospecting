"""Contratos locales, procedencia y configuración del prototipo académico."""

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
import re
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    HttpUrl,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)


def utc_now() -> datetime:
    """Fecha de metadatos locales; nunca sustituye la fecha de una fuente."""
    return datetime.now(UTC)


def _money(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("El dinero requiere Decimal, texto decimal o entero, nunca float.")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("Importe decimal inválido.") from error
    if not result.is_finite():
        raise ValueError("El importe debe ser finito.")
    return result


def _unique(values: list) -> list:
    if len(values) != len(set(values)):
        raise ValueError("No se permiten elementos duplicados.")
    return values


def _criterion_value(value: object) -> object:
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float, Decimal))
        or value not in (0, 0.5, 1)
    ):
        raise ValueError("El criterio admite solamente 0, 0.5, 1 o null.")
    return value


def _disabled(value: object) -> Literal[False]:
    if value is not False:
        raise ValueError("La función debe permanecer deshabilitada.")
    return False


def _domain(value: str) -> str:
    try:
        domain = value.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValueError("Dominio inválido.") from error
    labels = domain.split(".")
    if len(domain) > 253 or len(labels) < 2 or labels[-1].isdigit() or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise ValueError("El dominio debe ser un nombre de host, sin ruta ni credenciales.")
    return domain


Text = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
CountryCode = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z]{2}$")]
Count = Annotated[StrictInt, Field(ge=0)]
Money = Annotated[Decimal, BeforeValidator(_money), Field(ge=0)]
Ratio = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
Score = Annotated[float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]
ReferenceIds = Annotated[list[UUID], AfterValidator(_unique)]
SourceIds = Annotated[ReferenceIds, Field(min_length=1)]
CriterionValue = Annotated[Literal[0, 0.5, 1] | None, BeforeValidator(_criterion_value)]
KnownCriterionValue = Annotated[Literal[0, 0.5, 1], BeforeValidator(_criterion_value)]
Disabled = Annotated[Literal[False], BeforeValidator(_disabled)]
CriterionName = Literal[
    "document_need", "offer_match", "scale_potential", "adoption_capacity", "opportunity_timing"
]
CRITERION_NAMES = {
    "document_need", "offer_match", "scale_potential", "adoption_capacity", "opportunity_timing"
}


class Contract(BaseModel):
    """Revalida también instancias que llegan desde otro módulo."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")


class Segment(StrEnum):
    FINTECH_SOFTWARE = "fintech_software"
    CPG_LOYALTY = "cpg_loyalty"


class CampaignStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    PAUSED_BUDGET = "paused_budget"
    FAILED = "failed"


class IdentityStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CONTRADICTED = "contradicted"


class EntityType(StrEnum):
    LEGAL_ENTITY = "legal_entity"
    BRAND = "brand"
    SUBSIDIARY = "subsidiary"
    UNKNOWN = "unknown"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EXCLUDED = "excluded"


class BuyingRole(StrEnum):
    BUSINESS_CHAMPION = "business_champion"
    TECHNICAL_CHAMPION = "technical_champion"
    ECONOMIC_BUYER = "economic_buyer"
    UNKNOWN = "unknown"


class ChannelType(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    LINKEDIN = "linkedin"
    OTHER = "other"


class ChannelStatus(StrEnum):
    VERIFIED = "verified"
    PUBLISHED_PROFESSIONAL = "published_professional"
    ACCEPT_ALL = "accept_all"
    UNKNOWN = "unknown"
    INVALID = "invalid"
    MANUAL_CONFIRMED = "manual_confirmed"


class RunStage(StrEnum):
    DISCOVERED = "discovered"
    IDENTITY_RESOLVED = "identity_resolved"
    RESEARCHED = "researched"
    ASSESSED = "assessed"
    CONTACTS_CHECKED = "contacts_checked"
    COMPLETED = "completed"


class BusinessStatus(StrEnum):
    READY_PREFERRED = "ready_preferred"
    READY_ALTERNATIVE = "ready_alternative"
    NEEDS_CHANNEL_CONFIRMATION = "needs_channel_confirmation"
    QUALIFIED_NO_CONTACT = "qualified_no_contact"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    LOW_FIT = "low_fit"
    EXCLUDED = "excluded"


class UsageStatus(StrEnum):
    RESERVED = "reserved"
    IN_FLIGHT = "in_flight"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    RECONCILED = "reconciled"


class Product(Contract):
    id: Text
    name: Text
    capabilities: Annotated[list[Text], Field(min_length=1)]
    source_reference: Text
    validation_status: Literal["pending", "validated"]


class Catalog(Contract):
    version: Text
    validation_status: Literal["pending", "validated"]
    source_reference: Text
    source_date: date
    products: Annotated[list[Product], Field(min_length=1)]


class Profile(Contract):
    id: Text
    segment: Segment
    name: Text
    signals: Annotated[list[Text], Field(min_length=1)]
    products: Annotated[list[Text], Field(min_length=1)]
    target_roles: Annotated[list[Text], Field(min_length=1)]
    candidate: StrictBool
    source_reference: Text


ApolloSeniority = Literal["owner", "founder", "c_suite", "partner", "vp", "head", "director", "manager", "senior", "entry", "intern"]


class RoleFamily(Contract):
    id: Text
    function_id: Text
    profile_ids: Annotated[list[Text], Field(min_length=1), AfterValidator(_unique)]
    buying_role: Literal["business_champion", "technical_champion", "economic_buyer"]
    titles_en: Annotated[list[Text], Field(min_length=1), AfterValidator(_unique)]
    titles_es: Annotated[list[Text], Field(min_length=1), AfterValidator(_unique)]
    departments: Annotated[list[Text], Field(min_length=1), AfterValidator(_unique)]
    seniorities: Annotated[list[ApolloSeniority], AfterValidator(_unique)]
    function_terms: Annotated[list[Text], Field(min_length=1), AfterValidator(_unique)]
    excluded_titles: Annotated[list[Text], AfterValidator(_unique)]
    source_reference: Text
    source_date: date
    validation_status: Literal["pending", "validated"]


class RoleTaxonomy(Contract):
    version: Literal["role_taxonomy_v1"]
    source_date: date
    validation_status: Literal["pending", "validated"]
    families: Annotated[list[RoleFamily], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_families(self) -> Self:
        _unique([family.id for family in self.families])
        for bounded in (True, False):
            titles = {title.casefold() for family in self.families if bool(family.seniorities) == bounded
                      for title in family.titles_en + family.titles_es}
            if len(titles) >= 100:
                raise ValueError("Cada grupo de búsqueda admite menos de 100 títulos únicos.")
        return self


class PeoplePolicy(Contract):
    """Objetivo de personas pertinentes por cuenta (T16); propuesta pendiente de validación comercial.

    Es un objetivo, no una cuota: los topes de `limits.effort` y del presupuesto siguen mandando.
    """

    version: Literal["people_policy_v1"]
    validation_status: Literal["pending", "validated"]
    source_reference: Text
    source_date: date
    target: dict[Literal["medium", "high"], Annotated[StrictInt, Field(ge=1, le=5)]]
    min_functions: Annotated[StrictInt, Field(ge=1, le=5)]

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if set(self.target) != {"medium", "high"}:
            raise ValueError("El objetivo de personas necesita los niveles medio y alto.")
        return self


class CriterionDefinition(Contract):
    name: Text
    weight: Annotated[StrictInt, Field(gt=0, le=100)]
    strong_signal: Text
    partial_signal: Text


class HighThreshold(Contract):
    fit_score_min: Score
    coverage_min: Ratio
    document_need: KnownCriterionValue
    offer_match_min: KnownCriterionValue
    primary_source_required: StrictBool


class MediumThreshold(Contract):
    fit_score_min: Score
    coverage_min: Ratio
    document_need_min: KnownCriterionValue
    offer_match_min: KnownCriterionValue


class LowThreshold(Contract):
    coverage_min: Ratio


class Thresholds(Contract):
    high: HighThreshold
    medium: MediumThreshold
    low: LowThreshold


class Preconditions(Contract):
    confirmed_exclusion: Literal["excluded"]
    unknown_identity: Literal["insufficient_evidence"]
    unknown_criteria: Annotated[list[CriterionName], Field(min_length=1)]
    material_contradiction: Literal["insufficient_evidence"]


class Rubric(Contract):
    validation_status: Literal["proposed", "validated"]
    allowed_values: list[CriterionValue]
    criteria: dict[CriterionName, CriterionDefinition]
    priority_order: Annotated[list[Priority], Field(min_length=1)]
    preconditions: Preconditions
    thresholds: Thresholds
    zero_meaning: Text
    unknown_meaning: Text

    @model_validator(mode="after")
    def validate_criteria(self) -> Self:
        if set(self.criteria) != CRITERION_NAMES:
            raise ValueError("La rúbrica requiere los cinco criterios.")
        if sum(item.weight for item in self.criteria.values()) != 100:
            raise ValueError("Los pesos de la rúbrica deben sumar 100.")
        if len(self.allowed_values) != 4 or set(self.allowed_values) != {0, 0.5, 1, None}:
            raise ValueError("La rúbrica debe conservar los valores 0, 0.5, 1 y null.")
        if self.thresholds.high.fit_score_min < self.thresholds.medium.fit_score_min or self.thresholds.high.coverage_min < self.thresholds.medium.coverage_min:
            raise ValueError("La prioridad alta no puede exigir menos encaje o cobertura que la media.")
        return self


class DiscoveryLimits(Contract):
    web_queries: Annotated[Count, Field(le=8)]
    results_per_query: Annotated[Count, Field(le=10)]
    raw_candidates: Annotated[Count, Field(le=60)]
    target_per_country_segment: Annotated[Count, Field(le=5)]


class EffortLimits(Contract):
    web_queries: Count
    pages: Count
    people: Annotated[Count, Field(le=5)]
    enrichments_per_provider: Annotated[Count, Field(le=5)]
    people_queries: Annotated[Count, Field(le=2)]
    active_seconds: Count


class CacheLimits(Contract):
    web_days: Count
    contact_days: Count


class FreshnessLimits(Contract):
    email_days: Count
    employment_days: Count


class EmployeeRange(Contract):
    employee_min: Count
    employee_max: Count | None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.employee_max is not None and self.employee_max < self.employee_min:
            raise ValueError("El máximo de empleados no puede ser menor que el mínimo.")
        return self


class BudgetAllocation(Contract):
    llm_usd: Money
    web_usd: Money
    contacts_usd: Money
    uncertainty_usd: Money


class BudgetLimits(Contract):
    global_usd: Annotated[Money, Field(le=20)]
    operating_usd: Annotated[Money, Field(le=15)]
    uncertainty_usd: Annotated[Money, Field(le=5)]
    campaign_usd: Annotated[Money, Field(le=2)]
    company_usd: Annotated[Money, Field(le=Decimal("0.25"))]
    allocation: BudgetAllocation
    automatic_topups: Disabled
    variable_cost_waterfall: Disabled
    paid_phone_enrichment: Disabled

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        if not self.company_usd <= self.campaign_usd <= self.operating_usd <= self.global_usd:
            raise ValueError("Los límites de empresa, campaña y operación deben ser subordinados.")
        if self.operating_usd + self.uncertainty_usd > self.global_usd:
            raise ValueError("El límite operativo y el margen exceden el presupuesto global.")
        if sum(self.allocation.model_dump().values(), Decimal(0)) > self.global_usd:
            raise ValueError("La distribución excede el presupuesto global.")
        return self


class LlmLimits(Contract):
    max_input_tokens: Annotated[Count, Field(le=9000)]
    max_output_tokens: Annotated[Count, Field(le=1000)]


class CampaignLimits(Contract):
    discovery: DiscoveryLimits
    effort: dict[Literal["initial", "insufficient_evidence", "medium", "high", "low", "excluded"], EffortLimits]
    email_verifications_per_channel: Annotated[Count, Field(le=1)]
    evidence_expansions_per_company: Annotated[Count, Field(le=1)]
    active_seconds: Annotated[Count, Field(le=2700)]
    cache: CacheLimits
    freshness: FreshnessLimits
    budget: BudgetLimits
    llm: LlmLimits

    @model_validator(mode="after")
    def validate_effort(self) -> Self:
        caps = {
            "initial": (2, 3, 0, 0, 0, 90),
            "insufficient_evidence": (1, 2, 0, 0, 0, 45),
            "medium": (2, 2, 3, 3, 2, 90),
            "high": (4, 4, 5, 5, 2, 180),
            "low": (0, 0, 0, 0, 0, 0),
            "excluded": (0, 0, 0, 0, 0, 0),
        }
        if set(self.effort) != set(caps):
            raise ValueError("Faltan niveles de esfuerzo.")
        fields = ("web_queries", "pages", "people", "enrichments_per_provider", "people_queries", "active_seconds")
        for level, values in caps.items():
            if any(getattr(self.effort[level], name) > cap for name, cap in zip(fields, values, strict=True)):
                raise ValueError(f"El esfuerzo de {level} supera los topes del prototipo.")
        return self


class Defaults(CampaignLimits):
    countries: Annotated[list[CountryCode], Field(min_length=1), AfterValidator(_unique)]
    segments: Annotated[list[Segment], Field(min_length=1), AfterValidator(_unique)]
    max_companies: Annotated[StrictInt, Field(ge=1, le=20)]
    employee_ranges: dict[Literal["small", "medium", "large"], EmployeeRange]


MatchComponentName = Literal["role", "channel", "identity", "employment"]
MATCH_LEVELS = {
    "role": ("selected_role", "profile_role", "outside_profile", "unknown"),
    "channel": ("preferred_usable", "alternative_usable", "preferred_unconfirmed", "alternative_unconfirmed", "none"),
    "identity": ("confirmed_complete", "complete_pending", "incomplete"),
    "employment": ("evidence", "hunter_signal", "unverified"),
}
MATCH_LEVELS_V2 = MATCH_LEVELS | {"employment": ("corporate_evidence", "provider_claim", "contradicted", "unknown")}
PENDING_LEVELS = frozenset({"unknown", "none", "incomplete", "unverified", "provider_claim"})
Points = Annotated[StrictInt, Field(ge=0, le=100)]
CONTACT_MATCH_FINGERPRINTS = {
    "contact_match_v1": "dd990a111908273b12a82a916a8174962377367aa41c9dc7aa6f0f31407b6d7e",
    "contact_match_v2": "c68ed6877f566d289330f0397e4cd05044200b2bce547f59181e40a1c94463ee",
}


class MatchComponentConfig(Contract):
    weight: Annotated[StrictInt, Field(gt=0, le=100)]
    levels: dict[Text, Points]


class ContactMatchConfig(Contract):
    """La versión fija niveles, puntos y algoritmo; nunca se reinterpretan pesos históricos."""

    version: Literal["contact_match_v1", "contact_match_v2"]
    validation_status: Literal["proposed", "validated"]
    source_reference: Text
    components: dict[MatchComponentName, MatchComponentConfig]

    @model_validator(mode="after")
    def validate_points(self) -> Self:
        if self.version == "contact_match_v2" and self.validation_status != "proposed":
            raise ValueError("contact_match_v2 sigue siendo una propuesta sin validación comercial.")
        levels = MATCH_LEVELS if self.version == "contact_match_v1" else MATCH_LEVELS_V2
        if set(self.components) != set(levels):
            raise ValueError("El match necesita los componentes role, channel, identity y employment.")
        if sum(item.weight for item in self.components.values()) != 100:
            raise ValueError("Los pesos del match deben sumar 100.")
        for name, item in self.components.items():
            if set(item.levels) != set(levels[name]):
                raise ValueError(f"El componente {name} necesita exactamente los niveles {', '.join(levels[name])}.")
            if max(item.levels.values()) != item.weight:
                raise ValueError(f"El nivel más alto de {name} debe valer su peso, sin superarlo.")
            if any(points for level, points in item.levels.items() if level in PENDING_LEVELS):
                raise ValueError("Un dato pendiente no suma puntos.")
        digest = hashlib.sha256(json.dumps(self.model_dump(mode="json")["components"], sort_keys=True).encode()).hexdigest()
        if digest != CONTACT_MATCH_FINGERPRINTS[self.version]:
            raise ValueError("Cambiar pesos o niveles requiere una nueva versión de match implementada.")
        return self


class VeryfiConfig(Contract):
    people_provider: Literal["apollo"] | None = None
    schema_version: Annotated[StrictInt, Field(ge=1, le=1)]
    catalog: Catalog
    profiles: Annotated[list[Profile], Field(min_length=1)]
    rubrics: dict[Text, Rubric]
    defaults: Defaults
    role_taxonomy: RoleTaxonomy | None = None
    people_policy: PeoplePolicy | None = None
    contact_match: ContactMatchConfig | None = None

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        product_ids = [product.id for product in self.catalog.products]
        _unique(product_ids)
        _unique([profile.id for profile in self.profiles])
        if self.role_taxonomy is not None:
            profile_ids = {profile.id for profile in self.profiles}
            if any(not set(family.profile_ids) <= profile_ids for family in self.role_taxonomy.families):
                raise ValueError("Una familia de cargos referencia perfiles inexistentes.")
        if self.people_policy is not None:
            if self.role_taxonomy is None or self.people_provider != "apollo":
                raise ValueError("El objetivo de personas requiere la taxonomía de cargos y Apollo.")
            if any(target > self.defaults.effort[level].people for level, target in self.people_policy.target.items()):
                raise ValueError("El objetivo de personas supera el tope de personas del nivel.")
        for profile in self.profiles:
            if not set(profile.products) <= set(product_ids):
                raise ValueError("Un perfil referencia productos inexistentes.")
        if not self.rubrics:
            raise ValueError("La configuración necesita una rúbrica.")
        if set(self.defaults.countries) - {"CO", "MX"}:
            raise ValueError("La muestra inicial admite Colombia y México.")
        if set(self.defaults.employee_ranges) != {"small", "medium", "large"}:
            raise ValueError("Faltan rangos de empleados.")
        return self


class CampaignFilters(Contract):
    keywords: list[Text] = Field(default_factory=list)


def _validate_limit_reduction(limits: dict, defaults: dict) -> None:
    for name, value in limits.items():
        maximum = defaults[name]
        if isinstance(value, dict):
            _validate_limit_reduction(value, maximum)
        elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and value > maximum:
            raise ValueError(f"El límite {name} supera la configuración de campaña.")


class Campaign(Contract):
    id: UUID = Field(default_factory=uuid4)
    countries: Annotated[list[CountryCode], Field(min_length=1), AfterValidator(_unique)]
    segments: Annotated[list[Segment], Field(min_length=1), AfterValidator(_unique)]
    filters: CampaignFilters = Field(default_factory=CampaignFilters)
    max_companies: Annotated[StrictInt, Field(ge=1, le=20)] = 20
    limits: CampaignLimits | None = None
    rubric_version: Text = "rubric_v1"
    config_snapshot: VeryfiConfig
    status: CampaignStatus = CampaignStatus.CREATED
    created_at: UtcDatetime = Field(default_factory=utc_now)
    updated_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        defaults = self.config_snapshot.defaults
        if not set(self.countries) <= set(defaults.countries) or not set(self.segments) <= set(defaults.segments):
            raise ValueError("Países o segmentos fuera de la configuración de campaña.")
        if self.max_companies > defaults.max_companies:
            raise ValueError("La campaña supera el máximo configurado de empresas.")
        if self.rubric_version not in self.config_snapshot.rubrics:
            raise ValueError("La rúbrica no existe en la configuración de campaña.")
        if self.limits is None:
            self.limits = CampaignLimits.model_validate({
                name: getattr(defaults, name) for name in CampaignLimits.model_fields
            })
        _validate_limit_reduction(self.limits.model_dump(), defaults.model_dump())
        return self


ScaleScope = Literal["group", "subsidiary", "entity", "country", "unknown"]
CustomerTier = Literal["tier_1", "tier_2", "tier_3", "unknown"]


class CompanySize(Contract):
    original_value: Text
    public_revenue: Text | None = None
    geographic_coverage: Text | None = None
    scope: ScaleScope = "unknown"
    icp_tier: CustomerTier = "unknown"
    employee_count: Count | None = None
    employee_min: Count | None = None
    employee_max: Count | None = None
    evidence_ids: SourceIds

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.employee_min is not None and self.employee_max is not None and self.employee_max < self.employee_min:
            raise ValueError("Rango de empleados invertido.")
        if self.employee_count is not None and (
            self.employee_min is not None and self.employee_count < self.employee_min
            or self.employee_max is not None and self.employee_count > self.employee_max
        ):
            raise ValueError("La cifra de empleados no pertenece al rango informado.")
        return self


class IcpTierDefinition(Contract):
    tier: Literal["tier_1", "tier_2", "tier_3"]
    acv_potential: Text
    general_industry_revenue: Text
    software_fintech_employees: Text
    software_fintech_funding: Text
    employee_min: Count | None = None
    employee_max: Count | None = None
    revenue_min_usd_millions: Count | None = None
    revenue_max_usd_millions: Count | None = None
    sales_motion: Literal["outbound_sales_led", "inbound_self_serve"]
    priority_label: Text
    source_reference: Text

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.employee_min is not None and self.employee_max is not None and self.employee_max < self.employee_min:
            raise ValueError("Rango de empleados de tier invertido.")
        if (
            self.revenue_min_usd_millions is not None
            and self.revenue_max_usd_millions is not None
            and self.revenue_max_usd_millions < self.revenue_min_usd_millions
        ):
            raise ValueError("Rango de ingresos de tier invertido.")
        return self


class IcpReferenceCompany(Contract):
    id: Text
    name: Text
    segment: Segment
    subprofile: Text
    label: Literal["positive_reference", "negative_reference"]
    relationship: Literal["current_customer_reference", "prospect_archetype", "no_fit_pattern"]
    entity_type: EntityType = EntityType.UNKNOWN
    parent_name: Text | None = None
    brands_or_subsidiaries: Annotated[list[Text], AfterValidator(_unique)] = Field(default_factory=list)
    domains: Annotated[list[Text], AfterValidator(_unique)] = Field(default_factory=list)
    countries: Annotated[list[CountryCode], AfterValidator(_unique)] = Field(default_factory=list)
    tier_estimate: CustomerTier = "unknown"
    scale_notes: Text
    document_use_case: Text
    usage_authorization: Literal["pending", "internal_calibration_only"] = "pending"
    validation_status: Literal["pending", "validated"] = "pending"
    source_reference: Text

    @field_validator("domains")
    @classmethod
    def validate_domains(cls, values: list[str]) -> list[str]:
        return [_domain(value) for value in values]


class IcpReferenceRole(Contract):
    id: Text
    segment: Segment
    subprofile: Text
    buying_role: Literal["business_champion", "technical_champion", "economic_buyer"]
    titles_en: Annotated[list[Text], Field(min_length=1), AfterValidator(_unique)]
    titles_es: Annotated[list[Text], Field(min_length=1), AfterValidator(_unique)]
    departments: Annotated[list[Text], Field(min_length=1), AfterValidator(_unique)]
    seniorities: Annotated[list[Text], Field(min_length=1), AfterValidator(_unique)]
    rationale: Text
    validation_status: Literal["pending", "validated"] = "pending"
    source_reference: Text


class IndependentSamplePolicy(Contract):
    target_total_companies: Annotated[StrictInt, Field(ge=4, le=20)]
    target_per_country_segment: Annotated[StrictInt, Field(ge=1, le=5)]
    countries: Annotated[list[CountryCode], Field(min_length=1), AfterValidator(_unique)]
    segments: Annotated[list[Segment], Field(min_length=1), AfterValidator(_unique)]
    exclude_reference_groups: StrictBool = True
    isolation_rules: Annotated[list[Text], Field(min_length=1)]


class IcpEnterpriseConfig(Contract):
    version: Text
    validation_status: Literal["pending", "validated"]
    source_reference: Text
    source_date: date
    tiers: dict[Literal["tier_1", "tier_2", "tier_3"], IcpTierDefinition]
    reference_companies: Annotated[list[IcpReferenceCompany], Field(min_length=1)]
    reference_roles: Annotated[list[IcpReferenceRole], Field(min_length=1)]
    independent_sample_policy: IndependentSamplePolicy

    @model_validator(mode="after")
    def validate_icp(self) -> Self:
        if set(self.tiers) != {"tier_1", "tier_2", "tier_3"}:
            raise ValueError("La configuración ICP requiere los tres niveles (tier_1, tier_2, tier_3).")
        for key, item in self.tiers.items():
            if item.tier != key:
                raise ValueError("La clave del nivel debe coincidir con su identificador.")
        t3, t2, t1 = self.tiers["tier_3"], self.tiers["tier_2"], self.tiers["tier_1"]
        if (
            t3.employee_max is None or t2.employee_min is None or t2.employee_max is None or t1.employee_min is None
            or t3.employee_max + 1 != t2.employee_min
            or t2.employee_max + 1 != t1.employee_min
        ):
            raise ValueError("Los rangos de empleados entre niveles ICP deben ser contiguos y sin solape.")
        if (
            t3.revenue_max_usd_millions is None or t2.revenue_min_usd_millions is None
            or t2.revenue_max_usd_millions is None or t1.revenue_min_usd_millions is None
            or t3.revenue_max_usd_millions + 1 != t2.revenue_min_usd_millions
            or t2.revenue_max_usd_millions + 1 != t1.revenue_min_usd_millions
        ):
            raise ValueError("Los rangos de ingresos entre niveles ICP deben ser contiguos y sin solape.")
        _unique([company.id for company in self.reference_companies])
        _unique([role.id for role in self.reference_roles])
        for segment in Segment:
            positives = [c for c in self.reference_companies if c.segment == segment and c.label == "positive_reference"]
            negatives = [c for c in self.reference_companies if c.segment == segment and c.label == "negative_reference"]
            if not positives or not negatives:
                raise ValueError(f"El segmento {segment} requiere ejemplos positivos y negativos.")
        return self


CompanySourceField = Literal[
    "name", "domain", "entity_name", "entity_type", "aliases", "operating_countries", "parent_company_id", "segments", "size"
]


def _require_provenance(model: BaseModel, fields: tuple[str, ...]) -> None:
    for name in fields:
        value = getattr(model, name)
        unknown_enum = name in ("entity_type", "buying_role") and value == "unknown"
        if value is not None and not unknown_enum and name not in model.provenance:
            raise ValueError(f"El campo {name} necesita procedencia.")


class Company(Contract):
    id: UUID = Field(default_factory=uuid4)
    name: Text
    domain: Text | None = None
    entity_name: Text | None = None
    entity_type: EntityType = EntityType.UNKNOWN
    aliases: Annotated[list[Text], AfterValidator(_unique)] | None = None
    operating_countries: Annotated[list[CountryCode], Field(min_length=1), AfterValidator(_unique)] | None = None
    parent_company_id: UUID | None = None
    segments: Annotated[list[Segment], Field(min_length=1), AfterValidator(_unique)] | None = None
    size: CompanySize | None = None
    provenance: dict[CompanySourceField, SourceIds]
    identity_status: IdentityStatus = IdentityStatus.PENDING
    identity_key: Text | None = None

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _domain(value)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        _require_provenance(self, ("name", "domain", "entity_name", "entity_type", "aliases", "operating_countries", "parent_company_id", "segments"))
        if self.parent_company_id == self.id:
            raise ValueError("Una empresa no puede ser su propia matriz.")
        if self.identity_key is not None and self.identity_status != IdentityStatus.CONFIRMED:
            raise ValueError("La clave de identidad requiere identidad confirmada.")
        return self


class Evidence(Contract):
    id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    contact_id: UUID | None = None
    claim: Text
    url: HttpUrl | None = None
    provider: Text | None = None
    external_reference: Text | None = None
    excerpt: Text | None = None
    retrieved_at: UtcDatetime
    published_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None
    kind: Literal["observed", "inference", "unknown"]
    source_type: Literal["primary", "provider", "secondary", "manual"]
    contradiction_ids: ReferenceIds = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if (self.provider is None) != (self.external_reference is None):
            raise ValueError("La referencia de proveedor requiere proveedor y registro.")
        if self.url is None and self.provider is None:
            raise ValueError("La evidencia necesita URL o referencia de proveedor.")
        if self.source_type == "provider" and self.provider is None:
            raise ValueError("La fuente de proveedor necesita su referencia de registro.")
        if self.id in self.contradiction_ids:
            raise ValueError("Una evidencia no puede contradecirse a sí misma.")
        return self


class Criterion(Contract):
    value: CriterionValue
    evidence_ids: ReferenceIds = Field(default_factory=list)
    justification: Text

    @model_validator(mode="after")
    def validate_known_value(self) -> Self:
        if self.value is not None and not self.evidence_ids:
            raise ValueError("Un criterio conocido, incluido cero, necesita evidencia.")
        return self


class ProfileCitation(Contract):
    evidence_id: UUID
    quote: Annotated[Text, Field(max_length=600)]


class ProfileMatch(Contract):
    profile_id: Text
    citations: Annotated[list[ProfileCitation], Field(min_length=1)]


class Assessment(Contract):
    id: UUID = Field(default_factory=uuid4)
    campaign_id: UUID
    company_id: UUID
    criteria: dict[CriterionName, Criterion]
    fit_score: Score | None = None
    coverage: Ratio
    priority: Priority
    products: list[Text] = Field(default_factory=list)
    target_roles: list[Text] = Field(default_factory=list)
    model_id: Text | None = None
    prompt_version: Text | None = None
    rubric_version: Text
    explanation: Text
    created_at: UtcDatetime = Field(default_factory=utc_now)
    revision_of: UUID | None = None
    profile_matches: list[ProfileMatch] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_structure(self) -> Self:
        _unique([match.profile_id for match in self.profile_matches])
        if set(self.criteria) != CRITERION_NAMES:
            raise ValueError("La evaluación requiere los cinco criterios.")
        if (self.model_id is None) != (self.prompt_version is None):
            raise ValueError("Modelo y versión de prompt deben conservarse juntos.")
        if self.revision_of == self.id:
            raise ValueError("Una evaluación no puede revisarse a sí misma.")
        return self


class Channel(Contract):
    contact_id: UUID
    type: ChannelType
    value: Text
    evidence_ids: SourceIds
    provider_status: Text | None = None
    normalized_status: ChannelStatus = ChannelStatus.UNKNOWN
    published_evidence_ids: ReferenceIds = Field(default_factory=list)
    retrieved_at: UtcDatetime
    verified_at: UtcDatetime | None = None
    manual_confirmed_at: UtcDatetime | None = None
    manual_confirmation_reason: Text | None = None
    professional: StrictBool | None = None
    direct: StrictBool | None = None
    phone_country: CountryCode | None = None
    extension: Text | None = None
    warnings: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_observations(self) -> Self:
        if self.type == ChannelType.EMAIL:
            if not re.fullmatch(r"[^@\s<>(),;:\"]+@[^@\s]+\.[^@\s]+", self.value):
                raise ValueError("Formato de correo inválido.")
            local_part, domain = self.value.rsplit("@", 1)
            self.value = f"{local_part}@{_domain(domain)}"
        if self.type in (ChannelType.PHONE, ChannelType.WHATSAPP) and not re.fullmatch(r"\+[1-9][0-9]{1,14}", self.value):
            raise ValueError("El teléfono necesita formato internacional E.164.")
        if self.type == ChannelType.PHONE and self.phone_country is None:
            raise ValueError("El teléfono necesita país comprobado.")
        if self.extension is not None and not re.fullmatch(r"[0-9]+", self.extension):
            raise ValueError("La extensión debe ser numérica.")
        if self.type == ChannelType.LINKEDIN:
            url = HttpUrl(self.value)
            if url.host != "linkedin.com" and not url.host.endswith(".linkedin.com"):
                raise ValueError("El perfil debe pertenecer a LinkedIn.")
        elif self.type == ChannelType.OTHER and self.value.startswith(("http://", "https://")):
            HttpUrl(self.value)
        if self.normalized_status == ChannelStatus.VERIFIED and self.verified_at is None:
            raise ValueError("La verificación necesita fecha.")
        if self.normalized_status == ChannelStatus.PUBLISHED_PROFESSIONAL and not self.published_evidence_ids:
            raise ValueError("La publicación profesional necesita evidencia nominal.")
        if (self.manual_confirmed_at is None) != (self.manual_confirmation_reason is None):
            raise ValueError("La confirmación manual necesita fecha y motivo.")
        if self.normalized_status == ChannelStatus.MANUAL_CONFIRMED and self.manual_confirmed_at is None:
            raise ValueError("Falta confirmación manual.")
        if (self.phone_country is not None or self.extension is not None) and self.type not in (ChannelType.PHONE, ChannelType.WHATSAPP):
            raise ValueError("País telefónico y extensión corresponden a canales telefónicos.")
        return self


ContactSourceField = Literal["name", "title", "buying_role", "geographic_scope", "relevant_function", "current_employment"]


class Contact(Contract):
    id: UUID = Field(default_factory=uuid4)
    company_id: UUID
    name: Text | None = None
    title: Text | None = None
    name_complete: StrictBool | None = None
    current_employment: StrictBool | None = None
    relevant_function: StrictBool | None = None
    identity_status: IdentityStatus = IdentityStatus.PENDING
    buying_role: BuyingRole = BuyingRole.UNKNOWN
    geographic_scope: Text | None = None
    provenance: dict[ContactSourceField, SourceIds] = Field(default_factory=dict)
    employment_evidence_ids: ReferenceIds = Field(default_factory=list)
    channels: list[Channel] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        _require_provenance(self, ("name", "title", "buying_role", "geographic_scope", "relevant_function"))
        if self.name_complete is not None and self.name is None:
            raise ValueError("La completitud del nombre necesita un nombre observado.")
        if self.identity_status == IdentityStatus.CONFIRMED and (self.name is None or self.name_complete is not True):
            raise ValueError("La identidad confirmada necesita un nombre completo respaldado.")
        if self.current_employment is not None and not self.employment_evidence_ids:
            raise ValueError("La relación laboral conocida necesita evidencia.")
        if any(channel.contact_id != self.id for channel in self.channels):
            raise ValueError("El canal pertenece a otro contacto.")
        _unique([(channel.type, channel.value) for channel in self.channels])
        return self


class ConsumedLimits(Contract):
    web_queries: Count = 0
    pages: Count = 0
    people_queries: Count = 0
    enrichments: Count = 0
    email_verifications: Count = 0
    active_seconds: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)] = 0.0
    contacts_active_seconds: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)] = 0.0


class RunItem(Contract):
    campaign_id: UUID
    company_id: UUID
    stage: RunStage = RunStage.DISCOVERED
    last_assessment_id: UUID | None = None
    business_status: BusinessStatus | None = None
    attempts: dict[Text, Count] = Field(default_factory=dict)
    consumed_limits: ConsumedLimits = Field(default_factory=ConsumedLimits)
    stop_reason: Text | None = None
    error_message: Text | None = None
    error_stage: RunStage | None = None
    review_status: Literal["accepted", "rejected", "pending"] = "pending"
    review_reason: Text | None = None
    reviewed_at: UtcDatetime | None = None
    updated_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        if self.review_status != "pending" and (self.review_reason is None or self.reviewed_at is None):
            raise ValueError("La revisión necesita motivo y fecha.")
        if (self.review_reason is None) != (self.reviewed_at is None):
            raise ValueError("La revisión conserva juntos motivo y fecha.")
        return self


class TokenUsage(Contract):
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    cache_read_tokens: Count | None = None
    cache_write_tokens: Count | None = None
    additional_tokens: Count | None = None


class Usage(Contract):
    request_id: UUID = Field(default_factory=uuid4)
    campaign_id: UUID
    company_id: UUID | None = None
    provider: Text
    operation: Text
    account_ref: Text | None = None
    request_fingerprint: Annotated[StrictStr, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    reserved_cost_usd: Money | None = None
    reserved_credits: Money | None = None
    reserved_tokens: TokenUsage | None = None
    tokens: TokenUsage | None = None
    credits: Money | None = None
    estimated_cost_usd: Money | None = None
    final_cost_usd: Money | None = None
    outlay_usd: Money | None = None
    funding_source: Literal["free_credit", "prepaid", "new_outlay"] | None = None
    status: UsageStatus
    outcome: Literal["succeeded", "failed", "unknown"] | None = None
    error_message: Text | None = None
    created_at: UtcDatetime = Field(default_factory=utc_now)
    finished_at: UtcDatetime | None = None
    reconciled_at: UtcDatetime | None = None
