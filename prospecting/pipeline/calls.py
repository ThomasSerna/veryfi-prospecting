"""Reservar, llamar y registrar el consumo observado; ninguna transacción queda abierta durante la red."""

from decimal import Decimal
import os
import time
from uuid import UUID

from prospecting.budget import Budget, BudgetError, Observation, RequestLimit, SpendingAuthorization
from prospecting.haiku import MODEL_ID
from prospecting.models import Campaign, TokenUsage, Usage, UsageStatus
from prospecting.providers.apollo import ApolloAccess
from prospecting.providers import (
    CLAUDE_OPERATION, CLAUDE_PROVIDER, ProviderClient, ProviderRequest, input_token_bound, reservation_cost,
)


def require_apollo_access(campaign: Campaign, access: ApolloAccess | None, budget: Budget) -> None:
    if campaign.config_snapshot.people_provider != "apollo":
        raise ValueError("La campaña histórica solo permite consulta y exportación; prepara una campaña nueva con Apollo.")
    key = os.environ.get("APOLLO_API_KEY", "").strip()
    if not key or any(ord(char) < 32 or ord(char) == 127 for char in key):
        raise ValueError("Apollo bloqueado: falta una APOLLO_API_KEY válida en el entorno local.")
    try:
        key.encode("latin-1")
    except UnicodeEncodeError:
        raise ValueError("Apollo bloqueado: credencial local no válida para HTTP.") from None
    if access is None:
        raise ValueError("Apollo bloqueado: falta comprobar acceso, correo laboral y cuota.")
    access = ApolloAccess.model_validate(access)
    if not access.access_verified or not access.work_email_verified or not {
            "people_search", "people_enrichment"}.issubset(access.enabled_operations):
        raise ValueError("Apollo bloqueado: comprueba correo laboral, acceso a Search/Enrichment, cuota y facturación antes de investigar.")
    allowance = next((item for item in budget.account_allowances if
                      (item.provider, item.account_ref, item.funding_source) ==
                      ("apollo", access.account_ref, access.funding_source)), None)
    if allowance is None or allowance.credit_limit is None:
        raise ValueError("Apollo bloqueado: falta una cuenta con cuota comprobada compatible.")
    account = next(item for item in budget.snapshot(campaign.id).accounts if
                   (item.provider, item.account_ref) == ("apollo", access.account_ref))
    if account.credits.unknown or account.credits.available is None or account.credits.available < access.enrichment_credit_bound:
        raise ValueError("Apollo bloqueado: cuota agotada o pendiente de conciliación.")
    # Toda llamada a Apollo pasa por aquí: sus límites de solicitudes quedan registrados antes de reservar (T17).
    budget.limit_requests(apollo_request_limits(access))


def apollo_request_limits(access: ApolloAccess) -> list[RequestLimit]:
    """Convierte los límites de la cuenta de Apollo en límites del ledger por operación y ventana."""
    return [RequestLimit(provider="apollo", operation=operation, account_ref=access.account_ref,
                         window_seconds=window, max_requests=getattr(limit, field))
            for operation, limit in access.rate_limits.items() if operation in access.enabled_operations
            for window, field in ((60, "per_minute"), (3600, "per_hour"), (86400, "per_day"))]


def seconds_left(deadline: float | None) -> float | None:
    return None if deadline is None else deadline - time.monotonic()


def grant_for(authorizations: list[SpendingAuthorization] | None, provider: str, operation: str,
              account_ref: str | None) -> SpendingAuthorization | None:
    """Permiso de la sesión para la operación y cuenta exactas; sin él, la reserva se rechaza."""
    return next((item for item in authorizations or [] if
                 (item.provider, item.operation, item.account_ref) == (provider, operation, account_ref)), None)


def was_sent(budget: Budget, error) -> bool:
    """Un error con la reserva aún `reserved` o con prueba de no envío no consumió cupo del proveedor."""
    if getattr(error, "no_send", False) or getattr(error, "request_id", None) is None:
        return False
    usage = budget.db.get_usage(error.request_id)
    return usage is not None and usage.status != UsageStatus.RESERVED


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


def reserve_claude(budget: Budget, fingerprint: str, payload: dict, *, account_ref: str, funding_source: str,
                   campaign_id: UUID, company_id: UUID | None,
                   authorization: SpendingAuthorization | None) -> Usage:
    """Reserva la cota de entrada del payload real y su máximo de salida al precio publicado de Haiku (§14.3)."""
    input_tokens, output_tokens = input_token_bound(payload), payload["max_tokens"]
    return budget.reserve(Usage(
        campaign_id=campaign_id, company_id=company_id, provider=CLAUDE_PROVIDER, operation=CLAUDE_OPERATION,
        account_ref=account_ref, request_fingerprint=fingerprint,
        reserved_cost_usd=reservation_cost(MODEL_ID, input_tokens, output_tokens),
        reserved_credits=Decimal(0),
        reserved_tokens=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
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
    remaining = seconds_left(deadline)
    if remaining is not None and remaining <= 0:
        raise BudgetError("time_limit", "Se agotó el tiempo de la etapa antes de llamar.", usage.request_id)
    result = client.request_json(
        usage.request_id, request, response_model,
        authorization=authorization, remaining_seconds=remaining,
    )
    observed = observed_credits(result.data)
    if observed is not None:
        budget.record_result(usage.request_id, Observation(outcome="succeeded", credits=observed))
    return usage, result, observed


