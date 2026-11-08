"""Conciliación de Apollo con comprobantes del panel exclusivamente sintéticos, sin red (T17)."""

from datetime import timedelta
from decimal import Decimal
from io import StringIO
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import django
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
import pytest

from prospecting.budget import AccountAllowance
from prospecting.db import Database
from prospecting.models import CampaignStatus, Usage, UsageStatus, utc_now
from prospecting.pipeline import ProviderAccess, reconcile_usage
from prospecting.providers.apollo import ApolloAccess


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

APOLLO = "apollo-sintetica"
PERSONAL = "persona.sintetica@example.com"


@pytest.fixture
def ledger(tmp_path, make_campaign):
    """Base temporal con una búsqueda y dos enriquecimientos de Apollo enviados entre dos lecturas del panel."""
    path = tmp_path / "synthetic.sqlite3"
    before = utc_now() - timedelta(minutes=10)
    with Database(path) as db:
        campaign = db.save_campaign(make_campaign().model_copy(update={"status": CampaignStatus.PARTIAL}))
        rows = []
        for operation, status, outcome, credits, error in (
                ("people_search", UsageStatus.SUCCEEDED, "succeeded", Decimal(0), None),
                ("people_enrichment", UsageStatus.SUCCEEDED, "succeeded", None, None),
                ("people_enrichment", UsageStatus.UNCERTAIN, "unknown", None, f"Timeout sintético de {PERSONAL}")):
            rows.append(db.save_usage(Usage(
                campaign_id=campaign.id, provider="apollo", operation=operation, account_ref=APOLLO,
                request_fingerprint=uuid4().hex * 2, reserved_cost_usd=Decimal(0),
                reserved_credits=Decimal(0 if operation == "people_search" else 1), credits=credits,
                funding_source="free_credit", status=status, outcome=outcome, error_message=error,
                created_at=before + timedelta(minutes=1 + len(rows)), finished_at=before + timedelta(minutes=2 + len(rows)))))
    access = ProviderAccess(
        tavily_account_ref="tavily-sintetica", claude_account_ref="claude-sintetica",
        apollo_access=ApolloAccess(account_ref=APOLLO, source_reference="Acceso sintético", observed_at=before,
                                   work_email_verified=True, access_verified=True),
        account_allowances=[
            AccountAllowance(provider="apollo", account_ref=APOLLO, funding_source="free_credit", credit_limit="100",
                             source_reference="Cupo sintético", observed_at=before),
            AccountAllowance(provider="tavily", account_ref="tavily-sintetica", funding_source="free_credit",
                             credit_limit="10", source_reference="Cupo sintético", observed_at=before),
            AccountAllowance(provider="anthropic", account_ref="claude-sintetica", funding_source="prepaid",
                             cost_limit_usd="1", source_reference="Cupo sintético", observed_at=before),
        ])
    access_path = tmp_path / "provider-access.json"
    access_path.write_text(access.model_dump_json(), encoding="utf-8")
    return SimpleNamespace(path=path, campaign=campaign, rows=rows, access=access, access_path=access_path,
                           before=before, tmp_path=tmp_path)


def receipt(case, **changes):
    """Panel de 10 a 11 créditos: la búsqueda no cobra, un enriquecimiento cobra 1 y el timeout no cobró."""
    data = {
        "version": "apollo_reconciliation_v1", "provider": "apollo", "account_ref": APOLLO,
        "responsible": "Responsable sintético",
        "panel_before": {"credits_used": "10", "observed_at": case.before.isoformat(), "source_reference": "Panel sintético antes"},
        "panel_after": {"credits_used": "11", "observed_at": utc_now().isoformat(), "source_reference": "Panel sintético después"},
        "attribution": "inferred_from_total", "attribution_note": "El panel solo informa el total de la cuenta.",
        "requests": [
            {"request_id": str(case.rows[0].request_id), "operation": "people_search", "outcome": "succeeded", "credits": "0"},
            {"request_id": str(case.rows[1].request_id), "operation": "people_enrichment", "outcome": "succeeded", "credits": "1"},
            {"request_id": str(case.rows[2].request_id), "operation": "people_enrichment", "outcome": "failed", "credits": "0"},
        ],
    } | changes
    path = case.tmp_path / f"apollo-{uuid4()}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def usage(case):
    with Database(case.path) as db:
        return db.list_usage()


def command(case, path, *options):
    out = StringIO()
    with override_settings(PROSPECTING_DB_PATH=case.path, PROSPECTING_ACCESS_PATH=case.access_path):
        call_command("reconcile_usage", str(path), *options, stdout=out)
    return out.getvalue()


def test_valid_receipt_reconciles_every_row_once_and_reports_without_personal_data(ledger):
    path = receipt(ledger)
    output = command(ledger, path)
    rows = {row.request_id: row for row in usage(ledger)}
    assert all(row.status == UsageStatus.RECONCILED for row in rows.values())
    assert [rows[item.request_id].credits for item in ledger.rows] == [0, 1, 0]
    assert "Conciliación aplicada" in output and "conciliadas ahora: 3" in output and "Créditos disponibles: 99" in output
    assert PERSONAL not in output and "Persona" not in output
    snapshot = usage(ledger)
    again = command(ledger, path)
    assert usage(ledger) == snapshot and "conciliadas ahora: 0; ya conciliadas: 3" in again


def test_dry_run_checks_the_receipt_without_writing(ledger):
    before = usage(ledger)
    output = command(ledger, receipt(ledger), "--dry-run")
    assert "Prueba sin escribir" in output and usage(ledger) == before


@pytest.mark.parametrize("changes, message", [
    ({"panel_after": {"credits_used": "12", "observed_at": "2026-01-01T00:00:00Z", "source_reference": "x"}},
     "comprobante de conciliación válido"),
    ({"attribution_note": None}, "comprobante de conciliación válido"),
    ({"external_credits": "1"}, "comprobante de conciliación válido"),
    ({"version": "apollo_reconciliation_v2"}, "comprobante de conciliación válido"),
    ({"account_ref": "otra-cuenta"}, "cuenta de Apollo configurada"),
])
def test_invalid_or_foreign_receipts_are_rejected_without_echo_or_writes(ledger, changes, message):
    before = usage(ledger)
    with pytest.raises(CommandError, match=message) as error:
        command(ledger, receipt(ledger, **changes))
    assert "Responsable sintético" not in str(error.value) and usage(ledger) == before


def test_sum_must_match_the_panel_and_cover_the_whole_window(ledger):
    before = usage(ledger)
    data = json.loads(receipt(ledger).read_text(encoding="utf-8"))
    with pytest.raises(CommandError, match="válido"):
        command(ledger, receipt(ledger, panel_after=data["panel_after"] | {"credits_used": "13"}))
    incomplete = data["requests"][:2]
    incomplete[1] = incomplete[1] | {"credits": "1"}
    with pytest.raises(CommandError, match="receipt_incomplete"):
        command(ledger, receipt(ledger, requests=incomplete))
    with pytest.raises(CommandError, match="otra cuenta|no es de esta cuenta"):
        command(ledger, receipt(ledger, requests=data["requests"][:2] + [
            data["requests"][2] | {"request_id": str(uuid4())}]))
    assert usage(ledger) == before


def test_contradiction_leaves_the_whole_receipt_unapplied(ledger):
    data = json.loads(receipt(ledger).read_text(encoding="utf-8"))
    command(ledger, receipt(ledger))
    before = usage(ledger)
    changed = [data["requests"][0], data["requests"][1] | {"credits": "0"}, data["requests"][2] | {"credits": "1"}]
    with pytest.raises(CommandError, match="reconciliation_conflict"):
        command(ledger, receipt(ledger, requests=changed))
    assert usage(ledger) == before


def test_running_campaign_or_missing_database_block_reconciliation(ledger, tmp_path):
    with Database(ledger.path) as db:
        db.save_campaign(ledger.campaign.model_copy(update={"status": CampaignStatus.RUNNING}))
    before = usage(ledger)
    with pytest.raises(CommandError, match="campaña en ejecución"):
        command(ledger, receipt(ledger))
    assert usage(ledger) == before
    missing = tmp_path / "ausente" / "synthetic.sqlite3"
    with pytest.raises(ValueError, match="base local no existe"):
        reconcile_usage(missing, receipt(ledger), access=ledger.access)
    assert not missing.parent.exists()


def test_malformed_receipt_is_not_echoed(ledger):
    path = ledger.tmp_path / "roto.json"
    path.write_text('{"responsible": "Responsable sintético", ', encoding="utf-8")
    with pytest.raises(CommandError) as error:
        command(ledger, path)
    assert "Responsable" not in str(error.value)
