"""Bloqueos y privacidad de T21 con entradas exclusivamente sintéticas."""

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

import evaluate_enterprise_pipeline as evaluation
import evaluate_qualification as qualification_evaluation
from prospecting.db import Database
from prospecting.models import Campaign, Company, Evidence, RunItem, Usage
from test_enterprise_evaluation import manual_dataset


def pending_plan(tmp_path, role_config):
    config_path = tmp_path / "config.json"
    config_path.write_text(role_config.model_dump_json(), encoding="utf-8")
    plan = {
        "schema_version": "pipeline_evaluation_plan_v1",
        "created_at": "2026-01-01T00:00:00Z",
        "responsible": "Responsable sintético",
        "source_reference": "Prueba sintética sin autorización de gasto.",
        "config": {"path": config_path.name, "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest()},
        "inventory": {"status": "pending", "historical_coverage": "pending",
                      "reference": "Inventario sintético pendiente.", "historical_group_keys": []},
        "selection_policy": "Cinco cuentas por celda, sin reemplazos por resultados negativos.",
        "campaign_ids": {f"{country}:{segment}": str(uuid4()) for country, segment in evaluation.CELLS},
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return plan_path


def test_pending_run_preserves_database_and_never_opens_sqlite(tmp_path, role_config, monkeypatch):
    monkeypatch.setattr(evaluation, "DATA_ROOT", tmp_path)
    plan = pending_plan(tmp_path, role_config)
    db_path = tmp_path / "operational.sqlite3"
    original = "Historial sintético que debe permanecer intacto.".encode("utf-8")
    db_path.write_bytes(original)

    def forbidden(*args, **kwargs):
        pytest.fail("Un preflight pendiente intentó abrir la base o ejecutar el pipeline.")

    monkeypatch.setattr("sqlite3.connect", forbidden)
    monkeypatch.setattr(evaluation, "prepare_campaign", forbidden)
    monkeypatch.setattr(evaluation, "execute_campaign", forbidden)
    result = evaluation.run_plan(plan, country="CO", segment="fintech_software", db_path=db_path,
        access_path=tmp_path / "missing-access.json", approvals_path=tmp_path / "missing-approvals.json",
        output=tmp_path / "attempt")

    assert result["status"] == "blocked"
    assert {"independence_pending", "t14_gate_pending", "ledger_consolidation_pending",
            "authorization_required"} <= set(result["blockers"])
    assert db_path.read_bytes() == original
    capture = evaluation.load_capture(tmp_path / "attempt" / "capture.json")
    assert capture.status == "blocked" and capture.view is None and capture.usage is None


def test_run_does_not_create_an_empty_operational_database(tmp_path, role_config, monkeypatch):
    monkeypatch.setattr(evaluation, "DATA_ROOT", tmp_path)
    plan = pending_plan(tmp_path, role_config)
    db_path = tmp_path / "missing.sqlite3"
    result = evaluation.run_plan(plan, country="MX", segment="cpg_loyalty", db_path=db_path,
        access_path=tmp_path / "missing-access.json", approvals_path=tmp_path / "missing-approvals.json",
        output=tmp_path / "attempt")
    assert result["status"] == "blocked" and "ledger_missing" in result["blockers"]
    assert not db_path.exists()


def test_existing_output_is_never_overwritten(tmp_path, role_config, monkeypatch):
    monkeypatch.setattr(evaluation, "DATA_ROOT", tmp_path)
    plan = pending_plan(tmp_path, role_config)
    output = tmp_path / "attempt"
    output.mkdir()
    marker = output / "capture.json"
    marker.write_text("captura sintética anterior", encoding="utf-8")
    with pytest.raises(FileExistsError):
        evaluation.run_plan(plan, country="CO", segment="fintech_software", db_path=tmp_path / "db.sqlite3",
            access_path=tmp_path / "access.json", approvals_path=tmp_path / "approvals.json", output=output)
    assert marker.read_text(encoding="utf-8") == "captura sintética anterior"


def test_real_capture_cannot_be_saved_outside_data(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "DATA_ROOT", tmp_path / "private")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    capture = evaluation.PipelineCapture(schema_version="pipeline_capture_v1", origin="saved_real", country="CO", segment="fintech_software",
        plan_sha256="0" * 64, started_at=now, evaluated_at=now,
        status="blocked", blockers=["t14_gate_pending"])
    with pytest.raises(ValueError, match="data"):
        evaluation.save_capture(tmp_path / "public.json", capture)
    assert not (tmp_path / "public.json").exists()


def test_blocked_report_keeps_unknown_outcomes_and_hides_literal_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "DATA_ROOT", tmp_path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    capture = evaluation.PipelineCapture(schema_version="pipeline_capture_v1", origin="saved_real", country="CO", segment="fintech_software",
        plan_sha256="0" * 64, started_at=now, evaluated_at=now, status="blocked",
        blockers=["t14_gate_pending"], errors=["Error sintético: persona@example.com"])
    path = tmp_path / "capture.json"
    evaluation.save_capture(path, capture)

    def forbidden(*args, **kwargs):
        pytest.fail("El informe offline intentó abrir SQLite o acceder a la red.")

    monkeypatch.setattr("sqlite3.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    first = evaluation.report_captures([path])
    second = evaluation.report_captures([path])
    assert first == second
    assert first["real_coverage"] == "pending" and first["commercial_validation"] == "pending"
    assert first["totals"]["companies"] is None and first["totals"]["ready"] is None
    assert first["cost_per_useful_contact_usd"] is None and first["automatic_seconds"] is None
    assert "persona@example.com" not in json.dumps(first)


def authorized_synthetic_run(tmp_path, role_config, monkeypatch):
    """Aísla guardas del arnés; las comprobaciones T14 y el transporte son dobles sintéticos."""
    monkeypatch.setattr(evaluation, "DATA_ROOT", tmp_path)
    plan_path = pending_plan(tmp_path, role_config)
    plan = evaluation.read_json(plan_path)
    db_path = tmp_path / "operational.sqlite3"
    history = Campaign(countries=["CO"], segments=["fintech_software"], config_snapshot=role_config,
                       status="completed")
    with Database(db_path) as db:
        db.save_campaign(history)
        db.save_usage(Usage(campaign_id=history.id, provider="apollo", operation="people_search",
            account_ref="synthetic", request_fingerprint="a" * 64, reserved_cost_usd="0", reserved_credits="0",
            final_cost_usd="0", credits="0", funding_source="free_credit", status="reconciled", outcome="succeeded"))
    plan["inventory"].update(status="verified", historical_coverage="verified",
                             historical_group_keys=["group:historial-sintetico"])
    plan["t14"] = {name: {"path": "unused-synthetic.json", "sha256": "0" * 64}
                   for name in evaluation.GateFiles.model_fields}
    plan["ledger"] = {"db_sha256": evaluation.file_hash(db_path), "responsible": "Responsable sintético",
                      "source_reference": "Conciliación sintética.", "verified_at": "2026-01-01T00:00:00Z"}
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    session = {"schema_version": "pipeline_approval_session_v1", "session_id": str(uuid4()),
        "campaign_id": plan["campaign_ids"]["CO:fintech_software"], "approved_at": "2026-01-02T00:00:00Z",
        "approvals": [{"provider": "apollo", "operation": "people_search", "account_ref": "synthetic",
                       "max_cost_usd": "0", "max_credits": "0", "responsible": "Responsable sintético",
                       "source_reference": "Permiso exclusivamente sintético."}]}
    approvals = tmp_path / "approvals.json"
    approvals.write_text(json.dumps(session), encoding="utf-8")
    access = tmp_path / "access.json"
    access.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(evaluation, "verify_gate", lambda *_: {"group:historial-sintetico"})
    monkeypatch.setattr(evaluation, "load_provider_access", lambda *_: SimpleNamespace(account_allowances=[]))
    monkeypatch.setattr(evaluation, "provider_operations", lambda *_: [("apollo", "people_search", "synthetic")])
    monkeypatch.setattr(evaluation, "load_icp_enterprise", lambda *_: SimpleNamespace(reference_companies=[]))
    calls = []

    def execute(db_path, campaign_id, **kwargs):
        calls.append(kwargs)
        return evaluation.CampaignReport(campaign_id=campaign_id, status="partial", exclusions_status="pending")

    monkeypatch.setattr(evaluation, "execute_campaign", execute)
    return SimpleNamespace(plan_path=plan_path, plan=plan, db_path=db_path, session=session, approvals=approvals,
                           access=access, calls=calls)


def invoke_run(case, output, **kwargs):
    return evaluation.run_plan(case.plan_path, country="CO", segment="fintech_software", db_path=case.db_path,
        access_path=case.access, approvals_path=case.approvals, output=output, **kwargs)


def test_session_for_another_cell_never_executes(tmp_path, role_config, monkeypatch):
    case = authorized_synthetic_run(tmp_path, role_config, monkeypatch)
    case.session["campaign_id"] = case.plan["campaign_ids"]["MX:cpg_loyalty"]
    case.approvals.write_text(json.dumps(case.session), encoding="utf-8")
    result = invoke_run(case, tmp_path / "attempt")
    assert result["status"] == "blocked" and "authorization_session_mismatch" in result["blockers"]
    assert case.calls == [] and not (tmp_path / ".t21-approvals").exists()


def test_pending_preflight_does_not_consume_a_fresh_session(tmp_path, role_config, monkeypatch):
    case = authorized_synthetic_run(tmp_path, role_config, monkeypatch)
    case.plan["t14"] = None
    case.plan_path.write_text(json.dumps(case.plan), encoding="utf-8")
    assert invoke_run(case, tmp_path / "attempt")["status"] == "blocked"
    assert case.calls == [] and not (tmp_path / ".t21-approvals").exists()


def test_used_session_cannot_be_reused_from_a_copied_plan(tmp_path, role_config, monkeypatch):
    case = authorized_synthetic_run(tmp_path, role_config, monkeypatch)
    first = invoke_run(case, tmp_path / "attempt")
    assert first["status"] in {"complete", "incomplete"} and len(case.calls) == 1
    marker = tmp_path / ".t21-approvals" / f"{case.session['session_id']}.json"
    assert marker.is_file()
    copied = tmp_path / "copied-plan"
    copied.mkdir()
    (copied / "config.json").write_bytes((tmp_path / "config.json").read_bytes())
    case.plan_path = copied / "plan.json"
    case.plan["ledger"]["db_sha256"] = evaluation.file_hash(case.db_path)
    case.plan_path.write_text(json.dumps(case.plan), encoding="utf-8")
    second = invoke_run(case, tmp_path / "attempt2")
    assert second["status"] == "blocked" and "authorization_reused" in second["blockers"]
    assert len(case.calls) == 1


@pytest.mark.parametrize("change", [{"countries": ["MX"]}, {"max_companies": 20}])
def test_prepared_campaign_must_match_the_selected_cell(tmp_path, role_config, monkeypatch, change):
    case = authorized_synthetic_run(tmp_path, role_config, monkeypatch)
    monkeypatch.setattr(evaluation, "prepare_campaign",
                        lambda _, campaign: campaign.model_copy(update=change))
    result = invoke_run(case, tmp_path / "attempt")
    assert result["status"] == "incomplete" and case.calls == []
    assert not (tmp_path / ".t21-approvals").exists()


def test_other_cells_are_excluded_even_without_previous_capture_paths(tmp_path, role_config, monkeypatch):
    case = authorized_synthetic_run(tmp_path, role_config, monkeypatch)
    previous = Campaign(id=case.plan["campaign_ids"]["MX:cpg_loyalty"], countries=["MX"],
                        segments=["cpg_loyalty"], config_snapshot=role_config, status="completed")
    company_id = uuid4()
    fact = Evidence(company_id=company_id, claim="Cuenta sintética anterior, dominio previous.example.",
                    url="https://previous.example", kind="observed", source_type="primary",
                    retrieved_at=datetime(2026, 1, 1, tzinfo=UTC))
    company = Company(id=company_id, name="Cuenta sintética anterior", domain="previous.example",
                      provenance={"name": [fact.id], "domain": [fact.id]})
    with Database(case.db_path) as db:
        db.save_campaign(previous)
        db.save_company(company, evidence=[fact])
        db.save_run_item(RunItem(campaign_id=previous.id, company_id=company.id))
    case.plan["ledger"]["db_sha256"] = evaluation.file_hash(case.db_path)
    case.plan_path.write_text(json.dumps(case.plan), encoding="utf-8")
    invoke_run(case, tmp_path / "attempt")
    assert len(case.calls) == 1
    exclusions = evaluation.load_exclusions(case.calls[0]["exclusions_path"])
    assert any("previous.example" in entry.domains for entry in exclusions.entries)


@pytest.fixture
def passed_gate_files(tmp_path, config):
    # El helper usa formato saved_real para probar el protocolo con contenido enteramente sintético.
    manifest, candidate, reviews = manual_dataset(tmp_path, config)
    development = qualification_evaluation.evaluate_manual(manifest, candidate, reviews)
    protocol = tmp_path / "protocol.json"
    qualification_evaluation.freeze_manual_protocol(development, protocol)
    report = qualification_evaluation.evaluate_manual(manifest, candidate, reviews,
        split="evaluation", protocol_path=protocol)
    assert report["activation_gate"]["status"] == "passed"
    development_path, report_path = tmp_path / "development.json", tmp_path / "evaluation.json"
    qualification_evaluation.write_new(development_path, development)
    qualification_evaluation.write_new(report_path, report)
    paths = {"report": report_path, "development_report": development_path,
             "manifest": manifest, "reviews": reviews, "protocol": protocol}
    files = evaluation.GateFiles(**{name: {"path": str(path.relative_to(tmp_path)),
                                          "sha256": evaluation.file_hash(path)} for name, path in paths.items()})
    return files, config, paths


def test_passed_gate_is_verified_without_reopening_the_holdout(tmp_path, passed_gate_files):
    files, config, _ = passed_gate_files
    original = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    forbidden = evaluation.verify_gate(tmp_path, files, config)
    assert forbidden
    assert len(list(tmp_path.glob(".holdout-*.json"))) == 1
    assert original == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}


def test_development_only_cannot_be_used_as_activation_proof(tmp_path, passed_gate_files):
    files, config, _ = passed_gate_files
    invalid = files.model_copy(update={"report": files.development_report})
    with pytest.raises(ValueError):
        evaluation.verify_gate(tmp_path, invalid, config)


def test_changed_t14_inputs_are_rejected_before_any_pipeline_execution(tmp_path, passed_gate_files):
    files, config, paths = passed_gate_files
    paths["reviews"].write_bytes(paths["reviews"].read_bytes() + b" ")
    with pytest.raises(ValueError):
        evaluation.verify_gate(tmp_path, files, config)


def test_public_report_does_not_copy_free_text_provider_or_blocker_fields(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    capture = evaluation.PipelineCapture(schema_version="pipeline_capture_v1", origin="synthetic", country="CO",
        segment="fintech_software", plan_sha256="0" * 64, started_at=now, evaluated_at=now, status="incomplete",
        blockers=["persona-sintetica@example.com"], usage=[Usage(campaign_id=uuid4(),
            provider="persona-sintetica@example.com", operation="Nombre privado sintético",
            request_fingerprint="0" * 64, status="failed")])
    path = tmp_path / "synthetic.json"
    evaluation.save_capture(path, capture)
    report = evaluation.report_captures([path])
    assert report["blockers"] == ["other"]
    assert report["operations"][0]["provider"] == report["operations"][0]["operation"] == "other"
    assert "persona-sintetica@example.com" not in json.dumps(report)
    assert "Nombre privado" not in json.dumps(report)
