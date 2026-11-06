"""Migración y referencias T15 con datos exclusivamente sintéticos."""

import sqlite3
from uuid import uuid4

import pytest
from pydantic import ValidationError

from prospecting.db import Database, _SCHEMA_V1, _schema_signature
from prospecting.models import ProfileMatch, RunItem, VeryfiConfig


def legacy_database(path, records, persist_records):
    """Copia registros sintéticos a las columnas exactas del esquema original."""
    current = path.with_name("synthetic-current.sqlite3")
    with Database(current) as database:
        persist_records(database, records)
    with sqlite3.connect(current) as source, sqlite3.connect(path) as destination:
        destination.executescript(_SCHEMA_V1 + "PRAGMA user_version=1;")
        for table in ("campaigns", "companies", "contacts", "evidence", "run_items", "assessments", "usage"):
            columns = [row[1] for row in destination.execute(f"PRAGMA table_info({table})")]
            names = ",".join(columns)
            rows = source.execute(f"SELECT {names} FROM {table}").fetchall()
            destination.executemany(f"INSERT INTO {table} ({names}) VALUES ({','.join('?' for _ in columns)})", rows)


def test_migration_preserves_results_and_spending(tmp_path, records, persist_records):
    path = tmp_path / "synthetic-legacy.sqlite3"
    legacy_database(path, records, persist_records)
    with Database(path) as database:
        assert database.get_campaign(records.campaign.id) == records.campaign
        assert database.get_company(records.company.id) == records.company
        assert database.get_contact(records.contact.id) == records.contact
        assert database.get_assessment(records.assessment.id) == records.assessment
        assert database.get_assessment(records.assessment.id).profile_matches == []
        assert database.list_usage() == [records.usage]
        assert database.get_run_item(records.campaign.id, records.company.id) == records.run_item
    with Database(path) as reopened, Database(tmp_path / "synthetic-new.sqlite3") as fresh:
        assert _schema_signature(reopened._connection) == _schema_signature(fresh._connection)
        assert reopened.list_usage() == [records.usage]
        assert reopened._connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_migration_rolls_back_if_verification_fails(tmp_path, records, persist_records, monkeypatch):
    path = tmp_path / "synthetic-rollback.sqlite3"
    legacy_database(path, records, persist_records)
    verify = Database._verify_schema

    def reject_v2(self, *, version=2):
        if version == 2:
            raise sqlite3.DatabaseError("Fallo sintético de validación posterior.")
        verify(self, version=version)

    monkeypatch.setattr(Database, "_verify_schema", reject_v2)
    with pytest.raises(sqlite3.DatabaseError, match="sintético"):
        Database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert "profile_matches" not in {row[1] for row in connection.execute("PRAGMA table_info(assessments)")}
        assert connection.execute("SELECT request_id FROM usage").fetchone()[0] == str(records.usage.request_id)


def test_invalid_v1_is_not_partially_migrated(tmp_path):
    path = tmp_path / "synthetic-incomplete-v1.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript("CREATE TABLE paid_results (amount TEXT); PRAGMA user_version=1;")
        connection.execute("INSERT INTO paid_results VALUES ('0.25')")
    with pytest.raises(sqlite3.DatabaseError):
        Database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT amount FROM paid_results").fetchone()[0] == "0.25"


@pytest.mark.parametrize("use_claim", [False, True])
def test_profile_citations_survive_storage(database, role_config, make_campaign, make_company, make_assessment, use_claim):
    campaign = database.save_campaign(make_campaign(config_snapshot=role_config))
    company, facts = make_company(segments=["fintech_software"])
    source = facts[0].model_copy(update={"claim": "La empresa ofrece un producto de gastos con recibos.",
                                        "excerpt": None if use_claim else "La empresa ofrece un producto de gastos con recibos."})
    facts = [source, *facts[1:]]
    database.save_company(company, evidence=facts)
    database.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id))
    match = ProfileMatch.model_validate({"profile_id": "expense_reimbursement", "citations": [{
        "evidence_id": source.id, "quote": "producto de gastos con recibos"}]})
    assessment = make_assessment(campaign.id, company.id, profile_matches=[match])
    assert database.save_assessment(assessment).profile_matches == [match]
    assert database.get_assessment(assessment.id).profile_matches == [match]
    bad = assessment.model_copy(update={"id": uuid4(), "profile_matches": [
        match.model_copy(update={"profile_id": "cpg_brands"})]})
    with pytest.raises(ValueError, match="perfil"):
        database.save_assessment(bad)
    later = source.model_copy(update={"id": uuid4(), "claim": "Una fuente sintética posterior contradice el caso.",
                                      "contradiction_ids": [source.id]})
    database.save_evidence(later)
    assert database.get_assessment(assessment.id) == assessment
    with pytest.raises(ValueError, match="contradicciones"):
        database.save_assessment(assessment.model_copy(update={"id": uuid4()}))


@pytest.mark.parametrize("failure", ["unknown_profile", "unknown_seniority", "too_many_titles"])
def test_taxonomy_rejects_unbounded_or_unknown_configuration(role_config, failure):
    raw = role_config.model_dump(mode="json")
    family = raw["role_taxonomy"]["families"][0]
    if failure == "unknown_profile":
        family["profile_ids"] = ["missing_synthetic_profile"]
    elif failure == "unknown_seniority":
        family["seniorities"] = ["supreme"]
    else:
        family["titles_en"] = [f"Synthetic Product Role {index}" for index in range(100)]
    with pytest.raises(ValidationError):
        VeryfiConfig.model_validate(raw)
