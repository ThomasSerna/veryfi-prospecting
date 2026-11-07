"""Barreras de migración y conservación histórica con datos exclusivamente sintéticos."""

from uuid import uuid4
from types import SimpleNamespace
from decimal import Decimal

import pytest

from prospecting.db import Database
from prospecting.budget import Budget
from prospecting.models import RunItem, Usage, utc_now
from prospecting.pipeline import (
    confirm_alternative_channel, execute_campaign, prepare_campaign, read_campaign, review_company, run_campaign,
)
from prospecting.pipeline import campaign as bridge
from prospecting.providers.apollo import ApolloSearchResponse, ApolloEnrichmentResponse, parse_search, parse_enrichment

from test_campaign_ui import access


@pytest.mark.parametrize("missing", ["key", "key_control", "key_unicode", "absent", "access", "work_email", "enrichment"])
def test_unchecked_apollo_blocks_before_authorization_or_any_provider(
        tmp_path, make_campaign, access, monkeypatch, missing):
    path = tmp_path / "synthetic-preflight.sqlite3"
    campaign = prepare_campaign(path, make_campaign())
    if missing == "key":
        monkeypatch.delenv("APOLLO_API_KEY")
    elif missing in ("key_control", "key_unicode"):
        monkeypatch.setenv("APOLLO_API_KEY", "clave\rhostil" if missing == "key_control" else "clave🔑")
    elif missing == "absent":
        access = access.model_copy(update={"apollo_access": None})
    else:
        changes = {"access_verified": False} if missing == "access" else (
            {"work_email_verified": False} if missing == "work_email" else {"enabled_operations": ["people_search"]})
        access = access.model_copy(update={"apollo_access": access.apollo_access.model_copy(update=changes)})

    def forbidden(*args, **kwargs):
        pytest.fail("El bloqueo debe preceder a permisos, reservas y clientes de proveedores.")

    monkeypatch.setattr(bridge, "_approve", forbidden)
    monkeypatch.setattr(bridge, "ProviderClient", forbidden)
    with pytest.raises(ValueError, match="Apollo bloqueado"):
        execute_campaign(path, campaign.id, access=access, approvals=[])
    with Database(path) as db:
        assert db.get_campaign(campaign.id) == campaign
        assert db.list_usage() == []


@pytest.mark.parametrize("missing", ["pool", "account", "funding", "unknown_credits", "exhausted"])
def test_direct_campaign_run_checks_apollo_account_before_other_providers(
        tmp_path, make_campaign, access, missing):
    path = tmp_path / "synthetic-direct-preflight.sqlite3"
    campaign = prepare_campaign(path, make_campaign())
    accounts = []
    for account in access.account_allowances:
        if account.provider == "apollo":
            if missing == "pool":
                continue
            changes = {"account_ref": "otra-cuenta-sintetica"} if missing == "account" else (
                {"funding_source": "prepaid"} if missing == "funding" else {
                    "credit_limit": None if missing == "unknown_credits" else Decimal(0)})
            account = account.model_copy(update=changes)
        accounts.append(account)
    with Database(path) as db:
        budget = Budget(db, campaign.config_snapshot.defaults.budget, accounts)
        with pytest.raises(ValueError, match="Apollo bloqueado"):
            run_campaign(db, budget, SimpleNamespace(), campaign.id, authorizations=[],
                         tavily_account_ref=access.tavily_account_ref, apollo_access=access.apollo_access)
        assert db.get_campaign(campaign.id) == campaign
        assert db.list_usage() == []


def test_shared_company_keeps_legacy_contacts_and_spend_separate_from_apollo(
        tmp_path, config, make_campaign, make_company, make_assessment, make_hunter_contact, access):
    path, now = tmp_path / "synthetic-generations.sqlite3", utc_now()
    legacy = make_campaign(status="partial", config_snapshot=config.model_copy(update={"people_provider": None}))
    current = make_campaign(status="completed")
    company, company_facts = make_company(domain="empresa-sintetica.example", identity_status="confirmed",
                                           segments=["fintech_software"])
    old_contact, old_facts = make_hunter_contact(company, now)
    search = ApolloSearchResponse.model_validate({"total_entries": 1, "people": [{
        "id": "persona-sintetica", "first_name": "Persona", "last_name_obfuscated": "S***", "title": "CTO",
    }]})
    [(candidate, search_facts)] = parse_search(company, search, uuid4(), now)
    enriched = ApolloEnrichmentResponse.model_validate({"person": {
        "id": "persona-sintetica", "first_name": "Persona", "last_name": "Sintética Hunter", "title": "CTO",
        "email": old_contact.channels[0].value, "email_status": "verified", "match_confidence": "high",
        "organization_id": "org-sintetica", "organization": {
            "id": "org-sintetica", "name": company.name, "primary_domain": company.domain,
        }, "employment_history": [{"current": True, "organization_id": "org-sintetica"}],
    }})
    new_contact, enrichment_facts = parse_enrichment(candidate, company, enriched, uuid4(), now)
    with Database(path) as db:
        db.save_campaign(legacy)
        db.save_campaign(current)
        db.save_company(company, evidence=company_facts)
        for campaign in (legacy, current):
            item = db.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id, stage="completed"))
            assessment = make_assessment(campaign.id, company.id, priority="high", target_roles=["CTO"])
            db.save_assessment(assessment)
            db.save_run_item(item.model_copy(update={"last_assessment_id": assessment.id}))
        db.save_contact(old_contact, evidence=old_facts)
        old_usage = db.save_usage(Usage(campaign_id=legacy.id, company_id=company.id,
            provider="hunter", operation="domain_search", account_ref="hunter-historica-sintetica",
            request_fingerprint="a" * 64, reserved_credits="1", reserved_cost_usd="0", credits="1",
            funding_source="free_credit", status="succeeded", outcome="succeeded"))
        db.save_contact(new_contact, evidence=search_facts + enrichment_facts)

    before = read_campaign(path, legacy.id).companies[0]
    after = read_campaign(path, current.id).companies[0]
    assert [item.contact.id for item in before.contacts] == [old_contact.id]
    assert [item.contact.id for item in after.contacts] == [new_contact.id]
    # T18: la inferencia histórica de Hunter se lee como afirmación del proveedor y ya no deja lista a la persona.
    assert before.contacts[0].employment.state == "provider_claim" and before.contacts[0].employment.origin == "hunter"
    assert before.business_status == "qualified_no_contact"
    assert after.contacts[0].employment.state == "provider_claim" and after.contacts[0].employment.origin == "apollo"
    assert after.business_status != "ready_preferred"
    assert not any(item.provider == "hunter" for item in after.evidence)
    assert after.contacts[0].contact.channels[0].verified_at is None
    with pytest.raises(ValueError, match="histórica"):
        execute_campaign(path, legacy.id, access=access, approvals=[])
    with pytest.raises(ValueError, match="histórica"):
        review_company(path, legacy.id, company.id, status="accepted", reason="Revisión sintética")
    with pytest.raises(ValueError, match="flujo Apollo"):
        confirm_alternative_channel(path, current.id, old_contact.id, "other", "canal sintético",
                                    confirmed=True, reason="Comprobación sintética sin mensajes")
    with Database(path) as db:
        assert db.get_contact(old_contact.id) == old_contact
        assert db.get_usage(old_usage.request_id) == old_usage
        assert db.get_campaign(legacy.id) == legacy
