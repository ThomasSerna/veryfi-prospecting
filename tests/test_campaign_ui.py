"""Puente local T08 con campañas, contactos y permisos exclusivamente sintéticos, sin red."""

from datetime import timedelta
import csv
from io import StringIO
import sqlite3
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.presentation import download_csv
from prospecting.budget import AccountAllowance
from prospecting.db import Database
from prospecting.identity import ExclusionList
from prospecting.models import BusinessStatus, CampaignStatus, Channel, Contact, Evidence, RunItem, RunStage, Usage, utc_now
from prospecting.pipeline import (
    AuthorizationInput, ProviderAccess, execute_campaign, finish_campaign, list_saved_campaigns,
    load_provider_access, prepare_campaign, provider_operations, read_campaign, review_company,
)
from prospecting.pipeline import campaign as bridge


@pytest.fixture
def access():
    return ProviderAccess(
        tavily_account_ref="tavily-sintetica", claude_account_ref="claude-sintetica",
        account_allowances=[
            AccountAllowance(provider="tavily", account_ref="tavily-sintetica", funding_source="free_credit",
                             credit_limit="10", source_reference="Cupo sintético", observed_at=utc_now()),
            AccountAllowance(provider="anthropic", account_ref="claude-sintetica", funding_source="prepaid",
                             cost_limit_usd="1", source_reference="Cupo sintético", observed_at=utc_now()),
        ],
    )


def approval(**changes):
    return AuthorizationInput.model_validate({
        "provider": "tavily", "operation": "search", "account_ref": "tavily-sintetica",
        "max_cost_usd": "0", "max_credits": "5", "responsible": "Responsable sintético",
        "source_reference": "Aprobación sintética explícita",
    } | changes)


def test_missing_database_read_and_mutations_do_not_create_it(tmp_path, access):
    path = tmp_path / "ausente" / "synthetic.sqlite3"
    assert list_saved_campaigns(path) == []
    actions = [lambda: read_campaign(path, uuid4()), lambda: finish_campaign(path, uuid4()),
               lambda: review_company(path, uuid4(), uuid4(), status="pending", reason="Motivo sintético"),
               lambda: execute_campaign(path, uuid4(), access=access, approvals=[])]
    for action in actions:
        with pytest.raises(ValueError, match="base local no existe"):
            action()
    assert not path.parent.exists()


def test_prepare_persists_draft_reuses_id_and_active_campaign(tmp_path, make_campaign):
    path = tmp_path / "synthetic.sqlite3"
    campaign = make_campaign()
    first = prepare_campaign(path, campaign)
    assert first.status == "created"
    assert prepare_campaign(path, campaign.model_copy(update={"max_companies": 1})) == first
    with Database(path) as db:
        active = db.save_campaign(first.model_copy(update={"status": CampaignStatus.RUNNING}))
    assert prepare_campaign(path, make_campaign()) == active
    assert list_saved_campaigns(path) == [active]
    assert read_campaign(path, campaign.id).budget.campaign.confirmed == 0


def test_incompatible_saved_database_is_never_recreated(tmp_path, make_campaign):
    path = tmp_path / "synthetic.sqlite3"
    content = "Base sintética incompatible; conservar los bytes".encode("utf-8")
    path.write_bytes(content)
    for action in (lambda: list_saved_campaigns(path), lambda: prepare_campaign(path, make_campaign())):
        with pytest.raises(sqlite3.DatabaseError):
            action()
        assert path.read_bytes() == content


def test_finish_only_releases_campaign_and_preserves_checkpoints_ledger(tmp_path, records, persist_records):
    path = tmp_path / "synthetic.sqlite3"
    with Database(path) as db:
        persist_records(db, records)
        db.save_campaign(records.campaign.model_copy(update={"status": CampaignStatus.RUNNING}))
        item, usage = db.get_run_item(records.campaign.id, records.company.id), db.get_usage(records.usage.request_id)
    assert finish_campaign(path, records.campaign.id).status == "partial"
    with Database(path) as db:
        assert db.get_run_item(records.campaign.id, records.company.id) == item
        assert db.get_usage(usage.request_id) == usage
        assert db.get_active_campaign() is None


def test_read_never_reports_ready_without_an_assessment(tmp_path, make_campaign, make_company):
    path = tmp_path / "synthetic.sqlite3"
    campaign = prepare_campaign(path, make_campaign())
    company, evidence = make_company()
    with Database(path) as db:
        db.save_company(company, evidence=evidence)
        db.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id, business_status="ready_preferred"))
    assert read_campaign(path, campaign.id).companies[0].business_status is None


@pytest.mark.parametrize("content", ['{"secret":"NO-DEBE-MOSTRARSE"}', "{JSON inválido", "\ud800"])
def test_invalid_access_file_has_safe_error_without_fallback(tmp_path, content):
    path = tmp_path / "access.json"
    path.write_bytes(content.encode("utf-8", errors="surrogatepass"))
    with pytest.raises(ValueError) as error:
        load_provider_access(path)
    assert str(error.value) == "No se pudo leer la configuración válida de cupos y acceso a proveedores."
    with pytest.raises(ValueError):
        load_provider_access(tmp_path / "missing.json")


def test_access_roundtrip_has_no_permits_and_rejects_missing_conflicting_future_accounts(tmp_path, access):
    path = tmp_path / "access.json"
    path.write_text(access.model_dump_json(), encoding="utf-8")
    assert load_provider_access(path) == access
    for changes in (
        {"account_allowances": access.account_allowances[:1]},
        {"account_allowances": access.account_allowances + access.account_allowances[:1]},
        {"claude_funding_source": "new_outlay"},
        {"account_allowances": [item.model_copy(update={"observed_at": utc_now() + timedelta(days=1)})
                                for item in access.account_allowances]},
        {"authorizations": []},
    ):
        with pytest.raises(ValidationError):
            ProviderAccess.model_validate(access.model_dump() | changes)


def test_operations_respect_separate_hunter_accounts(access):
    hunter = {
        "search_account_ref": "hunter-search-sintetica", "verification_account_ref": "hunter-verify-sintetica",
        "enabled_operations": ["domain_search", "email_verifier"], "unified_credits": False,
        "automatic_lead_saving_disabled": True, "funding_source": "free_credit",
        "source_reference": "Comprobación sintética", "checked_at": utc_now(),
    }
    accounts = access.account_allowances + [AccountAllowance(
        provider="hunter", account_ref=account, funding_source="free_credit", credit_limit="10",
        source_reference="Cupo sintético", observed_at=utc_now()) for account in
        ("hunter-search-sintetica", "hunter-verify-sintetica")]
    checked = ProviderAccess.model_validate(access.model_dump() | {"hunter_access": hunter,
                                                                 "account_allowances": accounts})
    assert provider_operations(checked)[-2:] == [
        ("hunter", "domain_search", "hunter-search-sintetica"),
        ("hunter", "email_verifier", "hunter-verify-sintetica"),
    ]
    with pytest.raises(ValidationError):
        ProviderAccess.model_validate(checked.model_dump() | {
            "hunter_access": hunter | {"automatic_lead_saving_disabled": False},
        })

    domain_search_only = ProviderAccess.model_validate(checked.model_dump() | {
        "hunter_access": hunter | {"enabled_operations": ["domain_search"], "automatic_lead_saving_disabled": False},
    })
    assert provider_operations(domain_search_only)[-1] == ("hunter", "domain_search", "hunter-search-sintetica")


def test_execute_builds_fresh_grants_after_budget_and_preserves_campaign(tmp_path, make_campaign, access, monkeypatch):
    path = tmp_path / "synthetic.sqlite3"
    campaign = prepare_campaign(path, make_campaign())
    seen = []

    def simulated(db, campaign_id, exclusions, build):
        run = build(campaign)
        grant = run.authorizations[0]
        assert run.budget._session_started_at < grant.authorized_at <= utc_now()
        assert run.client.budget is run.budget and run.claude.budget is run.budget
        assert db.get_campaign(campaign_id).limits == campaign.limits
        assert not db._connection.in_transaction
        assert bridge._EXECUTION.locked()
        with pytest.raises(ValueError, match="ejecutándose"):
            finish_campaign(path, campaign_id)
        seen.append(grant)
        db.save_campaign(campaign.model_copy(update={"status": CampaignStatus.COMPLETED}))
        return bridge._report(db, campaign_id)

    monkeypatch.setattr(bridge, "_execute", simulated)
    assert execute_campaign(path, campaign.id, access=access, approvals=[approval()]).status == "completed"
    assert execute_campaign(path, campaign.id, access=access, approvals=[approval()]).status == "completed"
    assert len(seen) == 1
    with Database(path) as db:
        assert db.list_usage() == []


@pytest.mark.parametrize("changes, message", [
    ({"operation": "send"}, "operación"), ({"account_ref": "otra-cuenta"}, "operación"),
    ({"max_credits": "11"}, "créditos"), ({"max_cost_usd": "1"}, "económico"),
    ({"provider": "anthropic", "operation": "messages", "account_ref": "claude-sintetica",
      "max_cost_usd": "3", "max_credits": "0"}, "económico"),
])
def test_authorization_rejects_unbounded_or_unavailable_operation_before_client(
        tmp_path, make_campaign, access, monkeypatch, changes, message):
    path = tmp_path / "synthetic.sqlite3"
    campaign = prepare_campaign(path, make_campaign())
    monkeypatch.setattr(bridge, "ProviderClient", lambda *args: pytest.fail("No debe construir el cliente"))
    with pytest.raises(ValueError, match=message):
        execute_campaign(path, campaign.id, access=access, approvals=[approval(**changes)])
    assert list_saved_campaigns(path)[0].status == "created"


def test_duplicate_permissions_rejected_and_saved_unknown_cost_blocks_execution(tmp_path, make_campaign, access):
    path = tmp_path / "synthetic.sqlite3"
    campaign = prepare_campaign(path, make_campaign())
    with pytest.raises(ValueError, match="única operación"):
        execute_campaign(path, campaign.id, access=access, approvals=[approval(), approval()])
    with Database(path) as db:
        usage = db.save_usage(Usage(campaign_id=campaign.id, provider="tavily", operation="search",
                                   request_fingerprint="a" * 64, account_ref="tavily-sintetica", status="reserved"))
    with pytest.raises(ValueError, match="conciliación"):
        execute_campaign(path, campaign.id, access=access, approvals=[approval()])
    with Database(path) as db:
        assert db.get_usage(usage.request_id) == usage


def test_live_execution_blocks_review_close_and_does_not_register_permissions(
        tmp_path, make_campaign, make_company, access, monkeypatch):
    path = tmp_path / "synthetic.sqlite3"
    campaign = prepare_campaign(path, make_campaign())
    company, evidence = make_company()
    with Database(path) as db:
        db.save_company(company, evidence=evidence)
        db.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id))
    monkeypatch.setattr(bridge, "Budget", lambda *args: pytest.fail("No registra nuevos permisos"))
    with bridge._EXECUTION:
        for action in (
            lambda: finish_campaign(path, campaign.id),
            lambda: review_company(path, campaign.id, company.id, status="accepted", reason="Sintético"),
        ):
            with pytest.raises(ValueError, match="ejecutándose"):
                action()
        report = execute_campaign(path, campaign.id, access=access, approvals=[approval()])
        assert report.stop_reason == "campaign_already_running"


def test_review_survives_reopen_changes_only_review_and_preserves_unknowns(
        tmp_path, records, persist_records):
    path = tmp_path / "synthetic.sqlite3"
    with Database(path) as db:
        persist_records(db, records)
        original = db.get_run_item(records.campaign.id, records.company.id)
    reviewed = review_company(path, records.campaign.id, records.company.id, status="accepted", reason="Sintético")
    assert reviewed.review_status == "accepted" and reviewed.review_reason == "Sintético"
    assert reviewed.reviewed_at.utcoffset().total_seconds() == 0
    fields = {"review_status", "review_reason", "reviewed_at", "updated_at"}
    assert reviewed.model_dump(exclude=fields) == original.model_dump(exclude=fields)
    view = read_campaign(path, records.campaign.id)
    assert view.companies[0].run_item == reviewed
    assert view.budget.campaign.unknown and view.budget.campaign.available is None
    assert view.companies[0].assessment.fit_score is None
    with pytest.raises(ValueError):
        review_company(path, records.campaign.id, records.company.id, status="pending", reason=" ")
    with pytest.raises(ValueError, match="no pertenece"):
        review_company(path, records.campaign.id, uuid4(), status="pending", reason="Sintético")
    assert read_campaign(path, records.campaign.id).companies[0].run_item == reviewed


def test_read_recalculates_freshness_without_overwriting_persisted_checkpoint(
        tmp_path, make_campaign, make_company, make_assessment, monkeypatch):
    now = utc_now()
    path = tmp_path / "synthetic.sqlite3"
    campaign = prepare_campaign(path, make_campaign())
    company, company_evidence = make_company(domain="example.com", identity_status="confirmed",
                                             operating_countries=["CO", "MX"])
    assessment = make_assessment(campaign.id, company.id, priority="high", target_roles=["CTO"])
    contact_id = uuid4()
    source = Evidence(company_id=company.id, contact_id=contact_id, claim="Directorio profesional sintético",
                      excerpt="Persona Sintética Uno, CTO. persona@example.com", url="https://example.com/team",
                      retrieved_at=now, kind="observed", source_type="primary")
    verified = Evidence(company_id=company.id, contact_id=contact_id, claim="Email persona@example.com válido",
                        provider="hunter", external_reference="Verificación sintética", retrieved_at=now,
                        kind="observed", source_type="provider")
    contact = Contact(id=contact_id, company_id=company.id, name="Persona Sintética Uno", title="CTO",
                      name_complete=True, current_employment=True, relevant_function=True,
                      identity_status="confirmed", provenance={key: [source.id] for key in
                                                                 ("name", "title", "relevant_function")},
                      employment_evidence_ids=[source.id], channels=[Channel(
                          contact_id=contact_id, type="email", value="persona@example.com", evidence_ids=[verified.id],
                          normalized_status="verified", verified_at=now, retrieved_at=now, professional=True,
                          direct=True)])
    with Database(path) as db:
        db.save_company(company, evidence=company_evidence)
        item = db.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id))
        db.save_assessment(assessment)
        db.save_contact(contact, evidence=[source, verified])
        db.save_run_item(item.model_copy(update={"last_assessment_id": assessment.id,
                                               "business_status": BusinessStatus.READY_PREFERRED}))
    assert read_campaign(path, campaign.id).companies[0].business_status == "ready_preferred"
    exclusion_path = tmp_path / "synthetic-exclusions.json"
    exclusions = ExclusionList.model_validate({
        "version": "exclusiones-sinteticas-v1", "validation_status": "validated",
        "source_reference": "Lista sintética posterior al resultado", "observed_at": now,
        "entries": [{"id": "h1", "name": company.name, "domains": [company.domain], "scope": "entity",
                     "reason": "current_customer", "source_reference": "Fila sintética"}],
    })
    exclusion_path.write_text(exclusions.model_dump_json(), encoding="utf-8")
    with Database(path) as db:
        db.save_campaign(campaign.model_copy(update={"status": CampaignStatus.COMPLETED}))
        item = db.get_run_item(campaign.id, company.id)
        stored = db.save_run_item(item.model_copy(update={"stage": RunStage.COMPLETED}))
        previous_evidence, previous_usage = db.list_evidence(company.id), db.list_usage()
    excluded = read_campaign(path, campaign.id, exclusions_path=exclusion_path).companies[0]
    assert excluded.business_status == "excluded" and not excluded.contacts[0].eligible
    assert excluded.contacts[0].usable_channels == [] and excluded.run_item == stored
    assert list(csv.DictReader(StringIO(download_csv(
        path, campaign.id, exclusions_path=exclusion_path).decode("utf-8-sig")))) == []
    [row] = csv.DictReader(StringIO(download_csv(
        path, campaign.id, exclusions_path=exclusion_path, include_all=True).decode("utf-8-sig")))
    assert row["business_status"] == "excluded" and row["stored_business_status"] == "ready_preferred"
    with Database(path) as db:
        assert db.get_run_item(campaign.id, company.id) == stored
        assert db.list_assessments(campaign.id, company.id) == [assessment]
        assert db.list_evidence(company.id) == previous_evidence and db.list_usage() == previous_usage
    for country, expected in (("MX", "ready_preferred"), ("CO", "excluded")):
        entry = exclusions.entries[0].model_copy(update={"scope": "country", "countries": [country]})
        exclusion_path.write_text(exclusions.model_copy(update={"entries": [entry]}).model_dump_json(), encoding="utf-8")
        assert read_campaign(path, campaign.id, exclusions_path=exclusion_path).companies[0].business_status == expected
    entry = exclusions.entries[0].model_copy(update={"domains": ["otra-empresa.example"]})
    exclusion_path.write_text(exclusions.model_copy(update={"entries": [entry]}).model_dump_json(), encoding="utf-8")
    pending = read_campaign(path, campaign.id, exclusions_path=exclusion_path).companies[0]
    assert pending.business_status == "insufficient_evidence" and not pending.contacts[0].eligible
    assert pending.contacts[0].usable_channels == [] and pending.run_item == stored
    assert list(csv.DictReader(StringIO(download_csv(
        path, campaign.id, exclusions_path=exclusion_path).decode("utf-8-sig")))) == []
    with Database(path) as db:
        item = db.get_run_item(campaign.id, company.id)
        db.save_run_item(item.model_copy(update={"business_status": BusinessStatus.EXCLUDED}))
    excluded = read_campaign(path, campaign.id).companies[0]
    assert excluded.business_status == "excluded" and not excluded.contacts[0].eligible
    assert excluded.contacts[0].usable_channels == []
    with Database(path) as db:
        db.save_run_item(item.model_copy(update={"business_status": BusinessStatus.READY_PREFERRED}))
    monkeypatch.setattr(bridge, "utc_now", lambda: now + timedelta(days=31))
    result = read_campaign(path, campaign.id).companies[0]
    assert result.business_status == "qualified_no_contact"
    assert result.run_item.business_status == "ready_preferred"
    assert not result.contacts[0].eligible and result.contacts[0].usable_channels == []
