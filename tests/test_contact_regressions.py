"""Regresiones de contactos persistidos, UI y CSV con datos exclusivamente sintéticos."""

import csv
from io import StringIO
import os
from uuid import uuid4

import django
from django.test import Client, override_settings
from django.urls import reverse
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.presentation import export_csv
from prospecting.db import Database
from prospecting.models import Channel, Contact, Evidence, RunItem, utc_now
from prospecting.pipeline import read_campaign


@pytest.mark.parametrize("kind,value,publication", [
    ("phone", "+573005550001", "Central general: +573005550001."),
    ("email", "otra-persona@example.com", "Correo de Otra Persona Sintética: otra-persona@example.com."),
])
def test_reopened_ambiguous_direct_channel_is_pending_in_ui_and_primary_csv(tmp_path, make_campaign, make_company,
                                                                         make_assessment, kind, value, publication):
    path, now = tmp_path / "synthetic-contact.sqlite3", utc_now()
    campaign = make_campaign(status="completed")
    company, evidence = make_company(domain="example.com", identity_status="confirmed", segments=["fintech_software"])
    assessment = make_assessment(campaign.id, company.id, priority="high", target_roles=["CTO"])
    contact_id = uuid4()
    fact = Evidence(company_id=company.id, contact_id=contact_id, claim="Directorio exclusivamente sintético.",
                    excerpt=f"Persona Sintética Uno, CTO de {company.name}. {publication}",
                    url="https://example.com/team", retrieved_at=now, kind="observed", source_type="primary")
    channel = Channel(contact_id=contact_id, type=kind, value=value, evidence_ids=[fact.id], retrieved_at=now,
                      professional=True, direct=True, phone_country="CO" if kind == "phone" else None,
                      normalized_status="published_professional" if kind == "email" else "unknown",
                      published_evidence_ids=[fact.id] if kind == "email" else [])
    contact = Contact(id=contact_id, company_id=company.id, name="Persona Sintética Uno", title="CTO",
                      name_complete=True, identity_status="confirmed", current_employment=True, relevant_function=True,
                      provenance={field: [fact.id] for field in ("name", "title", "relevant_function")},
                      employment_evidence_ids=[fact.id], channels=[channel])
    item = RunItem(campaign_id=campaign.id, company_id=company.id, stage="completed",
                   last_assessment_id=assessment.id, business_status="ready_preferred")
    with Database(path) as db:
        db.save_campaign(campaign)
        db.save_company(company, evidence=evidence)
        db.save_run_item(item.model_copy(update={"last_assessment_id": None}))
        db.save_assessment(assessment)
        db.save_run_item(item)
        db.save_contact(contact, evidence=[fact])
    view = read_campaign(path, campaign.id)
    [result] = view.companies
    assert result.business_status == "needs_channel_confirmation"
    assert result.contacts[0].eligible and result.contacts[0].usable_channels == []
    assert list(csv.DictReader(StringIO(export_csv(view).decode("utf-8-sig")))) == []
    [row] = csv.DictReader(StringIO(export_csv(view, include_all=True).decode("utf-8-sig")))
    assert row["contact_id"] == str(contact.id) and row["contact_ready"] == "False"
    assert value in row["channels"] and str(fact.id) in row["sources"]
    with override_settings(PROSPECTING_DB_PATH=path, PROSPECTING_ACCESS_PATH=tmp_path / "missing-access.json",
                           PROSPECTING_EXCLUSIONS_PATH=tmp_path / "missing-exclusions.json"):
        response = Client(SERVER_NAME="localhost").get(reverse("webapp:company", kwargs={
            "campaign_id": campaign.id, "company_id": company.id}))
    assert response.status_code == 200
    assert "Falta confirmar canal" in response.content.decode("utf-8")
    with Database(path) as db:
        assert db.get_contact(contact.id) == contact
        assert db.get_run_item(campaign.id, company.id) == item


@pytest.mark.parametrize("title,record", [("CTO", "Persona Sintética Uno dejó de ser CTO de"),
                                          ("Executive Assistant to CTO", "Persona Sintética Uno es Executive Assistant to CTO de")])
def test_reopened_contact_with_contradictory_professional_facts_is_not_ready(tmp_path, make_campaign, make_company,
                                                                          make_assessment, title, record):
    path, now = tmp_path / "synthetic-former-contact.sqlite3", utc_now()
    campaign = make_campaign(status="completed")
    company, evidence = make_company(domain="example.com", identity_status="confirmed", segments=["fintech_software"])
    assessment = make_assessment(campaign.id, company.id, priority="high", target_roles=["CTO"])
    contact_id = uuid4()
    fact = Evidence(company_id=company.id, contact_id=contact_id, claim="Salida laboral exclusivamente sintética.",
                    excerpt=f"{record} {company.name}, correo profesional persona@example.com.",
                    url="https://example.com/team", retrieved_at=now, kind="observed", source_type="primary")
    channel = Channel(contact_id=contact_id, type="email", value="persona@example.com", evidence_ids=[fact.id],
                      retrieved_at=now, professional=True, direct=True, normalized_status="published_professional",
                      published_evidence_ids=[fact.id])
    contact = Contact(id=contact_id, company_id=company.id, name="Persona Sintética Uno", title=title,
                      name_complete=True, identity_status="confirmed", current_employment=True, relevant_function=True,
                      provenance={field: [fact.id] for field in ("name", "title", "relevant_function")},
                      employment_evidence_ids=[fact.id], channels=[channel])
    item = RunItem(campaign_id=campaign.id, company_id=company.id, stage="completed",
                   last_assessment_id=assessment.id, business_status="ready_preferred")
    with Database(path) as db:
        db.save_campaign(campaign)
        db.save_company(company, evidence=evidence)
        db.save_run_item(item.model_copy(update={"last_assessment_id": None}))
        db.save_assessment(assessment)
        db.save_run_item(item)
        db.save_contact(contact, evidence=[fact])
    [result] = read_campaign(path, campaign.id).companies
    assert result.business_status == "qualified_no_contact"
    assert not result.contacts[0].eligible and result.contacts[0].usable_channels == []
    view = read_campaign(path, campaign.id)
    assert list(csv.DictReader(StringIO(export_csv(view).decode("utf-8-sig")))) == []
    [row] = csv.DictReader(StringIO(export_csv(view, include_all=True).decode("utf-8-sig")))
    assert row["contact_eligible"] == row["contact_ready"] == "False"
    assert str(fact.id) in row["sources"]
    with override_settings(PROSPECTING_DB_PATH=path, PROSPECTING_ACCESS_PATH=tmp_path / "missing-access.json",
                           PROSPECTING_EXCLUSIONS_PATH=tmp_path / "missing-exclusions.json"):
        response = Client(SERVER_NAME="localhost").get(reverse("webapp:company", kwargs={
            "campaign_id": campaign.id, "company_id": company.id}))
    assert response.status_code == 200 and "Calificada sin contacto" in response.content.decode("utf-8")
    with Database(path) as db:
        assert db.get_contact(contact.id) == contact
        assert db.get_run_item(campaign.id, company.id) == item
