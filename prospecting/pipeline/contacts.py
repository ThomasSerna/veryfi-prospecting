"""Personas y canales profesionales de una empresa calificada, con cupos persistidos."""

from datetime import timedelta
from decimal import Decimal
import time
from typing import Literal
from uuid import UUID

from pydantic import Field

from prospecting.budget import Budget, BudgetError, Observation, SpendingAuthorization
from prospecting.contact_extraction import build_contacts_request, parse_contacts_output
from prospecting.contacts import (
    ContactError, apply_target_roles, channel_is_usable, derive_readiness, merge_contact, target_roles,
    validate_contact,
)
from prospecting.db import Database
from prospecting.models import BusinessStatus, Contract, IdentityStatus, Priority, RunStage, Text, UsageStatus, utc_now
from prospecting.pipeline.calls import observed_credits, reserve_claude, reserve_credits, seconds_left
from prospecting.providers import CLAUDE_OPERATION, CLAUDE_PROVIDER, ClaudeClient, ProviderClient, ProviderError
from prospecting.providers.hunter import (
    HunterAccess, HunterDomainSearchResponse, HunterFinderResponse, HunterVerifierResponse, classify_hunter_error,
    domain_search_request, finder_request, parse_domain_search, parse_finder, parse_verifier, target_departments,
    verifier_request,
)
from prospecting.providers.tavily import (
    SEARCH_CREDITS, TavilyExtractResponse, TavilySearchResponse, classify_tavily_error, contact_search_evidence,
    contact_search_request, extract_credits, extract_request, parse_extract,
)
from prospecting.sources import CONTACT_SEARCH_REFERENCE, is_non_business, url_host


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


# Claves persistidas de RunItem.attempts; reanudar depende de estos textos (docs/persistence.md).
PERSON_KEY = "contacts:person:"
REQUEST_KEY = "contacts:request:"
PROCESSED_KEY = "contacts:processed:"
HAIKU_KEY = "contacts:haiku"
HAIKU_REQUEST_KEY = "contacts:haiku_request:"
VERIFY_KEY = "contacts:verify:"
DOMAIN_SEARCH_KEY = "contacts:domain_search"
WEB_QUERIES_KEY = "contacts:web_queries"
PAGES_KEY = "contacts:pages"
EXTRACT_KEY = "contacts:extract"
ENRICHMENTS_KEY = "contacts:hunter_enrichments"
# Fallos de Hunter que permiten seguir por la ruta pública en lugar de detener la etapa.
_HUNTER_DEGRADED = ("permission_denied", "rate_limited", "quota_exceeded", "local_error")


class _ContactStage:
    """Una ejecución de la etapa de contactos de una empresa, organizada por fases.

    `run` es siempre el último RunItem guardado. La selección de personas se anota en
    `run.attempts` y se persiste con el siguiente checkpoint, junto al resultado que la
    produjo. Cada fase devuelve un ContactReport cuando la etapa termina, o None para seguir.
    """

    def __init__(self, db, budget, client, campaign, company, run, assessment, *, hunter_access, authorizations,
                 tavily_account_ref, claude, claude_account_ref, claude_funding_source, deadline):
        self.db, self.budget, self.client = db, budget, client
        self.campaign, self.company, self.run, self.assessment = campaign, company, run, assessment
        self.hunter_access, self.grants = hunter_access, authorizations or []
        self.tavily_account_ref = tavily_account_ref
        self.claude, self.claude_account_ref = claude, claude_account_ref
        self.claude_funding_source = claude_funding_source
        self.base = {"campaign_id": campaign.id, "company_id": company.id}
        self.effort = campaign.limits.effort[str(assessment.priority)]
        self.roles = target_roles(company, assessment, campaign)
        self.requests, self.evidence_ids, self.warnings = [], [], []
        self.degraded_error = None
        if hunter_access is not None and not hunter_access.automatic_lead_saving_disabled and any(
                operation in hunter_access.enabled_operations for operation in ("email_finder", "email_verifier")):
            self.warnings.append("Finder y Verifier deshabilitados: falta comprobar que no guardan leads automáticamente.")
        self.tick = time.monotonic()
        local_deadline = self.tick + max(0.0, self.effort.active_seconds - run.consumed_limits.contacts_active_seconds)
        self.deadline = local_deadline if deadline is None else min(deadline, local_deadline)

    # Estado, checkpoints y llamadas comunes a todas las fases.

    def grant(self, provider, operation, account):
        return next((item for item in self.grants if
                     (item.provider, item.operation, item.account_ref) == (provider, operation, account)), None)

    def facts(self):
        return self.db.list_evidence(self.company.id)

    def checkpoint(self, *, attempts=None, consumed=None, updates=None, aggregates=(), facts=()):
        now_tick = time.monotonic()
        elapsed = max(0.0, now_tick - self.tick)
        current = self.db.get_run_item(self.campaign.id, self.company.id)
        counters = current.consumed_limits.model_dump()
        for name, amount in (consumed or {}).items():
            counters[name] += amount
        counters["active_seconds"] += elapsed
        counters["contacts_active_seconds"] += elapsed
        selection = {key: value for key, value in self.run.attempts.items() if key.startswith(PERSON_KEY)}
        changes = {"attempts": current.attempts | selection | (attempts or {}),
                   "consumed_limits": type(current.consumed_limits).model_validate(counters),
                   "updated_at": utc_now()} | (updates or {})
        with self.db.transaction():
            for contact, source in aggregates:
                self.db.save_contact(contact, evidence=source)
                self.evidence_ids.extend(item.id for item in source)
            for fact in facts:
                self.db.save_evidence(fact)
                self.evidence_ids.append(fact.id)
            self.run = self.db.save_run_item(current.model_copy(update=changes))
        self.tick = now_tick

    def people(self):
        now = utc_now()
        fresh_ids = {item.contact_id for item in self.facts() if item.contact_id is not None
                     and now - timedelta(days=self.campaign.limits.cache.contact_days) <= item.retrieved_at <= now}
        return [item for item in self.db.list_contacts(self.company.id) if item.id in fresh_ids]

    def readiness(self):
        return derive_readiness(self.assessment, self.people(), self.facts(), self.campaign.limits, utc_now(),
                                self.company)

    def finish(self, reason, *, status="checked", message=None):
        state = self.readiness()
        updates = {"business_status": state, "stop_reason": reason,
                   "error_message": message,
                   "error_stage": RunStage.CONTACTS_CHECKED if status == "pending" else None}
        if status == "checked":
            updates["stage"] = max(self.run.stage, RunStage.CONTACTS_CHECKED, key=list(RunStage).index)
        self.checkpoint(updates=updates)
        return ContactReport(**self.base, status=status, business_status=state,
                             contact_ids=[item.id for item in self.people()],
                             evidence_ids=list(dict.fromkeys(self.evidence_ids)),
                             request_ids=list(dict.fromkeys(self.requests)), stop_reason=reason,
                             error_message=message, warnings=self.warnings)

    def cached(self, fingerprint, provider, operation, account, days):
        """Reutiliza un resultado ya procesado; una llamada enviada sin resultado nunca se repite."""
        now = utc_now()
        rows = [row for row in self.db.list_usage(company_id=self.company.id, provider=provider)
                if (row.operation, row.account_ref, row.request_fingerprint) == (operation, account, fingerprint)]
        for row in reversed(rows):
            previous = self.db.get_run_item(row.campaign_id, self.company.id)
            done = previous.attempts.get(f"{PROCESSED_KEY}{fingerprint}", 0)
            if row.status in (UsageStatus.IN_FLIGHT, UsageStatus.UNCERTAIN):
                raise BudgetError("request_uncertain", "Hay una llamada enviada pendiente de resultado o conciliación.", row.request_id)
            if row.status not in (UsageStatus.RESERVED, UsageStatus.RECONCILED) and not done:
                raise BudgetError("result_unavailable", "La llamada fue enviada, pero falta su resultado persistido.", row.request_id)
            if row.campaign_id == self.campaign.id:
                if row.status != UsageStatus.RESERVED and not done:
                    raise BudgetError("result_unavailable", "La llamada fue enviada, pero falta su resultado persistido.", row.request_id)
                if done:
                    self.requests.append(row.request_id)
                    return True
            elif (done and row.outcome == "succeeded"
                  and now - timedelta(days=days) <= (row.finished_at or row.created_at) <= now):
                self.requests.append(row.request_id)
                self.checkpoint(attempts={f"{PROCESSED_KEY}{fingerprint}": 1})
                return True
        return False

    def perform(self, request, response_model, *, credits, count_key, cap, consumed,
                parse, funding="free_credit", pages=0):
        """Reserva, llama, valida y guarda el resultado en un checkpoint; respeta caché y cupos."""
        fingerprint = self.client.fingerprint(request)
        limits = self.campaign.limits
        days = limits.cache.web_days if request.provider == "tavily" else limits.cache.contact_days
        if self.cached(fingerprint, request.provider, request.operation, request.account_ref, days):
            return
        if self.run.attempts.get(count_key, 0) >= cap:
            return
        if seconds_left(self.deadline) <= 0:
            raise BudgetError("time_limit", "Se agotó el tiempo de contactos antes de llamar.")
        grant = self.grant(request.provider, request.operation, request.account_ref)
        usage = reserve_credits(self.budget, request, fingerprint, Decimal(credits), funding_source=funding,
                                authorization=grant, **self.base)
        self.requests.append(usage.request_id)
        self.checkpoint(attempts={f"{REQUEST_KEY}{usage.request_id}": 1})
        attempts = {count_key: self.run.attempts.get(count_key, 0) + 1}
        if pages:
            attempts[PAGES_KEY] = self.run.attempts.get(PAGES_KEY, 0) + pages
        try:
            result = self.client.request_json(usage.request_id, request, response_model, authorization=grant,
                                              remaining_seconds=seconds_left(self.deadline))
        except (ProviderError, BudgetError) as error:
            current_usage = self.db.get_usage(usage.request_id)
            if current_usage.status != UsageStatus.RESERVED and not getattr(error, "no_send", False):
                self.checkpoint(attempts=attempts, consumed=consumed)
            raise
        if request.provider == "tavily":
            observed = observed_credits(result.data)
            if observed is not None:
                self.budget.record_result(usage.request_id, Observation(outcome="succeeded", credits=observed))
        if result.http_status == 202:
            self.checkpoint(attempts=attempts, consumed=consumed)
            raise BudgetError("verification_pending", "Hunter mantiene la verificación en procesamiento.", usage.request_id)
        try:
            aggregates, facts = parse(result.data, usage.request_id)
        except (ContactError, ValueError, TypeError):
            self.checkpoint(attempts=attempts, consumed=consumed)
            raise BudgetError("invalid_contact_data", "La respuesta no respalda los datos de contacto esperados.", usage.request_id) from None
        self.checkpoint(attempts=attempts | {f"{PROCESSED_KEY}{fingerprint}": 1}, consumed=consumed,
                        aggregates=aggregates, facts=facts)

    def save_candidates(self, parsed):
        """Fusiona candidatos con personas conocidas y respeta el cupo de personas del nivel."""
        facts = self.facts()
        known = self.db.list_contacts(self.company.id)
        selected = {UUID(key.split(":")[-1]) for key in self.run.attempts if key.startswith(PERSON_KEY)}
        def rank(pair):
            contact = pair[0]
            return (contact.name_complete is not True, contact.title not in self.roles,
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
            if candidate.id not in selected and len(selected) >= self.effort.people:
                continue
            candidate, role_facts = apply_target_roles(candidate, self.roles, facts + source)
            source += role_facts
            selected.add(candidate.id)
            saved.append((candidate, source))
        # La selección se persiste junto al resultado, sin reservar una persona por su nombre.
        for candidate, _ in saved:
            self.run.attempts[f"{PERSON_KEY}{candidate.id}"] = 1
        return saved, []

    # Fases, de menor a mayor esfuerzo (§9).

    def execute(self) -> ContactReport:
        if list(RunStage).index(self.run.stage) >= list(RunStage).index(RunStage.CONTACTS_CHECKED):
            return self.finish(self.run.stop_reason or "already_checked", status="already_checked")
        if self.effort.people == 0:
            return self.finish("people_limit")
        try:
            for phase in (self._recover_pending, self._reuse_known_people, self._search_hunter,
                          self._search_public, self._extract_public, self._enrich_people):
                report = phase()
                if report is not None:
                    return report
            if self.degraded_error is not None and not (
                    self.run.attempts.get(WEB_QUERIES_KEY, 0) or self.run.attempts.get(HAIKU_KEY, 0)):
                raise self.degraded_error
            return self.finish("contact_plan_exhausted")
        except (BudgetError, ProviderError, ContactError) as error:
            if getattr(error, "request_id", None) is not None:
                self.requests.append(error.request_id)
            return self.finish(_contact_error_reason(error), status="pending", message=str(error))
        except (ValueError, TypeError):
            return self.finish("invalid_contact_data", status="pending", message="No se pudieron validar los hechos de contacto.")

    def _recover_pending(self):
        """Una llamada enviada sin resultado validado deja la etapa pendiente, sin repetirla."""
        run = self.run
        for key in run.attempts:
            if not key.startswith(REQUEST_KEY):
                continue
            prior = self.db.get_usage(UUID(key.split(":")[-1]))
            if prior is not None and prior.status != UsageStatus.RESERVED and not run.attempts.get(f"{PROCESSED_KEY}{prior.request_fingerprint}", 0):
                self.requests.append(prior.request_id)
                return self.finish(run.stop_reason or "result_unavailable", status="pending",
                                   message=run.error_message or "Hay una llamada enviada sin resultado validado persistido.")
        for key in run.attempts:
            if key.startswith(HAIKU_REQUEST_KEY):
                prior = self.db.get_usage(UUID(key.split(":")[-1]))
                if prior is not None and not run.attempts.get(f"{PROCESSED_KEY}{prior.request_fingerprint}", 0):
                    return self.finish(run.stop_reason or "result_unavailable", status="pending",
                                       message=run.error_message or "La extracción enviada no tiene un resultado validado persistido.")
        return None

    def _reuse_known_people(self):
        """Un canal preferido ya guardado termina la etapa; las personas válidas ocupan su cupo."""
        if self.readiness() == BusinessStatus.READY_PREFERRED:
            return self.finish("preferred_channel_found")
        existing_eligible = [item for item in self.people() if validate_contact(
            item, self.company, self.assessment, self.facts(), self.campaign.limits, utc_now())]
        if existing_eligible:
            selected = {key.split(":")[-1] for key in self.run.attempts if key.startswith(PERSON_KEY)}
            additions = {}
            for item in existing_eligible:
                if str(item.id) not in selected and len(selected) < self.effort.people:
                    selected.add(str(item.id))
                    additions[f"{PERSON_KEY}{item.id}"] = 1
            self.checkpoint(attempts=additions)
        return None

    def _search_hunter(self):
        """Domain Search por cargos y, en el segundo intento, por departamentos."""
        access, company = self.hunter_access, self.company
        if access is None or "domain_search" not in access.enabled_operations:
            return None
        for index in range(self.effort.people_queries):
            request = domain_search_request(company, self.roles, access.search_account_ref,
                                            departments=target_departments(self.roles) if index else None)
            try:
                self.perform(request, HunterDomainSearchResponse, credits=1,
                             count_key=DOMAIN_SEARCH_KEY, cap=self.effort.people_queries,
                             consumed={"people_queries": 1}, funding=access.funding_source,
                             parse=lambda data, request_id: self.save_candidates(
                                 parse_domain_search(company, data, request_id, utc_now())))
            except (BudgetError, ProviderError) as error:
                if _contact_error_reason(error) not in _HUNTER_DEGRADED:
                    raise
                self.warnings.append(f"Hunter: {_contact_error_reason(error)}: {error}")
                self.degraded_error = error
                return None
            if self.readiness() == BusinessStatus.READY_PREFERRED:
                return self.finish("preferred_channel_found")
        return None

    def _search_public(self):
        """Búsqueda y extracción públicas con Tavily cuando no hay un directorio corporativo vigente."""
        company, campaign, effort = self.company, self.campaign, self.effort
        now = utc_now()
        stored_public = [item for item in self.facts() if item.source_type == "primary"
                         and item.excerpt and item.url is not None
                         and now - timedelta(days=campaign.limits.cache.web_days) <= item.retrieved_at <= now
                         and any(part in str(item.url).lower() for part in ("/equipo", "/team", "/directorio", "/leadership"))]
        if self.tavily_account_ref is None or stored_public or self.run.attempts.get(HAIKU_KEY, 0):
            return None
        queries = [f'"{company.name}" {" ".join(self.roles[:4])} equipo directorio {" ".join(campaign.countries)}']
        queries += [f'"{item.name}" "{company.name}" {item.title or "cargo actual"}' for item in self.people() if item.name]
        queries += [f'"{company.name}" equipo producto ingeniería marketing contacto profesional']
        for query in list(dict.fromkeys(queries))[:effort.web_queries]:
            request = contact_search_request(query, self.tavily_account_ref)
            self.perform(request, TavilySearchResponse, credits=SEARCH_CREDITS,
                         count_key=WEB_QUERIES_KEY, cap=effort.web_queries, consumed={"web_queries": 1},
                         parse=lambda data, request_id: ([], contact_search_evidence(company.id, data, request_id)))
        now = utc_now()
        urls = list(dict.fromkeys(str(item.url) for item in self.facts() if item.url is not None
                                  and item.external_reference and item.external_reference.startswith(CONTACT_SEARCH_REFERENCE)
                                  and now - timedelta(days=campaign.limits.cache.web_days) <= item.retrieved_at <= now
                                  and url_host(str(item.url)) is not None and not is_non_business(url_host(str(item.url)))))
        left = max(0, effort.pages - self.run.attempts.get(PAGES_KEY, 0))
        if urls and left:
            urls = urls[:left]
            request = extract_request(urls, f'{company.name}; {"; ".join(self.roles)}; equipo y contacto nominal',
                                      self.tavily_account_ref)
            def extracted(data, request_id):
                facts, failures = parse_extract(company, urls, data, request_id, utc_now())
                self.warnings.extend(f"Tavily Extract: {reason}" for _, reason in failures)
                return [], facts
            self.perform(request, TavilyExtractResponse, credits=extract_credits(len(urls)),
                         count_key=EXTRACT_KEY, cap=effort.pages,
                         consumed={"pages": len(urls)}, pages=len(urls), parse=extracted)
        return None

    def _extract_public(self):
        """Haiku extrae hechos nominales citados de la evidencia pública vigente; una sola vez por etapa."""
        claude, account, campaign = self.claude, self.claude_account_ref, self.campaign
        if claude is None or account is None or self.run.attempts.get(HAIKU_KEY, 0):
            return None
        now = utc_now()
        public = [item for item in self.facts() if item.excerpt is not None
                  and item.source_type in ("primary", "secondary")
                  and not (item.external_reference or "").startswith(CONTACT_SEARCH_REFERENCE)
                  and now - timedelta(days=campaign.limits.cache.web_days) <= item.retrieved_at <= now]
        if not public:
            return None
        payload, supplied = build_contacts_request(self.company, self.assessment, campaign, public, self.people())
        if not supplied:
            return None
        fingerprint = claude.fingerprint(payload, account)
        if self.cached(fingerprint, CLAUDE_PROVIDER, CLAUDE_OPERATION, account, campaign.limits.cache.contact_days):
            return None
        if seconds_left(self.deadline) <= 0:
            raise BudgetError("time_limit", "Se agotó el tiempo antes de extraer contactos.")
        grant = self.grant(CLAUDE_PROVIDER, CLAUDE_OPERATION, account)
        usage = reserve_claude(self.budget, fingerprint, campaign.limits.llm, account_ref=account,
                               funding_source=self.claude_funding_source, authorization=grant, **self.base)
        self.requests.append(usage.request_id)
        try:
            call = claude.create(usage.request_id, payload, account_ref=account, authorization=grant,
                                 remaining_seconds=seconds_left(self.deadline))
        finally:
            if self.db.get_usage(usage.request_id).status != UsageStatus.RESERVED:
                self.checkpoint(attempts={HAIKU_KEY: 1, f"{HAIKU_REQUEST_KEY}{usage.request_id}": 1})
        try:
            parsed = parse_contacts_output(call.text, call.stop_reason, self.company, self.assessment, campaign,
                                           supplied, utc_now(), usage.request_id, contacts=self.people())
            aggregates, facts = self.save_candidates(parsed)
        except ContactError:
            raise
        except (ValueError, TypeError):
            raise BudgetError("invalid_contact_output", "Haiku no devolvió hechos de contacto respaldados.", usage.request_id) from None
        self.checkpoint(attempts={f"{PROCESSED_KEY}{fingerprint}": 1}, aggregates=aggregates, facts=facts)
        return None

    def _enrich_people(self):
        """Finder y Verifier solo sobre personas pertinentes y vigentes, dentro del cupo de enriquecimientos."""
        for contact in self.people():
            report = self._enrich(contact)
            if report is not None:
                return report
        return None

    def _enrich(self, contact):
        company, access = self.company, self.hunter_access
        selected = {key.split(":")[-1] for key in self.run.attempts if key.startswith(PERSON_KEY)}
        if str(contact.id) not in selected:
            if len(selected) >= self.effort.people:
                return None
            self.checkpoint(attempts={f"{PERSON_KEY}{contact.id}": 1})
        if not validate_contact(contact, company, self.assessment, self.facts(), self.campaign.limits, utc_now()):
            return None
        if any(channel_is_usable(channel, contact, self.facts(), self.campaign.limits, utc_now(), company)
               and channel.type in ("email", "phone", "whatsapp") for channel in contact.channels):
            return self.finish("preferred_channel_found")
        if access is None or self.degraded_error is not None:
            return None
        if (not any(channel.type == "email" and channel.professional is True for channel in contact.channels)
                and "email_finder" in access.enabled_operations and access.automatic_lead_saving_disabled):
            request = finder_request(contact, company, access.search_account_ref)
            self.perform(request, HunterFinderResponse, credits=1, count_key=ENRICHMENTS_KEY,
                         cap=self.effort.enrichments_per_provider, consumed={"enrichments": 1},
                         funding=access.funding_source,
                         parse=lambda data, request_id: ([(parse_finder(contact, company, data, request_id, utc_now()))], []))
            contact = self.db.get_contact(contact.id)
            if self.readiness() == BusinessStatus.READY_PREFERRED:
                return self.finish("preferred_channel_found")
        if "email_verifier" not in access.enabled_operations or not access.automatic_lead_saving_disabled:
            return None
        return self._verify_emails(contact)

    def _verify_emails(self, contact):
        company, access = self.company, self.hunter_access
        for channel in contact.channels:
            if channel.type != "email" or channel.professional is not True or channel.direct is not True:
                continue
            if channel_is_usable(channel, contact, self.facts(), self.campaign.limits, utc_now(), company):
                continue
            request = verifier_request(channel.value, access.verification_account_ref or access.search_account_ref)
            channel_key = f"{VERIFY_KEY}{self.client.fingerprint(request)}"
            if self.run.attempts.get(channel_key, 0) >= self.campaign.limits.email_verifications_per_channel:
                continue
            def verified(data, request_id):
                return [parse_verifier(contact, company, data, request_id, utc_now())], []
            before = self.run.attempts.get(ENRICHMENTS_KEY, 0)
            try:
                self.perform(request, HunterVerifierResponse, credits="0.5" if access.unified_credits else "1",
                             count_key=ENRICHMENTS_KEY, cap=self.effort.enrichments_per_provider,
                             consumed={"enrichments": 1, "email_verifications": 1},
                             funding=access.funding_source, parse=verified)
            finally:
                if self.run.attempts.get(ENRICHMENTS_KEY, 0) > before:
                    self.checkpoint(attempts={channel_key: 1})
            if self.readiness() == BusinessStatus.READY_PREFERRED:
                return self.finish("preferred_channel_found")
        return None


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
    stage = _ContactStage(db, budget, client, campaign, company, run, assessment, hunter_access=hunter_access,
                          authorizations=authorizations, tavily_account_ref=tavily_account_ref, claude=claude,
                          claude_account_ref=claude_account_ref, claude_funding_source=claude_funding_source,
                          deadline=deadline)
    if not stage.roles:
        return ContactReport(**base, status="skipped", stop_reason="no_target_roles")
    return stage.execute()
