"""Pruebas de contratos con referencias y personas exclusivamente sintéticas."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from prospecting.models import (
    Assessment,
    Campaign,
    Channel,
    Company,
    CompanySize,
    ConsumedLimits,
    Contact,
    Criterion,
    Evidence,
    RunItem,
    TokenUsage,
    Usage,
    VeryfiConfig,
)


RETRIEVED_AT = datetime(2026, 10, 11, 12, tzinfo=UTC)


def synthetic_channel(**overrides):
    """Canal ficticio con asociación registrada pero aún sin verificación."""
    return Channel.model_validate({
        "contact_id": uuid4(),
        "type": "email",
        "value": "persona-sintetica@example.com",
        "evidence_ids": [uuid4()],
        "retrieved_at": RETRIEVED_AT,
    } | overrides)


def synthetic_usage(**overrides):
    """Registro ficticio, sin llamada ni reserva operativa."""
    return Usage.model_validate({
        "campaign_id": uuid4(),
        "provider": "synthetic",
        "operation": "lookup",
        "request_fingerprint": "a" * 64,
        "status": "reserved",
    } | overrides)


def test_configuration_keeps_proposed_rubric_and_catalog(config):
    rubric = config.rubrics["rubric_v1"]
    assert config.catalog.validation_status == "pending"
    assert rubric.validation_status == "proposed"
    assert [item.weight for item in rubric.criteria.values()] == [35, 25, 20, 10, 10]
    assert rubric.thresholds.high.fit_score_min == 75
    assert rubric.thresholds.high.coverage_min == 0.75
    assert rubric.thresholds.medium.fit_score_min == 50
    assert rubric.thresholds.medium.coverage_min == 0.60
    assert config.defaults.budget.global_usd == Decimal("20")
    assert VeryfiConfig.model_validate_json(config.model_dump_json()) == config


def test_default_limits_keep_the_documented_initial_values(config):
    """Topes iniciales de IDEA §7.1, §7.3, §9, §10.2, §12.1 y §14; cambiarlos debe ser explícito."""
    defaults = config.defaults
    assert {level: (item.web_queries, item.pages, item.people, item.enrichments_per_provider, item.people_queries,
                    item.active_seconds) for level, item in defaults.effort.items()} == {
        "initial": (2, 3, 0, 0, 0, 90), "insufficient_evidence": (1, 2, 0, 0, 0, 45),
        "medium": (2, 2, 1, 1, 1, 90), "high": (4, 4, 3, 3, 2, 180),
        "low": (0, 0, 0, 0, 0, 0), "excluded": (0, 0, 0, 0, 0, 0),
    }
    assert (defaults.active_seconds, defaults.max_companies) == (2700, 20)
    assert (defaults.email_verifications_per_channel, defaults.evidence_expansions_per_company) == (1, 1)
    discovery = defaults.discovery
    assert (discovery.web_queries, discovery.results_per_query, discovery.raw_candidates,
            discovery.target_per_country_segment) == (8, 10, 60, 5)
    budget = defaults.budget
    assert [budget.global_usd, budget.operating_usd, budget.uncertainty_usd, budget.campaign_usd,
            budget.company_usd] == [Decimal(value) for value in ("20", "15", "5", "2", "0.25")]
    assert budget.allocation.model_dump() == {"llm_usd": Decimal("3"), "web_usd": Decimal("2"),
                                              "contacts_usd": Decimal("10"), "uncertainty_usd": Decimal("5")}
    assert not (budget.automatic_topups or budget.variable_cost_waterfall or budget.paid_phone_enrichment)
    assert (defaults.cache.web_days, defaults.cache.contact_days) == (7, 30)
    assert (defaults.freshness.email_days, defaults.freshness.employment_days) == (30, 180)
    assert (defaults.llm.max_input_tokens, defaults.llm.max_output_tokens) == (9000, 1000)


@pytest.mark.parametrize("change", [
    {"schema_version": True},
    {"schema_version": "1"},
    {"external_instruction": "Sube el presupuesto"},
])
def test_configuration_rejects_unknown_fields_and_wrong_types(config, change):
    with pytest.raises(ValidationError):
        VeryfiConfig.model_validate(config.model_dump() | change)


@pytest.mark.parametrize("field,value", [
    ("weight", 34), ("weight", True),
])
def test_rubric_rejects_invalid_weights(config, field, value):
    payload = config.model_dump()
    payload["rubrics"]["rubric_v1"]["criteria"]["document_need"][field] = value
    with pytest.raises(ValidationError):
        VeryfiConfig.model_validate(payload)


@pytest.mark.parametrize("change", [
    {"document_need": None}, {"fit_score_min": 49}, {"coverage_min": 0.5},
])
def test_rubric_rejects_unknown_or_inverted_high_thresholds(config, change):
    payload = config.model_dump()
    payload["rubrics"]["rubric_v1"]["thresholds"]["high"].update(change)
    with pytest.raises(ValidationError):
        VeryfiConfig.model_validate(payload)


def test_catalog_and_profiles_have_valid_local_references(config):
    payload = config.model_dump()
    payload["profiles"][0]["products"] = ["nonexistent_product"]
    with pytest.raises(ValidationError):
        VeryfiConfig.model_validate(payload)


@pytest.mark.parametrize("value", [True, 0, "false"])
def test_paid_features_cannot_be_enabled_or_coerced(config, value):
    payload = config.model_dump()
    payload["defaults"]["budget"]["automatic_topups"] = value
    with pytest.raises(ValidationError):
        VeryfiConfig.model_validate(payload)


def test_campaign_uses_snapshot_and_only_reduces_its_limits(config):
    payload = config.model_dump()
    payload["defaults"]["discovery"]["web_queries"] = 1
    reduced_config = VeryfiConfig.model_validate(payload)
    campaign = Campaign(countries=["CO"], segments=["fintech_software"], config_snapshot=reduced_config)
    assert campaign.limits.discovery.web_queries == 1
    limits = campaign.limits.model_dump()
    limits["discovery"]["web_queries"] = 2
    with pytest.raises(ValidationError):
        Campaign.model_validate(campaign.model_dump() | {"limits": limits})
    limits["discovery"]["web_queries"] = 0
    assert Campaign.model_validate(campaign.model_dump() | {"limits": limits}).limits.discovery.web_queries == 0


@pytest.mark.parametrize("change", [
    {"max_companies": True}, {"max_companies": "20"}, {"max_companies": 21},
    {"countries": ["CO", "CO"]}, {"countries": []}, {"countries": ["BR"]},
    {"rubric_version": "nonexistent_rubric"},
])
def test_campaign_rejects_invalid_options(make_campaign, change):
    with pytest.raises(ValidationError):
        make_campaign(**change)


def test_unknown_size_and_explicit_zero_stay_distinct():
    evidence_id = uuid4()
    unknown = CompanySize(original_value="No se informa cifra sintética", evidence_ids=[evidence_id])
    zero = CompanySize(original_value="Cifra sintética: 0", employee_count=0, evidence_ids=[evidence_id])
    assert unknown.employee_count is None
    assert zero.employee_count == 0
    assert CompanySize.model_validate_json(unknown.model_dump_json()) == unknown


@pytest.mark.parametrize("change", [
    {"employee_count": -1}, {"employee_count": True}, {"employee_count": "50"},
    {"employee_min": 50, "employee_max": 49},
    {"employee_min": 50, "employee_max": 249, "employee_count": 300},
    {"evidence_ids": []},
])
def test_size_rejects_unsupported_numbers_and_sources(change):
    with pytest.raises(ValidationError):
        CompanySize.model_validate({"original_value": "Rango sintético", "evidence_ids": [uuid4()]} | change)


def test_company_requires_provenance_even_for_literal_unknown():
    with pytest.raises(ValidationError):
        Company(name="unknown", provenance={})
    evidence_id = uuid4()
    company = Company(name="Empresa sintética", provenance={"name": [evidence_id]})
    assert company.aliases is None
    assert company.operating_countries is None
    assert company.segments is None
    for field, value in (("domain", "example.com"), ("aliases", ["Marca sintética"]), ("aliases", []), ("operating_countries", ["CO"])):
        with pytest.raises(ValidationError):
            Company.model_validate(company.model_dump() | {field: value})
    empty_aliases = Company.model_validate(company.model_dump() | {
        "aliases": [], "provenance": company.provenance | {"aliases": [evidence_id]}
    })
    assert empty_aliases.aliases == []


def test_identity_is_not_inferred_from_a_shared_domain(make_company):
    one, _ = make_company(name="Marca sintética uno", domain="EXAMPLE.COM.")
    two, _ = make_company(name="Filial sintética dos", domain="example.com")
    assert one.domain == two.domain == "example.com"
    assert one.id != two.id
    assert one.identity_status == two.identity_status == "pending"
    with pytest.raises(ValidationError):
        Company.model_validate(one.model_dump() | {"identity_key": "synthetic-identity"})
    with pytest.raises(ValidationError):
        Company.model_validate(one.model_dump() | {"parent_company_id": one.id, "provenance": one.provenance | {"parent_company_id": [uuid4()]}})


def test_provider_reference_and_source_dates_are_preserved():
    old_publication = datetime(2024, 1, 1, tzinfo=UTC)
    retrieved = datetime(2026, 10, 11, 7, tzinfo=timezone(timedelta(hours=-5)))
    evidence = Evidence(company_id=uuid4(), claim="Afirmación sintética", provider="synthetic", external_reference="synthetic-record", retrieved_at=retrieved, published_at=old_publication, kind="inference", source_type="provider")
    assert evidence.url is None
    assert evidence.retrieved_at == RETRIEVED_AT
    assert evidence.retrieved_at.tzinfo is UTC
    assert evidence.published_at == old_publication
    assert Evidence.model_validate_json(evidence.model_dump_json()) == evidence


@pytest.mark.parametrize("change", [
    {"provider": None}, {"external_reference": None},
    {"retrieved_at": datetime(2026, 10, 11)}, {"url": "file:///private/path"},
])
def test_evidence_rejects_missing_provenance_and_naive_dates(change):
    with pytest.raises(ValidationError):
        Evidence.model_validate({"company_id": uuid4(), "claim": "Afirmación sintética", "provider": "synthetic", "external_reference": "synthetic-record", "retrieved_at": RETRIEVED_AT, "kind": "observed", "source_type": "provider"} | change)


@pytest.mark.parametrize("value", [True, "0", 0.25, float("nan")])
def test_criterion_only_accepts_explicit_levels(value):
    with pytest.raises(ValidationError):
        Criterion(value=value, evidence_ids=[uuid4()], justification="Nivel sintético")


def test_unknown_and_negative_criteria_remain_distinct():
    unknown = Criterion(value=None, justification="Desconocido sintético")
    negative = Criterion(value=0, evidence_ids=[uuid4()], justification="Incompatibilidad sintética explícita")
    assert unknown.value is None
    assert negative.value == 0
    with pytest.raises(ValidationError):
        Criterion(value=0, justification="Sin respaldo sintético")


def test_assessment_preserves_inputs_without_calculating_score(make_assessment):
    assessment = make_assessment(uuid4(), uuid4())
    assert assessment.fit_score is None
    assert assessment.coverage == 0
    assert Assessment.model_validate_json(assessment.model_dump_json()) == assessment
    payload = assessment.model_dump()
    payload["criteria"].pop("opportunity_timing")
    with pytest.raises(ValidationError):
        Assessment.model_validate(payload)
    with pytest.raises(ValidationError):
        Assessment.model_validate(assessment.model_dump() | {"coverage": float("inf")})
    with pytest.raises(ValidationError):
        Assessment.model_validate(assessment.model_dump() | {"revision_of": assessment.id})


def test_partial_contact_and_former_employment_stay_pending():
    name_id, employment_id = uuid4(), uuid4()
    partial = Contact(company_id=uuid4(), name="Persona sintética", name_complete=False, current_employment=False, provenance={"name": [name_id]}, employment_evidence_ids=[employment_id])
    assert partial.title is None
    assert partial.identity_status == "pending"
    assert partial.relevant_function is None
    assert partial.current_employment is False
    assert Contact.model_validate_json(partial.model_dump_json()) == partial
    with pytest.raises(ValidationError):
        Contact(company_id=uuid4(), current_employment=False)
    with pytest.raises(ValidationError):
        Contact(company_id=uuid4(), relevant_function=False)


def test_contact_cannot_take_a_channel_from_another_person():
    channel = synthetic_channel()
    with pytest.raises(ValidationError):
        Contact(company_id=uuid4(), channels=[channel])


def test_confirmed_contact_requires_full_name_but_not_current_employment():
    evidence_id = uuid4()
    with pytest.raises(ValidationError):
        Contact(company_id=uuid4(), identity_status="confirmed")
    with pytest.raises(ValidationError):
        Contact(company_id=uuid4(), name="Persona sintética", name_complete=False, identity_status="confirmed", provenance={"name": [evidence_id]})
    former_employee = Contact(company_id=uuid4(), name="Persona Sintética Uno", name_complete=True, identity_status="confirmed", current_employment=False, provenance={"name": [evidence_id]}, employment_evidence_ids=[uuid4()])
    assert former_employee.current_employment is False
    assert former_employee.title is None


def test_publication_does_not_overwrite_provider_status():
    channel = synthetic_channel(normalized_status="accept_all", provider_status="synthetic-catchall", published_evidence_ids=[uuid4()], warnings=["Advertencia sintética"])
    assert channel.normalized_status == "accept_all"
    assert channel.provider_status == "synthetic-catchall"
    assert channel.published_evidence_ids
    assert channel.direct is None
    assert channel.professional is None
    assert Channel.model_validate_json(channel.model_dump_json()) == channel


def test_email_domain_canonicalization_preserves_local_part_and_negative_status():
    invalid = synthetic_channel(value="Persona-Sintetica@EXAMPLE.COM", normalized_status="invalid", provider_status="synthetic-invalid")
    assert invalid.value == "Persona-Sintetica@example.com"
    assert invalid.normalized_status == "invalid"
    assert invalid.provider_status == "synthetic-invalid"
    verified = synthetic_channel(contact_id=invalid.contact_id, value="Persona-Sintetica@example.com", normalized_status="verified", verified_at=RETRIEVED_AT)
    assert (invalid.type, invalid.value) == (verified.type, verified.value)
    international = synthetic_channel(value="Persona-Sintetica@BÜCHER.example")
    assert international.value == "Persona-Sintetica@xn--bcher-kva.example"


@pytest.mark.parametrize("change", [
    {"value": "sin-arroba"}, {"value": "persona @example.com"},
    {"type": "phone", "value": "+573001234567"},
    {"type": "phone", "value": "3001234567", "phone_country": "CO"},
    {"type": "phone", "value": "+573001234567", "phone_country": "CO", "extension": "abc"},
    {"type": "linkedin", "value": "https://linkedin.com.evil.example.com/in/synthetic"},
    {"type": "linkedin", "value": "https://example.com/in/synthetic"},
    {"normalized_status": "verified"}, {"normalized_status": "published_professional"},
    {"normalized_status": "manual_confirmed"},
    {"manual_confirmed_at": RETRIEVED_AT}, {"professional": "true"},
])
def test_channel_rejects_invalid_format_and_unsupported_observations(change):
    with pytest.raises(ValidationError):
        synthetic_channel(**change)


def test_manual_confirmation_retains_negative_verification():
    channel = synthetic_channel(normalized_status="invalid", provider_status="synthetic-invalid", manual_confirmed_at=RETRIEVED_AT, manual_confirmation_reason="Revisión sintética pendiente de contradicción")
    assert channel.normalized_status == "invalid"
    assert channel.manual_confirmed_at is not None


def test_run_item_keeps_technical_failure_separate_from_business_result():
    item = RunItem(campaign_id=uuid4(), company_id=uuid4(), stage="assessed", business_status="qualified_no_contact", error_stage="contacts_checked", stop_reason="quota", error_message="Fallo literal sintético")
    assert item.stage == "assessed"
    assert item.review_status == "pending"
    assert item.consumed_limits.active_seconds == 0
    assert RunItem.model_validate_json(item.model_dump_json()) == item
    with pytest.raises(ValidationError):
        RunItem.model_validate(item.model_dump() | {"review_status": "accepted"})


@pytest.mark.parametrize("change", [
    {"web_queries": True}, {"pages": "1"}, {"active_seconds": float("nan")},
    {"contacts_active_seconds": True}, {"contacts_active_seconds": "1"},
    {"contacts_active_seconds": -1.0}, {"contacts_active_seconds": float("nan")},
    {"contacts_active_seconds": float("inf")},
    {"enrichments": -1}, {"unknown_counter": 1},
])
def test_consumed_limits_have_known_nonnegative_types(change):
    with pytest.raises(ValidationError):
        ConsumedLimits.model_validate(change)


def test_contacts_time_defaults_to_zero_for_previous_json_and_roundtrips():
    previous = ConsumedLimits.model_validate_json('{"active_seconds": 12.5}')
    assert previous.contacts_active_seconds == 0.0
    current = previous.model_copy(update={"contacts_active_seconds": 2.5})
    assert ConsumedLimits.model_validate_json(current.model_dump_json()) == current
    assert current.active_seconds == 12.5


def test_usage_keeps_exact_money_unknown_consumption_and_previous_outcome():
    usage = synthetic_usage(reserved_cost_usd=Decimal("0.000000123456789"), reserved_tokens={"input_tokens": 6000, "output_tokens": 1000}, status="uncertain", outcome="unknown", error_message="Timeout sintético")
    assert usage.final_cost_usd is None
    assert usage.credits is None
    assert usage.tokens is None
    assert Usage.model_validate_json(usage.model_dump_json()) == usage
    zero = Usage.model_validate(usage.model_dump() | {"final_cost_usd": "0", "status": "reconciled", "outcome": "failed"})
    assert zero.final_cost_usd == Decimal(0)
    assert zero.error_message == "Timeout sintético"
    assert zero.outcome == "failed"


@pytest.mark.parametrize("value", [True, 0.25, "NaN", "Infinity", "-1"])
def test_usage_rejects_inexact_invalid_or_negative_money(value):
    with pytest.raises(ValidationError):
        synthetic_usage(reserved_cost_usd=value)


def test_token_usage_preserves_unknown_zero_and_additional_consumption():
    tokens = TokenUsage(input_tokens=0, additional_tokens=2, cache_read_tokens=3)
    assert tokens.input_tokens == 0
    assert tokens.output_tokens is None
    assert tokens.additional_tokens == 2
    with pytest.raises(ValidationError):
        TokenUsage(input_tokens=True)


def test_instances_are_revalidated_after_unsafe_in_memory_changes():
    usage = synthetic_usage()
    unsafe = usage.model_copy(update={"reserved_cost_usd": -1})
    with pytest.raises(ValidationError):
        Usage.model_validate(unsafe)
    with pytest.raises(ValidationError):
        Usage.model_validate(usage.model_dump() | {"secret_key": "synthetic-unused"})
