"""Descubrimiento con Tavily Search e identidad con la evidencia guardada."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from prospecting.budget import Budget, BudgetError, SpendingAuthorization
from prospecting.db import Database
from prospecting.discovery import (
    CombinationReport, ExclusionList, ExclusionMatch, ExclusionStatus, IdentityDecision, PlannedQuery,
    SEARCH_CREDITS, STOPPING_REASONS, TavilySearchResponse, assess_identity, build_company,
    build_hit_evidence, build_search_queries, classify_tavily_error, exclusion_evidence,
    exclusions_status, find_reusable, group_candidates, match_exclusion, parse_search, search_request,
    select_candidates,
)
from prospecting.models import (
    BusinessStatus, Company, Contract, Count, IdentityStatus, Money, RunItem, RunStage, Text, utc_now,
)
from prospecting.pipeline.calls import call_free_credit
from prospecting.providers import ProviderClient, ProviderError


class QueryOutcome(Contract):
    query: PlannedQuery
    request_id: UUID | None = None
    status: Literal["succeeded", "failed", "skipped"]
    results: Count = 0
    credits: Money | None = None
    stop_reason: Text | None = None
    error_message: Text | None = None


class ExcludedCandidate(Contract):
    host: Text
    exclusion: ExclusionMatch


class DiscoveryReport(Contract):
    campaign_id: UUID
    queries: list[QueryOutcome]
    raw_hits: Count
    candidates: Count
    discarded: dict[Text, Count]
    selected_company_ids: list[UUID]
    combinations: list[CombinationReport]
    stop_reason: Text | None = None
    exclusions_status: ExclusionStatus = "missing"
    excluded: list[ExcludedCandidate] = Field(default_factory=list)
    reused_company_ids: list[UUID] = Field(default_factory=list)


def _known_companies(db: Database) -> list[Company]:
    """Toda empresa guardada pertenece al menos a un RunItem de alguna campaña."""
    companies = {}
    for campaign in db.list_campaigns():
        for item in db.list_run_items(campaign.id):
            if item.company_id not in companies:
                companies[item.company_id] = db.get_company(item.company_id)
    return list(companies.values())


def run_discovery(db: Database, budget: Budget, client: ProviderClient, campaign_id: UUID, *,
                  account_ref: str, authorization: SpendingAuthorization | None,
                  deadline: float | None = None,
                  exclusions: ExclusionList | None = None) -> DiscoveryReport:
    """Descubre candidatos con Tavily Search y guarda solo los seleccionados.

    Las cuentas excluidas por dominio se descartan antes de seleccionar y no ocupan plaza.
    """
    campaign = db.get_campaign(campaign_id)
    if campaign is None:
        raise ValueError("La campaña no existe.")
    planned = build_search_queries(campaign)
    status = exclusions_status(exclusions)
    if db.list_run_items(campaign_id):
        return DiscoveryReport(
            campaign_id=campaign_id, raw_hits=0, candidates=0, discarded={},
            selected_company_ids=[], combinations=[], stop_reason="already_discovered",
            queries=[QueryOutcome(query=query, status="skipped") for query in planned],
            exclusions_status=status,
        )
    limits = campaign.limits.discovery
    outcomes, hits, discarded, stop = [], [], {}, None
    for index, query in enumerate(planned):
        if stop is not None:
            outcomes.append(QueryOutcome(query=query, status="skipped", stop_reason=stop))
            continue
        usage = None
        try:
            usage, result, observed = call_free_credit(
                budget, client, search_request(query, account_ref, limits),
                TavilySearchResponse, campaign_id=campaign_id, company_id=None,
                credits=SEARCH_CREDITS, authorization=authorization, deadline=deadline,
            )
        except BudgetError as error:
            stop = error.code
            outcomes.append(QueryOutcome(
                query=query, request_id=error.request_id, status="failed",
                stop_reason=error.code, error_message=str(error),
            ))
            continue
        except ProviderError as error:
            reason = classify_tavily_error(error)
            if reason in STOPPING_REASONS:
                stop = reason
            outcomes.append(QueryOutcome(
                query=query, request_id=error.request_id, status="failed",
                stop_reason=reason, error_message=error.message,
            ))
            continue
        query_hits, query_discarded = parse_search(query, index, result.data, usage.request_id, utc_now())
        hits.extend(query_hits)
        for reason, count in query_discarded.items():
            discarded[reason] = discarded.get(reason, 0) + count
        outcomes.append(QueryOutcome(
            query=query, request_id=usage.request_id, status="succeeded",
            results=len(result.data.results), credits=observed,
        ))
    candidates, over_limit = group_candidates(hits, limits.raw_candidates)
    if over_limit:
        discarded["raw_candidate_limit"] = over_limit
    excluded, review, kept = [], {}, []
    for candidate in candidates:
        match = match_exclusion(candidate.host, [candidate.name], [candidate.hits[0].query.country], exclusions)
        if match is not None and match.strength == "confirmed":
            excluded.append(ExcludedCandidate(host=candidate.host, exclusion=match))
            continue
        if match is not None:
            review[candidate.host] = match
        kept.append(candidate)
    if excluded:
        discarded["excluded_account"] = len(excluded)
    selected, combinations = select_candidates(kept, campaign)
    confirmed = [item for item in _known_companies(db) if item.identity_status == IdentityStatus.CONFIRMED]
    company_ids, reused = [], []
    with db.transaction():
        for candidate in selected:
            existing = find_reusable(candidate, confirmed)
            if existing is not None:
                company_id = existing.id
                for item in build_hit_evidence(candidate, company_id):
                    db.save_evidence(item)
                reused.append(company_id)
            else:
                company, evidence = build_company(candidate)
                db.save_company(company, evidence=evidence)
                company_id = company.id
            match = review.get(candidate.host)
            if match is not None:
                db.save_evidence(exclusion_evidence(company_id, match, exclusions))
            db.save_run_item(RunItem(
                campaign_id=campaign_id, company_id=company_id,
                stop_reason=None if match is None else "exclusion_review",
            ))
            company_ids.append(company_id)
    return DiscoveryReport(
        campaign_id=campaign_id, queries=outcomes, raw_hits=len(hits),
        candidates=len(candidates), discarded=discarded, selected_company_ids=company_ids,
        combinations=combinations, stop_reason=stop, exclusions_status=status,
        excluded=excluded, reused_company_ids=reused,
    )


class IdentityReport(Contract):
    campaign_id: UUID
    company_id: UUID
    decision: IdentityDecision
    exclusions_status: ExclusionStatus


def resolve_company_identity(db: Database, campaign_id: UUID, company_id: UUID, *,
                             exclusions: ExclusionList | None = None) -> IdentityReport:
    """Resuelve identidad, duplicados y exclusiones con evidencia guardada; no llama a proveedores.

    Los datos de empresa solo se acumulan: una decisión pendiente nunca degrada una
    identidad ya confirmada en otra campaña.
    """
    campaign = db.get_campaign(campaign_id)
    run_item = db.get_run_item(campaign_id, company_id)
    company = db.get_company(company_id)
    if campaign is None or run_item is None or company is None:
        raise ValueError("La empresa no pertenece a la campaña.")
    campaign_company_ids = {item.company_id for item in db.list_run_items(campaign_id)}
    confirmed = [item for item in _known_companies(db) if item.identity_status == IdentityStatus.CONFIRMED]
    decision = assess_identity(company, db.list_evidence(company_id), campaign, exclusions,
                               confirmed, campaign_company_ids)
    provenance = dict(company.provenance)
    updates = {}
    for field, values, ids in (
        ("operating_countries", decision.operating_countries, decision.country_evidence_ids),
        ("segments", decision.segments, decision.segment_evidence_ids),
    ):
        if values:
            updates[field] = list(dict.fromkeys([*(getattr(company, field) or []), *values]))
            provenance[field] = list(dict.fromkeys([*provenance.get(field, []), *ids]))
    if decision.name is not None and company.identity_status != IdentityStatus.CONFIRMED:
        # El nombre observado en la página propia sustituye al inferido, que queda como alias.
        updates |= {"name": decision.name,
                    "aliases": list(dict.fromkeys([*(company.aliases or []), company.name]))}
        provenance["aliases"] = list(dict.fromkeys([*provenance.get("aliases", []), *provenance["name"]]))
        provenance["name"] = decision.name_evidence_ids
    if decision.status == "confirmed" and company.identity_status != IdentityStatus.CONFIRMED:
        updates |= {"identity_status": IdentityStatus.CONFIRMED, "identity_key": decision.identity_key}
    updated = Company.model_validate(company.model_dump() | updates | {"provenance": provenance})
    stages = list(RunStage)
    stage = run_item.stage
    if decision.status != "pending" and stages.index(stage) < stages.index(RunStage.IDENTITY_RESOLVED):
        stage = RunStage.IDENTITY_RESOLVED
    item_updates = {"stage": stage, "stop_reason": decision.stop_reason, "updated_at": utc_now()}
    if decision.status == "excluded":
        item_updates["business_status"] = BusinessStatus.EXCLUDED
    evidence = [] if decision.exclusion is None else [exclusion_evidence(company_id, decision.exclusion, exclusions)]
    with db.transaction():
        db.save_company(updated, evidence=evidence)
        db.save_run_item(run_item.model_copy(update=item_updates))
    return IdentityReport(campaign_id=campaign_id, company_id=company_id, decision=decision,
                          exclusions_status=exclusions_status(exclusions))
