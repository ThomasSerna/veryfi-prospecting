"""Taxonomía de personas con ejemplos y responsabilidades exclusivamente sintéticos."""

from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from prospecting.contact_extraction import build_contacts_request, parse_contacts_output
from prospecting.contacts import (
    ContactError, apply_campaign_roles, contact_match, load_contact_match, role_families, target_roles, validate_contact,
)
from prospecting.models import Contact, Evidence, RoleTaxonomy, utc_now
from prospecting.pipeline.contacts import _ContactStage
from prospecting.providers.apollo import people_search_request


@pytest.fixture
def role_case(config, make_campaign, make_company, make_assessment):
    profile = next(item for item in config.profiles if item.id == "expense_reimbursement")
    common = {"profile_ids": [profile.id], "departments": ["Producto"], "excluded_titles": ["Product Marketing", "Sales Director"],
              "source_reference": "Patrones sintéticos sin personas reales", "source_date": "2026-11-01", "validation_status": "pending"}
    families = [
        common | {"id": "product", "function_id": "product", "buying_role": "business_champion", "titles_en": ["Head of Product"],
                  "titles_es": ["Director de Producto"], "seniorities": ["head", "director"],
                  "function_terms": ["product roadmap", "hoja de ruta de producto"]},
        common | {"id": "engineering", "function_id": "engineering", "buying_role": "technical_champion", "titles_en": ["Principal Software Engineer", "Solutions Architect"],
                  "titles_es": ["Arquitecto de Soluciones"], "seniorities": [], "function_terms": ["integración de APIs"]},
        common | {"id": "finance", "function_id": "finance", "buying_role": "economic_buyer", "titles_en": ["CFO"], "titles_es": ["Director Financiero"],
                  "seniorities": ["c_suite", "director"], "function_terms": ["presupuesto financiero"]},
    ]
    taxonomy = RoleTaxonomy(version="role_taxonomy_v1", source_date="2026-11-01", validation_status="pending", families=families)
    current = config.model_copy(update={"people_provider": "apollo", "role_taxonomy": taxonomy})
    campaign = make_campaign(config_snapshot=current)
    company, _ = make_company(name="Empresa Sintética", domain="empresa-sintetica.example", identity_status="confirmed",
                             segments=["fintech_software"], operating_countries=["CO"])
    now = utc_now()
    source = Evidence(company_id=company.id, claim="Caso de uso sintético", excerpt="La empresa gestiona recibos y reembolsos.",
                      url=f"https://{company.domain}/producto", retrieved_at=now, kind="observed", source_type="primary")
    assessment = make_assessment(campaign.id, company.id, priority="high", profile_matches=[{
        "profile_id": profile.id, "citations": [{"evidence_id": source.id, "quote": source.excerpt}]}])
    return SimpleNamespace(company=company, campaign=campaign, assessment=assessment, source=source, now=now)


def professional(case, title):
    identifier = uuid4()
    name = "Persona Sintética " + str(identifier)[:8]
    fact = Evidence(company_id=case.company.id, contact_id=identifier, kind="observed", source_type="primary",
                    url=f"https://{case.company.domain}/equipo", retrieved_at=case.now,
                    claim="Directorio sintético", excerpt=f"{name} es {title} de {case.company.name}.")
    contact = Contact(id=identifier, company_id=case.company.id, name=name, title=title, name_complete=True,
                      current_employment=True, identity_status="confirmed",
                      provenance={field: [fact.id] for field in ("name", "title")}, employment_evidence_ids=[fact.id])
    return contact, fact


def classify(case, contact, facts):
    return apply_campaign_roles(contact, case.company, case.assessment, case.campaign, [case.source] + facts, case.now)


@pytest.mark.parametrize("title", ["head of product", "Director de Próducto", "Head of Product, LATAM", "Regional Head of Product",
                                  "Director Regional de Producto", "Principal Software Engineer"])
def test_role_variants_and_regional_specialists_are_relevant_without_authority(role_case, title):
    case = role_case
    contact, source = professional(case, title)
    classified = classify(case, contact, [source])
    assert classified.relevant_function is True and classified.buying_role == "unknown"
    assert contact.relevant_function is None
    assert validate_contact(classified, case.company, case.assessment, [case.source, source], case.campaign.limits, case.now,
                            target_roles(case.company, case.assessment, case.campaign), campaign=case.campaign)


@pytest.mark.parametrize("title, expected", [("Head of Innovation", None), ("Product Marketing Manager", False),
                                             ("Sales Director", False), ("Assistant to Head of Product", False)])
def test_ambiguous_and_outside_roles_never_reuse_a_global_positive(role_case, title, expected):
    case = role_case
    contact, source = professional(case, title)
    contact = contact.model_copy(update={"relevant_function": True, "provenance": contact.provenance | {"relevant_function": [source.id]}})
    assert classify(case, contact, [source]).relevant_function is expected


@pytest.mark.parametrize("change", ["valid", "negated_es", "negated_en", "cropped_negation", "external", "stale", "contradicted", "other_person"])
def test_ambiguous_function_needs_positive_nominal_current_corporate_evidence(role_case, change):
    case = role_case
    contact, source = professional(case, "Head of Innovation")
    value = {"negated_es": "no gestiona la hoja de ruta de producto", "negated_en": "not responsible for product roadmap"}.get(change,
             "gestiona la hoja de ruta de producto")
    quote = f"{contact.name} {'no ' if change == 'cropped_negation' else ''}{value}."
    responsibility = Evidence(company_id=case.company.id, contact_id=contact.id, kind="observed", source_type="primary",
        url=f"https://{case.company.domain}/equipo" if change != "external" else "https://otra-empresa.example/equipo",
        retrieved_at=case.now if change != "stale" else case.now - timedelta(days=400),
        claim=f"Hecho nominal publicado: responsibilities={value}", excerpt=quote,
        contradiction_ids=[source.id] if change == "contradicted" else [])
    original = responsibility.model_copy(update={"id": uuid4(), "contact_id": None, "claim": "Fuente corporativa sintética"})
    responsibility = responsibility.model_copy(update={
        "external_reference": f"apollo_public_v1:{uuid4()}#contact:responsibilities:{original.id}"})
    if change == "other_person":
        responsibility = responsibility.model_copy(update={"contact_id": uuid4()})
    facts = [source, original, responsibility]
    classified = classify(case, contact, facts)
    assert classified.relevant_function is (True if change == "valid" else None)
    if change == "valid":
        assert classified.provenance["relevant_function"] == [responsibility.id]
        assert validate_contact(classified, case.company, case.assessment, [case.source] + facts, case.campaign.limits, case.now,
                                campaign=case.campaign)


def test_case_of_use_does_not_leak_to_another_campaign(role_case, make_campaign, make_assessment):
    case = role_case
    contact, source = professional(case, "Head of Product")
    positive = classify(case, contact, [source])
    other = make_campaign(config_snapshot=case.campaign.config_snapshot)
    assessment = make_assessment(other.id, case.company.id, priority="high")
    assert role_families(case.company, assessment, other) == []
    assert target_roles(case.company, assessment, other) == []
    assert apply_campaign_roles(positive, case.company, assessment, other, [source], case.now).relevant_function is False
    assert classify(case, positive, [source]).relevant_function is True


def test_later_contradiction_blocks_profile_and_claim_citations_are_supported(role_case):
    case = role_case
    source = case.source.model_copy(update={"claim": case.source.excerpt, "excerpt": None})
    assert role_families(case.company, case.assessment, case.campaign, evidence=[source])
    negative = Evidence(company_id=case.company.id, claim="Contradicción sintética del caso de uso", kind="observed",
                        source_type="primary", url=f"https://{case.company.domain}/producto", retrieved_at=case.now,
                        contradiction_ids=[source.id])
    assert role_families(case.company, case.assessment, case.campaign, evidence=[source, negative]) == []
    assert target_roles(case.company, case.assessment, case.campaign, evidence=[source, negative]) == []


@pytest.mark.parametrize("original", [True, False])
def test_saving_new_observations_preserves_original_campaign_classification(role_case, original):
    case = role_case
    contact, source = professional(case, "Head of Product")
    source = source.model_copy(update={"external_reference": f"apollo_public_v1:{uuid4()}#contact:title"})
    old = contact.model_copy(update={"relevant_function": original,
                                    "provenance": contact.provenance | {"relevant_function": [source.id]}})
    facts = [case.source, source]
    stage = _ContactStage.__new__(_ContactStage)
    stage.campaign, stage.company, stage.assessment = case.campaign, case.company, case.assessment
    stage.roles = target_roles(case.company, case.assessment, case.campaign, evidence=facts)
    stage.facts = lambda: facts
    stage.db = SimpleNamespace(list_contacts=lambda identifier: [old], list_evidence=lambda identifier: facts)
    [(saved, _)], _ = stage.save_candidates([(contact, [source])])
    assert saved.relevant_function is original and saved.provenance["relevant_function"] == [source.id]
    assert classify(case, saved, [source]).relevant_function is True


def test_new_extraction_collects_cited_function_without_an_extra_request(role_case):
    case = role_case
    contact, source = professional(case, "Head of Innovation")
    responsibility = "gestiona la hoja de ruta de producto"
    source = source.model_copy(update={"contact_id": None, "excerpt": source.excerpt + f" {contact.name} {responsibility}."})
    payload, _ = build_contacts_request(case.company, case.assessment, case.campaign, [case.source, source], [])
    assert "contacts_extraction_v2" in payload["system"]
    output = {"candidates": [{"name": contact.name, "contact_id": None, "facts": [
        {"field": field, "value": value, "evidence_id": str(source.id), "quote": source.excerpt}
        for field, value in (("name", contact.name), ("title", contact.title), ("employment", case.company.name),
                             ("responsibilities", responsibility))]}]}
    request_id = uuid4()
    [(parsed, facts)] = parse_contacts_output(json.dumps(output), "end_turn", case.company, case.assessment,
                                               case.campaign, [case.source, source], case.now, request_id)
    assert parsed.relevant_function is True and parsed.buying_role == "unknown"
    responsibility_fact = next(item for item in facts if item.claim.startswith("Hecho nominal publicado: responsibilities="))
    assert responsibility_fact.external_reference == f"apollo_public_v1:{request_id}#contact:responsibilities:{source.id}"
    available = [case.source, source] + facts
    assert validate_contact(parsed, case.company, case.assessment, available, case.campaign.limits, case.now,
                            campaign=case.campaign)
    contradiction = Evidence(company_id=case.company.id, claim="La fuente original queda contradicha.", kind="observed",
                             source_type="primary", url=f"https://{case.company.domain}/equipo", retrieved_at=case.now,
                             contradiction_ids=[source.id])
    current = classify(case, parsed, available + [contradiction])
    assert current.relevant_function is None
    assert not validate_contact(current, case.company, case.assessment, available + [contradiction], case.campaign.limits,
                                case.now, campaign=case.campaign)


def test_taxonomy_preserves_selected_role_level_and_historical_match_weights(role_case):
    case = role_case
    contact, source = professional(case, "Head of Product")
    assessment = case.assessment.model_copy(update={"target_roles": [contact.title]})
    config = load_contact_match(Path(__file__).resolve().parents[1] / "config" / "contact_match.json")
    match = contact_match(contact, case.company, assessment, [case.source, source], case.campaign.limits,
                          case.now, target_roles(case.company, assessment, case.campaign), config, campaign=case.campaign)
    component = next(item for item in match.components if item.name == "role")
    assert component.level == "selected_role" and component.points == config.components["role"].levels["selected_role"]
    assert match.version == "contact_match_v1"


def test_role_queries_are_bounded_and_diversity_does_not_increase_limits(role_case):
    case = role_case
    contacts, facts = [], [case.source]
    for title in ("Head of Product", "Head of Product", "Principal Software Engineer", "CFO"):
        contact, fact = professional(case, title)
        contacts.append(classify(case, contact, [fact]))
        facts.append(fact)
    stage = _ContactStage.__new__(_ContactStage)
    stage.company, stage.assessment, stage.campaign = case.company, case.assessment, case.campaign
    stage.roles = target_roles(case.company, case.assessment, case.campaign)
    stage.people, stage.facts, stage.selected = lambda: contacts, lambda: facts, lambda: set()
    assert [contact.title for contact in stage.ranked_people()] == ["Head of Product", "Principal Software Engineer", "CFO", "Head of Product"]
    stage.apollo_access = SimpleNamespace(account_ref="cuenta-sintetica", funding_source="free_credit")
    stage.effort, stage.policy = case.campaign.limits.effort["high"], case.campaign.config_snapshot.people_policy
    requests = []
    stage.perform = lambda request, *args, **kwargs: requests.append(request)
    stage._search_apollo()
    assert len(requests) == 2
    assert requests[0].payload["person_seniorities"]
    assert "Principal Software Engineer" in requests[1].payload["person_titles"]
    assert "person_seniorities" not in requests[1].payload
    assert all(request.payload["person_titles"] and request.payload["include_similar_titles"] is False
               and request.payload["page"] == 1 and request.payload["per_page"] == 10 for request in requests)
    with pytest.raises(ContactError):
        people_search_request(case.company, [f"Cargo {index}" for index in range(100)], "cuenta-sintetica", by_roles=True)
    with pytest.raises(ContactError):
        people_search_request(case.company, [], "cuenta-sintetica", seniorities=[])
