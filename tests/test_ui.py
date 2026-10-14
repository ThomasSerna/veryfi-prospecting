"""Interfaz Django con bases temporales y datos exclusivamente sintéticos, sin tráfico real."""

import csv
from datetime import timedelta
from html import escape
from html.parser import HTMLParser
from io import StringIO
import os
from types import SimpleNamespace
from uuid import uuid4

import django
import pytest
from django.test import Client, override_settings
from django.urls import reverse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from prospecting.budget import AccountAllowance
from prospecting.db import Database
from prospecting.identity import ExclusionList
from prospecting.models import CampaignStatus, Channel, Contact, Evidence, RunItem, Usage, utc_now
from prospecting.pipeline import ProviderAccess, read_campaign
from prospecting.pipeline import campaign as bridge
from prospecting.sources import validate_public_url
from core.presentation import stop_message


@pytest.fixture
def client(ui_paths):
    return Client(SERVER_NAME="localhost")


def url(name, campaign_id=None, company_id=None):
    identifiers = {}
    if campaign_id is not None:
        identifiers["campaign_id"] = campaign_id
    if company_id is not None:
        identifiers["company_id"] = company_id
    return reverse(f"webapp:{name}", kwargs=identifiers)


def text(response):
    return response.content.decode("utf-8")


def prepare(client, **fields):
    if not client.session.get("draft_id"):
        assert client.get(url("new_campaign")).status_code == 200
    return client.post(url("new_campaign"), {
        "draft_id": client.session["draft_id"],
        "countries": ["CO"], "segments": ["fintech_software"],
        "keywords": "", "max_companies": "20", **fields,
    })


def confirmation(case, **fields):
    return {"contact_id": str(case.contact.id), "channel_type": "linkedin",
            "channel_value": case.contact.channels[0].value,
            "reason": "Mensajería profesional nominal comprobada sin enviar nada.", **fields}


class Links(HTMLParser):
    """Lee atributos reales de enlaces para distinguir texto hostil de destinos."""
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.urls.extend(value for name, value in attrs if name == "href")


@pytest.fixture
def ui_paths(tmp_path, monkeypatch):
    for name in ("TAVILY_API_KEY", "ANTHROPIC_API_KEY", "HUNTER_API_KEY", "APOLLO_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    paths = SimpleNamespace(db=tmp_path / "synthetic.sqlite3", access=tmp_path / "provider-access.json",
                            exclusions=tmp_path / "exclusions.json")
    from core import execution

    monkeypatch.setattr(execution, "_active_campaign_id", None)
    monkeypatch.setattr(execution, "_reports", {})
    with override_settings(PROSPECTING_DB_PATH=paths.db, PROSPECTING_ACCESS_PATH=paths.access,
                           PROSPECTING_EXCLUSIONS_PATH=paths.exclusions):
        yield paths


@pytest.fixture
def ui_results(ui_paths, make_campaign, make_company, make_assessment):
    now = utc_now()
    campaign = make_campaign(countries=["CO", "MX"], segments=["fintech_software", "cpg_loyalty"], status="completed")
    companies = []
    contact_id = uuid4()
    with Database(ui_paths.db) as db:
        db.save_campaign(campaign)
        for index, (country, segment, priority) in enumerate([
            ("CO", "fintech_software", "high"), ("MX", "cpg_loyalty", "low"),
        ]):
            company, sources = make_company(name=f"Empresa sintética {country}", domain=f"synthetic-{country.lower()}.example",
                                            entity_name=f"Entidad sintética {country}", operating_countries=[country],
                                            segments=[segment], identity_status="confirmed")
            assessment = make_assessment(campaign.id, company.id, priority=priority, target_roles=["CTO"],
                                         explanation=f"Caso de uso sintético {country}: procesar comprobantes.")
            db.save_company(company, evidence=sources)
            item = db.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id, stage="completed"))
            db.save_assessment(assessment)
            db.save_run_item(item.model_copy(update={"last_assessment_id": assessment.id}))
            companies.append(company)
            if index:
                continue
            fact = Evidence(company_id=company.id, contact_id=contact_id, retrieved_at=now, kind="observed",
                            source_type="primary", url=f"https://{company.domain}/team",
                            claim="Directorio profesional exclusivamente sintético.",
                            excerpt=f"Persona Sintética Uno, CTO de {company.name}, perfil profesional nominal.")
            contact = Contact(id=contact_id, company_id=company.id, name="Persona Sintética Uno", title="CTO",
                              identity_status="confirmed", name_complete=True, current_employment=True,
                              relevant_function=True, employment_evidence_ids=[fact.id],
                              provenance={key: [fact.id] for key in ("name", "title", "relevant_function")},
                              channels=[Channel(contact_id=contact_id, type="linkedin",
                                                value="https://www.linkedin.com/in/synthetic-person", evidence_ids=[fact.id],
                                                retrieved_at=now, normalized_status="unknown")])
            db.save_contact(contact, evidence=[fact])
    return SimpleNamespace(paths=ui_paths, campaign=campaign, companies=companies, contact=contact, now=now)


@pytest.fixture
def ui_access(ui_paths, monkeypatch):
    for variable in ("TAVILY_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(variable, "clave-exclusivamente-sintetica")
    access = ProviderAccess(tavily_account_ref="tavily-sintetica", claude_account_ref="claude-sintetica",
                            account_allowances=[
                                AccountAllowance(provider="tavily", account_ref="tavily-sintetica", funding_source="free_credit",
                                                 credit_limit="10", source_reference="Cupo sintético", observed_at=utc_now()),
                                AccountAllowance(provider="anthropic", account_ref="claude-sintetica", funding_source="prepaid",
                                                 cost_limit_usd="1", source_reference="Cupo sintético", observed_at=utc_now()),
                            ])
    ui_paths.access.write_text(access.model_dump_json(), encoding="utf-8")
    return access


def test_ui_starts_without_keys_database_or_provider_clients(ui_paths, client, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("La pantalla no debe crear clientes de proveedores")

    monkeypatch.setattr(bridge, "ProviderClient", forbidden)
    monkeypatch.setattr(bridge, "ClaudeClient", forbidden)
    for path in (url("campaigns"), url("new_campaign")):
        response = client.get(path)
        assert response.status_code == 200
        assert "Veryfi Prospecting" in text(response)
    assert not ui_paths.db.exists()


def test_prepare_criteria_and_refresh_preserve_one_campaign(ui_paths, client):
    response = prepare(client, countries=["MX"], segments=["cpg_loyalty"],
                       keywords="recibos, fidelización", max_companies="3")
    assert response.status_code == 302
    with Database(ui_paths.db) as db:
        campaigns = db.list_campaigns()
        assert len(campaigns) == 1
        campaign = campaigns[0]
        assert campaign.countries == ["MX"] and campaign.segments == ["cpg_loyalty"]
        assert campaign.max_companies == 3 and campaign.filters.keywords == ["recibos", "fidelización"]
        assert campaign.status == "created" and db.list_usage() == []
    assert client.get(response.url).status_code == 200
    assert prepare(client, countries=["MX"]).url == response.url
    with Database(ui_paths.db) as db:
        assert db.list_campaigns() == campaigns and db.list_usage() == []


@pytest.mark.parametrize("fields", [
    {"countries": []}, {"segments": []}, {"max_companies": "21"},
    {"countries": ["XX"]}, {"segments": ["inventado"]},
])
def test_invalid_criteria_are_reported_without_creating_database(ui_paths, client, fields):
    response = prepare(client, **fields)
    assert response.status_code == 400
    assert not ui_paths.db.exists()


def test_invalid_provider_configuration_does_not_echo_sensitive_input(ui_paths, client):
    ui_paths.access.write_text('{"secret":"NO-MOSTRAR-ESTE-VALOR"}', encoding="utf-8")
    response = client.get(url("campaigns"))
    assert response.status_code == 200
    assert "configuración válida de cupos" in text(response)
    assert "NO-MOSTRAR-ESTE-VALOR" not in text(response)
    assert not ui_paths.db.exists()


def test_filters_and_company_detail_show_persisted_evidence(ui_results, client):
    case = ui_results
    response = client.get(url("company", case.campaign.id, case.companies[0].id))
    assert response.status_code == 200
    assert "Caso de uso sintético CO" in text(response)
    assert "Directorio profesional exclusivamente sintético" in text(response)
    assert "Persona Sintética Uno" in text(response)

    response = client.get(url("campaign", case.campaign.id), {"countries": ["MX"]})
    assert response.status_code == 200
    assert "Empresa sintética MX" in text(response) and "Empresa sintética CO" not in text(response)
    assert "Persona Sintética Uno" not in text(response)
    query = {"countries": ["CO"], "segments": ["fintech_software"], "priorities": ["high"],
             "availability": ["needs_channel_confirmation"]}
    response = client.get(url("campaign", case.campaign.id), query)
    assert "Empresa sintética CO" in text(response) and "Empresa sintética MX" not in text(response)
    response = client.get(url("campaign", case.campaign.id), query | {"priorities": ["low"]})
    assert "Ninguna empresa coincide" in text(response)


def test_human_review_saves_reason_and_survives_new_browser(ui_results, client):
    case = ui_results
    with Database(case.paths.db) as db:
        item = db.get_run_item(case.campaign.id, case.companies[0].id)
        assessment = db.get_assessment(item.last_assessment_id)
    response = client.post(url("review", case.campaign.id, case.companies[0].id), {
        "status": "accepted", "reason": "Aceptación exclusivamente sintética, con canal pendiente.",
    })
    assert response.status_code == 302
    result = next(item for item in read_campaign(case.paths.db, case.campaign.id).companies
                  if item.company.id == case.companies[0].id)
    assert result.run_item.review_status == "accepted" and result.run_item.reviewed_at is not None
    assert result.business_status == "needs_channel_confirmation"
    assert result.assessment == assessment
    reopened = Client(SERVER_NAME="localhost").get(url("company", case.campaign.id, case.companies[0].id))
    assert 'value="accepted" selected' in text(reopened)
    assert "Aceptación exclusivamente sintética" in text(reopened)


def test_manual_confirmation_requires_checkbox_and_persists_only_on_explicit_action(ui_results, client):
    case = ui_results
    path = url("confirm_channel", case.campaign.id, case.companies[0].id)
    assert client.post(path, confirmation(case)).status_code == 400
    with Database(case.paths.db) as db:
        assert db.get_contact(case.contact.id) == case.contact
    assert client.post(path, confirmation(case, confirmed="on")).status_code == 302
    result = next(item for item in read_campaign(case.paths.db, case.campaign.id).companies
                  if item.company.id == case.companies[0].id)
    assert result.business_status == "ready_alternative"
    assert result.contacts[0].usable_channels[0].manual_confirmed_at is not None
    assert result.run_item.review_status == "pending"


def test_confirmation_of_ineligible_person_does_not_modify_channel(ui_results, client):
    case = ui_results
    with Database(case.paths.db) as db:
        db.save_contact(case.contact.model_copy(update={"current_employment": False}))
        original = db.get_contact(case.contact.id)
    response = client.post(url("confirm_channel", case.campaign.id, case.companies[0].id),
                           confirmation(case, confirmed="on"))
    assert response.status_code == 400
    with Database(case.paths.db) as db:
        assert db.get_contact(case.contact.id) == original


@pytest.mark.parametrize("confirmed_domain", [True, False])
def test_manual_confirmation_respects_current_exclusions_without_mutating_saved_result(ui_results, client, confirmed_domain):
    case = ui_results
    company = case.companies[0]
    exclusions = ExclusionList.model_validate({
        "version": "exclusiones-sinteticas-v1", "validation_status": "validated",
        "source_reference": "Lista sintética posterior a la investigación", "observed_at": utc_now(),
        "entries": [{"id": "synthetic-entry", "name": company.name,
                     "domains": [company.domain if confirmed_domain else "otra-empresa.example"], "scope": "entity",
                     "reason": "current_customer", "source_reference": "Exclusión exclusivamente sintética"}],
    })
    case.paths.exclusions.write_text(exclusions.model_dump_json(), encoding="utf-8")
    with Database(case.paths.db) as db:
        item, facts, usage = db.get_run_item(case.campaign.id, company.id), db.list_evidence(company.id), db.list_usage()
    response = client.post(url("confirm_channel", case.campaign.id, company.id), confirmation(case, confirmed="on"))
    assert response.status_code == 400
    with Database(case.paths.db) as db:
        assert db.get_contact(case.contact.id) == case.contact
        assert db.get_run_item(case.campaign.id, company.id) == item
        assert db.list_evidence(company.id) == facts and db.list_usage() == usage


def test_live_pipeline_blocks_human_writes_close_prepare_and_download(ui_results, client):
    case = ui_results
    with bridge._EXECUTION:
        for name, fields in [
            ("review", {"status": "accepted", "reason": "Motivo sintético."}),
            ("confirm_channel", confirmation(case, confirmed="on")),
        ]:
            response = client.post(url(name, case.campaign.id, case.companies[0].id), fields)
            assert response.status_code == 409
        assert client.post(url("close", case.campaign.id)).status_code == 409
        assert prepare(client).status_code == 409
        assert client.get(url("export", case.campaign.id)).status_code == 409


def test_download_rechecks_freshness_at_request_and_keeps_modes_separate(ui_results, client, monkeypatch):
    case = ui_results
    bridge.confirm_alternative_channel(case.paths.db, case.campaign.id, case.contact.id, "linkedin",
                                       case.contact.channels[0].value,
                                       reason="Acceso profesional sintético comprobado sin envío.", confirmed=True)
    response = client.get(url("export", case.campaign.id))
    assert response.status_code == 200 and response.content.startswith(b"\xef\xbb\xbf")
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment;" in response["Content-Disposition"]
    fresh_rows = list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"))))
    assert len(fresh_rows) == 1 and fresh_rows[0]["contact_id"] == str(case.contact.id)
    monkeypatch.setattr(bridge, "utc_now", lambda: case.now + timedelta(days=31))
    response = client.get(url("export", case.campaign.id))
    assert list(csv.DictReader(StringIO(response.content.decode("utf-8-sig")))) == []
    response = client.get(url("export", case.campaign.id), {"mode": "all", "countries": "XX"})
    all_rows = list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"))))
    assert {row["company_id"] for row in all_rows} == {str(company.id) for company in case.companies}
    assert client.get(url("export", case.campaign.id), {"mode": "inventado"}).status_code == 400


@pytest.mark.parametrize("demo", [True, False])
def test_demo_notice_and_csv_name_appear_only_in_demo_mode(ui_results, client, tmp_path, demo):
    case = ui_results
    with override_settings(PROSPECTING_DEMO=demo):
        pages = [client.get(url("campaigns")), client.get(url("campaign", case.campaign.id)),
                 client.get(url("company", case.campaign.id, case.companies[0].id))]
        with override_settings(PROSPECTING_CONFIG_PATH=tmp_path / "configuracion-ausente.json"):
            pages.append(client.get(url("new_campaign")))
        disposition = client.get(url("export", case.campaign.id), {"mode": "all"})["Content-Disposition"]
    assert [page.status_code for page in pages] == [200, 200, 200, 503]
    assert [("Demostración con datos exclusivamente sintéticos." in text(page)) for page in pages] == [demo] * 4
    assert ('filename="demo-sintetica-resultados-' in disposition) is demo
    assert disposition.endswith(f'resultados-{case.campaign.id}.csv"')


def test_validated_exclusions_do_not_display_missing_list_warning(ui_results, client):
    checked = ExclusionList(version="synthetic-v1", validation_status="validated", source_reference="Lista sintética",
                            observed_at=utc_now(), entries=[])
    ui_results.paths.exclusions.write_text(checked.model_dump_json(), encoding="utf-8")
    response = client.get(url("campaign", ui_results.campaign.id))
    assert response.status_code == 200
    assert "Lista de exclusiones ausente" not in text(response)


def test_budget_reservation_is_not_added_again_to_pending(ui_results, client):
    with Database(ui_results.paths.db) as db:
        db.save_usage(Usage(campaign_id=ui_results.campaign.id, provider="anthropic", operation="messages",
                            account_ref="cuenta-sintetica", funding_source="prepaid", request_fingerprint="b" * 64,
                            reserved_cost_usd="0.02", reserved_credits="0", status="reserved"))
    response = client.get(url("campaign", ui_results.campaign.id))
    assert response.status_code == 200
    assert "USD 0.020000" in text(response)
    assert "USD 0.040000" not in text(response)
    view = read_campaign(ui_results.paths.db, ui_results.campaign.id)
    assert view.budget.campaign.reserved == view.budget.campaign.pending


def test_hostile_external_text_is_escaped_and_private_source_is_not_a_link(
        ui_paths, client, make_campaign, make_company, make_assessment):
    hostile = "<script>alert(1)</script> **negrita** [enlace](javascript:alert(1))"
    now, contact_id = utc_now(), uuid4()
    campaign = make_campaign(status="completed")
    company, sources = make_company(name=f"Empresa sintética {hostile}", domain="synthetic-hostile.example",
                                    operating_countries=["CO"], segments=["fintech_software"], identity_status="confirmed")
    page = Evidence(company_id=company.id, retrieved_at=now, kind="observed", source_type="primary",
                    url="https://synthetic-hostile.example/equipo", claim=f"Afirmación sintética {hostile}", excerpt=hostile)
    private = Evidence(company_id=company.id, retrieved_at=now, kind="observed", source_type="primary",
                       url="http://127.0.0.1/panel", claim="Fuente sintética con destino privado.")
    person = Evidence(company_id=company.id, contact_id=contact_id, retrieved_at=now, kind="observed",
                      source_type="primary", url="https://synthetic-hostile.example/equipo",
                      claim=f"Persona sintética {hostile}", excerpt=hostile)
    contact = Contact(id=contact_id, company_id=company.id, name=f"Persona {hostile}", title=f"Cargo {hostile}",
                      provenance={"name": [person.id], "title": [person.id]},
                      channels=[Channel(contact_id=contact_id, type="other", value=f"Canal {hostile}",
                                        evidence_ids=[person.id], retrieved_at=now)])
    assessment = make_assessment(campaign.id, company.id, priority="low", explanation=f"Explicación sintética {hostile}")
    with Database(ui_paths.db) as db:
        db.save_campaign(campaign)
        db.save_company(company, evidence=[*sources, page, private])
        item = db.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id, stage="completed",
                                       stop_reason=f"motivo_sintetico {hostile}", error_stage="researched",
                                       error_message=f"Respuesta sintética literal {hostile}"))
        db.save_assessment(assessment)
        db.save_run_item(item.model_copy(update={"last_assessment_id": assessment.id}))
        db.save_contact(contact, evidence=[person])
    response = client.get(url("company", campaign.id, company.id))
    shown = text(response)
    for expected in (company.name, page.claim, assessment.explanation, contact.name, contact.title,
                     contact.channels[0].value, item.stop_reason, item.error_message):
        assert escape(expected) in shown
    assert "<script>alert(1)</script>" not in shown
    links = Links()
    links.feed(shown)
    assert "https://synthetic-hostile.example/equipo" in links.urls
    assert "http://127.0.0.1/panel" not in links.urls
    assert all(validate_public_url(value) == value for value in links.urls if value.startswith(("http:", "https:")))
    assert not any(value.startswith("javascript:") for value in links.urls)


def test_results_prioritize_fit_and_stop_reasons_explain_the_next_action(ui_results, client):
    response = client.get(url("campaign", ui_results.campaign.id))
    shown = text(response)
    assert shown.index("Empresa sintética CO") < shown.index("Empresa sintética MX")
    assert "no se repite" in stop_message("duplicate_request")
    assert "autoriza de nuevo" in stop_message("authorization_required")
    assert "evidencia" in stop_message("assessment_pending:invalid_response")


def test_csrf_is_required_and_read_only_routes_do_not_accept_writes(ui_paths):
    client = Client(SERVER_NAME="localhost", enforce_csrf_checks=True)
    response = client.get(url("new_campaign"))
    assert response.status_code == 200
    assert prepare(client).status_code == 403
    assert not ui_paths.db.exists()
    token = client.cookies["csrftoken"].value
    response = client.post(url("new_campaign"), {
        "draft_id": client.session["draft_id"],
        "countries": ["CO"], "segments": ["fintech_software"], "max_companies": "2",
    }, HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 302
    assert client.post(url("campaigns"), HTTP_X_CSRFTOKEN=token).status_code == 405


def test_unknown_campaign_and_company_are_not_found(ui_paths, client):
    assert client.get(url("campaign", uuid4())).status_code == 404
    prepare(client)
    with Database(ui_paths.db) as db:
        campaign = db.list_campaigns()[0]
    assert client.get(url("company", campaign.id, uuid4())).status_code == 404


def test_close_campaign_preserves_companies_contacts_assessment_and_spend(ui_results, client):
    case = ui_results
    with Database(case.paths.db) as db:
        db.save_campaign(case.campaign.model_copy(update={"status": CampaignStatus.RUNNING}))
        items = db.list_run_items(case.campaign.id)
        contacts = db.list_contacts(case.companies[0].id)
        assessment = db.get_assessment(items[0].last_assessment_id)
        usage = db.list_usage()
    response = client.post(url("close", case.campaign.id))
    assert response.status_code == 302
    with Database(case.paths.db) as db:
        assert db.get_campaign(case.campaign.id).status == "partial"
        assert db.list_run_items(case.campaign.id) == items
        assert db.list_contacts(case.companies[0].id) == contacts
        assert db.get_assessment(assessment.id) == assessment
        assert db.list_usage() == usage
