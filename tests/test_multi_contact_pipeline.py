"""Varias personas pertinentes por cuenta con Apollo (T16); personas, correos y respuestas exclusivamente sintéticos."""

import pytest

from prospecting.budget import SpendingAuthorization
from prospecting.contacts import contact_context, people_progress
from prospecting.models import BusinessStatus, Campaign, utc_now
from prospecting.pipeline import contacts as stage_module
from prospecting.providers.apollo import person_id
from test_contact_pipeline import contact_case, enable_role_taxonomy

ORDINALS = ("Uno", "Dos", "Tres", "Cuatro", "Cinco", "Seis", "Siete")
PRODUCT = ("Head of Product", "Product Manager", "Director of Product", "Senior Product Manager", "Group Product Manager")
ENGINEERING = ("Engineering Manager", "Solutions Architect", "Director of Engineering")


def multi(case, role_config, titles, *, priority="high", enriched=None):
    """Campaña con taxonomía y candidatos de Search con apellido ofuscado; Enrichment responde por id."""
    enable_role_taxonomy(case, role_config)
    # La campaña nueva toma los topes de su instantánea (T16: media 3/3, alta 5/5).
    case.campaign = Campaign.model_validate(case.campaign.model_dump() | {"limits": None})
    case.db.save_campaign(case.campaign)
    case.db._connection.execute("UPDATE assessments SET priority=?", (priority,))
    case.assessment = case.db.get_assessment(case.assessment.id)
    details = {}
    for index, title in enumerate(titles):
        identifier = f"persona-sintetica-{index}"
        case.people.append({"id": identifier, "first_name": "Persona Sintética", "last_name_obfuscated": "S***",
                            "title": title, "last_refreshed_at": utc_now().isoformat(),
                            "organization": {"name": case.company.name}})
        details[identifier] = {"last_name": ORDINALS[index], "title": title,
                               "email": f"persona.{index}@{case.company.domain}"} | (enriched or {}).get(index, {})

    def reply(payload):
        item = details[payload["id"]]
        name = f"Persona Sintética {item['last_name']}"
        return {"person": {"id": payload["id"], "first_name": "Persona Sintética", "last_name": item["last_name"],
                           "name": name, "title": item["title"], "match_confidence": item.get("confidence", "high"),
                           "email": item["email"], "email_status": "verified", "organization_id": "org-sintetica",
                           "organization": {"id": "org-sintetica", "name": case.company.name,
                                            "primary_domain": case.company.domain},
                           "employment_history": [{"current": True, "organization_id": "org-sintetica",
                                                   "organization_name": case.company.name, "title": item["title"]}]}}

    case.replies["people_enrichment"] = reply
    return case


def enriched_ids(case):
    return [payload["id"] for operation, payload, _ in case.calls if operation == "people_enrichment"]


def progress(case):
    people, facts = contact_context(case.campaign, case.db.list_contacts(case.company.id),
                                    case.db.list_evidence(case.company.id))
    return people_progress(people, case.company, case.assessment, facts, utc_now(), campaign=case.campaign)


def test_zero_candidates_search_once_per_query_without_enrichment(contact_case, role_config):
    case = multi(contact_case, role_config, [])
    report = case.find()
    assert [item[0] for item in case.calls] == ["people_search", "people_search"]
    assert (report.stop_reason, report.business_status) == ("contact_plan_exhausted", "qualified_no_contact")
    assert progress(case).candidates == 0


def test_one_candidate_is_enriched_and_reported_below_target(contact_case, role_config):
    case = multi(contact_case, role_config, ["Head of Product"])
    report = case.find()
    assert enriched_ids(case) == ["persona-sintetica-0"] and report.stop_reason == "contact_plan_exhausted"
    result = progress(case)
    assert (result.candidates, result.relevant, result.ready, result.target) == (1, 1, 0, 3)


def test_three_people_of_two_functions_reach_the_target(contact_case, role_config):
    case = multi(contact_case, role_config, ["Head of Product", "Engineering Manager", "Product Manager", "Solutions Architect"])
    report = case.find()
    assert len(enriched_ids(case)) == 3 and report.stop_reason == "people_target_reached"
    result = progress(case)
    assert (result.candidates, result.relevant, result.function_ids) == (4, 3, ["engineering", "product"])
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    assert run.consumed_limits.enrichments == 3 and run.attempts["contacts:apollo_enrichments"] == 3


def test_more_candidates_than_the_target_are_saved_but_not_enriched(contact_case, role_config):
    """No se enriquece a toda la organización: el resto queda candidato, con su procedencia de Search."""
    case = multi(contact_case, role_config, PRODUCT + ENGINEERING[:2])
    case.find()
    assert len(enriched_ids(case)) == 3
    people = case.db.list_contacts(case.company.id)
    assert len(people) == 7
    evidence = case.db.list_evidence(case.company.id)
    assert all(person_id(item, evidence) for item in people)
    assert sum("*" in item.name for item in people) == 4 and progress(case).candidates == 7


def test_non_pertinent_enrichments_continue_until_the_enrichment_cap(contact_case, role_config):
    """Cambio de cargo en Apollo: la persona deja de ser pertinente y la etapa prueba con la siguiente."""
    case = multi(contact_case, role_config, PRODUCT + ENGINEERING[:2],
                 enriched={index: {"title": "Recepcionista"} for index in range(7)})
    report = case.find()
    assert len(enriched_ids(case)) == 5 and report.stop_reason == "enrichment_limit"
    result = progress(case)
    assert (result.candidates, result.identity_verified, result.relevant) == (7, 5, 0)
    assert report.business_status == "qualified_no_contact"


def test_duplicate_search_results_are_one_person_and_one_enrichment(contact_case, role_config):
    case = multi(contact_case, role_config, ["Head of Product"])
    case.people.append(dict(case.people[0]))
    case.find()
    assert enriched_ids(case) == ["persona-sintetica-0"] and len(case.db.list_contacts(case.company.id)) == 1


def test_missing_email_still_counts_as_pertinent_but_never_as_ready(contact_case, role_config):
    case = multi(contact_case, role_config, ["Head of Product", "Engineering Manager", "Product Manager"],
                 enriched={index: {"email": None} for index in range(3)})
    report = case.find()
    assert report.stop_reason == "people_target_reached"
    result = progress(case)
    assert (result.relevant, result.channel_usable, result.ready) == (3, 0, 0)
    assert all(item.channels == [] for item in case.db.list_contacts(case.company.id))


def test_rejected_identity_does_not_stop_the_others_or_repeat(contact_case, role_config):
    case = multi(contact_case, role_config, ["Head of Product", "Engineering Manager", "Product Manager", "Solutions Architect"],
                 enriched={0: {"confidence": "low"}})
    report = case.find()
    assert report.status == "checked" and report.stop_reason == "people_target_reached"
    assert len(enriched_ids(case)) == 4 and any("Apollo no confirmó" in item for item in report.warnings)
    rejected = [person for person in case.db.list_contacts(case.company.id) if person.name_complete is False
                and person_id(person, case.db.list_evidence(case.company.id)) == "persona-sintetica-0"]
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    assert rejected and f"contacts:apollo_rejected:identity_unconfirmed:{rejected[0].id}" in run.attempts
    calls = len(case.calls)
    assert case.find().status == "already_checked" and len(case.calls) == calls


def test_legacy_snapshot_keeps_the_rejection_pending(contact_case, role_config):
    """Sin `people_policy` se conserva la conducta anterior a T16: el rechazo deja la cuenta pendiente."""
    case = multi(contact_case, role_config.model_copy(update={"people_policy": None}), ["Head of Product"],
                 enriched={0: {"confidence": "low"}})
    report = case.find()
    assert (report.status, report.stop_reason) == ("pending", "identity_unconfirmed")


def test_a_usable_channel_does_not_end_the_account_before_the_target(contact_case, role_config, monkeypatch):
    """Simula un primer canal preferido: con política se sigue hasta el objetivo; sin ella, se para."""
    monkeypatch.setattr(stage_module, "derive_readiness", lambda *args, **kwargs: BusinessStatus.READY_PREFERRED)
    titles = ["Head of Product", "Engineering Manager", "Product Manager", "Solutions Architect"]
    case = multi(contact_case, role_config, titles)
    assert case.find().stop_reason == "people_target_reached" and len(enriched_ids(case)) == 3


def test_legacy_snapshot_still_stops_at_the_first_preferred_channel(contact_case, role_config, monkeypatch):
    monkeypatch.setattr(stage_module, "derive_readiness", lambda *args, **kwargs: BusinessStatus.READY_PREFERRED)
    case = multi(contact_case, role_config.model_copy(update={"people_policy": None}), ["Head of Product", "Product Manager"])
    report = case.find()
    assert report.stop_reason == "preferred_channel_found" and enriched_ids(case) == []


def test_another_function_is_tried_before_stopping_with_a_single_function(contact_case, role_config, monkeypatch):
    """Si el orden dejara la otra función al final, el objetivo con una sola función no detiene la etapa."""
    ranked = stage_module._ContactStage.ranked_people
    monkeypatch.setattr(stage_module._ContactStage, "ranked_people", lambda self: sorted(
        ranked(self), key=lambda item: "Engineering" in (item.title or "")))
    case = multi(contact_case, role_config, ["Head of Product", "Product Manager", "Director of Product",
                                             "Engineering Manager", "Senior Product Manager"])
    report = case.find()
    enriched = enriched_ids(case)
    assert len(enriched) == 4 and enriched[-1] == "persona-sintetica-3"
    assert report.stop_reason == "people_target_reached" and progress(case).function_ids == ["engineering", "product"]


def test_medium_priority_targets_two_people(contact_case, role_config):
    case = multi(contact_case, role_config, ["Head of Product", "Engineering Manager", "Product Manager", "Solutions Architect"],
                 priority="medium")
    report = case.find()
    assert len(enriched_ids(case)) == 2 and report.stop_reason == "people_target_reached"
    assert progress(case).target == 2


def test_enrichment_authorization_cap_stops_without_another_call(contact_case, role_config):
    case = multi(contact_case, role_config, ["Head of Product", "Engineering Manager", "Product Manager", "Solutions Architect"])
    pool = next(grant for grant in case.grants if grant.operation == "people_enrichment")
    limited = case.budget.authorize(SpendingAuthorization(
        provider="apollo", account_ref=pool.account_ref, operation="people_enrichment", max_cost_usd="0",
        max_credits="2", responsible="Responsable sintético", source_reference="Permiso sintético acotado",
        authorized_at=utc_now()))
    grants = [grant for grant in case.grants if grant.operation != "people_enrichment"] + [limited]
    report = case.find(authorizations=grants)
    assert len(enriched_ids(case)) == 2 and report.status == "pending"
    assert report.stop_reason == "authorization_exceeded"
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    assert run.consumed_limits.enrichments == 2


def test_resume_after_an_uncertain_enrichment_does_not_repeat_calls(contact_case, role_config):
    case = multi(contact_case, role_config, ["Head of Product", "Engineering Manager", "Product Manager"])
    reply = case.replies["people_enrichment"]
    case.replies["people_enrichment"] = lambda payload: TimeoutError("sin respuesta sintética") if (
        payload["id"] == "persona-sintetica-1") else reply(payload)
    report = case.find()
    assert report.status == "pending" and report.stop_reason == "timeout"
    calls = len(case.calls)
    case.replies["people_enrichment"] = reply
    again = case.find()
    assert again.status == "pending" and len(case.calls) == calls
