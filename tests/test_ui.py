"""Flujo Streamlit con bases temporales y datos exclusivamente sintéticos, sin tráfico real."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

import app
from prospecting.budget import AccountAllowance
from prospecting.db import Database
from prospecting.identity import ExclusionList
from prospecting.models import (
    BusinessStatus, CampaignStatus, Channel, Contact, Evidence, RunItem, Usage, utc_now,
)
from prospecting.pipeline import ProviderAccess, read_campaign
from prospecting.pipeline import campaign as bridge


def widget(elements, label):
    return next(element for element in elements if element.label == label)


def screen():
    return AppTest.from_string("import app\napp.main()", default_timeout=30).run()


@pytest.fixture
def ui_paths(tmp_path, monkeypatch):
    for name in ("TAVILY_API_KEY", "ANTHROPIC_API_KEY", "HUNTER_API_KEY", "APOLLO_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    paths = SimpleNamespace(db=tmp_path / "synthetic.sqlite3", access=tmp_path / "provider-access.json",
                            exclusions=tmp_path / "exclusions.json")
    monkeypatch.setattr(app, "DB_PATH", paths.db)
    monkeypatch.setattr(app, "ACCESS_PATH", paths.access)
    monkeypatch.setattr(app, "EXCLUSIONS_PATH", paths.exclusions)
    return paths


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


def open_company(at, company):
    widget(at.selectbox, "Abrir ficha").select(company.id).run()
    assert not at.exception
    return at


def test_ui_starts_without_keys_database_or_provider_clients(ui_paths, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("La pantalla no debe crear clientes de proveedores")

    monkeypatch.setattr(bridge, "ProviderClient", forbidden)
    monkeypatch.setattr(bridge, "ClaudeClient", forbidden)
    at = screen()
    assert not at.exception and not at.error
    assert at.title[0].value == "Veryfi Prospecting"
    assert not ui_paths.db.exists()


def test_prepare_criteria_and_reruns_preserve_one_campaign(ui_paths):
    at = screen()
    widget(at.multiselect, "Países").set_value(["MX"])
    widget(at.multiselect, "Segmentos").set_value(["cpg_loyalty"])
    widget(at.text_input, "Palabras clave opcionales").input("recibos, fidelización")
    widget(at.number_input, "Máximo de empresas").set_value(3)
    widget(at.button, "Preparar campaña").click().run()
    assert not at.exception and not at.error
    with Database(ui_paths.db) as db:
        campaigns = db.list_campaigns()
        assert len(campaigns) == 1
        assert campaigns[0].countries == ["MX"] and campaigns[0].segments == ["cpg_loyalty"]
        assert campaigns[0].max_companies == 3 and campaigns[0].filters.keywords == ["recibos", "fidelización"]
        assert campaigns[0].status == "created" and db.list_usage() == []
    at.run()
    with Database(ui_paths.db) as db:
        assert db.list_campaigns() == campaigns and db.list_usage() == []


def test_empty_criteria_are_reported_without_creating_database(ui_paths):
    at = screen()
    widget(at.multiselect, "Países").set_value([])
    widget(at.button, "Preparar campaña").click().run()
    assert not at.exception and at.error
    assert not ui_paths.db.exists()
    assert any("campos obligatorios" in element.value for element in at.text)


def test_invalid_provider_configuration_does_not_echo_sensitive_input(ui_paths):
    ui_paths.access.write_text('{"secret":"NO-MOSTRAR-ESTE-VALOR"}', encoding="utf-8")
    at = screen()
    assert not at.exception and at.error
    assert "NO-MOSTRAR-ESTE-VALOR" not in " ".join(element.value for element in [*at.text, *at.error])
    assert not ui_paths.db.exists()


def test_filters_and_company_detail_show_persisted_evidence(ui_results):
    at = open_company(screen(), ui_results.companies[0])
    assert any("Caso de uso sintético CO" in element.value for element in at.text)
    assert any("Directorio profesional exclusivamente sintético" in element.value for element in at.text)
    widget(at.multiselect, "Filtrar país").set_value(["MX"]).run()
    assert list(at.dataframe[0].value["company"]) == ["Empresa sintética MX"]
    assert "Persona Sintética Uno" not in " ".join(element.value for element in at.text)
    widget(at.multiselect, "Filtrar país").set_value(["CO"])
    widget(at.multiselect, "Filtrar segmento").set_value(["fintech_software"])
    widget(at.multiselect, "Filtrar prioridad").set_value(["high"])
    widget(at.multiselect, "Filtrar canal").set_value(["needs_channel_confirmation"]).run()
    assert list(at.dataframe[0].value["company"]) == ["Empresa sintética CO"]
    widget(at.multiselect, "Filtrar prioridad").set_value(["low"]).run()
    assert any("Ninguna empresa coincide" in element.value for element in at.info)


def test_human_review_saves_reason_and_survives_new_streamlit_session(ui_results):
    at = open_company(screen(), ui_results.companies[0])
    widget(at.selectbox, "Revisión humana").select("accepted")
    widget(at.text_area, "Motivo de la revisión").input("Aceptación exclusivamente sintética, con canal pendiente.")
    widget(at.button, "Guardar revisión").click().run()
    assert not at.exception and not at.error
    saved = read_campaign(ui_results.paths.db, ui_results.campaign.id).companies
    result = next(item for item in saved if item.company.id == ui_results.companies[0].id)
    assert result.run_item.review_status == "accepted" and result.run_item.reviewed_at is not None
    assert result.business_status == "needs_channel_confirmation"
    reopened = open_company(screen(), ui_results.companies[0])
    assert widget(reopened.selectbox, "Revisión humana").value == "accepted"
    assert "exclusivamente sintética" in widget(reopened.text_area, "Motivo de la revisión").value


def test_manual_confirmation_requires_checkbox_and_persists_only_on_explicit_action(ui_results):
    at = open_company(screen(), ui_results.companies[0])
    reason = widget(at.text_area, "Motivo de la confirmación")
    reason.input("Mensajería profesional nominal comprobada sin enviar nada.")
    button = widget(at.button, "Guardar confirmación manual")
    button.click().run()
    assert not at.exception and at.error
    with Database(ui_results.paths.db) as db:
        assert db.get_contact(ui_results.contact.id) == ui_results.contact
    checkbox = next(element for element in at.checkbox if "He comprobado" in element.label)
    checkbox.check()
    widget(at.button, "Guardar confirmación manual").click().run()
    assert not at.exception and not at.error
    result = next(item for item in read_campaign(ui_results.paths.db, ui_results.campaign.id).companies
                  if item.company.id == ui_results.companies[0].id)
    assert result.business_status == "ready_alternative"
    assert result.contacts[0].usable_channels[0].manual_confirmed_at is not None
    assert result.run_item.review_status == "pending"


def test_execution_requires_explicit_operations_and_responsible_confirmation(ui_paths, ui_access, monkeypatch):
    calls = []
    monkeypatch.setattr(app, "execute_campaign", lambda *args, **kwargs: calls.append(True))
    at = screen()
    widget(at.button, "Preparar campaña").click().run()
    widget(at.button, "Autorizar y ejecutar").click().run()
    assert not at.exception and at.error
    widget(at.text_input, "Responsable del cupo").input("Responsable sintético")
    widget(at.text_input, "Referencia de la autorización").input("Aprobación sintética")
    at.checkbox(key="allow_tavily_search").check()
    at.number_input(key="credits_tavily_search").set_value(1.0)
    widget(at.button, "Autorizar y ejecutar").click().run()
    assert not at.exception and at.error and calls == []
    at.checkbox(key="allow_tavily_search").uncheck()
    widget(at.checkbox, "Soy responsable del cupo y autorizo únicamente las operaciones y topes seleccionados.").check()
    widget(at.button, "Autorizar y ejecutar").click().run()
    assert not at.exception and at.error and calls == []
    with Database(ui_paths.db) as db:
        assert db.list_usage() == [] and db.list_campaigns()[0].status == "created"


def test_approved_execution_displays_saved_progress_and_rerun_does_not_repeat(
        ui_paths, ui_access, make_company, make_assessment, monkeypatch):
    events = []

    def simulated(db, campaign_id, exclusions, build):
        run = build(db.get_campaign(campaign_id))
        assert bridge._EXECUTION.locked()
        assert run.authorizations[0].authorized_at > run.budget._session_started_at
        company, evidence = make_company()
        db.save_campaign(run.campaign.model_copy(update={"status": CampaignStatus.RUNNING}))
        db.save_company(company, evidence=evidence)
        item = db.save_run_item(RunItem(campaign_id=campaign_id, company_id=company.id, stage="completed"))
        assessment = make_assessment(campaign_id, company.id, priority="low")
        db.save_assessment(assessment)
        db.save_run_item(item.model_copy(update={"last_assessment_id": assessment.id,
                                               "business_status": BusinessStatus.LOW_FIT}))
        events.append(company.id)
        run.progress(bridge._progress(db, campaign_id, company.id))
        db.save_campaign(run.campaign.model_copy(update={"status": CampaignStatus.COMPLETED}))
        return bridge._report(db, campaign_id)

    monkeypatch.setattr(bridge, "_execute", simulated)
    at = screen()
    widget(at.button, "Preparar campaña").click().run()
    widget(at.text_input, "Responsable del cupo").input("Responsable sintético")
    widget(at.text_input, "Referencia de la autorización").input("Aprobación sintética")
    at.checkbox(key="allow_tavily_search").check()
    at.number_input(key="credits_tavily_search").set_value(1.0)
    widget(at.checkbox, "Soy responsable del cupo y autorizo únicamente las operaciones y topes seleccionados.").check()
    widget(at.button, "Autorizar y ejecutar").click().run()
    assert not at.exception and not at.error
    assert len(events) == 1
    assert at.get("progress") and at.status[0].state == "complete"
    with Database(ui_paths.db) as db:
        assert db.list_campaigns()[0].status == "completed" and len(db.list_run_items(db.list_campaigns()[0].id)) == 1
    at.run()
    assert len(events) == 1 and not at.exception


def test_live_execution_disables_human_writes_close_and_download(ui_results):
    with Database(ui_results.paths.db) as db:
        db.save_campaign(ui_results.campaign.model_copy(update={"status": CampaignStatus.RUNNING}))
    with bridge._EXECUTION:
        at = open_company(screen(), ui_results.companies[0])
        assert widget(at.button, "Guardar revisión").disabled
        assert widget(at.button, "Cerrar campaña conservando resultados").disabled
        assert widget(at.button, "Guardar confirmación manual").disabled
        assert not at.get("download_button")


def test_validated_exclusions_do_not_display_missing_list_warning(ui_results):
    checked = ExclusionList(version="synthetic-v1", validation_status="validated", source_reference="Lista sintética",
                            observed_at=utc_now(), entries=[])
    ui_results.paths.exclusions.write_text(checked.model_dump_json(), encoding="utf-8")
    at = screen()
    assert not at.exception
    assert not any("Lista de exclusiones ausente" in element.value for element in at.warning)


def test_budget_reservation_is_not_added_again_to_pending(ui_results):
    with Database(ui_results.paths.db) as db:
        db.save_usage(Usage(campaign_id=ui_results.campaign.id, provider="anthropic", operation="messages",
                            account_ref="cuenta-sintetica", funding_source="prepaid", request_fingerprint="b" * 64,
                            reserved_cost_usd="0.02", reserved_credits="0", status="reserved"))
    at = screen()
    assert not at.exception
    assert next(metric.value for metric in at.metric if metric.label == "Reservado · campaña") == "USD 0.020000"
    assert any("Pendiente de conciliación: USD 0.020000" in element.value for element in at.caption)


def test_results_prioritize_fit_and_stop_reasons_explain_the_next_action(ui_results):
    at = screen()
    assert not at.exception
    assert list(at.dataframe[0].value["company"]) == ["Empresa sintética CO", "Empresa sintética MX"]
    assert "no se repite" in app.stop_message("duplicate_request")
    assert "autoriza de nuevo" in app.stop_message("authorization_required")
    assert "evidencia" in app.stop_message("assessment_pending:invalid_response")
