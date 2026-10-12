"""Personas y canales profesionales de una empresa calificada, con cupos persistidos."""

from datetime import timedelta
from decimal import Decimal
import time
from typing import Literal
from uuid import UUID

from pydantic import Field

from prospecting.budget import Budget, BudgetError, Observation, SpendingAuthorization
from prospecting.contacts import (
    ContactError, HunterAccess, HunterDomainSearchResponse, HunterFinderResponse, HunterVerifierResponse,
    apply_target_roles, build_contacts_request, channel_is_usable, classify_hunter_error,
    derive_readiness, domain_search_request, finder_request, merge_contact, parse_contacts_output,
    parse_domain_search, parse_finder, parse_verifier, target_departments, target_roles, validate_contact,
    verifier_request,
)
from prospecting.db import Database
from prospecting.discovery import (
    SEARCH_CREDITS, TavilyExtractResponse, TavilySearchResponse, classify_tavily_error,
    extract_credits, extract_request, parse_extract,
)
from prospecting.haiku import MODEL_ID
from prospecting.models import (
    BusinessStatus, Contract, Evidence, IdentityStatus, Priority, RunStage, Text, TokenUsage, Usage,
    UsageStatus, utc_now,
)
from prospecting.pipeline.calls import observed_credits, seconds_left
from prospecting.providers import (
    CLAUDE_OPERATION, CLAUDE_PROVIDER, ClaudeClient, ProviderClient, ProviderError, ProviderRequest,
    reservation_cost,
)
from prospecting.sources import CONTACT_SEARCH_REFERENCE, SEARCH_HIT_CLAIM, is_non_business, url_host


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
        if seconds_left(deadline) <= 0:
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
                                         remaining_seconds=seconds_left(deadline))
        except (ProviderError, BudgetError) as error:
            current_usage = db.get_usage(usage.request_id)
            if current_usage.status != UsageStatus.RESERVED and not getattr(error, "no_send", False):
                checkpoint(attempts=attempts, consumed=consumed)
            raise
        if request.provider == "tavily":
            observed = observed_credits(result.data)
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
                                      url=hit.url, provider="tavily", external_reference=f"{CONTACT_SEARCH_REFERENCE}{request_id}:{index}",
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
                                     and item.external_reference and item.external_reference.startswith(CONTACT_SEARCH_REFERENCE)
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
                      and not (item.external_reference or "").startswith(CONTACT_SEARCH_REFERENCE)
                      and now - timedelta(days=campaign.limits.cache.web_days) <= item.retrieved_at <= now]
            if public:
                payload, supplied = build_contacts_request(company, assessment, campaign, public, people())
                if supplied:
                    fingerprint = claude.fingerprint(payload, claude_account_ref)
                    if not cached(fingerprint, CLAUDE_PROVIDER, CLAUDE_OPERATION, claude_account_ref, campaign.limits.cache.contact_days):
                        if seconds_left(deadline) <= 0:
                            raise BudgetError("time_limit", "Se agotó el tiempo antes de extraer contactos.")
                        limits = campaign.limits.llm
                        usage = budget.reserve(Usage(
                            **base, provider=CLAUDE_PROVIDER, operation=CLAUDE_OPERATION, account_ref=claude_account_ref,
                            request_fingerprint=fingerprint, reserved_credits=Decimal(0),
                            reserved_tokens=TokenUsage(input_tokens=limits.max_input_tokens, output_tokens=limits.max_output_tokens),
                            reserved_cost_usd=reservation_cost(MODEL_ID, limits.max_input_tokens, limits.max_output_tokens),
                            funding_source=claude_funding_source, status=UsageStatus.RESERVED,
                        ), grant(CLAUDE_PROVIDER, CLAUDE_OPERATION, claude_account_ref))
                        requests.append(usage.request_id)
                        try:
                            call = claude.create(usage.request_id, payload, account_ref=claude_account_ref,
                                                 authorization=grant(CLAUDE_PROVIDER, CLAUDE_OPERATION, claude_account_ref),
                                                 remaining_seconds=seconds_left(deadline))
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
