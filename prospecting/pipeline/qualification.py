"""Calificación con Haiku: Python valida, puntúa y decide la prioridad."""

import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Literal
from uuid import UUID, uuid4

from pydantic import StrictBool

from prospecting.budget import Budget, BudgetError, SpendingAuthorization
from prospecting.db import Database
from prospecting.models import (
    Assessment, BusinessStatus, Contract, Money, Priority, RunItem, RunStage, Text, TokenUsage, utc_now,
)
from prospecting.pipeline.calls import reserve_claude, seconds_left, was_sent
from prospecting.providers import ClaudeClient, ProviderError
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
_EVALUATION_DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


class _EvaluationTrace:
    """Artefactos locales exclusivos; nunca sustituye un checkpoint ni modifica la solicitud."""

    def __init__(self, directory: Path):
        directory = Path(directory).resolve()
        if not directory.is_relative_to(_EVALUATION_DATA_ROOT.resolve()):
            raise ValueError("Las trazas deben guardarse bajo data/ de este repositorio.")
        self.id = uuid4()
        self.path = directory / str(self.id)
        self.path.mkdir(parents=True, exist_ok=False)
        self.hashes = {}

    def write(self, name: str, value: dict) -> None:
        content = (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        with (self.path / name).open("xb") as target:
            target.write(content)
        self.hashes[name] = hashlib.sha256(content).hexdigest()


def _code_snapshot() -> tuple[str | None, dict[str, str]]:
    root = Path(__file__).resolve().parents[2]
    paths = ("prospecting/qualification.py", "prospecting/haiku.py", "prospecting/models.py",
             "prospecting/pipeline/qualification.py", "prospecting/pipeline/calls.py",
             "prospecting/providers/claude.py", "prospecting/budget.py")
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths}
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                                text=True, timeout=2, check=True)
        commit = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    return commit, hashes


def _expanded_evidence(assessment: Assessment, evidence) -> set[UUID]:
    """Evidencia de empresa posterior a una evaluación insuficiente: la ampliación de §7 permite recalificar."""
    if assessment.priority != Priority.INSUFFICIENT_EVIDENCE:
        return set()
    return {item.id for item in evidence if item.contact_id is None and item.source_type != "manual"
            and item.retrieved_at > assessment.created_at}


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
                    deadline: float | None = None,
                    evaluation_dir: Path | None = None) -> QualificationReport:
    """Haiku evalúa criterios con evidencia guardada; Python valida, puntúa y decide la prioridad.

    Sin identidad confirmada o con exclusión no se consulta a Haiku. Un fallo deja la
    evaluación pendiente con su motivo literal, sin reintentar ni cambiar de modelo (§12.2).
    `insufficient_evidence` no se fija como resultado comercial: queda una ampliación (§7).
    Solo una evaluación insuficiente se repite, y solo si hay evidencia de empresa posterior
    que entre en la solicitud; las demás se reutilizan. `evaluation_dir` conserva una
    traza prospectiva bajo data/, sin reconstruir respuestas ni latencias anteriores.
    """
    started = time.monotonic() if evaluation_dir is not None else None
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
    evidence = db.list_evidence(company_id)
    fresh = set() if not modeled else _expanded_evidence(modeled[-1], evidence)
    trace = None
    capture_errors = []

    def capture_input(payload=None, selected=()):
        nonlocal trace
        if evaluation_dir is None:
            return True
        try:
            trace = _EvaluationTrace(evaluation_dir)
            commit, hashes = _code_snapshot()
            trace.write("input.json", {
                "schema_version": "evaluation_trace_v1", "trace_id": str(trace.id),
                "origin": "new_real" if payload is not None else "saved_real",
                "captured_at": utc_now().isoformat(), "campaign": campaign.model_dump(mode="json"),
                "company": company.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in evidence if item.contact_id is None],
                "selected_evidence_ids": [str(item.id) for item in selected], "request_payload": payload,
                "prompt_version": PROMPT_VERSION if payload is not None else None,
                "requested_model_id": None if payload is None else payload["model"],
                "rubric_version": campaign.rubric_version,
                "catalog_version": campaign.config_snapshot.catalog.version,
                "commit": commit, "code_hashes": hashes,
            })
            return True
        except (OSError, ValueError) as error:
            capture_errors.append(f"No se pudo guardar la entrada de evaluación ({type(error).__name__}).")
            return False

    def capture(name, value):
        if trace is None:
            return True
        try:
            trace.write(name, value)
            return True
        except (OSError, ValueError) as error:
            capture_errors.append(f"No se pudo guardar {name} ({type(error).__name__}).")
            return False

    def with_trace_error(report):
        if not capture_errors:
            return report
        message = "Traza de evaluación incompleta: " + " ".join(capture_errors)
        previous_message = (report.error_message or "").split("Traza de evaluación incompleta:", 1)[0].strip()
        if previous_message and previous_message not in message:
            message = previous_message + " " + message
        updated = db.get_run_item(campaign_id, company_id)
        if updated.error_message != message:
            db.save_run_item(updated.model_copy(update={
                "error_message": message, "error_stage": RunStage.ASSESSED, "updated_at": utc_now(),
            }))
        return report.model_copy(update={"error_message": message})

    def finish(report):
        if evaluation_dir is None:
            return report
        if trace is None and not capture_errors:
            capture_input()
        report = with_trace_error(report)
        if trace is not None:
            assessment = None if report.assessment_id is None else db.get_assessment(report.assessment_id)
            usage = None if report.request_id is None else budget.db.get_usage(report.request_id)
            capture("result.json", {
                "assessment": None if assessment is None else assessment.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
                "usage": None if usage is None else usage.model_dump(mode="json"),
                "called_model": report.called_model,
                "duration_seconds": time.monotonic() - started if report.called_model else None,
            })
            capture("manifest.json", {
                "schema_version": "evaluation_trace_v1", "trace_id": str(trace.id),
                "artifacts": dict(trace.hashes), "complete": not capture_errors,
                "capture_errors": list(capture_errors),
            })
        return with_trace_error(report) if capture_errors else report

    def reuse():
        return finish(QualificationReport(**base, status="already_assessed", assessment_id=modeled[-1].id,
                                   priority=modeled[-1].priority, fit_score=modeled[-1].fit_score,
                                   coverage=modeled[-1].coverage))

    if modeled and not fresh:
        return reuse()

    def pending(reason, message, **extra):
        db.save_run_item(run_item.model_copy(update={
            "stop_reason": f"assessment_pending:{reason}", "error_message": message,
            "error_stage": RunStage.ASSESSED, "updated_at": utc_now(),
        }))
        return finish(QualificationReport(**base, status="pending", reason=reason, error_message=message, **extra))

    def without_model(priority, reason, explanation, stop_reason):
        if latest is not None and latest.model_id is None and latest.priority == priority:
            return finish(QualificationReport(**base, status="already_assessed", assessment_id=latest.id,
                                       priority=priority, coverage=latest.coverage, reason=reason))
        assessment = _store_assessment(db, run_item, Assessment(
            **base, criteria=unknown_criteria(explanation), fit_score=None, coverage=0.0,
            priority=priority, rubric_version=campaign.rubric_version, explanation=explanation,
            revision_of=None if latest is None else latest.id,
        ), stop_reason=stop_reason)
        return finish(QualificationReport(**base, status="assessed", assessment_id=assessment.id,
                                   priority=priority, coverage=0.0, reason=reason))

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
    try:
        payload, selected = build_haiku_request(company, evidence, campaign)
    except QualificationError as error:
        return pending(error.code, error.message)
    if fresh and not fresh & {item.id for item in selected}:
        # La evidencia nueva no cabe en la solicitud: repetirla no aportaría nada a Haiku.
        return reuse()
    if not selected:
        return without_model(Priority.INSUFFICIENT_EVIDENCE, "no_evidence",
                             "No hay evidencia utilizable de la empresa; no se consultó a Haiku.",
                             "insufficient_evidence:no_evidence")
    remaining = seconds_left(deadline)
    if remaining is not None and remaining <= 0:
        return pending("time_limit", "Se agotó el tiempo de la etapa antes de llamar.")
    if not capture_input(payload, selected):
        return pending("trace_capture_failed", capture_errors[-1])
    if evaluation_dir is not None:
        remaining = seconds_left(deadline)
        if remaining is not None and remaining <= 0:
            return pending("time_limit", "Se agotó el tiempo de la etapa durante la captura, antes de reservar.")
    try:
        usage = reserve_claude(budget, claude.fingerprint(payload, account_ref), payload, account_ref=account_ref,
                               funding_source=funding_source, authorization=authorization, **base)
        if not capture("request.json", {"request_id": str(usage.request_id),
                                        "request_fingerprint": usage.request_fingerprint}):
            return pending("trace_capture_failed", capture_errors[-1] +
                           " La reserva se conserva sin envío para conciliación.", request_id=usage.request_id)
        if evaluation_dir is not None:
            remaining = seconds_left(deadline)
            if remaining is not None and remaining <= 0:
                return pending("time_limit", "Se agotó el tiempo de la etapa durante la captura; "
                               "la reserva se conserva sin envío para conciliación.", request_id=usage.request_id)
        call = claude.create(usage.request_id, payload, account_ref=account_ref,
                             authorization=authorization, remaining_seconds=remaining)
    except BudgetError as error:
        return pending(error.code, str(error), request_id=error.request_id)
    except ProviderError as error:
        reason = f"http_{error.http_status}" if error.kind == "http" else error.kind
        return pending(reason, error.message, request_id=error.request_id,
                       called_model=was_sent(budget, error))
    spent = {"called_model": True, "request_id": call.request_id, "tokens": call.tokens,
             "estimated_cost_usd": call.estimated_cost_usd}
    capture("response.json", call.model_dump(mode="json"))
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
    return finish(QualificationReport(**base, status="assessed", assessment_id=assessment.id,
                               priority=result.priority, fit_score=result.fit_score,
                               coverage=result.coverage, reason=result.reason, **spent))
