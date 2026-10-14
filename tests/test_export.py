"""CSV generado desde SQLite temporal, con personas y textos exclusivamente sintéticos."""

from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import timedelta
from io import StringIO
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.presentation import CSV_FIELDS, csv_text, download_csv, export_csv
from prospecting.db import Database
from prospecting.models import BusinessStatus, Channel, Contact, Evidence, RunItem, RunStage, utc_now
from prospecting.pipeline import prepare_campaign, read_campaign, review_company
from prospecting.pipeline import campaign as bridge


def rows(content):
    return list(csv.DictReader(StringIO(content.decode("utf-8-sig"))))


@pytest.fixture
def csv_case(tmp_path, make_campaign, make_company, make_assessment):
    now = utc_now()
    path = tmp_path / "synthetic-export.sqlite3"
    campaign = prepare_campaign(path, make_campaign())
    company, evidence = make_company(domain="example.com", entity_name="Empresa sintética",
                                    identity_status="confirmed", operating_countries=["CO"], segments=["fintech_software"])
    assessment = make_assessment(campaign.id, company.id, priority="high", fit_score=88.9, coverage=0.9, target_roles=["CTO"])
    with Database(path) as db:
        db.save_company(company, evidence=evidence)
        item = db.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id))
        db.save_assessment(assessment)
        db.save_run_item(item.model_copy(update={"stage": RunStage.COMPLETED, "last_assessment_id": assessment.id,
                                                "business_status": BusinessStatus.READY_PREFERRED}))
        contacts = []
        for index in range(2):
            id = uuid4()
            name = f"Persona Sintética {'Uno' if index == 0 else 'Dos'}"
            email = f"persona-sintetica-{index}@example.com"
            phone = "+571234567890"
            primary = Evidence(company_id=company.id, contact_id=id, claim="Directorio corporativo sintético actual.",
                               excerpt=f"{name}, CTO de Empresa sintética. Teléfono nominal {phone}.",
                               url="https://example.com/team", retrieved_at=now, kind="observed", source_type="primary")
            verified = Evidence(company_id=company.id, contact_id=id, claim=f"Correo sintético {email}, estado valid.",
                                provider="hunter", external_reference=f"synthetic-verification-{index}", retrieved_at=now,
                                kind="observed", source_type="provider")
            contact = Contact(id=id, company_id=company.id, name=name, title="CTO", name_complete=True,
                              identity_status="confirmed" if index == 0 else "pending", current_employment=True,
                              relevant_function=True, employment_evidence_ids=[primary.id],
                              provenance={key: [primary.id] for key in ("name", "title", "relevant_function")},
                              channels=[Channel(contact_id=id, type="email", value=email, evidence_ids=[verified.id],
                                                provider_status="valid", normalized_status="verified", verified_at=now,
                                                retrieved_at=now, professional=True, direct=True,
                                                warnings=['Advertencia sintética con coma, comillas " y salto\nde línea.']),
                                        Channel(contact_id=id, type="phone", value=phone, phone_country="CO",
                                                evidence_ids=[primary.id], retrieved_at=now, professional=True, direct=True)])
            db.save_contact(contact, evidence=[primary, verified])
            contacts.append(contact)
        empty, empty_sources = make_company(name="Empresa sintética sin personas")
        db.save_company(empty, evidence=empty_sources)
        db.save_run_item(RunItem(campaign_id=campaign.id, company_id=empty.id, stop_reason="identity_review"))
    return SimpleNamespace(path=path, campaign=campaign, company=company, assessment=assessment, contacts=contacts,
                           empty=empty, now=now)


@pytest.mark.parametrize("value", [
    "=1+2", "+SUM(1)", "-1+2", "@SUM(1)", " =1+2", "\t=1+2", "\r=1+2", "\n=1+2",
    "\u00a0@SUM(1)", "\x00=1+2", " \x1b@SUM(1)", " \x7f=1+2", "\ufeff=1+2",
    "＝1+2", "＋SUM(1)", "－1+2", "＠SUM(1)", '=1+2";=1+2',
])
def test_dangerous_text_is_neutralized_without_losing_content(value):
    assert csv_text(value) == "'\t" + value


def test_null_zero_and_plain_text_remain_distinct():
    assert csv_text(None) == ""
    assert csv_text(0) == "0"
    assert csv_text('Texto sintético, "entre comillas"\nsegunda línea') == 'Texto sintético, "entre comillas"\nsegunda línea'


def test_primary_has_only_current_eligible_people_and_preserves_sources_and_identifiers(csv_case):
    case = csv_case
    view = read_campaign(case.path, case.campaign.id)
    content = export_csv(view)
    assert content.startswith(b"\xef\xbb\xbf")
    [row] = rows(content)
    assert list(row) == list(CSV_FIELDS)
    assert row["company_id"] == str(case.company.id) and row["contact_id"] == str(case.contacts[0].id)
    assert row["fit_score"] == "88.9" and row["coverage"] == "0.9"
    assert row["contact_ready"] == "True" and row["business_status"] == "ready_preferred"
    assert row["phone"] == "'\t+571234567890"
    channels = json.loads(row["channels"])
    assert channels[0]["provider_status"] == "valid" and channels[0]["verified_at"]
    facts = json.loads(row["sources"])
    assert all(fact["retrieved_at"] and (fact["url"] or fact["external_reference"]) for fact in facts)
    assert all(fact["contact_id"] in (None, str(case.contacts[0].id)) for fact in facts)
    assert json.loads(row["contact_provenance"])["name"]
    assert row["review_status"] == "pending" and row["review_reason"] == ""
    assert 'coma, comillas " y salto\nde línea.' in row["warnings"]
    assert all(len(parsed) == len(CSV_FIELDS) for parsed in csv.reader(StringIO(content.decode("utf-8-sig"))))


def test_all_results_keeps_pending_people_and_company_without_people(csv_case):
    case = csv_case
    exported = rows(export_csv(read_campaign(case.path, case.campaign.id), include_all=True))
    assert len(exported) == 3
    pending = next(row for row in exported if row["contact_id"] == str(case.contacts[1].id))
    assert pending["contact_eligible"] == "False" and pending["contact_ready"] == "False"
    empty = next(row for row in exported if row["company_id"] == str(case.empty.id))
    assert empty["contact_id"] == empty["email"] == empty["fit_score"] == empty["coverage"] == ""
    assert empty["stop_reason"] == "identity_review" and empty["sources"] != "[]"


def test_hostile_fields_cannot_start_a_new_cell_or_change_readiness(csv_case):
    case = csv_case
    reason = '=HYPERLINK("https://example.com";"sintético"),\n@SUM(1)'
    review_company(case.path, case.campaign.id, case.company.id, status="rejected", reason=reason)
    [row] = rows(download_csv(case.path, case.campaign.id))
    assert row["review_status"] == "rejected" and row["review_reason"] == "'\t" + reason
    assert row["business_status"] == "ready_preferred"
    assert None not in row and set(row) == set(CSV_FIELDS)


def test_download_rechecks_freshness_and_review_at_click_and_opens_own_connection(csv_case, monkeypatch):
    case = csv_case
    callback = lambda: download_csv(case.path, case.campaign.id)
    assert len(rows(callback())) == 1
    review_company(case.path, case.campaign.id, case.company.id, status="accepted", reason="Revisión sintética reciente.")
    with ThreadPoolExecutor(max_workers=1) as executor:
        [row] = rows(executor.submit(callback).result())
    assert row["review_status"] == "accepted" and row["reviewed_at"]
    monkeypatch.setattr(bridge, "utc_now", lambda: case.now + timedelta(days=31))
    assert rows(callback()) == []
    expired = rows(download_csv(case.path, case.campaign.id, include_all=True))
    person = next(row for row in expired if row["contact_id"] == str(case.contacts[0].id))
    assert person["business_status"] not in ("ready_preferred", "ready_alternative")
    assert person["stored_business_status"] == "ready_preferred"


def test_download_rejects_live_run_and_persisted_exclusions(csv_case):
    case = csv_case
    with bridge._EXECUTION, pytest.raises(ValueError, match="ejecutándose"):
        download_csv(case.path, case.campaign.id)
    with Database(case.path) as db:
        item = db.get_run_item(case.campaign.id, case.company.id)
        db.save_run_item(item.model_copy(update={"business_status": BusinessStatus.EXCLUDED}))
    assert rows(download_csv(case.path, case.campaign.id)) == []
    all_rows = rows(download_csv(case.path, case.campaign.id, include_all=True))
    assert all(row["business_status"] == "excluded" for row in all_rows if row["company_id"] == str(case.company.id))
