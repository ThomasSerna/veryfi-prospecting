"""Fixtures sintéticas y bloqueo de red externa para las pruebas locales."""

from datetime import datetime, timezone
from pathlib import Path
import socket
from types import SimpleNamespace
from uuid import uuid4

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RETRIEVED_AT = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def reject_external_network(monkeypatch):
    """Permite los sockets internos de Windows y rechaza destinos externos."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo
    local_hosts = {"127.0.0.1", "::1", "localhost"}

    def connect_locally(connection, address):
        if not isinstance(address, tuple) or address[0] not in local_hosts:
            raise AssertionError("Las pruebas no pueden acceder a la red externa.")
        return original_connect(connection, address)

    def connect_ex_locally(connection, address):
        if not isinstance(address, tuple) or address[0] not in local_hosts:
            raise AssertionError("Las pruebas no pueden acceder a la red externa.")
        return original_connect_ex(connection, address)

    def resolve_locally(host, *args, **kwargs):
        if host not in local_hosts:
            raise AssertionError("Las pruebas no pueden resolver destinos externos.")
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect_locally)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex_locally)
    monkeypatch.setattr(socket, "getaddrinfo", resolve_locally)


@pytest.fixture
def config():
    """Carga el catálogo propuesto, sin afirmar validación comercial."""
    from prospecting.models import VeryfiConfig

    return VeryfiConfig.model_validate_json(
        (PROJECT_ROOT / "config" / "veryfi.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def make_campaign(config):
    """Construye campañas sintéticas con una instantánea del catálogo."""
    from prospecting.models import Campaign

    def build(**overrides):
        fields = {
            "countries": ["CO"],
            "segments": ["fintech_software"],
            "config_snapshot": config,
            "rubric_version": "rubric_v1",
        }
        return Campaign.model_validate(fields | overrides)

    return build


@pytest.fixture
def make_company():
    """Cada dato conocido nace de una afirmación atómica sintética."""
    from prospecting.models import Company, Evidence

    def build(**overrides):
        company_id = overrides.pop("id", uuid4())
        fields = {"name": "Empresa sintética"} | overrides
        provenance = {}
        evidence = []
        for field in (
            "name", "domain", "aliases", "operating_countries", "segments",
            "parent_company_id", "size",
        ):
            if fields.get(field) is not None and fields.get(field) != []:
                fact = Evidence(
                    company_id=company_id,
                    claim=f"Dato sintético de {field}: {fields[field]}",
                    url="https://example.com/fuente-sintetica",
                    retrieved_at=RETRIEVED_AT,
                    kind="observed",
                    source_type="primary",
                )
                evidence.append(fact)
                provenance[field] = [fact.id]
        company = Company.model_validate(
            {"id": company_id, "provenance": provenance} | fields
        )
        return company, tuple(evidence)

    return build


@pytest.fixture
def make_contact():
    """Genera una persona ficticia con canal pendiente y fuentes nominales."""
    from prospecting.models import Channel, Contact, Evidence

    def build(company_id, **overrides):
        contact_id = overrides.pop("id", uuid4())
        evidence = []
        provenance = {}
        fields = {
            "name": "Persona Sintética Uno", "title": "Cargo sintético",
            "name_complete": True, "current_employment": True,
        }
        fields.update(overrides)
        for field in ("name", "title"):
            if fields[field] is not None:
                fact = Evidence(
                    company_id=company_id,
                    contact_id=contact_id,
                    claim=f"Dato profesional sintético de {field}: {fields[field]}",
                    url="https://example.com/directorio-sintetico",
                    retrieved_at=RETRIEVED_AT,
                    kind="observed",
                    source_type="primary",
                )
                evidence.append(fact)
                provenance[field] = [fact.id]
        employment_ids = []
        if fields["current_employment"] is not None:
            employment = Evidence(
                company_id=company_id,
                contact_id=contact_id,
                claim="Relación laboral sintética vigente en la entidad indicada.",
                url="https://example.com/empleo-sintetico",
                retrieved_at=RETRIEVED_AT,
                kind="observed",
                source_type="primary",
            )
            evidence.append(employment)
            employment_ids.append(employment.id)
        channel_fact = Evidence(
            company_id=company_id,
            contact_id=contact_id,
            claim="Canal sintético sin verificación de entregabilidad.",
            url="https://example.com/canal-sintetico",
            retrieved_at=RETRIEVED_AT,
            kind="observed",
            source_type="primary",
        )
        evidence.append(channel_fact)
        channel = Channel(
            contact_id=contact_id,
            type="email",
            value="persona-sintetica@example.com",
            evidence_ids=[channel_fact.id],
            normalized_status="unknown",
            retrieved_at=RETRIEVED_AT,
        )
        contact = Contact.model_validate(
            {
                "id": contact_id,
                "company_id": company_id,
                "provenance": provenance,
                "employment_evidence_ids": employment_ids,
                "channels": [channel],
            } | fields
        )
        return contact, tuple(evidence)

    return build


@pytest.fixture
def make_assessment():
    """La fixture conserva desconocidos, sin ejecutar una calificación."""
    from prospecting.models import Assessment

    def build(campaign_id, company_id, **overrides):
        criteria = {
            key: {
                "value": None,
                "evidence_ids": [],
                "justification": "Dato sintético desconocido.",
            }
            for key in (
                "document_need", "offer_match", "scale_potential",
                "adoption_capacity", "opportunity_timing",
            )
        }
        return Assessment.model_validate(
            {
                "campaign_id": campaign_id,
                "company_id": company_id,
                "criteria": criteria,
                "fit_score": None,
                "coverage": 0.0,
                "priority": "insufficient_evidence",
                "rubric_version": "rubric_v1",
                "explanation": "Evaluación sintética; no valida encaje comercial.",
            } | overrides
        )

    return build


@pytest.fixture
def database(tmp_path):
    """Toda base de pruebas es temporal y separada de data/."""
    from prospecting.db import Database

    with Database(tmp_path / "synthetic.sqlite3") as database:
        yield database


@pytest.fixture
def records(make_campaign, make_company, make_contact, make_assessment):
    """Prepara un grafo profesional completamente sintético."""
    from prospecting.models import RunItem, Usage

    campaign = make_campaign()
    company, company_evidence = make_company()
    contact, contact_evidence = make_contact(company.id)
    assessment = make_assessment(campaign.id, company.id)
    return SimpleNamespace(
        campaign=campaign,
        company=company,
        company_evidence=company_evidence,
        contact=contact,
        contact_evidence=contact_evidence,
        assessment=assessment,
        run_item=RunItem(campaign_id=campaign.id, company_id=company.id),
        usage=Usage(
            campaign_id=campaign.id,
            company_id=company.id,
            provider="synthetic",
            operation="lookup",
            request_fingerprint="a" * 64,
            account_ref="synthetic-account",
            status="reserved",
        ),
    )


@pytest.fixture
def persist_records():
    """Guarda un checkpoint mediante la misma interfaz de los llamadores."""
    def save(database, records):
        with database.transaction():
            database.save_campaign(records.campaign)
            database.save_company(records.company, evidence=records.company_evidence)
            database.save_run_item(records.run_item)
            database.save_contact(records.contact, evidence=records.contact_evidence)
            database.save_assessment(records.assessment)
            database.save_usage(records.usage)
            records.run_item = records.run_item.model_copy(
                update={"last_assessment_id": records.assessment.id}
            )
            database.save_run_item(records.run_item)
        return records

    return save
