"""Perfiles de T15 con evidencia y respuestas sintéticas, sin red."""

import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

import evaluate_qualification as evaluation
from prospecting.models import Evidence, RunItem, Segment
from prospecting.qualification import (
    PROFILE_PROMPT_VERSION, QualificationError, build_haiku_request, parse_output,
    prompt_version_for, validate_output,
)
from test_qualification import claude, message, output, scenario, search_hit


def with_taxonomy(case, role_config):
    campaign = case.campaign.model_copy(update={"config_snapshot": role_config})
    company = case.company.model_copy(update={"segments": [Segment.FINTECH_SOFTWARE]})
    return SimpleNamespace(**(vars(case) | {"campaign": campaign, "company": company}))


def profile_output(case, *, profile_id="expense_reimbursement", citations=None, **overrides):
    matches = [{"profile_id": profile_id, "citations": citations if citations is not None else [
        {"evidence_id": str(case.primary.id), "quote": case.primary.excerpt},
    ]}]
    return output(case, profile_matches=matches, **overrides)


def test_v5_requires_cited_profiles_and_keeps_shared_products_separate(scenario, role_config):
    case = with_taxonomy(scenario, role_config)
    payload, supplied = build_haiku_request(case.company, [case.primary], case.campaign)
    schema = payload["output_config"]["format"]["schema"]
    assert "profile_matches" in schema["required"]
    assert "expense_reimbursement" in payload["system"] and "payments_ap_erp" in payload["system"]
    assert "haiku_assessment_v5" in payload["system"]
    parsed = parse_output(profile_output(case), "end_turn", campaign=case.campaign)
    result = validate_output(parsed, supplied, case.campaign, company=case.company)
    assert result["document_need"].value == 1
    assert [match.profile_id for match in parsed.profile_matches] == ["expense_reimbursement"]
    assert parsed.products == ["document_ocr_api"]
    assert prompt_version_for("rubric_v1", role_taxonomy=True) == PROFILE_PROMPT_VERSION
    assert prompt_version_for("rubric_v2", role_taxonomy=True) == PROFILE_PROMPT_VERSION


def test_v5_accepts_no_backed_profile_without_inventing_one_from_product(scenario, role_config):
    case = with_taxonomy(scenario, role_config)
    parsed = parse_output(output(case, profile_matches=[]), "end_turn", campaign=case.campaign)
    validate_output(parsed, [case.primary], case.campaign, company=case.company)
    assert parsed.profile_matches == []
    with pytest.raises(QualificationError, match="contrato"):
        parse_output(output(case), "end_turn", campaign=case.campaign)


@pytest.mark.parametrize("profile_id", ["perfil-inventado", "cpg_brands"])
def test_v5_rejects_profiles_outside_company_and_campaign(scenario, role_config, profile_id):
    case = with_taxonomy(scenario, role_config)
    parsed = parse_output(profile_output(case, profile_id=profile_id), "end_turn", campaign=case.campaign)
    with pytest.raises(QualificationError) as error:
        validate_output(parsed, [case.primary], case.campaign, company=case.company)
    assert error.value.code == "unknown_profile"


@pytest.mark.parametrize(("source_changes", "quote", "reason"), [
    ({}, "Cita que nadie publicó.", "unsupported_quote"),
    ({"company_id": uuid4()}, None, "unsupported_profile"),
    ({"contact_id": uuid4()}, None, "unsupported_profile"),
    ({"kind": "inference"}, None, "unsupported_profile"),
    ({"external_reference": "contacts_search:sintetico"}, None, "unsupported_profile"),
    ({"contradiction_ids": [uuid4()]}, None, "contradicted_profile"),
])
def test_v5_rejects_unbacked_profile_citations(scenario, role_config, source_changes, quote, reason):
    case = with_taxonomy(scenario, role_config)
    source = case.primary.model_copy(update=source_changes)
    parsed = parse_output(profile_output(case, citations=[{
        "evidence_id": str(source.id), "quote": quote or source.excerpt,
    }]), "end_turn", campaign=case.campaign)
    with pytest.raises(QualificationError) as error:
        validate_output(parsed, [source], case.campaign, company=case.company)
    assert error.value.code == reason


def test_v5_rejects_unknown_search_and_inbound_contradictions(scenario, role_config):
    case = with_taxonomy(scenario, role_config)
    parsed = parse_output(profile_output(case, citations=[{
        "evidence_id": str(uuid4()), "quote": case.primary.excerpt,
    }]), "end_turn", campaign=case.campaign)
    with pytest.raises(QualificationError) as error:
        validate_output(parsed, [case.primary], case.campaign, company=case.company)
    assert error.value.code == "unknown_evidence"
    hit = search_hit(case)
    parsed = parse_output(profile_output(case, citations=[{
        "evidence_id": str(hit.id), "quote": hit.excerpt,
    }]), "end_turn", campaign=case.campaign)
    with pytest.raises(QualificationError) as error:
        validate_output(parsed, [case.primary, hit], case.campaign, company=case.company)
    assert error.value.code == "unsupported_profile"
    conflict = case.primary.model_copy(update={"id": uuid4(), "contradiction_ids": [case.primary.id]})
    parsed = parse_output(profile_output(case), "end_turn", campaign=case.campaign)
    with pytest.raises(QualificationError) as error:
        validate_output(parsed, [case.primary], case.campaign, company=case.company,
                        all_evidence=[case.primary, conflict])
    assert error.value.code == "contradicted_profile"


def test_v5_keeps_dense_evidence_inside_existing_token_budget(scenario, role_config):
    case = with_taxonomy(scenario, role_config)
    facts = [case.primary.model_copy(update={"id": uuid4(), "excerpt": "Texto sintético. " * 100})
             for _ in range(50)]
    payload, supplied = build_haiku_request(case.company, facts, case.campaign)
    size = len(payload["system"]) + len(payload["messages"][0]["content"]) + len(json.dumps(payload["output_config"]))
    assert 0 < len(supplied) < len(facts)
    assert size <= case.campaign.limits.llm.max_input_tokens * 2
    assert payload["max_tokens"] == case.campaign.limits.llm.max_output_tokens


def test_v5_pipeline_ignores_v3_cached_assessment_and_persists_citations(claude, role_config):
    original = claude.qualify()
    previous = claude.db.get_assessment(original.assessment_id)
    claude.campaign = claude.campaign.model_copy(update={"id": uuid4(), "config_snapshot": role_config})
    claude.db.save_campaign(claude.campaign)
    segment = Evidence(company_id=claude.company.id, claim="Segmento sintético FinTech/software.",
                       url="https://empresa-uno.example/perfil", retrieved_at=claude.primary.retrieved_at,
                       kind="observed", source_type="primary")
    claude.company = claude.company.model_copy(update={
        "segments": [Segment.FINTECH_SOFTWARE], "provenance": claude.company.provenance | {"segments": [segment.id]},
    })
    claude.db.save_company(claude.company, evidence=[segment])
    claude.db.save_run_item(RunItem(campaign_id=claude.campaign.id, company_id=claude.company.id,
                                  stage="identity_resolved"))
    old = previous.model_copy(update={"id": uuid4(), "campaign_id": claude.campaign.id})
    claude.db.save_assessment(old)
    claude.reply = message(profile_output(claude))
    report = claude.qualify()
    assert report.status == "assessed" and len(claude.requests) == 2
    saved = claude.db.get_assessment(report.assessment_id)
    assert saved.prompt_version == PROFILE_PROMPT_VERSION
    assert saved.revision_of == old.id
    assert saved.profile_matches[0].citations[0].evidence_id == claude.primary.id
    assert claude.qualify().status == "already_assessed" and len(claude.requests) == 2
    assert claude.db.get_assessment(previous.id) == previous
    _, supplied = build_haiku_request(claude.company, claude.db.list_evidence(claude.company.id), claude.campaign)
    snapshot = evaluation.Snapshot.model_validate({
        "schema_version": "evaluation_snapshot_v1", "origin": "synthetic",
        "campaign": claude.campaign.model_dump(mode="json"), "company": claude.company.model_dump(mode="json"),
        "evidence": [fact.model_dump(mode="json") for fact in claude.db.list_evidence(claude.company.id)],
        "selected_evidence_ids": [str(fact.id) for fact in supplied], "assessment": saved.model_dump(mode="json"),
    })
    case = SimpleNamespace(country="CO", segment="fintech_software")
    evaluation.validate_snapshot(snapshot, case, None)
    later_conflict = claude.primary.model_copy(update={
        "id": uuid4(), "retrieved_at": saved.created_at + timedelta(seconds=1),
        "contradiction_ids": [claude.primary.id],
    })
    snapshot = snapshot.model_copy(update={"evidence": [*snapshot.evidence, later_conflict]})
    evaluation.validate_snapshot(snapshot, case, None)
    broken = saved.model_dump(mode="json")
    broken["profile_matches"][0]["citations"][0]["quote"] = "Cita inventada en el artefacto."
    snapshot = snapshot.model_copy(update={"assessment": type(saved).model_validate(broken)})
    with pytest.raises(ValueError, match="perfiles o citas"):
        evaluation.validate_snapshot(snapshot, case, None)
