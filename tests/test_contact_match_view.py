"""Todas las personas de cada empresa, ordenadas por match en la lectura, la ficha y el CSV. Datos sintéticos."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

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
