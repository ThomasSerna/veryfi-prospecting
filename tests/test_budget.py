"""Reserva y conciliación con cuentas, fechas y datos exclusivamente sintéticos."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest

from prospecting.budget import (
    AccountAllowance, Budget, BudgetError, Confirmation, Observation,
    SpendingAuthorization,
)
from prospecting.db import Database
from prospecting.models import RunItem, TokenUsage, Usage, UsageStatus


ORIGIN = datetime(2020, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def prepared(database, config, make_campaign, make_company):
    campaign = database.save_campaign(make_campaign())
    company, facts = make_company()
    database.save_company(company, evidence=facts)
    database.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id))
    allowance = AccountAllowance(
        provider="synthetic", account_ref="synthetic-account", funding_source="prepaid",
        credit_limit="10", cost_limit_usd="10", source_reference="fixture sintética de cupo",
        observed_at=ORIGIN,
    )
    authorization = SpendingAuthorization(
        provider="synthetic", operation="lookup", account_ref="synthetic-account",
        max_cost_usd="10", max_credits="10", responsible="Responsable sintético",
        source_reference="permiso sintético", authorized_at=ORIGIN,
    )
    proposal = Usage(
        campaign_id=campaign.id, company_id=company.id, provider="synthetic", operation="lookup",
        account_ref="synthetic-account", request_fingerprint="a" * 64,
        reserved_cost_usd="0.10", reserved_credits="1", funding_source="prepaid",
        created_at=ORIGIN + timedelta(seconds=1), status="reserved",
    )
    return Budget(database, config.defaults.budget, [allowance]), proposal, authorization


def confirmation(**overrides):
    return Confirmation.model_validate({
        "outcome": "succeeded", "final_cost_usd": "0.05", "credits": "0.5",
        "outlay_usd": "0", "source_reference": "respuesta de proveedor sintético",
        "observed_at": ORIGIN + timedelta(seconds=2),
    } | overrides)


def claim(prepared):
    budget, proposal, grant = prepared
    budget.reserve(proposal, grant)
    return budget.claim(proposal.request_id, proposal.request_fingerprint, grant)


def test_reservation_and_reconciliation_replace_exposure_without_erasing_reserve(prepared):
    budget, proposal, grant = prepared
    saved = budget.reserve(proposal, grant)
    state = budget.snapshot(proposal.campaign_id, proposal.company_id)
    assert saved.status == UsageStatus.RESERVED
    assert state.company.pending == Decimal("0.10")
    assert state.company.available == Decimal("0.15")
    claim(prepared)
    budget.record_result(proposal.request_id, Observation(outcome="succeeded"))
    assert budget.snapshot(proposal.campaign_id).campaign.pending == Decimal("0.10")
    done = budget.reconcile(proposal.request_id, confirmation())
    assert done.reserved_cost_usd == Decimal("0.10")
    assert done.reserved_credits == Decimal("1")
    state = budget.snapshot(proposal.campaign_id, proposal.company_id)
    assert state.company.confirmed == Decimal("0.05")
    assert state.company.pending == 0
    assert state.accounts[0].credits.exposure == Decimal("0.5")
    assert state.confirmed_cost_usd == Decimal("0.05")
    assert state.outlay_usd == 0


def test_reservation_requires_session_authorization(prepared):
    budget, proposal, _ = prepared
    with pytest.raises(BudgetError, match="autorización") as error:
        budget.reserve(proposal, None)
    assert error.value.code == "authorization_required"
    assert budget.db.list_usage() == []


@pytest.mark.parametrize("changes", [
    {"provider": "another-synthetic"}, {"operation": "another-lookup"},
    {"account_ref": "another-account"}, {"authorized_at": ORIGIN + timedelta(seconds=5)},
])
def test_authorization_matches_identity_and_date(prepared, changes):
    budget, proposal, grant = prepared
    with pytest.raises(BudgetError):
        budget.reserve(proposal, grant.model_copy(update=changes))
    assert budget.db.list_usage() == []


def test_grant_is_a_total_not_a_per_call_limit(prepared):
    budget, proposal, grant = prepared
    grant = grant.model_copy(update={"max_credits": Decimal("1")})
    budget.reserve(proposal, grant)
    second = proposal.model_copy(update={"request_id": uuid4(), "request_fingerprint": "b" * 64})
    with pytest.raises(BudgetError) as error:
        budget.reserve(second, grant)
    assert error.value.code == "authorization_exceeded"
    assert len(budget.db.list_usage()) == 1


def test_grant_survives_budget_reconstruction_without_resetting_total(prepared):
    budget, proposal, grant = prepared
    grant = grant.model_copy(update={"max_credits": Decimal("1")})
    budget.reserve(proposal, grant)
    restored = Budget(budget.db, budget.global_limits, budget.account_allowances)
    second = proposal.model_copy(update={"request_id": uuid4(), "request_fingerprint": "b" * 64})
    with pytest.raises(BudgetError) as error:
        restored.reserve(second, grant)
    assert error.value.code == "authorization_exceeded"


def test_same_grant_cannot_change_its_caps(prepared):
    budget, proposal, grant = prepared
    budget.reserve(proposal, grant)
    changed = grant.model_copy(update={"max_credits": Decimal("9")})
    with pytest.raises(BudgetError) as error:
        budget.claim(proposal.request_id, proposal.request_fingerprint, changed)
    assert error.value.code == "authorization_conflict"


def test_account_allowance_is_initial_sprint_ceiling_not_a_date_filter(prepared):
    budget, proposal, grant = prepared
    budget.reserve(proposal, grant)
    allowance = budget.account_allowances[0].model_copy(update={
        "observed_at": ORIGIN + timedelta(days=10), "credit_limit": Decimal("1"),
    })
    restored = Budget(budget.db, budget.global_limits, [allowance])
    second = proposal.model_copy(update={"request_id": uuid4(), "request_fingerprint": "b" * 64})
    with pytest.raises(BudgetError) as error:
        restored.reserve(second, grant)
    assert error.value.code == "budget_exceeded"


@pytest.mark.parametrize("bound", ["company", "campaign", "account_credit", "account_cost"])
def test_each_bound_blocks_the_reservation(prepared, bound):
    budget, proposal, grant = prepared
    if bound == "company":
        proposal = proposal.model_copy(update={"reserved_cost_usd": Decimal("0.26")})
    elif bound == "campaign":
        proposal = proposal.model_copy(update={"company_id": None, "reserved_cost_usd": Decimal("2.01")})
    elif bound == "account_credit":
        budget.account_allowances[0].credit_limit = Decimal("0.5")
    else:
        budget.account_allowances[0].cost_limit_usd = Decimal("0.05")
    with pytest.raises(BudgetError) as error:
        budget.reserve(proposal, grant)
    assert error.value.code == "budget_exceeded"
    assert budget.db.list_usage() == []


def test_completed_campaign_spend_blocks_operating_limit_before_global_limit(prepared, make_campaign):
    budget, proposal, grant = prepared
    previous = budget.db.save_campaign(make_campaign(status="completed"))
    historical = proposal.model_copy(update={
        "request_id": uuid4(), "campaign_id": previous.id, "company_id": None,
        "provider": "another-synthetic-provider", "account_ref": "previous-synthetic-account",
        "status": UsageStatus.RECONCILED, "outcome": "succeeded",
        "reserved_cost_usd": Decimal("14.95"), "reserved_credits": Decimal(0),
        "final_cost_usd": Decimal("14.95"), "credits": Decimal(0), "outlay_usd": Decimal(0),
    })
    budget.db.save_usage(historical)
    before = budget.snapshot(proposal.campaign_id, proposal.company_id)
    assert before.operating.available == Decimal("0.05")
    assert before.global_budget.available == Decimal("5.05")
    assert before.company.exposure == 0
    with pytest.raises(BudgetError) as error:
        budget.reserve(proposal, grant)
    assert error.value.code == "budget_exceeded"
    assert budget.db.get_usage(proposal.request_id) is None


def test_global_limit_exposes_confirmed_excess_without_truncating(prepared):
    budget, proposal, grant = prepared
    budget.db.save_usage(proposal.model_copy(update={
        "company_id": None, "status": UsageStatus.RECONCILED, "outcome": "succeeded",
        "reserved_cost_usd": Decimal("20.01"), "final_cost_usd": Decimal("20.01"),
        "credits": Decimal(0), "outlay_usd": Decimal(0),
    }))
    state = budget.snapshot(proposal.campaign_id)
    assert state.global_budget.exceeded
    assert state.global_budget.confirmed == Decimal("20.01")
    assert state.global_budget.available == 0
    with pytest.raises(BudgetError):
        budget.reserve(proposal.model_copy(update={"request_id": uuid4(), "request_fingerprint": "b" * 64}), grant)


def test_authorized_cash_is_a_total_across_requests(prepared):
    budget, proposal, grant = prepared
    grant = grant.model_copy(update={"max_cost_usd": Decimal("0.15")})
    budget.reserve(proposal, grant)
    with pytest.raises(BudgetError) as error:
        budget.reserve(proposal.model_copy(update={"request_id": uuid4(), "request_fingerprint": "b" * 64}), grant)
    assert error.value.code == "authorization_exceeded"


def test_reduced_campaign_limits_are_preserved(prepared):
    budget, proposal, grant = prepared
    campaign = budget.db.get_campaign(proposal.campaign_id)
    limits = campaign.limits.model_dump()
    limits["budget"].update(campaign_usd="0.15", company_usd="0.10")
    reduced = type(campaign).model_validate(campaign.model_dump() | {"limits": limits})
    budget.db.save_campaign(reduced)
    state = budget.snapshot(proposal.campaign_id, proposal.company_id)
    assert state.campaign.limit == Decimal("0.15")
    assert state.company.limit == Decimal("0.10")
    with pytest.raises(BudgetError) as error:
        budget.reserve(proposal.model_copy(update={"company_id": None, "reserved_cost_usd": Decimal("0.16")}), grant)
    assert error.value.code == "budget_exceeded"


def test_company_cap_accumulates_across_campaigns(prepared, make_campaign):
    budget, proposal, grant = prepared
    proposal = proposal.model_copy(update={"reserved_cost_usd": Decimal("0.20")})
    budget.reserve(proposal, grant)
    other = budget.db.save_campaign(make_campaign())
    budget.db.save_run_item(RunItem(campaign_id=other.id, company_id=proposal.company_id))
    second = proposal.model_copy(update={
        "request_id": uuid4(), "campaign_id": other.id, "reserved_cost_usd": Decimal("0.06"),
    })
    with pytest.raises(BudgetError) as error:
        budget.reserve(second, grant)
    assert error.value.code == "budget_exceeded"
    assert budget.snapshot(other.id, proposal.company_id).company.exposure == Decimal("0.20")


def test_decimal_sum_and_available_keep_more_than_28_digits(prepared):
    budget, proposal, grant = prepared
    tiny = Decimal("0.0000000000000000000000000000000000000001")
    budget.reserve(proposal.model_copy(update={"reserved_cost_usd": tiny}), grant)
    budget.reserve(proposal.model_copy(update={
        "request_id": uuid4(), "request_fingerprint": "b" * 64,
        "reserved_cost_usd": Decimal("0.1"),
    }), grant)
    state = budget.snapshot(proposal.campaign_id, proposal.company_id)
    assert state.company.exposure == Decimal("0.1000000000000000000000000000000000000001")
    assert state.company.available == Decimal("0.1499999999999999999999999999999999999999")


def test_request_and_contextual_fingerprint_reuse_one_reservation(prepared):
    budget, proposal, grant = prepared
    first = budget.reserve(proposal, grant)
    assert budget.reserve(proposal, grant) == first
    assert budget.reserve(proposal.model_copy(update={"request_id": uuid4()}), grant) == first
    with pytest.raises(BudgetError) as error:
        budget.reserve(proposal.model_copy(update={"reserved_cost_usd": Decimal("0.11")}), grant)
    assert error.value.code == "request_conflict"
    assert len(budget.db.list_usage()) == 1


def test_different_fingerprint_for_same_request_id_is_rejected(prepared):
    budget, proposal, grant = prepared
    budget.reserve(proposal, grant)
    with pytest.raises(BudgetError) as error:
        budget.reserve(proposal.model_copy(update={"request_fingerprint": "b" * 64}), grant)
    assert error.value.code == "request_conflict"


def test_claim_is_exclusive_and_verifies_fingerprint(prepared):
    budget, proposal, grant = prepared
    budget.reserve(proposal, grant)
    with pytest.raises(BudgetError) as error:
        budget.claim(proposal.request_id, "b" * 64, grant)
    assert error.value.code == "fingerprint_mismatch"
    assert claim(prepared).status == UsageStatus.IN_FLIGHT
    with pytest.raises(BudgetError) as error:
        budget.claim(proposal.request_id, proposal.request_fingerprint, grant)
    assert error.value.code == "request_not_reserved"


@pytest.mark.parametrize("status", [UsageStatus.IN_FLIGHT, UsageStatus.UNCERTAIN])
def test_restart_keeps_unconfirmed_reservation_and_blocks_repetition(prepared, status):
    budget, proposal, grant = prepared
    claim(prepared)
    if status == UsageStatus.UNCERTAIN:
        budget.record_result(proposal.request_id, Observation(outcome="unknown", error_message="Timeout sintético"))
    restored = Budget(budget.db, budget.global_limits, budget.account_allowances)
    assert restored.snapshot(proposal.campaign_id).campaign.pending == Decimal("0.10")
    with pytest.raises(BudgetError):
        restored.claim(proposal.request_id, proposal.request_fingerprint, grant)
    with pytest.raises(BudgetError) as error:
        restored.reserve(proposal.model_copy(update={"request_id": uuid4()}), grant)
    assert error.value.code == "duplicate_request"


def test_observations_can_fill_unknowns_without_erasing_known_values(prepared):
    budget, proposal, _ = prepared
    claim(prepared)
    budget.record_result(proposal.request_id, Observation(outcome="succeeded"))
    budget.record_result(proposal.request_id, Observation(
        outcome="succeeded", tokens=TokenUsage(input_tokens=10), credits="0.5", estimated_cost_usd="0.03",
    ))
    result = budget.record_result(proposal.request_id, Observation(
        outcome="succeeded", tokens=TokenUsage(output_tokens=5), estimated_cost_usd="0.04",
    ))
    assert result.tokens == TokenUsage(input_tokens=10, output_tokens=5)
    assert result.credits == Decimal("0.5")
    assert result.estimated_cost_usd == Decimal("0.04")
    assert budget.snapshot(proposal.campaign_id).campaign.pending == Decimal("0.10")
    with pytest.raises(BudgetError):
        budget.record_result(proposal.request_id, Observation(outcome="succeeded", credits="0.6"))


def test_late_observation_cannot_change_a_reconciled_record(prepared):
    budget, proposal, _ = prepared
    claim(prepared)
    done = budget.reconcile(proposal.request_id, confirmation())
    with pytest.raises(BudgetError) as error:
        budget.record_result(proposal.request_id, Observation(outcome="succeeded"))
    assert error.value.code == "invalid_state"
    assert budget.db.get_usage(proposal.request_id) == done


def test_reconciliation_is_idempotent_and_conflicts_roll_back(prepared):
    budget, proposal, _ = prepared
    claim(prepared)
    done = budget.reconcile(proposal.request_id, confirmation())
    assert budget.reconcile(proposal.request_id, confirmation(observed_at=ORIGIN + timedelta(days=1))) == done
    with pytest.raises(BudgetError) as error:
        budget.reconcile(proposal.request_id, confirmation(final_cost_usd="0.06"))
    assert error.value.code == "reconciliation_conflict"
    assert budget.db.get_usage(proposal.request_id) == done


def test_no_send_releases_only_a_reservation_known_not_to_have_been_sent(prepared):
    budget, proposal, grant = prepared
    budget.reserve(proposal, grant)
    cancelled = budget.reconcile(proposal.request_id, confirmation(
        outcome="failed", final_cost_usd="0", credits="0", no_send=True,
    ))
    assert cancelled.reserved_cost_usd == Decimal("0.10")
    assert budget.snapshot(proposal.campaign_id).campaign.exposure == 0


def test_no_send_cannot_release_an_inflight_timeout(prepared):
    budget, proposal, _ = prepared
    claim(prepared)
    with pytest.raises(BudgetError) as error:
        budget.reconcile(proposal.request_id, confirmation(
            outcome="failed", final_cost_usd="0", credits="0", no_send=True,
        ))
    assert error.value.code == "invalid_no_send"
    assert budget.db.get_usage(proposal.request_id).status == UsageStatus.IN_FLIGHT


@pytest.mark.parametrize("field", ["reserved_cost_usd", "reserved_credits"])
def test_unknown_legacy_reservations_never_become_zero(prepared, field):
    budget, proposal, grant = prepared
    budget.db.save_usage(proposal.model_copy(update={field: None}))
    second = proposal.model_copy(update={"request_id": uuid4(), "request_fingerprint": "b" * 64})
    with pytest.raises(BudgetError) as error:
        budget.reserve(second, grant)
    assert error.value.code in ("budget_unknown", "authorization_unknown")
    assert len(budget.db.list_usage()) == 1


def test_known_confirmation_can_reconcile_unknown_legacy_reservation(prepared):
    budget, proposal, _ = prepared
    budget.db.save_usage(proposal.model_copy(update={
        "status": UsageStatus.UNCERTAIN, "reserved_cost_usd": None, "reserved_credits": None,
    }))
    budget.reconcile(proposal.request_id, confirmation())
    assert budget.snapshot(proposal.campaign_id).campaign.exposure == Decimal("0.05")


def test_multiple_legacy_reservations_with_same_fingerprint_block_claim(prepared):
    budget, proposal, grant = prepared
    budget.db.save_usage(proposal)
    budget.db.save_usage(proposal.model_copy(update={"request_id": uuid4()}))
    assert budget.snapshot(proposal.campaign_id).campaign.pending == Decimal("0.20")
    with pytest.raises(BudgetError) as error:
        budget.claim(proposal.request_id, proposal.request_fingerprint, grant)
    assert error.value.code == "duplicate_request"


def test_free_credit_tracks_credits_with_zero_economic_cost(prepared):
    budget, proposal, grant = prepared
    budget.account_allowances[0].funding_source = "free_credit"
    budget.account_allowances[0].cost_limit_usd = None
    proposal = proposal.model_copy(update={"funding_source": "free_credit", "reserved_cost_usd": Decimal(0)})
    budget.reserve(proposal, grant)
    budget.claim(proposal.request_id, proposal.request_fingerprint, grant)
    budget.reconcile(proposal.request_id, confirmation(final_cost_usd="0"))
    state = budget.snapshot(proposal.campaign_id)
    assert state.global_budget.confirmed == 0
    assert state.accounts[0].credits.confirmed == Decimal("0.5")


@pytest.mark.parametrize("funding,changes", [
    ("free_credit", {"final_cost_usd": "0.01"}),
    ("free_credit", {"final_cost_usd": "0", "outlay_usd": "0.01"}),
    ("prepaid", {"outlay_usd": "0.01"}),
])
def test_unexpected_real_charge_is_persisted_and_blocks_spending(prepared, funding, changes):
    budget, proposal, grant = prepared
    budget.account_allowances[0].funding_source = funding
    proposal = proposal.model_copy(update={
        "funding_source": funding, "reserved_cost_usd": Decimal(0) if funding == "free_credit" else Decimal("0.10"),
    })
    budget.reserve(proposal, grant)
    budget.claim(proposal.request_id, proposal.request_fingerprint, grant)
    result = budget.reconcile(proposal.request_id, confirmation(**changes))
    assert result.status == UsageStatus.RECONCILED
    assert result.funding_source == funding
    assert budget.snapshot(proposal.campaign_id).reservation_overrun
    with pytest.raises(BudgetError) as error:
        budget.reserve(proposal.model_copy(update={"request_id": uuid4(), "request_fingerprint": "b" * 64}), grant)
    assert error.value.code == "reservation_overrun"


def test_new_outlay_is_not_counted_twice_and_cash_is_bounded(prepared):
    budget, proposal, grant = prepared
    budget.account_allowances[0].funding_source = "new_outlay"
    proposal = proposal.model_copy(update={"funding_source": "new_outlay"})
    budget.reserve(proposal, grant)
    budget.claim(proposal.request_id, proposal.request_fingerprint, grant)
    budget.reconcile(proposal.request_id, confirmation(final_cost_usd="0.05", outlay_usd="0.05"))
    assert budget.snapshot(proposal.campaign_id).campaign.confirmed == Decimal("0.05")
    assert budget.snapshot(proposal.campaign_id).confirmed_cost_usd == Decimal("0.05")
    assert budget.snapshot(proposal.campaign_id).outlay_usd == Decimal("0.05")


def test_snapshot_does_not_infer_unknown_outlay_as_zero(prepared):
    budget, proposal, grant = prepared
    budget.reserve(proposal, grant)
    assert budget.snapshot(proposal.campaign_id).outlay_usd is None


def test_confirmed_overrun_is_saved_and_blocks_even_when_total_has_room(prepared):
    budget, proposal, grant = prepared
    claim(prepared)
    result = budget.reconcile(proposal.request_id, confirmation(final_cost_usd="0.11"))
    assert result.final_cost_usd == Decimal("0.11")
    assert budget.snapshot(proposal.campaign_id).reservation_overrun
    second = proposal.model_copy(update={"request_id": uuid4(), "request_fingerprint": "b" * 64})
    with pytest.raises(BudgetError) as error:
        budget.reserve(second, grant)
    assert error.value.code == "reservation_overrun"


def test_final_bill_can_discard_a_higher_estimate(prepared):
    budget, proposal, grant = prepared
    claim(prepared)
    budget.record_result(proposal.request_id, Observation(outcome="succeeded", estimated_cost_usd="0.11"))
    assert budget.snapshot(proposal.campaign_id).reservation_overrun
    budget.reconcile(proposal.request_id, confirmation())
    assert not budget.snapshot(proposal.campaign_id).reservation_overrun
    second = proposal.model_copy(update={"request_id": uuid4(), "request_fingerprint": "b" * 64})
    assert budget.reserve(second, grant).status == UsageStatus.RESERVED


def test_anonymous_legacy_funding_blocks_its_provider_account(prepared):
    budget, proposal, grant = prepared
    budget.db.save_usage(proposal.model_copy(update={"funding_source": None}))
    with pytest.raises(BudgetError) as error:
        budget.reserve(proposal.model_copy(update={"request_id": uuid4(), "request_fingerprint": "b" * 64}), grant)
    assert error.value.code == "account_unknown"


def test_actual_cash_can_exceed_economic_cost_without_being_hidden(prepared):
    budget, proposal, grant = prepared
    budget.account_allowances[0].funding_source = "new_outlay"
    proposal = proposal.model_copy(update={"funding_source": "new_outlay"})
    budget.reserve(proposal, grant)
    budget.claim(proposal.request_id, proposal.request_fingerprint, grant)
    budget.reconcile(proposal.request_id, confirmation(outlay_usd="0.08"))
    state = budget.snapshot(proposal.campaign_id)
    assert state.confirmed_cost_usd == Decimal("0.05")
    assert state.outlay_usd == Decimal("0.08")
    assert state.global_budget.confirmed == Decimal("0.08")


def test_retry_is_one_new_request_after_confirmed_transient_failure(prepared):
    budget, proposal, grant = prepared
    claim(prepared)
    budget.record_result(proposal.request_id, Observation(outcome="failed", retryable=True))
    budget.reconcile(proposal.request_id, confirmation(outcome="failed", final_cost_usd="0", credits="0"))
    retry = proposal.model_copy(update={"request_id": uuid4()})
    budget.reserve(retry, grant, retry_of=proposal.request_id)
    budget.claim(retry.request_id, retry.request_fingerprint, grant)
    budget.record_result(retry.request_id, Observation(outcome="failed", retryable=True))
    budget.reconcile(retry.request_id, confirmation(outcome="failed", final_cost_usd="0", credits="0"))
    with pytest.raises(BudgetError):
        budget.reserve(proposal.model_copy(update={"request_id": uuid4()}), grant, retry_of=retry.request_id)
    assert len(budget.db.list_usage()) == 2


def test_restart_does_not_infer_retryability_from_error_text(prepared):
    budget, proposal, grant = prepared
    claim(prepared)
    budget.record_result(proposal.request_id, Observation(
        outcome="failed", retryable=True, error_message="Error sintético transitorio HTTP 503",
    ))
    budget.reconcile(proposal.request_id, confirmation(outcome="failed", final_cost_usd="0", credits="0"))
    restored = Budget(budget.db, budget.global_limits, budget.account_allowances)
    with pytest.raises(BudgetError):
        restored.reserve(proposal.model_copy(update={"request_id": uuid4()}), grant, retry_of=proposal.request_id)


@pytest.mark.parametrize("bound", ["credits", "cost"])
def test_two_connections_cannot_reserve_the_same_remaining_balance(prepared, tmp_path, bound):
    budget, proposal, grant = prepared
    path = tmp_path / "synthetic-race.sqlite3"
    with Database(path) as target:
        target.save_campaign(budget.db.get_campaign(proposal.campaign_id))
        target.save_company(budget.db.get_company(proposal.company_id), evidence=budget.db.list_evidence(proposal.company_id))
        target.save_run_item(budget.db.get_run_item(proposal.campaign_id, proposal.company_id))
    allowance = budget.account_allowances[0].model_copy(update={
        "credit_limit": Decimal("1") if bound == "credits" else Decimal("10"),
    })
    if bound == "cost":
        proposal = proposal.model_copy(update={"reserved_cost_usd": Decimal("0.20")})
    barrier = Barrier(2)

    def reserve_one(fingerprint):
        with Database(path) as connection:
            candidate = proposal.model_copy(update={"request_id": uuid4(), "request_fingerprint": fingerprint})
            worker = Budget(connection, budget.global_limits, [allowance])
            barrier.wait(timeout=10)
            try:
                return worker.reserve(candidate, grant).status
            except BudgetError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(reserve_one, fingerprint) for fingerprint in ("b" * 64, "c" * 64)]
        results = [future.result(timeout=15) for future in futures]
    assert results.count(UsageStatus.RESERVED) == 1
    assert results.count("budget_exceeded") == 1
    with Database(path) as restored:
        assert len(restored.list_usage()) == 1
