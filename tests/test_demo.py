"""Demostración local: base temporal exclusivamente sintética, sin `data/`, claves ni proveedores."""

import csv
from io import StringIO
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import django
import pytest
from django.test import Client, override_settings
from django.urls import reverse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import demo
from core.presentation import download_csv, stop_message
from prospecting.contacts import fold_words
from prospecting.models import BusinessStatus, utc_now
from prospecting.pipeline import campaign as bridge
from prospecting.pipeline import confirm_alternative_channel, read_campaign
from prospecting.qualification import compute_score, rubric_for


@pytest.fixture
def seeded(tmp_path):
    campaign = demo.build_demo(tmp_path, utc_now())
    return SimpleNamespace(folder=tmp_path, campaign=campaign, db=tmp_path / demo.DB_NAME,
                           exclusions=tmp_path / demo.EXCLUSIONS_NAME)


def current(case):
    return read_campaign(case.db, case.campaign.id, exclusions_path=case.exclusions)


def test_demo_reaches_every_business_status_through_the_real_rules(seeded):
    view = current(seeded)
    assert sorted(item.business_status for item in view.companies) == sorted(BusinessStatus)
    assert all(item.business_status == item.run_item.business_status for item in view.companies)
    rubric = rubric_for(view.campaign)
    for item in view.companies:
        if item.assessment is not None:
            assert compute_score(item.assessment.criteria, rubric) == (item.assessment.fit_score, item.assessment.coverage)
    pending = next(item for item in view.companies if item.business_status == "needs_channel_confirmation")
    person = pending.contacts[0].contact
    confirm_alternative_channel(seeded.db, seeded.campaign.id, person.id, "linkedin", person.channels[0].value,
                                reason="Confirmación sintética durante la prueba; no se envió nada.", confirmed=True)
    after = {item.company.id: item.business_status for item in current(seeded).companies}
    assert after[pending.company.id] == "ready_alternative"


def test_every_demo_stop_reason_has_its_own_message(seeded):
    reasons = [item.run_item.stop_reason for item in current(seeded).companies]
    assert None not in reasons
    assert [reason for reason in reasons if "quedó pendiente" in stop_message(reason)] == []


def test_demo_only_creates_new_files_outside_local_data(tmp_path):
    existing = tmp_path / demo.DB_NAME
    existing.write_bytes(b"base existente")
    with pytest.raises(FileExistsError):
        demo.build_demo(tmp_path, utc_now())
    assert existing.read_bytes() == b"base existente"
    assert not (tmp_path / demo.EXCLUSIONS_NAME).exists()
    target = demo.PROJECT_ROOT / "data" / f"demo-{uuid4()}"
    with pytest.raises(ValueError, match="data/"):
        demo.build_demo(target, utc_now())
    assert not target.exists()


def test_every_seeded_record_is_visibly_synthetic(seeded):
    view = current(seeded)
    assert view.exclusions_status == "pending"
    for item in view.companies:
        assert "sintetica" in fold_words(item.company.name) and item.company.domain.endswith(".example")
        for fact in item.evidence:
            assert "sintetic" in fold_words(f"{fact.claim} {fact.excerpt or ''} {fact.external_reference or ''}")
            assert fact.url is None or fact.url.host.endswith(".example")
        for person in item.contacts:
            assert "sintetica" in fold_words(person.contact.name) or person.contact.name == "Persona S."
            for channel in person.contact.channels:
                assert channel.value.endswith(".example") or channel.value.startswith("https://www.linkedin.com/in/demo-")


def test_demo_environment_removes_keys_and_blocks_execution(seeded, monkeypatch):
    environ = {key: "clave-exclusivamente-sintetica" for key in demo.PROVIDER_KEYS} | {"PATH": "sin-cambios"}
    demo.apply_environment(seeded.folder, environ)
    assert not set(demo.PROVIDER_KEYS) & set(environ) and environ["PATH"] == "sin-cambios"
    assert environ["PROSPECTING_DEMO"] == "1" and Path(environ["PROSPECTING_DB_PATH"]) == seeded.db
    assert not Path(environ["PROSPECTING_ACCESS_PATH"]).exists()

    def forbidden(*args, **kwargs):
        pytest.fail("La demostración no debe crear clientes de proveedores")

    from core import execution

    monkeypatch.setattr(bridge, "ProviderClient", forbidden)
    monkeypatch.setattr(bridge, "ClaudeClient", forbidden)
    monkeypatch.setattr(execution, "_active_campaign_id", None)
    monkeypatch.setattr(execution, "_reports", {})
    client = Client(SERVER_NAME="localhost")
    with override_settings(PROSPECTING_DEMO=True, PROSPECTING_DB_PATH=Path(environ["PROSPECTING_DB_PATH"]),
                           PROSPECTING_ACCESS_PATH=Path(environ["PROSPECTING_ACCESS_PATH"]),
                           PROSPECTING_EXCLUSIONS_PATH=Path(environ["PROSPECTING_EXCLUSIONS_PATH"])):
        page = client.get(reverse("webapp:campaign", kwargs={"campaign_id": seeded.campaign.id}))
        response = client.post(reverse("webapp:execute", kwargs={"campaign_id": seeded.campaign.id}), {})
    assert page.status_code == 200
    assert "Demostración con datos exclusivamente sintéticos." in page.content.decode("utf-8")
    assert response.status_code == 400 and "Configura el acceso" in response.json()["error_message"]


def test_demo_shows_hostile_text_as_plain_text(seeded):
    hostile = next(item for item in current(seeded).companies if item.business_status == "insufficient_evidence")
    with override_settings(PROSPECTING_DB_PATH=seeded.db, PROSPECTING_EXCLUSIONS_PATH=seeded.exclusions,
                           PROSPECTING_ACCESS_PATH=seeded.folder / demo.ACCESS_NAME):
        page = Client(SERVER_NAME="localhost").get(reverse("webapp:company", kwargs={
            "campaign_id": seeded.campaign.id, "company_id": hostile.company.id}))
    content = page.content.decode("utf-8")
    assert page.status_code == 200
    assert "<script>alert" not in content and "&lt;script&gt;alert" in content


def test_demo_csv_exports_formula_text_as_text(seeded):
    content = download_csv(seeded.db, seeded.campaign.id, include_all=True, exclusions_path=seeded.exclusions)
    rows = list(csv.reader(StringIO(content.decode("utf-8-sig"))))
    cells = [cell for row in rows[1:] for cell in row]
    assert len(rows) - 1 == len(demo.COMPANIES)
    assert [cell for cell in cells if cell.lstrip().startswith(("=", "+", "-", "@"))] == []
    assert any(cell.startswith("'\t=1+2 Motivo sintético") for cell in cells)
