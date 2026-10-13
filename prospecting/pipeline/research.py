"""Extracción de páginas públicas y ampliación acotada de evidencia dentro del cupo de la empresa."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from prospecting.budget import Budget, BudgetError, SpendingAuthorization
from prospecting.db import Database
from prospecting.discovery import expansion_query, extract_query
from prospecting.models import BusinessStatus, Contract, Money, Text, utc_now
from prospecting.pipeline.calls import call_free_credit, grant_for, was_sent
from prospecting.providers import ProviderClient, ProviderError
from prospecting.providers.tavily import (
    EXTRACT_OPERATION, PROVIDER, SEARCH_CREDITS, SEARCH_OPERATION, TavilyExtractResponse, TavilySearchResponse,
    classify_tavily_error, company_search_evidence, company_search_request, extract_credits, extract_request,
    parse_extract,
)
from prospecting.sources import is_non_business, is_search_evidence, is_search_hit, url_host, within_domain


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
        usage, result, observed = call_free_credit(
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
        if was_sent(budget, error):
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


# Claves persistidas de RunItem.attempts de la ampliación; reanudar depende de estos textos (docs/persistence.md).
EXPANSION_KEY = "research:expansion"
EXPANSION_QUERIES_KEY = "research:web_queries"
EXPANSION_PAGES_KEY = "research:pages"


class ResearchReport(Contract):
    campaign_id: UUID
    company_id: UUID
    status: Literal["researched", "skipped", "pending"]
    request_ids: list[UUID] = Field(default_factory=list)
    requested_urls: list[Text] = Field(default_factory=list)
    failed_urls: list[UrlFailure] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    stop_reason: Text | None = None
    error_message: Text | None = None


def _rank(item) -> int:
    """Puesto del resultado del buscador guardado en `external_reference` (`<solicitud>#<puesto>`)."""
    rank = (item.external_reference or "").rpartition("#")[2]
    return int(rank) if rank.isdigit() else 10**6


def _checkpoint(db: Database, campaign_id: UUID, company_id: UUID, *, attempts=None, consumed=None,
                error=None, facts=()) -> None:
    """Guarda juntos la evidencia, los intentos y los límites consumidos sobre el último RunItem."""
    with db.transaction():
        run_item = db.get_run_item(campaign_id, company_id)
        counters = run_item.consumed_limits.model_dump()
        for name, amount in (consumed or {}).items():
            counters[name] += amount
        for fact in facts:
            db.save_evidence(fact)
        db.save_run_item(run_item.model_copy(update={
            "attempts": run_item.attempts | {key: run_item.attempts.get(key, 0) + amount
                                             for key, amount in (attempts or {}).items()},
            "consumed_limits": type(run_item.consumed_limits).model_validate(counters),
            "error_message": error, "error_stage": None if error is None else run_item.stage,
            "updated_at": utc_now(),
        }))


def research_company(db: Database, budget: Budget, client: ProviderClient, campaign_id: UUID,
                     company_id: UUID, *, account_ref: str,
                     authorizations: list[SpendingAuthorization] | None,
                     deadline: float | None = None) -> ResearchReport:
    """Ampliación acotada de evidencia, una sola vez por empresa, con el esfuerzo `insufficient_evidence` (§7, §9).

    Una búsqueda Tavily restringida al dominio de la empresa y la extracción de páginas propias
    aún no leídas. No decide la prioridad: después se resuelve la identidad y se recalifica.
    Una llamada enviada se cuenta aunque falle y nunca se repite; reanudar continúa la misma ampliación.
    """
    campaign = db.get_campaign(campaign_id)
    run_item = db.get_run_item(campaign_id, company_id)
    company = db.get_company(company_id)
    if campaign is None or run_item is None or company is None:
        raise ValueError("La empresa no pertenece a la campaña.")
    base = {"campaign_id": campaign_id, "company_id": company_id}
    limits, effort = campaign.limits, campaign.limits.effort["insufficient_evidence"]
    if (run_item.business_status == BusinessStatus.EXCLUDED or company.domain is None
            or is_non_business(company.domain)):
        return ResearchReport(**base, status="skipped", stop_reason="research_preconditions")
    if not run_item.attempts.get(EXPANSION_KEY, 0):
        if limits.evidence_expansions_per_company < 1:
            return ResearchReport(**base, status="skipped", stop_reason="expansion_limit")
        _checkpoint(db, campaign_id, company_id, attempts={EXPANSION_KEY: 1})
    report = {"request_ids": [], "evidence_ids": []}

    def call(request, response_model, credits, operation):
        """Devuelve (uso, resultado) o un informe pendiente; registra el consumo de lo enviado."""
        try:
            usage, result, _ = call_free_credit(
                budget, client, request, response_model, credits=credits, deadline=deadline,
                authorization=grant_for(authorizations, PROVIDER, operation, account_ref), **base)
        except BudgetError as error:
            return None, ResearchReport(**base, **report, status="pending", stop_reason=error.code,
                                        error_message=str(error))
        except ProviderError as error:
            reason = classify_tavily_error(error)
            spent = {} if not was_sent(budget, error) else (
                {"web_queries": 1} if operation == SEARCH_OPERATION else {"pages": len(request.payload["urls"])})
            key = EXPANSION_QUERIES_KEY if operation == SEARCH_OPERATION else EXPANSION_PAGES_KEY
            _checkpoint(db, campaign_id, company_id, error=f"{reason}: {error.message}",
                        attempts={key: amount for amount in spent.values()}, consumed=spent)
            report["request_ids"].append(error.request_id)
            return None, ResearchReport(**base, **report, status="pending", stop_reason=reason,
                                        error_message=error.message)
        report["request_ids"].append(usage.request_id)
        return (usage, result), None

    if db.get_run_item(campaign_id, company_id).attempts.get(EXPANSION_QUERIES_KEY, 0) < effort.web_queries:
        request = company_search_request(company, expansion_query(company, campaign), account_ref)
        done, pending = call(request, TavilySearchResponse, SEARCH_CREDITS, SEARCH_OPERATION)
        if pending is not None:
            return pending
        facts = company_search_evidence(company, done[1].data, done[0].request_id, utc_now())
        _checkpoint(db, campaign_id, company_id, attempts={EXPANSION_QUERIES_KEY: 1},
                    consumed={"web_queries": 1}, facts=facts)
        report["evidence_ids"] += [item.id for item in facts]
    facts = db.list_evidence(company_id)
    # Solo cuenta como leída una página observada; el nombre inferido cita la URL sin haberla leído.
    read = {str(item.url) for item in facts if item.url is not None and item.kind == "observed"
            and not is_search_evidence(item)}
    # Primero los resultados más recientes (los de la ampliación) y, entre ellos, por puesto.
    hits = sorted((item for item in facts if is_search_hit(item) and item.url is not None),
                  key=lambda item: (-item.retrieved_at.timestamp(), _rank(item), str(item.url)))
    urls = list(dict.fromkeys(
        str(item.url) for item in hits if str(item.url) not in read and url_host(str(item.url)) is not None
        and within_domain(url_host(str(item.url)), company.domain)))
    left = effort.pages - db.get_run_item(campaign_id, company_id).attempts.get(EXPANSION_PAGES_KEY, 0)
    urls = urls[:max(0, left)]
    if not urls:
        return ResearchReport(**base, **report, status="researched",
                              stop_reason="no_new_sources" if left > 0 else "page_limit")
    done, pending = call(extract_request(urls, extract_query(campaign), account_ref), TavilyExtractResponse,
                         extract_credits(len(urls)), EXTRACT_OPERATION)
    if pending is not None:
        return pending
    evidence, failures = parse_extract(company, urls, done[1].data, done[0].request_id, utc_now())
    _checkpoint(db, campaign_id, company_id, attempts={EXPANSION_PAGES_KEY: len(urls)},
                consumed={"pages": len(urls)}, facts=evidence)
    return ResearchReport(**base, **report | {"evidence_ids": report["evidence_ids"] + [item.id for item in evidence]},
                          status="researched", requested_urls=urls,
                          failed_urls=[UrlFailure(url=url, reason=reason) for url, reason in failures])
