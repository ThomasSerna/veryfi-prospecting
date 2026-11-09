"""Valores guardados en SQLite con los que se reanuda y deduplica; no cambian al reorganizar código.

Las huellas impiden repetir solicitudes ya enviadas, los ids deterministas evitan
duplicar personas y evidencia, y los marcadores separan resúmenes de buscador de
hechos. Un cambio intencionado de prompt, configuración o formato de solicitud
actualiza aquí su valor y, si corresponde, la versión del prompt
(docs/persistence.md). Todos los datos son sintéticos.
"""

from datetime import UTC, datetime
import hashlib
import json
import sqlite3
from uuid import UUID

from prospecting.contact_extraction import build_contacts_request, parse_contacts_output
from prospecting.db import Database
from prospecting.discovery import build_search_queries, expansion_query, extract_query
from prospecting.haiku import MODEL_ID
from prospecting.identity import ExclusionList, exclusion_evidence, match_exclusion
from prospecting.models import Assessment, Campaign, Company, Contact, Evidence
from prospecting.providers import CLAUDE_PRICES_PER_MTOK, ClaudeClient, ProviderClient
from legacy_hunter import (
    HUNTER_OPERATIONS, HunterDomainSearchResponse, domain_search_request, finder_request, parse_domain_search,
    verifier_request,
)
from prospecting.providers.tavily import TAVILY_OPERATIONS, company_search_request, extract_request, search_request
from prospecting.qualification import build_haiku_request, unknown_criteria
from prospecting.sources import SEARCH_HIT_CLAIM, is_search_hit


RETRIEVED_AT = datetime(2026, 10, 11, 12, tzinfo=UTC)
NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)
ACCOUNT = "cuenta-sintetica"
COMPANY_ID = UUID("00000000-0000-4000-8000-000000000001")
CONTACT_ID = UUID("00000000-0000-4000-8000-000000000002")
CAMPAIGN_ID = UUID("00000000-0000-4000-8000-000000000003")
REQUEST_ID = UUID("00000000-0000-4000-8000-000000000004")
PRODUCT, SEARCH, DIRECTORY, CONTACT_SEARCH = (
    UUID(f"00000000-0000-4000-8000-0000000001{index:02d}") for index in range(4)
)
NOMINAL = ("Persona Sintética Uno es Product Manager de Empresa Uno. "
           "Correo profesional persona@empresa-uno.example.")


def company() -> Company:
    sources = [PRODUCT]
    return Company(
        id=COMPANY_ID, name="Empresa Uno", domain="empresa-uno.example",
        operating_countries=["CO"], segments=["fintech_software"],
        identity_status="confirmed", identity_key="empresa-uno.example|empresauno|CO",
        provenance={"name": sources, "domain": sources, "operating_countries": sources, "segments": sources},
    )


def evidence() -> list[Evidence]:
    def fact(id, **fields):
        return Evidence(id=id, company_id=COMPANY_ID, retrieved_at=RETRIEVED_AT, kind="observed", **fields)

    return [
        fact(PRODUCT, claim="Texto publicado en la página, extraído por Tavily.",
             url="https://empresa-uno.example/producto", provider="tavily",
             external_reference="extraccion-sintetica#1.1", source_type="primary",
             excerpt="Empresa Uno permite subir recibos de gastos en Colombia."),
        fact(SEARCH, claim=f"{SEARCH_HIT_CLAIM} en el puesto 1 para la consulta «consulta sintética» "
                           "(perfil expense_reimbursement, país CO).",
             url="https://empresa-uno.example/", provider="tavily",
             external_reference="busqueda-sintetica#1", source_type="secondary",
             excerpt="Resumen sintético del buscador."),
        fact(DIRECTORY, claim="Texto publicado en la página, extraído por Tavily.",
             url="https://empresa-uno.example/equipo", provider="tavily",
             external_reference="extraccion-sintetica#2.1", source_type="primary", excerpt=NOMINAL),
        fact(CONTACT_SEARCH, claim=f"{SEARCH_HIT_CLAIM} en una búsqueda pública de contactos; requiere contraste.",
             url="https://directorio.example/empresa-uno", provider="tavily",
             external_reference=f"contacts_search:{REQUEST_ID}:0", source_type="secondary", excerpt=NOMINAL),
    ]


def contact() -> Contact:
    return Contact(id=CONTACT_ID, company_id=COMPANY_ID, name="Persona Sintética Uno", title="Product Manager",
                   name_complete=True, provenance={"name": [DIRECTORY], "title": [DIRECTORY]})


def campaign(config) -> Campaign:
    return Campaign(id=CAMPAIGN_ID, countries=["CO", "MX"], segments=["fintech_software", "cpg_loyalty"],
                    config_snapshot=config.model_copy(update={"people_provider": None}), created_at=RETRIEVED_AT, updated_at=RETRIEVED_AT)


def assessment() -> Assessment:
    return Assessment(campaign_id=CAMPAIGN_ID, company_id=COMPANY_ID, criteria=unknown_criteria("Sintético."),
                      coverage=0.0, priority="medium", target_roles=["Product Manager"],
                      rubric_version="rubric_v1", explanation="Evaluación sintética.")


def fingerprints(config) -> dict[str, str]:
    """Huella de cada constructor de solicitudes con entradas fijas."""
    client = ProviderClient(None, [*TAVILY_OPERATIONS, *HUNTER_OPERATIONS])
    current = campaign(config)
    queries = build_search_queries(current)
    haiku, _ = build_haiku_request(company(), evidence(), current)
    contacts, _ = build_contacts_request(company(), assessment(), current, evidence(), [contact()])
    return {
        "tavily_search": client.fingerprint(search_request(queries[0], ACCOUNT, current.limits.discovery)),
        "tavily_search_last": client.fingerprint(search_request(queries[-1], ACCOUNT, current.limits.discovery)),
        "tavily_extract": client.fingerprint(extract_request(
            ["https://empresa-uno.example/producto"], extract_query(current), ACCOUNT)),
        "tavily_company_search": client.fingerprint(company_search_request(
            company(), expansion_query(company(), current), ACCOUNT)),
        "hunter_domain_broad": client.fingerprint(domain_search_request(company(), ["Product Manager"], ACCOUNT)),
        "hunter_domain_roles": client.fingerprint(domain_search_request(
            company(), ["Product Manager"], ACCOUNT, by_roles=True)),
        "hunter_finder": client.fingerprint(finder_request(contact(), company(), ACCOUNT)),
        "hunter_verifier": client.fingerprint(verifier_request("persona@empresa-uno.example", ACCOUNT)),
        "haiku_assessment": ClaudeClient.fingerprint(haiku, ACCOUNT),
        "haiku_contacts": ClaudeClient.fingerprint(contacts, ACCOUNT),
    }


EXPECTED_FINGERPRINTS = {
    "tavily_search": "7ffaf59b70b633b6ebe2d1e28ab3eed5efce00c238f68484b23322315016e7b9",
    "tavily_search_last": "fc242ce31da2306567a247424a85d7d8504676f6ef2882d52694abbb74c07387",
    "tavily_extract": "e07e6d049bdc92127ed965084c09e7494dca1cba5c5073aa903e40968b4c2823",
    "tavily_company_search": "5d36ec882ff69fdaa130850da1565389d4015986f9829fdda6da3ae49d119f46",
    # Cambio intencionado: la primera búsqueda pide todas las personas del dominio; la de cargos conserva su huella.
    "hunter_domain_broad": "65efd2f4e81895f6f9c151e4ad3847d33053823aa4c00e01bb811c3498b2a563",
    "hunter_domain_roles": "75821173a121c6ef99b3491a2280a8b507d1c636f4c4aea34fea8a64652f8ae7",
    "hunter_finder": "8054608a83cf35292d9a3808652a2c5ff6e9ca5d90682f6f05f420668b578074",
    "hunter_verifier": "f48a0492f034a45888630bab111e202620df20717f4c8a537c1de2ebece036e7",
    "haiku_assessment": "e1b5c09b97919ae2006a8ee23d53d4151b71e552aefc70d2cda6ec8f83fc05fb",
    # Cambio intencionado: "Cargos pertinentes" enumera todos los cargos de los perfiles; la plantilla no cambia.
    "haiku_contacts": "cecdc874cdbeba008f7a499068d54eb004bae128e67196a20491c511c67dd062",
}


def test_request_fingerprints_do_not_change(config):
    assert fingerprints(config) == EXPECTED_FINGERPRINTS


def test_search_summaries_never_reach_contact_extraction(config):
    """Ambos marcadores excluyen resúmenes de buscador como prueba de una persona (§7.3)."""
    facts = evidence()
    assert SEARCH_HIT_CLAIM == "Tavily devolvió esta página"
    assert [is_search_hit(item) for item in facts] == [False, True, False, True]
    _, selected = build_contacts_request(company(), assessment(), campaign(config), facts, [contact()])
    assert [item.id for item in selected] == [PRODUCT, DIRECTORY]


def test_deterministic_ids_do_not_change(config):
    hunter = HunterDomainSearchResponse.model_validate({"data": {
        "domain": "empresa-uno.example", "organization": "Empresa Uno", "emails": [
            {"id": 42, "value": "persona@empresa-uno.example", "type": "personal",
             "first_name": "Persona Sintética", "last_name": "Uno", "position": "Product Manager"},
            {"value": "otra@empresa-uno.example", "type": "personal", "first_name": "Otra", "last_name": "Persona"},
        ]}})
    people = [item.id for item, _ in parse_domain_search(company(), hunter, REQUEST_ID, NOW)]
    output = json.dumps({"candidates": [{"contact_id": None, "name": "Persona Sintética Uno", "facts": [
        {"field": field, "value": value, "evidence_id": str(DIRECTORY), "quote": NOMINAL}
        for field, value in (("name", "Persona Sintética Uno"), ("title", "Product Manager"),
                             ("employment", "Empresa Uno"), ("email", "persona@empresa-uno.example"))]}]})
    public = parse_contacts_output(output, "end_turn", company(), assessment(), campaign(config),
                                   [evidence()[2]], NOW, REQUEST_ID)
    exclusions = ExclusionList.model_validate({
        "version": "exclusiones-sinteticas-v1", "validation_status": "validated",
        "source_reference": "Lista sintética", "observed_at": RETRIEVED_AT.isoformat(),
        "entries": [{"id": "e1", "name": "Empresa Uno", "domains": ["empresa-uno.example"],
                     "scope": "entity", "reason": "current_customer", "source_reference": "Fila sintética 1"}],
    })
    confirmed = match_exclusion("empresa-uno.example", ["Empresa Uno"], ["CO"], exclusions)
    ambiguous = match_exclusion("otro-dominio.example", ["Empresa Uno"], ["CO"], exclusions)
    assert [str(item) for item in people] == [
        "9f330463-a1da-59dc-beac-9a09f8d21d50", "b0633d23-fd32-5750-9aed-8a2b9a3c1b97"]
    assert [str(item.id) for item, _ in public] == ["9f930077-50a0-57fc-8a3b-5b33b60fb22d"]
    assert [str(exclusion_evidence(COMPANY_ID, match, exclusions).id) for match in (confirmed, ambiguous)] == [
        "2427ceee-90ce-55f7-8a19-f9a85648f26a", "a69153b4-d402-564b-9bca-eaf990a4ee2c"]


def test_sqlite_schema_versions_are_fixed(tmp_path):
    from prospecting.db import _SCHEMA_V1

    with sqlite3.connect(":memory:") as legacy:
        legacy.executescript(_SCHEMA_V1)
        original = legacy.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
    assert hashlib.sha256(json.dumps(original, ensure_ascii=False).encode("utf-8")).hexdigest() == (
        "041bdf146760695410c12672702ddcdec7a3c19a301f5a623d197ca0e66dff47")
    path = tmp_path / "synthetic-schema.sqlite3"
    with Database(path):
        pass
    with sqlite3.connect(path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        rows = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
    connection.close()
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()
    assert (version, digest) == (2, "14880148696ceb55146937607e51777ff4a43f37a647582a580b37bc09c1d486")


def test_reserved_model_has_a_published_price():
    """Sin precio acotado no se puede reservar la llamada (§14.5)."""
    assert MODEL_ID in CLAUDE_PRICES_PER_MTOK


def test_apollo_v1_request_fingerprints_are_fixed():
    from prospecting.providers.apollo import APOLLO_OPERATIONS, enrichment_request, people_search_request

    client = ProviderClient(None, APOLLO_OPERATIONS)
    assert {
        "broad": client.fingerprint(people_search_request(company(), ["Product Manager"], ACCOUNT)),
        "roles": client.fingerprint(people_search_request(company(), ["Product Manager"], ACCOUNT, by_roles=True)),
        "enrichment": client.fingerprint(enrichment_request("apollo-sintetico-1", ACCOUNT)),
    } == {
        "broad": "606b51a5dca7dfa3467dcbda7f0179f975e04c6d67978691b67c70cf641ab5a9",
        "roles": "7c92f3bf535dfa4c9c07ffa6a25ed0c6923c008657d50b34a1ad93a20c7bb98f",
        "enrichment": "9f62205cbb37cb6af56a6a319195c089d09d49a72f39aebde0ed56d6da963a66",
    }


def test_apollo_v1_ids_references_and_attempt_keys_are_fixed(config):
    from prospecting.pipeline.contacts import PEOPLE_SEARCH_KEY, ENRICHMENTS_KEY, REJECTED_KEY
    from prospecting.providers.apollo import ApolloSearchResponse, parse_search

    data = ApolloSearchResponse.model_validate({"total_entries": 1, "people": [{
        "id": "apollo-sintetico-1", "first_name": "Persona", "last_name_obfuscated": "S***", "title": "CTO"}]})
    [(candidate, facts)] = parse_search(company(), data, REQUEST_ID, NOW)
    assert str(candidate.id) == "099a33e4-625d-5787-9ac8-ed0e03af8b0a"
    assert [item.external_reference for item in facts] == [
        f"apollo_v1:apollo-sintetico-1:{REQUEST_ID}#{field}" for field in ("name", "title", "search")]
    current = campaign(config).model_copy(update={"config_snapshot": config.model_copy(update={"people_provider": "apollo"})})
    output = json.dumps({"candidates": [{"contact_id": None, "name": "Persona Sintética Uno", "facts": [
        {"field": field, "value": value, "evidence_id": str(DIRECTORY), "quote": NOMINAL}
        for field, value in (("name", "Persona Sintética Uno"), ("title", "Product Manager"),
                             ("employment", "Empresa Uno"), ("email", "persona@empresa-uno.example"))]}]})
    [(public, public_facts)] = parse_contacts_output(output, "end_turn", company(), assessment(), current,
                                                   [evidence()[2]], NOW, REQUEST_ID)
    assert str(public.id) == "c238a15c-f22a-5ac2-aa08-ae55ab7f7ac8"
    assert all((item.external_reference or "").startswith(f"apollo_public_v1:{REQUEST_ID}") for item in public_facts)
    assert (PEOPLE_SEARCH_KEY, ENRICHMENTS_KEY) == ("contacts:apollo_search", "contacts:apollo_enrichments")
    assert REJECTED_KEY == "contacts:apollo_rejected:"


def test_people_policy_version_is_fixed(role_config):
    """La versión del objetivo de personas (T16) identifica la regla de parada guardada en cada instantánea."""
    assert role_config.people_policy.version == "people_policy_v1"


def test_reconciliation_receipt_and_rate_limit_identifiers_are_fixed():
    """T17: el formato del comprobante y los límites Free quedan fijados; cambiarlos exige otra versión."""
    from typing import get_args

    from prospecting.pipeline import ReconciliationReceipt
    from prospecting.providers.apollo import ApolloAccess

    assert get_args(ReconciliationReceipt.model_fields["version"].annotation) == ("apollo_reconciliation_v1",)
    assert "rate_limits" in ApolloAccess.model_fields and not ApolloAccess.model_fields["rate_limits"].is_required()


def test_entity_mismatch_codes_are_fixed():
    """T17: los códigos de la condición de entidad se guardan en `contacts:apollo_rejected:`; no se renombran."""
    from prospecting.providers.apollo import ENTITY_MISMATCH_CODES

    assert ENTITY_MISMATCH_CODES == (
        "entity_mismatch_no_organization", "entity_mismatch_domain", "entity_mismatch_organization_id",
        "entity_mismatch_name", "entity_mismatch_not_current",
    )
    assert all(":" not in code for code in ENTITY_MISMATCH_CODES)


def test_manual_employment_references_are_fixed():
    """T23: la confirmación manual del empleo se reconoce por proveedor, prefijo y texto fijos; no se renombran."""
    from uuid import UUID

    from prospecting.contacts import (
        MANUAL_EMPLOYMENT_CLAIM, MANUAL_EMPLOYMENT_PROVIDER, MANUAL_EMPLOYMENT_REFERENCE, is_manual_employment,
        manual_employment_evidence,
    )

    assert (MANUAL_EMPLOYMENT_PROVIDER, MANUAL_EMPLOYMENT_REFERENCE) == ("manual_review", "manual-employment:")
    assert MANUAL_EMPLOYMENT_CLAIM == ("Empleo vigente confirmado manualmente por ventas, sin enviar mensajes, "
                                       "llamadas ni invitaciones. Motivo: ")
    campaign_id = UUID("00000000-0000-4000-8000-0000000000aa")
    person = contact()
    fact = manual_employment_evidence(company(), person, campaign_id, title="CTO", source_url="https://empresa-uno.example/equipo",
                                      reason="Motivo sintético.", now=NOW)
    assert fact.external_reference == f"manual-employment:{campaign_id}:{person.id}:{NOW.isoformat()}"
    assert (fact.source_type, fact.kind, fact.provider) == ("manual", "observed", "manual_review")
    assert fact.claim == MANUAL_EMPLOYMENT_CLAIM + "Motivo sintético." and is_manual_employment(fact)
