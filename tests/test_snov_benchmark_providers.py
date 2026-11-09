"""Contratos y HTTP del experimento con credenciales y personas exclusivamente sintéticas."""

from datetime import UTC, datetime, timedelta
import json
import sys
from urllib.error import URLError
from uuid import uuid4

from pydantic import ValidationError
import pytest

from experiments.snov_benchmark.contracts import (
    BenchmarkApproval, BenchmarkCompany, BenchmarkManifest, ProviderAccess, company_model, manifest_digest,
)
from experiments.snov_benchmark.providers import (
    RequestSpec, apollo_reveal_request, apollo_search_request, parse_apollo_reveal, parse_apollo_search,
    parse_snov_reveal, parse_snov_search, parse_snov_task, snov_auth_request, snov_poll_request,
    snov_reveal_request, snov_search_request,
)
from experiments.snov_benchmark.transport import BenchmarkProviderError, BenchmarkTransport, decode_response
from prospecting.contacts import ContactError
from prospecting.providers.http import HttpResponse


NOW = datetime.now(UTC) - timedelta(minutes=1)


def company():
    return BenchmarkCompany(
        company_id=uuid4(), name="Empresa sintética", domain="example.com", country="CO",
        segment="fintech_software", source_reference="Identidad exclusivamente sintética", observed_at=NOW,
        roles=["CTO"], role_families={"technology": ["CTO"]},
    )


def response(data, status=200, headers=None):
    return HttpResponse(status=status, headers={"Content-Type": "application/json", **(headers or {})},
                        body=json.dumps(data).encode())


def search_result(domain="example.com", reveal_url=None):
    return {"status": "completed", "data": {"total_pages": 1, "prospects": [{
        "first_name": "Persona", "last_name": "Sin***", "job_title": "CTO",
        "company": {"name": "Empresa sintética", "domain": domain},
        "email_and_hidden_info_reveal": reveal_url or (
            "https://api.snov.io/v2/database-search/prospects/search-emails/start/persona-sintetica"),
    }]}}


def test_manifest_identity_provenance_and_frozen_roles():
    item = company()
    model, evidence = company_model(item)
    assert model.name == item.name and model.domain == item.domain and model.entity_name is None
    assert {fact.external_reference for fact in evidence} == {item.source_reference}
    assert set(model.provenance) == {"name", "domain"}
    manifest = BenchmarkManifest(
        benchmark_id=uuid4(), origin="synthetic", created_at=NOW, source_reference="Muestra sintética",
        companies=[item], contact_days=30, config_versions={"config": "huella sintética"},
        limits={"max_requests": 20, "max_pages": 1, "max_people": 1, "max_polls": 2,
                "timeout_seconds": 5, "max_seconds": 30, "poll_interval_seconds": 1},
    )
    assert manifest_digest(manifest) == manifest_digest(BenchmarkManifest.model_validate_json(manifest.model_dump_json()))
    for update in ({"roles": ["CFO"]}, {"role_families": {"a": ["CTO"], "b": ["CTO"]}}):
        with pytest.raises(ValidationError):
            BenchmarkCompany.model_validate(item.model_dump() | update)
    values = manifest.model_dump()
    values["companies"][0]["evidence"] = [{
        "full_name": "Persona Sintética", "title": "CTO", "domain": "example.com",
        "source_url": "https://example.com/directorio-sintetico", "excerpt": "Persona Sintética, CTO",
        "observed_at": NOW + timedelta(seconds=1), "status": "current",
    }]
    with pytest.raises(ValidationError, match="congelar"):
        BenchmarkManifest.model_validate(values)


def test_access_and_approval_require_bounded_verified_source_and_one_session():
    raw = {"provider": "snov", "account_ref": "cuenta-sintetica", "access_verified": True,
           "observed_at": NOW, "source_reference": "Comprobación sintética", "funding_source": "free_credit",
           "credit_limit": "5", "cost_limit_usd": "0", "prior_credits_used": "1", "prior_cost_usd": "0",
           "usage_consolidated_verified": True, "usage_source_reference": "Ledger sintético consolidado",
           "operation_bounds": {"oauth": {"cost_usd": "0", "credits": "0", "observed_at": NOW,
                                          "source_reference": "Costo sintético"}},
           "rate_limits": {"oauth": {"per_minute": 1, "per_hour": 1, "per_day": 1}}}
    assert ProviderAccess.model_validate(raw).prior_credits_used == 1
    for change in ({"prior_credits_used": "6"}, {"rate_limits": {}}, {"credit_limit": None}):
        with pytest.raises(ValidationError):
            ProviderAccess.model_validate(raw | change)
    grant = {"provider": "snov", "operation": "oauth", "account_ref": "cuenta-sintetica",
             "max_cost_usd": "0", "max_credits": "0", "responsible": "Responsable sintético",
             "source_reference": "Permiso sintético", "authorized_at": NOW}
    approval = {"benchmark_id": uuid4(), "manifest_sha256": "0" * 64, "session_id": uuid4(),
                "responsible": grant["responsible"], "approved_at": NOW, "approvals": [grant]}
    assert BenchmarkApproval.model_validate(approval).approved_at == NOW
    for change in ({"approvals": [grant, grant]}, {"approved_at": NOW - timedelta(seconds=1)},
                   {"responsible": "Otra persona sintética"}):
        with pytest.raises(ValidationError):
            BenchmarkApproval.model_validate(approval | change)


def test_snov_filters_tasks_and_parsers_preserve_unknown_dates():
    item = company()
    request = snov_search_request(item)
    assert request.payload["filters"]["company"]["name"]["include"] == [item.name]
    assert request.payload["filters"]["prospect"]["job_titles"]["include"] == ["CTO"]
    assert parse_snov_task({"meta": {"task_hash": "tarea-sintetica"}}) == "tarea-sintetica"
    assert parse_snov_search({"status": "in_progress", "data": []}, item, NOW).status == "in_progress"
    result = parse_snov_search(search_result(domain="another.example"), item, NOW)
    person = result.candidates[0]
    assert person.domain == "another.example" and person.enriched is False
    assert snov_reveal_request(person.source_reference).path.endswith(person.id)
    revealed = parse_snov_reveal({"status": "completed", "data": {
        "first_name": "Persona", "last_name": "Sintética", "searching_date": "2026-01-01 10:00:00",
        "emails": [{"email": "persona-sintetica@another.example", "smtp_status": "valid"}],
    }}, person, NOW).person
    assert revealed.enriched and revealed.email_status == "valid" and revealed.email_verified_at is None
    assert parse_snov_reveal({"status": "in_progress", "data": []}, person, NOW).person is None
    no_email = parse_snov_reveal({"status": "completed", "data": {}}, person, NOW).person
    assert no_email.email is None and no_email.email_status == "missing"
    with pytest.raises(ValueError, match="otra identidad"):
        parse_snov_reveal({"status": "completed", "data": {"first_name": "Otra persona sintética"}}, person, NOW)


@pytest.mark.parametrize("url", [
    "https://evil.example/v2/database-search/prospects/search-emails/start/token",
    "https://api.snov.io/v2/database-search/prospects/search-emails/start/../token",
    "https://api.snov.io/v2/database-search/prospects/search-emails/start/token?next=evil",
])
def test_snov_never_follows_external_or_malformed_provider_urls(url):
    with pytest.raises(ValueError):
        parse_snov_search(search_result(reveal_url=url), company(), NOW)
    with pytest.raises(ValueError):
        snov_reveal_request(url)
    with pytest.raises(ValueError):
        snov_poll_request("../token")


def test_apollo_reuses_current_identity_guards_and_disables_optional_enrichment():
    item = company()
    people = parse_apollo_search({"total_entries": 1, "people": [{
        "id": "persona-sintetica", "first_name": "Persona", "last_name_obfuscated": "Sin***",
        "title": "CTO", "organization": {"name": item.name, "primary_domain": item.domain},
    }]}, item, NOW)
    person = people[0]
    request = apollo_reveal_request(person)
    assert request.payload["run_waterfall_email"] is False
    assert request.payload["run_waterfall_phone"] is False
    assert apollo_search_request(item).payload["person_titles"] == ["CTO"]
    raw = {"person": {"id": person.id, "first_name": "Persona", "last_name": "Sintética", "title": "CTO",
                      "match_confidence": "high", "email": "persona-sintetica@example.com", "email_status": "verified",
                      "organization_id": "empresa-sintetica", "organization": {
                          "id": "empresa-sintetica", "name": item.name, "primary_domain": item.domain},
                      "employment_history": [{"current": True, "organization_id": "empresa-sintetica"}]}}
    enriched = parse_apollo_reveal(raw, item, person, NOW)
    assert enriched.enriched and enriched.email_status == "valid" and enriched.email_verified_at is None
    raw["person"]["organization"]["primary_domain"] = "another.example"
    with pytest.raises(ContactError):
        parse_apollo_reveal(raw, item, person, NOW)


def test_oauth_is_explicit_countable_and_secret_never_leaves_transport(monkeypatch):
    monkeypatch.setenv("SNOV_CLIENT_ID", "cliente-exclusivamente-sintetico")
    monkeypatch.setenv("SNOV_CLIENT_SECRET", "secreto-exclusivamente-sintetico")
    calls = []
    replies = [response({"access_token": "token-exclusivamente-sintetico", "token_type": "Bearer", "expires_in": 3600}),
               response({"meta": {"task_hash": "tarea-sintetica"}})]

    def send(prepared, timeout, max_bytes):
        calls.append(prepared)
        return replies.pop(0)

    transport = BenchmarkTransport(send)
    with pytest.raises(BenchmarkProviderError, match="OAuth"):
        transport.send(snov_search_request(company()), timeout_seconds=3)
    assert not calls
    safe = transport.send(snov_auth_request(), timeout_seconds=3)
    assert transport.snov_authenticated and b"token-exclusivamente" not in safe.body
    assert b"client_secret=" in calls[0].data and calls[0].get_header("Authorization") is None
    transport.send(snov_search_request(company()), timeout_seconds=3)
    assert calls[1].get_header("Authorization") == "Bearer token-exclusivamente-sintetico"
    assert b"client_secret" not in calls[1].data
    transport._snov_expires_at = 0
    assert not transport.snov_authenticated
    with pytest.raises(BenchmarkProviderError):
        transport.send(snov_search_request(company()), timeout_seconds=3)
    assert len(calls) == 2


def test_transport_denies_mutations_and_persistable_secrets_before_network():
    calls = []
    transport = BenchmarkTransport(lambda *args: calls.append(args))
    with pytest.raises(BenchmarkProviderError) as error:
        transport.send(RequestSpec(provider="snov", operation="send", method="POST", path="/v1/add-prospect-to-list"),
                       timeout_seconds=1)
    assert error.value.code == "operation_forbidden" and not calls
    with pytest.raises(ValidationError):
        RequestSpec(provider="snov", operation="oauth", method="POST", path="/v1/oauth/access_token",
                    payload={"client_secret": "secreto-sintetico"})


def test_errors_are_not_retried_and_redact_credentials_and_contacts(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "clave-apollo-exclusivamente-sintetica")
    calls = []

    def failed(*args):
        calls.append(args)
        return response({"message": "Límite para clave-apollo-exclusivamente-sintetica y persona-sintetica@example.com"},
                        status=429, headers={"Retry-After": "7"})

    transport = BenchmarkTransport(failed)
    with pytest.raises(BenchmarkProviderError) as error:
        transport.send(apollo_search_request(company()), timeout_seconds=1)
    assert error.value.http_status == 429 and error.value.retry_after == 7
    assert "clave-apollo" not in error.value.message and "@example.com" not in error.value.message
    assert len(calls) == 1
    with pytest.raises(BenchmarkProviderError, match="API_INACCESSIBLE"):
        decode_response(response({"error_details": {"code": "API_INACCESSIBLE"}}, status=403))
    for raw in (response({"status": "not_enough_credits"}), HttpResponse(status=200, headers={}, body=b"{}"),
                HttpResponse(status=200, headers={"Content-Type": "application/json"}, body=b"{bad")):
        with pytest.raises(BenchmarkProviderError):
            decode_response(raw)


def test_logical_error_redacts_memory_only_oauth_token(monkeypatch):
    monkeypatch.setenv("SNOV_CLIENT_ID", "cliente-sintetico")
    monkeypatch.setenv("SNOV_CLIENT_SECRET", "secreto-sintetico")
    replies = [response({"access_token": "token-solo-memoria", "token_type": "Bearer", "expires_in": 3600}),
               response({"success": False, "message": "Acceso rechazado para token-solo-memoria"})]
    transport = BenchmarkTransport(lambda *args: replies.pop(0))
    transport.send(snov_auth_request(), timeout_seconds=1)
    with pytest.raises(BenchmarkProviderError) as error:
        transport.send(snov_search_request(company()), timeout_seconds=1)
    assert "token-solo-memoria" not in error.value.message
    assert error.value.code == "provider_error"


def test_provider_decoder_recursion_error_becomes_safe_invalid_response(monkeypatch):
    depth = sys.getrecursionlimit() + 100
    raw = HttpResponse(status=200, headers={"Content-Type": "application/json"},
                       body=b'{"nested":' * depth + b"0" + b"}" * depth)

    def reject_deep_json(value, **kwargs):
        assert value == raw.body
        raise RecursionError("Profundidad sintética del proveedor.")

    # El límite del decoder C varía por versión de Python; comprobamos la excepción concreta.
    monkeypatch.setattr("experiments.snov_benchmark.transport.json.loads", reject_deep_json)
    with pytest.raises(BenchmarkProviderError) as error:
        decode_response(raw)
    assert error.value.code == "invalid_response"


def test_timeout_redirect_and_oversize_fail_closed(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "clave-apollo-exclusivamente-sintetica")
    request = apollo_search_request(company())
    for reply in (response({}, status=302), response({"message": "x" * 100})):
        with pytest.raises(BenchmarkProviderError):
            BenchmarkTransport(lambda *args: reply).send(request, timeout_seconds=1, max_bytes=50)
    for failure in (TimeoutError(), URLError("fallo sintético")):
        def fail(*args):
            raise failure
        with pytest.raises(BenchmarkProviderError) as error:
            BenchmarkTransport(fail).send(request, timeout_seconds=1)
        assert error.value.code in {"timeout", "transport_error"}
