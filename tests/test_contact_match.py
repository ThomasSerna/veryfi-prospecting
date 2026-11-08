"""Porcentaje de match de contactos: determinístico, explicable y sin decidir listo. Datos sintéticos."""

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import random
from uuid import uuid4

from pydantic import ValidationError
import pytest

from prospecting.contacts import (
    ContactMatchConfig, contact_match, derive_readiness, employment_status, load_contact_match, match_sort_key,
    rank_contact_matches, target_roles, validate_contact,
)
from prospecting.models import Channel, Contact, Evidence


NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)
NAME = "Persona Sintética Uno"
EMAIL = "persona-sintetica@example.com"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "contact_match.json"
# Cambiar un peso o nivel exige una versión nueva y su huella aquí (docs/contacts.md).
CONFIG_FINGERPRINTS = {
    "contact_match_v1": "dd990a111908273b12a82a916a8174962377367aa41c9dc7aa6f0f31407b6d7e",
    "contact_match_v2": "c68ed6877f566d289330f0397e4cd05044200b2bce547f59181e40a1c94463ee",
}


@pytest.fixture
def weights():
    return load_contact_match(CONFIG_PATH)


@pytest.fixture
def v2_weights():
    return load_contact_match(CONFIG_PATH.with_name("contact_match_v2.json"))


@pytest.fixture
def ready(make_campaign, make_company, make_assessment):
    """Persona pertinente y vigente con correo verificado: el caso más útil."""
    campaign = make_campaign()
    company, _ = make_company(domain="example.com", entity_name="Empresa sintética", segments=["fintech_software"],
                               operating_countries=["CO"], identity_status="confirmed")
    assessment = make_assessment(campaign.id, company.id, priority="high", target_roles=["CTO"])
    contact_id = uuid4()
    source = Evidence(company_id=company.id, contact_id=contact_id, claim="Directorio corporativo sintético actual.",
                      excerpt=f"{NAME}, CTO de Empresa sintética, correo {EMAIL}.",
                      url="https://example.com/team", retrieved_at=NOW, kind="observed", source_type="primary")
    verified = Evidence(company_id=company.id, contact_id=contact_id, claim=f"Hunter informa email {EMAIL}; estado=valid.",
                        provider="hunter", external_reference="synthetic-verification", retrieved_at=NOW,
                        kind="observed", source_type="provider")
    contact = Contact(id=contact_id, company_id=company.id, name=NAME, title="CTO", name_complete=True,
                      current_employment=True, relevant_function=True, identity_status="confirmed",
                      provenance={field: [source.id] for field in ("name", "title", "relevant_function")},
                      employment_evidence_ids=[source.id], channels=[Channel(
                          contact_id=contact_id, type="email", value=EMAIL, evidence_ids=[verified.id],
                          provider_status="valid", normalized_status="verified", retrieved_at=NOW,
                          verified_at=NOW, professional=True, direct=True)])
    return company, campaign, assessment, contact, [source, verified]


def match_of(ready, weights, contact=None, evidence=None, company=None):
    base_company, campaign, assessment, base_contact, base_evidence = ready
    company = company or base_company
    return contact_match(contact or base_contact, company, assessment, evidence or base_evidence, campaign.limits, NOW,
                         target_roles(company, assessment, campaign), weights)


def levels(match):
    return {item.name: (item.level, item.points, item.pending) for item in match.components}


def retitled(ready, title):
    """La misma persona con otro cargo citado en su fuente."""
    _, _, _, contact, evidence = ready
    source = evidence[0].model_copy(update={"excerpt": f"{NAME}, {title} de Empresa sintética, correo {EMAIL}."})
    return contact.model_copy(update={"title": title}), [source, evidence[1]]


def test_versioned_weights_prioritize_role_and_sum_one_hundred(weights):
    assert weights.version == "contact_match_v1"
    assert {name: item.weight for name, item in weights.components.items()} == {
        "role": 50, "channel": 25, "identity": 15, "employment": 10}
    digest = hashlib.sha256(json.dumps(weights.model_dump(mode="json")["components"], sort_keys=True).encode()).hexdigest()
    assert CONFIG_FINGERPRINTS.get(weights.version) == digest, "Cambiaste pesos o niveles: usa una versión nueva."


def test_relevant_current_person_with_usable_email_scores_one_hundred(ready, weights):
    match = match_of(ready, weights)
    assert match.score == 100 and match.blocked_reason is None and match.version == "contact_match_v1"
    assert levels(match) == {"role": ("selected_role", 50, False), "channel": ("preferred_usable", 25, False),
                             "identity": ("confirmed_complete", 15, False), "employment": ("evidence", 10, False)}


@pytest.mark.parametrize("title, level, points", [
    ("Head of Product", "profile_role", 35),
    ("Sales Manager", "outside_profile", 0),
])
def test_role_rewards_assessment_choice_over_other_profile_roles(ready, weights, title, level, points):
    contact, evidence = retitled(ready, title)
    assert levels(match_of(ready, weights, contact, evidence))["role"] == (level, points, False)


def test_unknown_data_adds_nothing_but_stays_pending_not_failed(ready, weights):
    _, _, _, contact, evidence = ready
    unknown = Contact.model_validate(contact.model_dump() | {
        "title": None, "relevant_function": None, "name_complete": False, "identity_status": "pending",
        "current_employment": None, "channels": [],
        "provenance": {"name": contact.provenance["name"]}})
    match = match_of(ready, weights, unknown, evidence)
    assert match.score == 0 and match.blocked_reason is None
    assert levels(match) == {"role": ("unknown", 0, True), "channel": ("none", 0, True),
                             "identity": ("incomplete", 0, True), "employment": ("unverified", 0, True)}


def test_channel_levels_distinguish_usable_from_unconfirmed(ready, weights):
    _, _, _, contact, evidence = ready
    email = contact.channels[0]
    unverified = email.model_copy(update={"normalized_status": "unknown", "provider_status": None, "verified_at": None})
    linkedin = Channel(contact_id=contact.id, type="linkedin", value="https://www.linkedin.com/in/persona-sintetica",
                       evidence_ids=[evidence[1].id], retrieved_at=NOW, professional=True)
    invalid = email.model_copy(update={"normalized_status": "invalid", "provider_status": "invalid"})
    foreign = email.model_copy(update={"professional": False})
    for channels, expected in (([unverified], ("preferred_unconfirmed", 10, False)),
                               ([linkedin], ("alternative_unconfirmed", 7, False)),
                               ([invalid], ("none", 0, True)), ([foreign], ("none", 0, True))):
        person = contact.model_copy(update={"channels": channels})
        assert levels(match_of(ready, weights, person))["channel"] == expected


def test_identity_without_confirmation_scores_partially(ready, weights):
    _, _, _, contact, _ = ready
    pending = contact.model_copy(update={"identity_status": "pending"})
    assert levels(match_of(ready, weights, pending))["identity"] == ("complete_pending", 8, False)


@pytest.mark.parametrize("change, reason", [
    ({"identity_status": "contradicted"}, "identity_contradicted"),
    ({"current_employment": False}, "employment_ended"),
])
def test_rule_contradictions_block_without_hiding_the_breakdown(ready, weights, change, reason):
    _, _, _, contact, _ = ready
    match = match_of(ready, weights, contact.model_copy(update=change))
    assert match.blocked_reason == reason and len(match.components) == 4


def test_supported_scope_outside_company_countries_blocks_but_regional_scope_does_not(ready, weights):
    _, _, _, contact, evidence = ready
    provenance = contact.provenance | {"geographic_scope": [evidence[0].id]}
    other = contact.model_copy(update={"geographic_scope": "México", "provenance": provenance})
    assert match_of(ready, weights, other).blocked_reason == "scope_mismatch"
    regional = other.model_copy(update={"geographic_scope": "Responsable LATAM con residencia en México"})
    assert match_of(ready, weights, regional).blocked_reason is None


def test_match_orders_but_never_turns_an_outside_role_into_ready(ready, weights):
    company, campaign, assessment, _, _ = ready
    contact, evidence = retitled(ready, "Sales Manager")
    roles = target_roles(company, assessment, campaign)
    assert match_of(ready, weights, contact, evidence).score == 50
    assert not validate_contact(contact, company, assessment, evidence, campaign.limits, NOW, roles)
    assert derive_readiness(assessment, [contact], evidence, campaign.limits, NOW, company, roles) == "qualified_no_contact"


def test_order_is_deterministic_and_puts_blocked_people_last(ready, weights):
    company, campaign, assessment, best, evidence = ready
    roles = target_roles(company, assessment, campaign)

    def person(name, **changes):
        return Contact.model_validate(best.model_dump() | {"id": uuid4(), "name": name, "channels": []} | changes)

    people = [best, person("Ana Sintética"), person("Bruno Sintético"),
              person("Carla Sintética", identity_status="contradicted"),
              person("Diego Sintético", title=None, relevant_function=None, provenance={"name": best.provenance["name"]})]
    expected = [best.name, "Ana Sintética", "Bruno Sintético", "Diego Sintético", "Carla Sintética"]
    for seed in range(5):
        shuffled = people[:]
        random.Random(seed).shuffle(shuffled)
        ordered = sorted(shuffled, key=lambda item: match_sort_key(
            match_of(ready, weights, item), validate_contact(item, company, assessment, evidence, campaign.limits, NOW, roles),
            item, roles))
        assert [item.name for item in ordered] == expected


@pytest.mark.parametrize("mutate", [
    lambda data: data["components"]["role"].update(weight=45),
    lambda data: data["components"]["role"]["levels"].update(selected_role=40),
    lambda data: data["components"]["channel"]["levels"].update(preferred_usable=30),
    lambda data: data["components"]["identity"]["levels"].update(incomplete=3),
    lambda data: data["components"]["employment"]["levels"].update(manual=5),
    lambda data: data["components"].pop("employment"),
    lambda data: data["components"]["role"].update(weight="50"),
])
def test_invalid_weights_are_rejected_instead_of_defaulted(mutate):
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    mutate(data)
    with pytest.raises(ValidationError):
        ContactMatchConfig.model_validate(data)


def test_missing_config_fails_instead_of_using_default_weights(tmp_path):
    with pytest.raises(OSError):
        load_contact_match(tmp_path / "contact_match.json")


def test_v1_employment_levels_read_the_provider_neutral_state(ready, weights, make_hunter_contact):
    """T18 no cambia los pesos: la evidencia vale 10, Hunter conserva su nivel histórico y Apollo suma 0."""
    company, campaign, assessment, _, _ = ready
    assert levels(match_of(ready, weights))["employment"] == ("evidence", 10, False)
    hunter, hunter_facts = make_hunter_contact(company, NOW)
    assert levels(match_of(ready, weights, hunter, hunter_facts))["employment"] == ("hunter_signal", 6, False)
    assert not validate_contact(hunter, company, assessment, hunter_facts, campaign.limits, NOW)
    enrichment = Evidence(company_id=company.id, contact_id=hunter.id, claim="Apollo informa enrichment: sintético.",
                          provider="apollo", external_reference=f"apollo_v1:persona:{uuid4()}#enrichment",
                          retrieved_at=NOW, kind="observed", source_type="provider")
    claim = hunter.model_copy(update={"channels": []})
    assert levels(match_of(ready, weights, claim, [enrichment]))["employment"] == ("unverified", 0, True)


def test_v2_weights_are_versioned_and_corporate_evidence_reaches_one_hundred(ready, v2_weights):
    assert v2_weights.validation_status == "proposed"
    assert {name: item.weight for name, item in v2_weights.components.items()} == {
        "role": 40, "channel": 20, "identity": 15, "employment": 25}
    digest = hashlib.sha256(json.dumps(v2_weights.model_dump(mode="json")["components"], sort_keys=True).encode()).hexdigest()
    assert CONFIG_FINGERPRINTS[v2_weights.version] == digest
    match = match_of(ready, v2_weights)
    assert match.score == 100 and match.blocked_reason is None
    assert levels(match) == {"role": ("selected_role", 40, False), "channel": ("preferred_usable", 20, False),
                             "identity": ("confirmed_complete", 15, False), "employment": ("corporate_evidence", 25, False)}


@pytest.mark.parametrize("title", ["CTO", "Chief Technology Officer", "Director de Tecnología"])
def test_v2_bilingual_equivalent_titles_keep_the_same_priority(ready, v2_weights, title):
    contact, facts = retitled(ready, title)
    result = match_of(ready, v2_weights, contact, facts)
    assert levels(result)["role"] == ("selected_role", 40, False)
    assert result.score == 100


@pytest.mark.parametrize("change", ["unknown_version", "changed_points", "empty_source", "missing_source", "legacy_employment", "validated"])
def test_v2_rejects_unknown_versions_reused_version_and_missing_source(v2_weights, change):
    data = v2_weights.model_dump(mode="json")
    if change == "unknown_version":
        data["version"] = "contact_match_v3"
    elif change == "changed_points":
        data["components"]["role"]["levels"]["profile_role"] = 29
    elif change == "empty_source":
        data["source_reference"] = "  "
    elif change == "missing_source":
        data.pop("source_reference")
    elif change == "validated":
        data["validation_status"] = "validated"
    else:
        data["components"]["employment"]["levels"] = {"evidence": 25, "hunter_signal": 0, "unverified": 0}
    with pytest.raises(ValidationError):
        ContactMatchConfig.model_validate(data)


def test_v2_does_not_reward_provider_claims_or_make_high_match_ready(ready, v2_weights, make_hunter_contact):
    company, campaign, assessment, contact, evidence = ready
    person = contact.model_copy(update={"employment_evidence_ids": []})
    apollo = Evidence(company_id=company.id, contact_id=person.id, claim="Empleo declarado por Apollo, sintético.",
                      provider="apollo", external_reference="apollo_v1:persona-sintetica#enrichment", retrieved_at=NOW,
                      kind="observed", source_type="provider")
    facts = evidence + [apollo]
    match = match_of(ready, v2_weights, person, facts)
    assert match.score == 75 and levels(match)["employment"] == ("provider_claim", 0, True)
    assert not validate_contact(person, company, assessment, facts, campaign.limits, NOW)
    assert derive_readiness(assessment, [person], facts, campaign.limits, NOW, company) == "qualified_no_contact"
    hunter, hunter_facts = make_hunter_contact(company, NOW)
    assert levels(match_of(ready, v2_weights, hunter, hunter_facts))["employment"] == ("provider_claim", 0, True)
    assert levels(match_of(ready, v2_weights, person, evidence))["employment"] == ("unknown", 0, True)


def test_v2_expired_employment_loses_points_without_mutating_inputs(ready, v2_weights):
    company, campaign, assessment, contact, evidence = ready
    before = contact.model_dump(), [fact.model_dump() for fact in evidence]
    later = NOW + timedelta(days=campaign.limits.cache.web_days + 1)
    result = contact_match(contact, company, assessment, evidence, campaign.limits, later,
                           target_roles(company, assessment, campaign), v2_weights)
    assert levels(result)["employment"] == ("unknown", 0, True)
    assert (contact.model_dump(), [fact.model_dump() for fact in evidence]) == before


@pytest.mark.parametrize("conflict", ["ended", "departure", "cited_departure", "title_changed", "own_source", "reverse_source"])
def test_v2_blocks_all_employment_contradictions_and_preserves_v1(ready, weights, v2_weights, conflict):
    company, campaign, _, contact, evidence = ready
    source = evidence[0]
    if conflict == "ended":
        contact = contact.model_copy(update={"current_employment": False})
    elif conflict == "departure":
        evidence = evidence + [source.model_copy(update={"id": uuid4(), "excerpt": f"{NAME} ya no trabaja en Empresa sintética."})]
    elif conflict == "cited_departure":
        evidence = [source.model_copy(update={"contact_id": None, "excerpt": f"{NAME} ya no trabaja en Empresa sintética."}), evidence[1]]
    elif conflict == "title_changed":
        evidence = evidence + [source.model_copy(update={"id": uuid4(), "contradiction_ids": [source.id],
                                                        "excerpt": f"{NAME} ahora ocupa otro cargo."})]
    elif conflict == "own_source":
        evidence = [source.model_copy(update={"contradiction_ids": [uuid4()]}), evidence[1]]
    else:
        evidence = evidence + [source.model_copy(update={"id": uuid4(), "contact_id": None,
                                                        "contradiction_ids": [source.id]})]
    status = employment_status(contact, company, evidence, campaign.limits, NOW)
    assert status.state == "contradicted"
    expected = "employment_ended" if conflict in ("ended", "departure", "cited_departure") else "employment_contradicted"
    result = match_of(ready, v2_weights, contact, evidence)
    assert result.blocked_reason == expected and levels(result)["employment"] == ("contradicted", 0, False)
    historical = match_of(ready, weights, contact, evidence)
    assert historical.blocked_reason == ("employment_ended" if conflict in ("ended", "departure") else None)


def test_v2_puts_relevant_role_before_high_scoring_irrelevant_seniority(ready, v2_weights):
    company, campaign, assessment, relevant, evidence = ready
    outsider, outside_facts = retitled(ready, "Global Chief Executive Officer")
    outsider = outsider.model_copy(update={"id": uuid4(), "name": "Directora Sintética"})
    outside_facts = [item.model_copy(update={"contact_id": outsider.id, "excerpt": (item.excerpt or "").replace(NAME, outsider.name)})
                     for item in outside_facts]
    relevant = relevant.model_copy(update={"channels": [], "employment_evidence_ids": [], "name_complete": False})
    selected, outside = match_of(ready, v2_weights, relevant, evidence), match_of(ready, v2_weights, outsider, outside_facts)
    assert selected.score == 40 and outside.score > selected.score
    roles = target_roles(company, assessment, campaign)
    assert rank_contact_matches([(outsider, outside, False), (relevant, selected, False)], roles) == [relevant.id, outsider.id]


def test_v2_diversity_breaks_only_equal_scores_and_is_stable(ready, v2_weights):
    _, _, _, contact, _ = ready
    best = match_of(ready, v2_weights)
    people = [contact.model_copy(update={"id": uuid4(), "name": name}) for name in
              ("Ana Sintética", "Bruno Sintético", "Carla Sintética", "Diego Sintético")]
    functions = {people[0].id: "product", people[1].id: "product", people[2].id: "engineering", people[3].id: "finance"}
    entries = [(person, best, False) for person in people]
    for seed in range(5):
        random.Random(seed).shuffle(entries)
        assert rank_contact_matches(entries, ["CTO"], function_ids=functions,
                                    function_order=["product", "engineering", "finance"]) == [
            people[0].id, people[2].id, people[3].id, people[1].id]
    # Una función nueva con menos puntos no desplaza a otra persona de mayor match.
    lower = match_of(ready, v2_weights, contact.model_copy(update={"employment_evidence_ids": []}))
    assert lower.score < best.score
    entries = [(person, lower if person.id == people[2].id else best, False) for person in people]
    assert rank_contact_matches(entries, ["CTO"], function_ids=functions,
                                function_order=["product", "engineering", "finance"])[-1] == people[2].id


def test_v1_helper_preserves_historical_sort_and_offline_comparison(ready, weights, v2_weights):
    _, _, _, contact, _ = ready
    historical = match_of(ready, weights)
    current = match_of(ready, v2_weights)
    assert (historical.version, historical.score, current.version, current.score) == (
        "contact_match_v1", 100, "contact_match_v2", 100)
    people = [contact.model_copy(update={"id": uuid4(), "name": name}) for name in ("Ana Sintética", "Bruno Sintético")]
    entries = [(person, historical, False) for person in reversed(people)]
    expected = [item[0].id for item in sorted(entries, key=lambda item: match_sort_key(item[1], item[2], item[0], ["CTO"]))]
    assert rank_contact_matches(entries, ["CTO"], function_ids={people[0].id: "engineering", people[1].id: "product"},
                                function_order=["product", "engineering"]) == expected
