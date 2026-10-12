"""Reservar, llamar y registrar el consumo observado; ninguna transacción queda abierta durante la red."""

from decimal import Decimal
import time
from uuid import UUID

from prospecting.budget import Budget, BudgetError, Observation, SpendingAuthorization
from prospecting.haiku import MODEL_ID
from prospecting.models import LlmLimits, TokenUsage, Usage, UsageStatus
from prospecting.providers import (
    CLAUDE_OPERATION, CLAUDE_PROVIDER, ProviderClient, ProviderRequest, reservation_cost,
)


def seconds_left(deadline: float | None) -> float | None:
    return None if deadline is None else deadline - time.monotonic()


def observed_credits(data) -> Decimal | None:
    if data.usage is None or data.usage.credits is None:
        return None
    return Decimal(str(data.usage.credits))


def reserve_credits(budget: Budget, request: ProviderRequest, fingerprint: str, credits: Decimal, *,
                    funding_source: str, campaign_id: UUID, company_id: UUID | None,
                    authorization: SpendingAuthorization | None) -> Usage:
    """Reserva la cota de créditos; fuera del crédito gratuito, su costo exige una valoración comprobada (§14.3)."""
    cost = Decimal(0)
    if funding_source != "free_credit":
        account = next((item for item in budget.account_allowances if
                        (item.provider, item.account_ref, item.funding_source) ==
                        (request.provider, request.account_ref, funding_source)), None)
        if account is None or account.credit_valuation is None:
            raise BudgetError("price_unbounded", "Falta la valoración comprobada del crédito de esta cuenta.")
        cost = credits * account.credit_valuation.unit_value_usd
    return budget.reserve(Usage(
        campaign_id=campaign_id, company_id=company_id, provider=request.provider,
        operation=request.operation, account_ref=request.account_ref, request_fingerprint=fingerprint,
        reserved_credits=credits, reserved_cost_usd=cost,
        funding_source=funding_source, status=UsageStatus.RESERVED,
    ), authorization)


def reserve_claude(budget: Budget, fingerprint: str, limits: LlmLimits, *, account_ref: str, funding_source: str,
                   campaign_id: UUID, company_id: UUID | None,
                   authorization: SpendingAuthorization | None) -> Usage:
    """Reserva tokens máximos de entrada y salida al precio publicado de Haiku (§14.3)."""
    return budget.reserve(Usage(
        campaign_id=campaign_id, company_id=company_id, provider=CLAUDE_PROVIDER, operation=CLAUDE_OPERATION,
        account_ref=account_ref, request_fingerprint=fingerprint,
        reserved_cost_usd=reservation_cost(MODEL_ID, limits.max_input_tokens, limits.max_output_tokens),
        reserved_credits=Decimal(0),
        reserved_tokens=TokenUsage(input_tokens=limits.max_input_tokens, output_tokens=limits.max_output_tokens),
        funding_source=funding_source, status=UsageStatus.RESERVED,
    ), authorization)


def call_free_credit(budget: Budget, client: ProviderClient, request: ProviderRequest,
                     response_model, *, campaign_id: UUID, company_id: UUID | None, credits: int,
                     authorization: SpendingAuthorization | None, deadline: float | None):
    """Reserva, llama y registra créditos observados; devuelve (uso, resultado)."""
    remaining = seconds_left(deadline)
    if remaining is not None and remaining <= 0:
        raise BudgetError("time_limit", "Se agotó el tiempo de la etapa antes de llamar.")
    usage = reserve_credits(budget, request, client.fingerprint(request), Decimal(credits),
                            funding_source="free_credit", campaign_id=campaign_id, company_id=company_id,
                            authorization=authorization)
    result = client.request_json(
        usage.request_id, request, response_model,
        authorization=authorization, remaining_seconds=remaining,
    )
    observed = observed_credits(result.data)
    if observed is not None:
        budget.record_result(usage.request_id, Observation(outcome="succeeded", credits=observed))
    return usage, result, observed


