"""Reservar, llamar y registrar el consumo observado; ninguna transacción queda abierta durante la red."""

from decimal import Decimal
import time
from uuid import UUID

from prospecting.budget import Budget, BudgetError, Observation, SpendingAuthorization
from prospecting.models import Usage, UsageStatus
from prospecting.providers import ProviderClient, ProviderRequest


def seconds_left(deadline: float | None) -> float | None:
    return None if deadline is None else deadline - time.monotonic()


def observed_credits(data) -> Decimal | None:
    if data.usage is None or data.usage.credits is None:
        return None
    return Decimal(str(data.usage.credits))


def call_free_credit(budget: Budget, client: ProviderClient, request: ProviderRequest,
                     response_model, *, campaign_id: UUID, company_id: UUID | None, credits: int,
                     authorization: SpendingAuthorization | None, deadline: float | None):
    """Reserva, llama y registra créditos observados; devuelve (uso, resultado)."""
    remaining = seconds_left(deadline)
    if remaining is not None and remaining <= 0:
        raise BudgetError("time_limit", "Se agotó el tiempo de la etapa antes de llamar.")
    usage = budget.reserve(Usage(
        campaign_id=campaign_id, company_id=company_id, provider=request.provider,
        operation=request.operation, account_ref=request.account_ref,
        request_fingerprint=client.fingerprint(request),
        reserved_cost_usd=Decimal(0), reserved_credits=Decimal(credits),
        funding_source="free_credit", status=UsageStatus.RESERVED,
    ), authorization)
    result = client.request_json(
        usage.request_id, request, response_model,
        authorization=authorization, remaining_seconds=remaining,
    )
    observed = observed_credits(result.data)
    if observed is not None:
        budget.record_result(usage.request_id, Observation(outcome="succeeded", credits=observed))
    return usage, result, observed


