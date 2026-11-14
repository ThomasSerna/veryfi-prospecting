"""Versiones de match en campañas exclusivamente sintéticas y bases temporales, sin red."""

import json
from pathlib import Path
import sqlite3

from pydantic import ValidationError
import pytest

from prospecting.contacts import load_contact_match
from prospecting.db import Database
from prospecting.pipeline import prepare_campaign, read_campaign


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_new_campaign_freezes_v3_and_reopening_never_reloads_the_external_file(tmp_path, make_campaign):
    campaign = make_campaign()
    original = campaign.config_snapshot.model_dump(mode="json")
    source = tmp_path / "match.json"
    source.write_bytes((CONFIG_DIR / "contact_match_v3.json").read_bytes())
    path = tmp_path / "synthetic.sqlite3"
    saved = prepare_campaign(path, campaign, contact_match_path=source)
    expected = load_contact_match(source)
    assert saved.config_snapshot.contact_match == expected
    assert campaign.config_snapshot.model_dump(mode="json") == original
    source.write_text("configuración externa inválida", encoding="utf-8")
    assert prepare_campaign(path, campaign, contact_match_path=source) == saved
    assert read_campaign(path, saved.id).contact_match_version == "contact_match_v3"


@pytest.mark.parametrize("content", [None, "no es JSON", '{"version": "contact_match_v9"}', "v1", "v2", "modified"])
def test_invalid_new_config_never_saves_a_campaign_or_falls_back(tmp_path, make_campaign, content):
    source, path = tmp_path / "match.json", tmp_path / "synthetic.sqlite3"
    if content == "v1":
        source.write_bytes((CONFIG_DIR / "contact_match.json").read_bytes())
    elif content == "v2":
        source.write_bytes((CONFIG_DIR / "contact_match_v2.json").read_bytes())
    elif content == "modified":
        data = json.loads((CONFIG_DIR / "contact_match_v3.json").read_text(encoding="utf-8"))
        data["components"]["role"]["levels"]["profile_role"] = 38
        source.write_text(json.dumps(data), encoding="utf-8")
    elif content is not None:
        source.write_text(content, encoding="utf-8")
    with pytest.raises((OSError, ValueError)):
        prepare_campaign(path, make_campaign(), contact_match_path=source)
    with Database(path) as db:
        assert db.list_campaigns() == []


def test_match_snapshot_is_covered_by_campaign_immutability(tmp_path, make_campaign):
    path = tmp_path / "synthetic.sqlite3"
    saved = prepare_campaign(path, make_campaign())
    weights = saved.config_snapshot.contact_match.model_copy(update={"source_reference": "Otra propuesta sintética"})
    changed = saved.model_copy(update={"config_snapshot": saved.config_snapshot.model_copy(update={"contact_match": weights})})
    with Database(path) as db:
        with pytest.raises(ValueError, match="inmutable"):
            db.save_campaign(changed)
        assert db.get_campaign(saved.id) == saved


def test_old_campaign_without_the_new_field_keeps_v1_without_rewriting_its_snapshot(tmp_path, make_campaign):
    path = tmp_path / "synthetic.sqlite3"
    campaign = make_campaign(status="completed")
    with Database(path) as db:
        db.save_campaign(campaign)
    # Simula el JSON anterior a T19, donde el campo ni siquiera existía.
    with sqlite3.connect(path) as connection:
        raw = json.loads(connection.execute("SELECT config_snapshot FROM campaigns").fetchone()[0])
        raw.pop("contact_match")
        original = json.dumps(raw, ensure_ascii=False)
        connection.execute("UPDATE campaigns SET config_snapshot=?", (original,))
    view = read_campaign(path, campaign.id)
    assert view.campaign.config_snapshot.contact_match is None
    assert view.contact_match_version == "contact_match_v1"
    assert prepare_campaign(path, campaign, contact_match_path=tmp_path / "missing.json").id == campaign.id
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT config_snapshot FROM campaigns").fetchone()[0] == original


@pytest.mark.parametrize("version", ["contact_match_v2", "contact_match_v3"])
def test_invalid_saved_match_is_rejected_instead_of_read_as_v1(tmp_path, make_campaign, version):
    path = tmp_path / "synthetic.sqlite3"
    campaign = make_campaign()
    weights = load_contact_match(CONFIG_DIR / f"{version}.json")
    saved = campaign.model_copy(update={"config_snapshot": campaign.config_snapshot.model_copy(update={"contact_match": weights})})
    with Database(path) as db:
        db.save_campaign(saved)
    with sqlite3.connect(path) as connection:
        raw = json.loads(connection.execute("SELECT config_snapshot FROM campaigns").fetchone()[0])
        raw["contact_match"]["components"]["employment"]["levels"]["unknown"] = 1
        corrupted = json.dumps(raw)
        connection.execute("UPDATE campaigns SET config_snapshot=?", (corrupted,))
    with pytest.raises(ValidationError):
        read_campaign(path, saved.id)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT config_snapshot FROM campaigns").fetchone()[0] == corrupted


@pytest.mark.parametrize("version", ["contact_match_v1", "contact_match_v2"])
def test_view_can_use_v3_without_rewriting_historical_snapshot(tmp_path, make_campaign, version):
    path = tmp_path / "synthetic.sqlite3"
    campaign = make_campaign(status="completed")
    source = "contact_match.json" if version == "contact_match_v1" else f"{version}.json"
    original = load_contact_match(CONFIG_DIR / source)
    campaign = campaign.model_copy(update={
        "config_snapshot": campaign.config_snapshot.model_copy(update={"contact_match": original})})
    with Database(path) as db:
        db.save_campaign(campaign)
    with sqlite3.connect(path) as connection:
        before = connection.execute("SELECT config_snapshot FROM campaigns").fetchone()[0]
    current = load_contact_match(CONFIG_DIR / "contact_match_v3.json")
    view = read_campaign(path, campaign.id, contact_match_config=current)
    assert view.contact_match_version == "contact_match_v3"
    assert view.campaign.config_snapshot.contact_match == original
    assert read_campaign(path, campaign.id).contact_match_version == version
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT config_snapshot FROM campaigns").fetchone()[0] == before
