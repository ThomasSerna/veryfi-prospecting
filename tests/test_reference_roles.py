"""Cargos de `role_taxonomy_v2` frente a títulos reales de mercado; títulos sintéticos, sin personas ni red."""

import pytest

from prospecting.contacts import _family_title
from prospecting.models import IdentityStatus
from prospecting.providers.apollo import _entity_mismatch, people_search_request


def families_for(role_config, title):
    return {family.id for family in role_config.role_taxonomy.families if _family_title(title, family)}


@pytest.mark.parametrize("title, family", [
    # Patrón de los perfiles de referencia: datos de marketing y lealtad en consumo masivo.
    ("Marketing Data Strategy Lead", "marketing_data"),
    ("Sr. Director, Consumer Data & Precision Marketing", "marketing_data"),
    ("Gerente Sr de Datos de Marketing", "marketing_data"),
    ("Loyalty & Brand Manager", "marketing_owners"),
    ("Sr. Manager, Loyalty & CRM", "loyalty_crm"),
    ("Marketing Loyalty Programs Manager", "loyalty_crm"),
    ("Gerente de Programa de Lealtad", "loyalty_crm"),
    ("Head of CRM, LATAM", "loyalty_crm"),
    ("Senior Brand Manager México", "marketing_owners"),
    ("Directora de Marketing Digital", "marketing_owners"),
    ("Consumer Insights Sr Manager", "consumer_insights"),
    # FinTech: el cargo va con antigüedad, área o ámbito.
    ("Senior Product Manager, Expenses", "product_owners"),
    ("VP of Engineering, Platform", "engineering_leadership"),
    ("Director Regional de Producto", "product_leadership"),
])
def test_real_title_variants_belong_to_their_family(role_config, title, family):
    assert family in families_for(role_config, title)


@pytest.mark.parametrize("title", [
    "Brand Ambassador", "Employer Brand Manager", "Loyalty Analyst", "Assistant Brand Manager",
    "Practicante de Marketing Digital", "CRM Sales Manager", "Product Marketing Manager",
    "Sales Engineering Manager", "Gerente de Ventas", "Head of Innovation",
])
def test_junior_sales_and_unrelated_titles_stay_out(role_config, title):
    assert families_for(role_config, title) == set()


def test_catalog_search_adds_country_and_lets_apollo_return_similar_titles(make_company):
    company, _ = make_company(name="Empresa Sintética", domain="empresa-sintetica.example", identity_status="confirmed")
    local = people_search_request(company, ["Loyalty Manager", "loyalty"], "apollo-sintetico",
                                  seniorities=["manager"], countries=["MX", "CO", "US"])
    assert local.payload == {
        "q_organization_domains_list": ["empresa-sintetica.example"], "page": 1, "per_page": 10,
        "person_locations": ["Mexico", "Colombia"], "person_titles": ["Loyalty Manager", "loyalty"],
        "person_seniorities": ["manager"]}
    regional = people_search_request(company, ["Loyalty Manager"], "apollo-sintetico", seniorities=[])
    assert "person_locations" not in regional.payload and "include_similar_titles" not in regional.payload


@pytest.mark.parametrize("organization, expected", [
    ("Grupo Consumo Sintético", None), ("Consumo Sintético México", None), ("Otra Empresa", "entity_mismatch_name")])
def test_enrichment_accepts_a_name_variant_of_the_same_domain_but_not_another_entity(make_company, organization, expected):
    from prospecting.providers.apollo import ApolloEmployment, ApolloOrganization, ApolloPerson

    company, _ = make_company(name="Consumo Sintético", domain="consumo-sintetico.example",
                              identity_status=IdentityStatus.CONFIRMED)
    person = ApolloPerson(
        id="persona-sintetica", organization_id="org-sintetica",
        organization=ApolloOrganization(id="org-sintetica", name=organization, primary_domain=company.domain),
        employment_history=[ApolloEmployment(current=True, organization_id="org-sintetica")])
    assert _entity_mismatch(company, person) == expected


def test_qualification_prompt_leaves_room_for_the_evidence_of_a_whole_company(role_config, make_company):
    """Lote real del 2026-11-16: el prompt fijo y el esquema dejaban sitio para dos fragmentos y nada calificaba."""
    from datetime import UTC, datetime

    from prospecting.models import Campaign, Evidence
    from prospecting.qualification import build_haiku_request

    campaign = Campaign(countries=["CO", "MX"], segments=["fintech_software", "cpg_loyalty"],
                        config_snapshot=role_config, rubric_version="rubric_v2")
    company, _ = make_company(name="Consumo Sintético", domain="consumo-sintetico.example", identity_status="confirmed",
                              segments=["cpg_loyalty"], operating_countries=["MX"])
    fragment = "Texto sintético de una página con una promoción ficticia que pide registrar el ticket de compra. " * 8
    evidence = [Evidence(company_id=company.id, claim="Texto publicado en la página, extraído por Tavily.",
                         url=f"https://consumo-sintetico.example/pagina-{index}", excerpt=fragment[:800],
                         retrieved_at=datetime(2026, 11, 16, tzinfo=UTC), kind="observed", source_type="primary")
                for index in range(30)]
    _, selected = build_haiku_request(company, evidence, campaign)
    # Portada, ampliación propia y de terceros y extracción de contactos suman unos 25 fragmentos por empresa.
    assert len(selected) >= 25


def test_preferred_functions_go_first_among_relevant_people_even_with_a_lower_score(make_contact, make_company):
    """Lote real del 2026-11-16: una gerente de programas de lealtad quedó detrás de un director comercial."""
    from prospecting.contacts import ContactMatch, MatchComponent, rank_contact_matches

    company, _ = make_company()

    def entry(title, score, role="profile_role"):
        contact, _ = make_contact(company.id, title=title)
        match = ContactMatch(version="contact_match_v3", score=score, components=[
            MatchComponent(name="role", level=role, points=score, weight=55, pending=False)])
        return contact, match, False

    loyalty = entry("Marketing Loyalty Programs Manager", 39)
    commercial = entry("Commercial Director", 55, role="selected_role")
    outsider = entry("Plant Manager", 0, role="outside_profile")
    functions = {loyalty[0].id: "loyalty_crm", commercial[0].id: "cpg_economic"}
    order = rank_contact_matches([commercial, outsider, loyalty], [], function_ids=functions,
                                 preferred_functions={"loyalty_crm", "marketing_data"})
    assert order == [loyalty[0].id, commercial[0].id, outsider[0].id]
    # Sin funciones preferentes manda el puntaje, como antes.
    assert rank_contact_matches([commercial, outsider, loyalty], [], function_ids=functions)[0] == commercial[0].id


def test_profile_quote_taken_from_collapsed_text_is_saved_and_keeps_its_roles(
        database, role_config, make_campaign, make_company, make_assessment):
    """Lote real del 2026-11-16: la cita de Haiku (texto con espacios colapsados) hacía fallar la campaña al guardar."""
    from datetime import UTC, datetime

    from prospecting.contacts import role_families
    from prospecting.models import Evidence, RunItem, contains_quote

    campaign = database.save_campaign(make_campaign(
        countries=["MX"], segments=["cpg_loyalty"], config_snapshot=role_config, rubric_version="rubric_v2"))
    company, facts = make_company(name="Consumo Sintético", domain="consumo-sintetico.example",
                                  identity_status="confirmed", segments=["cpg_loyalty"], operating_countries=["MX"])
    page = Evidence(company_id=company.id, claim="Texto publicado en la página, extraído por Tavily.",
                    url="https://consumo-sintetico.example/promo", kind="observed", source_type="primary",
                    excerpt="Promoción sintética.\n\nRegistra tu   ticket\nde compra y gana premios.",
                    retrieved_at=datetime(2026, 11, 16, tzinfo=UTC))
    quote = "Registra tu ticket de compra y gana premios."
    assert contains_quote(page.excerpt, quote) and not contains_quote(page.excerpt, "Cita que nadie publicó.")
    database.save_company(company, evidence=[*facts, page])
    database.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id))
    assessment = database.save_assessment(make_assessment(
        campaign.id, company.id, rubric_version="rubric_v2",
        profile_matches=[{"profile_id": "cpg_brands", "citations": [{"evidence_id": page.id, "quote": quote}]}]))
    families = role_families(company, assessment, campaign, evidence=database.list_evidence(company.id))
    assert {"loyalty_crm", "marketing_data"} <= {family.id for family in families}
    assert [family.id for family in families if family.preferred] == ["loyalty_crm", "marketing_data"]
