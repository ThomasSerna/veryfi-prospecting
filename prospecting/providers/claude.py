"""Cliente de Claude con el SDK oficial, precios publicados y tope de reserva; sin reintentos automáticos."""

from decimal import Decimal
import hashlib
import json
import math
import os
import time
from uuid import UUID

from pydantic import StrictStr

from prospecting.budget import Budget, BudgetError, Observation, SpendingAuthorization
from prospecting.models import Contract, Money, Text, TokenUsage
from prospecting.providers.http import ProviderError, ProviderRequest, _retry_after, _safe_message


CLAUDE_PROVIDER = "anthropic"
CLAUDE_OPERATION = "messages"
CLAUDE_TIMEOUT_SECONDS = 30.0
# USD por millón de tokens (entrada, salida) para prompts de hasta 100K tokens;
# referencia oficial de la API de Claude (W4), consultada el 2026-10-11.
CLAUDE_PRICES_PER_MTOK = {"claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50"))}
# Margen para el prompt de sistema que Anthropic inyecta con las salidas estructuradas y el formato
# de los mensajes: también se factura como entrada y la documentación no publica su tamaño (W4).
INJECTED_PROMPT_TOKENS = 1000


def input_token_bound(payload: dict) -> int:
    """Cota superior de tokens de entrada facturables del payload que se envía.

    Supone que cada token cubre al menos un byte del texto: cuenta los bytes UTF-8 del payload
    serializado (sistema, mensajes y esquema; claves y escapes solo suman) y el margen del prompt
    inyectado. Medido el 2026-10-12: 13.757 bytes frente a 6.175 tokens facturados.
    """
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return len(serialized.encode("utf-8")) + INJECTED_PROMPT_TOKENS


def reservation_cost(model: str, max_input: int, max_output: int) -> Decimal:
    """Cota superior de una llamada: tokens máximos de entrada y salida por el precio publicado (§14.3)."""
    price_in, price_out = CLAUDE_PRICES_PER_MTOK[model]
    return (max_input * price_in + max_output * price_out) / Decimal(1_000_000)


def claude_cost(model: str, tokens: TokenUsage) -> Decimal | None:
    """Costo estimado; desconocido si falta el precio o el uso, o si hubo caché no acotada."""
    prices = CLAUDE_PRICES_PER_MTOK.get(model)
    if prices is None or tokens.input_tokens is None or tokens.output_tokens is None:
        return None
    if tokens.cache_read_tokens or tokens.cache_write_tokens or tokens.additional_tokens:
        return None
    return (tokens.input_tokens * prices[0] + tokens.output_tokens * prices[1]) / Decimal(1_000_000)


class ClaudeCall(Contract):
    request_id: UUID
    model: Text
    provider_message_id: Text | None = None
    stop_reason: Text | None = None
    text: StrictStr
    tokens: TokenUsage
    estimated_cost_usd: Money | None = None


class ClaudeClient:
    """Una llamada al SDK oficial por reserva reclamada; sin reintentos automáticos (§13.3)."""

    def __init__(self, budget: Budget, sdk_client=None):
        self.budget = budget
        self._sdk = sdk_client

    @staticmethod
    def fingerprint(payload: dict, account_ref: str) -> str:
        data = {"provider": CLAUDE_PROVIDER, "operation": CLAUDE_OPERATION,
                "account_ref": account_ref, "payload": payload}
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def create(self, request_id: UUID, payload: dict, *, account_ref: str,
               authorization: SpendingAuthorization | None,
               remaining_seconds: float | None = None) -> ClaudeCall:
        started_at = time.monotonic()
        context = {"request_id": request_id, "provider": CLAUDE_PROVIDER, "operation": CLAUDE_OPERATION}
        try:
            request = ProviderRequest(provider=CLAUDE_PROVIDER, operation=CLAUDE_OPERATION,
                                      account_ref=account_ref, payload=payload)
        except (ValueError, TypeError):
            raise ProviderError("local", "Solicitud inválida.", **context) from None
        timeout = CLAUDE_TIMEOUT_SECONDS
        if remaining_seconds is not None:
            if isinstance(remaining_seconds, bool) or not isinstance(remaining_seconds, (int, float)) or not math.isfinite(remaining_seconds) or remaining_seconds <= 0:
                raise ProviderError("local", "El tiempo restante debe ser positivo y finito.", **context)
            timeout = min(timeout, remaining_seconds)
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key or any(ord(char) < 32 or ord(char) == 127 for char in key):
            raise ProviderError("local", "Falta una credencial válida en el entorno.", **context)
        usage = self.budget.db.get_usage(request_id)
        if usage is not None and (usage.provider, usage.operation, usage.account_ref) != (
            CLAUDE_PROVIDER, CLAUDE_OPERATION, account_ref
        ):
            raise ProviderError("local", "La solicitud no corresponde a la reserva.", **context)
        import anthropic

        # La clave se pasa explícitamente: no se usan perfiles locales ni otras credenciales.
        sdk = self._sdk or anthropic.Anthropic(api_key=key, max_retries=0)
        self.budget.claim(request_id, expected_fingerprint=self.fingerprint(payload, account_ref),
                          authorization=authorization)
        if remaining_seconds is not None:
            timeout = min(timeout, remaining_seconds - (time.monotonic() - started_at))
            if timeout <= 0:
                self._fail(ProviderError("local", "El plazo venció antes de invocar el proveedor.", **context), "failed", no_send=True)
        try:
            self.budget.begin_send(request_id, deadline=None if remaining_seconds is None else started_at + remaining_seconds)
        except BudgetError as error:
            if error.code != "deadline_unsent":
                raise
            self._fail(ProviderError("local", "El plazo venció antes de invocar el proveedor.", **context), "failed", no_send=True)
        try:
            response = sdk.with_options(timeout=timeout, max_retries=0).messages.create(**payload)
        except anthropic.APITimeoutError:
            self._fail(ProviderError("timeout", "Timeout del proveedor; consumo pendiente.", **context), "unknown")
        except anthropic.APIConnectionError as cause:
            self._fail(ProviderError("transport", _safe_message(str(cause), key, request), **context), "unknown")
        except anthropic.APIStatusError as cause:
            detail = cause.body.get("error", cause.body) if isinstance(cause.body, dict) else None
            detail = detail.get("message") if isinstance(detail, dict) else None
            message = f"HTTP {cause.status_code}." + (f" {_safe_message(detail, key, request)}" if isinstance(detail, str) else "")
            self._fail(ProviderError(
                "http", message, http_status=cause.status_code,
                retry_after_seconds=_retry_after(cause.response.headers.get("retry-after")), **context,
            ), "failed")
        except anthropic.APIError as cause:
            self._fail(ProviderError("transport", _safe_message(str(cause), key, request), **context), "unknown")
        raw = getattr(response, "usage", None)
        tokens = TokenUsage(
            input_tokens=getattr(raw, "input_tokens", None),
            output_tokens=getattr(raw, "output_tokens", None),
            cache_read_tokens=getattr(raw, "cache_read_input_tokens", None),
            cache_write_tokens=getattr(raw, "cache_creation_input_tokens", None),
        )
        cost = claude_cost(payload.get("model", ""), tokens)
        self.budget.record_result(request_id, Observation(outcome="succeeded", tokens=tokens, estimated_cost_usd=cost))
        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        return ClaudeCall(
            request_id=request_id, model=response.model, provider_message_id=response.id,
            stop_reason=response.stop_reason, text=text, tokens=tokens, estimated_cost_usd=cost,
        )

    def _fail(self, error, outcome, *, no_send=False):
        self.budget.record_result(error.request_id, Observation(outcome=outcome, error_message=error.message), no_send=no_send)
        error.no_send = no_send
        raise error from None
