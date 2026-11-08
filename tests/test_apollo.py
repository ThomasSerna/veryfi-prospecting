"""Apollo con identidades, credenciales y transporte exclusivamente sintéticos."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from types import SimpleNamespace
from uuid import uuid4, uuid5

from pydantic import ValidationError
import pytest

from prospecting.budget import AccountAllowance, Budget, BudgetError, SpendingAuthorization
from prospecting.contacts import ContactError
from prospecting.models import Usage, utc_now
from prospecting.providers import HttpResponse, ProviderClient, ProviderError
from prospecting.providers.apollo import (
    APOLLO_OPERATIONS, APOLLO_STOP_REASONS, FREE_RATE_LIMITS, ApolloAccess, ApolloEnrichmentResponse, ApolloSearchResponse,
    classify_apollo_error, enrichment_request, parse_enrichment, parse_search,
    people_search_request, person_id,
)


NOW = datetime(2026, 10, 20, tzinfo=UTC)
PERSON_ID = "persona-sintetica"


def search_response():
    return ApolloSearchResponse.model_validate({"total_entries": 1, "people": [{
        "id": PERSON_ID, "first_name": "Persona", "last_name_obfuscated": "Si***a",
        "title": "CTO", "last_refreshed_at": NOW.isoformat(), "has_email": True,
        "organization": {"name": "Empresa sintética"},
    }]})


def enrichment_response(**overrides):
    return ApolloEnrichmentResponse.model_validate({"person": {
        "id": PERSON_ID, "first_name": "Persona", "last_name": "Sintética",
        "name": "Persona Sintética", "title": "CTO", "match_confidence": "high",
        "email": "persona-sintetica@example.com", "email_status": "verified",
        "organization_id": "empresa-sintetica",
        "organization": {"id": "empresa-sintetica", "name": "Empresa sintética", "primary_domain": "example.com"},
        "employment_history": [{"current": True, "organization_id": "empresa-sintetica",
                                "organization_name": "Empresa sintética", "title": "CTO", "start_date": "2020-01-01"}],
    } | overrides})


@pytest.fixture
def apollo_company(make_company):
    company, _ = make_company(domain="example.com", entity_name="Empresa sintética", identity_status="confirmed")
    return company


@pytest.fixture
def apollo_case(database, make_campaign, config, monkeypatch, apollo_company):
    campaign = make_campaign()
    database.save_campaign(campaign)
    allowance = AccountAllowance(provider="apollo", account_ref="apollo-sintetico", funding_source="free_credit",
                                 credit_limit="10", cost_limit_usd="0", source_reference="Cupo sintético", observed_at=NOW)
    budget = Budget(database, config.defaults.budget, [allowance])
    case = SimpleNamespace(db=database, campaign=campaign, company=apollo_company, budget=budget, calls=[],
                           request=people_search_request(apollo_company, ["CTO"], "apollo-sintetico"),
                           response=HttpResponse(status=200, headers={"Content-Type": "application/json"},
                                                 body=search_response().model_dump_json().encode()))

    def transport(prepared, timeout, max_bytes):
        case.calls.append(prepared)
        return case.response

    case.client = ProviderClient(budget, APOLLO_OPERATIONS, transport=transport)

    def reserve(credits="0"):
        grant = budget.authorize(SpendingAuthorization(
            provider="apollo", operation=case.request.operation, account_ref="apollo-sintetico",
            max_cost_usd="0", max_credits="10", responsible="Responsable sintético",
            source_reference="Autorización sintética sin red", authorized_at=utc_now()))
        usage = budget.reserve(Usage(
            campaign_id=campaign.id, provider="apollo", operation=case.request.operation,
            account_ref="apollo-sintetico", request_fingerprint=case.client.fingerprint(case.request),
            reserved_cost_usd="0", reserved_credits=credits, funding_source="free_credit", status="reserved"), grant)
        return usage, grant

    case.reserve = reserve
    monkeypatch.setenv("APOLLO_API_KEY", "clave-apollo-exclusivamente-sintetica")
    return case


def test_access_defaults_do_not_prove_account_and_reject_unbounded_limits():
    access = ApolloAccess(account_ref="apollo-sintetico", source_reference="Comprobación sintética", observed_at=NOW)
    assert access.work_email_verified is False
    assert access.access_verified is False
    assert access.enrichment_credit_bound == Decimal("1")
    for changes in ({"enrichment_credit_bound": "0"}, {"enrichment_credit_bound": "2"},
                    {"plan": "unknown"}, {"observed_at": utc_now() + timedelta(days=1)},
                    {"enabled_operations": ["people_search", "people_search"]}):
        with pytest.raises(ValidationError):
            ApolloAccess.model_validate(access.model_dump() | changes)


def test_search_and_enrichment_are_bounded_and_disable_optional_data(apollo_company):
    broad = people_search_request(apollo_company, ["CTO"], "apollo-sintetico")
    assert broad.payload == {"q_organization_domains_list": ["example.com"], "page": 1, "per_page": 10}
    targeted = people_search_request(apollo_company, ["CTO", "CTO", "VP Engineering"], "apollo-sintetico", by_roles=True)
    assert targeted.payload["person_titles"] == ["CTO", "VP Engineering"]
    assert targeted.payload["include_similar_titles"] is False
    assert enrichment_request(PERSON_ID, "apollo-sintetico").payload == {
        "id": PERSON_ID, "reveal_personal_emails": False, "reveal_phone_number": False,
        "run_waterfall_email": False, "run_waterfall_phone": False,
    }
    with pytest.raises(ContactError):
        people_search_request(apollo_company.model_copy(update={"identity_status": "pending"}), [], "apollo-sintetico")
    with pytest.raises(ContactError):
        enrichment_request("", "apollo-sintetico")


def test_free_plan_rate_limits_are_the_published_ones_and_cannot_be_loosened():
    """T17: límites del plan Free publicados en docs.apollo.io/reference/rate-limits (2026-11-07)."""
    published = {"per_minute": 50, "per_hour": 200, "per_day": 600}
    assert {name: limit.model_dump() for name, limit in FREE_RATE_LIMITS.items()} == {
        "people_search": published, "people_enrichment": published}
    base = {"account_ref": "apollo-sintetico", "source_reference": "Comprobación sintética", "observed_at": NOW}
    access = ApolloAccess.model_validate_json(json.dumps(base | {"observed_at": NOW.isoformat()}))
    assert access.rate_limits == FREE_RATE_LIMITS
    stricter = ApolloAccess(**base, rate_limits={
        "people_search": {"per_minute": 10, "per_hour": 100, "per_day": 300},
        "people_enrichment": {"per_minute": 5, "per_hour": 50, "per_day": 100}})
    assert stricter.rate_limits["people_enrichment"].per_minute == 5
    for limits in ({"people_search": {"per_minute": 51, "per_hour": 200, "per_day": 600},
                    "people_enrichment": published},
                   {"people_search": published},
                   {"people_search": {"per_minute": 300, "per_hour": 200, "per_day": 600}, "people_enrichment": published}):
        with pytest.raises(ValidationError):
            ApolloAccess(**base, rate_limits=limits)


def test_partial_search_identity_never_becomes_ready_and_id_is_stable(apollo_company):
    contact, evidence = parse_search(apollo_company, search_response(), uuid4(), NOW)[0]
    assert contact.id == uuid5(apollo_company.id, f"apollo:{PERSON_ID}")
    assert contact.name == "Persona Si***a"
    assert contact.name_complete is False
    assert contact.identity_status == "pending"
    assert contact.current_employment is None
    assert contact.channels == []
    assert person_id(contact, evidence) == PERSON_ID
    assert person_id(contact, []) is None
    assert all(item.provider == "apollo" and item.external_reference.startswith("apollo_v1:") for item in evidence)
    assert all(item.updated_at is None and item.published_at is None for item in evidence)
    assert parse_search(apollo_company, ApolloSearchResponse(total_entries=0, people=[]), uuid4(), NOW) == []


def test_enrichment_resolves_identity_without_fabricating_verification_or_employment_dates(apollo_company):
    candidate, _ = parse_search(apollo_company, search_response(), uuid4(), NOW)[0]
    contact, evidence = parse_enrichment(candidate, apollo_company, enrichment_response(
        verified_at=NOW.isoformat(), current_employment=True,
        contact={"name": "Otra Persona", "email": "intruso@example.org"},
        phone_numbers=[{"raw_number": "+573001234567"}],
    ), uuid4(), NOW)
    assert contact.name == "Persona Sintética"
    assert contact.identity_status == "confirmed"
    assert contact.current_employment is None
    assert len(contact.channels) == 1
    email = contact.channels[0]
    assert email.value == "persona-sintetica@example.com"
    assert email.normalized_status == "unknown"
    assert email.provider_status == "verified"
    assert email.verified_at is None
    assert email.professional and email.direct
    assert any(item.external_reference.endswith("#enrichment") for item in evidence)
    assert all(item.updated_at is None and item.published_at is None for item in evidence)


@pytest.mark.parametrize("changes,code", [
    ({"id": "otra-persona"}, "identity_mismatch"),
    ({"match_confidence": "medium"}, "identity_unconfirmed"),
    ({"match_confidence": "none"}, "identity_unconfirmed"),
    # T17: cada condición de entidad tiene su código; ninguno contiene datos de la persona.
    ({"organization_id": "otra-empresa"}, "entity_mismatch_organization_id"),
    ({"organization": {"id": "empresa-sintetica", "name": "Empresa sintética", "primary_domain": "another.example"}},
     "entity_mismatch_domain"),
    ({"organization": None}, "entity_mismatch_no_organization"),
    ({"organization": {"id": None, "name": "Empresa sintética", "primary_domain": "example.com"}},
     "entity_mismatch_no_organization"),
    ({"organization": {"id": "empresa-sintetica", "name": "Compañía completamente distinta", "primary_domain": "example.com"}},
     "entity_mismatch_name"),
    ({"employment_history": [{"current": False, "organization_id": "empresa-sintetica"}]}, "entity_mismatch_not_current"),
    ({"employment_history": []}, "entity_mismatch_not_current"),
    ({"employment_history": [{"current": True, "organization_id": "empresa-sintetica", "end_date": "2025-01-01"}]},
     "entity_mismatch_not_current"),
    ({"name": "Otra Persona"}, "identity_mismatch"),
])
def test_enrichment_rejects_mismatched_identity_or_previous_employer(apollo_company, changes, code):
    candidate, _ = parse_search(apollo_company, search_response(), uuid4(), NOW)[0]
    with pytest.raises(ContactError) as caught:
        parse_enrichment(candidate, apollo_company, enrichment_response(**changes), uuid4(), NOW)
    assert caught.value.code == code
    assert candidate.channels == []


def test_enrichment_with_no_match_preserves_candidate(apollo_company):
    candidate, _ = parse_search(apollo_company, search_response(), uuid4(), NOW)[0]
    assert parse_enrichment(candidate, apollo_company, ApolloEnrichmentResponse(person=None), uuid4(), NOW) == (candidate, [])


@pytest.mark.parametrize("payload", [{}, {"total_entries": 1}, {"people": []},
                                      {"total_entries": 1, "people": [{"id": 123}]},
                                      {"total_entries": 1, "people": [{"id": PERSON_ID, "has_email": "yes"}]}])
def test_malformed_provider_data_is_rejected(payload):
    with pytest.raises(ValidationError):
        ApolloSearchResponse.model_validate(payload)


def test_free_search_still_requires_reservation_and_uses_scoped_auth(apollo_case):
    case = apollo_case
    with pytest.raises((BudgetError, ProviderError)):
        case.client.request_json(uuid4(), case.request, ApolloSearchResponse)
    assert case.calls == []
    usage, grant = case.reserve()
    result = case.client.request_json(usage.request_id, case.request, ApolloSearchResponse, authorization=grant)
    prepared = case.calls[0]
    assert prepared.full_url == "https://api.apollo.io/api/v1/mixed_people/api_search"
    assert dict((key.lower(), value) for key, value in prepared.header_items())["x-api-key"] == "clave-apollo-exclusivamente-sintetica"
    assert json.loads(prepared.data) == case.request.payload
    assert usage.reserved_credits == 0
    assert result.data.total_entries == 1
    assert result.observation.credits is None


@pytest.mark.parametrize("status,classification", [(401, "permission_denied"), (403, "permission_denied"), (429, "rate_limited")])
def test_structured_api_errors_preserve_literal_reason_without_secrets(apollo_case, status, classification):
    case = apollo_case
    case.response = HttpResponse(status=status, headers={"Content-Type": "application/json", "Retry-After": "60"},
                                 body=json.dumps({"error_details": {"code": "USAGE.SYNTHETIC", "message":
                                     "Límite sintético; clave-apollo-exclusivamente-sintetica; persona@example.com"}}).encode())
    usage, grant = case.reserve()
    with pytest.raises(ProviderError) as caught:
        case.client.request_json(usage.request_id, case.request, ApolloSearchResponse, authorization=grant)
    error = caught.value
    assert classify_apollo_error(error) == classification
    assert "USAGE.SYNTHETIC" in str(error)
    assert "Límite sintético" in str(error)
    assert "clave-apollo-exclusivamente-sintetica" not in str(error)
    assert "persona@example.com" not in str(error)
    assert error.retry_after_seconds == 60
    assert len(case.calls) == 1


@pytest.mark.parametrize("status, body, headers, classification, literal", [
    # Cuerpos con la forma documentada en docs.apollo.io (status-codes, rate-limits), con texto sintético.
    (403, {"error_code": "API_INACCESSIBLE", "error": "Clave sintética sin acceso a este endpoint"}, {},
     "apollo_api_inaccessible", "Clave sintética sin acceso"),
    (429, {"error_details": {"code": "USAGE.RATE_LIMIT.API_RATE_LIMIT_EXCEEDED", "message": "Límite sintético",
                             "context": {"window": {"value": "minute"}}}}, {"Retry-After": "42"},
     "rate_limited", "Reintenta después de 42 s."),
    (429, {"error_details": {"code": "USAGE.RATE_LIMIT.PLATFORM_RATE_LIMIT", "message": "Carga sintética"}}, {},
     "rate_limited", "USAGE.RATE_LIMIT.PLATFORM_RATE_LIMIT"),
    (401, None, {}, "permission_denied", "HTTP 401."),
    (422, {"error": "Parámetro sintético inválido"}, {}, "apollo_invalid_input", "Parámetro sintético inválido"),
    (400, {"error": "Solicitud sintética rechazada"}, {}, "apollo_invalid_input", "HTTP 400."),
    (404, {"error": "No existe"}, {}, "apollo_not_found", "HTTP 404."),
    (500, {"error": "Caída sintética"}, {}, "apollo_provider_error", "HTTP 500."),
])
def test_documented_apollo_failures_get_their_own_reason_and_keep_the_literal_text(
        apollo_case, status, body, headers, classification, literal):
    case = apollo_case
    raw = b"Invalid API key. Texto plano sintetico" if body is None else json.dumps(body).encode()
    case.response = HttpResponse(status=status, headers={"Content-Type": "application/json", **headers}, body=raw)
    usage, grant = case.reserve()
    with pytest.raises(ProviderError) as caught:
        case.client.request_json(usage.request_id, case.request, ApolloSearchResponse, authorization=grant)
    assert classify_apollo_error(caught.value) == classification
    assert classification in APOLLO_STOP_REASONS
    assert literal in case.db.get_usage(usage.request_id).error_message
    assert "clave-apollo-exclusivamente-sintetica" not in str(caught.value)
    assert len(case.calls) == 1


@pytest.mark.parametrize("failure, classification", [
    (TimeoutError("sintético"), "apollo_timeout"),
    (OSError("Conexión sintética caída"), "apollo_transport_error"),
])
def test_apollo_outages_get_their_own_reason_and_stay_uncertain(apollo_case, failure, classification):
    case = apollo_case
    usage, grant = case.reserve()
    client = ProviderClient(case.budget, APOLLO_OPERATIONS,
                            transport=lambda *args: (_ for _ in ()).throw(failure))
    with pytest.raises(ProviderError) as caught:
        client.request_json(usage.request_id, case.request, ApolloSearchResponse, authorization=grant)
    assert classify_apollo_error(caught.value) == classification
    assert case.db.get_usage(usage.request_id).status == "uncertain"


def test_invalid_apollo_schema_is_an_apollo_reason(apollo_case):
    case = apollo_case
    case.response = HttpResponse(status=200, headers={"Content-Type": "application/json"}, body=b'{"people": "x"}')
    usage, grant = case.reserve()
    with pytest.raises(ProviderError) as caught:
        case.client.request_json(usage.request_id, case.request, ApolloSearchResponse, authorization=grant)
    assert classify_apollo_error(caught.value) == "apollo_invalid_response"


def test_enrichment_reserves_one_credit_without_claiming_observed_consumption(apollo_case):
    case = apollo_case
    case.request = enrichment_request(PERSON_ID, "apollo-sintetico")
    case.response = HttpResponse(status=200, headers={"Content-Type": "application/json"},
                                 body=enrichment_response().model_dump_json().encode())
    usage, grant = case.reserve("1")
    result = case.client.request_json(usage.request_id, case.request, ApolloEnrichmentResponse, authorization=grant)
    assert usage.reserved_credits == 1
    assert result.observation.credits is None
    assert case.db.get_usage(usage.request_id).credits is None
