"""Reserva local conservadora; ninguna función realiza llamadas de red."""

from decimal import Decimal, localcontext
import math
import time
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool

from prospecting.db import Database
from prospecting.models import (
    BudgetLimits, Contract, Money, Text, TokenUsage, Usage, UsageStatus,
    UtcDatetime, utc_now,
)


FundingSource = Literal["free_credit", "prepaid", "new_outlay"]
Outcome = Literal["succeeded", "failed", "unknown"]


class CreditValuation(Contract):
    """Valor de referencia fijo del sprint; no es un cargo ni habilita gasto."""

    unit_value_usd: Money
    source_reference: Text
    observed_at: UtcDatetime


class AccountAllowance(Contract):
    """Cupo inicial fijo del sprint, no saldo restante ni cuota que se reinicia.

    La fecha documenta la consulta; nunca excluye consumos anteriores del ledger.
    """

    provider: Text
    account_ref: Text
    funding_source: FundingSource
    credit_limit: Money | None = None
    cost_limit_usd: Money | None = None
    source_reference: Text
    observed_at: UtcDatetime
    credit_valuation: CreditValuation | None = None


class SpendingAuthorization(Contract):
    """Tope de sesión compartido entre las solicitudes vinculadas al permiso."""

    provider: Text
    operation: Text
    account_ref: Text
    max_cost_usd: Money
    max_credits: Money
    responsible: Text
    source_reference: Text
    authorized_at: UtcDatetime


class Observation(Contract):
    outcome: Outcome
    tokens: TokenUsage | None = None
    credits: Money | None = None
    estimated_cost_usd: Money | None = None
    error_message: Text | None = None
    observed_at: UtcDatetime = Field(default_factory=utc_now)
    retryable: StrictBool = False


class Confirmation(Contract):
    """Consumo confirmado; el llamador conserva su referencia en evidencia local.

    Usage guarda la cuenta y reconciled_at; no admite una referencia adicional.
    """

    outcome: Outcome
    final_cost_usd: Money
    credits: Money
    outlay_usd: Money
    tokens: TokenUsage | None = None
    source_reference: Text
    observed_at: UtcDatetime
    no_send: StrictBool = False


class BudgetError(Exception):
    """Fallo de presupuesto con código estable y mensaje apto para la interfaz."""

    def __init__(self, code: str, message: str, request_id: UUID | None = None):
        super().__init__(message)
        self.code = code
        self.request_id = request_id


class BudgetAmount(Contract):
    confirmed: Money
    estimated: Money
    reserved: Money
    pending: Money
    exposure: Money | None
    limit: Money | None
    available: Money | None
    unknown: StrictBool
    exceeded: StrictBool


class AccountSnapshot(Contract):
    provider: Text
    account_ref: Text
    funding_source: FundingSource
    cost: BudgetAmount
    credits: BudgetAmount


class BudgetSnapshot(Contract):
    global_budget: BudgetAmount
    operating: BudgetAmount
    campaign: BudgetAmount
    company: BudgetAmount | None
    accounts: list[AccountSnapshot]
    reservation_overrun: StrictBool
    confirmed_cost_usd: Money | None
    outlay_usd: Money | None
    free_credit_equivalent: BudgetAmount


def _sum(values) -> Decimal:
    """Suma exacta incluso cuando el ledger supera la precisión decimal global."""
    values = list(values)
    if not values:
        return Decimal(0)
    digits = max(value.adjusted() for value in values) - min(
        value.as_tuple().exponent for value in values
    ) + 1
    with localcontext() as context:
        context.prec = max(28, digits + len(str(len(values))) + 2)
        return sum(values, Decimal(0))


def _cost(usage: Usage) -> Decimal | None:
    if usage.status == UsageStatus.RECONCILED:
        if usage.final_cost_usd is None or usage.outlay_usd is None:
            return None
        return max(usage.final_cost_usd, usage.outlay_usd)
    if usage.reserved_cost_usd is None:
        return None
    return max(value for value in (
        usage.reserved_cost_usd, usage.estimated_cost_usd,
        usage.final_cost_usd, usage.outlay_usd,
    ) if value is not None)


def _credits(usage: Usage) -> Decimal | None:
    if usage.status == UsageStatus.RECONCILED:
        return usage.credits
    if usage.reserved_credits is None:
        return None
    return max(usage.reserved_credits, usage.credits or Decimal(0))


def _amount(rows: list[Usage], limit: Decimal | None, *, credits=False,
            credit_valuations: dict[tuple, CreditValuation] | None = None) -> BudgetAmount:
    credits = credits or credit_valuations is not None

    def convert(row, quantity):
        if credit_valuations is None:
            return quantity
        valuation = credit_valuations.get((row.provider, row.account_ref))
        if quantity is None or valuation is None or row.funding_source != "free_credit":
            return None
        with localcontext() as context:
            context.prec = max(28, len(quantity.as_tuple().digits) + len(valuation.unit_value_usd.as_tuple().digits))
            return quantity * valuation.unit_value_usd

    def value(row):
        return convert(row, _credits(row) if credits else _cost(row))

    confirmed = _sum(value(row) for row in rows if row.status == UsageStatus.RECONCILED and value(row) is not None)
    pending = _sum(value(row) for row in rows if row.status != UsageStatus.RECONCILED and value(row) is not None)
    unknown = any(value(row) is None for row in rows)
    exposure = None if unknown else _sum([confirmed, pending])
    reserved = _sum(
        convert(row, getattr(row, "reserved_credits" if credits else "reserved_cost_usd"))
        for row in rows if row.status != UsageStatus.RECONCILED
        and convert(row, getattr(row, "reserved_credits" if credits else "reserved_cost_usd")) is not None
    )
    estimated = _sum(
        convert(row, getattr(row, "credits" if credits else "estimated_cost_usd"))
        for row in rows if row.status != UsageStatus.RECONCILED
        and convert(row, getattr(row, "credits" if credits else "estimated_cost_usd")) is not None
    )
    return BudgetAmount(
        confirmed=confirmed, estimated=estimated, reserved=reserved, pending=pending,
        exposure=exposure, limit=limit,
        available=None if exposure is None or limit is None else max(Decimal(0), _sum([limit, exposure.copy_negate()])),
        unknown=unknown, exceeded=exposure is not None and limit is not None and exposure > limit,
    )


def _context(usage: Usage):
    return (
        usage.campaign_id, usage.company_id, usage.provider, usage.account_ref,
        usage.operation, usage.request_fingerprint,
    )


def _grant_key(authorization: SpendingAuthorization):
    return (
        authorization.provider, authorization.operation, authorization.account_ref,
        authorization.responsible, authorization.source_reference, authorization.authorized_at,
    )


def _overrun(usage: Usage) -> bool:
    funding_conflict = (
        usage.funding_source == "free_credit" and any(
            value is not None and value > 0 for value in (usage.final_cost_usd, usage.outlay_usd)
        )
    ) or (usage.funding_source == "prepaid" and usage.outlay_usd is not None and usage.outlay_usd > 0)
    observed = None if usage.status == UsageStatus.RECONCILED else usage.estimated_cost_usd
    return funding_conflict or any(
        actual is not None and reserved is not None and actual > reserved
        for actual, reserved in (
            (usage.final_cost_usd, usage.reserved_cost_usd),
            (observed, usage.reserved_cost_usd),
            (usage.outlay_usd, usage.reserved_cost_usd),
            (usage.credits, usage.reserved_credits),
        )
    )


def _tokens(previous: TokenUsage | None, current: TokenUsage | None) -> TokenUsage | None:
    if current is None:
        return previous
    values = {} if previous is None else previous.model_dump()
    for name, value in current.model_dump().items():
        if value is not None:
            if values.get(name) is not None and values[name] != value:
                raise BudgetError("usage_conflict", "Los tokens confirmados no se pueden sustituir.")
            values[name] = value
    return TokenUsage.model_validate(values)


class Budget:
    """Control de una base local; bases independientes no comparten presupuesto."""

    def __init__(self, db: Database, global_limits: BudgetLimits, account_allowances: list[AccountAllowance]):
        self._session_started_at = utc_now()
        self.db = db
        self.global_limits = BudgetLimits.model_validate_json(global_limits.model_dump_json())
        self.account_allowances = [AccountAllowance.model_validate_json(item.model_dump_json()) for item in account_allowances]
        keys = [(item.provider, item.account_ref) for item in self.account_allowances]
        if len(keys) != len(set(keys)):
            raise BudgetError("account_conflict", "Cada saldo real necesita un único cupo y referencia de cuenta.")
        self._retryable: set[UUID] = set()
        self._grants: dict[tuple, SpendingAuthorization] = {}
        self._grant_requests: dict[tuple, set[UUID]] = {}
        self._request_grants: dict[UUID, tuple] = {}
        self._claimed_unsent: set[UUID] = set()
        self._proved_unsent: set[UUID] = set()

    def authorize(self, authorization: SpendingAuthorization) -> SpendingAuthorization:
        """Registra un permiso fresco después de la aprobación humana explícita."""
        authorization = SpendingAuthorization.model_validate_json(authorization.model_dump_json())
        if not self._session_started_at < authorization.authorized_at <= utc_now():
            raise BudgetError("authorization_date", "El permiso debe proceder de esta sesión, después de su inicio.")
        key = _grant_key(authorization)
        previous = self._grants.get(key)
        if previous is not None and previous != authorization:
            raise BudgetError("authorization_conflict", "El mismo permiso no puede cambiar sus topes.")
        self._grants[key] = authorization
        self._grant_requests.setdefault(key, set())
        return SpendingAuthorization.model_validate_json(authorization.model_dump_json())

    def _registered_grant(self, authorization, request_id):
        if authorization is None:
            raise BudgetError("authorization_required", "La llamada necesita autorización explícita de gasto.", request_id)
        authorization = SpendingAuthorization.model_validate_json(authorization.model_dump_json())
        key = _grant_key(authorization)
        registered = self._grants.get(key)
        if registered is None:
            raise BudgetError("authorization_unregistered", "El permiso no está registrado en esta sesión.", request_id)
        if registered != authorization:
            raise BudgetError("authorization_conflict", "El mismo permiso no puede cambiar sus topes.", request_id)
        return authorization, key

    def _bind(self, request_id, key):
        self._request_grants[request_id] = key
        self._grant_requests[key].add(request_id)

    def _get(self, request_id: UUID) -> Usage:
        usage = self.db.get_usage(request_id)
        if usage is None:
            raise BudgetError("request_missing", "La solicitud no tiene una reserva registrada.", request_id)
        return usage

    def _snapshot(self, rows: list[Usage], campaign_id: UUID, company_id: UUID | None) -> BudgetSnapshot:
        campaign = self.db.get_campaign(campaign_id)
        if campaign is None:
            raise BudgetError("campaign_missing", "La campaña no existe.")
        limits = campaign.limits.budget
        accounts = []
        for allowance in self.account_allowances:
            matches = [row for row in rows if row.provider == allowance.provider
                       and row.account_ref in (None, allowance.account_ref)]
            accounts.append(AccountSnapshot(
                provider=allowance.provider, account_ref=allowance.account_ref,
                funding_source=allowance.funding_source,
                cost=_amount(matches, allowance.cost_limit_usd),
                credits=_amount(matches, allowance.credit_limit, credits=True),
            ))
        return BudgetSnapshot(
            global_budget=_amount(rows, min(self.global_limits.global_usd, limits.global_usd)),
            operating=_amount(rows, min(self.global_limits.operating_usd, limits.operating_usd)),
            campaign=_amount([row for row in rows if row.campaign_id == campaign_id], min(self.global_limits.campaign_usd, limits.campaign_usd)),
            company=None if company_id is None else _amount(
                [row for row in rows if row.company_id == company_id],
                min(self.global_limits.company_usd, limits.company_usd),
            ),
            accounts=accounts, reservation_overrun=any(_overrun(row) for row in rows),
            confirmed_cost_usd=None if any(row.status == UsageStatus.RECONCILED and row.final_cost_usd is None for row in rows)
            else _sum(row.final_cost_usd for row in rows if row.status == UsageStatus.RECONCILED),
            outlay_usd=None if any(row.outlay_usd is None for row in rows)
            else _sum(row.outlay_usd for row in rows),
            free_credit_equivalent=_amount(
                [row for row in rows if row.funding_source in (None, "free_credit")], None,
                credit_valuations={
                    (item.provider, item.account_ref): item.credit_valuation
                    for item in self.account_allowances if item.credit_valuation is not None
                },
            ),
        )

    def snapshot(self, campaign_id: UUID, company_id: UUID | None = None) -> BudgetSnapshot:
        """Muestra confirmado, estimado y reservas; desconocido nunca es cero."""
        with self.db.transaction():
            return self._snapshot(self.db.list_usage(), campaign_id, company_id)

    def _check(self, usage: Usage, authorization: SpendingAuthorization | None, rows: list[Usage]):
        authorization, key = self._registered_grant(authorization, usage.request_id)
        if (authorization.provider, authorization.operation, authorization.account_ref) != (usage.provider, usage.operation, usage.account_ref):
            raise BudgetError("authorization_mismatch", "La autorización corresponde a otro proveedor, operación o cuenta.", usage.request_id)
        if usage.created_at > utc_now():
            raise BudgetError("authorization_date", "La reserva no puede tener una fecha futura.", usage.request_id)
        previous = self._request_grants.get(usage.request_id)
        if previous is not None and previous != key:
            raise BudgetError("authorization_conflict", "La solicitud ya pertenece a otro permiso de esta sesión.", usage.request_id)
        account = next((item for item in self.account_allowances if
                        (item.provider, item.account_ref, item.funding_source) ==
                        (usage.provider, usage.account_ref, usage.funding_source)), None)
        if account is None:
            raise BudgetError("account_unconfigured", "La cuenta no tiene un cupo inicial comprobado.", usage.request_id)
        if any(row.provider == usage.provider and row.account_ref in (None, usage.account_ref)
               and (row.account_ref is None or row.funding_source is None) for row in rows):
            raise BudgetError("account_unknown", "Hay consumo sin cuenta u origen de financiación comprobados.", usage.request_id)
        state = self._snapshot(rows, usage.campaign_id, usage.company_id)
        if state.reservation_overrun:
            raise BudgetError("reservation_overrun", "Hay consumo superior a su reserva; se necesita revisión antes de gastar.", usage.request_id)
        bounds = [state.global_budget, state.operating, state.campaign]
        if state.company is not None:
            bounds.append(state.company)
        account_state = next(item for item in state.accounts if
                             (item.provider, item.account_ref, item.funding_source) ==
                             (usage.provider, usage.account_ref, usage.funding_source))
        bounds.append(account_state.cost)
        if usage.reserved_cost_usd > 0 and account.cost_limit_usd is None:
            raise BudgetError("account_cost_unknown", "El cupo económico de la cuenta no está acotado.", usage.request_id)
        if usage.reserved_credits > 0 and account.credit_limit is None:
            raise BudgetError("account_credits_unknown", "El cupo de créditos de la cuenta no está acotado.", usage.request_id)
        # Una operación explícitamente sin créditos no necesita conocer otra cuota.
        if account.credit_limit is not None or usage.reserved_credits > 0:
            bounds.append(account_state.credits)
        if any(bound.unknown for bound in bounds):
            raise BudgetError("budget_unknown", "Hay consumo o reservas sin acotar; concílialos antes de llamar.", usage.request_id)
        exceeded = [bound for bound in bounds if bound.exceeded]
        if exceeded and all(bound is state.company for bound in exceeded):
            # Solo el tope de la empresa: el resto de la campaña aún tiene presupuesto.
            raise BudgetError("company_budget_exceeded", "La reserva supera el tope de gasto de esta empresa.", usage.request_id)
        if exceeded:
            raise BudgetError("budget_exceeded", "La reserva supera el presupuesto o los créditos disponibles.", usage.request_id)
        request_ids = self._grant_requests[key] | {usage.request_id}
        authorized = [row for row in rows if row.request_id in request_ids]
        costs = _amount(authorized, authorization.max_cost_usd)
        credits = _amount(authorized, authorization.max_credits, credits=True)
        if costs.unknown or credits.unknown:
            raise BudgetError("authorization_unknown", "El consumo del permiso tiene importes desconocidos.", usage.request_id)
        if costs.exceeded or credits.exceeded:
            raise BudgetError("authorization_exceeded", "Las solicitudes acumulan más consumo que el permiso otorgado.", usage.request_id)
        return key

    def reserve(self, proposal: Usage, authorization: SpendingAuthorization | None, retry_of: UUID | None = None) -> Usage:
        proposal = Usage.model_validate_json(proposal.model_dump_json())
        if (proposal.status != UsageStatus.RESERVED or proposal.account_ref is None
                or proposal.funding_source is None or proposal.reserved_cost_usd is None
                or proposal.reserved_credits is None
                or any(getattr(proposal, name) is not None for name in (
                    "tokens", "credits", "estimated_cost_usd", "final_cost_usd", "outlay_usd",
                    "outcome", "error_message", "finished_at", "reconciled_at"))):
            raise BudgetError("invalid_reservation", "La propuesta debe contener una reserva nueva y completamente acotada.", proposal.request_id)
        if proposal.funding_source == "free_credit" and proposal.reserved_cost_usd != 0:
            raise BudgetError("invalid_funding", "El crédito gratuito confirmado debe reservar cero USD.", proposal.request_id)
        self._registered_grant(authorization, proposal.request_id)
        with self.db.transaction():
            rows = self.db.list_usage()
            existing = self.db.get_usage(proposal.request_id)
            if existing is not None:
                identity = ("campaign_id", "company_id", "provider", "operation", "account_ref",
                            "request_fingerprint", "reserved_cost_usd", "reserved_credits",
                            "reserved_tokens", "funding_source", "created_at")
                if any(getattr(existing, name) != getattr(proposal, name) for name in identity):
                    raise BudgetError("request_conflict", "El identificador ya representa otra solicitud o reserva.", proposal.request_id)
                if existing.status != UsageStatus.RESERVED:
                    return existing
                result = existing
                key = self._check(existing, authorization, rows)
            else:
                group = [row for row in rows if _context(row) == _context(proposal)]
                reserved = [row for row in group if row.status == UsageStatus.RESERVED]
                if len(reserved) == 1 and len(group) == 1 and retry_of is None:
                    result = reserved[0]
                    if any(getattr(result, name) != getattr(proposal, name) for name in
                           ("reserved_cost_usd", "reserved_credits", "reserved_tokens", "funding_source")):
                        raise BudgetError("request_conflict", "La solicitud duplicada tiene otra cota de consumo.", result.request_id)
                    key = self._check(result, authorization, rows)
                else:
                    if group:
                        if (retry_of is None or len(group) != 1 or group[0].request_id != retry_of
                                or group[0].status != UsageStatus.RECONCILED
                                or group[0].outcome != "failed" or retry_of not in self._retryable):
                            raise BudgetError("duplicate_request", "La huella ya tiene una solicitud; recupera o concilia antes de repetir.", group[-1].request_id)
                    elif retry_of is not None:
                        raise BudgetError("invalid_retry", "El reintento no corresponde a una solicitud previa del grupo.", proposal.request_id)
                    key = self._check(proposal, authorization, rows + [proposal])
                    result = self.db.save_usage(proposal)
        self._bind(result.request_id, key)
        return result

    def claim(self, request_id: UUID, expected_fingerprint: str, authorization: SpendingAuthorization | None) -> Usage:
        with self.db.transaction():
            usage = self._get(request_id)
            if usage.request_fingerprint != expected_fingerprint:
                raise BudgetError("fingerprint_mismatch", "La entrada no corresponde a la reserva.", request_id)
            if usage.status != UsageStatus.RESERVED:
                raise BudgetError("request_not_reserved", "La solicitud ya se envió, terminó o requiere conciliación.", request_id)
            if usage.reserved_cost_usd is None or usage.reserved_credits is None:
                raise BudgetError("invalid_reservation", "La reserva heredada no acota costo y créditos.", request_id)
            if usage.funding_source == "free_credit" and usage.reserved_cost_usd != 0:
                raise BudgetError("invalid_funding", "El crédito gratuito confirmado debe reservar cero USD.", request_id)
            rows = self.db.list_usage()
            others = [row for row in rows if row.request_id != request_id and _context(row) == _context(usage)]
            if any(row.status != UsageStatus.RECONCILED or row.outcome != "failed" for row in others):
                raise BudgetError("duplicate_request", "Otra solicitud del grupo impide un envío duplicado.", request_id)
            if len(others) > 1 or any(row.request_id not in self._retryable for row in others):
                raise BudgetError("invalid_retry", "El segundo intento necesita un fallo transitorio comprobado en esta ejecución.", request_id)
            key = self._check(usage, authorization, rows)
            result = self.db.save_usage(usage.model_copy(update={"status": UsageStatus.IN_FLIGHT}))
        self._bind(request_id, key)
        self._claimed_unsent.add(request_id)
        return result

    def begin_send(self, request_id: UUID, *, deadline: float | None = None) -> None:
        """Consume la prueba de no envío inmediatamente antes del transporte."""
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
            raise BudgetError("invalid_deadline", "El plazo del transporte debe ser finito.", request_id)
        with self.db.transaction():
            usage = self._get(request_id)
            if usage.status != UsageStatus.IN_FLIGHT or request_id not in self._claimed_unsent:
                raise BudgetError("send_not_claimed", "El transporte necesita una reclamación no usada de esta sesión.", request_id)
            self._check(usage, self._grants[self._request_grants[request_id]], self.db.list_usage())
        if deadline is not None and time.monotonic() >= deadline:
            raise BudgetError("deadline_unsent", "El plazo venció sin iniciar el transporte.", request_id)
        self._claimed_unsent.remove(request_id)

    def record_result(self, request_id: UUID, observation: Observation, *, no_send: bool = False) -> Usage:
        observation = Observation.model_validate_json(observation.model_dump_json())
        if type(no_send) is not bool:
            raise BudgetError("invalid_no_send", "La prueba de no envío requiere un booleano explícito.", request_id)
        with self.db.transaction():
            usage = self._get(request_id)
            if no_send:
                if (request_id not in self._claimed_unsent or usage.status != UsageStatus.IN_FLIGHT
                        or observation.outcome != "failed" or usage.outcome is not None
                        or any(getattr(usage, name) is not None for name in (
                            "tokens", "credits", "estimated_cost_usd", "final_cost_usd", "outlay_usd", "error_message"))
                        or observation.credits not in (None, 0)
                        or observation.estimated_cost_usd not in (None, 0)
                        or observation.tokens is not None and any(observation.tokens.model_dump().values())):
                    raise BudgetError("invalid_no_send", "No hay prueba local de una operación sin transporte ni consumo.", request_id)
                observation = observation.model_copy(update={
                    "credits": Decimal(0), "estimated_cost_usd": Decimal(0),
                    "tokens": None if usage.reserved_tokens is None else TokenUsage(**{
                        name: 0 for name in TokenUsage.model_fields
                    }),
                })
            if usage.status in (UsageStatus.RESERVED, UsageStatus.RECONCILED):
                raise BudgetError("invalid_state", "La solicitud no admite observaciones en su estado actual.", request_id)
            if usage.outcome not in (None, "unknown", observation.outcome):
                raise BudgetError("outcome_conflict", "No se puede sustituir un resultado confirmado.", request_id)
            if observation.observed_at < usage.created_at:
                raise BudgetError("observation_date", "La observación es anterior a la solicitud.", request_id)
            updates = {"tokens": _tokens(usage.tokens, observation.tokens)}
            for name in ("credits", "error_message"):
                value = getattr(observation, name)
                old = getattr(usage, name)
                if value is not None and old is not None and old != value:
                    raise BudgetError("usage_conflict", "El consumo o fallo registrado no se puede sustituir.", request_id)
                updates[name] = old if value is None else value
            if observation.estimated_cost_usd is not None:
                updates["estimated_cost_usd"] = observation.estimated_cost_usd
            updates.update(
                outcome=observation.outcome,
                status={"succeeded": UsageStatus.SUCCEEDED, "failed": UsageStatus.FAILED,
                        "unknown": UsageStatus.UNCERTAIN}[observation.outcome],
                finished_at=usage.finished_at or observation.observed_at,
            )
            result = self.db.save_usage(usage.model_copy(update=updates))
        self._claimed_unsent.discard(request_id)
        if no_send:
            self._proved_unsent.add(request_id)
        if observation.outcome == "failed" and observation.retryable:
            self._retryable.add(request_id)
        return result

    def reconcile(self, request_id: UUID, confirmation: Confirmation) -> Usage:
        confirmation = Confirmation.model_validate_json(confirmation.model_dump_json())
        with self.db.transaction():
            usage = self._get(request_id)
            if confirmation.observed_at < usage.created_at:
                raise BudgetError("confirmation_date", "La confirmación es anterior a la solicitud.", request_id)
            if confirmation.no_send:
                unsent = usage.status in (UsageStatus.RESERVED, UsageStatus.RECONCILED) or (
                    usage.status == UsageStatus.FAILED and request_id in self._proved_unsent
                )
                if (not unsent
                        or confirmation.outcome != "failed"
                        or any((confirmation.final_cost_usd, confirmation.credits, confirmation.outlay_usd))
                        or confirmation.tokens is not None and any(confirmation.tokens.model_dump().values())):
                    raise BudgetError("invalid_no_send", "Solo una reserva no enviada se cancela sin consumo.", request_id)
            elif usage.status == UsageStatus.RESERVED:
                raise BudgetError("invalid_state", "Una reserva no enviada necesita confirmación explícita de no envío.", request_id)
            if usage.outcome not in (None, "unknown", confirmation.outcome):
                raise BudgetError("outcome_conflict", "La conciliación contradice el resultado conocido.", request_id)
            tokens = _tokens(usage.tokens, confirmation.tokens)
            values = {"final_cost_usd": confirmation.final_cost_usd,
                      "credits": confirmation.credits, "outlay_usd": confirmation.outlay_usd}
            for name, value in values.items():
                if getattr(usage, name) is not None and getattr(usage, name) != value:
                    raise BudgetError("reconciliation_conflict", "La confirmación contradice un consumo ya registrado.", request_id)
            if usage.status == UsageStatus.RECONCILED:
                if usage.outcome != confirmation.outcome or usage.tokens != tokens:
                    raise BudgetError("reconciliation_conflict", "La conciliación confirmada es inmutable.", request_id)
                return usage
            return self.db.save_usage(usage.model_copy(update=values | {
                "tokens": tokens, "outcome": confirmation.outcome,
                "status": UsageStatus.RECONCILED,
                "finished_at": usage.finished_at or confirmation.observed_at,
                "reconciled_at": confirmation.observed_at,
            }))
