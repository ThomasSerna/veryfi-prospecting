"""Todas las personas de cada empresa, ordenadas por match en la lectura, la ficha y el CSV. Datos sintéticos."""

import csv
from io import StringIO
import json
import os
from pathlib import Path
from types import SimpleNamespace
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


MATCH_PATH = Path(__file__).resolve().parents[1] / "config" / "contact_match.json"
READY, SALES, CONTRADICTED = "Persona Sintética Lista", "Persona Sintética Ventas", "Persona Sintética Contradicha"


@pytest.fixture
def people(tmp_path, make_campaign, make_company, make_assessment):
    """Tres personas guardadas en un orden distinto al del match: ventas, contradicha y lista."""
    path, now = tmp_path / "synthetic-match.sqlite3", utc_now()
    campaign = make_campaign(status="completed")
    company, company_evidence = make_company(domain="example.com", identity_status="confirmed",
                                             segments=["fintech_software"])
    assessment = make_assessment(campaign.id, company.id, priority="high", target_roles=["CTO"])
    item = RunItem(campaign_id=campaign.id, company_id=company.id, stage="completed",
                   last_assessment_id=assessment.id, business_status="ready_preferred")
    with Database(path) as db:
        db.save_campaign(campaign)
        db.save_company(company, evidence=company_evidence)
        db.save_run_item(item.model_copy(update={"last_assessment_id": None}))
        db.save_assessment(assessment)
        db.save_run_item(item)
        for name, title, identity in ((SALES, "Sales Manager", "confirmed"), (CONTRADICTED, "CTO", "contradicted"),
                                      (READY, "CTO", "confirmed")):
            contact_id = uuid4()
            email = f"{name.split()[-1].lower()}@example.com"
            fact = Evidence(company_id=company.id, contact_id=contact_id, claim="Directorio exclusivamente sintético.",
                            excerpt=f"{name}, {title} de {company.name}.", url="https://example.com/team",
                            retrieved_at=now, kind="observed", source_type="primary")
            verified = Evidence(company_id=company.id, contact_id=contact_id, claim=f"Hunter informa email {email}; estado=valid.",
                                provider="hunter", external_reference=f"synthetic-verification-{contact_id}",
                                retrieved_at=now, kind="observed", source_type="provider")
            channels = [Channel(contact_id=contact_id, type="email", value=email, evidence_ids=[verified.id],
                                provider_status="valid", normalized_status="verified", retrieved_at=now,
                                verified_at=now, professional=True, direct=True)] if name == READY else []
            db.save_contact(Contact(id=contact_id, company_id=company.id, name=name, title=title, name_complete=True,
                                    identity_status=identity, current_employment=True,
                                    relevant_function=title == "CTO",
                                    provenance={field: [fact.id] for field in ("name", "title", "relevant_function")},
                                    employment_evidence_ids=[fact.id], channels=channels), evidence=[fact, verified])
    return SimpleNamespace(path=path, campaign=campaign, company=company, tmp_path=tmp_path)


def test_every_saved_person_is_returned_ordered_by_match_with_blocked_last(people):
    view = read_campaign(people.path, people.campaign.id, contact_match_path=MATCH_PATH)
    [result] = view.companies
    assert view.contact_match_version == "contact_match_v1"
    # La contradicha suma más que la de ventas, pero una regla la descarta y queda al final.
    assert [(person.contact.name, person.match.score, person.match.blocked_reason) for person in result.contacts] == [
        (READY, 100, None), (SALES, 25, None), (CONTRADICTED, 68, "identity_contradicted")]
    assert [person.eligible for person in result.contacts] == [True, False, False]
    assert result.business_status == "ready_preferred"


@pytest.mark.parametrize("content", [None, '{"version": "contact_match_v9"}', "no es JSON"])
def test_missing_or_invalid_weights_show_people_without_inventing_a_match(people, content):
    path = None
    if content is not None:
        path = people.tmp_path / "contact_match.json"
        path.write_text(content, encoding="utf-8")
    view = read_campaign(people.path, people.campaign.id, contact_match_path=path)
    [result] = view.companies
    assert view.contact_match_version is None and len(result.contacts) == 3
    assert all(person.match is None for person in result.contacts)
    assert result.business_status == read_campaign(people.path, people.campaign.id,
                                                    contact_match_path=MATCH_PATH).companies[0].business_status


def page(people, name, match_path=MATCH_PATH, **kwargs):
    with override_settings(PROSPECTING_DB_PATH=people.path, PROSPECTING_ACCESS_PATH=people.tmp_path / "missing-access.json",
                           PROSPECTING_EXCLUSIONS_PATH=people.tmp_path / "missing-exclusions.json",
                           PROSPECTING_CONTACT_MATCH_PATH=match_path):
        response = Client(SERVER_NAME="localhost").get(reverse(name, kwargs={"campaign_id": people.campaign.id} | kwargs))
    assert response.status_code == 200
    return response.content.decode("utf-8")


def test_company_page_lists_people_by_match_with_breakdown_and_blocked_reason(people):
    html = page(people, "webapp:company", company_id=people.company.id)
    assert html.index(READY) < html.index(SALES) < html.index(CONTRADICTED)
    assert "100 %</strong> de match" in html and "25 %</strong> de match" in html
    assert "Descartada por regla: su identidad tiene contradicciones" in html
    assert html.count("Cómo se calculó el match") == 3 and "Cargo fuera de los perfiles" in html
    assert "contact_match_v1" in html and "El porcentaje de match no está disponible" not in html


def test_company_page_warns_when_weights_are_invalid(people):
    broken = people.tmp_path / "contact_match.json"
    broken.write_text('{"version": "contact_match_v9"}', encoding="utf-8")
    html = page(people, "webapp:company", broken, company_id=people.company.id)
    assert "El porcentaje de match no está disponible" in html and "de match</span>" not in html
    assert all(name in html for name in (READY, SALES, CONTRADICTED))


def test_campaign_table_shows_people_count_and_best_match(people):
    html = page(people, "webapp:campaign")
    assert "<th class=\"numeric\">Contactos</th>" in html and "Mejor match 100 %" in html


def csv_rows(content):
    return list(csv.DictReader(StringIO(content.decode("utf-8-sig"))))


def test_csv_rows_follow_match_order_and_leave_missing_match_empty(people):
    view = read_campaign(people.path, people.campaign.id, contact_match_path=MATCH_PATH)
    rows = csv_rows(export_csv(view, include_all=True))
    assert [(row["contact_name"], row["contact_match"], row["contact_match_blocked"]) for row in rows] == [
        (READY, "100", ""), (SALES, "25", ""), (CONTRADICTED, "68", "identity_contradicted")]
    assert {row["contact_match_version"] for row in rows} == {"contact_match_v1"}
    assert json.loads(rows[1]["contact_match_detail"])[0] == {
        "name": "role", "level": "outside_profile", "points": 0, "weight": 50, "pending": False}
    # La exportación principal sigue limitada a personas listas.
    assert [row["contact_name"] for row in csv_rows(export_csv(view))] == [READY]
    plain = csv_rows(export_csv(read_campaign(people.path, people.campaign.id), include_all=True))
    assert len(plain) == 3 and all(row["contact_match"] == row["contact_match_detail"] == "" for row in plain)


def test_csv_download_uses_the_configured_weights(people):
    with override_settings(PROSPECTING_DB_PATH=people.path, PROSPECTING_ACCESS_PATH=people.tmp_path / "missing-access.json",
                           PROSPECTING_EXCLUSIONS_PATH=people.tmp_path / "missing-exclusions.json",
                           PROSPECTING_CONTACT_MATCH_PATH=MATCH_PATH):
        response = Client(SERVER_NAME="localhost").get(
            reverse("webapp:export", kwargs={"campaign_id": people.campaign.id}), {"mode": "all"})
    assert response.status_code == 200
    assert [row["contact_match"] for row in csv_rows(response.content)] == ["100", "25", "68"]
