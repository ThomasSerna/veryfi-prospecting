"""Cliente HTTP y presupuesto con respuestas y credenciales solo sintéticas."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import format_datetime
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import Request
from uuid import uuid4

import pytest
from pydantic import ValidationError

from prospecting.budget import (
    AccountAllowance, Budget, BudgetError, Confirmation, SpendingAuthorization,
)
from prospecting.db import Database
from prospecting.models import Contract, Usage, UsageStatus, utc_now
from prospecting.providers import (
    HttpResponse, OperationSpec, ProviderClient, ProviderError, ProviderRequest,
)
import prospecting.providers as providers


SYNTHETIC_KEY = "clave-exclusivamente-sintetica-para-pruebas"
OBSERVED_AT = datetime(2026, 10, 11, tzinfo=UTC)


class SyntheticResponse(Contract):
    matches: list[str]


class SyntheticPendingMeta(Contract):
    params: dict[str, str]
    message: str


class SyntheticPendingResponse(Contract):
    data: dict[str, str]
    meta: SyntheticPendingMeta


@pytest.fixture
def provider_case(database, config, make_campaign, monkeypatch, tmp_path):
    """Una cuenta ficticia, sin proveedores activos ni conexiones externas."""
    campaign = make_campaign()
    database.save_campaign(campaign)
    allowance = AccountAllowance(
        provider="tavily", account_ref="cuenta-sintetica", funding_source="prepaid",
        credit_limit="10", cost_limit_usd="1",
        source_reference="Saldo sintético para pruebas", observed_at=OBSERVED_AT,
    )
    budget = Budget(database, config.defaults.budget, [allowance])
    grant = SpendingAuthorization(
        provider="tavily", operation="synthetic_lookup", account_ref="cuenta-sintetica",
        max_cost_usd="1", max_credits="10", responsible="Responsable sintético",
        source_reference="Autorización sintética para transporte sin red",
        authorized_at=utc_now(),
    )
    budget.authorize(grant)
    spec = OperationSpec(
        provider="tavily", operation="synthetic_lookup",
        endpoint="https://example.com/api/synthetic", api_key_env="TAVILY_API_KEY",
    )
    request = ProviderRequest(
        provider="tavily", operation="synthetic_lookup", account_ref="cuenta-sintetica",
        payload={"query": "Empresa completamente sintética"},
    )
    case = SimpleNamespace(
        db=database, db_path=tmp_path / "synthetic.sqlite3",
        campaign=campaign, allowance=allowance, grant=grant,
        budget=budget, spec=spec, request=request, calls=[], failure=None,
        response=HttpResponse(
            status=200, headers={"Content-Type": "application/json"},
            body=b'{"matches": ["Resultado exclusivamente sintetico"]}',
        ),
    )

    def transport(prepared, timeout_seconds, max_bytes):
        assert not database._connection.in_transaction
        case.calls.append((prepared, timeout_seconds, max_bytes))
        if case.failure is not None:
            raise case.failure
        return case.response

    case.transport = transport
    case.client = ProviderClient(budget, [spec], transport=transport)

    def reserve(request=None, **overrides):
        request = request or case.request
        usage = Usage(
            campaign_id=campaign.id, provider=request.provider,
            operation=request.operation, account_ref=request.account_ref,
            request_fingerprint=case.client.fingerprint(request),
            reserved_cost_usd="0.10", reserved_credits="1",
            funding_source="prepaid", status=UsageStatus.RESERVED,
        )
        usage = Usage.model_validate(usage.model_dump() | overrides)
        return budget.reserve(usage, authorization=grant)

    case.reserve = reserve
    monkeypatch.setenv("TAVILY_API_KEY", SYNTHETIC_KEY)
    return case


@pytest.fixture
def hunter_case(provider_case, config, monkeypatch):
    """Verifier ficticio: reutiliza el transporte sintético, sin consultar Hunter."""
    case = provider_case
    case.allowance = case.allowance.model_copy(update={"provider": "hunter"})
    case.budget = Budget(case.db, config.defaults.budget, [case.allowance])
    case.grant = case.budget.authorize(case.grant.model_copy(update={
        "provider": "hunter", "operation": "email_verifier", "authorized_at": utc_now(),
    }))
    case.spec = OperationSpec(
        provider="hunter", operation="email_verifier", method="GET",
        endpoint="https://api.hunter.io/v2/email-verifier", api_key_env="HUNTER_API_KEY",
        timeout_seconds=25.0,
    )
    case.request = ProviderRequest(
        provider="hunter", operation="email_verifier", account_ref=case.grant.account_ref,
        params={"email": "persona-sintetica@example.com"},
    )
    case.client = ProviderClient(case.budget, [case.spec], transport=case.transport)

    def reserve():
        return case.budget.reserve(Usage(
            campaign_id=case.campaign.id, provider="hunter", operation="email_verifier",
            account_ref=case.request.account_ref,
            request_fingerprint=case.client.fingerprint(case.request),
            reserved_cost_usd="0.10", reserved_credits="0.5",
            funding_source="prepaid", status=UsageStatus.RESERVED,
        ), case.grant)

    case.reserve = reserve
    monkeypatch.setenv("HUNTER_API_KEY", SYNTHETIC_KEY)
    return case


def call(case, usage, **kwargs):
    return case.client.request_json(
        usage.request_id, case.request, SyntheticResponse,
        authorization=case.grant, **kwargs,
    )


def test_success_validates_response_and_leaves_cost_pending(provider_case):
    case = provider_case
    usage = case.reserve()
    result = call(case, usage)
    assert result.request_id == usage.request_id
    assert isinstance(result.data, SyntheticResponse)
    assert result.data.matches == ["Resultado exclusivamente sintetico"]
    assert result.observation.outcome == "succeeded"
    assert result.http_status == 200
    previous = result.model_dump()
    previous.pop("http_status")
    assert type(result).model_validate(previous).http_status == 200
    saved = case.db.get_usage(usage.request_id)
    assert saved.outcome == "succeeded"
    assert saved.final_cost_usd is None
    assert saved.credits is None
    assert saved.reserved_cost_usd == Decimal("0.10")
    assert saved.reserved_credits == Decimal("1")


def test_missing_reservation_cannot_send(provider_case):
    case = provider_case
    with pytest.raises((BudgetError, ProviderError)):
        case.client.request_json(
            uuid4(), case.request, SyntheticResponse, authorization=case.grant,
        )
    assert case.calls == []


def test_missing_authorization_cannot_send(provider_case):
    case = provider_case
    usage = case.reserve()
    with pytest.raises(BudgetError):
        case.client.request_json(usage.request_id, case.request, SyntheticResponse)
    assert case.calls == []
    assert case.db.get_usage(usage.request_id).status == UsageStatus.RESERVED


def test_no_balance_cannot_reach_transport(provider_case, config):
    case = provider_case
    empty = case.allowance.model_copy(update={
        "cost_limit_usd": Decimal("0"), "credit_limit": Decimal("0"),
    })
    budget = Budget(case.db, config.defaults.budget, [empty])
    active = budget.authorize(case.grant.model_copy(update={"authorized_at": utc_now()}))
    client = ProviderClient(budget, [case.spec], transport=case.transport)
    usage = Usage(
        campaign_id=case.campaign.id, provider=case.request.provider,
        operation=case.request.operation, account_ref=case.request.account_ref,
        request_fingerprint=client.fingerprint(case.request),
        reserved_cost_usd="0.10", reserved_credits="1",
        funding_source="prepaid", status=UsageStatus.RESERVED,
    )
    with pytest.raises(BudgetError) as error:
        budget.reserve(usage, authorization=active)
    assert error.value.code == "budget_exceeded"
    assert case.calls == []
    assert case.db.get_usage(usage.request_id) is None


@pytest.mark.parametrize("key", [None, " ", "synthetic\r\nInjected: true", "clave-sintética-🌎"])
def test_missing_or_unsafe_key_cannot_send(provider_case, monkeypatch, key):
    case = provider_case
    usage = case.reserve()
    if key is None:
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    else:
        monkeypatch.setenv("TAVILY_API_KEY", key)
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    assert error.value.kind == "local"
    assert case.calls == []
    assert case.db.get_usage(usage.request_id).status == UsageStatus.RESERVED


def test_transport_receives_auth_json_bounds_and_remaining_timeout(provider_case):
    case = provider_case
    usage = case.reserve()
    call(case, usage, remaining_seconds=2.5)
    prepared, timeout, max_bytes = case.calls[0]
    assert isinstance(prepared, Request)
    assert prepared.get_method() == "POST"
    assert prepared.full_url == "https://example.com/api/synthetic"
    headers = {key.lower(): value for key, value in prepared.header_items()}
    assert headers["authorization"] == f"Bearer {SYNTHETIC_KEY}"
    assert SYNTHETIC_KEY not in prepared.full_url
    assert SYNTHETIC_KEY not in prepared.data.decode("utf-8")
    assert json.loads(prepared.data) == case.request.payload
    assert 0 < timeout <= 2.5
    assert max_bytes == 1024 * 1024


@pytest.mark.parametrize("remaining", [0, -1, float("nan"), float("inf")])
def test_invalid_remaining_time_cannot_send(provider_case, remaining):
    case = provider_case
    usage = case.reserve()
    with pytest.raises(ProviderError) as error:
        call(case, usage, remaining_seconds=remaining)
    assert error.value.kind == "local"
    assert case.calls == []


def test_default_timeout_does_not_grow_with_remaining_time(provider_case):
    case = provider_case
    usage = case.reserve()
    call(case, usage, remaining_seconds=100)
    assert case.calls[0][1] == 10


@pytest.mark.parametrize("remaining, expected", [(None, 25.0), (100.0, 25.0), (2.5, 2.5)])
def test_operation_timeout_respects_the_remaining_deadline(hunter_case, remaining, expected):
    case = hunter_case
    usage = case.reserve()
    call(case, usage, remaining_seconds=remaining)
    prepared, timeout, _ = case.calls[0]
    assert 0 < timeout <= expected
    if remaining is None or remaining == 100.0:
        assert timeout == expected
    assert prepared.get_method() == "GET"
    assert SYNTHETIC_KEY not in prepared.full_url
    assert prepared.get_header("Authorization") == f"Bearer {SYNTHETIC_KEY}"


@pytest.mark.parametrize("timeout", [0.0, -1.0, True, "25", float("nan"), float("inf")])
def test_operation_timeout_rejects_unbounded_or_invalid_values(provider_case, timeout):
    with pytest.raises(ValidationError):
        OperationSpec.model_validate(provider_case.spec.model_dump() | {"timeout_seconds": timeout})


def test_hunter_pending_verification_keeps_reservation_across_reopen(hunter_case):
    case = hunter_case
    usage = case.reserve()
    case.response = HttpResponse(
        status=202, headers={"Content-Type": "application/json"},
        body=json.dumps({"data": {}, "meta": {
            "params": case.request.params, "message": "Verificación sintética pendiente",
        }}).encode("utf-8"),
    )
    result = case.client.request_json(
        usage.request_id, case.request, SyntheticPendingResponse, authorization=case.grant,
    )
    assert result.http_status == 202
    assert result.observation.outcome == "unknown"
    assert result.data.meta.params == case.request.params
    with Database(case.db_path) as reopened:
        saved = reopened.get_usage(usage.request_id)
        assert saved.status == UsageStatus.UNCERTAIN
        assert saved.outcome == "unknown"
        assert saved.reserved_credits == Decimal("0.5")
        assert saved.reserved_cost_usd == Decimal("0.10")
        assert saved.credits is None and saved.final_cost_usd is None
    with pytest.raises(BudgetError):
        case.client.request_json(
            usage.request_id, case.request, SyntheticPendingResponse, authorization=case.grant,
        )
    assert len(case.calls) == 1


@pytest.mark.parametrize("body, content_type, kind", [
    (b"{invalido", "application/json", "json"),
    (b'{"data": {}, "meta": {}}', "application/json", "schema"),
    (b"respuesta sintetica", "text/plain", "content_type"),
    (b"x" * (1024 * 1024 + 1), "application/json", "response_limit"),
], ids=["invalid-json", "invalid-schema", "non-json", "oversize"])
def test_malformed_hunter_pending_response_remains_uncertain(
    hunter_case, body, content_type, kind
):
    case = hunter_case
    usage = case.reserve()
    case.response = HttpResponse(
        status=202, headers={"Content-Type": content_type}, body=body,
    )
    with pytest.raises(ProviderError) as error:
        case.client.request_json(
            usage.request_id, case.request, SyntheticPendingResponse, authorization=case.grant,
        )
    assert error.value.kind == kind
    saved = case.db.get_usage(usage.request_id)
    assert saved.status == UsageStatus.UNCERTAIN and saved.outcome == "unknown"
    assert saved.reserved_credits == Decimal("0.5") and saved.credits is None
    assert saved.error_message == error.value.message


def test_hunter_smtp_failure_is_an_error_despite_2xx(hunter_case):
    case = hunter_case
    usage = case.reserve()
    case.response = HttpResponse(
        status=222, headers={"Content-Type": "application/json"},
        body=b'{"errors": [{"id": "smtp_error", "code": 222, "details": "Fallo SMTP sintetico"}]}',
    )
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    assert error.value.kind == "http" and error.value.http_status == 222
    assert error.value.message == "HTTP 222. smtp_error 222 Fallo SMTP sintetico"
    saved = case.db.get_usage(usage.request_id)
    assert saved.status == UsageStatus.FAILED and saved.outcome == "failed"
    assert saved.reserved_credits == Decimal("0.5") and saved.credits is None
    assert len(case.calls) == 1


def test_hunter_error_array_preserves_literal_without_credentials_or_personal_data(hunter_case):
    case = hunter_case
    usage = case.reserve()
    case.response = HttpResponse(
        status=451, headers={"Content-Type": "application/json"},
        body=json.dumps({"errors": [{
            "id": "claimed_email", "code": 451,
            "details": f"Fallo sintético literal {case.request.params['email']} {SYNTHETIC_KEY} "
                       "+573001234567 https://example.com/synthetic",
        }]}).encode("utf-8"),
    )
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    saved = case.db.get_usage(usage.request_id)
    assert saved.error_message == error.value.message
    assert "claimed_email 451 Fallo sintético literal" in saved.error_message
    assert SYNTHETIC_KEY not in saved.error_message
    assert case.request.params["email"] not in saved.error_message
    assert "+573001234567" not in saved.error_message
    assert "https://example.com/synthetic" not in saved.error_message


@pytest.mark.parametrize("ticks", [[0.0, 3.0], [0.0, 1.0, 3.0]])
def test_expired_deadline_after_claim_cannot_invoke_transport(provider_case, monkeypatch, ticks):
    case = provider_case
    usage = case.reserve()
    ticks = iter(ticks)
    monkeypatch.setattr(providers.time, "monotonic", lambda: next(ticks))
    with pytest.raises(ProviderError) as error:
        call(case, usage, remaining_seconds=2.5)
    assert error.value.kind == "local"
    assert error.value.no_send is True
    assert case.calls == []
    saved = case.db.get_usage(usage.request_id)
    assert saved.status == UsageStatus.FAILED
    assert saved.outcome == "failed"
    assert saved.final_cost_usd is None
    assert saved.reserved_cost_usd == Decimal("0.10")
    assert saved.reserved_credits == Decimal("1")
    assert saved.credits == 0
    assert saved.estimated_cost_usd == 0
    assert case.budget.snapshot(case.campaign.id).campaign.pending == Decimal("0.10")
    done = case.budget.reconcile(usage.request_id, Confirmation(
        outcome="failed", final_cost_usd="0", credits="0", outlay_usd="0",
        no_send=True, source_reference="Plazo sintético vencido sin invocar transporte",
        observed_at=utc_now(),
    ))
    assert done.status == UsageStatus.RECONCILED
    assert done.error_message == saved.error_message
    assert done.reserved_cost_usd == Decimal("0.10")
    assert done.reserved_credits == Decimal("1")
    assert case.budget.snapshot(case.campaign.id).campaign.exposure == 0
    assert case.budget.snapshot(case.campaign.id).accounts[0].credits.exposure == 0
    with Database(case.db_path) as reopened:
        assert reopened.get_usage(usage.request_id).status == UsageStatus.RECONCILED
        assert reopened.get_usage(usage.request_id).final_cost_usd == 0


def test_duplicate_request_id_never_sends_twice(provider_case):
    case = provider_case
    usage = case.reserve()
    call(case, usage)
    with pytest.raises((BudgetError, ProviderError)):
        call(case, usage)
    assert len(case.calls) == 1


def test_changed_request_cannot_spend_original_reservation(provider_case):
    case = provider_case
    usage = case.reserve()
    changed = case.request.model_copy(update={"payload": {"query": "Otra entrada sintética"}})
    with pytest.raises((BudgetError, ProviderError)):
        case.client.request_json(
            usage.request_id, changed, SyntheticResponse, authorization=case.grant,
        )
    assert case.calls == []
    assert case.db.get_usage(usage.request_id).status == UsageStatus.RESERVED


@pytest.mark.parametrize("failure", [
    TimeoutError("Timeout sintético"), URLError(TimeoutError("Timeout sintético")),
    URLError("Fallo sintético"), OSError("Fallo de transporte sintético"), OSError(),
])
def test_uncertain_send_survives_reopen_and_is_not_retried(provider_case, failure):
    case = provider_case
    usage = case.reserve()
    case.failure = failure
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    assert error.value.kind in {"timeout", "transport"}
    assert error.value.no_send is False
    assert error.value.retryable is False
    assert len(case.calls) == 1
    with pytest.raises(BudgetError) as denied:
        case.budget.reconcile(usage.request_id, Confirmation(
            outcome="failed", final_cost_usd="0", credits="0", outlay_usd="0",
            no_send=True, source_reference="No envío sintético sin prueba",
            observed_at=utc_now(),
        ))
    assert denied.value.code == "invalid_no_send"
    with Database(case.db_path) as reopened:
        saved = reopened.get_usage(usage.request_id)
        assert saved.status == UsageStatus.UNCERTAIN
        assert saved.outcome == "unknown"
        assert saved.final_cost_usd is None
        assert saved.reserved_cost_usd == Decimal("0.10")
        assert saved.reserved_credits == Decimal("1")
        assert saved.error_message
    with pytest.raises((BudgetError, ProviderError)):
        call(case, usage)
    assert len(case.calls) == 1


@pytest.mark.parametrize("status", [403, 429, 500])
def test_http_error_keeps_reservation_without_generic_permission_mapping(provider_case, status):
    case = provider_case
    usage = case.reserve()
    case.response = HttpResponse(
        status=status, headers={"Content-Type": "application/json"},
        body=b'{"message": "Fallo exclusivamente sintetico"}',
    )
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    assert error.value.kind == "http"
    assert error.value.http_status == status
    assert error.value.retryable is False
    assert error.value.no_send is False
    with pytest.raises(BudgetError) as denied:
        case.budget.reconcile(usage.request_id, Confirmation(
            outcome="failed", final_cost_usd="0", credits="0", outlay_usd="0",
            no_send=True, source_reference="No envío sintético sin prueba", observed_at=utc_now(),
        ))
    assert denied.value.code == "invalid_no_send"
    saved = case.db.get_usage(usage.request_id)
    assert saved.outcome == "failed"
    assert saved.final_cost_usd is None
    assert saved.reserved_cost_usd == Decimal("0.10")
    assert saved.reserved_credits == Decimal("1")
    assert len(case.calls) == 1


@pytest.mark.parametrize("body, kind", [
    (b"{invalido", "json"),
    (b'{"matches": "estructura sintetica incorrecta"}', "schema"),
])
def test_invalid_response_is_persisted_without_releasing_cost(provider_case, body, kind):
    case = provider_case
    usage = case.reserve()
    case.response = HttpResponse(
        status=200, headers={"Content-Type": "application/json"}, body=body,
    )
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    assert error.value.kind == kind
    saved = case.db.get_usage(usage.request_id)
    assert saved.outcome == "failed"
    assert saved.final_cost_usd is None
    assert saved.reserved_cost_usd == Decimal("0.10")
    assert saved.error_message


@pytest.mark.parametrize("headers", [{}, {"Content-Type": "text/html"}])
def test_non_json_content_is_rejected(provider_case, headers):
    case = provider_case
    usage = case.reserve()
    case.response = HttpResponse(status=200, headers=headers, body=b'{"matches": []}')
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    assert error.value.kind == "content_type"
    assert case.db.get_usage(usage.request_id).reserved_cost_usd == Decimal("0.10")


def test_case_insensitive_json_content_type_accepts_empty_results(provider_case):
    case = provider_case
    usage = case.reserve()
    case.response = HttpResponse(
        status=200, headers={"content-type": "application/problem+json; charset=utf-8"},
        body=b'{"matches": []}',
    )
    assert call(case, usage).data.matches == []
    assert case.db.get_usage(usage.request_id).outcome == "succeeded"


def test_injected_transport_cannot_bypass_response_size_limit(provider_case):
    case = provider_case
    usage = case.reserve()
    case.response = HttpResponse(
        status=200, headers={"Content-Type": "application/json"},
        body=b"x" * (1024 * 1024 + 1),
    )
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    assert error.value.kind == "response_limit"
    assert case.db.get_usage(usage.request_id).reserved_cost_usd == Decimal("0.10")


def test_redirect_is_not_followed_and_cannot_receive_credentials(provider_case):
    case = provider_case
    usage = case.reserve()
    case.response = HttpResponse(
        status=302, headers={"Location": "http://127.0.0.1/secreto"}, body=b"",
    )
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    assert error.value.kind == "redirect"
    assert len(case.calls) == 1


@pytest.mark.parametrize("retry_after, expected", [("3", 3), ("no-fecha", None), ("-1", None)])
def test_retry_after_numeric_is_metadata_and_never_causes_retry(provider_case, retry_after, expected):
    case = provider_case
    usage = case.reserve()
    case.response = HttpResponse(
        status=429, headers={"Retry-After": retry_after, "Content-Type": "application/json"},
        body=b'{"message": "Limite sintetico"}',
    )
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    assert error.value.retry_after_seconds == expected
    assert len(case.calls) == 1


def test_retry_after_http_date_is_parsed_without_sleeping(provider_case):
    case = provider_case
    usage = case.reserve()
    retry_date = format_datetime(utc_now() + timedelta(seconds=30), usegmt=True)
    case.response = HttpResponse(
        status=429, headers={"Retry-After": retry_date, "Content-Type": "application/json"},
        body=b'{"message": "Limite sintetico"}',
    )
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    assert 0 < error.value.retry_after_seconds <= 30
    assert len(case.calls) == 1


def test_error_body_does_not_leak_key_or_personal_payload(provider_case):
    case = provider_case
    usage = case.reserve()
    case.response = HttpResponse(
        status=403, headers={"Content-Type": "application/json"},
        body=json.dumps({
            "message": f"Fallo sintético literal; clave {SYNTHETIC_KEY}",
            "contact": "persona-exclusivamente-sintetica@example.com",
        }).encode("utf-8"),
    )
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    saved = case.db.get_usage(usage.request_id)
    visible = str(error.value) + saved.error_message
    assert SYNTHETIC_KEY not in visible
    assert "persona-exclusivamente-sintetica@example.com" not in visible
    assert "Fallo sintético literal" in visible


@pytest.mark.parametrize("detail", [
    {"error": "Límite sintético del plan; clave " + SYNTHETIC_KEY},
    {"message": "Límite sintético del plan; clave " + SYNTHETIC_KEY},
    "Límite sintético del plan; clave " + SYNTHETIC_KEY,
])
def test_nested_detail_error_is_kept_literal_without_secrets(provider_case, detail):
    case = provider_case
    usage = case.reserve()
    case.response = HttpResponse(
        status=432, headers={"Content-Type": "application/json"},
        body=json.dumps({"detail": detail}).encode("utf-8"),
    )
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    saved = case.db.get_usage(usage.request_id)
    assert error.value.message.startswith("HTTP 432. Límite sintético del plan")
    assert saved.error_message == error.value.message
    assert SYNTHETIC_KEY not in saved.error_message


def test_schema_error_does_not_persist_sensitive_input_values(provider_case):
    case = provider_case
    usage = case.reserve()
    case.response = HttpResponse(
        status=200, headers={"Content-Type": "application/json"},
        body=json.dumps({"matches": {"secret": SYNTHETIC_KEY}}).encode("utf-8"),
    )
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    assert error.value.kind == "schema"
    assert SYNTHETIC_KEY not in str(error.value)
    assert SYNTHETIC_KEY not in case.db.get_usage(usage.request_id).error_message


def test_fingerprint_canonicalizes_input_and_excludes_environment_key(provider_case, monkeypatch):
    case = provider_case
    left = case.request.model_copy(update={
        "params": {"page": 1, "limit": 2},
        "payload": {"query": "Empresa sintética", "options": {"a": 1, "b": 2}},
    })
    right = left.model_copy(update={
        "params": {"limit": 2, "page": 1},
        "payload": {"options": {"b": 2, "a": 1}, "query": "Empresa sintética"},
    })
    fingerprint = case.client.fingerprint(left)
    assert len(fingerprint) == 64
    assert case.client.fingerprint(right) == fingerprint
    monkeypatch.setenv("TAVILY_API_KEY", "otra-clave-exclusivamente-sintetica")
    assert case.client.fingerprint(left) == fingerprint
    changed = left.model_copy(update={"account_ref": "otra-cuenta-sintetica"})
    assert case.client.fingerprint(changed) != fingerprint


def test_fingerprint_uses_effective_query_to_avoid_duplicate_charge(provider_case):
    case = provider_case
    omitted = case.request.model_copy(update={"params": {"page": None, "ignored": []}})
    assert case.client.fingerprint(omitted) == case.client.fingerprint(case.request)
    boolean = case.request.model_copy(update={"params": {"enabled": True}})
    same_query = case.request.model_copy(update={"params": {"enabled": "True"}})
    assert case.client.fingerprint(boolean) == case.client.fingerprint(same_query)


@pytest.mark.parametrize("status, kinds", [(200, {"json", "schema"}), (500, {"http"})])
def test_deeply_nested_external_json_preserves_error_and_reserved_cost(provider_case, status, kinds):
    case = provider_case
    usage = case.reserve()
    body = ('{"matches":' + "[" * 1100 + '"sintético"' + "]" * 1100 + "}").encode("utf-8")
    case.response = HttpResponse(
        status=status, headers={"Content-Type": "application/json"}, body=body,
    )
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    assert error.value.kind in kinds
    saved = case.db.get_usage(usage.request_id)
    assert saved.outcome == "failed"
    assert saved.final_cost_usd is None
    assert saved.reserved_cost_usd == Decimal("0.10")
    assert saved.error_message
    assert len(case.calls) == 1


@pytest.mark.parametrize("field, value", [
    ("params", {"api_key": SYNTHETIC_KEY}),
    ("payload", {"api_key": SYNTHETIC_KEY}),
    ("payload", {"invalid_json": object()}),
])
def test_unsafe_request_input_never_reaches_transport(provider_case, field, value):
    case = provider_case
    usage = case.reserve()
    changed = case.request.model_copy(update={field: value})
    with pytest.raises(ProviderError) as error:
        case.client.request_json(
            usage.request_id, changed, SyntheticResponse, authorization=case.grant,
        )
    assert error.value.kind == "local"
    assert case.calls == []


@pytest.mark.parametrize("endpoint", [
    "http://example.com/api", "https://user:password@example.com/api",
    "https://example.com/api?api_key=synthetic", "https://example.com/api#fragment",
    "https://localhost/api", "https://127.0.0.1/api", "https://10.0.0.1/api",
    "https://169.254.169.254/api", "https://[::1]/api",
])
def test_operation_descriptor_rejects_unsafe_destination(endpoint):
    with pytest.raises(ValidationError):
        OperationSpec(
            provider="tavily", operation="synthetic_lookup",
            endpoint=endpoint, api_key_env="TAVILY_API_KEY",
        )


@pytest.mark.parametrize("headers", [
    {"Authorization": SYNTHETIC_KEY}, {"x-api-key": SYNTHETIC_KEY},
    {"X-Synthetic": "unsafe\r\nInjected: true"},
    {"X-Synthetic": "unsafe\x00value"}, {"X-Synthetic": "unsafe\x7fvalue"},
])
def test_operation_descriptor_rejects_extra_credentials_or_header_injection(headers):
    with pytest.raises(ValidationError):
        OperationSpec(
            provider="tavily", operation="synthetic_lookup",
            endpoint="https://example.com/api", api_key_env="TAVILY_API_KEY",
            headers=headers,
        )


def test_urllib_transport_disables_proxy_redirects_and_bounds_reading(monkeypatch):
    captured = {}
    response = BytesIO(b"respuesta exclusivamente sintetica")
    response.code = 200
    response.headers = {"Content-Type": "application/json"}

    def open_synthetic(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return response

    def build_synthetic(*handlers):
        captured["handlers"] = handlers
        return SimpleNamespace(open=open_synthetic)

    monkeypatch.setattr(providers, "build_opener", build_synthetic)
    request = Request("https://example.com/synthetic")
    result = providers._urllib_transport(request, 2.5, 4)
    proxy, redirects = captured["handlers"]
    assert proxy.proxies == {}
    assert redirects.redirect_request(
        request, None, 302, "Redirección sintética", {}, "http://127.0.0.1/secreto",
    ) is None
    assert captured["request"] is request
    assert captured["timeout"] == 2.5
    assert result.body == b"respu"
    assert response.closed


@pytest.mark.parametrize("invalid_response", [None, {"status": 999, "headers": {}, "body": b""}])
def test_malformed_injected_transport_keeps_uncertain_reservation(provider_case, invalid_response):
    case = provider_case
    usage = case.reserve()
    case.response = invalid_response
    with pytest.raises(ProviderError) as error:
        call(case, usage)
    assert error.value.kind == "transport"
    saved = case.db.get_usage(usage.request_id)
    assert saved.status == UsageStatus.UNCERTAIN
    assert saved.final_cost_usd is None
    assert saved.reserved_cost_usd == Decimal("0.10")
    assert len(case.calls) == 1


def test_budget_and_providers_import_without_ui_credentials_network_or_database(tmp_path):
    """Los módulos nuevos no realizan acciones externas al importarse."""
    script = """
import os
from pathlib import Path
import socket
import sqlite3
import sys

for key in ("TAVILY_API_KEY", "ANTHROPIC_API_KEY", "APOLLO_API_KEY", "HUNTER_API_KEY"):
    os.environ.pop(key, None)

def reject(*args, **kwargs):
    raise AssertionError("Importar no puede abrir red ni bases de datos.")

socket.socket.connect = reject
socket.socket.connect_ex = reject
socket.getaddrinfo = reject
socket.create_connection = reject
sqlite3.connect = reject
sys.path.insert(0, sys.argv[1])
import prospecting.budget
import prospecting.providers
assert "streamlit" not in sys.modules
assert not list(Path.cwd().iterdir())
"""
    subprocess.run(
        [sys.executable, "-c", script, str(Path(__file__).resolve().parents[1])],
        cwd=tmp_path, check=True, timeout=10,
    )
