"""Orquestación mínima: único módulo que reserva gasto y llama a proveedores.

Ninguna transacción queda abierta durante una llamada de red. Solo se admite
crédito gratuito de Tavily: sin un precio acotado por crédito no hay llamada (§14).
"""

from decimal import Decimal
import time
from typing import Literal
from uuid import UUID

from prospecting.budget import Budget, BudgetError, Observation, SpendingAuthorization
from prospecting.db import Database
from prospecting.discovery import (
    SEARCH_CREDITS,
    STOPPING_REASONS, CombinationReport, PlannedQuery, TavilyExtractResponse,
    TavilySearchResponse, build_company, build_search_queries, classify_tavily_error,
    extract_credits, extract_query, extract_request, group_candidates, parse_extract,
    is_non_business, parse_search, search_request, select_candidates, url_host,
)
from prospecting.models import (
    Contract, Count, Money, RunItem, Text, Usage, UsageStatus, utc_now,
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


class DiscoveryReport(Contract):
    campaign_id: UUID
    queries: list[QueryOutcome]
    raw_hits: Count
    candidates: Count
    discarded: dict[Text, Count]
    selected_company_ids: list[UUID]
    combinations: list[CombinationReport]
    stop_reason: Text | None = None


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


def run_discovery(db: Database, budget: Budget, client: ProviderClient, campaign_id: UUID, *,
                  account_ref: str, authorization: SpendingAuthorization | None,
                  deadline: float | None = None) -> DiscoveryReport:
    """Descubre candidatos con Tavily Search y guarda solo los seleccionados."""
    campaign = db.get_campaign(campaign_id)
    if campaign is None:
        raise ValueError("La campaña no existe.")
    planned = build_search_queries(campaign)
    if db.list_run_items(campaign_id):
        return DiscoveryReport(
            campaign_id=campaign_id, raw_hits=0, candidates=0, discarded={},
            selected_company_ids=[], combinations=[], stop_reason="already_discovered",
            queries=[QueryOutcome(query=query, status="skipped") for query in planned],
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
    selected, combinations = select_candidates(candidates, campaign)
    company_ids = []
    with db.transaction():
        for candidate in selected:
            company, evidence = build_company(candidate)
            db.save_company(company, evidence=evidence)
            db.save_run_item(RunItem(campaign_id=campaign_id, company_id=company.id))
            company_ids.append(company.id)
    return DiscoveryReport(
        campaign_id=campaign_id, queries=outcomes, raw_hits=len(hits),
        candidates=len(candidates), discarded=discarded, selected_company_ids=company_ids,
        combinations=combinations, stop_reason=stop,
    )


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
