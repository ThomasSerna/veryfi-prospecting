"""La ficha y el CSV interpretan contactos compartidos según su campaña sintética."""

from types import SimpleNamespace
from uuid import uuid4

from demo import DB_NAME, build_demo
from core.presentation import export_csv
from prospecting.db import Database
from prospecting.models import RunItem, utc_now
from prospecting.pipeline import read_campaign
from test_contact_match_view import csv_rows, page


def test_campaign_taxonomy_is_isolated_in_view_html_and_csv(tmp_path):
    campaign = build_demo(tmp_path, utc_now())
    path = tmp_path / DB_NAME
    before = read_campaign(path, campaign.id)
    original = next(item for item in before.companies if item.company.domain == "pagos-sintetica.example")
    person = original.contacts[0]
    assert person.eligible and person.contact.relevant_function is True
    assert person.function_id == "product" and original.people.function_ids == ["product"]
    original_row = next(row for row in csv_rows(export_csv(before, include_all=True))
                        if row["contact_id"] == str(person.contact.id))
    assert original_row["function_id"] == "product" and original_row["people_functions"] == '["product"]'
    taxonomy = campaign.config_snapshot.role_taxonomy
    restricted = taxonomy.model_copy(update={"families": [family for family in taxonomy.families
                                                         if family.function_id != "product"]})
    other = campaign.model_copy(update={"id": uuid4(), "config_snapshot": campaign.config_snapshot.model_copy(
        update={"role_taxonomy": restricted})})
    assessment = original.assessment.model_copy(update={"id": uuid4(), "campaign_id": other.id, "target_roles": []})
    with Database(path) as database:
        stored = database.get_contact(person.contact.id)
        database.save_campaign(other)
        run = RunItem(campaign_id=other.id, company_id=original.company.id, stage="completed")
        database.save_run_item(run)
        database.save_assessment(assessment)
        database.save_run_item(run.model_copy(update={"last_assessment_id": assessment.id}))
    views = [read_campaign(path, identifier) for identifier in (other.id, campaign.id)]
    rejected = views[0].companies[0].contacts[0]
    assert rejected.eligible is False and rejected.contact.relevant_function is None
    assert rejected.match.components[0].pending is True
    restored = next(item for item in views[1].companies if item.company.id == original.company.id).contacts[0]
    assert restored.eligible and restored.match == person.match
    assert csv_rows(export_csv(views[0])) == []
    [row] = csv_rows(export_csv(views[0], include_all=True))
    assert row["contact_eligible"] == row["contact_ready"] == "False"
    assert row["contact_match_version"] == "contact_match_v2"
    case = SimpleNamespace(path=path, campaign=other, tmp_path=tmp_path)
    html = page(case, "webapp:company", company_id=original.company.id)
    assert person.contact.name in html and "Cargo pendiente" in html
    assert "<dt>Función pertinente</dt><dd>Pendiente</dd>" in html
    original_case = SimpleNamespace(path=path, campaign=campaign, tmp_path=tmp_path)
    original_html = page(original_case, "webapp:company", company_id=original.company.id)
    assert "<dt>Función pertinente</dt><dd>Sí</dd>" in original_html
    assert "<dt>Función pertinente</dt><dd>Pendiente</dd>" not in original_html
    with Database(path) as database:
        assert database.get_contact(person.contact.id) == stored
