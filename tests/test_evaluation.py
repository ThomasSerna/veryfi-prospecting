"""Conjuntos y respuestas exclusivamente sintéticos para el evaluador offline T10."""

from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import NAMESPACE_URL, uuid5

import pytest

import evaluate_qualification as evaluation
from prospecting.haiku import MODEL_ID
from prospecting.models import Assessment, Campaign, Company, Criterion, Evidence, Rubric, Usage
from prospecting.qualification import PROMPT_VERSION, build_haiku_request, classify, rubric_for


NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)
NAMES = ("document_need", "offer_match", "scale_potential", "adoption_capacity", "opportunity_timing")


def write_reference(root, filename, value):
    path = root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": filename, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write_synthetic_dataset(directory, config, definitions=None):
    """Genera una demostración determinista; todos sus datos y revisores son ficticios."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    definitions = definitions or [
        {"case_id": "true_positive", "values": [1, 1, 1, 1, 1], "acceptance": "accepted"},
        {"case_id": "false_positive", "values": [1, 1, 1, 1, 1], "acceptance": "rejected"},
        {"case_id": "false_negative", "values": [0, 0.5, 1, 1, 1], "acceptance": "accepted"},
        {"case_id": "true_negative", "values": [0, 0.5, 1, 1, 1], "acceptance": "rejected"},
    ]
    cases = []
    for spec in definitions:
        case_id = spec["case_id"]
        identifier = lambda suffix: uuid5(NAMESPACE_URL, f"synthetic-evaluation:{case_id}:{suffix}")
        company_id, fact_id = identifier("company"), identifier("evidence")
        fact = Evidence(id=fact_id, company_id=company_id, claim="Afirmación exclusivamente sintética.",
                        url=f"https://{case_id.replace('_', '-')}.example/producto", retrieved_at=NOW,
                        source_type="primary", kind="observed", excerpt="Este producto ficticio recibe comprobantes.")
        fields = {"name": spec.get("name", f"Empresa Sintética {case_id}"),
                  "domain": spec.get("domain", f"{case_id.replace('_', '-')}.example"),
                  "operating_countries": [spec.get("country", "CO")], "segments": [spec.get("segment", "fintech_software")]}
        if "aliases" in spec:
            fields["aliases"] = spec["aliases"]
        company = Company(id=company_id, **fields, identity_status="confirmed",
                          provenance={field: [fact_id] for field in fields})
        campaign = Campaign(id=identifier("campaign"), countries=["CO", "MX"],
                            segments=["fintech_software", "cpg_loyalty"], config_snapshot=config,
                            created_at=NOW, updated_at=NOW)
        values = spec.get("values", [1, 1, 1, 1, 1])
        criteria = {name: Criterion(value=value, evidence_ids=[] if value is None else [fact_id],
                                    justification="Justificación sintética.") for name, value in zip(NAMES, values, strict=True)}
        result = classify(criteria, rubric_for(campaign), excluded=spec.get("excluded", False), identity_confirmed=True,
                          contradiction=False, primary_support=True)
        assessment = Assessment(id=identifier("assessment"), campaign_id=campaign.id, company_id=company.id,
                                criteria=criteria, fit_score=result.fit_score, coverage=result.coverage,
                                priority=result.priority, model_id=MODEL_ID, prompt_version=PROMPT_VERSION,
                                rubric_version=campaign.rubric_version, explanation="Explicación sintética.", created_at=NOW)
        snapshot = {"schema_version": "evaluation_snapshot_v1", "origin": "synthetic",
                    "campaign": campaign.model_dump(mode="json"), "company": company.model_dump(mode="json"),
                    "evidence": [fact.model_dump(mode="json")], "assessment": None if spec.get("error") else assessment.model_dump(mode="json"),
                    "selected_evidence_ids": [str(fact_id)], "error_reason": spec.get("error"),
                    "flow_cost_usd": spec.get("flow_cost"), "duration_seconds": spec.get("duration")}
        artifact = write_reference(root, f"{case_id}/snapshot.json", snapshot)
        gold = spec.get("gold", values)
        label = {"schema_version": "evaluation_label_v1", "label_id": f"{case_id}-synthetic-review", "version": "labels_v1",
                 "case_id": case_id, "snapshot_sha256": artifact["sha256"], "assessment_id": None,
                 "reference_type": spec.get("reference_type", "academic"), "reviewer": "Revisor Sintético",
                 "role": "Rol Sintético", "organization": "Organización Sintética", "review_reference": "Fuente Sintética 1",
                 "reviewed_at": NOW.isoformat(), "reason": "Motivo sintético.", "prediction_visible": spec.get("prediction_visible", False),
                 "acceptance": spec.get("acceptance", "pending"),
                 "criteria": {name: {"status": "resolved", "value": value, "evidence_ids": [] if value is None else [str(fact_id)],
                                      "reason": "Evaluación sintética del criterio."} for name, value in zip(NAMES, gold, strict=True)},
                 "products_status": "resolved", "products": [],
                 "audits": [] if spec.get("error") else [{"claim_reference": "criteria:document_need", "evidence_ids": [str(fact_id)],
                                                           "supported": True, "reason": "Auditoría exclusivamente sintética."}]}
        reference = None if spec.get("unlabelled") else write_reference(root, f"{case_id}/label-v1.json", label)
        cases.append({"case_id": case_id, "split": spec.get("split", "evaluation"), "origin": "synthetic",
                      "country": spec.get("country", "CO"), "segment": spec.get("segment", "fintech_software"),
                      "group_keys": spec.get("group_keys", []), "artifact": artifact, "label": reference})
    manifest = {"schema_version": "evaluation_manifest_v1", "dataset_version": "synthetic-v1", "created_at": NOW.isoformat(),
                "inventory": {"status": "pending", "historical_coverage": "pending", "reference": "Inventario sintético provisional.",
                              "historical_group_keys": []}, "cases": cases}
    write_reference(root, "manifest.json", manifest)
    return root / "manifest.json"


def revise_case(path, index, section, transform):
    """Cambia una fixture y actualiza sólo su referencia, como una nueva captura de prueba."""
    manifest = evaluation.read_json(path)
    case = manifest["cases"][index]
    value = evaluation.read_json(path.parent / case[section]["path"])
    transform(value)
    case[section] = write_reference(path.parent, case[section]["path"], value)
    if section == "artifact" and case["label"]:
        label = evaluation.read_json(path.parent / case["label"]["path"])
        label["snapshot_sha256"] = case["artifact"]["sha256"]
        case["label"] = write_reference(path.parent, case["label"]["path"], label)
    write_reference(path.parent, path.name, manifest)


def add_trace(path, *, invalid=False, origin="synthetic", reuse=False):
    manifest = evaluation.read_json(path)
    case = manifest["cases"][0]
    snapshot = evaluation.Snapshot.model_validate(evaluation.read_json(path.parent / case["case_id"] / "snapshot.json"))
    payload, selected = build_haiku_request(snapshot.company, snapshot.evidence, snapshot.campaign)
    raw = {"criteria": {name: item.model_dump(mode="json") for name, item in snapshot.assessment.criteria.items()},
           "products": [], "target_roles": [], "explanation": "Explicación sintética.",
           "contradiction_evidence_ids": [], "uncertainties": []}
    request_id = uuid5(NAMESPACE_URL, "synthetic-evaluation-request")
    fingerprint = evaluation.digest({"provider": "anthropic", "operation": "messages", "account_ref": "synthetic-account", "payload": payload})
    usage = Usage(request_id=request_id, campaign_id=snapshot.campaign.id, company_id=snapshot.company.id,
                  provider="anthropic", operation="messages", account_ref="synthetic-account", request_fingerprint=fingerprint,
                  status="succeeded", outcome="succeeded", tokens={}, estimated_cost_usd="0.001", final_cost_usd="0.001", created_at=NOW)
    source = {"schema_version": "evaluation_trace_v1", "trace_id": "synthetic-trace", "campaign": snapshot.campaign.model_dump(mode="json"),
              "company": snapshot.company.model_dump(mode="json"), "evidence": [item.model_dump(mode="json") for item in snapshot.evidence],
              "selected_evidence_ids": [] if reuse else [str(item.id) for item in selected], "request_payload": None if reuse else payload,
              "prompt_version": None if reuse else PROMPT_VERSION, "requested_model_id": None if reuse else MODEL_ID,
              "rubric_version": snapshot.campaign.rubric_version, "catalog_version": snapshot.campaign.config_snapshot.catalog.version,
              "commit": None, "code_hashes": {}, "captured_at": NOW.isoformat(), "origin": origin}
    report = {"campaign_id": str(snapshot.campaign.id), "company_id": str(snapshot.company.id), "status": "pending" if invalid else "already_assessed" if reuse else "assessed",
              "assessment_id": None if invalid else str(snapshot.assessment.id), "priority": None if invalid else str(snapshot.assessment.priority),
              "fit_score": None if invalid else snapshot.assessment.fit_score, "coverage": None if invalid else snapshot.assessment.coverage,
              "called_model": not reuse, "request_id": None if reuse else str(request_id),
              "tokens": None if reuse else {}, "estimated_cost_usd": None if reuse else "0.001",
              "reason": "invalid_output" if invalid else None}
    result = {"assessment": None if invalid else snapshot.assessment.model_dump(mode="json"), "report": report,
              "usage": None if reuse else usage.model_dump(mode="json"), "duration_seconds": None if reuse else 1.25, "called_model": not reuse}
    artifacts = {"input.json": source, "result.json": result}
    if not reuse:
        artifacts["request.json"] = {"request_id": str(request_id), "request_fingerprint": fingerprint}
        artifacts["response.json"] = {"request_id": str(request_id), "model": MODEL_ID,
                                      "text": "invalid synthetic JSON" if invalid else json.dumps(raw), "stop_reason": "end_turn", "tokens": {}, "estimated_cost_usd": "0.001"}
    hashes = {name: write_reference(path.parent, f"trace/{name}", data)["sha256"] for name, data in artifacts.items()}
    trace = {"schema_version": "evaluation_trace_v1", "trace_id": "synthetic-trace", "artifacts": hashes, "complete": True, "capture_errors": []}
    case["artifact"] = write_reference(path.parent, "trace/manifest.json", trace)
    label = evaluation.read_json(path.parent / case["label"]["path"])
    label["snapshot_sha256"] = case["artifact"]["sha256"]
    if invalid:
        label["audits"] = []
    case["label"] = write_reference(path.parent, case["label"]["path"], label)
    write_reference(path.parent, path.name, manifest)


def revise_trace(path, filename, transform):
    manifest = evaluation.read_json(path)
    case = manifest["cases"][0]
    trace_path = path.parent / case["artifact"]["path"]
    trace = evaluation.read_json(trace_path)
    value = evaluation.read_json(trace_path.parent / filename)
    transform(value)
    trace["artifacts"][filename] = write_reference(trace_path.parent, filename, value)["sha256"]
    case["artifact"] = write_reference(path.parent, case["artifact"]["path"], trace)
    label = evaluation.read_json(path.parent / case["label"]["path"])
    label["snapshot_sha256"] = case["artifact"]["sha256"]
    case["label"] = write_reference(path.parent, case["label"]["path"], label)
    write_reference(path.parent, path.name, manifest)


def test_confusion_denominators_wilson_and_reproducible_no_writes(tmp_path, config, monkeypatch):
    path = write_synthetic_dataset(tmp_path, config)
    before = {item: item.read_bytes() for item in tmp_path.rglob("*") if item.is_file()}
    monkeypatch.setattr("socket.socket.connect", lambda *_: pytest.fail("Intentó acceder a la red."))
    monkeypatch.setattr("sqlite3.connect", lambda *_: pytest.fail("Intentó abrir una base."))
    report = evaluation.evaluate_manifest(path)
    assert report == evaluation.evaluate_manifest(path)
    summary = report["summaries"][0]
    assert [summary["counts"][key] for key in ("TP", "FP", "FN", "TN")] == [1, 1, 1, 1]
    assert summary["metrics"]["precision"] == summary["metrics"]["false_positive_rate"]
    assert summary["metrics"]["precision"]["value"] == 0.5
    assert summary["metrics"]["precision"]["wilson95"] == pytest.approx([0.0945312057, 0.9054687943])
    assert summary["counts"]["blind_reviews"] == 4 and summary["counts"]["visible_reviews"] == 0
    assert report["independence"] == "pending"
    assert summary["costs"]["flow_cost_usd"]["total_usd"] is None
    assert before == {item: item.read_bytes() for item in tmp_path.rglob("*") if item.is_file()}


def test_pending_failures_and_exclusions_never_become_true_negatives(tmp_path, config):
    specs = [{"case_id": "abstain", "values": [None] * 5, "acceptance": "accepted"},
             {"case_id": "failed", "error": "timeout", "acceptance": "rejected"},
             {"case_id": "excluded", "excluded": True, "acceptance": "rejected"},
             {"case_id": "unreviewed", "unlabelled": True}]
    report = evaluation.evaluate_manifest(write_synthetic_dataset(tmp_path, config, specs))
    groups = report["summaries"]
    labelled = next(group for group in groups if group["reference_type"] == "academic")
    assert all(labelled["counts"][key] == 0 for key in ("TP", "FP", "FN", "TN"))
    assert labelled["counts"]["accepted_not_selected"] == labelled["counts"]["abstentions"] == 1
    assert labelled["counts"]["errors"] == labelled["counts"]["excluded"] == 1
    assert labelled["metrics"]["precision"]["value"] is None
    assert report["cases"][1]["priority"] is None


@pytest.mark.parametrize("overlap", [{"domain": "shared.example"}, {"name": "Misma Empresa Sintética"},
                                     {"aliases": ["Alias Sintético Común"]}, {"group_keys": ["Grupo Matriz Sintético"]}])
def test_split_rejects_entity_domain_alias_and_group_overlap(tmp_path, config, overlap):
    path = write_synthetic_dataset(tmp_path, config, [{"case_id": "dev", "split": "development", **overlap},
                                                     {"case_id": "eval", **overlap}])
    with pytest.raises(ValueError, match="ambas particiones"):
        evaluation.evaluate_manifest(path)


def test_historical_inventory_overlap_and_partial_inventory(tmp_path, config):
    path = write_synthetic_dataset(tmp_path, config)
    manifest = evaluation.read_json(path)
    manifest["inventory"].update(status="verified", historical_coverage="verified", historical_group_keys=["domain:true-positive.example"])
    write_reference(tmp_path, "manifest.json", manifest)
    with pytest.raises(ValueError, match="inventario histórico"):
        evaluation.evaluate_manifest(path)
    manifest["inventory"]["historical_group_keys"] = []
    write_reference(tmp_path, "manifest.json", manifest)
    assert evaluation.evaluate_manifest(path)["independence"] == "pending"
    manifest["inventory"]["historical_group_keys"] = ["domain:historical-synthetic.example"]
    write_reference(tmp_path, "manifest.json", manifest)
    assert evaluation.evaluate_manifest(path)["independence"] == "verified"
    manifest["inventory"]["historical_coverage"] = "pending"
    write_reference(tmp_path, "manifest.json", manifest)
    assert evaluation.evaluate_manifest(path)["independence"] == "pending"


def test_integrity_duplicates_cross_references_and_missing_fixed_identifiers(tmp_path, config):
    path = write_synthetic_dataset(tmp_path, config)
    artifact = tmp_path / "true_positive/snapshot.json"
    artifact.write_text(artifact.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        evaluation.evaluate_manifest(path)
    path = write_synthetic_dataset(tmp_path, config)
    revise_case(path, 0, "artifact", lambda item: item["evidence"][0].update(company_id="00000000-0000-4000-8000-000000000999"))
    with pytest.raises(ValueError, match="otra entidad"):
        evaluation.evaluate_manifest(path)
    path = write_synthetic_dataset(tmp_path, config)
    revise_case(path, 0, "artifact", lambda item: item["company"].pop("id"))
    with pytest.raises(ValueError, match="explícitos"):
        evaluation.evaluate_manifest(path)
    path = write_synthetic_dataset(tmp_path, config)
    manifest = evaluation.read_json(path)
    manifest["cases"].append(manifest["cases"][0])
    write_reference(tmp_path, "manifest.json", manifest)
    with pytest.raises(ValueError, match="duplicado"):
        evaluation.evaluate_manifest(path)


def test_path_traversal_is_rejected_before_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "resolve", lambda *_: pytest.fail("Resolvió una ruta prohibida."))
    with pytest.raises(ValueError, match="sale del directorio"):
        evaluation.checked_file(tmp_path, evaluation.FileReference(path="../secret.json", sha256="a" * 64))


def test_criterion_confusion_pending_gold_and_support_are_audited(tmp_path, config):
    path = write_synthetic_dataset(tmp_path, config, [{"case_id": "criteria", "values": [0, 1, 1, 1, 1],
                                                      "gold": [None, 0.5, 1, 1, 1], "acceptance": "accepted"}])
    revise_case(path, 0, "label", lambda item: item["criteria"]["scale_potential"].update(status="pending", value=None, evidence_ids=[]))
    summary = evaluation.evaluate_manifest(path)["summaries"][0]
    assert summary["metrics"]["criterion_agreement"]["denominator"] == 4
    assert summary["metrics"]["null_zero_confusion"]["numerator"] == 1
    assert summary["metrics"]["criterion_overstatement"]["numerator"] == 1
    assert summary["per_criterion"]["document_need"]["confusion"] == {"None->0": 1}
    revise_case(path, 0, "label", lambda item: item["audits"].append(dict(item["audits"][0])))
    with pytest.raises(ValueError, match="duplica"):
        evaluation.evaluate_manifest(path)


def test_origin_reviewer_breakdowns_and_decimal_costs_do_not_mix(tmp_path, config):
    path = write_synthetic_dataset(tmp_path, config, [{"case_id": "academic", "acceptance": "accepted", "flow_cost": "0.1"},
                                                      {"case_id": "veryfi", "reference_type": "Veryfi", "country": "MX", "segment": "cpg_loyalty", "acceptance": "accepted", "flow_cost": "0.2"}])
    report = evaluation.evaluate_manifest(path)
    assert len(report["summaries"]) == 2
    assert report["summaries"][0]["costs"]["flow_cost_usd"]["cost_per_accepted_usd"] == "0.1"
    assert report["summaries"][1]["by_country"]["MX"]["counts"]["TP"] == 1
    assert report["summaries"][1]["by_country_segment"]["MX:cpg_loyalty"]["counts"]["TP"] == 1
    revise_case(path, 0, "label", lambda item: item.update(acceptance="rejected"))
    assert evaluation.evaluate_manifest(path)["summaries"][0]["costs"]["flow_cost_usd"]["cost_per_accepted_usd"] is None
    manifest = evaluation.read_json(path)
    manifest["cases"][0]["origin"] = "saved_real"
    write_reference(tmp_path, "manifest.json", manifest)
    with pytest.raises(ValueError, match="origen"):
        evaluation.evaluate_manifest(path)


def test_raw_trace_replay_and_invalid_output_preserve_pending(tmp_path, config):
    path = write_synthetic_dataset(tmp_path, config, [{"case_id": "trace", "acceptance": "accepted"}])
    add_trace(path)
    report = evaluation.evaluate_manifest(path)
    assert report["cases"][0]["mode"] == "replay" and report["cases"][0]["priority"] == "high"
    assert report["summaries"][0]["costs"]["evaluation_final_cost_usd"]["total_usd"] == "0.001"
    add_trace(path, invalid=True)
    row = evaluation.evaluate_manifest(path)["cases"][0]
    assert row["priority"] is None and row["error_reason"] == "invalid_output"
    assert row["model_id"] == MODEL_ID and row["prompt_version"] == PROMPT_VERSION


def test_trace_without_new_model_nullable_fields_are_audit_only(tmp_path, config):
    path = write_synthetic_dataset(tmp_path, config, [{"case_id": "reuse", "acceptance": "accepted"}])
    add_trace(path, reuse=True)
    row = evaluation.evaluate_manifest(path)["cases"][0]
    assert row["mode"] == "audit_only" and row["duration_seconds"] is None and row["input_sha256"] is None


def test_counterfactual_keeps_semantics_versions_and_unknown_conditions(tmp_path, config):
    path = write_synthetic_dataset(tmp_path, config)
    original = evaluation.evaluate_manifest(path)
    rubric = config.rubrics["rubric_v1"].model_dump(mode="json")
    rubric["thresholds"]["high"]["fit_score_min"] = 100.0
    candidate = {"version": "rubric_candidate_v2", "rubric": Rubric.model_validate(rubric)}
    alternate = evaluation.evaluate_manifest(path, candidate)
    assert evaluation.paired_comparison(original, alternate)[0]["case_id"] == "false_negative"
    assert alternate["candidate"]["version"] == "rubric_candidate_v2" and len(alternate["candidate"]["sha256"]) == 64
    candidate["version"] = "rubric_v1"
    with pytest.raises(ValueError, match="otra versión"):
        evaluation.evaluate_manifest(path, candidate)
    rubric["zero_meaning"] += " Otra definición."
    with pytest.raises(ValueError, match="semántica"):
        evaluation.evaluate_manifest(path, {"version": "rubric_candidate_v3", "rubric": Rubric.model_validate(rubric)})
    revise_case(path, 0, "artifact", lambda item: item["assessment"].update(priority="insufficient_evidence"))
    with pytest.raises(ValueError, match="condiciones originales"):
        evaluation.evaluate_manifest(path, {"version": "rubric_candidate_v2", "rubric": config.rubrics["rubric_v1"]})


def test_blind_templates_hide_predictions_and_do_not_overwrite(tmp_path, config):
    path = write_synthetic_dataset(tmp_path / "source", config)
    output = tmp_path / "blind"
    evaluation.prepare_blind(path, output)
    ficha = evaluation.read_json(output / "true_positive-blind.json")
    assert not {"assessment", "fit_score", "coverage", "priority"} & ficha.keys()
    template = evaluation.read_json(output / "true_positive-label-template.json")
    assert template["prediction_visible"] is False and template["acceptance"] == "pending"
    with pytest.raises(FileExistsError):
        evaluation.prepare_blind(path, output)


def test_cli_default_is_aggregate_and_invalid_labels_do_not_expose_values(tmp_path, config):
    path = write_synthetic_dataset(tmp_path, config)
    script = Path(evaluation.__file__)
    result = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True)
    assert result.returncode == 0 and "Empresa Sintética" not in result.stdout and "Revisor Sintético" not in result.stdout
    revise_case(path, 0, "label", lambda item: item.update(reference_type="PERSONAL_VALUE_NOT_FOR_LOGS"))
    result = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True)
    assert result.returncode == 2 and "PERSONAL_VALUE_NOT_FOR_LOGS" not in result.stderr


@pytest.mark.parametrize(("filename", "change"), [
    ("response.json", lambda data: data["tokens"].update(input_tokens=999999)),
    ("request.json", lambda data: data.update(request_id="00000000-0000-4000-8000-000000000999")),
    ("result.json", lambda data: data["report"].update(fit_score=999)),
    ("result.json", lambda data: data["usage"].update(provider="tavily", operation="search")),
    ("result.json", lambda data: data.update(called_model=False)),
])
def test_trace_rejects_incoherent_result_usage_and_response_even_with_valid_hashes(tmp_path, config, filename, change):
    path = write_synthetic_dataset(tmp_path, config, [{"case_id": "coherence", "acceptance": "accepted"}])
    add_trace(path)
    revise_trace(path, filename, change)
    with pytest.raises(ValueError):
        evaluation.evaluate_manifest(path)


def test_incomplete_request_capture_preserves_the_failure_without_replay(tmp_path, config):
    path = write_synthetic_dataset(tmp_path, config, [{"case_id": "incomplete", "acceptance": "accepted"}])
    add_trace(path)
    def incomplete_result(data):
        data.update(assessment=None, called_model=False)
        data["report"].update(status="pending", assessment_id=None, priority=None, fit_score=None, coverage=None,
                              called_model=False, tokens=None, estimated_cost_usd=None, reason="trace_capture_failed")
        data["usage"].update(status="reserved", outcome=None, tokens=None, estimated_cost_usd=None, final_cost_usd=None)
    revise_trace(path, "result.json", incomplete_result)
    manifest = evaluation.read_json(path)
    trace_reference = manifest["cases"][0]["artifact"]
    trace = evaluation.read_json(path.parent / trace_reference["path"])
    trace["artifacts"].pop("request.json")
    trace["artifacts"].pop("response.json")
    trace.update(complete=False, capture_errors=["request.json no se pudo guardar: fallo sintético."])
    manifest["cases"][0]["artifact"] = write_reference(path.parent, trace_reference["path"], trace)
    label_reference = manifest["cases"][0]["label"]
    label = evaluation.read_json(path.parent / label_reference["path"])
    label.update(snapshot_sha256=manifest["cases"][0]["artifact"]["sha256"], audits=[])
    manifest["cases"][0]["label"] = write_reference(path.parent, label_reference["path"], label)
    write_reference(path.parent, path.name, manifest)
    row = evaluation.evaluate_manifest(path)["cases"][0]
    assert row["mode"] == "incomplete_trace" and row["error_reason"] == "capture_incomplete" and row["priority"] is None


def test_blind_context_and_pairing_use_exact_messages_instead_of_full_excerpt(tmp_path, config):
    path = write_synthetic_dataset(tmp_path / "source", config, [{"case_id": "context", "acceptance": "accepted"}])
    revise_case(path, 0, "artifact", lambda data: data["evidence"][0].update(excerpt="x" * 600 + "UNSENT_SYNTHETIC_SUFFIX"))
    add_trace(path)
    baseline = evaluation.evaluate_manifest(path)
    assert baseline["cases"][0]["context_reproducibility"] == "exact_messages"
    evaluation.prepare_blind(path, tmp_path / "blind")
    blind = evaluation.read_json(tmp_path / "blind/context-blind.json")
    assert blind["evidence"] == [] and "UNSENT_SYNTHETIC_SUFFIX" not in json.dumps(blind["submitted_messages"])
    assert "rubric" in blind and "fit_score" not in blind
    revise_trace(path, "input.json", lambda data: data["request_payload"]["messages"][0].update(content="different synthetic context"))
    with pytest.raises(ValueError, match="vinculados"):
        evaluation.evaluate_manifest(path)
    changed = json.loads(json.dumps(baseline))
    changed["cases"][0]["input_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="mismos casos"):
        evaluation.paired_comparison(baseline, changed)


def test_replay_rejects_unsent_reference_despite_consistent_hashes(tmp_path, config):
    path = write_synthetic_dataset(tmp_path, config, [{"case_id": "unsent"}])
    add_trace(path)
    unseen = str(uuid5(NAMESPACE_URL, "synthetic-unsent-evidence"))

    def add_unsent(data):
        fact = dict(data["evidence"][0], id=unseen)
        data["evidence"].append(fact)
        data["selected_evidence_ids"].append(unseen)
        assert unseen not in json.dumps(data["request_payload"])

    revise_trace(path, "input.json", add_unsent)
    def cite_unsent(data):
        raw = json.loads(data["text"])
        raw["criteria"]["document_need"]["evidence_ids"] = [unseen]
        data["text"] = json.dumps(raw)
    revise_trace(path, "response.json", cite_unsent)
    revise_trace(path, "result.json", lambda data: data["assessment"]["criteria"]["document_need"].update(evidence_ids=[unseen]))
    with pytest.raises(ValueError, match="declarada no coincide"):
        evaluation.evaluate_manifest(path)


@pytest.mark.parametrize("field,value", [("source_type", "secondary"), ("claim", "Afirmación ajena sintética.")])
def test_replay_rejects_snapshot_provenance_and_text_not_sent(tmp_path, config, field, value):
    path = write_synthetic_dataset(tmp_path, config, [{"case_id": "provenance"}])
    add_trace(path)
    revise_trace(path, "input.json", lambda data: data["evidence"][0].update({field: value}))
    with pytest.raises(ValueError, match="enviad"):
        evaluation.evaluate_manifest(path)


def test_unknown_archived_context_is_audit_only_without_rebuilding_prompt(tmp_path, config):
    path = write_synthetic_dataset(tmp_path, config, [{"case_id": "old_format"}])
    add_trace(path)
    revise_trace(path, "input.json", lambda data: data["request_payload"]["messages"][0].update(content="Formato histórico sintético desconocido."))
    source = evaluation.read_json(path.parent / "trace/input.json")
    fingerprint = evaluation.digest({"provider": "anthropic", "operation": "messages",
                                     "account_ref": "synthetic-account", "payload": source["request_payload"]})
    revise_trace(path, "request.json", lambda data: data.update(request_fingerprint=fingerprint))
    revise_trace(path, "result.json", lambda data: data["usage"].update(request_fingerprint=fingerprint))
    row = evaluation.evaluate_manifest(path)["cases"][0]
    assert row["mode"] == "audit_only" and row["context_reproducibility"] == "unverified_format"
    assert row["input_sha256"] is None and row["evidence_scope"] == "available_only"
    assert row["priority"] == "high"
