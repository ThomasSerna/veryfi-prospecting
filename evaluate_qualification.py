"""Evaluación offline de T10: instantáneas congeladas, revisión atribuida y métricas reproducibles.

No abre bases ni llama proveedores. Un replay valida una respuesta ya guardada;
una rúbrica candidata solo recalcula pesos/umbrales, nunca prueba otro prompt.
"""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from typing import Annotated, Literal
import unicodedata
from uuid import UUID

from pydantic import Field, StrictBool, StringConstraints, ValidationError, model_validator

from prospecting.models import (
    Assessment, Campaign, Company, Contract, CountryCode, Criterion, CriterionName,
    CriterionValue, Evidence, Money, ReferenceIds, Rubric, Segment, Text, TokenUsage,
    Priority, Usage, UtcDatetime,
)
from prospecting.qualification import (
    classify, compute_score, identity_confirmed, material_contradiction, parse_output, primary_support,
    QualificationError, allowed_roles, rubric_for, validate_output,
    SEARCH_RESULT_CLAIM,
)
from prospecting.sources import is_search_hit
from prospecting.text import clip

Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
CaseId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$")]
Duration = Annotated[float, Field(ge=0, allow_inf_nan=False)]
DATA_ROOT = Path(__file__).resolve().parent / "data"


class FileReference(Contract):
    path: Text
    sha256: Digest


class Inventory(Contract):
    status: Literal["pending", "verified"]
    historical_coverage: Literal["pending", "verified"]
    reference: Text
    historical_group_keys: list[Text] = Field(default_factory=list)


class EvaluationCase(Contract):
    case_id: CaseId
    split: Literal["development", "evaluation"]
    origin: Literal["synthetic", "saved_real", "new_real"]
    country: CountryCode
    segment: Segment
    group_keys: list[Text]
    artifact: FileReference
    label: FileReference | None = None


class EvaluationManifest(Contract):
    schema_version: Literal["evaluation_manifest_v1"]
    dataset_version: Text
    created_at: UtcDatetime
    inventory: Inventory
    cases: Annotated[list[EvaluationCase], Field(min_length=1)]


class Snapshot(Contract):
    schema_version: Literal["evaluation_snapshot_v1"]
    origin: Literal["synthetic", "saved_real"]
    campaign: Campaign
    company: Company
    evidence: list[Evidence]
    assessment: Assessment | None = None
    error_reason: Text | None = None
    selected_evidence_ids: ReferenceIds | None = None
    flow_cost_usd: Money | None = None
    duration_seconds: Duration | None = None


class ReviewedCriterion(Contract):
    status: Literal["resolved", "pending"]
    value: CriterionValue
    evidence_ids: ReferenceIds = Field(default_factory=list)
    reason: Text

    @model_validator(mode="after")
    def check_value(self):
        if self.status == "pending" and (self.value is not None or self.evidence_ids):
            raise ValueError("Un criterio pendiente no tiene un valor ni respaldo decidido.")
        if self.status == "resolved" and self.value is not None and not self.evidence_ids:
            raise ValueError("Un valor conocido revisado necesita evidencia.")
        return self


class ClaimAudit(Contract):
    claim_reference: Text
    evidence_ids: ReferenceIds
    supported: StrictBool | None
    reason: Text


class EvaluationLabel(Contract):
    schema_version: Literal["evaluation_label_v1"]
    label_id: Text
    version: Text
    previous_sha256: Digest | None = None
    case_id: CaseId
    snapshot_sha256: Digest
    assessment_id: UUID | None = None
    reference_type: Literal["Veryfi", "academic"]
    reviewer: Text
    role: Text
    organization: Text
    review_reference: Text
    reviewed_at: UtcDatetime
    reason: Text
    acceptance: Literal["accepted", "rejected", "pending"]
    prediction_visible: StrictBool = True
    criteria: dict[CriterionName, ReviewedCriterion] = Field(default_factory=dict)
    products_status: Literal["resolved", "pending"] = "pending"
    products: list[Text] = Field(default_factory=list)
    audits: list[ClaimAudit] = Field(default_factory=list)


class TraceManifest(Contract):
    schema_version: Literal["evaluation_trace_v1"]
    trace_id: Text
    artifacts: dict[Text, Digest]
    complete: StrictBool
    capture_errors: list[Text]


class TraceInput(Contract):
    schema_version: Literal["evaluation_trace_v1"]
    trace_id: Text
    campaign: Campaign
    company: Company
    evidence: list[Evidence]
    selected_evidence_ids: ReferenceIds
    request_payload: dict | None
    prompt_version: Text | None
    requested_model_id: Text | None
    rubric_version: Text
    catalog_version: Text
    commit: Text | None
    code_hashes: dict[Text, Digest]
    captured_at: UtcDatetime
    origin: Literal["synthetic", "saved_real", "new_real"]


class RecordedResponse(Contract):
    request_id: UUID
    model: Text
    provider_message_id: Text | None = None
    stop_reason: Text | None = None
    text: str
    tokens: TokenUsage
    estimated_cost_usd: Money | None = None


class SubmittedEvidence(Contract):
    evidence_id: UUID
    source_type: Text
    kind: Text
    url: Text | None
    provider: Text | None
    retrieved_at: Text
    published_at: Text | None
    claim: Text | None
    excerpt: Text | None


class RecordedReport(Contract):
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


class TraceResult(Contract):
    assessment: Assessment | None
    report: RecordedReport
    usage: Usage | None
    duration_seconds: Duration | None
    called_model: StrictBool


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("JSON no finito.")))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def checked_file(root, reference):
    relative = Path(reference.path)
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise ValueError("La referencia sale del directorio del conjunto.")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("La referencia sale del directorio del conjunto.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != reference.sha256:
        raise ValueError("El hash de un artefacto no coincide.")
    return path


def submitted_evidence(source):
    """Comprueba el bloque archivado; no reconstruye prompts con instrucciones actuales."""
    messages = source.request_payload.get("messages")
    if (not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict)
            or messages[0].get("role") != "user" or not isinstance(messages[0].get("content"), str)):
        return None
    content = messages[0]["content"]
    if content.count("<evidencia>") != 1 or content.count("</evidencia>") != 1:
        return None
    block = content.split("<evidencia>", 1)[1].split("</evidencia>", 1)[0]
    try:
        sent = [SubmittedEvidence.model_validate(json.loads(line)) for line in block.splitlines() if line.strip()]
    except ValueError:
        raise ValueError("El bloque de evidencia enviado no cumple el contrato archivado.") from None
    ids = [item.evidence_id for item in sent]
    if len(ids) != len(set(ids)) or set(ids) != set(source.selected_evidence_ids):
        raise ValueError("La evidencia declarada no coincide con la enviada.")
    facts = {item.id: item for item in source.evidence}
    for item in sent:
        fact = facts.get(item.evidence_id)
        if fact is None:
            raise ValueError("La evidencia enviada no existe en la instantánea.")
        search = is_search_hit(fact)
        expected = {"source_type": str(fact.source_type), "kind": "search_result" if search else str(fact.kind),
                    "url": None if fact.url is None else str(fact.url), "provider": fact.provider,
                    "retrieved_at": fact.retrieved_at.date().isoformat(),
                    "published_at": None if fact.published_at is None else fact.published_at.date().isoformat()}
        if any(getattr(item, name) != value for name, value in expected.items()):
            raise ValueError("La procedencia enviada no coincide con la instantánea.")
        for name, full in (("claim", SEARCH_RESULT_CLAIM if search else fact.claim), ("excerpt", fact.excerpt)):
            fragment = getattr(item, name)
            if clip(full, max(1, len(fragment) if fragment else len(full or ""))) != fragment:
                raise ValueError("El fragmento enviado no corresponde a la evidencia archivada.")
    return ids


def load_snapshot(root, case):
    path = checked_file(root, case.artifact)
    data = read_json(path)
    if data.get("schema_version") == "evaluation_snapshot_v1":
        snapshot = Snapshot.model_validate(data)
        if snapshot.origin != case.origin:
            raise ValueError("El origen declarado no coincide con la instantánea.")
        return snapshot, None, "audit_only", None, {}
    trace = TraceManifest.model_validate(data)
    artifacts = {name: read_json(checked_file(path.parent, FileReference(path=name, sha256=sha)))
                 for name, sha in trace.artifacts.items()}
    source = TraceInput.model_validate(artifacts["input.json"])
    submitted = None if source.request_payload is None else submitted_evidence(source)
    if source.origin != case.origin or source.trace_id != trace.trace_id:
        raise ValueError("El origen o identificador de la traza no coincide.")
    if (source.rubric_version != source.campaign.rubric_version
            or source.catalog_version != source.campaign.config_snapshot.catalog.version
            or source.request_payload is not None and source.request_payload.get("model") != source.requested_model_id):
        raise ValueError("Las versiones de la entrada no coinciden.")
    result = None if "result.json" not in artifacts else TraceResult.model_validate(artifacts["result.json"])
    assessment, usage, report = (None, None, None) if result is None else (result.assessment, result.usage, result.report)
    response = None if "response.json" not in artifacts else RecordedResponse.model_validate(artifacts["response.json"])
    if trace.complete and result is None or response is not None and usage is None:
        raise ValueError("La traza completa necesita resultado y la respuesta necesita consumo registrado.")
    if report is not None and (report.company_id != source.company.id or report.campaign_id != source.campaign.id
            or report.assessment_id != (None if assessment is None else assessment.id)
            or report.priority != (None if assessment is None else assessment.priority)
            or result.called_model != report.called_model
            or assessment is not None and (report.fit_score != assessment.fit_score or report.coverage != assessment.coverage)):
        raise ValueError("El informe no corresponde al caso/evaluación capturado.")
    if usage is not None:
        request = artifacts.get("request.json")
        expected = digest({"provider": "anthropic", "operation": "messages",
                           "account_ref": usage.account_ref, "payload": source.request_payload})
        missing_before_send = request is None and not trace.complete and response is None and report is not None and not report.called_model and usage.status == "reserved"
        if (usage.campaign_id != source.campaign.id or usage.company_id != source.company.id
                or usage.provider != "anthropic" or usage.operation != "messages"
                or usage.request_fingerprint != expected
                or not missing_before_send and (request is None or request.get("request_id") != str(usage.request_id) or request.get("request_fingerprint") != expected)
                or report is not None and report.request_id != usage.request_id
                or report is not None and report.called_model and (report.tokens != usage.tokens or report.estimated_cost_usd != usage.estimated_cost_usd)
                or response is not None and (response.request_id != usage.request_id or not result.called_model or response.tokens != usage.tokens
                                             or response.estimated_cost_usd != usage.estimated_cost_usd)):
            raise ValueError("La solicitud, la respuesta y el consumo no están vinculados.")
    if assessment is not None and source.request_payload is not None and (assessment.prompt_version != source.prompt_version
            or response is not None and assessment.model_id != response.model):
        raise ValueError("La evaluación no corresponde al modelo/prompt capturado.")
    snapshot = Snapshot(schema_version="evaluation_snapshot_v1", origin="synthetic" if case.origin == "synthetic" else "saved_real",
                        campaign=source.campaign, company=source.company, evidence=source.evidence,
                        assessment=assessment, selected_evidence_ids=submitted,
                        error_reason=report.reason if report is not None and report.status == "pending" else None,
                        duration_seconds=None if result is None else result.duration_seconds)
    mode = "replay" if response else "audit_only" if source.request_payload is None else "trace_without_response"
    if source.request_payload is not None and submitted is None:
        mode = "audit_only"
    if not trace.complete or trace.capture_errors:
        snapshot.error_reason = "capture_incomplete"
        mode = "incomplete_trace"
    metadata = {"model_id": response.model if response else (None if assessment is None else assessment.model_id),
                "requested_model_id": source.requested_model_id,
                "prompt_version": source.prompt_version, "capture_commit": source.commit,
                "capture_code_hashes": source.code_hashes,
                "submitted_evidence_verified": submitted is not None,
                "submitted_messages": None if source.request_payload is None else source.request_payload.get("messages"),
                "request_payload_sha256": None if source.request_payload is None else digest(source.request_payload)}
    return snapshot, response, mode, usage, metadata


def validate_snapshot(snapshot, case, label):
    company, campaign, facts = snapshot.company, snapshot.campaign, snapshot.evidence
    for model, required in [(company, {"id"}), (campaign, {"id", "created_at", "updated_at"}),
                            *((fact, {"id", "retrieved_at"}) for fact in facts)]:
        if not required <= model.model_fields_set:
            raise ValueError("Una instantánea necesita identificadores y fechas explícitos.")
    ids = {fact.id for fact in facts}
    if len(ids) != len(facts) or any(fact.company_id != company.id or fact.contact_id is not None for fact in facts):
        raise ValueError("La evidencia está duplicada o pertenece a otra entidad/persona.")
    references = [ref for values in company.provenance.values() for ref in values]
    if company.size is not None:
        references += company.size.evidence_ids
    references += [ref for fact in facts for ref in fact.contradiction_ids]
    references += snapshot.selected_evidence_ids or []
    if case.country not in campaign.countries or case.segment not in campaign.segments or not set(references) <= ids:
        raise ValueError("La procedencia o el país/segmento no corresponde al caso.")
    assessment = snapshot.assessment
    if assessment is not None:
        if not {"id", "created_at"} <= assessment.model_fields_set:
            raise ValueError("La evaluación necesita identificador y fecha explícitos.")
        if (assessment.company_id != company.id or assessment.campaign_id != campaign.id
                or assessment.rubric_version != campaign.rubric_version
                or not set(assessment.products) <= {product.id for product in campaign.config_snapshot.catalog.products}
                or not set(assessment.target_roles) <= set(allowed_roles(campaign))
                or not {ref for criterion in assessment.criteria.values() for ref in criterion.evidence_ids} <= ids):
            raise ValueError("La evaluación referencia otra entidad/configuración/evidencia.")
        rubric = rubric_for(campaign)
        fit, coverage = compute_score(assessment.criteria, rubric)
        if (fit is None) != (assessment.fit_score is None) or (fit is not None and
                not math.isclose(fit, assessment.fit_score, rel_tol=1e-9, abs_tol=1e-9)) or not math.isclose(coverage, assessment.coverage, abs_tol=1e-9):
            raise ValueError("La puntuación/cobertura no corresponde a los criterios congelados.")
        selected = facts if snapshot.selected_evidence_ids is None else [fact for fact in facts if fact.id in snapshot.selected_evidence_ids]
        cited = {ref for criterion in assessment.criteria.values() for ref in criterion.evidence_ids}
        if snapshot.selected_evidence_ids is not None and not cited <= set(snapshot.selected_evidence_ids):
            raise ValueError("La evaluación cita evidencia que no se envió.")
        contradiction = any(fact.contradiction_ids for fact in selected if fact.id in cited)
        # Assessment histórico no conserva las contradicciones propuestas por Haiku.
        possible = {classify(assessment.criteria, rubric, excluded=assessment.priority == "excluded",
                            identity_confirmed=identity_confirmed(company), contradiction=flag,
                            primary_support=primary_support(assessment.criteria, selected)).priority
                    for flag in ({True} if contradiction else {False, True})}
        if assessment.priority not in possible:
            raise ValueError("La prioridad no corresponde a los criterios/condiciones disponibles.")
    if label is None:
        return
    if (label.case_id != case.case_id or label.snapshot_sha256 != case.artifact.sha256
            or label.assessment_id is not None and (assessment is None or label.assessment_id != assessment.id)):
        raise ValueError("La etiqueta no corresponde al artefacto/evaluación revisado.")
    if not set(label.products) <= {product.id for product in campaign.config_snapshot.catalog.products}:
        raise ValueError("La revisión propone un producto ajeno al catálogo congelado.")
    claims = set() if assessment is None else ({f"criteria:{name}" for name in assessment.criteria}
             | {f"products:{product}" for product in assessment.products} | {"explanation"})
    audited = [audit.claim_reference for audit in label.audits]
    if len(audited) != len(set(audited)) or not set(audited) <= claims:
        raise ValueError("Una auditoría duplica o inventa afirmaciones de la evaluación.")
    for reviewed in [*label.criteria.values(), *label.audits]:
        if not set(reviewed.evidence_ids) <= ids:
            raise ValueError("La revisión cita evidencia ajena al caso.")
        if snapshot.selected_evidence_ids is not None and not set(reviewed.evidence_ids) <= set(snapshot.selected_evidence_ids):
            raise ValueError("La revisión de una entrada conocida cita evidencia que no se envió.")
    if any(audit.supported is True and not audit.evidence_ids for audit in label.audits):
        raise ValueError("Un respaldo confirmado requiere evidencia auditada.")


def group_keys(snapshot, case):
    company = snapshot.company
    normalize = lambda value: re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", value.lower()))
    keys = {f"company:{company.id}", *(f"group:{normalize(key)}" for key in case.group_keys),
            *(f"name:{normalize(name)}" for name in [company.name, company.entity_name, *(company.aliases or [])] if name)}
    if company.domain:
        keys.add(f"domain:{company.domain.removeprefix('www.')}")
    if company.parent_company_id:
        keys.add(f"company:{company.parent_company_id}")
    return keys


def rate(numerator, denominator):
    if not denominator:
        return {"numerator": numerator, "denominator": denominator, "value": None, "wilson95": None}
    value, z = numerator / denominator, 1.959963984540054
    scale = 1 + z * z / denominator
    middle = (value + z * z / (2 * denominator)) / scale
    margin = z * math.sqrt(value * (1 - value) / denominator + z * z / (4 * denominator ** 2)) / scale
    return {"numerator": numerator, "denominator": denominator, "value": value,
            "wilson95": [max(0.0, middle - margin), min(1.0, middle + margin)]}


def summarize(rows):
    counts = Counter()
    for row in rows:
        predicted, acceptance = row["priority"], row["acceptance"]
        counts["cases"] += 1
        counts["reviewed"] += acceptance in {"accepted", "rejected"}
        counts["accepted"] += acceptance == "accepted"
        counts["accepted_not_selected"] += acceptance == "accepted" and predicted not in {"high", "medium"}
        counts["accepted_excluded"] += acceptance == "accepted" and predicted == "excluded"
        counts["errors"] += row["error_reason"] is not None
        counts["abstentions"] += predicted == "insufficient_evidence"
        counts["excluded"] += predicted == "excluded"
        counts["label_pending"] += acceptance == "pending"
        counts["blind_reviews"] += acceptance != "pending" and row["prediction_visible"] is False
        counts["visible_reviews"] += acceptance != "pending" and row["prediction_visible"] is True
        if predicted in {"high", "medium", "low"} and acceptance != "pending":
            positive = predicted in {"high", "medium"}
            counts[("TP" if positive else "FN") if acceptance == "accepted" else ("FP" if positive else "TN")] += 1
    tp, fp, fn, tn = (counts[key] for key in ("TP", "FP", "FN", "TN"))
    metrics = {"precision": rate(tp, tp + fp), "false_positive_fraction": rate(fp, tp + fp),
               "false_positive_rate": rate(fp, fp + tn), "review_coverage": rate(counts["reviewed"], len(rows)),
               "decision_coverage": rate(tp + fp + fn + tn, counts["reviewed"])}
    compared = [item for row in rows for item in row["criteria_comparison"].values()]
    metrics["criterion_agreement"] = rate(sum(item["agrees"] for item in compared), len(compared))
    metrics["null_zero_confusion"] = rate(sum(item["null_zero"] for item in compared), len(compared))
    metrics["criterion_overstatement"] = rate(sum(item["overstatement"] for item in compared), len(compared))
    per_criterion = {}
    for name in sorted({name for row in rows for name in row["criteria_comparison"]}):
        items = [row["criteria_comparison"][name] for row in rows if name in row["criteria_comparison"]]
        confusion = Counter(f"{item['expected_value']}->{item['predicted_value']}" for item in items)
        per_criterion[name] = {"agreement": rate(sum(item["agrees"] for item in items), len(items)), "confusion": dict(confusion)}
    audits = [item for row in rows for item in row["audits"] if item["supported"] is not None]
    metrics["audited_support"] = rate(sum(item["supported"] for item in audits), len(audits))
    products = [row["products_agree"] for row in rows if row["products_agree"] is not None]
    metrics["product_agreement"] = rate(sum(products), len(products))
    costs = {kind: {"known_cases": sum(row[kind] is not None for row in rows),
                    "total_usd": None if not any(row[kind] is not None for row in rows) else str(sum((Decimal(row[kind]) for row in rows if row[kind] is not None), Decimal(0)))}
             for kind in ("evaluation_estimated_cost_usd", "evaluation_final_cost_usd", "flow_cost_usd")}
    for kind, amount in costs.items():
        amount["cost_per_accepted_usd"] = (str(Decimal(amount["total_usd"]) / counts["accepted"])
             if counts["accepted"] and amount["known_cases"] == len(rows) else None)
    for key in ("TP", "FP", "FN", "TN", "cases", "reviewed", "accepted", "accepted_not_selected",
                "errors", "abstentions", "excluded", "accepted_excluded", "label_pending", "blind_reviews", "visible_reviews"):
        counts.setdefault(key, 0)
    return {"counts": dict(counts), "metrics": metrics, "per_criterion": per_criterion, "costs": costs,
            "priority_confusion": dict(Counter(f"{row['expected_priority']}->{row['priority']}" for row in rows if row["expected_priority"] is not None)),
            "latency_seconds": [row["duration_seconds"] for row in rows if row["duration_seconds"] is not None]}


def compatible_rubric(original, candidate):
    before, after = original.model_dump(), candidate.model_dump()
    before.pop("thresholds"); after.pop("thresholds")
    for item in (before, after):
        for definition in item["criteria"].values():
            definition.pop("weight")
    if before != after:
        raise ValueError("El contrafactual solo admite pesos/umbrales con la misma semántica.")


def evaluate_manifest(path, candidate=None):
    if Path(path).drive.startswith("\\\\"):
        raise ValueError("El evaluador solo lee archivos locales.")
    path = Path(path).resolve()
    manifest = EvaluationManifest.model_validate(read_json(path))
    rows, seen, entities, partition = [], set(), set(), {"development": set(), "evaluation": set()}
    inventory_keys = set(manifest.inventory.historical_group_keys)
    for case in manifest.cases:
        if case.case_id in seen:
            raise ValueError("Identificador de caso duplicado.")
        seen.add(case.case_id)
        snapshot, response, mode, usage, metadata = load_snapshot(path.parent, case)
        if snapshot.company.id in entities:
            raise ValueError("Una empresa está repetida en el conjunto.")
        entities.add(snapshot.company.id)
        label = None if case.label is None else EvaluationLabel.model_validate(read_json(checked_file(path.parent, case.label)))
        validate_snapshot(snapshot, case, label)
        keys = group_keys(snapshot, case)
        if keys & partition["evaluation" if case.split == "development" else "development"]:
            raise ValueError("Una entidad/dominio/alias/grupo aparece en ambas particiones.")
        if case.split == "evaluation" and keys & inventory_keys:
            raise ValueError("El conjunto de evaluación reutiliza una entidad del inventario histórico.")
        partition[case.split].update(keys)
        assessment, error = snapshot.assessment, snapshot.error_reason
        if assessment is None and error is None:
            error = "not_assessed"
        selected = snapshot.evidence if snapshot.selected_evidence_ids is None else [fact for fact in snapshot.evidence if fact.id in snapshot.selected_evidence_ids]
        criteria = None if assessment is None else assessment.criteria
        result = None
        if response is not None and mode == "replay":
            try:
                output = parse_output(response.text, response.stop_reason)
                criteria = validate_output(output, selected, snapshot.campaign)
                result = classify(criteria, rubric_for(snapshot.campaign), excluded=False,
                                  identity_confirmed=identity_confirmed(snapshot.company),
                                  contradiction=material_contradiction(output, criteria, selected),
                                  primary_support=primary_support(criteria, selected))
                if (assessment is None or criteria != assessment.criteria or result.priority != assessment.priority
                        or result.fit_score != assessment.fit_score or result.coverage != assessment.coverage
                        or list(dict.fromkeys(output.products)) != assessment.products
                        or list(dict.fromkeys(output.target_roles)) != assessment.target_roles):
                    raise ValueError("El replay no reproduce la evaluación capturada.")
            except QualificationError as failure:
                if assessment is not None:
                    raise ValueError("La respuesta inválida no puede tener una evaluación válida.") from failure
                error = failure.code
        priority = None if assessment is None or error is not None else str(assessment.priority)
        if candidate is not None and criteria is not None and error is None:
            compatible_rubric(rubric_for(snapshot.campaign), candidate["rubric"])
            if candidate["rubric"] != rubric_for(snapshot.campaign) and candidate["version"] == snapshot.campaign.rubric_version:
                raise ValueError("Cambiar pesos/umbrales requiere otra versión de rúbrica.")
            contradiction = any(fact.contradiction_ids for fact in selected if fact.id in {ref for criterion in criteria.values() for ref in criterion.evidence_ids})
            contradiction = contradiction or (result is not None and result.reason == "material_contradiction")
            baseline = classify(criteria, rubric_for(snapshot.campaign), excluded=priority == "excluded",
                                identity_confirmed=identity_confirmed(snapshot.company), contradiction=contradiction,
                                primary_support=primary_support(criteria, selected))
            if baseline.priority != assessment.priority or baseline.fit_score != assessment.fit_score or baseline.coverage != assessment.coverage:
                raise ValueError("Faltan condiciones originales: el contrafactual no reproduce la clasificación base.")
            result = classify(criteria, candidate["rubric"], excluded=priority == "excluded",
                              identity_confirmed=identity_confirmed(snapshot.company),
                              contradiction=contradiction,
                              primary_support=primary_support(criteria, selected))
            priority = str(result.priority)
        comparisons = {} if label is None or criteria is None else {
            name: {"agrees": reviewed.value == criteria[name].value,
                   "expected_value": reviewed.value, "predicted_value": criteria[name].value,
                   "null_zero": {reviewed.value, criteria[name].value} == {None, 0},
                   "overstatement": reviewed.value is not None and criteria[name].value is not None and criteria[name].value > reviewed.value}
            for name, reviewed in label.criteria.items() if reviewed.status == "resolved"}
        expected = None
        if label is not None and len(label.criteria) == 5 and all(item.status == "resolved" for item in label.criteria.values()):
            gold = {name: Criterion(value=item.value, evidence_ids=item.evidence_ids, justification=item.reason) for name, item in label.criteria.items()}
            cited = {ref for item in gold.values() for ref in item.evidence_ids}
            baseline = None if criteria is None else classify(criteria, rubric_for(snapshot.campaign), excluded=assessment.priority == "excluded",
                 identity_confirmed=identity_confirmed(snapshot.company),
                 contradiction=any(fact.contradiction_ids for fact in selected if fact.id in {ref for item in criteria.values() for ref in item.evidence_ids}),
                 primary_support=primary_support(criteria, selected))
            if mode == "replay" or baseline is not None and baseline.priority == assessment.priority:
                expected = str(classify(gold, candidate["rubric"] if candidate else rubric_for(snapshot.campaign), excluded=priority == "excluded",
                               identity_confirmed=identity_confirmed(snapshot.company),
                               contradiction=any(fact.contradiction_ids for fact in snapshot.evidence if fact.id in cited),
                               primary_support=primary_support(gold, snapshot.evidence)).priority)
        rows.append({"case_id": case.case_id, "split": case.split, "origin": case.origin,
                     "country": case.country, "segment": str(case.segment), "mode": mode,
                     "reference_type": None if label is None else label.reference_type,
                     "acceptance": "pending" if label is None else label.acceptance,
                     "prediction_visible": None if label is None else label.prediction_visible,
                     "label_sha256": None if case.label is None else case.label.sha256,
                     "label_content_sha256": None if label is None else digest(label.model_dump(mode="json", exclude={"snapshot_sha256", "assessment_id", "label_id", "version", "previous_sha256", "audits"})),
                     "artifact_sha256": case.artifact.sha256, "priority": priority, "error_reason": error,
                     "classification_reproducibility": ("not_assessed" if assessment is None else
                                                         "exact_replay" if mode == "replay" else "partial_conditions"),
                     "expected_priority": expected, "criteria_comparison": comparisons,
                     "audits": [] if label is None else [item.model_dump(mode="json") for item in label.audits],
                     "products_agree": None if label is None or label.products_status != "resolved" or assessment is None else set(label.products) == set(assessment.products),
                     "input_sha256": None if not metadata.get("submitted_evidence_verified") else digest(metadata["submitted_messages"]),
                     "context_reproducibility": ("not_captured" if metadata.get("submitted_messages") is None else
                                                 "exact_messages" if metadata.get("submitted_evidence_verified") else "unverified_format"),
                     "model_id": metadata.get("model_id") or (None if assessment is None else assessment.model_id),
                     "prompt_version": metadata.get("prompt_version") or (None if assessment is None else assessment.prompt_version),
                     "capture_metadata": metadata,
                     "evidence_scope": "available_only" if snapshot.selected_evidence_ids is None else "submitted",
                     "rubric_version": candidate["version"] if candidate else snapshot.campaign.rubric_version,
                     "evaluation_estimated_cost_usd": None if usage is None or usage.estimated_cost_usd is None else str(usage.estimated_cost_usd),
                     "evaluation_final_cost_usd": None if usage is None or usage.final_cost_usd is None else str(usage.final_cost_usd),
                     "flow_cost_usd": None if snapshot.flow_cost_usd is None else str(snapshot.flow_cost_usd),
                     "duration_seconds": snapshot.duration_seconds})
    groups = defaultdict(list)
    for row in rows:
        groups[(row["split"], row["origin"], row["reference_type"])].append(row)
    summaries = [{"split": split, "origin": origin, "reference_type": reviewer,
                  **summarize(group), "by_country": {key: summarize([row for row in group if row["country"] == key]) for key in sorted({row["country"] for row in group})},
                  "by_segment": {key: summarize([row for row in group if row["segment"] == key]) for key in sorted({row["segment"] for row in group})}}
                 for (split, origin, reviewer), group in groups.items()]
    for summary in summaries:
        group = groups[(summary["split"], summary["origin"], summary["reference_type"])]
        summary["by_country_segment"] = {f"{country}:{segment}": summarize([row for row in group if row["country"] == country and row["segment"] == segment])
            for country, segment in sorted({(row["country"], row["segment"]) for row in group})}
    project = Path(__file__).resolve().parent
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True, timeout=5)
        commit = commit.stdout.strip() if commit.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        commit = None
    return {"schema_version": "evaluation_report_v1", "dataset_version": manifest.dataset_version,
            "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "independence": "verified" if manifest.inventory.status == manifest.inventory.historical_coverage == "verified" and inventory_keys else "pending",
            "inventory_reference": manifest.inventory.reference, "counterfactual": candidate is not None,
            "candidate": None if candidate is None else {"version": candidate["version"], "rubric": candidate["rubric"].model_dump(mode="json"),
                                                       "sha256": digest({"version": candidate["version"], "rubric": candidate["rubric"].model_dump(mode="json")})},
            "evaluator_commit": commit, "evaluator_code_hashes": {name: hashlib.sha256((project / name).read_bytes()).hexdigest()
                for name in ("evaluate_qualification.py", "prospecting/qualification.py", "prospecting/models.py", "prospecting/haiku.py", "uv.lock")},
            "python_version": sys.version,
            "cases": rows, "summaries": summaries}


def paired_comparison(first, second):
    left, right = ({row["case_id"]: row for row in report["cases"]} for report in (first, second))
    counterfactual = first["counterfactual"] or second["counterfactual"]
    if left.keys() != right.keys() or any((left[key]["input_sha256"] is None or left[key]["input_sha256"] != right[key]["input_sha256"])
            and not (counterfactual and left[key]["artifact_sha256"] == right[key]["artifact_sha256"])
            or any(left[key][field] != right[key][field] for field in ("label_content_sha256", "origin", "split", "reference_type")) for key in left):
        raise ValueError("La comparación requiere los mismos casos, evidencia enviada y etiquetas.")
    return [{"case_id": key, "before": left[key]["priority"], "after": right[key]["priority"],
             "basis": "stored_criteria" if counterfactual else "submitted_messages",
             "changed": left[key]["priority"] != right[key]["priority"]} for key in sorted(left)]


def render_markdown(report):
    lines = ["# Evaluación de calificación T10", "", f"Conjunto: `{report['dataset_version']}`. Independencia: **{report['independence']}**.", "",
             "Las revisiones son atribuciones documentadas; no autentican al revisor ni validan criterios pendientes.", "",
             "| Partición | Origen | Revisión | N | TP / FP / FN / TN | Precisión |", "|---|---|---|---:|---|---|"]
    for summary in report["summaries"]:
        counts, precision = summary["counts"], summary["metrics"]["precision"]
        value = "No calculable" if precision["value"] is None else f"{precision['numerator']}/{precision['denominator']} ({precision['value']:.1%})"
        lines.append(f"| {summary['split']} | {summary['origin']} | {summary['reference_type'] or 'Pendiente'} | {counts['cases']} | {counts['TP']} / {counts['FP']} / {counts['FN']} / {counts['TN']} | {value} |")
    lines += ["", "Pendientes, abstenciones, exclusiones y fallos se informan aparte en el JSON. No son negativos verdaderos.",
              "", "Sin línea base manual no se afirma ahorro; sin aceptados el costo por aceptado no es calculable."]
    return "\n".join(lines) + "\n"


def prepare_blind(manifest_path, output):
    manifest_path, output = Path(manifest_path).resolve(), Path(output)
    manifest = EvaluationManifest.model_validate(read_json(manifest_path))
    if any(case.origin != "synthetic" for case in manifest.cases) and not output.resolve().is_relative_to(DATA_ROOT.resolve()):
        raise ValueError("Las fichas reales deben permanecer bajo data/.")
    evaluate_manifest(manifest_path)
    for case in manifest.cases:
        snapshot, _, _, _, metadata = load_snapshot(manifest_path.parent, case)
        facts = snapshot.evidence if snapshot.selected_evidence_ids is None else [item for item in snapshot.evidence if item.id in snapshot.selected_evidence_ids]
        data = {"case_id": case.case_id, "snapshot_sha256": case.artifact.sha256,
                "company": snapshot.company.model_dump(mode="json", include={"id", "name", "domain", "aliases", "operating_countries", "segments", "identity_status"}),
                "evidence": [] if metadata.get("submitted_messages") is not None else [item.model_dump(mode="json") for item in facts],
                "submitted_messages": metadata.get("submitted_messages"),
                "evidence_scope": "available_only" if snapshot.selected_evidence_ids is None else "submitted",
                "catalog": snapshot.campaign.config_snapshot.catalog.model_dump(mode="json"),
                "rubric_version": snapshot.campaign.rubric_version, "rubric": rubric_for(snapshot.campaign).model_dump(mode="json")}
        write_new(output / f"{case.case_id}-blind.json", data)
        label = {"schema_version": "evaluation_label_v1", "label_id": f"{case.case_id}-review", "version": "labels_v1", "case_id": case.case_id,
                 "snapshot_sha256": case.artifact.sha256, "assessment_id": None, "reference_type": "academic",
                 "reviewer": None, "role": None, "organization": None, "review_reference": None, "reviewed_at": None,
                 "reason": None, "acceptance": "pending", "prediction_visible": False,
                 "criteria": {}, "products_status": "pending", "products": [], "audits": []}
        write_new(output / f"{case.case_id}-label-template.json", label)


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rubric", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--prepare-blind", type=Path)
    args = parser.parse_args()
    try:
        candidate = None if args.rubric is None else read_json(args.rubric)
        if candidate is not None:
            if set(candidate) != {"version", "rubric"} or not isinstance(candidate["version"], str) or not candidate["version"].strip():
                raise ValueError("La candidata necesita version y rubric.")
            candidate["rubric"] = Rubric.model_validate(candidate["rubric"])
        report = evaluate_manifest(args.manifest, candidate)
        if args.compare:
            report["paired_comparison"] = paired_comparison(evaluate_manifest(args.compare), report)
        if args.prepare_blind:
            prepare_blind(args.manifest, args.prepare_blind)
        if args.output:
            if any(row["origin"] != "synthetic" for row in report["cases"]) and not args.output.resolve().is_relative_to(DATA_ROOT.resolve()):
                raise ValueError("Los informes con casos reales deben permanecer bajo data/.")
            write_new(args.output / "report.json", report)
            write_new(args.output / "report.md", render_markdown(report))
        else:
            print(render_markdown(report))
    except ValidationError:
        parser.exit(2, "Evaluación rechazada: un artefacto no cumple el contrato. No se muestran sus datos.\n")
    except OSError:
        parser.exit(2, "Evaluación rechazada: no se pudo leer o crear un artefacto; la salida no sobrescribe archivos.\n")
    except KeyError:
        parser.exit(2, "Evaluación rechazada: falta un artefacto obligatorio.\n")
    except ValueError as error:
        parser.exit(2, f"Evaluación rechazada: {error}\n")


if __name__ == "__main__":
    main()
