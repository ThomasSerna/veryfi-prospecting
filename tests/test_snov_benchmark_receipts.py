"""Conciliación sintética: los comprobantes se validan completos antes de cambiar el expediente."""

from datetime import timedelta
import json
from uuid import uuid4

import pytest

from experiments.snov_benchmark.contracts import manifest_digest
from experiments.snov_benchmark.fixtures import FixtureTransport, build_fixture_inputs
from experiments.snov_benchmark.pipeline import run_benchmark
from experiments.snov_benchmark.receipts import apply_receipts
import experiments.snov_benchmark.receipts as receipts_module
from experiments.snov_benchmark.report import report_capture
from prospecting.budget import BudgetError
from prospecting.db import Database
from prospecting.models import utc_now


@pytest.fixture
def experiment(tmp_path):
    manifest, access, approval = build_fixture_inputs()
    output = tmp_path / "synthetic"
    transport = FixtureTransport()
    captures = run_benchmark(manifest, access, approval, output, transport=transport)
    assert all(item.status == "completed" for item in captures)
    return manifest, captures, output, transport


def bundle(experiment, providers=("apollo", "snov")):
    manifest, _, output, _ = experiment
    with Database(output / "ledger.sqlite3") as db:
        usage = db.list_usage(campaign_id=manifest.benchmark_id)
    observed = utc_now().isoformat()
    return {"schema_version": "snov_benchmark_receipts_v1", "benchmark_id": str(manifest.benchmark_id),
            "manifest_sha256": manifest_digest(manifest), "origin": "synthetic", "responsible": "Revisor sintético",
            "receipts": [{"request_id": str(row.request_id), "confirmation": {
                "outcome": "succeeded", "credits": "1" if row.operation == "people_enrichment" else "0",
                "final_cost_usd": "0", "outlay_usd": "0", "source_reference": "fixture:panel-sintetico",
                "observed_at": observed}}
                for row in usage if row.provider in providers]}


def write_packet(output, payload, name="receipt-input.json"):
    path = output / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def snapshot(output):
    with Database(output / "ledger.sqlite3") as db:
        rows = sorted((row.model_dump(mode="json") for row in db.list_usage()), key=lambda item: item["request_id"])
    archived = {path.name: path.read_bytes() for path in (output / "receipts").glob("*.json")}
    return rows, (output / "capture.json").read_bytes(), (output / "state.json").read_bytes(), archived


def test_consumption_becomes_known_only_after_attributed_receipts(experiment):
    manifest, captures, output, transport = experiment
    before_calls = len(transport.calls)
    before = report_capture(manifest, captures)
    assert all(metrics["credits"] is None and metrics["final_cost_usd"] is None
               for metrics in before["providers"].values())
    payload = bundle(experiment)
    updated = apply_receipts(manifest, captures, write_packet(output, payload), output / "capture.json")
    after = report_capture(manifest, updated)
    assert all(metrics["credits"] == "4" and metrics["final_cost_usd"] == "0"
               for metrics in after["providers"].values())
    assert all(metrics["cost_per_useful_contact_usd"] is None for metrics in after["providers"].values())
    assert len(transport.calls) == before_calls
    assert len(list((output / "receipts").glob("*.json"))) == 1
    with Database(output / "ledger.sqlite3") as db:
        assert all(row.status == "reconciled" for row in db.list_usage(campaign_id=manifest.benchmark_id))
    assert json.loads((output / "capture.json").read_text(encoding="utf-8")) == [item.model_dump(mode="json") for item in updated]


def test_one_provider_can_be_reconciled_without_claiming_the_other_consumption(experiment):
    manifest, captures, output, _ = experiment
    payload = bundle(experiment, ("apollo",))
    updated = apply_receipts(manifest, captures, write_packet(output, payload), output / "capture.json")
    metrics = report_capture(manifest, updated)["providers"]
    assert metrics["apollo"]["credits"] == "4"
    assert metrics["snov"]["credits"] is metrics["snov"]["final_cost_usd"] is None


def test_identical_receipt_is_idempotent_and_contradiction_preserves_previous_values(experiment):
    manifest, captures, output, _ = experiment
    payload = bundle(experiment)
    path = write_packet(output, payload)
    updated = apply_receipts(manifest, captures, path, output / "capture.json")
    first = snapshot(output)
    repeated = apply_receipts(manifest, updated, path, output / "capture.json")
    assert snapshot(output) == first
    assert repeated == updated
    changed = json.loads(json.dumps(payload))
    charged = next(item for item in changed["receipts"] if item["confirmation"]["credits"] == "1")
    charged["confirmation"]["credits"] = "2"
    with pytest.raises(BudgetError, match="contradice"):
        apply_receipts(manifest, repeated, write_packet(output, changed, "contradictory.json"), output / "capture.json")
    assert snapshot(output) == first


@pytest.mark.parametrize("change", ["missing", "duplicate", "foreign_request", "origin", "manifest", "benchmark",
                                        "future_date", "old_date", "unknown_outcome"])
def test_invalid_receipt_does_not_mutate_any_usage_capture_or_checkpoint(experiment, change):
    manifest, captures, output, _ = experiment
    payload = bundle(experiment)
    if change == "missing":
        payload["receipts"].pop()
    elif change == "duplicate":
        payload["receipts"].append(payload["receipts"][0])
    elif change == "foreign_request":
        payload["receipts"][0]["request_id"] = str(uuid4())
    elif change == "origin":
        payload["origin"] = "real"
    elif change == "manifest":
        payload["manifest_sha256"] = "a" * 64
    elif change == "benchmark":
        payload["benchmark_id"] = str(uuid4())
    elif change == "future_date":
        payload["receipts"][-1]["confirmation"]["observed_at"] = (utc_now() + timedelta(days=1)).isoformat()
    elif change == "old_date":
        payload["receipts"][-1]["confirmation"]["observed_at"] = (utc_now() - timedelta(days=1)).isoformat()
    elif change == "unknown_outcome":
        payload["receipts"][-1]["confirmation"]["outcome"] = "unknown"
    before = snapshot(output)
    with pytest.raises((ValueError, BudgetError)):
        apply_receipts(manifest, captures, write_packet(output, payload), output / "capture.json")
    assert snapshot(output) == before


def test_checkpoint_mismatch_rejects_receipts_before_mutations(experiment):
    manifest, captures, output, _ = experiment
    payload = bundle(experiment)
    captures[0].status = "blocked"
    before = snapshot(output)
    with pytest.raises(ValueError, match="checkpoint"):
        apply_receipts(manifest, captures, write_packet(output, payload), output / "capture.json")
    assert snapshot(output) == before


@pytest.mark.parametrize("field,value", [("provider", "snov"), ("operation", "forged_operation")])
def test_capture_provenance_cannot_override_ledger_even_with_matching_checkpoint(experiment, field, value):
    manifest, captures, output, _ = experiment
    payload = bundle(experiment)
    if field == "provider":
        captures[0].provider = value
    else:
        captures[0].requests[0]["operation"] = value
    checkpoint = json.loads((output / "state.json").read_text(encoding="utf-8"))
    checkpoint["captures"] = [item.model_dump(mode="json") for item in captures]
    (output / "state.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    (output / "capture.json").write_text(json.dumps(checkpoint["captures"]), encoding="utf-8")
    before = snapshot(output)
    with pytest.raises(ValueError, match="procedencia"):
        apply_receipts(manifest, captures, write_packet(output, payload), output / "capture.json")
    assert snapshot(output) == before


def test_late_invalid_provider_rolls_back_preview_of_the_first_provider(experiment):
    manifest, captures, output, _ = experiment
    payload = bundle(experiment)
    apollo_ids = {row["request_id"] for capture in captures if capture.provider == "apollo" for row in capture.requests}
    payload["receipts"].sort(key=lambda item: item["request_id"] not in apollo_ids)
    payload["receipts"] = payload["receipts"][:-1]
    before = snapshot(output)
    with pytest.raises(ValueError, match="todas las solicitudes"):
        apply_receipts(manifest, captures, write_packet(output, payload), output / "capture.json")
    assert snapshot(output) == before


def test_receipt_retry_recovers_when_capture_write_failed_after_ledger_and_checkpoint(experiment, monkeypatch):
    manifest, captures, output, _ = experiment
    path = write_packet(output, bundle(experiment))
    original_write = receipts_module.write_json

    def fail_capture_write(target, payload):
        if target == output / "capture.json":
            raise OSError("Fallo sintético al guardar la captura.")
        original_write(target, payload)

    with monkeypatch.context() as patch:
        patch.setattr(receipts_module, "write_json", fail_capture_write)
        with pytest.raises(OSError, match="sintético"):
            apply_receipts(manifest, captures, path, output / "capture.json")
    recovered = apply_receipts(manifest, captures, path, output / "capture.json")
    assert all(row["credits"] == "4" for row in report_capture(manifest, recovered)["providers"].values())
