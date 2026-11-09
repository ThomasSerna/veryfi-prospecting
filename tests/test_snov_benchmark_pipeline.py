"""Seguridad y recuperación del experimento exclusivamente con datos y transporte sintéticos."""

from datetime import timedelta
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest

from experiments.snov_benchmark import pipeline
from experiments.snov_benchmark.contracts import manifest_digest
from experiments.snov_benchmark.fixtures import build_fixture_inputs, FixtureTransport
from experiments.snov_benchmark.report import report_capture
from experiments.snov_benchmark.transport import BenchmarkProviderError, BenchmarkTransport
from prospecting.models import utc_now


def fresh_approval(manifest, approval):
    now = utc_now()
    return approval.model_copy(update={"session_id": uuid4(), "approved_at": now,
        "manifest_sha256": manifest_digest(manifest),
        "approvals": [grant.model_copy(update={"authorized_at": now}) for grant in approval.approvals]})


def test_both_arms_use_same_pipeline_and_isolated_ledger(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    transport = FixtureTransport()
    captures = pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=transport)
    assert len(captures) == 4
    assert all(item.status == "completed" for item in captures)
    report = report_capture(manifest, captures)
    assert report["comparison_complete"]
    assert {item[0] for item in transport.calls} == {"apollo", "snov"}
    assert report["providers"]["snov"]["useful_contacts"] == 0
    assert report["providers"]["apollo"]["useful_contacts"] == 0
    assert all(item["final_cost_usd"] is None for item in report["providers"].values())
    with sqlite3.connect(tmp_path / "ledger.sqlite3") as db:
        assert db.execute("select distinct stage from run_items").fetchall() == [("discovered",)]
        assert db.execute("select count(*) from usage where operation='opening_balance'").fetchone()[0] == 2
        assert db.execute("select sum(cast(reserved_credits as real)) from usage where provider='snov' and operation='people_enrichment'").fetchone()[0] == 4
        assert db.execute("select sum(cast(reserved_credits as real)) from usage where provider='snov' and operation='people_enrichment_result'").fetchone()[0] == 0
    assert not (tmp_path / "prospecting.sqlite3").exists()


@pytest.mark.parametrize("change,code", [
    ("access", "access_unverified"), ("cost", "operation_unbounded"),
    ("expired", "authorization_expired"), ("hash", "approval_manifest_mismatch"),
    ("config", "config_changed"), ("operations", "authorization_required"),
])
def test_failed_preflight_never_authenticates_or_creates_output(tmp_path, change, code):
    manifest, access, approval = build_fixture_inputs()
    if change == "access":
        access[0] = access[0].model_copy(update={"access_verified": False})
    elif change == "cost":
        access[1] = access[1].model_copy(update={"operation_bounds": {}})
    elif change == "expired":
        approval = approval.model_copy(update={"approved_at": utc_now() - timedelta(hours=2)})
    elif change == "hash":
        approval = approval.model_copy(update={"manifest_sha256": "0" * 64})
    elif change == "config":
        manifest = manifest.model_copy(update={"config_versions": {"veryfi_sha256": "0" * 64}})
    else:
        approval = approval.model_copy(update={"approvals": approval.approvals[:-1]})
    transport = FixtureTransport()
    output = tmp_path / "uncreated"
    with pytest.raises(ValueError, match=code):
        pipeline.run_benchmark(manifest, access, approval, output, transport=transport)
    assert not output.exists()
    assert transport.calls == []


def test_live_missing_credentials_never_sends_including_oauth(tmp_path, monkeypatch):
    manifest, access, approval = build_fixture_inputs()
    manifest = manifest.model_copy(update={"origin": "real"})
    approval = fresh_approval(manifest, approval)
    for key in ("APOLLO_API_KEY", "SNOV_CLIENT_ID", "SNOV_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    transport = FixtureTransport()
    with pytest.raises(ValueError, match="credentials_missing"):
        pipeline.run_benchmark(manifest, access, approval, tmp_path / "no-output", live=True, transport=transport)
    assert transport.calls == []
    assert not (tmp_path / "no-output").exists()


def test_synthetic_mode_rejects_real_transport(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    with pytest.raises(ValueError, match="transporte real"):
        pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=BenchmarkTransport())


def test_reservation_is_claimed_before_reveal(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    class InspectTransport(FixtureTransport):
        def send(self, spec, **kwargs):
            if spec.operation == "people_enrichment":
                with sqlite3.connect(tmp_path / "ledger.sqlite3") as db:
                    status, credits = db.execute("select status,reserved_credits from usage where provider=? and operation=? order by created_at desc limit 1",
                        (spec.provider, spec.operation)).fetchone()
                assert status == "in_flight" and int(credits) == 1
            return super().send(spec, **kwargs)
    captures = pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=InspectTransport())
    assert all(item.status == "completed" for item in captures)


def test_lost_post_retains_reservation_and_never_repeats(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    class LostPost(FixtureTransport):
        def send(self, spec, **kwargs):
            if spec.provider == "snov" and spec.operation == "people_enrichment":
                self.calls.append((spec.provider, spec.operation, spec.path))
                raise BenchmarkProviderError("timeout", "Timeout sintético literal")
            return super().send(spec, **kwargs)
    transport = LostPost()
    first = pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=transport)
    snov = [item for item in first if item.provider == "snov"]
    assert snov[0].status == "uncertain" and snov[1].status == "blocked"
    assert snov[0].errors[-1]["message"] == "Timeout sintético literal"
    with sqlite3.connect(tmp_path / "ledger.sqlite3") as db:
        row = db.execute("select status,reserved_credits,credits from usage where provider='snov' and operation='people_enrichment'").fetchone()
        assert row == ("uncertain", "1", None)
    before = list(transport.calls)
    pipeline.run_benchmark(manifest, access, fresh_approval(manifest, approval), tmp_path, transport=transport)
    assert transport.calls == before


def test_permission_failure_keeps_literal_error_and_stops_provider(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    class Denied(FixtureTransport):
        def send(self, spec, **kwargs):
            if spec.provider == "snov" and spec.operation == "people_search":
                self.calls.append((spec.provider, spec.operation, spec.path))
                raise BenchmarkProviderError("http_403", "Permiso sintético denegado", http_status=403)
            return super().send(spec, **kwargs)
    transport = Denied()
    captures = pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=transport)
    snov = [item for item in captures if item.provider == "snov"]
    assert snov[0].status == "blocked"
    assert snov[0].requests[-1]["http_status"] == 403
    assert snov[0].requests[-1]["outcome"] == "failed"
    assert sum(provider == "snov" and op == "people_search" for provider, op, _ in transport.calls) == 1


def test_people_limit_counts_attempts_and_not_only_successes(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    manifest = manifest.model_copy(update={"limits": manifest.limits.model_copy(update={"max_people": 1})})
    approval = fresh_approval(manifest, approval)
    transport = FixtureTransport()
    captures = pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=transport)
    assert all(sum(person.enriched for person in capture.candidates) == 1 for capture in captures)
    assert sum(op == "people_enrichment" for _, op, _ in transport.calls) == 4


def test_approval_cannot_be_reused_and_manifest_cannot_replace_results(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=FixtureTransport())
    evidence = pipeline.read_json(tmp_path / ".approval-sessions" / f"{approval.session_id}.json")
    assert evidence["approval"] == approval.model_dump(mode="json")
    assert evidence["access"] == [item.model_dump(mode="json") for item in access]
    original = (tmp_path / "capture.json").read_bytes()
    with pytest.raises(FileExistsError):
        pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=FixtureTransport())
    changed = manifest.model_copy(update={"source_reference": "otra muestra sintética"})
    with pytest.raises(ValueError, match="otra muestra"):
        pipeline.run_benchmark(changed, access, fresh_approval(changed, approval), tmp_path, transport=FixtureTransport())
    assert (tmp_path / "capture.json").read_bytes() == original


def test_experiment_lock_rejects_concurrent_runner(tmp_path):
    with pipeline.experiment_lock(tmp_path):
        with pytest.raises(ValueError, match="Otra ejecución"):
            with pipeline.experiment_lock(tmp_path):
                pytest.fail("No debe adquirir el mismo bloqueo.")
    with pipeline.experiment_lock(tmp_path):
        pass


def test_real_paths_must_be_inside_experiment(tmp_path):
    with pytest.raises(ValueError, match="expedientes reales"):
        pipeline.private_path(tmp_path / "outside.json")


def test_cli_fixtures_and_report(tmp_path, capsys):
    from experiments.snov_benchmark.__main__ import main
    output = tmp_path / "fixtures"
    assert main(["fixtures", "--output", str(output)]) == 0
    assert "sin red" in capsys.readouterr().out
    target = output / "repeated-report.json"
    assert main(["report", "--manifest", str(output / "manifest.json"), "--capture",
                 str(output / "capture.json"), "--output", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["origin"] == "synthetic"


def test_report_never_overwrites_manifest_capture_or_existing_report(tmp_path):
    from experiments.snov_benchmark.__main__ import main
    assert main(["fixtures", "--output", str(tmp_path)]) == 0
    for name in ("manifest.json", "capture.json", "report.json", "state.json", "ledger.sqlite3"):
        target = tmp_path / name
        original = target.read_bytes()
        assert main(["report", "--manifest", str(tmp_path / "manifest.json"), "--capture",
            str(tmp_path / "capture.json"), "--output", str(target)]) == 2
        assert target.read_bytes() == original


def test_resume_preserves_original_response_dates_without_new_requests(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    captures = pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=FixtureTransport())
    original_dates = [person.retrieved_at for person in captures[0].candidates]
    state = pipeline.read_json(tmp_path / "state.json")
    state["captures"][0]["status"] = "blocked"
    pipeline.write_json(tmp_path / "state.json", state)
    transport = FixtureTransport()
    resumed = pipeline.run_benchmark(manifest, access, fresh_approval(manifest, approval), tmp_path, transport=transport)
    assert resumed[0].status == "completed"
    assert [person.retrieved_at for person in resumed[0].candidates] == original_dates
    assert transport.calls == []


def test_resume_cannot_replace_accounts_or_funding(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=FixtureTransport())
    access[0] = access[0].model_copy(update={"account_ref": "another-synthetic-account"})
    changed = fresh_approval(manifest, approval)
    changed = changed.model_copy(update={"approvals": [grant.model_copy(update={"account_ref": "another-synthetic-account"})
        if grant.provider == "apollo" else grant for grant in changed.approvals]})
    transport = FixtureTransport()
    with pytest.raises(ValueError, match="cuentas, cupos"):
        pipeline.run_benchmark(manifest, access, changed, tmp_path, transport=transport)
    assert transport.calls == []


def test_missing_apollo_domain_waits_for_enrichment_identity(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    class MissingDomain(FixtureTransport):
        def send(self, spec, **kwargs):
            response = super().send(spec, **kwargs)
            if spec.provider == "apollo" and spec.operation == "people_search":
                raw = json.loads(response.body)
                for person in raw["people"]:
                    person["organization"].pop("primary_domain")
                return self._response(raw)
            return response
    captures = pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=MissingDomain())
    assert all(sum(person.enriched for person in capture.candidates) == 2 for capture in captures if capture.provider == "apollo")


def test_other_snov_entity_is_never_revealed(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    class WrongDomain(FixtureTransport):
        def send(self, spec, **kwargs):
            response = super().send(spec, **kwargs)
            if spec.provider == "snov" and spec.operation == "people_search_result":
                raw = json.loads(response.body)
                raw["data"]["prospects"][0]["company"]["domain"] = "other-entity.example"
                return self._response(raw)
            return response
    transport = WrongDomain()
    captures = pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=transport)
    assert all(sum(person.enriched for person in capture.candidates) == 1 for capture in captures if capture.provider == "snov")
    assert sum(provider == "snov" and op == "people_enrichment" for provider, op, _ in transport.calls) == 2


def test_pending_task_resumes_from_hash_without_restarting_post(tmp_path, monkeypatch):
    manifest, access, approval = build_fixture_inputs()
    class Pending(FixtureTransport):
        pending = True
        def send(self, spec, **kwargs):
            if spec.provider == "snov" and spec.operation == "people_search_result" and self.pending:
                self.pending = False
                self.calls.append((spec.provider, spec.operation, spec.path))
                return self._response({"status": "in_progress", "data": []})
            return super().send(spec, **kwargs)
    transport = Pending()
    def pause(_):
        raise pipeline._Stop("time_limit", "Pausa sintética controlada")
    with monkeypatch.context() as patch:
        patch.setattr(pipeline.time, "sleep", pause)
        first = pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=transport)
    assert next(item for item in first if item.provider == "snov").status == "blocked"
    captures = pipeline.run_benchmark(manifest, access, fresh_approval(manifest, approval), tmp_path, transport=transport)
    assert all(item.status == "completed" for item in captures)
    assert sum(provider == "snov" and op == "people_search" for provider, op, _ in transport.calls) == 2


def test_polling_and_request_caps_are_enforced_before_more_network(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    class ForeverPending(FixtureTransport):
        def send(self, spec, **kwargs):
            if spec.provider == "snov" and spec.operation == "people_search_result":
                self.calls.append((spec.provider, spec.operation, spec.path))
                return self._response({"status": "in_progress", "data": []})
            return super().send(spec, **kwargs)
    transport = ForeverPending()
    captures = pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=transport)
    snov = next(item for item in captures if item.provider == "snov")
    assert snov.errors[-1]["code"] == "poll_limit"
    assert sum(op == "people_search_result" for _, op, _ in transport.calls) == manifest.limits.max_polls
    assert pipeline.read_json(tmp_path / "state.json")["active_seconds"] > 0


def test_live_rates_cannot_exceed_documented_caps(monkeypatch):
    manifest, access, approval = build_fixture_inputs()
    manifest = manifest.model_copy(update={"origin": "real"})
    approval = fresh_approval(manifest, approval)
    for name in ("APOLLO_API_KEY", "SNOV_CLIENT_ID", "SNOV_CLIENT_SECRET"):
        monkeypatch.setenv(name, "fixture-only")
    assert "rate_unverified" in pipeline.preflight(manifest, access, approval, live=True)


def test_existing_ledger_without_checkpoint_is_never_opened_or_replaced(tmp_path, monkeypatch):
    manifest, access, approval = build_fixture_inputs()
    ledger = tmp_path / "ledger.sqlite3"
    original = b"Historial exclusivamente sintetico que no debe reemplazarse"
    ledger.write_bytes(original)
    def forbidden(*args, **kwargs):
        pytest.fail("No se debe abrir ni migrar este ledger.")
    monkeypatch.setattr(pipeline, "Database", forbidden)
    transport = FixtureTransport()
    with pytest.raises(ValueError, match="sin checkpoint"):
        pipeline.run_benchmark(manifest, access, approval, tmp_path, transport=transport)
    assert ledger.read_bytes() == original
    assert transport.calls == []


def test_checkpoint_with_missing_ledger_never_recreates_paid_usage(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    original = tmp_path / "original"
    pipeline.run_benchmark(manifest, access, approval, original, transport=FixtureTransport())
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    state = (original / "state.json").read_bytes()
    (incomplete / "state.json").write_bytes(state)
    transport = FixtureTransport()
    with pytest.raises(ValueError, match="no se recrea"):
        pipeline.run_benchmark(manifest, access, fresh_approval(manifest, approval), incomplete, transport=transport)
    assert not (incomplete / "ledger.sqlite3").exists()
    assert (incomplete / "state.json").read_bytes() == state
    assert transport.calls == []


def test_deeply_nested_input_fails_without_traceback_or_network(tmp_path, capsys, monkeypatch):
    from experiments.snov_benchmark.__main__ import main
    source = tmp_path / "nested.json"
    source.write_text("[" * 1200 + "0" + "]" * 1200, encoding="utf-8")
    def decoder_exhausted(*args, **kwargs):
        raise RecursionError("Límite sintético del decodificador")
    monkeypatch.setattr(pipeline.json, "loads", decoder_exhausted)
    assert main(["preflight", "--manifest", str(source), "--access", str(source), "--approvals", str(source)]) == 2
    assert "profundidad permitida" in capsys.readouterr().err
