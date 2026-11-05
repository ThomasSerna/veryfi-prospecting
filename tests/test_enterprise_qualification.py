"""Rúbrica enterprise con empresas, fuentes y respuestas exclusivamente sintéticas."""

import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from prospecting.models import CompanySize, Evidence, RunItem
from prospecting.haiku import CHARS_PER_TOKEN
from prospecting.qualification import (
    ENTERPRISE_PROMPT_VERSION, PROMPT_VERSION, build_haiku_request, enterprise_employee_signal,
    enterprise_sort_key, prompt_version_for,
)
from test_qualification import RETRIEVED_AT, claude, criteria, decide, message, output, scenario


def sized_company(make_company, *, scope="entity", entity_type="legal_entity", **size_fields):
    company, _ = make_company(entity_type=entity_type, identity_status="confirmed")
    original = "Dato sintético de plantilla y ámbito."
    source = Evidence(company_id=company.id, claim=original, excerpt=original,
                      url="https://example.com/escala-sintetica", retrieved_at=RETRIEVED_AT,
                      kind="observed", source_type="primary")
    size = CompanySize(original_value=original, scope=scope, evidence_ids=[source.id], **size_fields)
    return company.model_copy(update={"size": size}), source


def test_v1_is_unchanged_and_v2_preserves_other_criteria_and_thresholds(config):
    old = config.rubrics["rubric_v1"].model_dump(mode="json")
    canonical = json.dumps(old, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert hashlib.sha256(canonical).hexdigest() == "0cb73e50d60a8acd85b4f8e57166bd0b31e7ba309f71127db283a5439d087a48"
    new = config.rubrics["rubric_v2"]
    assert [item.weight for item in new.criteria.values()] == [30, 20, 35, 10, 5]
    assert sum(item.weight for item in new.criteria.values()) == 100
    assert new.thresholds == config.rubrics["rubric_v1"].thresholds
    for name in ("document_need", "offer_match", "adoption_capacity", "opportunity_timing"):
        assert new.criteria[name].strong_signal == old["criteria"][name]["strong_signal"]
        assert new.criteria[name].partial_signal == old["criteria"][name]["partial_signal"]


@pytest.mark.parametrize(("values", "priority", "coverage"), [
    ((None, None, 1, None, None), "insufficient_evidence", 0.35),
    ((1, 1, None, None, None), "insufficient_evidence", 0.50),
    ((1, 1, None, 1, 1), "medium", 0.65),
    ((0.5, 1, 1, 1, 1), "medium", 1.0),
    ((1, 0.5, 1, 1, 0), "high", 1.0),
])
def test_v2_coverage_and_need_prevent_priority_from_size_alone(config, values, priority, coverage):
    result = decide(values, config.rubrics["rubric_v2"])
    assert result.priority == priority and result.coverage == pytest.approx(coverage)


def test_v2_zero_remains_known_while_null_removes_weight(config):
    rubric = config.rubrics["rubric_v2"]
    unknown = decide((1, 1, 1, 1, None), rubric)
    zero = decide((1, 1, 1, 1, 0), rubric)
    assert (unknown.fit_score, unknown.coverage) == (100, 0.95)
    assert (zero.fit_score, zero.coverage) == (95, 1.0)


@pytest.mark.parametrize(("fields", "expected"), [
    ({"employee_count": 49}, None),
    ({"employee_count": 50}, 0.5),
    ({"employee_count": 249}, 0.5),
    ({"employee_count": 250}, 1),
    ({"employee_min": 50, "employee_max": 249}, 0.5),
    ({"employee_min": 200, "employee_max": 500}, None),
    ({"employee_min": 250}, 1),
    ({"employee_min": 100}, None),
    ({"employee_max": 249}, None),
    ({}, None),
])
def test_employee_signal_uses_only_unambiguous_limits(make_company, fields, expected):
    company, source = sized_company(make_company, **fields)
    assert enterprise_employee_signal(company, [source]) == expected


@pytest.mark.parametrize(("scope", "entity_type", "expected"), [
    ("entity", "legal_entity", 1),
    ("country", "legal_entity", 1),
    ("subsidiary", "subsidiary", 1),
    ("subsidiary", "brand", None),
    ("group", "legal_entity", None),
    ("group", "subsidiary", None),
    ("group", "brand", None),
    ("group", "unknown", None),
    ("unknown", "legal_entity", None),
])
def test_employee_signal_never_lends_group_size_to_a_subsidiary(make_company, scope, entity_type, expected):
    company, source = sized_company(make_company, scope=scope, entity_type=entity_type, employee_count=1000)
    assert enterprise_employee_signal(company, [source]) == expected
    if scope == "group":
        company = company.model_copy(update={"parent_company_id": uuid4()})
        assert enterprise_employee_signal(company, [source]) is None


def test_employee_signal_requires_present_observed_sources_without_contradictions(make_company):
    company, source = sized_company(make_company, employee_count=250)
    assert enterprise_employee_signal(company, []) is None
    for change in ({"kind": "inference"}, {"source_type": "secondary"},
                   {"company_id": uuid4()}, {"contradiction_ids": [uuid4()]}):
        assert enterprise_employee_signal(company, [source.model_copy(update=change)]) is None
    assert enterprise_employee_signal(company.model_copy(update={"identity_status": "pending"}), [source]) is None
    conflict = source.model_copy(update={"id": uuid4(), "contradiction_ids": [source.id]})
    assert enterprise_employee_signal(company, [source, conflict]) is None


def test_v4_adds_scale_context_without_changing_v3(make_company, make_campaign):
    company, source = sized_company(make_company, employee_count=250, public_revenue="USD 10 millones")
    first, _ = build_haiku_request(company, [source], make_campaign())
    new_campaign = make_campaign(rubric_version="rubric_v2")
    second, selected = build_haiku_request(company, [source], new_campaign)
    assert source in selected
    assert '"employee_signal": 1.0' in second["messages"][0]["content"]
    assert '"scope": "entity"' in second["messages"][0]["content"]
    assert "employee_signal" not in first["messages"][0]["content"]
    assert "haiku_assessment_v4" not in first["system"]
    assert "menos de 50 empleados Y evidencia explícita" in second["system"]
    assert "financiación queda como contexto y no puntúa" in second["system"]
    assert "No infieras equivalencias monetarias" in second["system"]
    assert "niveles distintos no son por sí solos una contradicción" in second["system"]
    assert prompt_version_for("rubric_v1") == PROMPT_VERSION == "haiku_assessment_v3"
    assert prompt_version_for("rubric_v2") == ENTERPRISE_PROMPT_VERSION == "haiku_assessment_v4"


def test_v4_keeps_group_context_but_not_its_employee_signal(make_company, make_campaign):
    company, source = sized_company(make_company, scope="group", entity_type="subsidiary", employee_count=1000)
    payload, _ = build_haiku_request(company, [source], make_campaign(rubric_version="rubric_v2"))
    profile = payload["messages"][0]["content"].split("<evidencia>")[0]
    assert '"scope": "group"' in profile
    assert '"size_scope_applies": false' in profile and '"employee_signal": null' in profile


def test_v4_drops_structured_size_when_its_source_is_not_supplied(make_company, make_campaign):
    company, _ = sized_company(make_company, employee_count=1000)
    payload, _ = build_haiku_request(company, [], make_campaign(rubric_version="rubric_v2"))
    profile = payload["messages"][0]["content"].split("<evidencia>")[0]
    assert '"size": null' in profile and "employee_count" not in profile


def test_v4_request_bounds_dense_evidence_and_scale_context(make_company, make_campaign):
    company, source = sized_company(make_company, employee_count=250, public_revenue="USD 100 millones")
    company = company.model_copy(update={"size": company.size.model_copy(update={
        "original_value": "Dato sintético muy extenso. " * 1000,
        "geographic_coverage": "Cobertura sintética extensa. " * 1000,
    })})
    facts = [source, *[source.model_copy(update={"id": uuid4(), "excerpt": "Texto sintético. " * 200})
                      for _ in range(40)]]
    campaign = make_campaign(rubric_version="rubric_v2")
    payload, selected = build_haiku_request(company, facts, campaign)
    assert len(selected) < len(facts)
    size = (len(payload["system"]) + len(payload["messages"][0]["content"])
            + len(json.dumps(payload["output_config"]["format"]["schema"], ensure_ascii=False)))
    assert size <= campaign.limits.llm.max_input_tokens * CHARS_PER_TOKEN
    assert size / 2.11 <= campaign.limits.llm.max_input_tokens


def test_v4_drops_size_when_source_does_not_fit_the_request(make_company, make_campaign, monkeypatch):
    company, source = sized_company(make_company, employee_count=1000)
    monkeypatch.setattr("prospecting.qualification.select_evidence", lambda evidence, available: [])
    payload, selected = build_haiku_request(company, [source], make_campaign(rubric_version="rubric_v2"))
    profile = payload["messages"][0]["content"].split("<evidencia>")[0]
    assert selected == [] and '"size": null' in profile and "employee_count" not in profile


def test_v4_does_not_restore_size_by_dropping_a_conflicting_source(make_company, make_campaign, monkeypatch):
    company, source = sized_company(make_company, employee_count=1000)
    conflict = source.model_copy(update={"id": uuid4(), "contradiction_ids": [source.id]})
    monkeypatch.setattr("prospecting.qualification.select_evidence", lambda evidence, available: [source])
    payload, _ = build_haiku_request(company, [source, conflict], make_campaign(rubric_version="rubric_v2"))
    profile = payload["messages"][0]["content"].split("<evidencia>")[0]
    assert '"size": null' in profile and '"employee_signal": null' in profile


def test_v2_need_precedes_score_only_inside_the_same_priority(make_company):
    company, _ = make_company()
    partial = SimpleNamespace(priority="medium", fit_score=65, criteria=criteria(0.5, 0.5, 1, 0.5, 0))
    clear = SimpleNamespace(priority="medium", fit_score=62.5, criteria=criteria(1, 0.5, 0.5, 0.5, 0))
    high = SimpleNamespace(priority="high", fit_score=75, criteria=criteria(1, 0.5, 1, 0.5, 0))
    assert enterprise_sort_key(company, clear) < enterprise_sort_key(company, partial)
    assert enterprise_sort_key(company, high) < enterprise_sort_key(company, clear)
    assert enterprise_sort_key(company, None)[0] == 3


def test_v2_pipeline_uses_v4_and_preserves_reuse_of_v1(claude):
    first = claude.qualify()
    old_campaign = claude.campaign
    old_assessment = claude.db.get_assessment(first.assessment_id)
    claude.campaign = old_campaign.model_copy(update={"id": uuid4(), "rubric_version": "rubric_v2"})
    claude.db.save_campaign(claude.campaign)
    claude.db.save_run_item(RunItem(campaign_id=claude.campaign.id, company_id=claude.company.id,
                                  stage="identity_resolved"))
    claude.reply = message(output(claude, values=(1, 1, None, 1, 1)))
    current = claude.qualify()
    assert current.status == "assessed" and current.priority == "medium"
    assert claude.db.get_assessment(current.assessment_id).prompt_version == ENTERPRISE_PROMPT_VERSION
    assert claude.qualify().status == "already_assessed" and len(claude.requests) == 2
    claude.campaign = old_campaign
    assert claude.qualify().assessment_id == first.assessment_id and len(claude.requests) == 2
    assert claude.db.get_assessment(first.assessment_id) == old_assessment
