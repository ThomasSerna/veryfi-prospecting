"""Resumen visual de campañas con datos sintéticos y una sola lectura contextual."""

from datetime import timedelta
import os
from types import SimpleNamespace

import django
import pytest
from django.test import Client, RequestFactory, override_settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core import execution, views
from prospecting.db import Database


@pytest.fixture
def redesign_paths(tmp_path, monkeypatch):
    for variable in ("TAVILY_API_KEY", "ANTHROPIC_API_KEY", "APOLLO_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(execution, "_active_campaign_id", None)
    monkeypatch.setattr(execution, "_reports", {})
    paths = SimpleNamespace(db=tmp_path / "synthetic.sqlite3", access=tmp_path / "access.json",
                            exclusions=tmp_path / "exclusions.json")
    with override_settings(PROSPECTING_DB_PATH=paths.db, PROSPECTING_ACCESS_PATH=paths.access,
                           PROSPECTING_EXCLUSIONS_PATH=paths.exclusions):
        yield paths


def result(*, review="pending", stage="completed", priority=None, status=None):
    return SimpleNamespace(run_item=SimpleNamespace(review_status=review, stage=stage),
                           assessment=None if priority is None else SimpleNamespace(priority=priority),
                           business_status=status)


def test_campaign_insights_separate_progress_review_and_contact():
    pending_ready = result(status="ready_preferred", priority="high")
    view = SimpleNamespace(companies=[pending_ready, result(review="accepted", stage="researched"),
                                     result(status="excluded", priority="high")])
    summary = views._campaign_insights(view)
    assert (summary["total"], summary["completed"], summary["review_pending"], summary["ready"]) == (3, 2, 2, 1)
    assert summary["progress"] == 67 and summary["next_review"] is pending_ready
    distribution = {item["value"]: item for item in summary["priority_distribution"]}
    assert distribution["high"]["count"] == 1 and distribution["excluded"]["count"] == 1
    assert distribution["pending"]["count"] == 1 and distribution["pending"]["query"] == ""
    assert distribution["excluded"]["query"] == "availability=excluded"
    assert sum(item["count"] for item in distribution.values()) == summary["total"]


def test_campaign_insights_do_not_invent_progress_without_companies():
    summary = views._campaign_insights(SimpleNamespace(companies=[]))
    assert summary["progress"] is None and summary["next_review"] is None
    assert summary["total"] == summary["review_pending"] == summary["ready"] == 0
    assert all(item["count"] == item["percent"] == 0 for item in summary["priority_distribution"])


def test_campaign_insights_do_not_count_a_pending_channel_as_ready():
    summary = views._campaign_insights(SimpleNamespace(companies=[
        result(review="accepted", status="needs_channel_confirmation"),
        result(status="ready_alternative"),
    ]))
    assert summary["needs_confirmation"] == summary["ready"] == summary["review_pending"] == 1


def test_dashboard_without_campaigns_does_not_read_or_create_database(redesign_paths, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("El inicio vacío no debe leer ni crear una campaña.")

    monkeypatch.setattr(views, "_campaign_view", forbidden)
    monkeypatch.setattr(views, "render", lambda request, template, context: context)
    context = views.campaigns(RequestFactory().get("/"))
    assert context["highlighted_campaign"] is context["campaign_insights"] is context["budget_view"] is None
    assert not redesign_paths.db.exists()


def test_dashboard_reads_only_the_active_campaign(redesign_paths, make_campaign, monkeypatch):
    active = make_campaign(status="paused_budget")
    latest = make_campaign(status="completed", created_at=active.created_at + timedelta(seconds=1))
    with Database(redesign_paths.db) as db:
        db.save_campaign(active)
        db.save_campaign(latest)
    calls = []
    original = views.read_campaign

    def observed(db_path, campaign_id, **kwargs):
        calls.append(campaign_id)
        return original(db_path, campaign_id, **kwargs)

    monkeypatch.setattr(views, "read_campaign", observed)
    monkeypatch.setattr(views, "render", lambda request, template, context: context)
    context = views.campaigns(RequestFactory().get("/"))
    assert calls == [active.id]
    assert context["highlighted_campaign"].id == context["budget_campaign"].id == active.id
    assert context["highlighted_is_active"] is True
    assert context["budget_view"] is context["highlighted_view"].budget


def test_dashboard_labels_the_latest_without_an_active_campaign(redesign_paths, make_campaign, monkeypatch):
    latest = make_campaign(status="completed")
    with Database(redesign_paths.db) as db:
        db.save_campaign(latest)
    monkeypatch.setattr(views, "render", lambda request, template, context: context)
    context = views.campaigns(RequestFactory().get("/"))
    assert context["highlighted_campaign"].id == latest.id
    assert context["highlighted_is_active"] is False


def test_preparation_keeps_its_groups_and_active_campaign_block(redesign_paths, make_campaign):
    active = make_campaign(status="paused_budget")
    with Database(redesign_paths.db) as db:
        db.save_campaign(active)
    response = Client(SERVER_NAME="localhost").get("/campaigns/new/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert all(f"<legend>{name}</legend>" in content for name in ("Mercado", "Alcance", "Resumen"))
    assert "Hay una campaña sin terminar." in content
    assert "disabled" in content and str(active.id) in content
