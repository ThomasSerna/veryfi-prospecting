"""Resumen visual de campañas con datos sintéticos y una sola lectura contextual."""

from datetime import timedelta
import os
import re
from types import SimpleNamespace

import django
import pytest
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core import execution, views
from prospecting.db import Database
from prospecting.models import RunItem


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
    assert context["highlighted_campaign"] is context["campaign_insights"] is None
    assert "budget_view" not in context
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
    assert context["highlighted_campaign"].id == active.id
    assert context["highlighted_is_active"] is True


def test_dashboard_labels_the_latest_without_an_active_campaign(redesign_paths, make_campaign, monkeypatch):
    latest = make_campaign(status="completed")
    with Database(redesign_paths.db) as db:
        db.save_campaign(latest)
    monkeypatch.setattr(views, "render", lambda request, template, context: context)
    context = views.campaigns(RequestFactory().get("/"))
    assert context["highlighted_campaign"].id == latest.id
    assert context["highlighted_is_active"] is False


def test_home_is_a_single_campaign_summary_and_history_is_separate(redesign_paths, make_campaign):
    active = make_campaign(status="paused_budget", countries=["CO"])
    latest = make_campaign(status="completed", countries=["MX"], created_at=active.created_at + timedelta(seconds=1))
    with Database(redesign_paths.db) as db:
        db.save_campaign(active)
        db.save_campaign(latest)
    client = Client(SERVER_NAME="localhost")
    home = client.get(reverse("webapp:campaigns"))
    content = home.content.decode()
    assert home.status_code == 200
    assert "<table" not in content and "Campañas recientes" not in content
    assert "Prioridad de empresas" not in content
    assert str(active.id) in content and str(latest.id) not in content
    assert content.count('class="home-metric ') == 2
    assert "home-metric-total" not in content and "Revisar siguiente" not in content
    assert "Empresas con un canal disponible" not in content
    assert "Sin revisar" in content and "Con contacto listo" in content
    assert 'href="/campaigns/"' in content
    # La barra superior ya no resume el presupuesto ni el menú anuncia el servicio local.
    assert "data-budget-summary" not in content and "Servicio local" not in content
    history = client.get(reverse("webapp:campaign_history"))
    content = history.content.decode()
    assert history.status_code == 200
    assert 'aria-label="Historial de campañas"' in content
    assert str(active.id) in content and str(latest.id) in content
    assert 'aria-current="page">' in content


@pytest.mark.parametrize("with_campaign", [False, True])
def test_summary_has_one_headline_without_repeated_explanations(redesign_paths, make_campaign, with_campaign):
    if with_campaign:
        with Database(redesign_paths.db) as db:
            db.save_campaign(make_campaign(status="completed"))
    response = Client(SERVER_NAME="localhost").get(reverse("webapp:campaigns"))
    assert response.status_code == 200
    content = response.content.decode()
    heading = re.search(r"<h1\b[^>]*>(.*?)</h1>", content, re.S)
    assert heading is not None
    assert " ".join(re.sub(r"<[^>]*>", "", heading[1]).split()) == "Resumen"
    assert len(re.findall(r"<h1\b", content)) == 1
    assert "Una mirada." not in content and "El siguiente paso." not in content
    assert "Tu investigación, donde la dejaste." not in content
    assert "El resumen corresponde a" not in content
    assert "La disponibilidad del contacto y la revisión son independientes." not in content


@pytest.mark.parametrize("with_campaign", [False, True])
def test_drawer_exposes_navigation_across_routes(redesign_paths, make_campaign, make_company, with_campaign):
    routes = [reverse(f"webapp:{name}") for name in ("campaigns", "campaign_history", "new_campaign")]
    if with_campaign:
        campaign = make_campaign(status="completed")
        with Database(redesign_paths.db) as db:
            db.save_campaign(campaign)
            for name in ("Primera empresa sintética", "Segunda empresa sintética"):
                company, facts = make_company(name=name)
                db.save_company(company, evidence=facts)
                db.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id))
        routes += [reverse("webapp:campaign", kwargs={"campaign_id": campaign.id}),
                   reverse("webapp:company", kwargs={"campaign_id": campaign.id, "company_id": company.id})]
    client = Client(SERVER_NAME="localhost")
    for route in routes:
        response = client.get(route)
        assert response.status_code == 200
        content = response.content.decode()
        topbar = re.search(r'<header class="topbar">(.*?)</header>', content, re.S)
        assert topbar is not None
        is_summary = route == reverse("webapp:campaigns")
        assert " ".join(re.sub(r"<[^>]*>", "", topbar[1]).split()) == (
            "Prospecting Ver historial" if is_summary else "Prospecting"
        )
        if is_summary:
            assert re.search(r'<a\b[^>]*href="/campaigns/"[^>]*>.*?Ver historial</a>', topbar[1], re.S)
            assert content.count("Ver historial") == 1
        assert 'aria-label="Veryfi Prospecting, inicio"' in topbar[1]
        assert "/static/img/veryfi-logo.svg" in topbar[1]
        drawer = re.search(r'<details\b[^>]*id="navigation-drawer"[^>]*>(.*?)</details>', content, re.S)
        assert drawer is not None and 'aria-label="Menú principal"' in drawer[1]
        assert 'data-live-region="navigation"' in drawer[1]
        assert 'href="#main"' in content
        active_url = route if route in routes[:3] else reverse("webapp:campaign_history")
        assert re.search(r'<a\b[^>]*href="' + re.escape(active_url) + r'"[^>]*aria-current="(?:page|location)"', drawer[1])
        assert "breadcrumb" not in topbar[1] and "sequence-nav" not in topbar[1]
    if with_campaign:
        company_page = content[content.index('class="company-page"'):]
        assert 'aria-label="Navegación secuencial de empresas"' in company_page
        assert f'href="{reverse("webapp:campaign", kwargs={"campaign_id": campaign.id})}"' in company_page
        assert "Volver a la campaña" in company_page


@pytest.mark.parametrize(("route", "notice"), [
    ("webapp:campaign_history", "Hay una investigación en curso."),
    ("webapp:campaigns", "Investigación en curso."),
])
def test_running_campaign_keeps_creation_blocked(redesign_paths, make_campaign, monkeypatch, route, notice):
    active = make_campaign(status="running")
    with Database(redesign_paths.db) as db:
        db.save_campaign(active)
        db.save_campaign(make_campaign(status="completed", created_at=active.created_at + timedelta(seconds=1)))
    calls = []
    original = views.read_campaign

    def observed(db_path, campaign_id, **kwargs):
        calls.append(campaign_id)
        return original(db_path, campaign_id, **kwargs)

    monkeypatch.setattr(views, "read_campaign", observed)
    monkeypatch.setattr(execution, "snapshot", lambda campaign_id: {"is_executing": True})
    response = Client(SERVER_NAME="localhost").get(reverse(route))
    assert response.status_code == 200 and calls == [active.id]
    main = response.content.decode().split('<main ', 1)[1]
    assert notice in main
    assert re.search(r'<a\b(?=[^>]*href="/campaigns/new/")(?=[^>]*aria-disabled="true")(?=[^>]*tabindex="-1")[^>]*>', main)


def test_empty_history_is_read_only_and_does_not_create_database(redesign_paths):
    client = Client(SERVER_NAME="localhost")
    response = client.get(reverse("webapp:campaign_history"))
    assert response.status_code == 200 and "Sin campañas registradas" in response.content.decode()
    assert client.post(reverse("webapp:campaign_history")).status_code == 405
    assert not redesign_paths.db.exists()


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


@pytest.mark.parametrize("with_campaign", [False, True])
def test_summary_map_is_decorative_and_outside_dashboard_polling(redesign_paths, make_campaign, with_campaign):
    if with_campaign:
        with Database(redesign_paths.db) as db:
            db.save_campaign(make_campaign(status="completed"))
    client = Client(SERVER_NAME="localhost")
    response = client.get(reverse("webapp:campaigns"))
    assert response.status_code == 200
    content = response.content.decode()
    image = "img/latam-contours.webp"
    background, dashboard = content.split("data-live-dashboard", 1)
    assert re.search(r'<[^>]+class="summary-map"[^>]*aria-hidden="true"', background)
    assert re.search(r'<img\b(?=[^>]*latam-contours.webp)(?=[^>]*alt="")[^>]*>', background)
    assert re.search(r'srcset="[^"]*latam-contours\.webp\?[^"]+ 1800w, [^"]*latam-contours-hd\.webp 3000w"', background)
    assert re.search(r'<svg\b[^>]*class="summary-currents"[^>]*>.*?<path\b', background, re.S)
    assert 'src="/static/js/summary-map.js' in background
    assert 'role="switch"' not in background and "Animación del mapa" not in content
    assert image not in dashboard
    assert ("Abrir campaña" if with_campaign else "Preparar campaña") in dashboard
    for route in ("webapp:campaign_history", "webapp:new_campaign"):
        other = client.get(reverse(route))
        assert other.status_code == 200
        other_content = other.content.decode()
        assert image not in other_content and "latam-contours-hd.webp" not in other_content
        assert "summary-map.css" not in other_content and "summary-map.js" not in other_content
