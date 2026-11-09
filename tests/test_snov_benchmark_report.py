"""Comparación sintética y neutral; las fechas de consulta no verifican empleo ni correo."""

from datetime import timedelta
from decimal import Decimal

import pytest

from experiments.snov_benchmark.contracts import BenchmarkCapture, BenchmarkManifest, BenchmarkPerson, manifest_digest
from experiments.snov_benchmark.fixtures import FixtureTransport, build_fixture_inputs
from experiments.snov_benchmark.report import report_capture
from prospecting.models import utc_now


def person(company, **changes):
    values = {"id": "synthetic-person", "first_name": "Ana", "last_name": "Sintética", "title": "CTO",
              "domain": company.domain, "email": f"ana@{company.domain}", "email_status": "valid",
              "retrieved_at": utc_now() - timedelta(milliseconds=10), "source_reference": "fixture:persona",
              "enriched": True}
    values.update(changes)
    return BenchmarkPerson(**values)


def capture(manifest, provider, company, candidates=(), requests=(), status="completed"):
    return BenchmarkCapture(benchmark_id=manifest.benchmark_id, manifest_sha256=manifest_digest(manifest),
                            provider=provider, company_id=company.company_id, origin=manifest.origin,
                            observed_at=utc_now(), candidates=list(candidates), requests=list(requests), status=status)


def test_same_evidence_and_missing_verification_date_apply_to_both_providers():
    manifest, _, _ = build_fixture_inputs()
    captures = [capture(manifest, provider, company, [person(company)])
                for company in manifest.companies for provider in ("apollo", "snov")]
    report = report_capture(manifest, captures)
    assert report["comparison_complete"] is True
    for metrics in report["providers"].values():
        assert metrics["found"] == metrics["enriched"] == metrics["full_names"] == 2
        assert metrics["employment_evidenced"] == metrics["professional_valid_email"] == 2
        assert metrics["usable_channel"] == metrics["useful_contacts"] == 0
        assert metrics["cost_per_useful_contact_usd"] is None
        assert metrics["denominators"]["companies"] == 2


def test_only_explicit_fresh_email_date_enables_useful_contact_and_unknown_cost_stays_null():
    manifest, _, _ = build_fixture_inputs()
    company = manifest.companies[0]
    row = person(company, email_verified_at=utc_now() - timedelta(days=1))
    requests = [{"outcome": "succeeded", "elapsed_seconds": 1.5, "credits": "1", "final_cost_usd": None}]
    result = report_capture(manifest, [capture(manifest, "snov", company, [row], requests)])["providers"]["snov"]
    assert result["useful_contacts"] == result["usable_channel"] == 1
    assert result["credits"] == "1"
    assert result["final_cost_usd"] is result["cost_per_useful_contact_usd"] is None
    assert result["elapsed_seconds"] == 1.5


@pytest.mark.parametrize("changes,expected", [
    ({"email_status": "unknown", "email_verified_at": utc_now() - timedelta(days=1)}, (1, 0, 0)),
    ({"last_name": "Sin***"}, (0, 0, 0)),
    ({"domain": "otra-fixture.example"}, (1, 0, 0)),
    ({"email": "info@finanzas-fixture.example"}, (1, 0, 0)),
    ({"email_verified_at": utc_now() - timedelta(days=31)}, (1, 0, 0)),
])
def test_pending_and_mismatched_data_never_becomes_useful(changes, expected):
    manifest, _, _ = build_fixture_inputs()
    company = manifest.companies[0]
    metrics = report_capture(manifest, [capture(manifest, "apollo", company, [person(company, **changes)])])["providers"]["apollo"]
    assert (metrics["full_names"], metrics["usable_channel"], metrics["useful_contacts"]) == expected


@pytest.mark.parametrize("evidence_change", [
    {"published_at": None},
    {"published_at": utc_now() - timedelta(days=31)},
    {"status": "ended"},
    {"status": "ambiguous"},
    {"source_url": "https://otra-fixture.example/equipo"},
    {"excerpt": "Directorio sin atribución nominal."},
    {"title": "Director de Ventas"},
])
def test_shared_corporate_evidence_needs_nominal_role_date_and_correct_source(evidence_change):
    manifest, _, _ = build_fixture_inputs()
    data = manifest.model_dump(mode="json")
    data["companies"][0]["evidence"][0].update({
        key: value.isoformat() if hasattr(value, "isoformat") else value for key, value in evidence_change.items()})
    manifest = BenchmarkManifest.model_validate(data)
    company = manifest.companies[0]
    metrics = report_capture(manifest, [capture(manifest, "snov", company, [person(company)])])["providers"]["snov"]
    assert metrics["employment_evidenced"] == metrics["useful_contacts"] == 0


def test_deduplication_and_function_aliases_do_not_inflate_diversity():
    manifest, _, _ = build_fixture_inputs()
    company = manifest.companies[0]
    people = [person(company), person(company, id="duplicate", title="Director de Tecnología"),
              person(company, id="another-person", first_name="Elena", last_name="Ejemplo", email=f"elena@{company.domain}")]
    metrics = report_capture(manifest, [capture(manifest, "apollo", company, people)])["providers"]["apollo"]
    assert metrics["found"] == 2
    assert metrics["duplicates"] == 1
    assert metrics["functions"] == ["technology"]
    assert metrics["functions_count"] == 1


@pytest.mark.parametrize("title", ["Assistant to CTO", "Asistente del CTO", "CTO Advisor", "Junior CTO", "CTO Assistant"])
def test_advisors_and_assistants_do_not_inherit_the_target_function(title):
    manifest, _, _ = build_fixture_inputs()
    company = manifest.companies[0]
    metrics = report_capture(manifest, [capture(manifest, "snov", company, [person(company, title=title)])])["providers"]["snov"]
    assert metrics["relevant"] == metrics["functions_count"] == metrics["useful_contacts"] == 0


def test_conflicting_names_on_one_email_are_pending_and_named_aliases_deduplicate_without_email():
    manifest, _, _ = build_fixture_inputs()
    company = manifest.companies[0]
    conflicting = [person(company), person(company, id="other", first_name="Elena", last_name="Ejemplo")]
    metrics = report_capture(manifest, [capture(manifest, "apollo", company, conflicting)])["providers"]["apollo"]
    assert metrics["found"] == metrics["identity_conflicts"] == 1
    assert metrics["professional_valid_email"] == metrics["employment_evidenced"] == metrics["useful_contacts"] == 0
    named = [person(company), person(company, id="no-email", email=None, email_status="missing")]
    metrics = report_capture(manifest, [capture(manifest, "snov", company, named)])["providers"]["snov"]
    assert metrics["found"] == 1
    assert metrics["duplicates"] == 1
    assert metrics["identity_conflicts"] == 0


def test_no_sample_or_useful_results_are_not_a_zero_cost_success():
    manifest, _, _ = build_fixture_inputs()
    report = report_capture(manifest, [])
    assert report["comparison_complete"] is False
    assert len(report["missing_captures"]) == 4
    assert report["providers"]["apollo"]["useful_contact_rate"] is None
    assert report["providers"]["snov"]["cost_per_useful_contact_usd"] is None


def test_report_rejects_foreign_origin_hash_and_repeated_arm():
    manifest, _, _ = build_fixture_inputs()
    row = capture(manifest, "apollo", manifest.companies[0])
    for changes in ({"origin": "real"}, {"manifest_sha256": "a" * 64}):
        with pytest.raises(ValueError, match="manifiesto"):
            report_capture(manifest, [row.model_copy(update=changes)])
    with pytest.raises(ValueError, match="una captura"):
        report_capture(manifest, [row, row])


def test_cost_denominators_and_request_failures_are_explicit():
    manifest, _, _ = build_fixture_inputs()
    company = manifest.companies[0]
    requests = [{"outcome": "succeeded", "elapsed_seconds": "0.2", "credits": "1", "final_cost_usd": "0.03"},
                {"outcome": "failed", "elapsed_seconds": "0.3", "credits": "0", "final_cost_usd": "0.01"}]
    row = person(company, email_verified_at=utc_now() - timedelta(days=1))
    metrics = report_capture(manifest, [capture(manifest, "snov", company, [row], requests)])["providers"]["snov"]
    assert Decimal(metrics["cost_per_useful_contact_usd"]) == Decimal("0.04")
    assert metrics["error_rate"] == 0.5
    assert metrics["denominators"]["requests"] == 2
    bad = capture(manifest, "snov", company, requests=[{"final_cost_usd": "-1"}])
    with pytest.raises(ValueError, match="no negativos"):
        report_capture(manifest, [bad])


def test_fixture_inputs_are_synthetic_and_transport_has_no_network_fallback():
    manifest, access, approval = build_fixture_inputs()
    assert manifest.origin == "synthetic"
    assert all(company.domain.endswith(".example") for company in manifest.companies)
    assert approval.manifest_sha256 == manifest_digest(manifest)
    assert all(item.prior_credits_used == 2 for item in access)
    assert all("sint" in item.source_reference for item in approval.approvals)
    transport = FixtureTransport()
    assert transport.synthetic is True
    assert transport.snov_authenticated is False
