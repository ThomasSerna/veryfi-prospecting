"""Etapas de persona y objetivo de personas pertinentes (T16), con personas y páginas exclusivamente sintéticas."""

import pytest

from prospecting.contacts import PERSON_STAGES, apply_target_roles, people_progress, people_target, person_stage
from prospecting.models import Campaign
from test_employment_status import DIRECTORY, EMAIL, NAME, NOW, TITLE, apollo_person, case, corroborate, enrich, page, search


def stage(case, contact, facts):
    return person_stage(contact, case.company, case.assessment, facts, case.limits, NOW, campaign=case.campaign)


def test_search_result_with_obfuscated_surname_stays_a_candidate(case):
    contact, facts = search(case)
    assert "*" in contact.name and stage(case, contact, facts) == "candidate"


def test_enriched_person_without_usable_email_is_relevant_but_not_ready(case):
    """Un correo de Apollo sin fecha de verificación no es canal utilizable ni prueba el empleo."""
    contact, facts = apollo_person(case)
    assert stage(case, contact, facts) == "relevant"


def test_corporate_directory_with_published_email_makes_the_person_ready(case):
    contact, facts = apollo_person(case)
    merged, facts = corroborate(case, contact, facts, page(case, DIRECTORY))
    assert stage(case, merged, facts) == "ready"


def test_usable_channel_without_employment_evidence_is_not_ready(case):
    """El correo publicado nominalmente es utilizable, pero sin el cargo vigente la persona no está lista."""
    contact, facts = apollo_person(case)
    merged, facts = corroborate(case, contact, facts, page(case, f"{NAME}, correo {EMAIL}."))
    assert stage(case, merged, facts) == "channel_usable"


def test_title_change_and_departure_are_never_pertinent(case):
    contact, facts = apollo_person(case)
    changed, changed_facts = corroborate(case, contact, facts, page(case, f"{NAME}, CFO de Empresa sintética."), title="CFO")
    assert stage(case, changed, changed_facts) not in ("relevant", "channel_usable", "ready")
    news = page(case, f"{NAME} dejó la empresa en septiembre.", path="/noticias", contact_id=contact.id,
                source_type="secondary")
    assert stage(case, contact, facts + [news]) == "identity_verified"


def test_confirmed_identity_with_a_function_outside_the_profile_is_not_relevant(case):
    contact, facts = enrich(case, *search(case, title="Recepcionista"), title="Recepcionista",
                            employment_history=[{"current": True, "organization_id": "empresa-sintetica",
                                                 "title": "Recepcionista"}])
    contact = apply_target_roles(contact, [TITLE])
    assert contact.relevant_function is False and stage(case, contact, facts) == "identity_verified"


def test_progress_counts_cumulative_stages_without_a_policy(case):
    """Sin `people_policy` no hay objetivo: `None`, nunca cero."""
    candidate, candidate_facts = search(case, id="otra-persona-sintetica")
    relevant, relevant_facts = apollo_person(case)
    progress = people_progress([candidate, relevant], case.company, case.assessment,
                               candidate_facts + relevant_facts, NOW, campaign=case.campaign)
    assert (progress.candidates, progress.identity_verified, progress.relevant, progress.channel_usable,
            progress.ready) == (2, 1, 1, 0, 0)
    assert (progress.target, progress.policy_version, progress.function_ids) == (None, None, [])
    assert PERSON_STAGES == ("candidate", "identity_verified", "relevant", "channel_usable", "ready")
    from core.presentation import people_counts, people_summary

    assert people_summary(progress) == "2 candidatas · 1 pertinente · 0 listas"
    assert people_counts(progress.model_copy(update={"ready": 1})) == "1 pertinente · 1 lista"
    assert people_summary(None) == people_counts(None) == ""


@pytest.mark.parametrize("priority, people, expected", [
    ("high", None, 3), ("medium", None, 2), ("high", 2, 2), ("low", None, None),
])
def test_target_follows_policy_and_never_exceeds_the_people_cap(role_config, make_assessment, priority, people, expected):
    campaign = Campaign(countries=["CO"], segments=["fintech_software"], config_snapshot=role_config)
    if people is not None:
        limits = campaign.limits.model_dump()
        limits["effort"]["high"] |= {"people": people, "enrichments_per_provider": people}
        campaign = Campaign.model_validate(campaign.model_dump() | {"limits": limits})
    assessment = make_assessment(campaign.id, campaign.id, priority=priority)
    assert people_target(campaign, assessment) == expected
