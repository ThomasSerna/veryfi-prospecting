"""Muestra y transporte completamente sintéticos para ejecutar el mismo orquestador sin red."""

from datetime import timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from prospecting.budget import SpendingAuthorization
from prospecting.models import utc_now
from prospecting.providers.apollo import ApolloRateLimit
from prospecting.providers.http import HttpResponse

from .contracts import (
    BenchmarkApproval, BenchmarkCompany, BenchmarkLimits, BenchmarkManifest, EmploymentEvidence,
    OperationBound, ProviderAccess, manifest_digest,
)


BENCHMARK_ID = UUID("c77a6e22-d653-4fd7-a533-e6a46d13ef11")
COMPANY_IDS = (UUID("10000000-0000-4000-8000-000000000001"), UUID("10000000-0000-4000-8000-000000000002"))
COMPANIES = (
    {"name": "Finanzas Sintéticas", "domain": "finanzas-fixture.example", "country": "CO", "segment": "fintech_software"},
    {"name": "Consumo Sintético", "domain": "consumo-fixture.example", "country": "MX", "segment": "cpg_loyalty"},
)
PEOPLE = (
    {"first_name": "Ana", "last_name": "Sintética", "title": "CTO", "email_status": "valid"},
    {"first_name": "Luis", "last_name": "Ejemplo", "title": "CFO", "email_status": "unknown"},
)
OPERATIONS = {
    "apollo": ("people_search", "people_enrichment"),
    "snov": ("oauth", "people_search", "people_search_result", "people_enrichment", "people_enrichment_result"),
}


def build_fixture_inputs():
    """Autoriza únicamente este escenario sintético; no constituye autorización de gasto real."""
    now = utc_now()
    created = now - timedelta(seconds=2)
    config_bytes = (Path(__file__).resolve().parents[2] / "config" / "veryfi.json").read_bytes()
    config = json.loads(config_bytes)
    companies = []
    for company_id, item in zip(COMPANY_IDS, COMPANIES):
        evidence = [EmploymentEvidence(
            full_name=f"{person['first_name']} {person['last_name']}", title=person["title"], domain=item["domain"],
            source_url=f"https://{item['domain']}/equipo", excerpt=(
                f"{person['first_name']} {person['last_name']}, {person['title']} de {item['name']}. "
                "Directorio y nombres completamente sintéticos."),
            observed_at=created - timedelta(minutes=1), published_at=created - timedelta(days=1), status="current",
        ) for person in PEOPLE]
        companies.append(BenchmarkCompany(
            company_id=company_id, **item, source_reference="fixture:identidad-sintetica-v1",
            observed_at=created - timedelta(hours=1), roles=["CTO", "Director de Tecnología", "CFO", "Director Financiero"],
            role_families={"technology": ["CTO", "Director de Tecnología"], "finance": ["CFO", "Director Financiero"]},
            evidence=evidence,
        ))
    manifest = BenchmarkManifest(
        benchmark_id=BENCHMARK_ID, origin="synthetic", created_at=created,
        source_reference="fixture:snov-vs-apollo-v1; ninguna empresa ni persona real",
        companies=companies, contact_days=config["defaults"]["cache"]["contact_days"],
        config_versions={"role_taxonomy": config["role_taxonomy"]["version"],
                         "veryfi_sha256": hashlib.sha256(config_bytes).hexdigest(), "fixture": "snov_fixture_v1"},
        limits=BenchmarkLimits(max_requests=100, max_pages=2, max_people=3, max_polls=3,
                               timeout_seconds=1.0, max_seconds=30.0, poll_interval_seconds=0.001),
    )
    access, grants = [], []
    approved_at = now - timedelta(seconds=1)
    for provider, operations in OPERATIONS.items():
        account = f"fixture-{provider}"
        bounds = {operation: OperationBound(
            cost_usd=Decimal("0"), credits=Decimal("1") if operation == "people_enrichment" else Decimal("0"),
            source_reference="fixture:costos-sinteticos; no son precios reales", observed_at=approved_at,
        ) for operation in operations}
        access.append(ProviderAccess(
            provider=provider, account_ref=account, access_verified=True, observed_at=approved_at,
            source_reference="fixture:acceso-sintetico", funding_source="free_credit",
            credit_limit=Decimal("100"), cost_limit_usd=Decimal("0"), prior_credits_used=Decimal("2"),
            prior_cost_usd=Decimal("0"), usage_consolidated_verified=True,
            usage_source_reference="fixture:consumo-previo-sintetico", operation_bounds=bounds,
            rate_limits={operation: ApolloRateLimit(per_minute=1000, per_hour=10000, per_day=100000)
                         for operation in operations},
        ))
        grants.extend(SpendingAuthorization(
            provider=provider, operation=operation, account_ref=account, max_cost_usd=Decimal("0"),
            max_credits=Decimal("20"), responsible="Responsable sintético",
            source_reference="fixture:permiso-sintetico; no autoriza APIs reales", authorized_at=approved_at,
        ) for operation in operations)
    approval = BenchmarkApproval(
        benchmark_id=manifest.benchmark_id, manifest_sha256=manifest_digest(manifest), session_id=uuid4(),
        responsible="Responsable sintético", approved_at=approved_at, approvals=grants,
    )
    return manifest, access, approval


class FixtureTransport:
    """Devuelve respuestas del contrato de proveedor; nunca abre sockets ni lee credenciales."""

    synthetic = True

    def __init__(self):
        self.snov_authenticated = False
        self.calls = []
        self.tasks = {}

    @staticmethod
    def _response(data):
        return HttpResponse(status=200, headers={"Content-Type": "application/json"},
                            body=json.dumps(data, ensure_ascii=False).encode("utf-8"))

    @staticmethod
    def _person(company_index, person_index):
        person = dict(PEOPLE[person_index])
        company = COMPANIES[company_index]
        person.update(id=f"fixture_{company_index}_{person_index}", company=company,
                      email=f"persona{person_index}@{company['domain']}")
        return person

    def send(self, spec, *, timeout_seconds, max_bytes=1024 * 1024):
        self.calls.append((spec.provider, spec.operation, spec.path))
        if spec.provider == "apollo":
            payload = spec.payload or {}
            if spec.operation == "people_search":
                domain = payload["q_organization_domains_list"][0]
                index = next(i for i, item in enumerate(COMPANIES) if item["domain"] == domain)
                people = [self._person(index, i) for i in range(len(PEOPLE))]
                return self._response({"total_entries": len(people), "people": [
                    {"id": person["id"], "first_name": person["first_name"],
                     "last_name_obfuscated": person["last_name"][:3] + "***",
                     "title": person["title"], "has_email": True,
                     "organization": {"id": f"fixture_org_{index}", "name": COMPANIES[index]["name"],
                                      "primary_domain": domain}}
                    for person in people]})
            if spec.operation == "people_enrichment":
                _, company_index, person_index = payload["id"].split("_")
                index, person_index = int(company_index), int(person_index)
                person = self._person(index, person_index)
                organization_id = f"fixture_org_{index}"
                return self._response({"person": {
                    "id": person["id"], "first_name": person["first_name"], "last_name": person["last_name"],
                    "name": f"{person['first_name']} {person['last_name']}", "title": person["title"],
                    "email": person["email"], "email_status": "verified" if person["email_status"] == "valid" else "unknown",
                    "organization_id": organization_id,
                    "organization": {"id": organization_id, "name": person["company"]["name"],
                                     "primary_domain": person["company"]["domain"]},
                    "employment_history": [{"current": True, "organization_id": organization_id,
                                            "organization_name": person["company"]["name"], "title": person["title"]}],
                    "match_confidence": "high",
                }})
        if spec.provider == "snov":
            if spec.operation == "oauth":
                self.snov_authenticated = True
                return self._response({"access_token": "token-sintetico", "token_type": "Bearer", "expires_in": 3600})
            if not self.snov_authenticated:
                raise AssertionError("El escenario sintético también requiere OAuth reservado.")
            if spec.operation == "people_search":
                name = spec.payload["filters"]["company"]["name"]["include"][0]
                index = next(i for i, item in enumerate(COMPANIES) if item["name"] == name)
                task = f"search_{index}"
                self.tasks[task] = index
                return self._response({"data": [], "meta": {"task_hash": task, "page": 1},
                                       "links": {"result": f"https://api.snov.io/v2/database-search/prospects/result/{task}"}})
            if spec.operation == "people_search_result":
                index = self.tasks[spec.path.rsplit("/", 1)[-1]]
                return self._response({"data": {"total": len(PEOPLE), "page": 1, "total_pages": 1, "prospects": [
                    {"first_name": person["first_name"], "last_name": person["last_name"][:3] + "***", "job_title": person["title"],
                     "company": {"name": COMPANIES[index]["name"], "domain": COMPANIES[index]["domain"]},
                     "email_and_hidden_info_reveal": (
                         f"https://api.snov.io/v2/database-search/prospects/search-emails/start/fixture_{index}_{i}")}
                    for i, person in enumerate(PEOPLE)]}, "status": "completed", "links": []})
            if spec.operation == "people_enrichment":
                identifier = spec.path.rsplit("/", 1)[-1]
                task = f"enrich_{identifier}"
                self.tasks[task] = identifier
                return self._response({"data": [], "meta": {"task_hash": task},
                    "links": {"result": f"https://api.snov.io/v2/database-search/prospects/search-emails/result/{task}"}})
            if spec.operation == "people_enrichment_result":
                identifier = self.tasks[spec.path.rsplit("/", 1)[-1]]
                _, company_index, person_index = identifier.split("_")
                person = self._person(int(company_index), int(person_index))
                return self._response({"data": {"first_name": person["first_name"], "last_name": person["last_name"],
                    "searching_date": "2026-11-08 12:00:00",
                    "emails": [{"email": person["email"], "smtp_status": person["email_status"]}]},
                    "meta": {"task_hash": spec.path.rsplit("/", 1)[-1]}, "links": [], "status": "completed"})
        raise AssertionError(f"Solicitud fuera del escenario sintético: {spec.provider}/{spec.operation}")


def run_fixtures(output):
    from .pipeline import run_benchmark

    manifest, access, approval = build_fixture_inputs()
    return run_benchmark(manifest, access, approval, output, live=False, transport=FixtureTransport())
