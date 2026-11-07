"""Vigencia del empleo neutral al proveedor (T18), con personas, páginas y respuestas exclusivamente sintéticas."""

from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from prospecting.contact_extraction import parse_contacts_output
from prospecting.contacts import (
    ContactError, apply_target_roles, contact_context, derive_readiness, employment_status, mentions, validate_contact,
)
from prospecting.models import Evidence
from prospecting.providers.apollo import ApolloEnrichmentResponse, ApolloSearchResponse, parse_enrichment, parse_search


NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)
PERSON_ID = "persona-sintetica"
NAME, TITLE, EMAIL = "Persona Sintética", "CTO", "persona-sintetica@example.com"
DIRECTORY = f"{NAME}, {TITLE} de Empresa sintética, correo {EMAIL}."


@pytest.fixture
def case(make_campaign, make_company, make_assessment):
    campaign = make_campaign()
    assert campaign.config_snapshot.people_provider == "apollo"
    company, _ = make_company(domain="example.com", entity_name="Empresa sintética", segments=["fintech_software"],
                              identity_status="confirmed")
    assessment = make_assessment(campaign.id, company.id, priority="high", target_roles=[TITLE])
    return SimpleNamespace(campaign=campaign, company=company, assessment=assessment, limits=campaign.limits)


def search(case, **person):
    response = ApolloSearchResponse.model_validate({"total_entries": 1, "people": [{
        "id": PERSON_ID, "first_name": "Persona", "last_name_obfuscated": "S***", "title": TITLE,
        "last_refreshed_at": NOW.isoformat(), "has_email": True, "organization": {"name": "Empresa sintética"},
    } | person]})
    [(contact, facts)] = parse_search(case.company, response, uuid4(), NOW)
    return contact, facts


def enrich(case, contact, facts, **person):
    response = ApolloEnrichmentResponse.model_validate({"person": {
        "id": PERSON_ID, "first_name": "Persona", "last_name": "Sintética", "name": NAME, "title": TITLE,
        "match_confidence": "high", "email": EMAIL, "email_status": "verified", "organization_id": "empresa-sintetica",
        "organization": {"id": "empresa-sintetica", "name": "Empresa sintética", "primary_domain": "example.com"},
        "employment_history": [{"current": True, "organization_id": "empresa-sintetica", "title": TITLE}],
    } | person})
    enriched, new = parse_enrichment(contact, case.company, response, uuid4(), NOW)
    return apply_target_roles(enriched, [TITLE]), facts + new


def apollo_person(case, **person):
    return enrich(case, *search(case), **person)


def page(case, excerpt, *, path="/equipo", contact_id=None, source_type="primary", host="example.com", **fields):
    return Evidence(company_id=case.company.id, contact_id=contact_id, url=f"https://{host}{path}",
                    claim="Texto publicado en la página, extraído por Tavily.", provider="tavily",
                    external_reference=f"tavily-sintetico#{uuid4()}", excerpt=excerpt,
                    retrieved_at=fields.pop("retrieved_at", NOW), kind="observed", source_type=source_type, **fields)


def corroborate(case, contact, facts, source, *, title=TITLE, employment="Empresa sintética", contacts=None):
    """Haiku cita la página corporativa; Python valida las citas y fusiona con la persona de Apollo."""
    cited = [("name", NAME), ("title", title), ("employment", employment), ("email", EMAIL)]
    output = {"candidates": [{"contact_id": str(contact.id), "name": NAME, "facts": [
        {"field": field, "value": value, "evidence_id": str(source.id), "quote": source.excerpt}
        for field, value in cited if mentions(source.excerpt, value)]}]}
    [(merged, derived)] = parse_contacts_output(json.dumps(output), "end_turn", case.company, case.assessment,
                                                case.campaign, [source], NOW, uuid4(),
                                                contacts=contacts or [contact])
    return merged, facts + [source] + derived


def with_employment(contact, *facts):
    """Simula hechos del puesto ya guardados para aislar la regla de vigencia."""
    return contact.model_copy(update={"current_employment": True, "employment_evidence_ids": list(dict.fromkeys(
        contact.employment_evidence_ids + [fact.id for fact in facts]))})


def status(case, contact, facts):
    """Calcula el estado y comprueba las invariantes: no muta la persona y solo la evidencia habilita."""
    before = contact.model_dump()
    result = employment_status(contact, case.company, facts, case.limits, NOW)
    assert contact.model_dump() == before
    if validate_contact(contact, case.company, case.assessment, facts, case.limits, NOW):
        assert result.state == "corporate_evidence"
    return result


def ready(case, contact, facts):
    return derive_readiness(case.assessment, [contact], facts, case.limits, NOW, case.company)


def test_apollo_email_without_corporate_evidence_is_only_a_provider_claim(case):
    contact, facts = apollo_person(case)
    assert contact.current_employment is None
    assert contact.channels[0].normalized_status == "unknown" and contact.channels[0].verified_at is None
    result = status(case, contact, facts)
    assert (result.state, result.origin, result.reason, result.review_required) == (
        "provider_claim", "apollo", "provider_claim_only", False)
    enrichment = next(item for item in facts if item.external_reference.endswith("#enrichment"))
    assert result.evidence_ids == [enrichment.id]
    assert not validate_contact(contact, case.company, case.assessment, facts, case.limits, NOW)
    assert ready(case, contact, facts) == "qualified_no_contact"


@pytest.mark.parametrize("refreshed", [NOW, NOW - timedelta(days=400)])
def test_profile_refresh_date_never_confirms_employment(case, refreshed):
    contact, facts = search(case, last_refreshed_at=refreshed.isoformat())
    assert (status(case, contact, facts).state, status(case, contact, facts).reason) == ("unknown", "incomplete_name")
    enriched, facts = enrich(case, contact, facts)
    assert status(case, enriched, facts).reason == "provider_claim_only"


def test_current_corporate_directory_justifies_employment_without_sending_messages(case):
    contact, facts = apollo_person(case)
    merged, facts = corroborate(case, contact, facts, page(case, DIRECTORY))
    result = status(case, merged, facts)
    employment = next(item for item in facts if item.claim.startswith("Hecho nominal publicado: employment="))
    assert (result.state, result.origin, result.reason, result.evidence_ids) == (
        "corporate_evidence", "apollo", None, [employment.id])
    assert validate_contact(merged, case.company, case.assessment, facts, case.limits, NOW)
    assert ready(case, merged, facts) == "ready_preferred"


def test_title_change_on_corporate_page_contradicts_employment(case):
    contact, facts = apollo_person(case)
    source = page(case, f"{NAME}, CFO de Empresa sintética.")
    merged, facts = corroborate(case, contact, facts, source, title="CFO")
    result = status(case, merged, facts)
    assert (result.state, result.reason, result.review_required) == ("contradicted", "title_changed", True)
    assert result.evidence_ids and merged.identity_status == "contradicted"
    assert ready(case, merged, facts) == "qualified_no_contact"


def test_reenrichment_with_another_title_needs_corporate_confirmation(case):
    contact, facts = apollo_person(case)
    merged, facts = corroborate(case, contact, facts, page(case, DIRECTORY))
    assert status(case, merged, facts).state == "corporate_evidence"
    reenriched, facts = enrich(case, merged, facts, title="VP Engineering", employment_history=[
        {"current": True, "organization_id": "empresa-sintetica", "title": "VP Engineering"}])
    assert reenriched.title == "VP Engineering" and reenriched.current_employment is True
    result = status(case, reenriched, facts)
    assert (result.state, result.reason, result.review_required) == ("provider_claim", "title_unconfirmed", True)
    assert not validate_contact(reenriched, case.company, case.assessment, facts, case.limits, NOW)


@pytest.mark.parametrize("departure", [
    f"{NAME} dejó la empresa en septiembre.", f"{NAME} ya no trabaja en Empresa sintética.",
    f"La ex {TITLE} {NAME} se unió a otra compañía.",
])
def test_departure_overrides_provider_claim_and_corporate_evidence(case, departure):
    contact, facts = apollo_person(case)
    merged, facts = corroborate(case, contact, facts, page(case, DIRECTORY))
    news = page(case, departure, path="/noticias", contact_id=merged.id, source_type="secondary")
    for person, evidence in ((contact, facts), (merged, facts)):
        result = status(case, person, evidence + [news])
        assert (result.state, result.reason) == ("contradicted", "employment_ended")
        assert news.id in result.evidence_ids
    negative = status(case, merged.model_copy(update={"current_employment": False}), facts)
    assert (negative.state, negative.reason) == ("contradicted", "employment_ended")


def test_corporate_page_naming_another_entity_ends_employment(case):
    contact, facts = apollo_person(case)
    source = page(case, f"{NAME}, {TITLE} de Otra Empresa Sintética.")
    merged, facts = corroborate(case, contact, facts, source, employment="Otra Empresa Sintética")
    assert merged.current_employment is False
    assert (status(case, merged, facts).state, status(case, merged, facts).reason) == ("contradicted", "employment_ended")


def test_ambiguous_sources_keep_the_apollo_claim_pending_review(case):
    contact, facts = apollo_person(case)
    anonymous = page(case, "Equipo directivo de Empresa sintética.")
    result = status(case, with_employment(contact, anonymous), facts + [anonymous])
    assert (result.state, result.reason, result.review_required) == ("provider_claim", "ambiguous_source", True)
    assert anonymous.id in result.evidence_ids
    undated, undated_facts = corroborate(case, contact, facts, page(case, DIRECTORY, path="/blog/novedades"))
    assert undated.current_employment is None
    result = status(case, undated, undated_facts)
    assert (result.state, result.reason, result.review_required) == ("provider_claim", "undated_source", True)


def test_homonyms_are_not_merged_and_the_person_stays_a_claim(case):
    contact, facts = apollo_person(case)
    homonym = contact.model_copy(update={"id": uuid4()})
    with pytest.raises(ContactError) as error:
        corroborate(case, contact, facts, page(case, DIRECTORY), contacts=[contact, homonym])
    assert error.value.code == "ambiguous_identity"
    assert status(case, contact, facts).state == "provider_claim"


def test_obfuscated_surname_never_matches_a_published_full_name(case):
    contact, facts = search(case)
    fact = page(case, f"Persona S. Uno, {TITLE} de Empresa sintética.", contact_id=contact.id)
    assert mentions(fact.excerpt, contact.name)  # El apellido ofuscado coincidiría con otra persona.
    result = status(case, with_employment(contact, fact), facts + [fact])
    assert (result.state, result.reason) == ("unknown", "incomplete_name")


@pytest.mark.parametrize(("changes", "reason"), [
    ({"retrieved_at": NOW - timedelta(days=31)}, "stale_source"),
    ({"path": "/noticias", "source_type": "secondary", "published_at": NOW - timedelta(days=366)}, "stale_source"),
    ({"path": "/noticias", "source_type": "secondary", "published_at": NOW + timedelta(days=1)}, "future_date"),
    ({"updated_at": NOW + timedelta(hours=1)}, "future_date"),
])
def test_stale_or_future_sources_block_ready_with_a_reason(case, changes, reason):
    contact, facts = apollo_person(case)
    fact = page(case, DIRECTORY, contact_id=contact.id, **changes)
    person, evidence = with_employment(contact, fact), facts + [fact]
    result = status(case, person, evidence)
    assert (result.state, result.origin, result.reason) == ("provider_claim", "apollo", reason)
    assert fact.id in result.evidence_ids
    assert ready(case, person, evidence) == "qualified_no_contact"


def test_old_apollo_claim_without_evidence_becomes_unknown(case):
    contact, facts = apollo_person(case)
    later = NOW + timedelta(days=case.limits.cache.contact_days + 1)
    result = employment_status(contact, case.company, facts, case.limits, later)
    assert (result.state, result.origin, result.reason) == ("unknown", "apollo", "stale_source")


@pytest.mark.parametrize("direction", ["own", "reverse"])
def test_contradicted_employment_source_blocks_in_both_directions(case, direction):
    contact, facts = apollo_person(case)
    merged, facts = corroborate(case, contact, facts, page(case, DIRECTORY))
    employment = next(item for item in facts if item.claim.startswith("Hecho nominal publicado: employment="))
    if direction == "own":
        facts = [item.model_copy(update={"contradiction_ids": [uuid4()]}) if item.id == employment.id else item
                 for item in facts]
    else:
        facts = facts + [page(case, "Directorio sintético corregido.", path="/equipo-2026",
                              contradiction_ids=[employment.id])]
    result = status(case, merged, facts)
    assert (result.state, result.reason, result.evidence_ids) == ("contradicted", "contradicted_source", [employment.id])
    assert ready(case, merged, facts) == "qualified_no_contact"


def test_hunter_history_is_invisible_to_an_apollo_campaign(case, make_hunter_contact):
    contact, facts = make_hunter_contact(case.company, NOW)
    selected, kept = contact_context(case.campaign, [contact], facts)
    assert selected == [] and not any(item.provider == "hunter" for item in kept)
    assert status(case, contact, kept).state == "unknown"
