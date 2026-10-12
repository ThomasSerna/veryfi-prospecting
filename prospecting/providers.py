"""Clientes acotados de proveedores (HTTP JSON y SDK de Anthropic); sin reintentos automáticos."""

from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
import hashlib
from http.client import HTTPException
import ipaddress
import json
import math
import os
import re
import socket
import time
from typing import Annotated, Callable, Generic, Literal, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPRedirectHandler, ProxyHandler, Request, build_opener,
)
from uuid import UUID

from pydantic import (
    BaseModel, Field, HttpUrl, JsonValue, StrictBytes, StrictInt, StrictStr,
    field_validator, model_validator,
)

from prospecting.budget import Budget, BudgetError, Observation, SpendingAuthorization
from prospecting.models import Contract, Money, Text, TokenUsage


MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 10.0
T = TypeVar("T", bound=BaseModel)
_SECRET_FIELDS = {"api_key", "apikey", "authorization", "x-api-key", "access_token"}
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


class OperationSpec(Contract):
    """Descriptor confiable definido por código, nunca por contenido externo."""

    provider: Text
    operation: Text
    endpoint: HttpUrl
    method: Literal["GET", "POST"] = "POST"
    api_key_env: Literal[
        "TAVILY_API_KEY", "ANTHROPIC_API_KEY", "APOLLO_API_KEY", "HUNTER_API_KEY"
    ]
    auth_header: Text = "Authorization"
    auth_prefix: StrictStr = "Bearer "
    headers: dict[Text, StrictStr] = Field(default_factory=dict)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value):
        parts = urlsplit(str(value))
        host = parts.hostname or ""
        if parts.scheme != "https" or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("El endpoint requiere HTTPS sin credenciales, query ni fragmento.")
        if host.lower().rstrip(".") == "localhost" or host.lower().rstrip(".").endswith((".localhost", ".local", ".internal")) or "." not in host:
            raise ValueError("El endpoint debe ser un host público autorizado.")
        try:
            address = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise ValueError("No se permiten direcciones privadas, locales o de metadata.")
        return value

    @model_validator(mode="after")
    def validate_headers(self):
        names = [self.auth_header, *self.headers]
        if any(not _HEADER_NAME.fullmatch(name) for name in names):
            raise ValueError("Nombre de cabecera inválido.")
        values = [self.auth_prefix, *self.headers.values()]
        if any(ord(char) < 32 or ord(char) == 127 for value in values for char in value):
            raise ValueError("Las cabeceras no admiten caracteres de control.")
        try:
            for value in values:
                value.encode("latin-1")
        except UnicodeEncodeError:
            raise ValueError("Las cabeceras deben poder codificarse como HTTP.") from None
        forbidden = {self.auth_header.lower(), "host", "content-length", "transfer-encoding", *_SECRET_FIELDS}
        if any(name.lower() in forbidden for name in self.headers):
            raise ValueError("Las cabeceras adicionales no pueden sustituir transporte o autenticación.")
        if self.auth_header.lower() in {"host", "content-length", "transfer-encoding", "content-type"}:
            raise ValueError("La cabecera de autenticación no puede alterar el transporte.")
        return self


class ProviderRequest(Contract):
    """Entrada sin destinos ni credenciales aportados por el llamador."""

    provider: Text
    operation: Text
    account_ref: Text
    params: dict[Text, JsonValue] = Field(default_factory=dict)
    payload: dict[Text, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_input(self):
        def check(value):
            if isinstance(value, dict):
                if any(key.lower() in _SECRET_FIELDS for key in value):
                    raise ValueError("Las credenciales solo se leen desde variables de entorno.")
                for item in value.values():
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)
        check(self.params)
        check(self.payload)
        for value in self.params.values():
            values = value if isinstance(value, list) else [value]
            if any(isinstance(item, (dict, list)) for item in values):
                raise ValueError("Los parámetros de query deben ser escalares o listas de escalares.")
        json.dumps(self.model_dump(mode="json"), allow_nan=False)
        return self


class HttpResponse(Contract):
    status: Annotated[StrictInt, Field(ge=100, le=599)]
    headers: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    body: StrictBytes


class ProviderResult(Contract, Generic[T]):
    request_id: UUID
    data: T
    observation: Observation


class ProviderError(Exception):
    """Error seguro para persistencia, sin cuerpos ni solicitudes originales."""

    def __init__(self, kind, message, *, request_id=None, provider=None, operation=None,
                 http_status=None, retry_after_seconds=None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.request_id = request_id
        self.provider = provider
        self.operation = operation
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds
        self.retryable = False
        self.no_send = False


def _header(headers, name):
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


def _retry_after(value):
    if value is None:
        return None
    try:
        if re.fullmatch(r"[0-9]+", value.strip()):
            seconds = float(value.strip())
        else:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                return None
            seconds = max(0.0, (parsed - datetime.now(UTC)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return None
    return seconds if math.isfinite(seconds) else None


def _reject_json_constant(value):
    raise ValueError("JSON no admite constantes no finitas.")


def _query(params):
    return urlencode(sorted((name, value) for name, value in params.items() if value is not None), doseq=True)


def _safe_message(message, key, request):
    text = str(message)
    values = [key]
    def collect(value):
        if isinstance(value, str) and len(value) >= 3:
            values.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(request.params)
    collect(request.payload)
    for value in sorted(set(values), key=len, reverse=True):
        if value:
            text = text.replace(value, "[omitido]")
    text = re.sub(r"https?://[^\s\"'<>]+", "[URL omitida]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[correo omitido]", text)
    text = re.sub(r"\+?\d[\d ()-]{7,}\d", "[número omitido]", text)
    return re.sub(r"[\x00-\x1f\x7f]", " ", text).strip()[:1000] or "Fallo de transporte del proveedor."


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urllib_transport(request, timeout, max_bytes):
    """Una operación HTTPS; el timeout no garantiza un plazo absoluto de DNS."""
    opener = build_opener(ProxyHandler({}), _RejectRedirects())
    deadline = time.monotonic() + timeout
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        chunks = []
        size = 0
        read = getattr(response, "read1", response.read)
        while size <= max_bytes:
            if time.monotonic() >= deadline:
                raise TimeoutError("Se agotó el tiempo de lectura.")
            chunk = read(min(65536, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return HttpResponse(status=response.code, headers=dict(response.headers), body=b"".join(chunks))


class ProviderClient:
    """Solo llama operaciones explícitas tras reclamar una reserva persistida."""

    def __init__(self, budget: Budget, operation_specs: list[OperationSpec],
                 transport: Callable[[Request, float, int], HttpResponse] | None = None):
        self.budget = budget
        specs = [OperationSpec.model_validate(spec) for spec in operation_specs]
        self._specs = {(spec.provider, spec.operation): spec for spec in specs}
        if len(self._specs) != len(specs):
            raise ValueError("Hay descriptores duplicados para una operación.")
        self._transport = transport or _urllib_transport

    def _spec(self, request, request_id=None):
        spec = self._specs.get((request.provider, request.operation))
        if spec is None:
            raise ProviderError("local", "La operación no está habilitada.", request_id=request_id,
                                provider=request.provider, operation=request.operation)
        if spec.method == "GET" and request.payload is not None:
            raise ProviderError("local", "GET no admite cuerpo JSON.", request_id=request_id,
                                provider=request.provider, operation=request.operation)
        return spec

    def fingerprint(self, request: ProviderRequest) -> str:
        request = ProviderRequest.model_validate(request)
        spec = self._spec(request)
        data = {"provider": request.provider, "operation": request.operation,
                "account_ref": request.account_ref, "query": _query(request.params),
                "payload": request.payload, "method": spec.method,
                "endpoint": str(spec.endpoint), "headers": spec.headers}
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def request_json(self, request_id: UUID, request: ProviderRequest, response_model: type[T], *,
                     authorization: SpendingAuthorization | None = None,
                     remaining_seconds: float | None = None) -> ProviderResult[T]:
        started_at = time.monotonic()
        try:
            request = ProviderRequest.model_validate(request)
        except (ValueError, TypeError):
            raise ProviderError("local", "Solicitud inválida.", request_id=request_id) from None
        spec = self._spec(request, request_id)
        context = {"request_id": request_id, "provider": request.provider, "operation": request.operation}
        if not isinstance(response_model, type) or not issubclass(response_model, BaseModel):
            raise ProviderError("local", "La respuesta exige un modelo Pydantic.", **context)
        timeout = DEFAULT_TIMEOUT_SECONDS
        if remaining_seconds is not None:
            if isinstance(remaining_seconds, bool) or not isinstance(remaining_seconds, (int, float)) or not math.isfinite(remaining_seconds) or remaining_seconds <= 0:
                raise ProviderError("local", "El tiempo restante debe ser positivo y finito.", **context)
            timeout = min(timeout, remaining_seconds)
        key = os.environ.get(spec.api_key_env, "").strip()
        if not key or any(ord(char) < 32 or ord(char) == 127 for char in key):
            raise ProviderError("local", "Falta una credencial válida en el entorno.", **context)
        try:
            key.encode("latin-1")
        except UnicodeEncodeError:
            raise ProviderError("local", "La credencial no puede codificarse como HTTP.", **context) from None
        usage = self.budget.db.get_usage(request_id)
        if usage is not None and (usage.provider, usage.operation, usage.account_ref) != (
            request.provider, request.operation, request.account_ref
        ):
            raise ProviderError("local", "La solicitud no corresponde a la reserva.", **context)
        url = str(spec.endpoint)
        query = _query(request.params)
        if query:
            url += "?" + query
        body = None if request.payload is None else json.dumps(
            request.payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        headers = {"Accept": "application/json", **spec.headers,
                   spec.auth_header: spec.auth_prefix + key}
        if body is not None:
            headers["Content-Type"] = "application/json"
        prepared = Request(url, data=body, headers=headers, method=spec.method)
        self.budget.claim(request_id, expected_fingerprint=self.fingerprint(request),
                          authorization=authorization)
        if remaining_seconds is not None:
            timeout = min(timeout, remaining_seconds - (time.monotonic() - started_at))
            if timeout <= 0:
                self._fail(ProviderError("local", "El plazo venció antes de invocar el transporte.", **context), "failed", no_send=True)
        try:
            self.budget.begin_send(request_id, deadline=None if remaining_seconds is None else started_at + remaining_seconds)
        except BudgetError as error:
            if error.code != "deadline_unsent":
                raise
            self._fail(ProviderError("local", "El plazo venció antes de invocar el transporte.", **context), "failed", no_send=True)
        try:
            response = HttpResponse.model_validate(self._transport(prepared, timeout, MAX_RESPONSE_BYTES))
        except (TimeoutError, socket.timeout):
            error = ProviderError("timeout", "Timeout del proveedor; consumo pendiente.", **context)
            self._fail(error, "unknown")
        except (URLError, OSError, HTTPException) as cause:
            if isinstance(cause, URLError) and isinstance(cause.reason, TimeoutError):
                error = ProviderError("timeout", "Timeout del proveedor; consumo pendiente.", **context)
            else:
                error = ProviderError("transport", _safe_message(str(cause), key, request), **context)
            self._fail(error, "unknown")
        except (ValueError, TypeError):
            self._fail(ProviderError("transport", "Respuesta inválida del transporte; consumo pendiente.", **context), "unknown")
        if len(response.body) > MAX_RESPONSE_BYTES:
            self._fail(ProviderError("response_limit", "La respuesta supera el límite de tamaño.", **context), "failed")
        if response.status >= 300 or response.status < 200:
            message = f"HTTP {response.status}."
            try:
                raw = json.loads(response.body)
                if isinstance(raw, dict):
                    detail = raw.get("error", raw)
                    if isinstance(detail, dict):
                        detail = detail.get("message", detail.get("detail"))
                    # Tavily responde {"detail": {"error": "..."}}.
                    if isinstance(detail, dict):
                        detail = detail.get("error", detail.get("message"))
                    if isinstance(detail, str):
                        message += " " + _safe_message(detail, key, request)
            except (ValueError, UnicodeError, RecursionError):
                pass
            error = ProviderError("redirect" if 300 <= response.status < 400 else "http", message,
                                  http_status=response.status,
                                  retry_after_seconds=_retry_after(_header(response.headers, "Retry-After")), **context)
            self._fail(error, "failed")
        content_type = (_header(response.headers, "Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json" and not (content_type.startswith("application/") and content_type.endswith("+json")):
            self._fail(ProviderError("content_type", "El proveedor no devolvió contenido JSON.", **context), "failed")
        try:
            json.loads(response.body, parse_constant=_reject_json_constant)
        except (ValueError, UnicodeError, RecursionError):
            self._fail(ProviderError("json", "JSON inválido del proveedor.", **context), "failed")
        try:
            data = response_model.model_validate_json(response.body)
        except (ValueError, TypeError):
            self._fail(ProviderError("schema", "La respuesta no cumple el esquema esperado.", **context), "failed")
        observation = Observation(outcome="succeeded")
        self.budget.record_result(request_id, observation)
        return ProviderResult(request_id=request_id, data=data, observation=observation)

    def _fail(self, error, outcome, *, no_send=False):
        self.budget.record_result(error.request_id, Observation(outcome=outcome, error_message=error.message), no_send=no_send)
        error.no_send = no_send
        raise error from None


CLAUDE_PROVIDER = "anthropic"
CLAUDE_OPERATION = "messages"
CLAUDE_TIMEOUT_SECONDS = 30.0
# USD por millón de tokens (entrada, salida) para prompts de hasta 100K tokens;
# referencia oficial de la API de Claude (W4), consultada el 2026-10-11.
CLAUDE_PRICES_PER_MTOK = {"claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50"))}


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
