"""Respuestas malformadas del SDK y consumo exclusivamente sintéticos, sin red."""

from decimal import Decimal
import json
from types import SimpleNamespace
from urllib.parse import quote, quote_plus

import anthropic
import httpx2
import pytest

from prospecting.budget import AccountAllowance, Budget, BudgetError, SpendingAuthorization
from prospecting.haiku import MODEL_ID
from prospecting.models import Usage, utc_now
from prospecting.providers import ClaudeClient, ProviderError


@pytest.fixture
def sdk_case(database, config, make_campaign, monkeypatch):
    campaign = make_campaign()
    database.save_campaign(campaign)
    case = SimpleNamespace(db=database, requests=[], status=200, reply={
        "id": "msg_sintetico", "type": "message", "role": "assistant", "model": MODEL_ID,
        "content": [{"type": "text", "text": "Respuesta exclusivamente sintética."}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 300,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    })

    def handler(request):
        case.requests.append(request)
        return httpx2.Response(case.status, json=case.reply)

    key = "clave-anthropic-exclusivamente-sintetica"
    monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    case.budget = Budget(database, config.defaults.budget, [AccountAllowance(
        provider="anthropic", account_ref="cuenta-sintetica", funding_source="prepaid",
        cost_limit_usd="1", source_reference="Cupo sintético", observed_at=utc_now(),
    )])
    case.grant = case.budget.authorize(SpendingAuthorization(
        provider="anthropic", operation="messages", account_ref="cuenta-sintetica",
        max_cost_usd="1", max_credits="0", responsible="Responsable sintético",
        source_reference="Autorización sintética sin red", authorized_at=utc_now(),
    ))
    sdk = anthropic.Anthropic(api_key=key, max_retries=0,
                              http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    case.client = ClaudeClient(case.budget, sdk_client=sdk)
    case.payload = {"model": MODEL_ID, "max_tokens": 1000,
                    "messages": [{"role": "user", "content": "Consulta sintética."}]}
    case.reservation = case.budget.reserve(Usage(
        campaign_id=campaign.id, provider="anthropic", operation="messages", account_ref="cuenta-sintetica",
        request_fingerprint=case.client.fingerprint(case.payload, "cuenta-sintetica"),
        reserved_cost_usd="0.01", reserved_credits="0", funding_source="prepaid", status="reserved",
    ), case.grant)
    case.call = lambda: case.client.create(case.reservation.request_id, case.payload,
                                          account_ref="cuenta-sintetica", authorization=case.grant)
    yield case
    sdk.close()


@pytest.mark.parametrize("field, value", [
    ("input_tokens", -1), ("input_tokens", True), ("output_tokens", "300"),
    ("cache_creation_input_tokens", -2),
])
def test_malformed_usage_records_schema_error_and_preserves_valid_counts(sdk_case, field, value):
    case = sdk_case
    case.reply["usage"][field] = value
    with pytest.raises(ProviderError) as error:
        case.call()
    assert error.value.kind == "schema"
    saved = case.db.get_usage(case.reservation.request_id)
    assert saved.status == "uncertain" and saved.outcome == "unknown"
    assert saved.error_message == error.value.message
    assert saved.reserved_cost_usd == Decimal("0.01") and saved.final_cost_usd is None
    assert saved.estimated_cost_usd is None
    assert saved.tokens.input_tokens == (None if field == "input_tokens" else 1200)
    assert saved.tokens.output_tokens == (None if field == "output_tokens" else 300)
    assert len(case.requests) == 1
    with pytest.raises(BudgetError):
        case.call()
    assert len(case.requests) == 1


@pytest.mark.parametrize("field, value", [
    ("id", 123), ("model", ""), ("stop_reason", 42),
    ("content", None), ("content", [{"type": "text"}]),
    ("content", [{"type": "text", "text": 123}]),
])
def test_malformed_envelope_preserves_observed_usage_without_recording_success(sdk_case, field, value):
    case = sdk_case
    case.reply[field] = value
    with pytest.raises(ProviderError) as error:
        case.call()
    assert error.value.kind == "schema"
    saved = case.db.get_usage(case.reservation.request_id)
    assert saved.status == "uncertain" and saved.outcome == "unknown"
    assert saved.error_message == error.value.message
    assert saved.tokens.input_tokens == 1200 and saved.tokens.output_tokens == 300
    assert saved.estimated_cost_usd == Decimal("0.00027")
    assert saved.reserved_cost_usd == Decimal("0.01") and saved.final_cost_usd is None
    assert len(case.requests) == 1


def test_valid_envelope_accepts_resolved_model_and_joins_text_blocks(sdk_case):
    case = sdk_case
    case.reply["model"] = "haiku-alias-resuelto-sintetico"
    case.reply["content"] = [{"type": "text", "text": "Primera parte. "},
                             {"type": "text", "text": "Segunda parte."}]
    call = case.call()
    assert call.model == "haiku-alias-resuelto-sintetico"
    assert call.text == "Primera parte. Segunda parte."
    assert call.estimated_cost_usd == Decimal("0.00027")
    saved = case.db.get_usage(call.request_id)
    assert saved.status == "succeeded" and saved.error_message is None


@pytest.mark.parametrize("encode", [quote, quote_plus, lambda value: json.dumps(value)[1:-1]],
                         ids=["url", "query", "json-ascii"])
def test_sdk_http_errors_omit_encoded_input_and_preserve_safe_diagnostic(sdk_case, encode):
    case = sdk_case
    sensitive = [case.payload["messages"][0]["content"], "clave-anthropic-exclusivamente-sintetica"]
    case.status = 401
    case.reply = {"error": {"type": "authentication_error",
        "message": "Fallo SDK sintético denied. " + " | ".join(map(encode, sensitive))}}
    with pytest.raises(ProviderError) as error:
        case.call()
    assert error.value.kind == "http" and error.value.http_status == 401
    saved = case.db.get_usage(case.reservation.request_id)
    assert "Fallo SDK sintético denied." in error.value.message
    assert saved.error_message == error.value.message and saved.outcome == "failed"
    assert saved.request_fingerprint == case.reservation.request_fingerprint
    assert saved.reserved_cost_usd == Decimal("0.01") and len(case.requests) == 1
    for value in sensitive:
        assert value not in saved.error_message and encode(value) not in saved.error_message
