"""Métricas T21 sobre expedientes exclusivamente sintéticos, sin proveedores."""

from datetime import timedelta
from decimal import Decimal
import json
from uuid import uuid4

import pytest

import evaluate_enterprise_pipeline as evaluation
from prospecting.contacts import load_contact_match
from prospecting.db import Database
from prospecting.models import Channel, CompanySize, Contact, Evidence, RoleTaxonomy, RunItem, Usage, utc_now
from prospecting.pipeline import CampaignReport, DiscoveryReport, read_campaign


@pytest.fixture
def captured(tmp_path, make_campaign, make_company, make_assessment):
    now = utc_now()
    campaign = make_campaign(status="completed")
    campaign.config_snapshot.people_provider = None
    company, facts = make_company(name="Cuenta Sintética Example", domain="example.com", identity_status="confirmed",
                                  operating_countries=["CO"], segments=["fintech_software"])
    assessment = make_assessment(campaign.id, company.id, priority="high", target_roles=["CTO"])
    contact_id = uuid4()
    corporate = Evidence(company_id=company.id, contact_id=contact_id, claim="Directorio sintético.",
        excerpt="Persona Sintética Lista, CTO de Cuenta Sintética Example.", url="https://example.com/team",
        retrieved_at=now, updated_at=now, kind="observed", source_type="primary")
    email = Evidence(company_id=company.id, contact_id=contact_id, claim="Hunter informa email persona-sintetica@example.com; estado=valid. Dato sintético.",
        provider="hunter", external_reference="synthetic:email", retrieved_at=now, kind="observed", source_type="provider")
    contact = Contact(id=contact_id, company_id=company.id, name="Persona Sintética Lista", title="CTO",
        name_complete=True, identity_status="confirmed", current_employment=True, relevant_function=True,
        provenance={key: [corporate.id] for key in ("name", "title", "relevant_function")},
        employment_evidence_ids=[corporate.id], channels=[Channel(contact_id=contact_id, type="email",
            value="persona-sintetica@example.com", evidence_ids=[email.id], provider_status="valid",
            normalized_status="verified", retrieved_at=now, verified_at=now, professional=True, direct=True)])
    path = tmp_path / "synthetic.sqlite3"
    with Database(path) as db:
        db.save_campaign(campaign)
        db.save_company(company, evidence=facts)
        db.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id))
        db.save_contact(contact, evidence=[corporate, email])
        db.save_assessment(assessment)
        db.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id,
            last_assessment_id=assessment.id, stage="completed", business_status="ready_preferred"))
    view = read_campaign(path, campaign.id)
    movement = Usage(campaign_id=campaign.id, company_id=company.id, provider="apollo", operation="people_enrichment",
        request_fingerprint="a" * 64, account_ref="cuenta-sintetica", status="reconciled", outcome="succeeded",
        reserved_cost_usd="0.01", reserved_credits="1", credits="1", estimated_cost_usd="0.01",
        final_cost_usd="0.01", outlay_usd="0", reconciled_at=now)
    report = CampaignReport(campaign_id=campaign.id, status="completed", exclusions_status="pending",
        discovery=DiscoveryReport(campaign_id=campaign.id, queries=[], raw_hits=3, candidates=2, discarded={},
                                  selected_company_ids=[company.id], combinations=[]))
    return evaluation.PipelineCapture(schema_version="pipeline_capture_v1", origin="synthetic", country="CO",
        segment="fintech_software", plan_sha256="b" * 64, started_at=now, evaluated_at=utc_now(),
        duration_seconds=3.0, status="complete", campaign_report=report, view=view, usage=[movement])


def save(tmp_path, name, capture):
    path = tmp_path / name
    evaluation.save_capture(path, capture)
    return path


def test_known_metrics_are_offline_aggregates_without_personal_data(tmp_path, captured, monkeypatch):
    path = save(tmp_path, "synthetic.json", captured)
    monkeypatch.setattr("sqlite3.connect", lambda *_args, **_kwargs: pytest.fail("Abrió SQLite."))
    monkeypatch.setattr("socket.socket.connect", lambda *_args: pytest.fail("Accedió a la red."))
    report = evaluation.report_captures([path])
    totals = report["totals"]
    assert totals["companies"] == totals["qualified"] == totals["candidates"] == 1
    assert totals["relevant"] == totals["employment_verified"] == totals["emails_usable"] == totals["ready"] == 1
    assert totals["contact_coverage"]["value"] == 1
    assert report["flow_cost_usd"] == report["cost_per_useful_contact_usd"] == "0.01"
    assert report["automatic_seconds"] == 3
    assert report["commercial_validation"] == "pending"
    assert report["real_coverage"] == "pending"
    assert report["totals"]["accepted_Veryfi"]["value"] is None
    public = json.dumps(report, ensure_ascii=False)
    assert "Persona Sintética Lista" not in public and "example.com" not in public
    assert "Cuenta Sintética" not in public
    assert evaluation.report_captures([path]) == report


def test_repeated_paths_do_not_duplicate_spend_people_or_time(tmp_path, captured):
    path = save(tmp_path, "synthetic.json", captured)
    report = evaluation.report_captures([path, path])
    assert report["totals"]["companies"] == report["totals"]["ready"] == 1
    assert report["operations"][0]["requests"] == 1
    assert report["flow_cost_usd"] == "0.01" and report["automatic_seconds"] == 3
    assert report["discovery"]["raw_hits"] == 3


def test_frozen_date_is_used_for_freshness_and_validated_without_channel_is_not_ready(tmp_path, captured):
    path = save(tmp_path, "fresh.json", captured)
    later = captured.model_copy(deep=True)
    later.attempt_id = uuid4()
    later.evaluated_at += timedelta(days=365)
    later.view.companies[0].contacts[0].contact.channels = []
    later_path = save(tmp_path, "stale.json", later)
    assert evaluation.report_captures([path])["totals"]["ready"] == 1
    stale = evaluation.report_captures([later_path])
    assert stale["totals"]["employment_verified"] == stale["totals"]["ready"] == 0
    assert stale["cost_per_useful_contact_usd"] is None
    no_channel = captured.model_copy(deep=True)
    no_channel.view.companies[0].contacts[0].contact.channels = []
    counts, _ = evaluation.company_metrics(no_channel.view.companies[0], no_channel.view.campaign, no_channel.evaluated_at)
    assert counts["employment_verified"] == 1 and counts["ready"] == 0


def test_match_replay_uses_the_view_functions_and_diversity_counts_only_pertinent_people(
        tmp_path, config, make_campaign, make_company, make_assessment, monkeypatch):
    """La función desempata igual que en la ficha aunque la identidad siga pendiente; la diversidad no la cuenta."""
    profile = next(item for item in config.profiles if item.id == "expense_reimbursement")
    common = {"profile_ids": [profile.id], "departments": ["Producto"], "excluded_titles": [], "seniorities": [],
              "function_terms": ["integración de APIs"], "source_reference": "Patrones sintéticos sin personas reales",
              "source_date": "2026-11-01", "validation_status": "pending"}
    taxonomy = RoleTaxonomy(version="role_taxonomy_v1", source_date="2026-11-01", validation_status="pending", families=[
        common | {"id": "product", "function_id": "product", "buying_role": "business_champion",
                  "titles_en": ["Head of Product"], "titles_es": ["Director de Producto"]},
        common | {"id": "engineering", "function_id": "engineering", "buying_role": "technical_champion",
                  "titles_en": ["Solutions Architect"], "titles_es": ["Arquitecto de Soluciones"]}])
    weights = load_contact_match(evaluation.ROOT / "config" / "contact_match_v2.json")
    campaign = make_campaign(status="completed", config_snapshot=config.model_copy(update={
        "people_provider": None, "role_taxonomy": taxonomy, "contact_match": weights}))
    company, facts = make_company(name="Cuenta Sintética Example", domain="example.com", identity_status="confirmed",
                                  operating_countries=["CO"], segments=["fintech_software"])
    now = utc_now()
    use_case = Evidence(company_id=company.id, claim="Caso de uso sintético", excerpt="La empresa gestiona recibos y reembolsos.",
                        url="https://example.com/producto", retrieved_at=now, kind="observed", source_type="primary")
    assessment = make_assessment(campaign.id, company.id, priority="high", profile_matches=[{
        "profile_id": profile.id, "citations": [{"evidence_id": use_case.id, "quote": use_case.excerpt}]}])
    path = tmp_path / "functions.sqlite3"
    with Database(path) as db:
        db.save_campaign(campaign)
        db.save_company(company, evidence=[*facts, use_case])
        db.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id))
        for title, identity in (("Head of Product", "confirmed"), ("Solutions Architect", "pending")):
            contact_id = uuid4()
            name = f"Persona Sintética {str(contact_id)[:8]}"
            fact = Evidence(company_id=company.id, contact_id=contact_id, kind="observed", source_type="primary",
                            url="https://example.com/equipo", retrieved_at=now, claim="Directorio sintético",
                            excerpt=f"{name} es {title} de {company.name}.")
            db.save_contact(Contact(id=contact_id, company_id=company.id, name=name, title=title, name_complete=True,
                                    current_employment=True, identity_status=identity,
                                    provenance={field: [fact.id] for field in ("name", "title")},
                                    employment_evidence_ids=[fact.id]), evidence=[fact])
        db.save_assessment(assessment)
        db.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id, last_assessment_id=assessment.id,
                                 stage="completed", business_status="qualified_no_contact"))
    result = read_campaign(path, campaign.id).companies[0]
    shown = {person.contact.id: person.function_id for person in result.contacts if person.function_id}
    assert sorted(shown.values()) == ["engineering", "product"]
    assert sorted(person.stage for person in result.contacts) == ["candidate", "relevant"]
    calls, rank = [], evaluation.rank_contact_matches
    monkeypatch.setattr(evaluation, "rank_contact_matches",
                        lambda entries, roles, **kwargs: calls.append(kwargs["function_ids"]) or rank(entries, roles, **kwargs))
    counts, _ = evaluation.company_metrics(result, campaign, now)
    assert calls == [shown, shown]
    assert counts["distinct_functions"] == 1 and counts["diverse_functions"] == 0


def test_provider_claim_does_not_become_employment_verified_or_ready(tmp_path, captured):
    result = captured.view.companies[0]
    person = result.contacts[0].contact
    provider = Evidence(company_id=result.company.id, contact_id=person.id, claim="Afirmación sintética de Apollo.",
        provider="apollo", external_reference="apollo_v1:synthetic:request#enrichment", retrieved_at=captured.started_at,
        kind="observed", source_type="provider")
    result.evidence.append(provider)
    person.employment_evidence_ids = [provider.id]
    path = save(tmp_path, "provider-only.json", captured)
    totals = evaluation.report_captures([path])["totals"]
    assert totals["employment_verified"] == totals["ready"] == 0
    assert totals["emails_usable"] == 1


def test_reconciliation_fills_unknowns_without_counting_request_twice(tmp_path, captured):
    before = captured.model_copy(deep=True)
    movement = before.usage[0]
    movement.status, movement.final_cost_usd, movement.credits, movement.reconciled_at = "succeeded", None, None, None
    after = captured.model_copy(deep=True)
    after.attempt_id = uuid4()
    after.evaluated_at += timedelta(seconds=1)
    after.campaign_report.discovery = None
    first, second = save(tmp_path, "before.json", before), save(tmp_path, "after.json", after)
    report = evaluation.report_captures([second, first])
    assert report["operations"][0]["requests"] == 1
    assert report["operations"][0]["credits_confirmed"] == "1"
    assert report["flow_cost_usd"] == "0.01" and report["automatic_seconds"] == 6
    assert report["discovery"]["raw_hits"] == 3
    after.usage[0].final_cost_usd = Decimal("0.02")
    # Un importe ya confirmado no puede sustituirse por otro, aunque la captura sea posterior.
    contradictory = captured.model_copy(deep=True)
    contradictory.attempt_id = uuid4()
    contradictory.evaluated_at += timedelta(seconds=2)
    contradictory.usage[0].final_cost_usd = Decimal("0.02")
    conflict = save(tmp_path, "conflict.json", contradictory)
    with pytest.raises(ValueError, match="contradictorios"):
        evaluation.report_captures([second, conflict])


def test_unknown_cost_is_null_and_known_empty_ledger_is_zero(tmp_path, captured):
    captured.usage[0].final_cost_usd = None
    captured.usage[0].estimated_cost_usd = None
    path = save(tmp_path, "unknown.json", captured)
    assert evaluation.report_captures([path])["flow_cost_usd"] is None
    captured.usage = []
    empty = save(tmp_path, "no-calls.json", captured)
    assert evaluation.report_captures([empty])["flow_cost_usd"] == "0"


def test_integrity_mixed_origins_and_raw_error_are_handled_safely(tmp_path, captured, monkeypatch):
    path = save(tmp_path, "synthetic.json", captured)
    corrupted = json.loads(path.read_text(encoding="utf-8"))
    corrupted["payload"]["duration_seconds"] = 1
    changed = tmp_path / "corrupted.json"
    changed.write_text(json.dumps(corrupted), encoding="utf-8")
    with pytest.raises(ValueError, match="huella"):
        evaluation.report_captures([changed])
    monkeypatch.setattr(evaluation, "DATA_ROOT", tmp_path)
    real = captured.model_copy(update={"origin": "saved_real", "hashes": evaluation.evaluation_hashes()})
    real_path = save(tmp_path, "real.json", real)
    with pytest.raises(ValueError, match="mezclan"):
        evaluation.report_captures([path, real_path])
    captured.errors = ["Persona Sintética Lista persona-sintetica@example.com"]
    captured.view.companies[0].run_item.stop_reason = "Error para persona-sintetica@example.com"
    secret = save(tmp_path, "private-error.json", captured)
    report = evaluation.report_captures([secret])
    assert report["stop_reasons"] == {"other": 1}
    assert "persona-sintetica@example.com" not in json.dumps(report)


def test_cli_report_writes_new_output_only(tmp_path, captured):
    path = save(tmp_path, "synthetic.json", captured)
    output = tmp_path / "report.json"
    assert evaluation.main(["report", str(path), "--output", str(output)]) == 0
    original = output.read_bytes()
    assert evaluation.main(["report", str(path), "--output", str(output)]) == 2
    assert output.read_bytes() == original


def test_review_time_means_and_sample_completeness_are_explicit(tmp_path, captured):
    company_id = captured.view.companies[0].company.id
    captured.reviews = [evaluation.CompanyReview(company_id=company_id, reference_type="academic", acceptance="accepted",
        reviewer="Revisor exclusivamente sintético", organization="Equipo sintético", source_reference="Prueba sintética",
        reviewed_at=captured.evaluated_at, review_seconds=12)]
    captured.view.campaign.status = "partial"
    path = save(tmp_path, "reviewed.json", captured)
    report = evaluation.report_captures([path, path])
    assert report["review_seconds"] == 12
    assert report["totals"]["accepted_academic"]["value"] == 1
    assert report["totals"]["accepted_Veryfi"]["value"] is None
    assert report["totals"]["relevant_per_company"] == {"numerator": 1, "denominator": 1, "value": 1}
    assert report["totals"]["ready_per_company"]["value"] == 1
    assert report["sample"]["target_companies"] == 20 and report["sample"]["complete"] is False
    assert report["sample"]["observed_companies"] == 1
    assert report["campaign_statuses"] == {"partial": 1}


@pytest.mark.parametrize("problem", ["group", "pending_identity", "contradiction", "future", "secondary"])
def test_size_requires_same_scope_identity_and_observed_uncontested_sources(captured, problem):
    result = captured.view.companies[0]
    source = result.evidence[0]
    result.company.size = CompanySize(original_value="300 empleados, ejemplo sintético", employee_count=300,
                                     scope="entity", evidence_ids=[source.id])
    assert evaluation.company_metrics(result, captured.view.campaign, captured.evaluated_at)[1] == "large"
    if problem == "group":
        result.company.size.scope = "group"
    elif problem == "pending_identity":
        result.company.identity_status = "pending"
    elif problem == "contradiction":
        source.contradiction_ids = [uuid4()]
    elif problem == "future":
        source.retrieved_at = captured.evaluated_at + timedelta(seconds=1)
    else:
        source.source_type = "secondary"
    assert evaluation.company_metrics(result, captured.view.campaign, captured.evaluated_at)[1] == "unknown"
