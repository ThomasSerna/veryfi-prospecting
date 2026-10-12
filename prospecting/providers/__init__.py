"""Clientes acotados de proveedores; solo `prospecting.pipeline` los invoca tras reservar gasto.

`http` define descriptores, solicitudes, errores y el transporte JSON; `claude`, el cliente
del SDK oficial. Los adaptadores por proveedor se importan desde su propio módulo.
"""

from prospecting.providers.claude import (
    CLAUDE_OPERATION, CLAUDE_PRICES_PER_MTOK, CLAUDE_PROVIDER, CLAUDE_TIMEOUT_SECONDS, ClaudeCall, ClaudeClient,
    claude_cost, reservation_cost,
)
from prospecting.providers.http import (
    DEFAULT_TIMEOUT_SECONDS, MAX_RESPONSE_BYTES, HttpResponse, OperationSpec, ProviderClient, ProviderError,
    ProviderRequest, ProviderResult,
)

__all__ = [
    "CLAUDE_OPERATION", "CLAUDE_PRICES_PER_MTOK", "CLAUDE_PROVIDER", "CLAUDE_TIMEOUT_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS", "MAX_RESPONSE_BYTES", "ClaudeCall", "ClaudeClient", "HttpResponse",
    "OperationSpec", "ProviderClient", "ProviderError", "ProviderRequest", "ProviderResult", "claude_cost",
    "reservation_cost",
]
