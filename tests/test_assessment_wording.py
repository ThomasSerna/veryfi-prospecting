"""Revisión editorial de una ficha sintética con transporte simulado."""

import json

import pytest

from prospecting.pipeline.qualification import WORDING_VERSION, request_wording, save_wording
from prospecting.qualification import QualificationError
from test_qualification import ACCOUNT, claude, message, scenario


def draft(case, original, **overrides):
    reply = {
        "explanation": "Empresa Uno permite subir recibos de gastos.",
        "uncertainties": ["Cuántos recibos suben los usuarios"],
        "justifications": {name: "Motivo sintético revisado." for name in original.criteria},
    }
    case.reply = message(json.dumps(reply | overrides))
    return request_wording(case.db, case.budget, case.client, original, account_ref=ACCOUNT,
                           funding_source="prepaid", authorization=case.grant)


def test_reviewed_wording_preserves_assessment_sources_and_terminal_status(claude):
    original = claude.db.get_assessment(claude.qualify().assessment_id)
    before = claude.db.get_run_item(original.campaign_id, original.company_id)
    before = claude.db.save_run_item(before.model_copy(update={"stop_reason": "max_effort"}))
    wording, call = draft(claude, original)
    assert len(claude.requests) == 2 and claude.db.get_usage(call.request_id).status == "succeeded"
    assert claude.db.get_run_item(original.campaign_id, original.company_id) == before
    revision = save_wording(claude.db, original, wording, model_id=call.model)
    assert revision.revision_of == original.id and revision.id != original.id
    assert revision.prompt_version == WORDING_VERSION and revision.model_id == call.model
    assert revision.explanation == wording.explanation + " Información pendiente: Cuántos recibos suben los usuarios."
    metadata = {"id", "created_at", "revision_of", "model_id", "prompt_version", "explanation"}
    metadata = {key: True for key in metadata} | {"criteria": {"__all__": {"justification"}}}
    assert revision.model_dump(exclude=metadata) == original.model_dump(exclude=metadata)
    assert {key: item.justification for key, item in revision.criteria.items()} == wording.justifications
    current = claude.db.get_run_item(original.campaign_id, original.company_id)
    assert current.last_assessment_id == revision.id
    assert current.model_dump(exclude={"updated_at", "last_assessment_id"}) == before.model_dump(
        exclude={"updated_at", "last_assessment_id"})
    with pytest.raises(ValueError, match="vigente"):
        save_wording(claude.db, original, wording, model_id=call.model)
    assert claude.db.list_assessments(original.campaign_id, original.company_id) == [original, revision]


@pytest.mark.parametrize("incomplete", [{"uncertainties": []}, {"justifications": {}}, {"fit_score": 100}])
def test_invalid_wording_never_changes_selected_assessment(claude, incomplete):
    original = claude.db.get_assessment(claude.qualify().assessment_id)
    with pytest.raises(QualificationError):
        draft(claude, original, **incomplete)
    assert claude.db.list_assessments(original.campaign_id, original.company_id) == [original]
    assert claude.db.get_run_item(original.campaign_id, original.company_id).last_assessment_id == original.id
