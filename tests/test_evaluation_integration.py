"""De la captura al evaluador con SDK, empresas y respuestas exclusivamente sintéticos."""

import hashlib
import json

import httpx2
import pytest

from evaluate_qualification import ReviewedCriterion, evaluate_manifest
from prospecting.pipeline import qualification
from test_qualification import claude, message, output, scenario


def synthetic_copy(directory, target):
    """Crea una fixture nueva del transporte simulado; conserva intacta la captura original."""
    source = next(directory.iterdir())
    original = {path.name: path.read_bytes() for path in source.iterdir()}
    target.mkdir(parents=True)
    trace = json.loads(original["manifest.json"])
    for name in trace["artifacts"]:
        value = json.loads(original[name])
        if name == "input.json":
            value["origin"] = "synthetic"
        content = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        (target / name).write_bytes(content)
        trace["artifacts"][name] = hashlib.sha256(content).hexdigest()
    trace_file = target / "manifest.json"
    trace_file.write_text(json.dumps(trace), encoding="utf-8")
    manifest = {
        "schema_version": "evaluation_manifest_v1", "dataset_version": "synthetic_roundtrip_v1",
        "created_at": "2026-10-13T12:00:00Z",
        "inventory": {"status": "pending", "historical_coverage": "pending",
                      "reference": "Fixture de integración sintética; no valida Veryfi."},
        "cases": [{"case_id": "synthetic_roundtrip", "split": "development", "origin": "synthetic",
                   "country": "CO", "segment": "fintech_software", "group_keys": [],
                   "artifact": {"path": "trace/manifest.json",
                                "sha256": hashlib.sha256(trace_file.read_bytes()).hexdigest()}}],
    }
    dataset_file = target.parent / "manifest.json"
    dataset_file.write_text(json.dumps(manifest), encoding="utf-8")
    assert {path.name: path.read_bytes() for path in source.iterdir()} == original
    return dataset_file


@pytest.mark.parametrize(("condition", "mode", "priority", "error"), [
    ("valid", "replay", "medium", None),
    ("reuse", "audit_only", "medium", None),
    ("invalid", "replay", None, "max_tokens"),
    ("timeout", "trace_without_response", None, "timeout"),
    ("no_authorization", "trace_without_response", None, "authorization_required"),
    ("storage", "incomplete_trace", None, "trace_capture_failed"),
    ("response_storage", "incomplete_trace", "medium", None),
])
def test_pipeline_capture_is_consumed_without_any_new_call(
        claude, tmp_path, monkeypatch, condition, mode, priority, error):
    if condition == "reuse":
        claude.qualify()
    elif condition == "invalid":
        claude.reply = message("{salida sintética truncada", stop_reason="max_tokens")
    elif condition == "timeout":
        def timeout(request):
            raise httpx2.ReadTimeout("Fallo exclusivamente sintético.", request=request)
        claude.failure = timeout
    elif condition in {"storage", "response_storage"}:
        write = qualification._EvaluationTrace.write
        failed_artifact = "request.json" if condition == "storage" else "response.json"
        if condition == "response_storage":
            claude.reply = message(output(claude))
            claude.reply["model"] = "claude-haiku-5-5-synthetic-resolved"
        def fail_request(trace, name, value):
            if name == failed_artifact:
                raise OSError("Fallo de almacenamiento exclusivamente sintético.")
            write(trace, name, value)
        monkeypatch.setattr(qualification._EvaluationTrace, "write", fail_request)
    directory = tmp_path / "data" / "captured"
    kwargs = {"authorization": None} if condition == "no_authorization" else {}
    claude.qualify(evaluation_dir=directory, **kwargs)
    dataset = synthetic_copy(directory, tmp_path / "dataset" / "trace")
    calls_before = len(claude.requests)
    usage_before = claude.db.list_usage()
    result = evaluate_manifest(dataset)
    row = result["cases"][0]
    assert row["origin"] == "synthetic" and row["mode"] == mode
    assert row["priority"] == priority and row["error_reason"] == error
    assert row["capture_error_reason"] == ("capture_incomplete" if condition in {"storage", "response_storage"} else None)
    if condition == "response_storage":
        assert row["model_id"] == claude.reply["model"]
        assert row["capture_metadata"]["requested_model_id"] == "claude-haiku-5-5"
    assert result["summaries"][0]["metrics"]["precision"]["value"] is None
    assert len(claude.requests) == calls_before and claude.db.list_usage() == usage_before
    assert evaluate_manifest(dataset) == result


def test_missing_annotation_is_not_a_resolved_unknown():
    review = {"status": "resolved", "evidence_ids": [], "reason": "La fuente sintética no permite determinarlo."}
    with pytest.raises(ValueError):
        ReviewedCriterion.model_validate(review)
    assert ReviewedCriterion.model_validate(review | {"value": None}).value is None
