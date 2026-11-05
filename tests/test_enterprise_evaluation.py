"""Referencias enteramente sintéticas; simulan formatos reales sin datos ni llamadas reales."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

import evaluate_qualification as evaluation
from prospecting.models import Rubric
from test_evaluation import revise_case, write_reference, write_synthetic_dataset


def manual_dataset(tmp_path, config, *, saved_format=True):
    """Representa 32 expedientes con fuentes .example y revisores sintéticos."""
    definitions = []
    for split, total in (("development", 3), ("evaluation", 5)):
        for country in ("CO", "MX"):
            for segment in ("fintech_software", "cpg_loyalty"):
                for index in range(total):
                    values = ([1, 1, 0, .5, 0] if index == 0 else
                              [1, 1, .5, 1, 1] if index == 1 else [0, 0, 1, 1, 1])
                    definitions.append({"case_id": f"{split}_{country}_{segment}_{index}", "split": split,
                        "country": country, "segment": segment, "values": values,
                        "acceptance": "accepted" if index < 2 else "rejected"})
    path = write_synthetic_dataset(tmp_path, config, definitions)
    manifest = evaluation.read_json(path)
    candidate = {"version": "rubric_v2", "rubric": config.rubrics["rubric_v2"]}
    reviews = {"schema_version": "enterprise_reviews_v1", "rubric_version": "rubric_v2",
               "rubric_sha256": evaluation.digest(candidate["rubric"].model_dump(mode="json")), "cases": []}
    for case in manifest["cases"]:
        snapshot = evaluation.read_json(path.parent / case["artifact"]["path"])
        snapshot.update(assessment=None, origin="saved_real" if saved_format else "synthetic")
        case["origin"] = snapshot["origin"]
        case["artifact"] = write_reference(path.parent, case["artifact"]["path"], snapshot)
        label = evaluation.read_json(path.parent / case["label"]["path"])
        label.update(snapshot_sha256=case["artifact"]["sha256"], audits=[])
        case["label"] = write_reference(path.parent, case["label"]["path"], label)
        scale = dict(label, label_id=f"{case['case_id']}-scale", version="scale_v2",
                     criteria={"scale_potential": dict(label["criteria"]["scale_potential"], value=1,
                         evidence_ids=[snapshot["evidence"][0]["id"]])})
        if not case["case_id"].endswith("_0"):
            scale["criteria"]["scale_potential"] = label["criteria"]["scale_potential"]
        reviews["cases"].append({"case_id": case["case_id"], "snapshot_sha256": case["artifact"]["sha256"],
            "scale_label": scale, "excluded": {"value": False, "reason": "Revisión sintética de exclusiones."},
            "contradiction": {"value": False, "reason": "Revisión sintética de contradicciones."}})
    manifest["inventory"].update(status="verified", historical_coverage="verified",
                                  historical_group_keys=["group:referencia_sintetica_excluida"])
    write_reference(path.parent, path.name, manifest)
    write_reference(path.parent, "reviews.json", reviews)
    return path, candidate, path.parent / "reviews.json"


def change_reviews(path, change):
    data = evaluation.read_json(path)
    change(data)
    write_reference(path.parent, path.name, data)


def test_manual_four_scenarios_are_pure_and_do_not_evaluate_model(tmp_path, config, monkeypatch):
    manifest, candidate, reviews = manual_dataset(tmp_path, config)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    monkeypatch.setattr("socket.socket.connect", lambda *_: pytest.fail("Intentó acceder a red."))
    monkeypatch.setattr("sqlite3.connect", lambda *_: pytest.fail("Intentó abrir SQLite."))
    report = evaluation.evaluate_manual(manifest, candidate, reviews)
    assert report["development_checks"]["status"] == "passed"
    assert report["activation_gate"]["status"] == "pending"
    assert len(report["cases"]) == 12 and all(row["case_id"].startswith("development") for row in report["cases"])
    assert all(set(row["scenarios"]) == {"v1", "weights_only", "scale_v2", "v2"} for row in report["cases"])
    assert report["haiku_validated"] is False and "model_id" not in json.dumps(report)
    assert report["development_checks"]["mean_position_after"] < report["development_checks"]["mean_position_before"]
    assert "no mide la precisión de Haiku" in evaluation.render_markdown(report)
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}


def test_synthetic_cases_cannot_approve_activation(tmp_path, config):
    manifest, candidate, reviews = manual_dataset(tmp_path, config, saved_format=False)
    report = evaluation.evaluate_manual(manifest, candidate, reviews)
    assert report["development_checks"]["status"] == "pending"
    assert "synthetic_cases" in report["development_checks"]["pending_reasons"]


def test_holdout_is_once_and_protocol_allows_later_blind_holdout_annotations(tmp_path, config):
    manifest, candidate, reviews = manual_dataset(tmp_path, config)
    raw = evaluation.read_json(manifest)
    later_labels = {case["case_id"]: case["label"] for case in raw["cases"] if case["split"] == "evaluation"}
    for case in raw["cases"]:
        if case["split"] == "evaluation":
            case["label"] = None
    write_reference(manifest.parent, manifest.name, raw)
    original_reviews = evaluation.read_json(reviews)
    pending_reviews = json.loads(json.dumps(original_reviews))
    for item in pending_reviews["cases"]:
        if item["case_id"].startswith("evaluation"):
            item["scale_label"] = None
    write_reference(reviews.parent, reviews.name, pending_reviews)
    development = evaluation.evaluate_manual(manifest, candidate, reviews)
    protocol = tmp_path / "protocol.json"
    evaluation.freeze_manual_protocol(development, protocol)
    pending = evaluation.evaluate_manual(manifest, candidate, reviews, split="evaluation", protocol_path=protocol)
    assert pending["activation_gate"]["status"] == "pending"
    assert all(not row["scenarios"] for row in pending["cases"])
    assert not list(tmp_path.glob(".holdout-*.json"))
    for case in raw["cases"]:
        if case["case_id"] in later_labels:
            case["label"] = later_labels[case["case_id"]]
    write_reference(manifest.parent, manifest.name, raw)
    write_reference(reviews.parent, reviews.name, original_reviews)
    report = evaluation.evaluate_manual(manifest, candidate, reviews, split="evaluation", protocol_path=protocol)
    assert report["activation_gate"]["status"] == "passed"
    assert len(report["cases"]) == 20 and len(list(tmp_path.glob(".holdout-*.json"))) == 1
    with pytest.raises(FileExistsError):
        evaluation.evaluate_manual(manifest, candidate, reviews, split="evaluation", protocol_path=protocol)


@pytest.mark.parametrize("change", [
    lambda data: data.update(rubric_sha256="f" * 64),
    lambda data: data.update(rubric_version="rubric_v1"),
    lambda data: data["cases"][0].update(snapshot_sha256="f" * 64),
    lambda data: data["cases"].append(data["cases"][0]),
    lambda data: data["cases"][0]["scale_label"]["criteria"].update(document_need={"status": "resolved", "value": None, "reason": "Ajeno."}),
    lambda data: data["cases"][0]["scale_label"]["criteria"]["scale_potential"].update(evidence_ids=["00000000-0000-4000-8000-000000000999"]),
    lambda data: data["cases"][0]["excluded"].update(value=True, evidence_ids=["00000000-0000-4000-8000-000000000999"]),
    lambda data: data["cases"][0]["scale_label"].update(prediction_visible=True),
    lambda data: data["cases"][0]["scale_label"].update(reference_type="Veryfi"),
])
def test_manual_rejects_wrong_rubric_snapshot_scope_and_reviews(tmp_path, config, change):
    manifest, candidate, reviews = manual_dataset(tmp_path, config)
    change_reviews(reviews, change)
    with pytest.raises(ValueError):
        evaluation.evaluate_manual(manifest, candidate, reviews)


def test_pending_and_resolved_unknown_are_different(tmp_path, config):
    manifest, candidate, reviews = manual_dataset(tmp_path, config)
    change_reviews(reviews, lambda data: data["cases"][0]["scale_label"]["criteria"]["scale_potential"].update(value=None, evidence_ids=[]))
    row = evaluation.evaluate_manual(manifest, candidate, reviews)["cases"][0]
    assert row["complete"] and row["scenarios"]["v2"]["coverage"] == .65
    change_reviews(reviews, lambda data: data["cases"][0]["scale_label"]["criteria"]["scale_potential"].update(status="pending"))
    row = evaluation.evaluate_manual(manifest, candidate, reviews)["cases"][0]
    assert not row["complete"] and row["scenarios"] == {}


def test_other_semantics_thresholds_and_model_snapshots_are_rejected(tmp_path, config):
    manifest, candidate, reviews = manual_dataset(tmp_path, config)
    for change in (lambda item: item["criteria"]["document_need"].update(strong_signal="Otra definición."),
                   lambda item: item["thresholds"]["high"].update(fit_score_min=99)):
        raw = candidate["rubric"].model_dump(mode="json")
        change(raw)
        other = {"version": "rubric_v2", "rubric": Rubric.model_validate(raw)}
        change_reviews(reviews, lambda data: data.update(rubric_sha256=evaluation.digest(other["rubric"].model_dump(mode="json"))))
        with pytest.raises(ValueError, match="otros criterios"):
            evaluation.evaluate_manual(manifest, other, reviews)
    trace = write_synthetic_dataset(tmp_path / "assessed", config)
    change_reviews(reviews, lambda data: data.update(cases=[], rubric_sha256=evaluation.digest(candidate["rubric"].model_dump(mode="json"))))
    with pytest.raises(ValueError, match="sin evaluación"):
        evaluation.evaluate_manual(trace, candidate, reviews)


@pytest.mark.parametrize("kind", ["candidate", "development_review", "development_label", "selection"])
def test_frozen_protocol_rejects_changed_inputs(tmp_path, config, kind):
    manifest, candidate, reviews = manual_dataset(tmp_path, config)
    protocol = tmp_path / "protocol.json"
    evaluation.freeze_manual_protocol(evaluation.evaluate_manual(manifest, candidate, reviews), protocol)
    if kind == "candidate":
        raw = candidate["rubric"].model_dump(mode="json")
        raw["criteria"]["scale_potential"]["strong_signal"] += " Otra guía."
        candidate = {"version": "rubric_v2", "rubric": Rubric.model_validate(raw)}
        change_reviews(reviews, lambda data: data.update(rubric_sha256=evaluation.digest(raw)))
    elif kind == "development_review":
        change_reviews(reviews, lambda data: data["cases"][0]["excluded"].update(reason="Otra revisión."))
    elif kind == "development_label":
        revise_case(manifest, 0, "label", lambda data: data.update(reason="Otro criterio académico."))
    else:
        raw = evaluation.read_json(manifest)
        raw["dataset_version"] += "-changed"
        write_reference(manifest.parent, manifest.name, raw)
    with pytest.raises(ValueError, match="congelar"):
        evaluation.evaluate_manual(manifest, candidate, reviews, split="evaluation", protocol_path=protocol)
    assert not list(tmp_path.glob(".holdout-*.json"))


@pytest.mark.parametrize("failure", ["new_false_positive", "lost_documented", "ranking", "empty_cohort"])
def test_gate_checks_each_requirement_and_empty_denominator(failure):
    def decision(priority, position):
        return {"priority": priority, "position": position}
    rows = [{"case_id": "accepted", "complete": True, "acceptance": "accepted", "document_need": 1, "scale_v2": 1,
             "scenarios": {"v1": decision("medium", 2), "v2": decision("high", 1)}},
            {"case_id": "rejected", "complete": True, "acceptance": "rejected", "document_need": .5, "scale_v2": .5,
             "scenarios": {"v1": decision("low", 1), "v2": decision("low", 2)}}]
    if failure == "new_false_positive":
        rows[1]["scenarios"]["v2"]["priority"] = "medium"
    elif failure == "lost_documented":
        rows[0]["scenarios"]["v2"]["priority"] = "low"
    elif failure == "ranking":
        rows[0]["scenarios"]["v2"]["position"] = 2
    else:
        rows[0]["scale_v2"] = .5
    gate = evaluation._manual_gate(rows, eligible=True, reasons=[])
    assert gate["status"] == ("pending" if failure == "empty_cohort" else "failed")


def test_manual_blind_files_include_enterprise_context_without_predictions(tmp_path, config, monkeypatch):
    manifest, candidate, reviews = manual_dataset(tmp_path, config)
    monkeypatch.setattr(evaluation, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(evaluation, "evaluate_manifest", lambda *_: pytest.fail("Calculó resultados para preparar fichas."))
    output = tmp_path / "blind"
    evaluation.prepare_blind(manifest, output, manual_candidate=candidate)
    blind = evaluation.read_json(output / "development_CO_fintech_software_0-blind.json")
    assert "size" in blind["company"] and blind["scale_rubric_version"] == "rubric_v2"
    assert not {"assessment", "fit_score", "priority"} & blind.keys()
    template = evaluation.read_json(output / "manual-reviews-template.json")
    assert len(template["cases"]) == 32 and template["cases"][0]["scale_label"] is None
    assert len(list(output.iterdir())) == 97


def test_pending_holdout_has_no_predictions_or_false_positive_measurement(tmp_path, config):
    manifest, candidate, reviews = manual_dataset(tmp_path, config)
    change_reviews(reviews, lambda data: data["cases"][12]["excluded"].update(value=None))
    report = evaluation.evaluate_manual(manifest, candidate, reviews, split="evaluation")
    assert report["activation_gate"]["status"] == "pending"
    assert all(not row["scenarios"] for row in report["cases"])
    assert all(item["evaluated"] == 0 and all(value is None for value in item["false_positives_academic"].values())
               for item in report["summaries"])
    assert "No calculable" in evaluation.render_markdown(report)
    assert not list(tmp_path.glob(".holdout-*.json"))


def test_cli_rejects_incompatible_holdout_flags_before_opening(tmp_path, config):
    manifest, candidate, reviews = manual_dataset(tmp_path, config)
    candidate_file = tmp_path / "candidate.json"
    write_reference(tmp_path, candidate_file.name, {"version": candidate["version"], "rubric": candidate["rubric"].model_dump(mode="json")})
    result = subprocess.run([sys.executable, str(Path(evaluation.__file__)), str(manifest),
        "--manual-reviews", str(reviews), "--rubric", str(candidate_file), "--partition", "evaluation",
        "--freeze-protocol", str(tmp_path / "bad-protocol.json")], capture_output=True, text=True)
    assert result.returncode == 2
    assert not list(tmp_path.glob(".holdout-*.json"))
    assert not (tmp_path / "bad-protocol.json").exists()


def test_holdout_verifies_development_label_bytes_after_freezing(tmp_path, config):
    manifest, candidate, reviews = manual_dataset(tmp_path, config)
    protocol = tmp_path / "protocol.json"
    evaluation.freeze_manual_protocol(evaluation.evaluate_manual(manifest, candidate, reviews), protocol)
    source = evaluation.read_json(manifest)
    label_path = manifest.parent / source["cases"][0]["label"]["path"]
    # La referencia permanece intacta: modificar bytes debe fallar antes de abrir el holdout.
    label_path.write_text(label_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        evaluation.evaluate_manual(manifest, candidate, reviews, split="evaluation", protocol_path=protocol)
    assert not list(tmp_path.glob(".holdout-*.json"))


def test_swapping_known_country_segment_cells_is_rejected_despite_balanced_quotas(tmp_path, config):
    manifest, candidate, reviews = manual_dataset(tmp_path, config)
    source = evaluation.read_json(manifest)
    first, second = source["cases"][12], source["cases"][27]
    first["country"], second["country"] = second["country"], first["country"]
    first["segment"], second["segment"] = second["segment"], first["segment"]
    write_reference(manifest.parent, manifest.name, source)
    with pytest.raises(ValueError, match="atribución conocida"):
        evaluation.evaluate_manual(manifest, candidate, reviews, split="evaluation")
    assert not list(tmp_path.glob(".holdout-*.json"))


def test_unknown_country_segment_attribution_keeps_holdout_pending_without_opening(tmp_path, config):
    manifest, candidate, reviews = manual_dataset(tmp_path, config)
    revise_case(manifest, 12, "artifact", lambda data: data["company"].update(operating_countries=None, segments=None))
    case = evaluation.read_json(manifest)["cases"][12]
    def align_review(data):
        data["cases"][12]["snapshot_sha256"] = case["artifact"]["sha256"]
        data["cases"][12]["scale_label"]["snapshot_sha256"] = case["artifact"]["sha256"]
    change_reviews(reviews, align_review)
    report = evaluation.evaluate_manual(manifest, candidate, reviews, split="evaluation")
    assert report["activation_gate"]["status"] == "pending"
    assert "cell_attribution_pending" in report["activation_gate"]["pending_reasons"]
    assert report["cases"][0]["cell_verified"] is False
    assert all(not row["scenarios"] for row in report["cases"])
    assert not list(tmp_path.glob(".holdout-*.json"))
