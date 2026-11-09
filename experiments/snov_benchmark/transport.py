"""HTTP experimental acotado, sin reintentos ni autenticación implícita."""

from email.utils import parsedate_to_datetime
from datetime import UTC, datetime
from http.client import HTTPException
import json
import math
import os
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, quote_plus, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from pydantic import BaseModel, Field, StrictInt, StrictStr, ValidationError

from prospecting.providers.http import HttpResponse

from .providers import RequestSpec, SNOV_REVEAL, SNOV_SEARCH, TOKEN_PATTERN


class BenchmarkProviderError(Exception):
    def __init__(self, code, message, *, http_status=None, retry_after=None):
        self.code, self.message = code, message
        self.http_status, self.retry_after = http_status, retry_after
        super().__init__(message)


def redact_message(message, sensitive=()):
    """Mantiene el fallo literal salvo secretos y datos identificables del transporte."""
    text = str(message)
    values = [*sensitive, *(os.environ.get(name, "") for name in (
        "SNOV_CLIENT_ID", "SNOV_CLIENT_SECRET", "APOLLO_API_KEY",
    ))]
    variants = {part for value in values if isinstance(value, str) and value for part in (
        value, quote(value, safe=""), quote_plus(value), json.dumps(value)[1:-1],
    )}
    for value in sorted(variants, key=len, reverse=True):
        text = text.replace(value, "[omitido]")
    text = re.sub(r"https?://[^\s\"'<>]+", "[URL omitida]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[correo omitido]", text)
    text = re.sub(r"\+?\d[\d ()-]{7,}\d", "[número omitido]", text)
    return re.sub(r"[\x00-\x1f\x7f]", " ", text).strip()[:1000]


def _retry_after(headers):
    value = next((value for name, value in headers.items() if name.lower() == "retry-after"), None)
    if value is None:
        return None
    try:
        seconds = float(value) if re.fullmatch(r"\d+", value) else (
            parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _json(response):
    try:
        value = json.loads(response.body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise BenchmarkProviderError("invalid_response", "El proveedor devolvió JSON inválido.",
                                     http_status=response.status) from None
    if not isinstance(value, dict):
        raise BenchmarkProviderError("invalid_response", "La respuesta JSON del proveedor debe ser un objeto.",
                                     http_status=response.status)
    return value


def decode_response(response: HttpResponse) -> dict:
    response = HttpResponse.model_validate(response)
    if not 200 <= response.status < 300:
        try:
            data = _json(response)
        except BenchmarkProviderError:
            data = {}
        message = data.get("message") or data.get("error_description") or data.get("error")
        message = message if isinstance(message, str) else f"El proveedor respondió HTTP {response.status}."
        details = data.get("error_details")
        provider_code = data.get("error_code") or (details.get("code") if isinstance(details, dict) else None)
        if isinstance(provider_code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", provider_code):
            message = f"{provider_code}: {message}"
        raise BenchmarkProviderError(f"http_{response.status}", redact_message(message),
                                     http_status=response.status, retry_after=_retry_after(response.headers))
    content_type = next((value for name, value in response.headers.items() if name.lower() == "content-type"), "")
    if not (content_type.split(";", 1)[0].strip().lower() == "application/json"
            or content_type.split(";", 1)[0].strip().lower().endswith("+json")):
        raise BenchmarkProviderError("invalid_response", "El proveedor no devolvió Content-Type JSON.",
                                     http_status=response.status)
    data = _json(response)
    status = data.get("status")
    if (data.get("success") is False or isinstance(status, str) and status in {"not_enough_credits", "failed", "error"}
            or data.get("error") or data.get("errors")):
        message = data.get("message") or data.get("error") or data.get("status") or "El proveedor informó un fallo."
        raise BenchmarkProviderError("provider_error", redact_message(message), http_status=response.status)
    return data


def _endpoint(spec):
    paths = {
        ("snov", "oauth", "POST"): r"/v1/oauth/access_token",
        ("snov", "people_search", "POST"): SNOV_SEARCH + r"/start",
        ("snov", "people_search_result", "GET"): SNOV_SEARCH + r"/result/" + TOKEN_PATTERN,
        ("snov", "people_enrichment", "POST"): SNOV_REVEAL + r"/start/" + TOKEN_PATTERN,
        ("snov", "people_enrichment_result", "GET"): SNOV_REVEAL + r"/result/" + TOKEN_PATTERN,
        ("apollo", "people_search", "POST"): r"/api/v1/mixed_people/api_search",
        ("apollo", "people_enrichment", "POST"): r"/api/v1/people/match",
    }
    pattern = paths.get((spec.provider, spec.operation, spec.method))
    if pattern is None or re.fullmatch(pattern, spec.path) is None:
        raise BenchmarkProviderError("operation_forbidden", "La operación o ruta no pertenece al experimento.")
    if spec.method == "GET" and spec.payload is not None:
        raise BenchmarkProviderError("invalid_request", "GET no admite cuerpo JSON.")
    return ("https://api.snov.io" if spec.provider == "snov" else "https://api.apollo.io") + spec.path


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http(request, timeout_seconds, max_bytes):
    opener = build_opener(ProxyHandler({}), _RejectRedirects())
    deadline = time.monotonic() + timeout_seconds
    try:
        response = opener.open(request, timeout=timeout_seconds)
    except HTTPError as error:
        response = error
    with response:
        chunks, size = [], 0
        read = getattr(response, "read1", response.read)
        while size <= max_bytes:
            if time.monotonic() >= deadline:
                raise TimeoutError()
            chunk = read(min(65536, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return HttpResponse(status=response.code, headers=dict(response.headers), body=b"".join(chunks))


class _TokenReply(BaseModel):
    access_token: StrictStr
    token_type: StrictStr
    expires_in: StrictInt = Field(gt=0)


def _credential(name):
    value = os.environ.get(name, "").strip()
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise BenchmarkProviderError("missing_credentials", f"Falta una credencial válida: {name}.")
    return value


class BenchmarkTransport:
    """El pipeline debe reservar cada send; OAuth nunca se invoca automáticamente."""

    def __init__(self, transport=None):
        self._transport = transport or _http
        self._snov_token = None
        self._snov_expires_at = 0.0

    @property
    def snov_authenticated(self):
        return self._snov_token is not None and time.monotonic() < self._snov_expires_at

    def send(self, spec: RequestSpec, *, timeout_seconds, max_bytes=1_048_576) -> HttpResponse:
        spec = RequestSpec.model_validate(spec)
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (float, int))
                or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
                or type(max_bytes) is not int or max_bytes < 1):
            raise BenchmarkProviderError("invalid_request", "El transporte requiere plazo y tamaño positivos.")
        url, secrets = _endpoint(spec), []
        headers = {"Accept": "application/json"}
        if spec.params:
            url += "?" + urlencode(spec.params, doseq=True)
        if spec.provider == "snov" and spec.operation == "oauth":
            credentials = {"grant_type": "client_credentials", "client_id": _credential("SNOV_CLIENT_ID"),
                           "client_secret": _credential("SNOV_CLIENT_SECRET")}
            secrets = [credentials["client_id"], credentials["client_secret"]]
            body = urlencode(credentials).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            if spec.provider == "snov":
                if not self.snov_authenticated:
                    raise BenchmarkProviderError("authentication_required", "Snov requiere una operación OAuth reservada y vigente.")
                key = self._snov_token
                headers["Authorization"] = "Bearer " + key
            else:
                key = _credential("APOLLO_API_KEY")
                headers["x-api-key"] = key
                headers["Cache-Control"] = "no-cache"
            secrets = [key]
            body = None if spec.payload is None else json.dumps(spec.payload, allow_nan=False).encode("utf-8")
            if body is not None:
                headers["Content-Type"] = "application/json"
        try:
            request = Request(url, data=body, headers=headers, method=spec.method)
            response = HttpResponse.model_validate(self._transport(request, timeout_seconds, max_bytes))
        except (TimeoutError, socket.timeout):
            raise BenchmarkProviderError("timeout", "Timeout del proveedor; consumo pendiente.") from None
        except (OSError, URLError, HTTPException) as error:
            raise BenchmarkProviderError("transport_error", redact_message(str(error), secrets)) from None
        except (ValueError, TypeError, UnicodeError):
            raise BenchmarkProviderError("invalid_response", "El transporte devolvió una respuesta inválida.") from None
        if len(response.body) > max_bytes:
            raise BenchmarkProviderError("response_too_large", "La respuesta supera el tamaño permitido.",
                                         http_status=response.status)
        try:
            decoded = decode_response(response)
        except BenchmarkProviderError as error:
            raise BenchmarkProviderError(error.code, redact_message(error.message, secrets),
                                         http_status=error.http_status, retry_after=error.retry_after) from None
        if spec.provider == "snov" and spec.operation == "oauth":
            try:
                token = _TokenReply.model_validate(decoded)
                if (token.token_type != "Bearer" or not token.access_token
                        or any(ord(char) < 33 or ord(char) > 126 for char in token.access_token)):
                    raise ValueError()
            except (ValidationError, ValueError):
                raise BenchmarkProviderError("invalid_response", "Snov devolvió una credencial OAuth inválida.") from None
            self._snov_token = token.access_token
            self._snov_expires_at = time.monotonic() + token.expires_in
            response = HttpResponse(status=response.status, headers={"Content-Type": "application/json"},
                                    body=json.dumps({"authenticated": True, "expires_in": token.expires_in}).encode())
        return response
