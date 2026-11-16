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
    ("Sr. Manager, Loyalty & CRM", "marketing_owners"),
    ("Gerente de Programa de Lealtad", "marketing_owners"),
    ("Head of CRM, LATAM", "marketing_owners"),
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
