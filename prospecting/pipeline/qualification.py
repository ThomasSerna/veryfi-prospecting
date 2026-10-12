"""Calificación con Haiku: Python valida, puntúa y decide la prioridad."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import StrictBool

from prospecting.budget import Budget, BudgetError, SpendingAuthorization
from prospecting.db import Database
from prospecting.haiku import MODEL_ID
from prospecting.models import (
    Assessment, BusinessStatus, Contract, Money, Priority, RunItem, RunStage, Text, TokenUsage, Usage,
    UsageStatus, utc_now,
)
from prospecting.pipeline.calls import seconds_left
from prospecting.providers import CLAUDE_OPERATION, CLAUDE_PROVIDER, ClaudeClient, ProviderError, reservation_cost
from prospecting.qualification import (
    PROMPT_VERSION, QualificationError, build_haiku_request, classify, explanation_text,
    identity_confirmed, material_contradiction, parse_output, primary_support, rubric_for,
    unknown_criteria, validate_output,
)


class QualificationReport(Contract):
    campaign_id: UUID
    company_id: UUID
    status: Literal["assessed", "already_assessed", "pending"]
    assessment_id: UUID | None = None
    priority: Priority | None = None
    fit_score: float | None = None
    coverage: float | None = None
    reason: Text | None = None
    called_model: StrictBool = False
    request_id: UUID | None = None
    tokens: TokenUsage | None = None
    estimated_cost_usd: Money | None = None
    error_message: Text | None = None


_FINAL_STATUS = {Priority.LOW: BusinessStatus.LOW_FIT}


def _store_assessment(db: Database, run_item: RunItem, assessment: Assessment, *, stop_reason) -> Assessment:
    stages = list(RunStage)
    stage = max(run_item.stage, RunStage.ASSESSED, key=stages.index)
    update = {"stage": stage, "last_assessment_id": assessment.id, "stop_reason": stop_reason,
              "error_message": None, "error_stage": None, "updated_at": utc_now()}
    if assessment.priority in _FINAL_STATUS:
        update["business_status"] = _FINAL_STATUS[assessment.priority]
    with db.transaction():
        saved = db.save_assessment(assessment)
        db.save_run_item(run_item.model_copy(update=update))
    return saved


def qualify_company(db: Database, budget: Budget, claude: ClaudeClient, campaign_id: UUID,
                    company_id: UUID, *, account_ref: str,
                    funding_source: Literal["free_credit", "prepaid", "new_outlay"],
                    authorization: SpendingAuthorization | None,
                    deadline: float | None = None) -> QualificationReport:
    """Haiku evalúa criterios con evidencia guardada; Python valida, puntúa y decide la prioridad.

    Sin identidad confirmada o con exclusión no se consulta a Haiku. Un fallo deja la
    evaluación pendiente con su motivo literal, sin reintentar ni cambiar de modelo (§12.2).
    `insufficient_evidence` no se fija como resultado comercial: queda una ampliación (§7).
    """
    campaign = db.get_campaign(campaign_id)
    run_item = db.get_run_item(campaign_id, company_id)
    company = db.get_company(company_id)
    if campaign is None or run_item is None or company is None:
        raise ValueError("La empresa no pertenece a la campaña.")
    base = {"campaign_id": campaign_id, "company_id": company_id}
    previous = [item for item in db.list_assessments(campaign_id, company_id)
                if item.rubric_version == campaign.rubric_version]
    latest = previous[-1] if previous else None
    modeled = [item for item in previous if item.prompt_version == PROMPT_VERSION]
    if modeled:
        return QualificationReport(**base, status="already_assessed", assessment_id=modeled[-1].id,
                                   priority=modeled[-1].priority, fit_score=modeled[-1].fit_score,
                                   coverage=modeled[-1].coverage)

    def pending(reason, message, **extra):
        db.save_run_item(run_item.model_copy(update={
            "stop_reason": f"assessment_pending:{reason}", "error_message": message,
            "error_stage": RunStage.ASSESSED, "updated_at": utc_now(),
        }))
        return QualificationReport(**base, status="pending", reason=reason, error_message=message, **extra)

    def without_model(priority, reason, explanation, stop_reason):
        if latest is not None and latest.model_id is None and latest.priority == priority:
            return QualificationReport(**base, status="already_assessed", assessment_id=latest.id,
                                       priority=priority, coverage=latest.coverage, reason=reason)
        assessment = _store_assessment(db, run_item, Assessment(
            **base, criteria=unknown_criteria(explanation), fit_score=None, coverage=0.0,
            priority=priority, rubric_version=campaign.rubric_version, explanation=explanation,
            revision_of=None if latest is None else latest.id,
        ), stop_reason=stop_reason)
        return QualificationReport(**base, status="assessed", assessment_id=assessment.id,
                                   priority=priority, coverage=0.0, reason=reason)

    if run_item.business_status == BusinessStatus.EXCLUDED:
        return without_model(Priority.EXCLUDED, "confirmed_exclusion",
                             "Exclusión confirmada antes de investigar; no se consultó a Haiku.",
                             run_item.stop_reason)
    if not identity_confirmed(company):
        return without_model(
            Priority.INSUFFICIENT_EVIDENCE, "identity_unconfirmed",
            f"Identidad no confirmada ({run_item.stop_reason or 'pendiente'}); no se consultó a Haiku.",
            "insufficient_evidence:identity_unconfirmed",
        )
    evidence = db.list_evidence(company_id)
    try:
        payload, selected = build_haiku_request(company, evidence, campaign)
    except QualificationError as error:
        return pending(error.code, error.message)
    if not selected:
        return without_model(Priority.INSUFFICIENT_EVIDENCE, "no_evidence",
                             "No hay evidencia utilizable de la empresa; no se consultó a Haiku.",
                             "insufficient_evidence:no_evidence")
    remaining = seconds_left(deadline)
    if remaining is not None and remaining <= 0:
        return pending("time_limit", "Se agotó el tiempo de la etapa antes de llamar.")
    limits = campaign.limits.llm
    try:
        usage = budget.reserve(Usage(
            **base, provider=CLAUDE_PROVIDER, operation=CLAUDE_OPERATION, account_ref=account_ref,
            request_fingerprint=claude.fingerprint(payload, account_ref),
            reserved_cost_usd=reservation_cost(MODEL_ID, limits.max_input_tokens, limits.max_output_tokens),
            reserved_credits=Decimal(0),
            reserved_tokens=TokenUsage(input_tokens=limits.max_input_tokens, output_tokens=limits.max_output_tokens),
            funding_source=funding_source, status=UsageStatus.RESERVED,
        ), authorization)
        call = claude.create(usage.request_id, payload, account_ref=account_ref,
                             authorization=authorization, remaining_seconds=remaining)
    except BudgetError as error:
        return pending(error.code, str(error), request_id=error.request_id)
    except ProviderError as error:
        reason = f"http_{error.http_status}" if error.kind == "http" else error.kind
        return pending(reason, error.message, request_id=error.request_id, called_model=not error.no_send)
    spent = {"called_model": True, "request_id": call.request_id, "tokens": call.tokens,
             "estimated_cost_usd": call.estimated_cost_usd}
    try:
        output = parse_output(call.text, call.stop_reason)
        criteria = validate_output(output, selected, campaign)
    except QualificationError as error:
        return pending(error.code, error.message, **spent)
    result = classify(
        criteria, rubric_for(campaign), excluded=False, identity_confirmed=True,
        contradiction=material_contradiction(output, criteria, selected),
        primary_support=primary_support(criteria, selected),
    )
    assessment = _store_assessment(db, run_item, Assessment(
        **base, criteria=criteria, fit_score=result.fit_score, coverage=result.coverage,
        priority=result.priority, products=list(dict.fromkeys(output.products)),
        target_roles=list(dict.fromkeys(output.target_roles)), model_id=call.model,
        prompt_version=PROMPT_VERSION, rubric_version=campaign.rubric_version,
        explanation=explanation_text(output), revision_of=None if latest is None else latest.id,
    ), stop_reason={
        Priority.LOW: "low_fit", Priority.INSUFFICIENT_EVIDENCE: f"insufficient_evidence:{result.reason}",
    }.get(result.priority))
    return QualificationReport(**base, status="assessed", assessment_id=assessment.id,
                               priority=result.priority, fit_score=result.fit_score,
                               coverage=result.coverage, reason=result.reason, **spent)
