"""Orquestación mínima: único módulo que reserva gasto y llama a proveedores.

Ninguna transacción queda abierta durante una llamada de red. Tavily solo se usa con
crédito gratuito y Haiku con su precio publicado: sin un precio acotado no hay llamada (§14).
"""

from datetime import timedelta
from decimal import Decimal
import time
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool

from prospecting.budget import Budget, BudgetError, Observation, SpendingAuthorization
from prospecting.db import Database
from prospecting.contacts import (
    ContactError, HunterAccess, HunterDomainSearchResponse, HunterFinderResponse, HunterVerifierResponse,
    apply_target_roles, build_contacts_request, channel_is_usable, derive_readiness,
    classify_hunter_error, domain_search_request, finder_request, merge_contact, parse_contacts_output,
    parse_domain_search, parse_finder, parse_verifier, target_departments, target_roles,
    validate_contact, verifier_request,
)
from prospecting.discovery import (
    SEARCH_CREDITS,
    SEARCH_HIT_CLAIM,
    STOPPING_REASONS, CombinationReport, ExclusionList, ExclusionMatch, ExclusionStatus,
    IdentityDecision, PlannedQuery, TavilyExtractResponse, TavilySearchResponse,
    assess_identity, build_company, build_hit_evidence, build_search_queries,
    classify_tavily_error, exclusion_evidence, exclusions_status, extract_credits,
    extract_query, extract_request, find_reusable, group_candidates, is_non_business,
    match_exclusion, parse_extract, parse_search, search_request, select_candidates, url_host,
)
from prospecting.models import (
    Assessment, BusinessStatus, Company, Contract, Count, IdentityStatus, Money, Priority,
    Contact, Evidence, RunItem, RunStage, Text, TokenUsage, Usage, UsageStatus, utc_now,
)
from prospecting.providers import (
    CLAUDE_OPERATION, CLAUDE_PRICES_PER_MTOK, CLAUDE_PROVIDER, ClaudeClient, ProviderClient,
    ProviderError, ProviderRequest,
)
from prospecting.qualification import (
    MODEL_ID, PROMPT_VERSION, QualificationError, build_haiku_request, classify,
    explanation_text, identity_confirmed, material_contradiction, parse_output, primary_support,
    rubric_for, unknown_criteria, validate_output,
)


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


class QualificationReport(Contract):
    campaign_id: UUID
    company_id: UUID
    status: Literal["assessed", "already_assessed", "pending"]
    assessment_id: UUID | None = None
    priority: Priority | None = None
    fit_score: float | None = None
    coverage: float | None = None
    reason: Text | None = None
    called_model: StrictBool = False
    request_id: UUID | None = None
    tokens: TokenUsage | None = None
    estimated_cost_usd: Money | None = None
    error_message: Text | None = None


_FINAL_STATUS = {Priority.LOW: BusinessStatus.LOW_FIT}


def _reserved_claude_cost(model: str, max_input: int, max_output: int) -> Decimal:
    price_in, price_out = CLAUDE_PRICES_PER_MTOK[model]
    return (max_input * price_in + max_output * price_out) / Decimal(1_000_000)


def _store_assessment(db: Database, run_item: RunItem, assessment: Assessment, *, stop_reason) -> Assessment:
    stages = list(RunStage)
    stage = max(run_item.stage, RunStage.ASSESSED, key=stages.index)
    update = {"stage": stage, "last_assessment_id": assessment.id, "stop_reason": stop_reason,
              "error_message": None, "error_stage": None, "updated_at": utc_now()}
    if assessment.priority in _FINAL_STATUS:
        update["business_status"] = _FINAL_STATUS[assessment.priority]
    with db.transaction():
        saved = db.save_assessment(assessment)
        db.save_run_item(run_item.model_copy(update=update))
    return saved


def qualify_company(db: Database, budget: Budget, claude: ClaudeClient, campaign_id: UUID,
                    company_id: UUID, *, account_ref: str,
                    funding_source: Literal["free_credit", "prepaid", "new_outlay"],
                    authorization: SpendingAuthorization | None,
                    deadline: float | None = None) -> QualificationReport:
    """Haiku evalúa criterios con evidencia guardada; Python valida, puntúa y decide la prioridad.

    Sin identidad confirmada o con exclusión no se consulta a Haiku. Un fallo deja la
    evaluación pendiente con su motivo literal, sin reintentar ni cambiar de modelo (§12.2).
    `insufficient_evidence` no se fija como resultado comercial: queda una ampliación (§7).
    """
    campaign = db.get_campaign(campaign_id)
    run_item = db.get_run_item(campaign_id, company_id)
    company = db.get_company(company_id)
    if campaign is None or run_item is None or company is None:
        raise ValueError("La empresa no pertenece a la campaña.")
    base = {"campaign_id": campaign_id, "company_id": company_id}
    previous = [item for item in db.list_assessments(campaign_id, company_id)
                if item.rubric_version == campaign.rubric_version]
    latest = previous[-1] if previous else None
    modeled = [item for item in previous if item.prompt_version == PROMPT_VERSION]
    if modeled:
        return QualificationReport(**base, status="already_assessed", assessment_id=modeled[-1].id,
                                   priority=modeled[-1].priority, fit_score=modeled[-1].fit_score,
                                   coverage=modeled[-1].coverage)

    def pending(reason, message, **extra):
        db.save_run_item(run_item.model_copy(update={
            "stop_reason": f"assessment_pending:{reason}", "error_message": message,
            "error_stage": RunStage.ASSESSED, "updated_at": utc_now(),
        }))
        return QualificationReport(**base, status="pending", reason=reason, error_message=message, **extra)

    def without_model(priority, reason, explanation, stop_reason):
        if latest is not None and latest.model_id is None and latest.priority == priority:
            return QualificationReport(**base, status="already_assessed", assessment_id=latest.id,
                                       priority=priority, coverage=latest.coverage, reason=reason)
        assessment = _store_assessment(db, run_item, Assessment(
            **base, criteria=unknown_criteria(explanation), fit_score=None, coverage=0.0,
            priority=priority, rubric_version=campaign.rubric_version, explanation=explanation,
            revision_of=None if latest is None else latest.id,
        ), stop_reason=stop_reason)
        return QualificationReport(**base, status="assessed", assessment_id=assessment.id,
                                   priority=priority, coverage=0.0, reason=reason)

    if run_item.business_status == BusinessStatus.EXCLUDED:
        return without_model(Priority.EXCLUDED, "confirmed_exclusion",
                             "Exclusión confirmada antes de investigar; no se consultó a Haiku.",
                             run_item.stop_reason)
    if not identity_confirmed(company):
        return without_model(
            Priority.INSUFFICIENT_EVIDENCE, "identity_unconfirmed",
            f"Identidad no confirmada ({run_item.stop_reason or 'pendiente'}); no se consultó a Haiku.",
            "insufficient_evidence:identity_unconfirmed",
        )
    evidence = db.list_evidence(company_id)
    try:
        payload, selected = build_haiku_request(company, evidence, campaign)
    except QualificationError as error:
        return pending(error.code, error.message)
    if not selected:
        return without_model(Priority.INSUFFICIENT_EVIDENCE, "no_evidence",
                             "No hay evidencia utilizable de la empresa; no se consultó a Haiku.",
                             "insufficient_evidence:no_evidence")
    remaining = _remaining(deadline)
    if remaining is not None and remaining <= 0:
        return pending("time_limit", "Se agotó el tiempo de la etapa antes de llamar.")
    limits = campaign.limits.llm
    try:
        usage = budget.reserve(Usage(
            **base, provider=CLAUDE_PROVIDER, operation=CLAUDE_OPERATION, account_ref=account_ref,
            request_fingerprint=claude.fingerprint(payload, account_ref),
            reserved_cost_usd=_reserved_claude_cost(MODEL_ID, limits.max_input_tokens, limits.max_output_tokens),
            reserved_credits=Decimal(0),
            reserved_tokens=TokenUsage(input_tokens=limits.max_input_tokens, output_tokens=limits.max_output_tokens),
            funding_source=funding_source, status=UsageStatus.RESERVED,
        ), authorization)
        call = claude.create(usage.request_id, payload, account_ref=account_ref,
                             authorization=authorization, remaining_seconds=remaining)
    except BudgetError as error:
        return pending(error.code, str(error), request_id=error.request_id)
    except ProviderError as error:
        reason = f"http_{error.http_status}" if error.kind == "http" else error.kind
        return pending(reason, error.message, request_id=error.request_id, called_model=not error.no_send)
    spent = {"called_model": True, "request_id": call.request_id, "tokens": call.tokens,
             "estimated_cost_usd": call.estimated_cost_usd}
    try:
        output = parse_output(call.text, call.stop_reason)
        criteria = validate_output(output, selected, campaign)
    except QualificationError as error:
        return pending(error.code, error.message, **spent)
    result = classify(
        criteria, rubric_for(campaign), excluded=False, identity_confirmed=True,
        contradiction=material_contradiction(output, criteria, selected),
        primary_support=primary_support(criteria, selected),
    )
    assessment = _store_assessment(db, run_item, Assessment(
        **base, criteria=criteria, fit_score=result.fit_score, coverage=result.coverage,
        priority=result.priority, products=list(dict.fromkeys(output.products)),
        target_roles=list(dict.fromkeys(output.target_roles)), model_id=call.model,
        prompt_version=PROMPT_VERSION, rubric_version=campaign.rubric_version,
        explanation=explanation_text(output), revision_of=None if latest is None else latest.id,
    ), stop_reason={
        Priority.LOW: "low_fit", Priority.INSUFFICIENT_EVIDENCE: f"insufficient_evidence:{result.reason}",
    }.get(result.priority))
    return QualificationReport(**base, status="assessed", assessment_id=assessment.id,
                               priority=result.priority, fit_score=result.fit_score,
                               coverage=result.coverage, reason=result.reason, **spent)


class ContactReport(Contract):
    campaign_id: UUID
    company_id: UUID
    status: Literal["checked", "already_checked", "pending", "skipped"]
    business_status: BusinessStatus | None = None
    contact_ids: list[UUID] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    request_ids: list[UUID] = Field(default_factory=list)
    stop_reason: Text | None = None
    error_message: Text | None = None
    warnings: list[Text] = Field(default_factory=list)


def _contact_error_reason(error) -> str:
    if isinstance(error, BudgetError):
        return error.code
    if isinstance(error, ContactError):
        return error.code
    if error.provider == "hunter":
        return classify_hunter_error(error)
    return classify_tavily_error(error)


def find_contacts(db: Database, budget: Budget, client: ProviderClient, campaign_id: UUID,
                  company_id: UUID, *, hunter_access: HunterAccess | None = None,
                  authorizations: list[SpendingAuthorization] | None = None,
                  tavily_account_ref: str | None = None, claude: ClaudeClient | None = None,
                  claude_account_ref: str | None = None,
                  claude_funding_source: Literal["free_credit", "prepaid", "new_outlay"] = "prepaid",
                  deadline: float | None = None) -> ContactReport:
    """Investiga una empresa calificada con cupos persistidos y fuentes nominales.

    Los permisos deben estar registrados en Budget por el responsable de esta sesión.
    No hay polling, envío, cambios de cuenta ni reintentos de solicitudes enviadas.
    """
    campaign, company = db.get_campaign(campaign_id), db.get_company(company_id)
    run = db.get_run_item(campaign_id, company_id)
    if campaign is None or company is None or run is None:
        raise ValueError("La empresa no pertenece a la campaña.")
    assessment = None if run.last_assessment_id is None else db.get_assessment(run.last_assessment_id)
    base = {"campaign_id": campaign_id, "company_id": company_id}
    if (run.business_status == BusinessStatus.EXCLUDED or assessment is None
            or assessment.priority not in (Priority.MEDIUM, Priority.HIGH)
            or company.identity_status != IdentityStatus.CONFIRMED
            or company.domain is None or is_non_business(company.domain)):
        return ContactReport(**base, status="skipped", business_status=run.business_status,
                             stop_reason="contact_preconditions")
    if hunter_access is not None:
        hunter_access = HunterAccess.model_validate(hunter_access)
    effort = campaign.limits.effort[str(assessment.priority)]
    roles = target_roles(company, assessment, campaign)
    if not roles:
        return ContactReport(**base, status="skipped", stop_reason="no_target_roles")
    requests, evidence_ids, warnings = [], [], []
    if hunter_access is not None and not hunter_access.automatic_lead_saving_disabled and any(
            operation in hunter_access.enabled_operations for operation in ("email_finder", "email_verifier")):
        warnings.append("Finder y Verifier deshabilitados: falta comprobar que no guardan leads automáticamente.")
    tick = time.monotonic()
    local_deadline = tick + max(0.0, effort.active_seconds - run.consumed_limits.contacts_active_seconds)
    deadline = local_deadline if deadline is None else min(deadline, local_deadline)
    grants = authorizations or []

    def grant(provider, operation, account):
        return next((item for item in grants if
                     (item.provider, item.operation, item.account_ref) == (provider, operation, account)), None)

    def checkpoint(*, attempts=None, consumed=None, updates=None, aggregates=(), facts=()):
        nonlocal run, tick
        now_tick = time.monotonic()
        elapsed = max(0.0, now_tick - tick)
        current = db.get_run_item(campaign_id, company_id)
        counters = current.consumed_limits.model_dump()
        for name, amount in (consumed or {}).items():
            counters[name] += amount
        counters["active_seconds"] += elapsed
        counters["contacts_active_seconds"] += elapsed
        selection = {key: value for key, value in run.attempts.items() if key.startswith("contacts:person:")}
        changes = {"attempts": current.attempts | selection | (attempts or {}),
                   "consumed_limits": type(current.consumed_limits).model_validate(counters),
                   "updated_at": utc_now()} | (updates or {})
        with db.transaction():
            for contact, source in aggregates:
                db.save_contact(contact, evidence=source)
                evidence_ids.extend(item.id for item in source)
            for fact in facts:
                db.save_evidence(fact)
                evidence_ids.append(fact.id)
            run = db.save_run_item(current.model_copy(update=changes))
        tick = now_tick

    def people():
        now = utc_now()
        facts = db.list_evidence(company_id)
        fresh_ids = {item.contact_id for item in facts if item.contact_id is not None
                     and now - timedelta(days=campaign.limits.cache.contact_days) <= item.retrieved_at <= now}
        return [item for item in db.list_contacts(company_id) if item.id in fresh_ids]

    def readiness():
        return derive_readiness(assessment, people(), db.list_evidence(company_id),
                                campaign.limits, utc_now(), company)

    def finish(reason, *, status="checked", message=None):
        state = readiness()
        updates = {"business_status": state, "stop_reason": reason,
                   "error_message": message,
                   "error_stage": RunStage.CONTACTS_CHECKED if status == "pending" else None}
        if status == "checked":
            updates["stage"] = max(run.stage, RunStage.CONTACTS_CHECKED, key=list(RunStage).index)
        checkpoint(updates=updates)
        return ContactReport(**base, status=status, business_status=state,
                             contact_ids=[item.id for item in people()],
                             evidence_ids=list(dict.fromkeys(evidence_ids)),
                             request_ids=list(dict.fromkeys(requests)), stop_reason=reason,
                             error_message=message, warnings=warnings)

    def processed_key(fingerprint):
        return f"contacts:processed:{fingerprint}"

    def cached(fingerprint, provider, operation, account, days):
        now = utc_now()
        rows = [row for row in db.list_usage(company_id=company_id, provider=provider)
                if (row.operation, row.account_ref, row.request_fingerprint) == (operation, account, fingerprint)]
        for row in reversed(rows):
            previous = db.get_run_item(row.campaign_id, company_id)
            done = previous.attempts.get(processed_key(fingerprint), 0)
            if row.status in (UsageStatus.IN_FLIGHT, UsageStatus.UNCERTAIN):
                raise BudgetError("request_uncertain", "Hay una llamada enviada pendiente de resultado o conciliación.", row.request_id)
            if row.status not in (UsageStatus.RESERVED, UsageStatus.RECONCILED) and not done:
                raise BudgetError("result_unavailable", "La llamada fue enviada, pero falta su resultado persistido.", row.request_id)
            if row.campaign_id == campaign_id:
                if row.status != UsageStatus.RESERVED and not done:
                    raise BudgetError("result_unavailable", "La llamada fue enviada, pero falta su resultado persistido.", row.request_id)
                if done:
                    requests.append(row.request_id)
                    return True
            elif (done and row.outcome == "succeeded"
                  and now - timedelta(days=days) <= (row.finished_at or row.created_at) <= now):
                requests.append(row.request_id)
                checkpoint(attempts={processed_key(fingerprint): 1})
                return True
        return False

    def reserve(request, fingerprint, credits, funding):
        cost = Decimal(0)
        if funding != "free_credit":
            account = next((item for item in budget.account_allowances if
                            (item.provider, item.account_ref, item.funding_source) ==
                            (request.provider, request.account_ref, funding)), None)
            if account is None or account.credit_valuation is None:
                raise BudgetError("price_unbounded", "Falta la valoración comprobada del crédito de esta cuenta.")
            cost = credits * account.credit_valuation.unit_value_usd
        return budget.reserve(Usage(
            **base, provider=request.provider, operation=request.operation,
            account_ref=request.account_ref, request_fingerprint=fingerprint,
            reserved_credits=credits, reserved_cost_usd=cost,
            funding_source=funding, status=UsageStatus.RESERVED,
        ), grant(request.provider, request.operation, request.account_ref))

    def perform(request, response_model, *, credits, count_key, cap, consumed,
                parse, funding="free_credit", pages=0):
        fingerprint = client.fingerprint(request)
        days = campaign.limits.cache.web_days if request.provider == "tavily" else campaign.limits.cache.contact_days
        if cached(fingerprint, request.provider, request.operation, request.account_ref, days):
            return
        if run.attempts.get(count_key, 0) >= cap:
            return
        if _remaining(deadline) <= 0:
            raise BudgetError("time_limit", "Se agotó el tiempo de contactos antes de llamar.")
        usage = reserve(request, fingerprint, Decimal(credits), funding)
        requests.append(usage.request_id)
        checkpoint(attempts={f"contacts:request:{usage.request_id}": 1})
        attempts = {count_key: run.attempts.get(count_key, 0) + 1}
        if pages:
            attempts["contacts:pages"] = run.attempts.get("contacts:pages", 0) + pages
        try:
            result = client.request_json(usage.request_id, request, response_model,
                                         authorization=grant(request.provider, request.operation, request.account_ref),
                                         remaining_seconds=_remaining(deadline))
        except (ProviderError, BudgetError) as error:
            current_usage = db.get_usage(usage.request_id)
            if current_usage.status != UsageStatus.RESERVED and not getattr(error, "no_send", False):
                checkpoint(attempts=attempts, consumed=consumed)
            raise
        if request.provider == "tavily":
            observed = _credits(result.data)
            if observed is not None:
                budget.record_result(usage.request_id, Observation(outcome="succeeded", credits=observed))
        if result.http_status == 202:
            checkpoint(attempts=attempts, consumed=consumed)
            raise BudgetError("verification_pending", "Hunter mantiene la verificación en procesamiento.", usage.request_id)
        try:
            aggregates, facts = parse(result.data, usage.request_id)
        except (ContactError, ValueError, TypeError):
            checkpoint(attempts=attempts, consumed=consumed)
            raise BudgetError("invalid_contact_data", "La respuesta no respalda los datos de contacto esperados.", usage.request_id) from None
        checkpoint(attempts=attempts | {processed_key(fingerprint): 1}, consumed=consumed,
                   aggregates=aggregates, facts=facts)

    def save_candidates(parsed):
        facts = db.list_evidence(company_id)
        known = db.list_contacts(company_id)
        selected = {UUID(key.split(":")[-1]) for key in run.attempts if key.startswith("contacts:person:")}
        def rank(pair):
            contact = pair[0]
            return (contact.name_complete is not True, contact.title not in roles,
                    not any(channel.normalized_status == "verified" for channel in contact.channels))
        saved = []
        for candidate, source in sorted(parsed, key=rank):
            match = next((old for old in known if old.id == candidate.id or any(
                a.type == b.type and a.type in ("email", "linkedin") and a.value == b.value
                for a in old.channels for b in candidate.channels)), None)
            if match is not None:
                old_id = candidate.id
                candidate = candidate.model_copy(update={"id": match.id, "channels": [
                    channel.model_copy(update={"contact_id": match.id}) for channel in candidate.channels]})
                source = [item.model_copy(update={"contact_id": match.id}) if item.contact_id == old_id else item for item in source]
                candidate = merge_contact(match, candidate, facts + source)
            if candidate.id not in selected and len(selected) >= effort.people:
                continue
            candidate, role_facts = apply_target_roles(candidate, roles, facts + source)
            source += role_facts
            selected.add(candidate.id)
            saved.append((candidate, source))
        # La selección se persiste junto al resultado, sin reservar una persona por su nombre.
        for candidate, _ in saved:
            run.attempts[f"contacts:person:{candidate.id}"] = 1
        return saved, []

    if list(RunStage).index(run.stage) >= list(RunStage).index(RunStage.CONTACTS_CHECKED):
        return finish(run.stop_reason or "already_checked", status="already_checked")
    if effort.people == 0:
        return finish("people_limit")
    try:
        for key in run.attempts:
            if not key.startswith("contacts:request:"):
                continue
            prior = db.get_usage(UUID(key.split(":")[-1]))
            if prior is not None and prior.status != UsageStatus.RESERVED and not run.attempts.get(processed_key(prior.request_fingerprint), 0):
                requests.append(prior.request_id)
                return finish(run.stop_reason or "result_unavailable", status="pending",
                              message=run.error_message or "Hay una llamada enviada sin resultado validado persistido.")
        for key in run.attempts:
            if key.startswith("contacts:haiku_request:"):
                prior = db.get_usage(UUID(key.split(":")[-1]))
                if prior is not None and not run.attempts.get(processed_key(prior.request_fingerprint), 0):
                    return finish(run.stop_reason or "result_unavailable", status="pending",
                                  message=run.error_message or "La extracción enviada no tiene un resultado validado persistido.")
        if readiness() == BusinessStatus.READY_PREFERRED:
            return finish("preferred_channel_found")
        existing_eligible = [item for item in people() if validate_contact(
            item, company, assessment, db.list_evidence(company_id), campaign.limits, utc_now())]
        if existing_eligible:
            selected = {key.split(":")[-1] for key in run.attempts if key.startswith("contacts:person:")}
            additions = {}
            for item in existing_eligible:
                if str(item.id) not in selected and len(selected) < effort.people:
                    selected.add(str(item.id))
                    additions[f"contacts:person:{item.id}"] = 1
            checkpoint(attempts=additions)
        degraded_error = None
        hunter_available = hunter_access is not None and "domain_search" in hunter_access.enabled_operations
        if hunter_available:
            for index in range(effort.people_queries):
                request = domain_search_request(company, roles, hunter_access.search_account_ref,
                                                departments=target_departments(roles) if index else None)
                try:
                    perform(request, HunterDomainSearchResponse, credits=1,
                            count_key="contacts:domain_search", cap=effort.people_queries,
                            consumed={"people_queries": 1}, funding=hunter_access.funding_source,
                            parse=lambda data, request_id: save_candidates(parse_domain_search(company, data, request_id, utc_now())))
                except (BudgetError, ProviderError) as error:
                    if _contact_error_reason(error) not in ("permission_denied", "rate_limited", "quota_exceeded", "local_error"):
                        raise
                    warnings.append(f"Hunter: {_contact_error_reason(error)}: {error}")
                    degraded_error = error
                    hunter_available = False
                    break
                if readiness() == BusinessStatus.READY_PREFERRED:
                    return finish("preferred_channel_found")

        now = utc_now()
        stored_public = [item for item in db.list_evidence(company_id) if item.source_type == "primary"
                         and item.excerpt and item.url is not None
                         and now - timedelta(days=campaign.limits.cache.web_days) <= item.retrieved_at <= now
                         and any(part in str(item.url).lower() for part in ("/equipo", "/team", "/directorio", "/leadership"))]
        if tavily_account_ref is not None and not stored_public and not run.attempts.get("contacts:haiku", 0):
            existing = people()
            queries = [f'"{company.name}" {" ".join(roles[:4])} equipo directorio {" ".join(campaign.countries)}']
            queries += [f'"{item.name}" "{company.name}" {item.title or "cargo actual"}' for item in existing if item.name]
            queries += [f'"{company.name}" equipo producto ingeniería marketing contacto profesional']
            for query in list(dict.fromkeys(queries))[:effort.web_queries]:
                request = ProviderRequest(provider="tavily", operation="search", account_ref=tavily_account_ref,
                                          payload={"query": query, "search_depth": "basic", "topic": "general",
                                                   "max_results": 10, "include_usage": True,
                                                   "exclude_domains": ["linkedin.com"]})
                def public_hits(data, request_id):
                    facts = [Evidence(company_id=company_id, claim=f"{SEARCH_HIT_CLAIM} en una búsqueda pública de contactos; requiere contraste.",
                                      url=hit.url, provider="tavily", external_reference=f"contacts_search:{request_id}:{index}",
                                      excerpt=(hit.content or hit.title or "Resultado sin texto.")[:800],
                                      retrieved_at=utc_now(), kind="observed", source_type="secondary")
                             for index, hit in enumerate(data.results) if url_host(hit.url) is not None
                             and not is_non_business(url_host(hit.url))]
                    return [], facts
                perform(request, TavilySearchResponse, credits=SEARCH_CREDITS,
                        count_key="contacts:web_queries", cap=effort.web_queries,
                        consumed={"web_queries": 1}, parse=public_hits)
            now = utc_now()
            facts = db.list_evidence(company_id)
            urls = list(dict.fromkeys(str(item.url) for item in facts if item.url is not None
                                     and item.external_reference and item.external_reference.startswith("contacts_search:")
                                     and now - timedelta(days=campaign.limits.cache.web_days) <= item.retrieved_at <= now
                                     and url_host(str(item.url)) is not None and not is_non_business(url_host(str(item.url)))))
            left = max(0, effort.pages - run.attempts.get("contacts:pages", 0))
            if urls and left:
                urls = urls[:left]
                request = extract_request(urls, f'{company.name}; {"; ".join(roles)}; equipo y contacto nominal', tavily_account_ref)
                def extracted(data, request_id):
                    facts, failures = parse_extract(company, urls, data, request_id, utc_now())
                    warnings.extend(f"Tavily Extract: {reason}" for _, reason in failures)
                    return [], facts
                perform(request, TavilyExtractResponse, credits=extract_credits(len(urls)),
                        count_key="contacts:extract", cap=effort.pages,
                        consumed={"pages": len(urls)}, pages=len(urls), parse=extracted)

        if claude is not None and claude_account_ref is not None and not run.attempts.get("contacts:haiku", 0):
            now = utc_now()
            public = [item for item in db.list_evidence(company_id) if item.excerpt is not None
                      and item.source_type in ("primary", "secondary")
                      and not (item.external_reference or "").startswith("contacts_search:")
                      and now - timedelta(days=campaign.limits.cache.web_days) <= item.retrieved_at <= now]
            if public:
                payload, supplied = build_contacts_request(company, assessment, campaign, public, people())
                if supplied:
                    fingerprint = claude.fingerprint(payload, claude_account_ref)
                    if not cached(fingerprint, CLAUDE_PROVIDER, CLAUDE_OPERATION, claude_account_ref, campaign.limits.cache.contact_days):
                        if _remaining(deadline) <= 0:
                            raise BudgetError("time_limit", "Se agotó el tiempo antes de extraer contactos.")
                        limits = campaign.limits.llm
                        usage = budget.reserve(Usage(
                            **base, provider=CLAUDE_PROVIDER, operation=CLAUDE_OPERATION, account_ref=claude_account_ref,
                            request_fingerprint=fingerprint, reserved_credits=Decimal(0),
                            reserved_tokens=TokenUsage(input_tokens=limits.max_input_tokens, output_tokens=limits.max_output_tokens),
                            reserved_cost_usd=_reserved_claude_cost(MODEL_ID, limits.max_input_tokens, limits.max_output_tokens),
                            funding_source=claude_funding_source, status=UsageStatus.RESERVED,
                        ), grant(CLAUDE_PROVIDER, CLAUDE_OPERATION, claude_account_ref))
                        requests.append(usage.request_id)
                        try:
                            call = claude.create(usage.request_id, payload, account_ref=claude_account_ref,
                                                 authorization=grant(CLAUDE_PROVIDER, CLAUDE_OPERATION, claude_account_ref),
                                                 remaining_seconds=_remaining(deadline))
                        finally:
                            if db.get_usage(usage.request_id).status != UsageStatus.RESERVED:
                                checkpoint(attempts={"contacts:haiku": 1, f"contacts:haiku_request:{usage.request_id}": 1})
                        try:
                            parsed = parse_contacts_output(call.text, call.stop_reason, company, assessment, campaign,
                                                           supplied, utc_now(), usage.request_id, contacts=people())
                            aggregates, facts = save_candidates(parsed)
                        except ContactError:
                            raise
                        except (ValueError, TypeError):
                            raise BudgetError("invalid_contact_output", "Haiku no devolvió hechos de contacto respaldados.", usage.request_id) from None
                        checkpoint(attempts={processed_key(fingerprint): 1}, aggregates=aggregates, facts=facts)

        for contact in people():
            selected = {key.split(":")[-1] for key in run.attempts if key.startswith("contacts:person:")}
            if str(contact.id) not in selected:
                if len(selected) >= effort.people:
                    continue
                checkpoint(attempts={f"contacts:person:{contact.id}": 1})
            if not validate_contact(contact, company, assessment, db.list_evidence(company_id), campaign.limits, utc_now()):
                continue
            if any(channel_is_usable(channel, contact, db.list_evidence(company_id), campaign.limits, utc_now())
                   and channel.type in ("email", "phone", "whatsapp") for channel in contact.channels):
                return finish("preferred_channel_found")
            if hunter_access is None or degraded_error is not None:
                continue
            cap, key = effort.enrichments_per_provider, "contacts:hunter_enrichments"
            if (not any(channel.type == "email" and channel.professional is True for channel in contact.channels)
                    and "email_finder" in hunter_access.enabled_operations
                    and hunter_access.automatic_lead_saving_disabled):
                request = finder_request(contact, company, hunter_access.search_account_ref)
                perform(request, HunterFinderResponse, credits=1, count_key=key, cap=cap,
                        consumed={"enrichments": 1}, funding=hunter_access.funding_source,
                        parse=lambda data, request_id: ([(parse_finder(contact, company, data, request_id, utc_now()))], []))
                contact = db.get_contact(contact.id)
                if readiness() == BusinessStatus.READY_PREFERRED:
                    return finish("preferred_channel_found")
            if "email_verifier" not in hunter_access.enabled_operations or not hunter_access.automatic_lead_saving_disabled:
                continue
            for channel in contact.channels:
                if channel.type != "email" or channel.professional is not True or channel.direct is not True:
                    continue
                if channel_is_usable(channel, contact, db.list_evidence(company_id), campaign.limits, utc_now()):
                    continue
                request = verifier_request(channel.value, hunter_access.verification_account_ref or hunter_access.search_account_ref)
                channel_key = f"contacts:verify:{client.fingerprint(request)}"
                if run.attempts.get(channel_key, 0) >= campaign.limits.email_verifications_per_channel:
                    continue
                def verified(data, request_id):
                    return [parse_verifier(contact, company, data, request_id, utc_now())], []
                before = run.attempts.get(key, 0)
                try:
                    perform(request, HunterVerifierResponse, credits="0.5" if hunter_access.unified_credits else "1",
                            count_key=key, cap=cap, consumed={"enrichments": 1, "email_verifications": 1},
                            funding=hunter_access.funding_source, parse=verified)
                finally:
                    if run.attempts.get(key, 0) > before:
                        checkpoint(attempts={channel_key: 1})
                if readiness() == BusinessStatus.READY_PREFERRED:
                    return finish("preferred_channel_found")
        if degraded_error is not None and not (run.attempts.get("contacts:web_queries", 0) or run.attempts.get("contacts:haiku", 0)):
            raise degraded_error
        return finish("contact_plan_exhausted")
    except (BudgetError, ProviderError, ContactError) as error:
        if getattr(error, "request_id", None) is not None:
            requests.append(error.request_id)
        return finish(_contact_error_reason(error), status="pending", message=str(error))
    except (ValueError, TypeError):
        return finish("invalid_contact_data", status="pending", message="No se pudieron validar los hechos de contacto.")
