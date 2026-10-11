"""Persistencia y recuperación sin red, con datos exclusivamente sintéticos."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest

from prospecting.db import Database
from prospecting.models import (
    BusinessStatus, CampaignStatus, ChannelStatus, ConsumedLimits, Evidence,
    RunItem, RunStage, TokenUsage, UsageStatus,
)


def test_complete_graph_roundtrip(database, records, persist_records):
    saved = persist_records(database, records)

    assert database.get_campaign(saved.campaign.id) == saved.campaign
    assert database.get_company(saved.company.id) == saved.company
    assert database.get_contact(saved.contact.id) == saved.contact
    assert database.get_assessment(saved.assessment.id) == saved.assessment
    assert database.get_usage(saved.usage.request_id) == saved.usage
    assert database.get_run_item(saved.campaign.id, saved.company.id) == saved.run_item
    assert database.list_campaigns() == [saved.campaign]
    assert database.list_contacts(saved.company.id) == [saved.contact]
    assert database.list_assessments(saved.campaign.id, saved.company.id) == [saved.assessment]
    assert database.list_run_items(saved.campaign.id) == [saved.run_item]
    assert database.list_usage(campaign_id=saved.campaign.id) == [saved.usage]
    assert database.list_usage(company_id=saved.company.id, provider="synthetic") == [saved.usage]
    assert database.list_usage(provider="unavailable-synthetic") == []
    facts = saved.company_evidence + saved.contact_evidence
    assert {fact.id for fact in database.list_evidence(saved.company.id)} == {
        fact.id for fact in facts
    }
    assert {fact.id for fact in database.list_evidence(
        saved.company.id, contact_id=saved.contact.id
    )} == {fact.id for fact in saved.contact_evidence}


def test_unknown_values_and_negative_values_remain_distinct(
    database, records, persist_records, make_assessment
):
    persist_records(database, records)
    unknown = database.get_assessment(records.assessment.id)
    assert unknown.fit_score is None
    assert unknown.coverage == 0
    assert unknown.criteria["scale_potential"].value is None
    assert database.get_company(records.company.id).operating_countries is None
    assert database.get_usage(records.usage.request_id).final_cost_usd is None
    negative = make_assessment(records.campaign.id, records.company.id)
    criterion = negative.criteria["scale_potential"].model_copy(
        update={
            "value": 0.0,
            "evidence_ids": [records.company_evidence[0].id],
            "justification": "Señal sintética explícitamente incompatible.",
        }
    )
    negative = negative.model_copy(update={
        "criteria": negative.criteria | {"scale_potential": criterion},
        "fit_score": 0.0,
        "coverage": 0.2,
    })
    database.save_assessment(negative)
    restored = database.get_assessment(negative.id)
    assert restored.fit_score == 0
    assert restored.criteria["scale_potential"].value == 0
    assert restored.criteria["document_need"].value is None
    assert len(database.list_assessments(records.campaign.id, records.company.id)) == 2


def test_shared_domain_does_not_merge_entities(database, make_company, make_campaign):
    first, first_facts = make_company(
        name="Matriz sintética A", domain="grupo-sintetico.example", entity_type="legal_entity",
        operating_countries=["CO", "MX"],
    )
    second, second_facts = make_company(
        name="Filial sintética B", domain="grupo-sintetico.example", entity_type="subsidiary",
        parent_company_id=first.id,
    )
    brand, brand_facts = make_company(
        name="Marca sintética C", domain="grupo-sintetico.example", entity_type="brand",
        parent_company_id=first.id,
    )
    database.save_company(first, evidence=first_facts)
    database.save_company(second, evidence=second_facts)
    database.save_company(brand, evidence=brand_facts)
    assert database.get_company(first.id).operating_countries == ["CO", "MX"]
    assert database.get_company(second.id).parent_company_id == first.id
    assert database.get_company(first.id).id != database.get_company(second.id).id
    assert database.get_company(brand.id).entity_type == "brand"
    for country in ("CO", "MX"):
        campaign = database.save_campaign(make_campaign(countries=[country]))
        item = RunItem(campaign_id=campaign.id, company_id=first.id)
        database.save_run_item(item)
        assert database.list_run_items(campaign.id) == [item]
        assert database.get_campaign(campaign.id).countries == [country]
    assert database.get_company(first.id) == first


def test_parent_cycle_rolls_back_company_update(database, make_company):
    parent, parent_facts = make_company()
    child, child_facts = make_company(parent_company_id=parent.id)
    database.save_company(parent, evidence=parent_facts)
    database.save_company(child, evidence=child_facts)
    cycle, cycle_facts = make_company(id=parent.id, parent_company_id=child.id)
    with pytest.raises(ValueError, match="ciclo"):
        database.save_company(cycle, evidence=cycle_facts)
    assert database.get_company(parent.id) == parent
    assert {fact.id for fact in database.list_evidence(parent.id)} == {fact.id for fact in parent_facts}


def test_false_professional_facts_stay_false(database, make_company, make_contact):
    company, company_facts = make_company()
    database.save_company(company, evidence=company_facts)
    contact, contact_facts = make_contact(
        company.id, name_complete=False, current_employment=False, relevant_function=False,
    )
    saved = database.save_contact(contact, evidence=contact_facts)
    assert saved.name_complete is False
    assert saved.current_employment is False
    assert saved.relevant_function is False
    assert saved.identity_status == "pending"


def test_known_empty_aliases_preserve_provenance(database, make_company):
    company, facts = make_company(aliases=[])
    saved = database.save_company(company, evidence=facts)
    assert saved.aliases == []
    assert saved.provenance["aliases"] == company.provenance["aliases"]


def test_duplicate_confirmed_identity_rolls_back_aggregate(database, make_company):
    first, first_facts = make_company(
        identity_status="confirmed", identity_key="synthetic:entity:one"
    )
    second, second_facts = make_company(
        identity_status="confirmed", identity_key="synthetic:entity:one"
    )
    database.save_company(first, evidence=first_facts)
    with pytest.raises(sqlite3.IntegrityError):
        database.save_company(second, evidence=second_facts)
    assert database.get_company(second.id) is None
    assert database.list_evidence(second.id) == []
    assert database.get_company(first.id) == first


@pytest.mark.parametrize("wrong_company", [False, True])
def test_assessment_rejects_missing_or_foreign_evidence(
    database, records, persist_records, make_company, make_assessment, wrong_company
):
    persist_records(database, records)
    evidence_id = uuid4()
    if wrong_company:
        other, facts = make_company()
        database.save_company(other, evidence=facts)
        evidence_id = facts[0].id
    assessment = make_assessment(records.campaign.id, records.company.id)
    criterion = assessment.criteria["document_need"].model_copy(
        update={"value": 0.0, "evidence_ids": [evidence_id]}
    )
    assessment = assessment.model_copy(update={
        "criteria": assessment.criteria | {"document_need": criterion}
    })
    with pytest.raises(ValueError):
        database.save_assessment(assessment)
    assert database.get_assessment(assessment.id) is None
    assert database.get_assessment(records.assessment.id) == records.assessment


def test_channel_cannot_borrow_another_company_source(
    database, records, persist_records, make_company
):
    persist_records(database, records)
    other, facts = make_company()
    database.save_company(other, evidence=facts)
    channel = records.contact.channels[0].model_copy(update={"evidence_ids": [facts[0].id]})
    invalid = records.contact.model_copy(update={"channels": [channel]})
    with pytest.raises(ValueError):
        database.save_contact(invalid)
    assert database.get_contact(records.contact.id) == records.contact


@pytest.mark.parametrize("change", [
    "remove", "unknown", "manual", "stale", "without_provider", "new_primary",
])
def test_negative_channel_verification_cannot_be_erased_or_overridden(
    database, records, persist_records, change
):
    persist_records(database, records)
    channel = records.contact.channels[0]
    negative_fact = Evidence(
        company_id=records.company.id,
        contact_id=records.contact.id,
        claim="El proveedor sintético informa que el correo es inválido.",
        provider="synthetic",
        external_reference="synthetic-invalid-channel",
        retrieved_at=channel.retrieved_at,
        kind="observed",
        source_type="provider",
    )
    invalid_channel = channel.model_copy(update={
        "normalized_status": ChannelStatus.INVALID,
        "provider_status": "synthetic_invalid",
        "evidence_ids": [negative_fact.id],
    })
    invalid_contact = database.save_contact(
        records.contact.model_copy(update={"channels": [invalid_channel]}),
        evidence=(negative_fact,),
    )
    changes = {"normalized_status": ChannelStatus.UNKNOWN}
    facts = ()
    if change == "manual":
        manual = negative_fact.model_copy(update={
            "id": uuid4(), "source_type": "manual",
            "claim": "Confirmación manual sintética; no verifica entregabilidad.",
        })
        facts = (manual,)
        changes = {
            "normalized_status": ChannelStatus.MANUAL_CONFIRMED,
            "manual_confirmed_at": channel.retrieved_at,
            "manual_confirmation_reason": "Revisión sintética nominal.",
            "evidence_ids": [negative_fact.id, manual.id],
        }
    elif change in ("stale", "without_provider"):
        changes = {
            "normalized_status": ChannelStatus.VERIFIED,
            "verified_at": channel.retrieved_at,
        }
        if change == "without_provider":
            changes.update({
                "verified_at": channel.retrieved_at + timedelta(seconds=1),
                "evidence_ids": channel.evidence_ids,
            })
    elif change == "new_primary":
        primary = Evidence(
            company_id=records.company.id,
            contact_id=records.contact.id,
            claim="Página sintética nueva que no verifica entregabilidad.",
            url="https://example.com/nueva-publicacion-sintetica",
            retrieved_at=channel.retrieved_at + timedelta(seconds=1),
            kind="observed",
            source_type="primary",
        )
        facts = (primary,)
        changes = {
            "normalized_status": ChannelStatus.VERIFIED,
            "provider_status": "synthetic_valid",
            "verified_at": primary.retrieved_at,
            "evidence_ids": [negative_fact.id, primary.id],
        }
    channels = [] if change == "remove" else [invalid_channel.model_copy(update=changes)]
    with pytest.raises(ValueError):
        database.save_contact(invalid_contact.model_copy(update={"channels": channels}), evidence=facts)
    assert database.get_contact(records.contact.id) == invalid_contact
    persisted_ids = {fact.id for fact in database.list_evidence(records.company.id)}
    assert all(fact.id not in persisted_ids for fact in facts)


def test_new_provider_observation_can_resolve_negative_verification(
    database, records, persist_records
):
    persist_records(database, records)
    channel = records.contact.channels[0]
    negative = channel.model_copy(update={"normalized_status": ChannelStatus.INVALID})
    database.save_contact(records.contact.model_copy(update={"channels": [negative]}))
    verified_at = channel.retrieved_at + timedelta(seconds=1)
    fact = Evidence(
        company_id=records.company.id,
        contact_id=records.contact.id,
        claim="Nueva verificación sintética válida del proveedor.",
        provider="synthetic",
        external_reference="synthetic-valid-channel",
        retrieved_at=verified_at,
        kind="observed",
        source_type="provider",
    )
    verified = channel.model_copy(update={
        "normalized_status": ChannelStatus.VERIFIED,
        "provider_status": "synthetic_valid",
        "verified_at": verified_at,
        "evidence_ids": channel.evidence_ids + [fact.id],
    })
    saved = database.save_contact(
        records.contact.model_copy(update={"channels": [verified]}), evidence=(fact,)
    )
    assert saved.channels[0].normalized_status == ChannelStatus.VERIFIED
    assert saved.channels[0].evidence_ids == verified.evidence_ids


@pytest.mark.parametrize("source_type", ["manual", "primary"])
def test_manual_and_published_channels_require_the_matching_source_type(
    database, records, persist_records, source_type
):
    persist_records(database, records)
    channel = records.contact.channels[0]
    source = records.contact_evidence[-1].model_copy(update={
        "id": uuid4(), "source_type": "secondary",
        "claim": "Referencia sintética secundaria que no confirma un canal.",
    })
    if source_type == "manual":
        changes = {
            "normalized_status": ChannelStatus.MANUAL_CONFIRMED,
            "manual_confirmed_at": channel.retrieved_at,
            "manual_confirmation_reason": "Revisión sintética.",
            "evidence_ids": [source.id],
        }
    else:
        changes = {
            "normalized_status": ChannelStatus.PUBLISHED_PROFESSIONAL,
            "published_evidence_ids": [source.id],
            "evidence_ids": [source.id],
        }
    candidate = records.contact.model_copy(update={"channels": [channel.model_copy(update=changes)]})
    with pytest.raises(ValueError):
        database.save_contact(candidate, evidence=(source,))
    valid_source = source.model_copy(update={"source_type": source_type})
    saved = database.save_contact(candidate, evidence=(valid_source,))
    assert saved.channels[0].normalized_status == changes["normalized_status"]


def test_evidence_contact_must_belong_to_its_company(
    database, records, persist_records, make_company
):
    persist_records(database, records)
    other, facts = make_company()
    database.save_company(other, evidence=facts)
    wrong = records.contact_evidence[0].model_copy(
        update={"id": uuid4(), "company_id": other.id}
    )
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        database.save_evidence(wrong)
    assert {fact.id for fact in database.list_evidence(other.id)} == {
        fact.id for fact in facts
    }


def test_assessment_requires_campaign_membership(
    database, records
):
    database.save_campaign(records.campaign)
    database.save_company(records.company, evidence=records.company_evidence)
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        database.save_assessment(records.assessment)
    assert database.get_assessment(records.assessment.id) is None


def test_selected_assessment_cannot_cross_campaign_or_company(
    database, records, persist_records, make_company, make_assessment
):
    persist_records(database, records)
    other, facts = make_company()
    database.save_company(other, evidence=facts)
    database.save_run_item(RunItem(campaign_id=records.campaign.id, company_id=other.id))
    assessment = make_assessment(records.campaign.id, other.id)
    database.save_assessment(assessment)
    item = records.run_item.model_copy(update={"last_assessment_id": assessment.id})
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        database.save_run_item(item)
    assert database.get_run_item(records.campaign.id, records.company.id) == records.run_item


def test_revision_preserves_history_and_changes_selection_explicitly(
    database, records, persist_records, make_assessment
):
    persist_records(database, records)
    revision = make_assessment(
        records.campaign.id,
        records.company.id,
        revision_of=records.assessment.id,
        created_at=records.assessment.created_at + timedelta(seconds=1),
        explanation="Revisión sintética conservada como evaluación nueva.",
    )
    database.save_assessment(revision)
    assert database.list_assessments(records.campaign.id, records.company.id) == [
        records.assessment, revision
    ]
    assert database.get_run_item(
        records.campaign.id, records.company.id
    ).last_assessment_id == records.assessment.id
    selected = records.run_item.model_copy(update={"last_assessment_id": revision.id})
    database.save_run_item(selected)
    assert database.get_run_item(
        records.campaign.id, records.company.id
    ).last_assessment_id == revision.id
    assert database.get_assessment(records.assessment.id) == records.assessment


def test_contact_cannot_borrow_another_person_employment_evidence(
    database, records, persist_records, make_contact
):
    persist_records(database, records)
    other, facts = make_contact(records.company.id)
    database.save_contact(other, evidence=facts)
    invalid = other.model_copy(update={
        "employment_evidence_ids": records.contact.employment_evidence_ids
    })
    with pytest.raises(ValueError):
        database.save_contact(invalid)
    assert database.get_contact(other.id) == other


def test_failed_checkpoint_rolls_back_every_write(database, records):
    with pytest.raises(RuntimeError, match="Interrupción sintética"):
        with database.transaction():
            database.save_campaign(records.campaign)
            database.save_company(records.company, evidence=records.company_evidence)
            database.save_run_item(records.run_item)
            database.save_usage(records.usage)
            raise RuntimeError("Interrupción sintética")
    assert database.get_campaign(records.campaign.id) is None
    assert database.get_company(records.company.id) is None
    assert database.get_usage(records.usage.request_id) is None
    assert database.get_run_item(records.campaign.id, records.company.id) is None


@pytest.mark.parametrize("field", [
    "stage", "attempts", "consumed_limits", "last_assessment_id", "business_status",
])
def test_confirmed_checkpoint_cannot_lose_progress(
    database, records, persist_records, field
):
    persist_records(database, records)
    limits = ConsumedLimits(web_queries=1, pages=1, active_seconds=1.0)
    item = database.save_run_item(records.run_item.model_copy(update={
        "stage": RunStage.ASSESSED,
        "attempts": {"synthetic_research": 1},
        "consumed_limits": limits,
        "business_status": BusinessStatus.INSUFFICIENT_EVIDENCE,
    }))
    regression = {
        "stage": RunStage.DISCOVERED,
        "attempts": {},
        "consumed_limits": limits.model_copy(update={"web_queries": 0}),
        "last_assessment_id": None,
        "business_status": None,
    }
    with pytest.raises(ValueError):
        database.save_run_item(item.model_copy(update={field: regression[field]}))
    assert database.get_run_item(item.campaign_id, item.company_id) == item


def test_caught_aggregate_failure_does_not_leave_partial_data(
    database, make_campaign, make_company
):
    campaign = make_campaign()
    company, facts = make_company(domain="empresa-sintetica.example")
    broken = company.model_copy(update={
        "provenance": company.provenance | {"name": [uuid4()]}
    })
    with database.transaction():
        database.save_campaign(campaign)
        with pytest.raises((ValueError, sqlite3.IntegrityError)):
            database.save_company(broken, evidence=facts)
        assert database.get_company(company.id) is None
        assert database.list_evidence(company.id) == []
    assert database.get_campaign(campaign.id) == campaign


def test_nested_transaction_is_rejected_without_discarding_outer_work(
    database, make_campaign
):
    campaign = make_campaign()
    with database.transaction():
        database.save_campaign(campaign)
        with pytest.raises(ValueError):
            with database.transaction():
                raise AssertionError("No debe entrar a una transacción anidada.")
    assert database.get_campaign(campaign.id) == campaign


@pytest.mark.parametrize("object_name", ["evidence", "assessment"])
def test_immutable_records_are_idempotent_and_reject_collision(
    database, records, persist_records, object_name
):
    persist_records(database, records)
    if object_name == "evidence":
        record = records.company_evidence[0]
        save = database.save_evidence
        changed = record.model_copy(update={"claim": "Afirmación sintética diferente."})
    else:
        record = records.assessment
        save = database.save_assessment
        changed = record.model_copy(update={"explanation": "Evaluación sintética diferente."})
    assert save(record) == record
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        save(changed)
    assert save(record) == record


def test_usage_roundtrip_preserves_exact_subcent_costs(
    database, records, persist_records
):
    persist_records(database, records)
    usage = records.usage.model_copy(update={
        "reserved_cost_usd": Decimal("0.0000007"),
        "estimated_cost_usd": Decimal("0.0000003"),
        "final_cost_usd": Decimal("0.0000001"),
        "reserved_credits": Decimal("0.5"),
        "credits": Decimal("0.25"),
        "tokens": TokenUsage(input_tokens=17, output_tokens=3),
    })
    saved = database.save_usage(usage)
    assert saved.final_cost_usd == Decimal("0.0000001")
    assert saved.reserved_credits == Decimal("0.5")
    assert database.get_usage(usage.request_id) == saved


@pytest.mark.parametrize("field", [
    "provider", "operation", "request_fingerprint", "account_ref", "campaign_id",
])
def test_usage_request_identity_is_immutable(
    database, records, persist_records, make_campaign, field
):
    persist_records(database, records)
    values = {
        "provider": "other-synthetic",
        "operation": "other-lookup",
        "request_fingerprint": "b" * 64,
        "account_ref": "other-synthetic-account",
    }
    if field == "campaign_id":
        other = make_campaign()
        database.save_campaign(other)
        database.save_run_item(RunItem(campaign_id=other.id, company_id=records.company.id))
        values[field] = other.id
    with pytest.raises(ValueError):
        database.save_usage(records.usage.model_copy(update={field: values[field]}))
    assert database.get_usage(records.usage.request_id) == records.usage


@pytest.mark.parametrize("field", [
    "reserved_cost_usd", "reserved_credits", "final_cost_usd", "credits", "tokens",
])
@pytest.mark.parametrize("clear", [False, True])
def test_recorded_usage_cannot_be_lost_or_changed(
    database, records, persist_records, field, clear
):
    persist_records(database, records)
    initial = TokenUsage(input_tokens=17) if field == "tokens" else Decimal("0.125")
    usage = database.save_usage(records.usage.model_copy(update={field: initial}))
    replacement = None if clear else (
        TokenUsage(input_tokens=18) if field == "tokens" else Decimal("0.25")
    )
    with pytest.raises(ValueError):
        database.save_usage(usage.model_copy(update={field: replacement}))
    assert database.get_usage(usage.request_id) == usage


@pytest.mark.parametrize("field", [
    "estimated_cost_usd", "funding_source", "outcome", "finished_at", "reconciled_at",
])
def test_usage_cannot_erase_known_metadata(database, records, persist_records, field):
    persist_records(database, records)
    facts = {
        "estimated_cost_usd": Decimal("0.001"),
        "funding_source": "prepaid",
        "outcome": "succeeded",
        "finished_at": records.usage.created_at + timedelta(seconds=1),
        "reconciled_at": records.usage.created_at + timedelta(seconds=2),
    }
    usage = database.save_usage(records.usage.model_copy(update={field: facts[field]}))
    with pytest.raises(ValueError):
        database.save_usage(usage.model_copy(update={field: None}))
    assert database.get_usage(usage.request_id) == usage


def test_usage_can_refine_estimate_and_fill_unknown_token_counts(
    database, records, persist_records
):
    persist_records(database, records)
    usage = database.save_usage(records.usage.model_copy(update={
        "estimated_cost_usd": Decimal("0.001"),
        "tokens": TokenUsage(input_tokens=17),
    }))
    refined = database.save_usage(usage.model_copy(update={
        "estimated_cost_usd": Decimal("0.002"),
        "tokens": TokenUsage(input_tokens=17, output_tokens=3),
    }))
    assert refined.estimated_cost_usd == Decimal("0.002")
    assert refined.tokens.input_tokens == 17
    assert refined.tokens.output_tokens == 3
    assert refined.tokens.additional_tokens is None
    assert refined.final_cost_usd is None


def test_same_fingerprint_does_not_duplicate_or_forbid_distinct_requests(
    database, records, persist_records
):
    persist_records(database, records)
    assert database.save_usage(records.usage) == records.usage
    other = records.usage.model_copy(update={"request_id": uuid4()})
    database.save_usage(other)
    assert {usage.request_id for usage in database.list_usage()} == {
        records.usage.request_id, other.request_id
    }


@pytest.mark.parametrize("first_state,second_state", [
    ("running", "running"), ("running", "paused_budget"),
    ("paused_budget", "running"), ("paused_budget", "paused_budget"),
])
def test_single_active_campaign_across_connections(
    tmp_path, make_campaign, first_state, second_state
):
    path = tmp_path / "synthetic-active.sqlite3"
    first = make_campaign(status=first_state)
    second = make_campaign(status=second_state)
    with Database(path) as writer, Database(path) as other_writer:
        writer.save_campaign(first)
        with pytest.raises(sqlite3.IntegrityError):
            other_writer.save_campaign(second)
        assert other_writer.get_active_campaign() == first
        assert other_writer.get_campaign(second.id) is None
        writer.save_campaign(first.model_copy(update={"status": CampaignStatus.PARTIAL}))
        assert other_writer.get_active_campaign() is None
        other_writer.save_campaign(second)
        assert writer.get_active_campaign() == second


def test_campaign_cannot_redefine_an_existing_rubric_version(
    database, records, persist_records, make_campaign
):
    persist_records(database, records)
    fields = records.campaign.config_snapshot.model_dump()
    fields["rubrics"]["rubric_v1"]["criteria"]["document_need"]["strong_signal"] = (
        "Definición sintética distinta bajo la misma versión."
    )
    snapshot = type(records.campaign.config_snapshot).model_validate(fields)
    campaign = make_campaign(config_snapshot=snapshot)
    with pytest.raises(ValueError):
        database.save_campaign(campaign)
    assert database.get_campaign(campaign.id) is None
    assert database.get_campaign(records.campaign.id) == records.campaign


def test_new_rubric_version_preserves_the_previous_campaign_snapshot(
    database, records, persist_records, make_campaign, make_assessment
):
    persist_records(database, records)
    fields = records.campaign.config_snapshot.model_dump()
    revised_rubric = fields["rubrics"].pop("rubric_v1")
    revised_rubric["criteria"]["document_need"]["strong_signal"] = (
        "Definición sintética registrada con una versión distinta."
    )
    fields["rubrics"]["rubric_v2"] = revised_rubric
    snapshot = type(records.campaign.config_snapshot).model_validate(fields)
    campaign = make_campaign(config_snapshot=snapshot, rubric_version="rubric_v2")
    database.save_campaign(campaign)
    database.save_run_item(RunItem(campaign_id=campaign.id, company_id=records.company.id))
    assessment = make_assessment(
        campaign.id, records.company.id, rubric_version="rubric_v2"
    )
    database.save_assessment(assessment)
    assert database.get_campaign(campaign.id).config_snapshot == snapshot
    assert database.get_campaign(records.campaign.id) == records.campaign
    assert database.get_assessment(records.assessment.id) == records.assessment


def test_reducing_company_limit_preserves_existing_memberships(
    database, records, persist_records, make_company
):
    persist_records(database, records)
    company, facts = make_company()
    database.save_company(company, evidence=facts)
    database.save_run_item(RunItem(campaign_id=records.campaign.id, company_id=company.id))
    reduced = records.campaign.model_copy(update={"max_companies": 1})
    with pytest.raises(ValueError):
        database.save_campaign(reduced)
    assert database.get_campaign(records.campaign.id) == records.campaign
    assert len(database.list_run_items(records.campaign.id)) == 2


def test_reopen_recovers_checkpoint_and_paid_usage(tmp_path, records, persist_records):
    path = tmp_path / "synthetic-recovery.sqlite3"
    records.usage = records.usage.model_copy(update={
        "reserved_cost_usd": Decimal("0.25"),
        "final_cost_usd": Decimal("0.0000001"),
    })
    with Database(path) as database:
        persist_records(database, records)
    with Database(path) as restored:
        assert restored.get_run_item(records.campaign.id, records.company.id) == records.run_item
        assert restored.get_contact(records.contact.id) == records.contact
        assert restored.get_assessment(records.assessment.id) == records.assessment
        assert restored.get_usage(records.usage.request_id) == records.usage
        assert len(restored.list_evidence(records.company.id)) == len(
            records.company_evidence + records.contact_evidence
        )


def test_reopen_preserves_failed_stage_and_uncertain_reservation(
    tmp_path, records, persist_records
):
    path = tmp_path / "synthetic-uncertain.sqlite3"
    failure = "synthetic provider: timeout (request synthetic-123)"
    records.run_item = records.run_item.model_copy(update={
        "stage": RunStage.ASSESSED,
        "error_stage": RunStage.CONTACTS_CHECKED,
        "error_message": failure,
        "stop_reason": "provider_timeout",
        "attempts": {"synthetic_lookup": 1},
    })
    records.usage = records.usage.model_copy(update={
        "status": UsageStatus.UNCERTAIN,
        "reserved_cost_usd": Decimal("0.25"),
        "reserved_credits": Decimal("1"),
        "reserved_tokens": TokenUsage(input_tokens=6000, output_tokens=1000),
        "error_message": failure,
    })
    with Database(path) as database:
        persist_records(database, records)
    with Database(path) as restored:
        checkpoint = restored.get_run_item(records.campaign.id, records.company.id)
        usage = restored.get_usage(records.usage.request_id)
        assert checkpoint == records.run_item
        assert checkpoint.stage == RunStage.ASSESSED
        assert checkpoint.error_stage == RunStage.CONTACTS_CHECKED
        assert checkpoint.error_message == failure
        assert usage == records.usage
        assert usage.status == UsageStatus.UNCERTAIN
        assert usage.reserved_cost_usd == Decimal("0.25")
        assert usage.final_cost_usd is None
        assert usage.error_message == failure


def test_data_modules_import_without_streamlit_or_side_effects(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    script = """
import os
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])

def reject_side_effects(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'sqlite3.connect',
                 'os.mkdir', 'os.remove', 'os.rename', 'os.rmdir', 'os.truncate'}:
        raise AssertionError(f'Efecto secundario al importar: {event}')
    if event == 'open':
        mode, flags = args[1:3]
        if (mode is not None and any(flag in mode for flag in 'wax+')) or (
            flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        ):
            raise AssertionError('La importación intentó escribir un archivo.')

sys.addaudithook(reject_side_effects)
import prospecting.models
import prospecting.db
assert 'streamlit' not in sys.modules
assert list(Path.cwd().iterdir()) == []
"""
    process = subprocess.run(
        [sys.executable, "-B", "-c", script, str(project_root)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stderr
    assert list(tmp_path.iterdir()) == []


def test_sql_text_remains_data(database, make_company):
    company, facts = make_company(name="Empresa sintética'); DROP TABLE usage; --")
    database.save_company(company, evidence=facts)
    assert database.get_company(company.id).name == company.name
    assert database.list_usage() == []


@pytest.mark.parametrize("version", [0, 2, 999])
def test_unknown_schema_preserves_existing_data(tmp_path, version):
    path = tmp_path / "synthetic-incompatible.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE synthetic_paid_data (amount TEXT)")
        connection.execute("INSERT INTO synthetic_paid_data VALUES (?)", ("0.25",))
        connection.execute(f"PRAGMA user_version = {version}")
    with pytest.raises(sqlite3.DatabaseError):
        Database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT amount FROM synthetic_paid_data").fetchone() == ("0.25",)


def test_incomplete_known_schema_is_rejected(tmp_path):
    path = tmp_path / "synthetic-incomplete.sqlite3"
    with Database(path):
        pass
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE usage")
    with pytest.raises(sqlite3.DatabaseError):
        Database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_schema WHERE type='table' AND name='usage'"
        ).fetchone()[0] == 0


def test_reading_corrupted_channel_revalidates_model(
    tmp_path, records, persist_records
):
    path = tmp_path / "synthetic-corrupted.sqlite3"
    with Database(path) as database:
        persist_records(database, records)
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE contacts SET channels = ? WHERE id = ?",
                ('[{"unexpected": "synthetic corruption"}]', str(records.contact.id)),
            )
        with pytest.raises((ValueError, sqlite3.DatabaseError)):
            database.get_contact(records.contact.id)
