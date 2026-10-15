"""Porcentaje de match de contactos: determinístico, explicable y sin decidir listo. Datos sintéticos."""

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import random
from uuid import uuid4

from pydantic import ValidationError
import pytest

from prospecting.contacts import (
    ContactMatchConfig, contact_match, derive_readiness, load_contact_match, match_sort_key, target_roles,
    validate_contact,
)
from prospecting.models import Channel, Contact, Evidence


NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)
NAME = "Persona Sintética Uno"
EMAIL = "persona-sintetica@example.com"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "contact_match.json"
# Cambiar un peso o nivel exige una versión nueva y su huella aquí (docs/contacts.md).
CONFIG_FINGERPRINTS = {"contact_match_v1": "dd990a111908273b12a82a916a8174962377367aa41c9dc7aa6f0f31407b6d7e"}


@pytest.fixture
def weights():
    return load_contact_match(CONFIG_PATH)


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
