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

from prospecting.contacts import (
    HUNTER_OPERATIONS, HunterDomainSearchResponse, build_contacts_request, domain_search_request,
    finder_request, parse_contacts_output, parse_domain_search, target_departments, verifier_request,
)
from prospecting.db import Database
from prospecting.discovery import build_search_queries, extract_query
from prospecting.haiku import MODEL_ID
from prospecting.identity import ExclusionList, exclusion_evidence, match_exclusion
from prospecting.models import Assessment, Campaign, Company, Contact, Evidence
from prospecting.providers import CLAUDE_PRICES_PER_MTOK, ClaudeClient, ProviderClient
from prospecting.providers.tavily import TAVILY_OPERATIONS, extract_request, search_request
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
                    config_snapshot=config, created_at=RETRIEVED_AT, updated_at=RETRIEVED_AT)


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
        "hunter_domain_roles": client.fingerprint(domain_search_request(company(), ["Product Manager"], ACCOUNT)),
        "hunter_domain_departments": client.fingerprint(domain_search_request(
            company(), ["Product Manager"], ACCOUNT, departments=target_departments(["Product Manager", "CTO"]))),
        "hunter_finder": client.fingerprint(finder_request(contact(), company(), ACCOUNT)),
        "hunter_verifier": client.fingerprint(verifier_request("persona@empresa-uno.example", ACCOUNT)),
        "haiku_assessment": ClaudeClient.fingerprint(haiku, ACCOUNT),
        "haiku_contacts": ClaudeClient.fingerprint(contacts, ACCOUNT),
    }


EXPECTED_FINGERPRINTS = {
    "tavily_search": "7ffaf59b70b633b6ebe2d1e28ab3eed5efce00c238f68484b23322315016e7b9",
    "tavily_search_last": "fc242ce31da2306567a247424a85d7d8504676f6ef2882d52694abbb74c07387",
    "tavily_extract": "e07e6d049bdc92127ed965084c09e7494dca1cba5c5073aa903e40968b4c2823",
    "hunter_domain_roles": "75821173a121c6ef99b3491a2280a8b507d1c636f4c4aea34fea8a64652f8ae7",
    "hunter_domain_departments": "9f6184b7ee6b0286f02e6481f4138500581e8cacb3611eaf94597f03210c6877",
    "hunter_finder": "8054608a83cf35292d9a3808652a2c5ff6e9ca5d90682f6f05f420668b578074",
    "hunter_verifier": "f48a0492f034a45888630bab111e202620df20717f4c8a537c1de2ebece036e7",
    "haiku_assessment": "e1b5c09b97919ae2006a8ee23d53d4151b71e552aefc70d2cda6ec8f83fc05fb",
    "haiku_contacts": "d4dea5e2d34b3ee2706a2fa85237c139e399c5f5b94a5310a257f9f9d5db45b2",
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


def test_sqlite_schema_does_not_change(tmp_path):
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
    assert (version, digest) == (1, "041bdf146760695410c12672702ddcdec7a3c19a301f5a623d197ca0e66dff47")


def test_reserved_model_has_a_published_price():
    """Sin precio acotado no se puede reservar la llamada (§14.5)."""
    assert MODEL_ID in CLAUDE_PRICES_PER_MTOK
