"""Orquestación mínima: único módulo que reserva gasto y llama a proveedores.

Ninguna transacción queda abierta durante una llamada de red. Solo se admite
crédito gratuito de Tavily: sin un precio acotado por crédito no hay llamada (§14).
"""

from decimal import Decimal
import time
from typing import Literal
from uuid import UUID

from pydantic import Field

from prospecting.budget import Budget, BudgetError, Observation, SpendingAuthorization
from prospecting.db import Database
from prospecting.discovery import (
    SEARCH_CREDITS,
    STOPPING_REASONS, CombinationReport, ExclusionList, ExclusionMatch, ExclusionStatus,
    IdentityDecision, PlannedQuery, TavilyExtractResponse, TavilySearchResponse,
    assess_identity, build_company, build_hit_evidence, build_search_queries,
    classify_tavily_error, exclusion_evidence, exclusions_status, extract_credits,
    extract_query, extract_request, find_reusable, group_candidates, is_non_business,
    match_exclusion, parse_extract, parse_search, search_request, select_candidates, url_host,
)
from prospecting.models import (
    BusinessStatus, Company, Contract, Count, IdentityStatus, Money, RunItem, RunStage, Text,
    Usage, UsageStatus, utc_now,
)
from prospecting.providers import ProviderClient, ProviderError, ProviderRequest


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


class IdentityReport(Contract):
    campaign_id: UUID
    company_id: UUID
    decision: IdentityDecision
    exclusions_status: ExclusionStatus


class UrlFailure(Contract):
    url: Text
    reason: Text


class ExtractReport(Contract):
    campaign_id: UUID
    company_id: UUID
    request_id: UUID | None = None
    requested_urls: list[Text]
    rejected_urls: list[UrlFailure]
    failed_urls: list[UrlFailure]
    evidence_ids: list[UUID]
    credits: Money | None = None
    stop_reason: Text | None = None
    error_message: Text | None = None


def _remaining(deadline: float | None) -> float | None:
    return None if deadline is None else deadline - time.monotonic()


def _credits(data) -> Decimal | None:
    if data.usage is None or data.usage.credits is None:
        return None
    return Decimal(str(data.usage.credits))


def _call(budget: Budget, client: ProviderClient, request: ProviderRequest,
          response_model, *, campaign_id: UUID, company_id: UUID | None, credits: int,
          authorization: SpendingAuthorization | None, deadline: float | None):
    """Reserva, llama y registra créditos observados; devuelve (uso, resultado)."""
    remaining = _remaining(deadline)
    if remaining is not None and remaining <= 0:
        raise BudgetError("time_limit", "Se agotó el tiempo de la etapa antes de llamar.")
    usage = budget.reserve(Usage(
        campaign_id=campaign_id, company_id=company_id, provider=request.provider,
        operation=request.operation, account_ref=request.account_ref,
        request_fingerprint=client.fingerprint(request),
        reserved_cost_usd=Decimal(0), reserved_credits=Decimal(credits),
        funding_source="free_credit", status=UsageStatus.RESERVED,
    ), authorization)
    result = client.request_json(
        usage.request_id, request, response_model,
        authorization=authorization, remaining_seconds=remaining,
    )
    observed = _credits(result.data)
    if observed is not None:
        budget.record_result(usage.request_id, Observation(outcome="succeeded", credits=observed))
    return usage, result, observed


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
            usage, result, observed = _call(
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


def extract_company_pages(db: Database, budget: Budget, client: ProviderClient,
                          campaign_id: UUID, company_id: UUID, urls: list[str], *,
                          account_ref: str, authorization: SpendingAuthorization | None,
                          deadline: float | None = None) -> ExtractReport:
    """Extrae fragmentos mínimos de páginas públicas dentro del cupo inicial de páginas."""
    campaign = db.get_campaign(campaign_id)
    run_item = db.get_run_item(campaign_id, company_id)
    company = db.get_company(company_id)
    if campaign is None or run_item is None or company is None:
        raise ValueError("La empresa no pertenece a la campaña.")
    rejected, valid = [], []
    for url in urls:
        host = url_host(url) if isinstance(url, str) else None
        if host is None:
            rejected.append(UrlFailure(url=str(url)[:300] or "(vacía)", reason="unsafe_url"))
        elif is_non_business(host):
            rejected.append(UrlFailure(url=url.strip(), reason="non_business_domain"))
        elif url.strip() not in valid:
            valid.append(url.strip())
    left = campaign.limits.effort["initial"].pages - run_item.consumed_limits.pages
    requested = valid[:max(0, left)]
    report = {
        "campaign_id": campaign_id, "company_id": company_id, "requested_urls": requested,
        "rejected_urls": rejected, "failed_urls": [], "evidence_ids": [],
    }
    if not requested:
        return ExtractReport(**report, stop_reason="page_limit" if valid else "no_valid_urls")
    request = extract_request(requested, extract_query(campaign), account_ref)
    attempts = run_item.attempts | {"tavily_extract": run_item.attempts.get("tavily_extract", 0) + 1}
    pages = run_item.consumed_limits.model_copy(update={
        "pages": run_item.consumed_limits.pages + len(requested),
    })
    try:
        usage, result, observed = _call(
            budget, client, request, TavilyExtractResponse,
            campaign_id=campaign_id, company_id=company_id,
            credits=extract_credits(len(requested)),
            authorization=authorization, deadline=deadline,
        )
    except BudgetError as error:
        return ExtractReport(**report | {"requested_urls": []}, request_id=error.request_id,
                             stop_reason=error.code, error_message=str(error))
    except ProviderError as error:
        reason = classify_tavily_error(error)
        update = {"error_message": f"{reason}: {error.message}", "error_stage": run_item.stage,
                  "updated_at": utc_now()}
        if not error.no_send:
            update |= {"attempts": attempts, "consumed_limits": pages}
        db.save_run_item(run_item.model_copy(update=update))
        return ExtractReport(**report, request_id=error.request_id,
                             stop_reason=reason, error_message=error.message)
    evidence, failures = parse_extract(company, requested, result.data, usage.request_id, utc_now())
    with db.transaction():
        for item in evidence:
            db.save_evidence(item)
        db.save_run_item(run_item.model_copy(update={
            "attempts": attempts, "consumed_limits": pages,
            "error_message": None, "error_stage": None, "updated_at": utc_now(),
        }))
    return ExtractReport(**report | {
        "failed_urls": [UrlFailure(url=url, reason=reason) for url, reason in failures],
        "evidence_ids": [item.id for item in evidence],
    }, request_id=usage.request_id, credits=observed)
