"""Ejecución Django simulada: sincronización explícita, permisos nuevos y ninguna red."""

from threading import Event, Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest

from prospecting.db import Database
from prospecting.models import BusinessStatus, CampaignStatus, RunItem
from prospecting.pipeline import campaign as bridge
from webapp import execution

from test_ui import client, confirmation, prepare, text, ui_access, ui_paths, ui_results, url


def approval(**fields):
    return {
        "responsible": "Responsable exclusivamente sintético",
        "reference": "Aprobación exclusivamente sintética",
        "confirmed": "on", "allow_tavily_search": "on",
        "cost_tavily_search": "0", "credits_tavily_search": "1", **fields,
    }


def prepared_campaign(client, ui_paths):
    assert prepare(client).status_code == 302
    with Database(ui_paths.db) as db:
        return db.list_campaigns()[0]


@pytest.fixture
def threads(monkeypatch):
    """Todos los trabajadores de prueba terminan antes de restaurar el estado global."""
    created = []
    release = Event()

    def create_thread(*args, **kwargs):
        thread = Thread(*args, **kwargs)
        created.append(thread)
        return thread

    monkeypatch.setattr(execution.threading, "Thread", create_thread)
    yield SimpleNamespace(created=created, release=release)
    release.set()
    for thread in created:
        if thread.ident is not None:
            thread.join(timeout=5)
            assert not thread.is_alive(), "El trabajador sintético debe terminar antes de cerrar la prueba."


@pytest.fixture
def blocked_execution(monkeypatch, threads, make_company):
    entered = Event()
    calls = []

    def simulated(db_path, campaign_id, **kwargs):
        calls.append((campaign_id, kwargs))
        company, evidence = make_company()
        with Database(db_path) as db:
            db.save_company(company, evidence=evidence)
            db.save_run_item(RunItem(campaign_id=campaign_id, company_id=company.id, stage="researched"))
        entered.set()
        assert threads.release.wait(timeout=30), "La prueba debe liberar el proveedor sintético."
        return SimpleNamespace(stop_reason="authorization_required")

    monkeypatch.setattr(execution, "execute_campaign", simulated)
    return SimpleNamespace(entered=entered, calls=calls, release=threads.release)


@pytest.mark.parametrize("fields", [
    {"confirmed": ""}, {"responsible": ""}, {"reference": ""},
    {"allow_tavily_search": ""}, {"cost_tavily_search": "-1"},
    {"cost_tavily_search": ""}, {"credits_tavily_search": ""},
    {"credits_tavily_search": "NaN"},
])
def test_execution_requires_explicit_operations_caps_responsible_and_confirmation(
        ui_paths, ui_access, client, monkeypatch, fields):
    calls = []
    monkeypatch.setattr(execution, "start_execution", lambda *args, **kwargs: calls.append(kwargs))
    campaign = prepared_campaign(client, ui_paths)
    response = client.post(url("execute", campaign.id), approval(**fields))
    assert response.status_code == 400
    assert calls == []
    with Database(ui_paths.db) as db:
        assert db.list_usage() == [] and db.get_campaign(campaign.id).status == "created"


def test_missing_provider_key_disables_and_rejects_that_authorization(
        ui_paths, ui_access, client, monkeypatch):
    campaign = prepared_campaign(client, ui_paths)
    monkeypatch.delenv("TAVILY_API_KEY")
    calls = []
    monkeypatch.setattr(execution, "start_execution", lambda *args, **kwargs: calls.append(kwargs))
    response = client.post(url("execute", campaign.id), approval())
    assert response.status_code == 400 and calls == []


def test_execute_starts_one_daemon_and_polling_or_second_click_cannot_repeat(
        ui_paths, ui_access, client, threads, blocked_execution):
    campaign = prepared_campaign(client, ui_paths)
    path = url("execute", campaign.id)
    response = client.post(path, approval())
    assert response.status_code == 202
    assert blocked_execution.entered.wait(timeout=5)
    assert response.json()["is_executing"] is True
    assert len(threads.created) == 1 and threads.created[0].daemon is True
    assert client.post(path, approval()).status_code == 202
    assert client.post(path, {}).status_code == 202
    for name in ("campaign", "status"):
        response = client.get(url(name, campaign.id))
        assert response.status_code == 200, text(response)
    state = client.get(url("status", campaign.id)).json()
    assert state["is_executing"] is True
    assert "Empresa sintética" in state["html"]
    assert "Desconocido" in state["html"]
    assert len(blocked_execution.calls) == len(threads.created) == 1
    blocked_execution.release.set()
    threads.created[0].join(timeout=5)
    assert not threads.created[0].is_alive()
    refreshed = client.get(url("status", campaign.id)).json()
    assert refreshed["is_executing"] is False
    assert refreshed["stop_reason"] == "authorization_required"
    assert "authorization_required" in text(client.get(url("campaign", campaign.id)))


def test_pending_thread_window_blocks_every_mutation_and_export(
        ui_results, ui_access, client, monkeypatch):
    case = ui_results
    with Database(case.paths.db) as db:
        db.save_campaign(case.campaign.model_copy(update={"status": CampaignStatus.RUNNING}))
    started = []

    class PendingThread:
        def __init__(self, *args, **kwargs):
            assert kwargs["daemon"] is True

        def start(self):
            started.append(True)

    monkeypatch.setattr(execution.threading, "Thread", PendingThread)
    assert client.post(url("execute", case.campaign.id), approval()).status_code == 202
    assert not bridge._EXECUTION.locked()
    assert execution.snapshot(case.campaign.id)["is_executing"] is True
    assert len(started) == 1
    assert prepare(client).status_code == 409
    assert client.post(url("close", case.campaign.id)).status_code == 409
    assert client.post(url("review", case.campaign.id, case.companies[0].id),
                       {"status": "accepted", "reason": "Motivo sintético."}).status_code == 409
    assert client.post(url("confirm_channel", case.campaign.id, case.companies[0].id),
                       confirmation(case, confirmed="on")).status_code == 409
    assert client.get(url("export", case.campaign.id)).status_code == 409
    other = case.campaign.model_copy(update={"id": uuid4(), "status": CampaignStatus.PARTIAL})
    with Database(case.paths.db) as db:
        db.save_campaign(other)
    assert client.post(url("execute", other.id), approval()).status_code == 409
    assert len(started) == 1


def test_failure_to_start_thread_releases_campaign_for_retry(
        ui_paths, ui_access, client, monkeypatch):
    campaign = prepared_campaign(client, ui_paths)

    class BrokenThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("Error sintético al iniciar el trabajador.")

    monkeypatch.setattr(execution.threading, "Thread", BrokenThread)
    response = client.post(url("execute", campaign.id), approval())
    assert response.status_code == 503
    assert execution.snapshot(campaign.id)["is_executing"] is False
    assert client.get(url("campaign", campaign.id)).status_code == 200
    assert prepare(client).status_code == 302


def test_terminal_worker_error_is_retained_after_refresh_without_echoing_secret(
        ui_paths, ui_access, client, threads, monkeypatch):
    campaign = prepared_campaign(client, ui_paths)

    def failed(*args, **kwargs):
        raise RuntimeError("NO-MOSTRAR-SECRETO-SINTÉTICO")

    monkeypatch.setattr(execution, "execute_campaign", failed)
    assert client.post(url("execute", campaign.id), approval()).status_code == 202
    threads.created[0].join(timeout=5)
    assert not threads.created[0].is_alive()
    state = client.get(url("status", campaign.id)).json()
    assert state["is_executing"] is False and state["error_message"]
    page = text(client.get(url("campaign", campaign.id)))
    assert state["error_message"] in page
    assert "NO-MOSTRAR-SECRETO-SINTÉTICO" not in page


def test_approved_execution_uses_new_budget_session_and_displays_saved_results(
        ui_paths, ui_access, client, threads, make_company, make_assessment, monkeypatch):
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
        db.save_campaign(run.campaign.model_copy(update={"status": CampaignStatus.COMPLETED}))
        return bridge._report(db, campaign_id)

    monkeypatch.setattr(bridge, "_execute", simulated)
    campaign = prepared_campaign(client, ui_paths)
    assert client.post(url("execute", campaign.id), approval()).status_code == 202
    threads.created[0].join(timeout=5)
    assert not threads.created[0].is_alive()
    state = client.get(url("status", campaign.id)).json()
    assert state["is_executing"] is False and state["error_message"] is None
    assert len(events) == 1
    assert set(client.session.keys()) == {"draft_id"}
    assert "Empresa sintética" in text(client.get(url("campaign", campaign.id)))
    with Database(ui_paths.db) as db:
        assert db.get_campaign(campaign.id).status == "completed"
        assert len(db.list_run_items(campaign.id)) == 1
    client.get(url("campaign", campaign.id))
    client.get(url("status", campaign.id))
    assert len(events) == 1


@pytest.mark.parametrize("fields", [
    {"credits_tavily_search": "11"}, {"cost_tavily_search": "2"},
])
def test_caps_above_checked_allowance_never_create_provider_clients_or_spend(
        ui_paths, ui_access, client, threads, monkeypatch, fields):
    campaign = prepared_campaign(client, ui_paths)

    def forbidden(*args, **kwargs):
        pytest.fail("El pipeline debe comprobar los topes antes de crear clientes.")

    monkeypatch.setattr(bridge, "ProviderClient", forbidden)
    monkeypatch.setattr(bridge, "ClaudeClient", forbidden)
    assert client.post(url("execute", campaign.id), approval(**fields)).status_code == 202
    threads.created[0].join(timeout=5)
    assert not threads.created[0].is_alive()
    state = client.get(url("status", campaign.id)).json()
    assert state["is_executing"] is False
    assert state["error_message"] and "supera" in state["error_message"]
    with Database(ui_paths.db) as db:
        assert db.list_usage() == [] and db.get_campaign(campaign.id).status == "created"


def test_resume_requires_a_new_explicit_authorization(
        ui_paths, ui_access, client, threads, monkeypatch):
    calls = []

    def paused(db_path, campaign_id, **kwargs):
        calls.append(kwargs["approvals"])
        with Database(db_path) as db:
            db.save_campaign(db.get_campaign(campaign_id).model_copy(update={"status": CampaignStatus.PAUSED_BUDGET}))
        return SimpleNamespace(stop_reason="authorization_required")

    monkeypatch.setattr(execution, "execute_campaign", paused)
    campaign = prepared_campaign(client, ui_paths)
    assert client.post(url("execute", campaign.id), approval()).status_code == 202
    threads.created[0].join(timeout=5)
    assert not threads.created[0].is_alive()
    assert client.post(url("execute", campaign.id), {}).status_code == 400
    assert client.post(url("execute", campaign.id), approval(confirmed="")).status_code == 400
    assert len(calls) == 1
    assert client.post(url("execute", campaign.id), approval(reference="Otra aprobación sintética")).status_code == 202
    threads.created[1].join(timeout=5)
    assert not threads.created[1].is_alive()
    assert len(calls) == 2 and calls[0] is not calls[1]
    assert calls[1][0].source_reference == "Otra aprobación sintética"
