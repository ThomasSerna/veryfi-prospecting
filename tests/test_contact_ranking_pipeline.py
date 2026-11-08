"""Prioridad de enriquecimiento T19 con respuestas Apollo y personas exclusivamente sintéticas."""

from pathlib import Path
from uuid import uuid4

import pytest

from prospecting.contacts import load_contact_match
from prospecting.models import Evidence, utc_now
from prospecting.providers.apollo import ApolloSearchResponse, parse_search
from test_contact_pipeline import contact_case
from test_multi_contact_pipeline import enriched_ids, multi, progress


@pytest.fixture
def v2_config(role_config):
    weights = load_contact_match(Path(__file__).resolve().parents[1] / "config" / "contact_match_v2.json")
    return role_config.model_copy(update={"contact_match": weights})


def seed_blocked_person(case, index, reason):
    """Guarda Search con evidencia contradictoria antes de la etapa, sin simular un enriquecimiento."""
    [(person, facts)] = parse_search(case.company, ApolloSearchResponse.model_validate({
        "people": [case.people[index]], "total_entries": 1}), uuid4(), utc_now())
    source = Evidence(company_id=case.company.id, contact_id=person.id, retrieved_at=utc_now(), kind="observed",
                      source_type="primary", url=f"https://{case.company.domain}/equipo",
                      claim="Evidencia corporativa exclusivamente sintética.")
    if reason == "title_changed":
        source = source.model_copy(update={"contradiction_ids": person.provenance["title"]})
    elif reason == "contradicted_source":
        source = source.model_copy(update={"contradiction_ids": [facts[0].id]})
        person = person.model_copy(update={"employment_evidence_ids": [facts[0].id]})
    else:
        person = person.model_copy(update={"geographic_scope": "México", "provenance": person.provenance | {
            "geographic_scope": [source.id]}})
    case.db.save_contact(person, evidence=facts + [source])


@pytest.mark.parametrize("reverse", [False, True])
def test_v2_score_selects_enrichment_independently_of_search_order(contact_case, v2_config, reverse):
    case = multi(contact_case, v2_config, ["Head of Product", "Product Manager"])
    if reverse:
        case.people.reverse()
    report = case.find()
    assert enriched_ids(case) == ["persona-sintetica-1", "persona-sintetica-0"]
    assert report.status == "checked" and progress(case).relevant == 2 and progress(case).ready == 0
    count, usage = len(case.calls), case.db.list_usage()
    assert case.find().status == "already_checked" and len(case.calls) == count
    assert case.db.list_usage() == usage


def test_v2_score_precedes_diversity_but_t16_still_requires_the_missing_function(contact_case, v2_config):
    case = multi(contact_case, v2_config, ["Product Manager", "Product Manager", "Product Manager",
                                            "Engineering Manager", "Product Manager"])
    report = case.find()
    ids = enriched_ids(case)
    assert len(ids) == 4 and all(id != "persona-sintetica-3" for id in ids[:3])
    assert ids[-1] == "persona-sintetica-3" and "persona-sintetica-4" not in ids[3:]
    assert report.stop_reason == "people_target_reached" and progress(case).function_ids == ["engineering", "product"]
    assert case.db.get_run_item(case.campaign.id, case.company.id).consumed_limits.enrichments == 4


def test_v2_alternates_functions_only_when_scores_are_equal(contact_case, v2_config):
    case = multi(contact_case, v2_config, ["Head of Product", "Director of Product", "Engineering Manager",
                                            "Solutions Architect"])
    report = case.find()
    ids = enriched_ids(case)
    assert len(ids) == 3 and ids[0] in {"persona-sintetica-0", "persona-sintetica-1"}
    assert ids[1] in {"persona-sintetica-2", "persona-sintetica-3"}
    assert ids[2] in {"persona-sintetica-0", "persona-sintetica-1"}
    assert report.stop_reason == "people_target_reached"


@pytest.mark.parametrize("reason", ["title_changed", "contradicted_source", "scope_mismatch"])
def test_v2_never_enriches_a_person_with_supported_contradictions(contact_case, v2_config, reason):
    case = multi(contact_case, v2_config, ["Product Manager"])
    seed_blocked_person(case, 0, reason)
    report = case.find()
    assert report.status == "checked" and report.stop_reason == "contact_plan_exhausted"
    assert [operation for operation, _, _ in case.calls] == ["people_search", "people_search"]
    assert all(row.reserved_credits == row.credits == 0 for row in case.db.list_usage())


def test_a_blocked_function_does_not_trigger_extra_enrichment_for_diversity(contact_case, v2_config):
    case = multi(contact_case, v2_config, ["Product Manager", "Product Manager", "Product Manager", "Engineering Manager"])
    seed_blocked_person(case, 3, "title_changed")
    report = case.find()
    assert len(enriched_ids(case)) == 3 and "persona-sintetica-3" not in enriched_ids(case)
    assert report.stop_reason == "people_target_reached" and progress(case).function_ids == ["product"]


def test_v2_resume_after_uncertain_enrichment_keeps_prior_calls_and_consumption(contact_case, v2_config):
    case = multi(contact_case, v2_config, ["Product Manager", "Head of Product", "Engineering Manager"])
    reply = case.replies["people_enrichment"]
    case.replies["people_enrichment"] = lambda payload: TimeoutError("sin respuesta sintética") if (
        payload["id"] == "persona-sintetica-2") else reply(payload)
    report = case.find()
    assert report.status == "pending" and report.stop_reason == "apollo_timeout"
    calls, usage = len(case.calls), case.db.list_usage()
    case.replies["people_enrichment"] = reply
    again = case.find()
    assert again.status == "pending" and again.stop_reason == "request_uncertain"
    assert len(case.calls) == calls and case.db.list_usage() == usage


def test_invalid_stored_v2_fails_before_any_provider_call(contact_case, v2_config):
    case = multi(contact_case, v2_config, ["Product Manager"])
    case.db._connection.execute("UPDATE campaigns SET config_snapshot=json_set(config_snapshot, "
                                "'$.contact_match.components.role.weight', 39) WHERE id=?", (str(case.campaign.id),))
    with pytest.raises(ValueError):
        case.find()
    assert case.calls == [] and case.db.list_usage() == []
