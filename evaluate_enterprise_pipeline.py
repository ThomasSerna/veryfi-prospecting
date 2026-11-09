"""Evaluación T21: captura autorizada de una celda y agregación offline reproducible.

Los expedientes reales permanecen en data/. El informe contiene solo agregados;
el replay no prueba otros prompts ni atribuye causalidad al cambio de proveedor.
"""

import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

import evaluate_qualification as qualification_evaluation
from evaluate_qualification import (
    Digest, Duration, EvaluationLabel, EvaluationManifest, FileReference, Inventory,
    checked_file, digest, group_keys, read_json, rate, write_new,
)
from prospecting.contacts import (
    apply_campaign_roles, channel_is_usable, contact_match, employment_status,
    load_contact_match, person_function, person_stage, rank_contact_matches,
    role_families, target_roles, validate_contact,
)
from prospecting.db import Database
from prospecting.discovery import load_icp_enterprise
from prospecting.identity import ExclusionEntry, ExclusionList, load_exclusions
from prospecting.models import (
    Campaign, CampaignFilters, Contract, CountryCode, Segment, Text, Usage,
    UtcDatetime, VeryfiConfig, utc_now,
)
from prospecting.pipeline import (
    AuthorizationInput, CampaignReport, CampaignView, execute_campaign, load_provider_access,
    prepare_campaign, provider_operations, read_campaign,
)
from prospecting.qualification import _scale_scope_applies, _scale_sources, enterprise_employee_signal

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data"
CELLS = {(country, segment) for country in ("CO", "MX") for segment in ("fintech_software", "cpg_loyalty")}
PUBLIC_OPERATIONS = {
    ("tavily", "search"), ("tavily", "extract"), ("anthropic", "messages"),
    ("apollo", "people_search"), ("apollo", "people_enrichment"), ("hunter", "domain_search"),
}
BLOCKER_CODES = {
    "plan_future", "independence_pending", "t14_gate_pending", "t14_gate_unverified",
    "ledger_missing", "ledger_consolidation_pending", "ledger_fingerprint_mismatch",
    "ledger_schema_unverified", "ledger_checkpoint_required", "authorization_session_mismatch",
    "authorization_reused", "authorization_required", "previous_capture_unverified", "enterprise_config_required",
}
STOP_CODES = {"entity_mismatch", "entity_mismatch_domain", "entity_mismatch_organization", "entity_mismatch_employment",
              "duplicate_review", "duplicate_request", "identity_unverified", "name_unconfirmed", "country_unconfirmed",
              "enrichment_limit", "people_limit", "page_limit", "campaign_time_limit", "company_time_limit",
              "excluded_account", "exclusion_review", "insufficient_evidence", "permission_denied", "quota_exceeded",
              "rate_limited", "local_rate_limit", "authorization_required", "authorization_exceeded", "budget_exceeded",
              "company_budget_exceeded", "apollo_timeout", "apollo_transport_error", "apollo_invalid_response",
              "apollo_api_inaccessible", "apollo_provider_error", "apollo_invalid_input", "timeout", "transport_error"}


class GateFiles(Contract):
    report: FileReference
    development_report: FileReference
    protocol: FileReference
    manifest: FileReference
    reviews: FileReference


class LedgerConfirmation(Contract):
    db_sha256: Digest
    responsible: Text
    source_reference: Text
    verified_at: UtcDatetime


class PipelinePlan(Contract):
    schema_version: Literal["pipeline_evaluation_plan_v1"]
    created_at: UtcDatetime
    responsible: Text
    source_reference: Text
    config: FileReference
    inventory: Inventory
    selection_policy: Text
    campaign_ids: dict[Text, UUID]
    filters: CampaignFilters = Field(default_factory=CampaignFilters)
    t14: GateFiles | None = None
    ledger: LedgerConfirmation | None = None
    exclusions: FileReference | None = None
    previous_captures: list[FileReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_cells(self):
        if set(self.campaign_ids) != {f"{country}:{segment}" for country, segment in CELLS}:
            raise ValueError("El plan requiere las cuatro celdas CO/MX × FinTech/CPG.")
        if len(set(self.campaign_ids.values())) != 4:
            raise ValueError("Cada celda requiere una campaña distinta.")
        return self


class ApprovalSession(Contract):
    schema_version: Literal["pipeline_approval_session_v1"]
    session_id: UUID
    campaign_id: UUID
    approved_at: UtcDatetime
    approvals: Annotated[list[AuthorizationInput], Field(min_length=1)]


class CompanyReview(Contract):
    company_id: UUID
    reference_type: Literal["academic", "Veryfi"]
    acceptance: Literal["accepted", "rejected", "pending"]
    reviewer: Text
    organization: Text
    source_reference: Text
    reviewed_at: UtcDatetime
    review_seconds: Duration | None = None


class PipelineCapture(Contract):
    schema_version: Literal["pipeline_capture_v1"]
    attempt_id: UUID = Field(default_factory=uuid4)
    origin: Literal["synthetic", "saved_real", "new_real"]
    country: CountryCode
    segment: Segment
    plan_sha256: Digest
    started_at: UtcDatetime
    evaluated_at: UtcDatetime
    duration_seconds: Duration | None = None
    status: Literal["blocked", "complete", "incomplete"]
    blockers: list[Text] = Field(default_factory=list)
    errors: list[Text] = Field(default_factory=list)
    campaign_report: CampaignReport | None = None
    view: CampaignView | None = None
    usage: list[Usage] | None = None
    hashes: dict[Text, Digest] = Field(default_factory=dict)
    historical_group_keys: list[Text] = Field(default_factory=list)
    reviews: list[CompanyReview] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_capture(self):
        if self.evaluated_at < self.started_at:
            raise ValueError("La fecha de corte precede al inicio.")
        if self.status == "complete" and (self.view is None or self.usage is None or self.campaign_report is None):
            raise ValueError("La captura completa necesita vista, reporte y ledger.")
        if self.status == "blocked" and not self.blockers:
            raise ValueError("Una captura bloqueada necesita motivos.")
        if self.view is not None:
            campaign = self.view.campaign
            if campaign.countries != [self.country] or campaign.segments != [self.segment]:
                raise ValueError("La vista pertenece a otra celda.")
            if self.campaign_report is not None and self.campaign_report.campaign_id != campaign.id:
                raise ValueError("El reporte pertenece a otra campaña.")
            if any(item.campaign_id != campaign.id for item in self.usage or []):
                raise ValueError("El ledger contiene otra campaña.")
            ids = [item.company.id for item in self.view.companies]
            if len(set(ids)) != len(ids):
                raise ValueError("La captura repite empresas.")
            for result in self.view.companies:
                company_id = result.company.id
                if result.run_item.company_id != company_id or result.run_item.campaign_id != campaign.id:
                    raise ValueError("Un checkpoint pertenece a otra empresa o campaña.")
                if any(fact.company_id != company_id for fact in result.evidence) or any(
                    person.contact.company_id != company_id for person in result.contacts
                ):
                    raise ValueError("El expediente contiene evidencia o personas de otra empresa.")
                contact_ids = [person.contact.id for person in result.contacts]
                if len(set(contact_ids)) != len(contact_ids):
                    raise ValueError("El expediente repite identificadores de personas.")
                if result.assessment is not None and (result.assessment.company_id != company_id or
                                                     result.assessment.campaign_id != campaign.id):
                    raise ValueError("La evaluación pertenece a otra empresa o campaña.")
            if any(review.company_id not in ids for review in self.reviews):
                raise ValueError("Una revisión pertenece a una empresa ajena.")
        return self


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def private_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to(DATA_ROOT.resolve()):
        raise ValueError("Los expedientes reales deben permanecer bajo data/.")
    return path


def save_capture(path, capture):
    capture = PipelineCapture.model_validate(capture)
    if capture.origin != "synthetic":
        private_path(path)
    payload = capture.model_dump(mode="json")
    write_new(Path(path), {"payload": payload, "sha256": digest(payload)})


def load_capture(path):
    data = read_json(path)
    if not isinstance(data, dict) or set(data) != {"payload", "sha256"} or digest(data["payload"]) != data["sha256"]:
        raise ValueError("La huella del expediente no coincide.")
    capture = PipelineCapture.model_validate(data["payload"])
    if capture.origin != "synthetic":
        private_path(path)
    return capture


def verify_gate(root, files, config):
    """Lee la prueba ya abierta; nunca vuelve a abrir ni modifica el holdout."""
    paths = {name: checked_file(root, getattr(files, name)) for name in GateFiles.model_fields}
    report, development, protocol = (read_json(paths[name]) for name in ("report", "development_report", "protocol"))
    manifest = EvaluationManifest.model_validate(read_json(paths["manifest"]))
    candidate = {"version": "rubric_v2", "rubric": config.rubrics["rubric_v2"]}
    repeated_development = qualification_evaluation.evaluate_manual(paths["manifest"], candidate, paths["reviews"])
    stable = lambda report: {key: value for key, value in report.items() if key not in {"manifest_sha256", "reviews_sha256"}}
    if digest(stable(repeated_development)) != digest(stable(development)) or development.get("development_checks", {}).get("status") != "passed":
        raise ValueError("El desarrollo T14 no se reproduce con sus entradas.")
    keys = ("selection_sha256", "development_labels_sha256", "development_reviews_sha256", "candidate_sha256", "evaluator_sha256")
    if (protocol.get("schema_version") != "enterprise_protocol_v1" or protocol.get("development_status") != "passed"
            or protocol.get("development_report_sha256") != digest(development)
            or any(protocol.get(key) != report.get(key) or report.get(key) != development.get(key) for key in keys)):
        raise ValueError("El protocolo T14 no respalda el informe.")
    if report.get("manifest_sha256") != file_hash(paths["manifest"]) or report.get("reviews_sha256") != file_hash(paths["reviews"]):
        raise ValueError("Las entradas T14 cambiaron tras la evaluación.")
    cohort = sorted((case.case_id, case.artifact.sha256) for case in manifest.cases if case.split == "evaluation")
    marker = paths["manifest"].parent / f".holdout-{digest(cohort)}.json"
    opened = read_json(marker)
    if (opened.get("schema_version") != "enterprise_holdout_opened_v1" or opened.get("protocol_sha256") != digest(protocol)
            or any(opened.get(key) != report.get(key) for key in (*keys, "manifest_sha256", "reviews_sha256"))):
        raise ValueError("Falta la apertura única verificable del holdout T14.")
    rows = report.get("cases", [])
    expected = Counter(f"{case.country}:{case.segment}" for case in manifest.cases if case.split == "evaluation")
    if (report.get("schema_version") != "enterprise_evaluation_report_v1" or report.get("partition") != "evaluation"
            or report.get("independence") != "verified" or expected != Counter({f"{c}:{s}": 5 for c, s in CELLS})
            or {row["case_id"] for row in rows} != {key for key, _ in cohort}
            or len(rows) != 20 or any(not row.get("complete") or not row.get("cell_verified") for row in rows)
            or any(case.origin == "synthetic" for case in manifest.cases)):
        raise ValueError("La muestra independiente T14 no está completa y comprobada.")
    gate = qualification_evaluation._manual_gate(rows, eligible=True, reasons=[])
    if gate != report.get("activation_gate") or gate["status"] != "passed":
        raise ValueError("La condición de activación T14 no está aprobada.")
    forbidden = set(manifest.inventory.historical_group_keys)
    for case in manifest.cases:
        snapshot, _, _, _, _ = qualification_evaluation.load_snapshot(paths["manifest"].parent, case)
        forbidden.update(group_keys(snapshot, case))
        if case.label is not None:
            label = EvaluationLabel.model_validate(read_json(checked_file(paths["manifest"].parent, case.label)))
            qualification_evaluation.validate_snapshot(snapshot, case, label)
    return forbidden


def exclusion_keys(company):
    return group_keys(SimpleNamespace(company=company), SimpleNamespace(group_keys=[]))


def evaluation_hashes():
    names = ("evaluate_enterprise_pipeline.py", "evaluate_qualification.py", "prospecting/contacts.py",
             "prospecting/qualification.py", "prospecting/models.py", "config/contact_match.json", "config/contact_match_v2.json")
    return {name: file_hash(ROOT / name) for name in names}


def effective_exclusions(plan, plan_root, forbidden, now):
    icp = load_icp_enterprise(ROOT / "config" / "icp_enterprise.json")
    entries = [ExclusionEntry(id=f"t21-{index}", name=key.partition(":")[2],
        domains=[key.partition(":")[2]] if key.startswith("domain:") else [], scope="group", reason="excluded",
        source_reference=plan.inventory.reference) for index, key in enumerate(sorted(forbidden))
        if key.startswith(("domain:", "name:", "group:"))]
    entries += [ExclusionEntry(id=f"reference-{index}", name=item.name,
        aliases=[*(item.brands_or_subsidiaries or []), *([item.parent_name] if item.parent_name else [])],
        domains=item.domains, scope="group", reason="excluded", source_reference=item.source_reference)
        for index, item in enumerate(icp.reference_companies)]
    if plan.exclusions is not None:
        provided = load_exclusions(checked_file(plan_root, plan.exclusions))
        entries += [entry.model_copy(update={"id": f"provided-{index}"}) for index, entry in enumerate(provided.entries)]
    return ExclusionList(version="t21_independence_v1", validation_status="pending",
        source_reference=plan.inventory.reference, observed_at=now, entries=entries)


def run_plan(plan_path, *, country, segment, db_path, access_path, approvals_path, output):
    """Ejecuta una sola celda con permisos frescos; un bloqueo no abre SQLite."""
    plan_path, output = private_path(plan_path), private_path(output)
    if (country, segment) not in CELLS:
        raise ValueError("Celda desconocida.")
    plan = PipelinePlan.model_validate(read_json(plan_path))
    config = VeryfiConfig.model_validate(read_json(checked_file(plan_path.parent, plan.config)))
    output.mkdir(parents=True, exist_ok=False)
    started = utc_now()
    blockers, errors, forbidden = [], [], set(plan.inventory.historical_group_keys)
    if plan.created_at > started:
        blockers.append("plan_future")
    if plan.inventory.status != "verified" or plan.inventory.historical_coverage != "verified" or not forbidden:
        blockers.append("independence_pending")
    if plan.t14 is None:
        blockers.append("t14_gate_pending")
    else:
        try:
            forbidden.update(verify_gate(plan_path.parent, plan.t14, config))
        except (OSError, ValueError, KeyError, TypeError) as error:
            blockers.append("t14_gate_unverified")
            errors.append(str(error))
    db_path = private_path(db_path)
    if not db_path.is_file() or db_path.stat().st_size == 0:
        blockers.append("ledger_missing")
    elif plan.ledger is None:
        blockers.append("ledger_consolidation_pending")
    elif plan.ledger.verified_at > started or file_hash(db_path) != plan.ledger.db_sha256:
        blockers.append("ledger_fingerprint_mismatch")
    if db_path.is_file():
        header = db_path.read_bytes()[:100]
        # Abrir el constructor migraría un histórico v1; el encabezado permite bloquearlo sin SQL.
        if header[:16] != b"SQLite format 3\x00" or int.from_bytes(header[60:64], "big") != 2:
            blockers.append("ledger_schema_unverified")
        if any(Path(str(db_path) + suffix).exists() and Path(str(db_path) + suffix).stat().st_size
               for suffix in ("-wal", "-journal")):
            blockers.append("ledger_checkpoint_required")
    hashes = {"plan": file_hash(plan_path), "config": plan.config.sha256,
              "code": file_hash(__file__), **evaluation_hashes()}
    approvals, access, session = [], None, None
    try:
        session = ApprovalSession.model_validate(read_json(private_path(approvals_path)))
        approvals = session.approvals
        if (session.campaign_id != plan.campaign_ids[f"{country}:{segment}"] or
                not plan.created_at <= session.approved_at <= started):
            blockers.append("authorization_session_mismatch")
        if (DATA_ROOT / ".t21-approvals" / f"{session.session_id}.json").exists():
            blockers.append("authorization_reused")
        access = load_provider_access(private_path(access_path))
        if not approvals or {(item.provider, item.operation, item.account_ref) for item in approvals} != set(provider_operations(access)):
            blockers.append("authorization_required")
        hashes.update(access=file_hash(access_path), approvals=file_hash(approvals_path))
    except (OSError, ValueError, TypeError):
        blockers.append("authorization_required")
    for reference in plan.previous_captures:
        previous = load_capture(checked_file(plan_path.parent, reference))
        if previous.origin == "synthetic" or previous.view is None:
            blockers.append("previous_capture_unverified")
            continue
        previous_campaign = previous.view.campaign
        if previous_campaign.id not in plan.campaign_ids.values():
            blockers.append("previous_capture_unverified")
        if previous_campaign.id != plan.campaign_ids[f"{country}:{segment}"]:
            for result in previous.view.companies:
                forbidden.update(exclusion_keys(result.company))
    if config.people_provider != "apollo" or config.role_taxonomy is None or config.people_policy is None:
        blockers.append("enterprise_config_required")
    campaign = Campaign(id=plan.campaign_ids[f"{country}:{segment}"], countries=[country], segments=[segment],
                        filters=plan.filters, max_companies=5, rubric_version="rubric_v2", config_snapshot=config)
    write_new(output / "preflight.json", {"plan": plan.model_dump(mode="json"), "hashes": hashes,
        "country": country, "segment": segment, "blockers": sorted(set(blockers)), "created_at": started.isoformat()})
    if blockers:
        capture = PipelineCapture(schema_version="pipeline_capture_v1", origin="new_real", country=country, segment=segment, plan_sha256=hashes["plan"],
            started_at=started, evaluated_at=utc_now(), status="blocked", blockers=sorted(set(blockers)),
            errors=errors, hashes=hashes, historical_group_keys=sorted(forbidden))
        save_capture(output / "capture.json", capture)
        return {"status": "blocked", "blockers": capture.blockers}
    exclusions_path = output / "exclusions.json"
    report, view, usage = None, None, None
    clock = time.monotonic()
    try:
        with Database(db_path) as db:
            if not db.list_campaigns() or not db.list_usage():
                raise ValueError("El ledger operativo no contiene el historial consolidado.")
            active = db.get_active_campaign()
            if active is not None and active.id != campaign.id:
                raise ValueError("Otra campaña permanece activa; no se cierra automáticamente.")
            for previous_campaign in db.list_campaigns():
                if previous_campaign.id != campaign.id:
                    for item in db.list_run_items(previous_campaign.id):
                        forbidden.update(exclusion_keys(db.get_company(item.company_id)))
        # Incluye las otras celdas aunque el operador omita sus expedientes previos.
        exclusions = effective_exclusions(plan, plan_path.parent, forbidden, started)
        write_new(exclusions_path, exclusions.model_dump(mode="json"))
        prepared = prepare_campaign(db_path, campaign)
        if (prepared.id != campaign.id or prepared.rubric_version != "rubric_v2" or prepared.countries != campaign.countries
                or prepared.segments != campaign.segments or prepared.filters != campaign.filters
                or prepared.max_companies != campaign.max_companies or prepared.limits != campaign.limits
                or prepared.config_snapshot.model_dump(exclude={"contact_match"}) != config.model_dump(exclude={"contact_match"})):
            raise ValueError("La campaña preparada no corresponde al plan enterprise.")
        def check_progress(progress):
            with Database(db_path) as db:
                company = db.get_company(progress.company_id)
            if exclusion_keys(company) & forbidden:
                raise ValueError("independence_overlap")
        write_new(DATA_ROOT / ".t21-approvals" / f"{session.session_id}.json", {
            "schema_version": "pipeline_approval_used_v1", "session_id": str(session.session_id),
            "campaign_id": str(campaign.id), "approvals_sha256": hashes["approvals"], "used_at": utc_now().isoformat()})
        report = execute_campaign(db_path, campaign.id, access=access, approvals=approvals,
                                  exclusions_path=exclusions_path, progress=check_progress)
    except Exception as error:
        errors.append(str(error))
    duration = time.monotonic() - clock
    try:
        view = read_campaign(db_path, campaign.id, account_allowances=access.account_allowances,
                             exclusions_path=exclusions_path)
    except Exception as error:
        errors.append(str(error))
    try:
        with Database(db_path) as db:
            usage = db.list_usage(campaign_id=campaign.id)
    except Exception as error:
        errors.append(str(error))
    capture = PipelineCapture(schema_version="pipeline_capture_v1", origin="new_real", country=country, segment=segment, plan_sha256=hashes["plan"],
        started_at=started, evaluated_at=utc_now(), duration_seconds=duration,
        status="incomplete" if errors or view is None or report is None or usage is None else "complete",
        errors=errors, campaign_report=report, view=view, usage=usage, hashes=hashes,
        historical_group_keys=sorted(forbidden))
    save_capture(output / "capture.json", capture)
    return {"status": capture.status, "campaign_status": None if report is None else str(report.status)}


def company_metrics(result, campaign, now):
    """Recalcula reglas con la fecha congelada, nunca con la fecha de ejecución del informe."""
    company, assessment, facts = result.company, result.assessment, result.evidence
    roles = [] if assessment is None else target_roles(company, assessment, campaign, evidence=facts)
    contacts = [person.contact for person in result.contacts]
    if assessment is not None:
        contacts = [apply_campaign_roles(contact, company, assessment, campaign, facts, now) for contact in contacts]
    selected = assessment is not None and str(assessment.priority) in {"high", "medium"}
    metrics = Counter(companies=1, qualified=int(selected), candidates=len(contacts))
    functions, functions_by_contact, rankings = set(), {}, {"contact_match_v1": [], "contact_match_v2": []}
    weights = [load_contact_match(ROOT / "config" / name) for name in ("contact_match.json", "contact_match_v2.json")]
    for contact in contacts:
        state = employment_status(contact, company, facts, campaign.limits, now)
        stage = None if assessment is None else person_stage(contact, company, assessment, facts, campaign.limits, now, roles, campaign=campaign)
        eligible = bool(selected and result.business_status != "excluded" and validate_contact(
            contact, company, assessment, facts, campaign.limits, now, roles, campaign=campaign))
        channels = [item for item in contact.channels if channel_is_usable(item, contact, facts, campaign.limits, now, company)]
        metrics.update(relevant=int(stage in {"relevant", "channel_usable", "ready"}),
            employment_verified=int(state.state == "corporate_evidence"), employment_obsolete=int(state.reason in {"employment_ended", "stale_source", "title_changed"}),
            emails_observed=sum(item.type == "email" for item in contact.channels),
            emails_usable=sum(item.type == "email" for item in channels), channels_usable=len(channels),
            ready=int(eligible and bool(channels)), preferred_ready=int(eligible and any(item.type in {"email", "phone", "whatsapp"} for item in channels)))
        if assessment is not None:
            # Desempata con la misma función que la ficha y el pipeline; la diversidad solo cuenta pertinentes.
            function = person_function(contact, company, assessment, campaign, facts, now)
            if function is not None:
                functions_by_contact[contact.id] = function
                if stage in {"relevant", "channel_usable", "ready"}:
                    functions.add(function)
            for weight in weights:
                ranking = contact_match(contact, company, assessment, facts, campaign.limits, now, roles, weight, campaign=campaign)
                rankings[weight.version].append((contact, ranking, eligible))
    metrics.update(with_ready=int(metrics["ready"] > 0 and selected), with_people=int(bool(contacts) and selected),
                   diverse_functions=int(len(functions) >= 2), distinct_functions=len(functions))
    metrics["alternative_ready"] = metrics["ready"] - metrics["preferred_ready"]
    families = [] if assessment is None else role_families(company, assessment, campaign, evidence=facts)
    orders = {version: rank_contact_matches(entries, roles, function_ids=functions_by_contact,
        function_order=list(dict.fromkeys(family.function_id for family in families))) for version, entries in rankings.items()}
    metrics["ranking_changed_companies"] = int(orders["contact_match_v1"] != orders["contact_match_v2"])
    size = company.size
    current_facts = [fact for fact in facts if fact.retrieved_at <= now]
    size_known = size is not None and _scale_scope_applies(company) and _scale_sources(company, current_facts)
    lower = None if not size_known else size.employee_count if size.employee_count is not None else size.employee_min
    upper = None if not size_known else size.employee_count if size.employee_count is not None else size.employee_max
    signal = enterprise_employee_signal(company, current_facts)
    category = ("large" if signal == 1 else "medium" if signal == .5 else "small"
                if size_known and upper is not None and upper < 50 else "unknown")
    metrics["large_without_fit"] = int(category == "large" and assessment is not None and str(assessment.priority) == "low")
    return metrics, category


def summarized(counts, available=True):
    names = ("companies", "qualified", "candidates", "relevant", "employment_verified", "employment_obsolete",
             "emails_observed", "emails_usable", "channels_usable", "ready", "preferred_ready", "alternative_ready", "with_ready", "with_people",
             "diverse_functions", "distinct_functions", "ranking_changed_companies", "large_without_fit")
    result = {name: counts[name] for name in names}
    result.update(person_coverage=rate(counts["with_people"], counts["qualified"]),
                  contact_coverage=rate(counts["with_ready"], counts["qualified"]),
                  usable_email_rate=rate(counts["emails_usable"], counts["emails_observed"]),
                  relevant_people_rate=rate(counts["relevant"], counts["candidates"]))
    for metric in ("relevant", "ready"):
        result[f"{metric}_per_company"] = {"numerator": counts[metric], "denominator": counts["companies"],
            "value": None if not counts["companies"] else counts[metric] / counts["companies"]}
    for kind in ("academic", "Veryfi"):
        result[f"accepted_{kind}"] = rate(counts[f"accepted_{kind}"], counts[f"reviewed_{kind}"])
    if not available:
        result = {key: ({"numerator": None, "denominator": None, "value": None, "wilson95": None}
                        if isinstance(value, dict) else None) for key, value in result.items()}
    return result


def merge_usage(previous, current):
    """Conserva la identidad y los importes conocidos; admite conciliación posterior sin duplicarla."""
    immutable = ("campaign_id", "company_id", "provider", "operation", "request_fingerprint", "created_at")
    protected = ("account_ref", "reserved_cost_usd", "reserved_credits", "credits", "final_cost_usd", "outlay_usd", "error_message")
    ranks = {"reserved": 0, "in_flight": 1, "uncertain": 2, "succeeded": 2, "failed": 2, "reconciled": 3}
    if (any(getattr(previous, key) != getattr(current, key) for key in immutable)
            or any(getattr(previous, key) is not None and getattr(previous, key) != getattr(current, key) for key in protected)
            or ranks[str(current.status)] < ranks[str(previous.status)]
            or previous.outcome in {"succeeded", "failed"} and current.outcome != previous.outcome):
        raise ValueError("Un request_id contiene consumos contradictorios.")
    for key in ("estimated_cost_usd", "funding_source", "outcome", "finished_at", "reconciled_at", "tokens", "reserved_tokens"):
        if getattr(previous, key) is not None and getattr(current, key) is None:
            raise ValueError("Una captura posterior pierde datos de consumo conocidos.")
    return current


def report_captures(paths):
    """Agrega solo expedientes íntegros, sin abrir SQLite ni llamar proveedores."""
    captures = [load_capture(path) for path in paths]
    if not captures:
        raise ValueError("Se requiere al menos una captura.")
    if any(item.origin == "synthetic" for item in captures) and any(item.origin != "synthetic" for item in captures):
        raise ValueError("No se mezclan capturas sintéticas y reales.")
    for capture in captures:
        if capture.origin != "synthetic" and capture.view is not None and any(
            capture.hashes.get(name) != value for name, value in evaluation_hashes().items()
        ):
            raise ValueError("El código o la configuración de evaluación difieren de la captura real.")
    attempts, latest, usage, plans = {}, {}, {}, set()
    for capture in sorted(captures, key=lambda item: (item.evaluated_at, str(item.attempt_id))):
        value = capture.model_dump(mode="json")
        if capture.attempt_id in attempts and attempts[capture.attempt_id] != digest(value):
            raise ValueError("Un intento tiene contenido contradictorio.")
        attempts[capture.attempt_id] = digest(value)
        plans.add(capture.plan_sha256)
        for movement in capture.usage or []:
            previous = usage.get(movement.request_id)
            usage[movement.request_id] = movement if previous is None else merge_usage(previous, movement)
        if capture.view is not None:
            key = capture.view.campaign.id
            if key not in latest or (latest[key].evaluated_at, str(latest[key].attempt_id)) < (capture.evaluated_at, str(capture.attempt_id)):
                latest[key] = capture
    totals, groups, errors, discovered, cells = Counter(), {}, Counter(), Counter(), Counter()
    review_durations = []
    # Discovery solo está presente en la primera pasada: una reanudación no debe borrarlo.
    discovery_by_campaign = {}
    for capture in sorted(captures, key=lambda item: (item.evaluated_at, str(item.attempt_id))):
        if capture.campaign_report is not None and capture.campaign_report.discovery is not None:
            key = capture.campaign_report.campaign_id
            discovery = capture.campaign_report.discovery
            if key in discovery_by_campaign and discovery_by_campaign[key] != discovery:
                raise ValueError("Los reportes iniciales de descubrimiento se contradicen.")
            discovery_by_campaign[key] = discovery
    seen, duplicate = set(), 0
    for capture in latest.values():
        campaign = capture.view.campaign
        for result in capture.view.companies:
            keys = exclusion_keys(result.company)
            if keys & seen:
                duplicate += 1
                continue
            seen.update(keys)
            counts, size = company_metrics(result, campaign, capture.evaluated_at)
            reviewed = set()
            for review in capture.reviews:
                if review.company_id == result.company.id:
                    if review.reference_type in reviewed:
                        raise ValueError("Una empresa repite la revisión de una misma procedencia.")
                    reviewed.add(review.reference_type)
                    review_durations.append(review.review_seconds)
                    if review.acceptance != "pending":
                        counts[f"reviewed_{review.reference_type}"] += 1
                        counts[f"accepted_{review.reference_type}"] += int(review.acceptance == "accepted")
            totals.update(counts)
            cell = (str(capture.country), str(capture.segment), size)
            groups.setdefault(cell, Counter()).update(counts)
            cells[cell[:2]] += 1
            if result.run_item.stop_reason:
                errors[result.run_item.stop_reason if result.run_item.stop_reason in STOP_CODES else "other"] += 1
            for key, count in result.run_item.attempts.items():
                if "entity_mismatch" in key:
                    reason = next((part for part in key.split(":") if part.startswith("entity_mismatch")), "entity_mismatch")
                    errors[reason if reason in STOP_CODES else "entity_mismatch"] += count
    for discovery in discovery_by_campaign.values():
        discovered.update(raw_hits=discovery.raw_hits, candidates=discovery.candidates)
        discovered["discarded"] += sum(discovery.discarded.values())
        discovered["duplicates"] += sum(value for key, value in discovery.discarded.items()
                                        if key in {"duplicate", "duplicate_domain", "duplicate_url"})
    costs = Counter()
    by_operation = {}
    for movement in usage.values():
        operation = (movement.provider, movement.operation)
        if operation not in PUBLIC_OPERATIONS:
            operation = ("other", "other")
        values = by_operation.setdefault(operation, Counter())
        values["requests"] += 1
        values["failed"] += int(movement.outcome == "failed" or movement.status == "failed")
        confirmed = movement.final_cost_usd
        estimate = movement.estimated_cost_usd
        values["confirmed_usd"] += confirmed or Decimal(0)
        values["estimated_usd"] += estimate or Decimal(0)
        values["reserved_usd"] += movement.reserved_cost_usd or Decimal(0)
        values["outlay_usd"] += movement.outlay_usd or Decimal(0)
        values["credits_confirmed"] += movement.credits if movement.status == "reconciled" and movement.credits is not None else Decimal(0)
        values["credits_observed"] += movement.credits or Decimal(0)
        values["credits_pending_bound"] += (movement.reserved_credits or Decimal(0)) if movement.status != "reconciled" else Decimal(0)
        values["pending_requests"] += int(movement.status != "reconciled" or confirmed is None)
        values["cost_unknown"] += int(confirmed is None and estimate is None)
        costs["attributable_usd"] += confirmed if confirmed is not None else estimate or Decimal(0)
        costs["unknown_requests"] += int(confirmed is None and estimate is None)
    durations = [capture.duration_seconds for capture in {item.attempt_id: item for item in captures}.values() if capture.status != "blocked"]
    complete = all(item.status == "complete" for item in captures)
    ledger_known = bool(latest) and all(item.usage is not None for item in latest.values())
    cost = None if costs["unknown_requests"] or not ledger_known else costs["attributable_usd"]
    observed_cells = {(str(item.country), str(item.segment)) for item in latest.values()}
    return {"schema_version": "pipeline_evaluation_report_v1", "origin": "synthetic" if captures[0].origin == "synthetic" else "real",
        "input_sha256": sorted(set(attempts.values())), "plan_sha256": sorted(plans),
        "qa_status": "reproducible" if complete else "incomplete", "commercial_validation": "pending",
        "real_coverage": "measured" if complete and latest and captures[0].origin != "synthetic" else "pending",
        "blockers": sorted({reason if reason in BLOCKER_CODES else "other" for capture in captures for reason in capture.blockers}),
        "incomplete_captures": sum(item.status != "complete" for item in captures), "duplicates": duplicate,
        "capture_errors": sum(len(item.errors) for item in {capture.attempt_id: capture for capture in captures}.values()),
        "sample": {"target_companies": 20, "observed_companies": totals["companies"] if latest else None,
                   "complete": observed_cells == CELLS and all(cells[cell] == 5 for cell in CELLS),
                   "cells": [{"country": country, "segment": segment, "target": 5,
                              "observed": cells[country, segment] if (country, segment) in observed_cells else None}
                             for country, segment in sorted(CELLS)]},
        "campaign_statuses": dict(sorted(Counter(str(capture.view.campaign.status) for capture in latest.values()).items())),
        "totals": summarized(totals, bool(latest)),
        "strata": [{"country": country, "segment": segment, "size": size,
                    **summarized(groups.get((country, segment, size), Counter()), any(str(item.country) == country and str(item.segment) == segment for item in latest.values()))}
                   for country, segment in sorted(CELLS) for size in ("small", "medium", "large", "unknown")],
        "discovery": dict(discovered), "stop_reasons": dict(sorted(errors.items())),
        "operations": [{"provider": provider, "operation": operation, **{key: str(value) if isinstance(value, Decimal) else value for key, value in values.items()}}
                       for (provider, operation), values in sorted(by_operation.items())],
        "flow_cost_usd": None if cost is None else str(cost),
        "cost_per_useful_contact_usd": None if cost is None or not totals["ready"] else str(cost / totals["ready"]),
        "automatic_seconds": None if not durations or any(value is None for value in durations) else sum(durations),
        "review_seconds": None if not review_durations or any(value is None for value in review_durations) else sum(review_durations),
        "hunter_baseline": {"basis": "documented_aggregates", "T09": {"selections": 16, "contact_coverage": rate(0, 5)},
                            "T11": {"selections": 8, "contact_coverage": rate(0, 4)}, "combined_unique_companies": None,
                            "ready_contacts": 0},
        "limitations": ["Comparación histórica descriptiva: proveedor, muestra, rúbrica y flujo cambiaron simultáneamente.",
            "Las 24 selecciones Hunter no equivalen a 24 empresas distintas; los denominadores no se suman.",
            "El replay de match compara las mismas personas, no los contactos que habría encontrado otro orden.",
            "La comparación de rúbricas y escala requiere evaluate_qualification.py y sus revisiones; no simula otro prompt.",
            "Sin revisión atribuible de Veryfi no se declara validación comercial ni cobertura general de LATAM."]}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    run = modes.add_parser("run", help="Captura una celda autorizada o registra su bloqueo sin tráfico.")
    run.add_argument("plan", type=Path)
    run.add_argument("--country", choices=["CO", "MX"], required=True)
    run.add_argument("--segment", choices=["fintech_software", "cpg_loyalty"], required=True)
    for name in ("db", "access", "approvals", "output"):
        run.add_argument(f"--{name}", type=Path, required=True)
    report = modes.add_parser("report", help="Genera solo agregados a partir de capturas congeladas.")
    report.add_argument("captures", type=Path, nargs="+")
    report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "run":
            result = run_plan(args.plan, country=args.country, segment=args.segment, db_path=args.db,
                              access_path=args.access, approvals_path=args.approvals, output=args.output)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["status"] == "complete" else 2
        write_new(args.output, report_captures(args.captures))
        print("Informe agregado generado.")
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print("No se pudo validar la entrada o conservar una salida nueva; revisar los artefactos privados.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
