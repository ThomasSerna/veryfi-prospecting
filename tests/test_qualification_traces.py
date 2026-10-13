"""Captura de evaluación con transporte y datos exclusivamente sintéticos, sin red."""

import hashlib
import json
from pathlib import Path

import httpx2
import pytest

from prospecting.models import BusinessStatus, Evidence, IdentityStatus, UsageStatus
from prospecting.pipeline import qualification
from prospecting.providers import ClaudeClient
from prospecting.qualification import build_haiku_request
from test_qualification import (
    ACCOUNT, RETRIEVED_AT, SYNTHETIC_KEY, claude, message, output, scenario,
)


@pytest.fixture(autouse=True)
def synthetic_data_root(tmp_path, monkeypatch):
    """Aísla la raíz protegida; las pruebas nunca escriben en los datos reales."""
    monkeypatch.setattr(qualification, "_EVALUATION_DATA_ROOT", tmp_path / "data")


def read_trace(directory):
    paths = list(directory.iterdir())
    assert len(paths) == 1
    return paths[0], {path.name: json.loads(path.read_text(encoding="utf-8"))
                      for path in paths[0].iterdir()}


def test_trace_freezes_request_response_versions_and_hashes(claude, tmp_path):
    directory = tmp_path / "data" / "evaluation"
    payload, selected = build_haiku_request(claude.company, claude.db.list_evidence(claude.company.id), claude.campaign)
    report = claude.qualify(evaluation_dir=directory)
    path, files = read_trace(directory)
    assert set(files) == {"input.json", "request.json", "response.json", "result.json", "manifest.json"}
    assert files["input.json"]["schema_version"] == "evaluation_trace_v1"
    assert files["input.json"]["origin"] == "new_real"  # El consumidor declara esta fixture como synthetic.
    assert files["input.json"]["trace_id"] == path.name
    assert files["input.json"]["request_payload"] == payload == json.loads(claude.requests[0].content)
    assert files["input.json"]["selected_evidence_ids"] == [str(item.id) for item in selected]
    assert files["input.json"]["rubric_version"] == "rubric_v1"
    assert files["input.json"]["catalog_version"] == "catalog_v1"
    assert files["input.json"]["prompt_version"] == qualification.PROMPT_VERSION
    assert files["input.json"]["code_hashes"]["prospecting/pipeline/qualification.py"] == hashlib.sha256(
        Path(qualification.__file__).read_bytes()).hexdigest()
    assert files["request.json"]["request_fingerprint"] == ClaudeClient.fingerprint(payload, ACCOUNT)
    assert files["response.json"]["text"] == output(claude)
    assert files["response.json"]["request_id"] == str(report.request_id)
    assert files["result.json"]["assessment"] == claude.db.get_assessment(report.assessment_id).model_dump(mode="json")
    assert files["result.json"]["report"] == report.model_dump(mode="json")
    assert files["result.json"]["usage"] == claude.db.get_usage(report.request_id).model_dump(mode="json")
    assert files["result.json"]["duration_seconds"] >= 0
    assert files["manifest.json"]["complete"] is True
    for name, digest in files["manifest.json"]["artifacts"].items():
        assert hashlib.sha256((path / name).read_bytes()).hexdigest() == digest
    contents = "".join(file.read_text(encoding="utf-8") for file in path.iterdir())
    assert SYNTHETIC_KEY not in contents and "Autorización sintética sin red" not in contents


def test_trace_excludes_contacts_but_keeps_manual_company_provenance(claude, tmp_path, make_contact):
    person, sources = make_contact(claude.company.id)
    claude.db.save_contact(person, evidence=sources)
    fact = Evidence(company_id=claude.company.id, contact_id=person.id, claim="Texto nominal sintético exclusivo.",
                    url="https://empresa-uno.example/persona", retrieved_at=RETRIEVED_AT,
                    kind="observed", source_type="primary")
    claude.db.save_evidence(fact)
    directory = tmp_path / "data" / "evaluation"
    claude.qualify(evaluation_dir=directory)
    _, files = read_trace(directory)
    evidence = files["input.json"]["evidence"]
    assert str(fact.id) not in {item["id"] for item in evidence}
    assert str(claude.manual.id) in {item["id"] for item in evidence}
    assert all(item["contact_id"] is None for item in evidence)
    assert "Texto nominal sintético exclusivo." not in json.dumps(files)


@pytest.mark.parametrize(("raw", "stop_reason", "reason"), [
    ("{JSON sintético inválido", "end_turn", "invalid_output"),
    ("{}", "max_tokens", "max_tokens"),
])
def test_raw_invalid_output_survives_with_paid_usage(claude, tmp_path, raw, stop_reason, reason):
    directory = tmp_path / "data" / "evaluation"
    claude.reply = message(raw, stop_reason=stop_reason)
    report = claude.qualify(evaluation_dir=directory)
    _, files = read_trace(directory)
    assert report.status == "pending" and report.reason == reason
    assert files["response.json"]["text"] == raw
    assert files["response.json"]["stop_reason"] == stop_reason
    assert files["result.json"]["assessment"] is None
    assert files["result.json"]["usage"]["status"] == "succeeded"
    assert files["manifest.json"]["complete"] is True
    assert len(claude.requests) == 1


def test_reuse_has_snapshot_without_fabricated_raw_latency_or_usage(claude, tmp_path):
    first = claude.qualify()
    directory = tmp_path / "data" / "evaluation"
    again = claude.qualify(evaluation_dir=directory)
    _, files = read_trace(directory)
    assert again.status == "already_assessed" and again.assessment_id == first.assessment_id
    assert set(files) == {"input.json", "result.json", "manifest.json"}
    assert files["input.json"]["origin"] == "saved_real"
    assert files["input.json"]["request_payload"] is None
    assert files["input.json"]["requested_model_id"] is None
    assert files["result.json"]["duration_seconds"] is None
    assert files["result.json"]["called_model"] is False
    assert files["result.json"]["usage"] is None
    assert len(claude.requests) == 1


@pytest.mark.parametrize("identity", ["pending", "confirmed"])
def test_without_model_is_captured_without_provider_response(claude, tmp_path, identity):
    if identity == "pending":
        claude.db.save_company(claude.company.model_copy(update={"identity_status": IdentityStatus.PENDING, "identity_key": None}))
    else:
        item = claude.db.get_run_item(claude.campaign.id, claude.company.id)
        claude.db.save_run_item(item.model_copy(update={"business_status": BusinessStatus.EXCLUDED}))
    directory = tmp_path / "data" / "evaluation"
    report = claude.qualify(evaluation_dir=directory)
    _, files = read_trace(directory)
    assert report.status == "assessed" and not report.called_model
    assert set(files) == {"input.json", "result.json", "manifest.json"}
    assert files["input.json"]["origin"] == "saved_real"
    assert files["result.json"]["assessment"]["model_id"] is None
    assert files["result.json"]["duration_seconds"] is None
    assert claude.requests == []


@pytest.mark.parametrize("relative", ["unsafe", "another-project/data/traces", "data/../external/data/traces"])
def test_capture_directory_outside_data_blocks_reservation_and_transport(claude, tmp_path, relative):
    directory = tmp_path / relative
    report = claude.qualify(evaluation_dir=directory)
    assert report.status == "pending" and report.reason == "trace_capture_failed"
    assert "Traza de evaluación incompleta" in report.error_message
    assert not directory.exists()
    assert claude.requests == [] and claude.db.list_usage() == []


@pytest.mark.parametrize("slow_artifact", ["input.json", "request.json"])
def test_capture_time_never_extends_the_provider_deadline(claude, tmp_path, monkeypatch, slow_artifact):
    expired = False
    original = qualification._EvaluationTrace.write

    def slow(trace, name, value):
        nonlocal expired
        original(trace, name, value)
        if name == slow_artifact:
            expired = True

    monkeypatch.setattr(qualification._EvaluationTrace, "write", slow)
    monkeypatch.setattr(qualification, "seconds_left", lambda deadline: -1 if expired else 1)
    report = claude.qualify(evaluation_dir=tmp_path / "data" / "evaluation", deadline=1)
    assert report.status == "pending" and report.reason == "time_limit"
    assert not report.called_model and claude.requests == []
    if slow_artifact == "input.json":
        assert claude.db.list_usage() == []
    else:
        assert claude.db.get_usage(report.request_id).status == UsageStatus.RESERVED


@pytest.mark.parametrize("failed_artifact", ["input.json", "request.json", "response.json", "result.json", "manifest.json"])
def test_capture_failure_preserves_checkpoints_and_never_retries(claude, tmp_path, monkeypatch, failed_artifact):
    original = qualification._EvaluationTrace.write

    def fail(trace, name, value):
        if name == failed_artifact:
            raise OSError("Fallo sintético de almacenamiento.")
        return original(trace, name, value)

    monkeypatch.setattr(qualification._EvaluationTrace, "write", fail)
    directory = tmp_path / "data" / "evaluation"
    report = claude.qualify(evaluation_dir=directory)
    assert "Traza de evaluación incompleta" in report.error_message
    item = claude.db.get_run_item(claude.campaign.id, claude.company.id)
    assert item.error_message == report.error_message
    _, files = read_trace(directory)
    assert failed_artifact not in files
    if failed_artifact != "manifest.json":
        assert files["manifest.json"]["complete"] is False
        assert files["manifest.json"]["capture_errors"]
    if failed_artifact in {"input.json", "request.json"}:
        assert report.status == "pending" and report.reason == "trace_capture_failed"
        assert not report.called_model and claude.requests == []
        if failed_artifact == "request.json":
            assert "reserva se conserva sin envío" in report.error_message
            assert claude.db.get_usage(report.request_id).status == UsageStatus.RESERVED
        else:
            assert claude.db.list_usage() == []
    else:
        assert report.status == "assessed" and report.called_model and len(claude.requests) == 1
        assert item.stage == "assessed" and item.last_assessment_id == report.assessment_id
        assert claude.db.get_usage(report.request_id).status == UsageStatus.SUCCEEDED
        assert claude.qualify().status == "already_assessed" and len(claude.requests) == 1


def test_timeout_trace_keeps_uncertain_usage_and_literal_provider_error(claude, tmp_path):
    def timeout(request):
        raise httpx2.ReadTimeout("Timeout exclusivamente sintético.", request=request)

    claude.failure = timeout
    directory = tmp_path / "data" / "evaluation"
    report = claude.qualify(evaluation_dir=directory)
    _, files = read_trace(directory)
    assert report.reason == "timeout" and report.called_model
    assert "consumo pendiente" in report.error_message
    assert "response.json" not in files
    assert files["result.json"]["usage"]["status"] == "uncertain"
    assert files["result.json"]["duration_seconds"] >= 0
    assert len(claude.requests) == 1


def test_exclusive_artifacts_and_trace_directories_never_overwrite(claude, tmp_path):
    directory = tmp_path / "data" / "evaluation"
    trace = qualification._EvaluationTrace(directory)
    trace.write("input.json", {"synthetic": True})
    before = (trace.path / "input.json").read_bytes()
    with pytest.raises(FileExistsError):
        trace.write("input.json", {"synthetic": False})
    assert (trace.path / "input.json").read_bytes() == before
    claude.qualify(evaluation_dir=directory)
    claude.qualify(evaluation_dir=directory)
    assert len(list(directory.iterdir())) == 3
    assert (trace.path / "input.json").read_bytes() == before
    assert len(claude.requests) == 1
