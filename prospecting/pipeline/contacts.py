"""Personas y canales profesionales de una empresa calificada, con cupos persistidos."""

from datetime import timedelta
from decimal import Decimal
import time
from typing import Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from prospecting.budget import Budget, BudgetError, Observation, SpendingAuthorization
from prospecting.contact_extraction import build_contacts_request, parse_contacts_output
from prospecting.contacts import (
    ContactError, apply_campaign_roles, apply_target_roles, channel_is_usable, contact_context, derive_readiness,
    matched_role_family, merge_contact, people_progress, people_target, person_function, role_families, role_position,
    target_roles, validate_contact,
)
from prospecting.db import Database
from prospecting.models import (
    BusinessStatus, ChannelStatus, ChannelType, Contact, Contract, Evidence, IdentityStatus, Priority,
    RunItem, RunStage, Text, UsageStatus, utc_now,
)
from prospecting.pipeline.calls import grant_for, observed_credits, require_apollo_access, reserve_claude, reserve_credits, seconds_left
from prospecting.providers import CLAUDE_OPERATION, CLAUDE_PROVIDER, ClaudeClient, ProviderClient, ProviderError
from prospecting.providers.apollo import (
    ApolloAccess, ApolloSearchResponse, ApolloEnrichmentResponse, classify_apollo_error,
    people_search_request, enrichment_request, parse_search, parse_enrichment, person_id,
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


def confirm_alternative_channel(db: Database, campaign_id: UUID, contact_id: UUID,
                                channel_type: ChannelType, channel_value: str, *, reason: str,
                                confirmed: bool) -> RunItem:
    """Registra acceso profesional nominal comprobado manualmente, sin enviar nada."""
    if confirmed is not True:
        raise ValueError("La confirmación requiere una declaración explícita de acceso directo profesional sin envío.")
    channel_type = ChannelType(channel_type)
    if channel_type not in (ChannelType.LINKEDIN, ChannelType.OTHER):
        raise ValueError("Solo se pueden confirmar manualmente canales alternativos existentes.")
    reason = TypeAdapter(Text).validate_python(reason)
    channel_value = TypeAdapter(Text).validate_python(channel_value)
    with db.transaction():
        campaign, contact = db.get_campaign(campaign_id), db.get_contact(contact_id)
        run = None if contact is None else db.get_run_item(campaign_id, contact.company_id)
        if campaign is None or contact is None or run is None:
            raise ValueError("El contacto no pertenece a la campaña.")
        if campaign.config_snapshot.people_provider != "apollo":
            raise ValueError("La campaña histórica solo permite consulta y exportación.")
        company = db.get_company(contact.company_id)
        assessment = None if run.last_assessment_id is None else db.get_assessment(run.last_assessment_id)
        people, evidence = contact_context(campaign, db.list_contacts(contact.company_id), db.list_evidence(contact.company_id))
        if contact.id not in {item.id for item in people}:
            raise ValueError("El contacto no pertenece al flujo Apollo de esta campaña.")
        now = utc_now()
        stored_contact = contact
        roles = None if assessment is None else target_roles(company, assessment, campaign, evidence=evidence)
        if assessment is not None:
            contact = apply_campaign_roles(contact, company, assessment, campaign, evidence, now)
        if (assessment is None or assessment.campaign_id != campaign_id or run.business_status == BusinessStatus.EXCLUDED
                or not validate_contact(contact, company, assessment, evidence, campaign.limits, now, roles, campaign=campaign)):
            raise ValueError("La persona necesita identidad, cargo y empleo pertinente vigentes antes de confirmar un canal.")
        channel = next((item for item in contact.channels
                        if (item.type, item.value) == (channel_type, channel_value)), None)
        if channel is None:
            raise ValueError("El canal debe existir y pertenecer a esta persona.")
        if channel.normalized_status == ChannelStatus.INVALID:
            raise ValueError("La confirmación manual no elimina una verificación negativa.")
        fact = Evidence(company_id=company.id, contact_id=contact.id, kind="observed", source_type="manual",
                        provider="manual_review", external_reference=f"manual-channel:{campaign_id}:{contact.id}:{now.isoformat()}",
                        retrieved_at=now, claim=f"Acceso directo profesional nominal a {contact.name} por {channel.type}: {channel.value}.",
                        excerpt=f"Confirmado manualmente sin enviar mensajes ni notificaciones. Motivo: {reason}")
        updated_channel = channel.model_copy(update={
            "normalized_status": ChannelStatus.MANUAL_CONFIRMED, "manual_confirmed_at": now,
            "manual_confirmation_reason": reason, "professional": True, "direct": True,
            "evidence_ids": channel.evidence_ids + [fact.id],
        })
        updated = Contact.model_validate(stored_contact.model_copy(update={"channels": [
            updated_channel if item == channel else item for item in contact.channels]}))
        if not channel_is_usable(updated_channel, updated, evidence + [fact], campaign.limits, now, company):
            raise ValueError("El canal conserva evidencia contradictoria o con fecha futura; no se puede confirmar.")
        db.save_contact(updated, evidence=[fact])
        people, evidence = contact_context(campaign, db.list_contacts(company.id), db.list_evidence(company.id))
        readiness = derive_readiness(assessment, people, evidence,
                                     campaign.limits, now, company, roles, campaign=campaign)
        return db.save_run_item(run.model_copy(update={"business_status": readiness, "updated_at": now}))


def _blocked_reason(usage) -> str:
    """Una llamada en curso o con resultado incierto espera conciliación; las demás, su resultado persistido."""
    return "request_uncertain" if usage.status in (UsageStatus.IN_FLIGHT, UsageStatus.UNCERTAIN) else "result_unavailable"


def _contact_error_reason(error) -> str:
    if isinstance(error, (BudgetError, ContactError)):
        return error.code
    if error.provider == "apollo":
        return classify_apollo_error(error)
    return classify_tavily_error(error)


# Claves persistidas de RunItem.attempts; reanudar depende de estos textos (docs/persistence.md).
PERSON_KEY = "contacts:person:"
REQUEST_KEY = "contacts:request:"
PROCESSED_KEY = "contacts:processed:"
HAIKU_KEY = "contacts:haiku"
HAIKU_REQUEST_KEY = "contacts:haiku_request:"
PEOPLE_SEARCH_KEY = "contacts:apollo_search"
WEB_QUERIES_KEY = "contacts:web_queries"
PAGES_KEY = "contacts:pages"
EXTRACT_KEY = "contacts:extract"
ENRICHMENTS_KEY = "contacts:apollo_enrichments"
# T16: Apollo no confirmó a esa persona (`<código>:<contact_id>`); su resultado queda procesado y no se repite.
REJECTED_KEY = "contacts:apollo_rejected:"


def _rank(contact: Contact, roles: list[str], selected: set[UUID]):
    """Orden de investigación (T09): seleccionadas, nombre completo, cargo pertinente y su prioridad, canal verificado."""
    return (contact.id not in selected, contact.name_complete is not True, contact.relevant_function is not True,
            role_position(contact.title, roles), not any(channel.normalized_status == ChannelStatus.VERIFIED for channel in contact.channels),
            str(contact.id))


class _ContactStage:
    """Una ejecución de la etapa de contactos de una empresa, organizada por fases.

    `run` es siempre el último RunItem guardado. Los candidatos se guardan todos con su
    procedencia; el cupo de personas (`contacts:person:`) solo lo ocupa quien supera la
    validación al investigarla. Cada fase devuelve un ContactReport cuando la etapa termina, o None para seguir.
    Sin `people_policy` (instantáneas anteriores a T16) la etapa termina en el primer canal preferido; con ella,
    los enriquecimientos siguen hasta el objetivo de personas pertinentes o el tope del nivel.
    """

    def __init__(self, db, budget, client, campaign, company, run, assessment, *, apollo_access, authorizations,
                 tavily_account_ref, claude, claude_account_ref, claude_funding_source, deadline):
        self.db, self.budget, self.client = db, budget, client
        self.campaign, self.company, self.run, self.assessment = campaign, company, run, assessment
        self.apollo_access, self.grants = apollo_access, authorizations or []
        self.tavily_account_ref = tavily_account_ref
        self.claude, self.claude_account_ref = claude, claude_account_ref
        self.claude_funding_source = claude_funding_source
        self.base = {"campaign_id": campaign.id, "company_id": company.id}
        self.effort = campaign.limits.effort[str(assessment.priority)]
        self.policy, self.target = campaign.config_snapshot.people_policy, people_target(campaign, assessment)
        self.parsed_attempts = {}
        self.roles = target_roles(company, assessment, campaign, evidence=self.facts())
        self.requests, self.evidence_ids, self.warnings = [], [], []
        self.tick = time.monotonic()
        local_deadline = self.tick + max(0.0, self.effort.active_seconds - run.consumed_limits.contacts_active_seconds)
        self.deadline = local_deadline if deadline is None else min(deadline, local_deadline)

    # Estado, checkpoints y llamadas comunes a todas las fases.

    def facts(self):
        return contact_context(self.campaign, self.db.list_contacts(self.company.id),
                               self.db.list_evidence(self.company.id))[1]

    def checkpoint(self, *, attempts=None, consumed=None, updates=None, aggregates=(), facts=()):
        now_tick = time.monotonic()
        elapsed = max(0.0, now_tick - self.tick)
        current = self.db.get_run_item(self.campaign.id, self.company.id)
        counters = current.consumed_limits.model_dump()
        for name, amount in (consumed or {}).items():
            counters[name] += amount
        counters["active_seconds"] += elapsed
        counters["contacts_active_seconds"] += elapsed
        changes = {"attempts": current.attempts | (attempts or {}),
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

    def selected(self) -> set[UUID]:
        """Personas que ocupan el cupo; una selección antigua de un cargo fuera del perfil no lo ocupa (T09)."""
        ids = {UUID(key.split(":")[-1]) for key in self.run.attempts if key.startswith(PERSON_KEY)}
        if self.campaign.config_snapshot.role_taxonomy is not None:
            return ids.intersection(item.id for item in self.people() if item.relevant_function is True)
        return ids - {item.id for item in self.db.list_contacts(self.company.id) if item.relevant_function is False}

    def ranked_people(self):
        selected = self.selected()
        people = sorted(self.people(), key=lambda item: _rank(item, self.roles, selected))
        if self.campaign.config_snapshot.role_taxonomy is None:
            return people
        families = role_families(self.company, self.assessment, self.campaign, evidence=self.facts())
        positions = {}
        for family in families:
            positions.setdefault(family.function_id, len(positions))
        occurrences, ordered = {}, []
        facts, now = self.facts(), utc_now()
        for contact in people:
            family, _ = matched_role_family(contact, self.company, self.assessment, self.campaign, facts, now)
            base = _rank(contact, self.roles, selected)
            quality = base[:3] + (base[-2],)
            key = quality, None if family is None else family.function_id
            occurrence = occurrences.get(key, 0)
            occurrences[key] = occurrence + 1
            ordered.append((quality, occurrence, positions.get(key[1], len(positions)), base, contact))
        return [item[-1] for item in sorted(ordered, key=lambda item: item[:-1])]

    def people(self):
        now = utc_now()
        fresh_ids = {item.contact_id for item in self.facts() if item.contact_id is not None
                     and now - timedelta(days=self.campaign.limits.cache.contact_days) <= item.retrieved_at <= now}
        people, _ = contact_context(self.campaign, self.db.list_contacts(self.company.id),
                                    self.db.list_evidence(self.company.id))
        return [apply_campaign_roles(item, self.company, self.assessment, self.campaign, self.facts(), now)
                for item in people if item.id in fresh_ids]

    def readiness(self):
        return derive_readiness(self.assessment, self.people(), self.facts(), self.campaign.limits, utc_now(),
                                self.company, self.roles, campaign=self.campaign)

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
            previous_campaign = self.db.get_campaign(row.campaign_id)
            if previous_campaign.config_snapshot.people_provider != "apollo":
                continue
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
        grant = grant_for(self.grants, request.provider, request.operation, request.account_ref)
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
        if request.provider == "apollo" and request.operation == "people_search":
            self.budget.record_result(usage.request_id, Observation(outcome="succeeded", credits=Decimal(0)))
        try:
            aggregates, facts = parse(result.data, usage.request_id)
        except ContactError:
            self.checkpoint(attempts=attempts, consumed=consumed)
            raise
        except (ValueError, TypeError):
            self.checkpoint(attempts=attempts, consumed=consumed)
            raise BudgetError("invalid_contact_data", "La respuesta no respalda los datos de contacto esperados.", usage.request_id) from None
        extra, self.parsed_attempts = self.parsed_attempts, {}
        self.checkpoint(attempts=attempts | extra | {f"{PROCESSED_KEY}{fingerprint}": 1}, consumed=consumed,
                        aggregates=aggregates, facts=facts)

    def goal(self):
        """Estado del objetivo de la política (T16): `(cumplido, funciones cubiertas)`.

        Las funciones cubiertas solo se devuelven cuando ya hay personas suficientes pero falta diversidad y
        queda un candidato de otra función por intentar: entonces solo se enriquece a candidatos de otras funciones.
        """
        people, facts, now = self.people(), self.facts(), utc_now()
        progress = people_progress(people, self.company, self.assessment, facts, now, self.roles, campaign=self.campaign)
        if self.target is None or progress.relevant < self.target:
            return False, None
        covered = set(progress.function_ids)
        if len(covered) >= self.policy.min_functions:
            return True, None
        others = any(self.enrichable(item, facts) and person_function(
            item, self.company, self.assessment, self.campaign, facts, now) not in covered | {None} for item in people)
        return (False, covered) if others else (True, None)

    def goal_reached(self) -> bool:
        """Sin política, el primer canal preferido (histórico); con política, el objetivo y su diversidad."""
        if self.policy is None:
            return self.readiness() == BusinessStatus.READY_PREFERRED
        return self.goal()[0]

    def enrichable(self, contact, facts) -> bool:
        """Candidato pertinente con identificador de Apollo que aún no se enriqueció ni se intentó enriquecer."""
        identifier = person_id(contact, facts)
        if (identifier is None or contact.relevant_function is not True
                or contact.identity_status == IdentityStatus.CONTRADICTED or contact.current_employment is False
                or any(item.contact_id == contact.id and (item.external_reference or "").endswith("#enrichment")
                       for item in facts)):
            return False
        fingerprint = self.client.fingerprint(enrichment_request(identifier, self.apollo_access.account_ref))
        return not self.run.attempts.get(f"{PROCESSED_KEY}{fingerprint}", 0)

    def exhausted_reason(self) -> str:
        """Motivo de cierre al agotar el plan: objetivo cumplido, tope de enriquecimientos o plan agotado."""
        if self.policy is not None:
            if self.goal_reached():
                return "people_target_reached"
            if self.run.attempts.get(ENRICHMENTS_KEY, 0) >= min(self.effort.people, self.effort.enrichments_per_provider):
                return "enrichment_limit"
        return "contact_plan_exhausted"

    def save_candidates(self, parsed):
        """Fusiona candidatos con personas conocidas y los conserva todos con su procedencia (T09).

        Guardar no ocupa el cupo de personas: un candidato fuera del perfil o sin validar no
        desplaza a uno idóneo encontrado después. Los topes de llamadas no cambian.
        """
        facts = self.facts()
        known, _ = contact_context(self.campaign, self.db.list_contacts(self.company.id),
                                   self.db.list_evidence(self.company.id))
        saved = []
        for candidate, source in parsed:
            apollo_id = person_id(candidate, source)
            match = next((old for old in known if old.id == candidate.id or apollo_id is None and any(
                a.type == b.type and a.type in ("email", "linkedin") and a.value == b.value
                for a in old.channels for b in candidate.channels)), None)
            if match is not None:
                old_id = candidate.id
                candidate = candidate.model_copy(update={"id": match.id, "channels": [
                    channel.model_copy(update={"contact_id": match.id}) for channel in candidate.channels]})
                source = [item.model_copy(update={"contact_id": match.id}) if item.contact_id == old_id else item for item in source]
                candidate = merge_contact(match, candidate, facts + source)
            if self.campaign.config_snapshot.role_taxonomy is not None:
                provenance = {field: ids for field, ids in candidate.provenance.items() if field != "relevant_function"}
                if match is not None and match.provenance.get("relevant_function"):
                    provenance["relevant_function"] = match.provenance["relevant_function"]
                candidate = candidate.model_copy(update={"relevant_function": None if match is None else match.relevant_function,
                                                         "provenance": provenance})
            else:
                candidate = apply_target_roles(candidate, self.roles)
            saved.append((candidate, source))
        return saved, []

    # Fases, de menor a mayor esfuerzo (§9).

    def execute(self) -> ContactReport:
        if list(RunStage).index(self.run.stage) >= list(RunStage).index(RunStage.CONTACTS_CHECKED):
            return self.finish(self.run.stop_reason or "already_checked", status="already_checked")
        if self.effort.people == 0:
            return self.finish("people_limit")
        try:
            for phase in (self._recover_pending, self._reuse_known_people, self._search_apollo,
                          self._enrich_people, self._search_public, self._extract_public, self._reuse_known_people):
                report = phase()
                if report is not None:
                    return report
            return self.finish(self.exhausted_reason())
        except (BudgetError, ProviderError, ContactError) as error:
            if getattr(error, "request_id", None) is not None:
                self.requests.append(error.request_id)
            return self.finish(_contact_error_reason(error), status="pending", message=str(error))
        except (ValueError, TypeError):
            return self.finish("invalid_contact_data", status="pending", message="No se pudieron validar los hechos de contacto.")

    def _recover_pending(self):
        """Una llamada enviada sin resultado validado deja la etapa pendiente, sin repetirla.

        El motivo describe el bloqueo actual (`request_uncertain` o `result_unavailable`), no el fallo original,
        que sigue en el mensaje: así un fallo antiguo de Apollo no detiene la pasada de las demás empresas (T17).
        """
        run = self.run
        for key in run.attempts:
            if not key.startswith(REQUEST_KEY):
                continue
            prior = self.db.get_usage(UUID(key.split(":")[-1]))
            if prior is not None and prior.status != UsageStatus.RESERVED and not run.attempts.get(f"{PROCESSED_KEY}{prior.request_fingerprint}", 0):
                self.requests.append(prior.request_id)
                return self.finish(_blocked_reason(prior), status="pending",
                                   message=run.error_message or "Hay una llamada enviada sin resultado validado persistido.")
        for key in run.attempts:
            if key.startswith(HAIKU_REQUEST_KEY):
                prior = self.db.get_usage(UUID(key.split(":")[-1]))
                if prior is not None and not run.attempts.get(f"{PROCESSED_KEY}{prior.request_fingerprint}", 0):
                    return self.finish(_blocked_reason(prior), status="pending",
                                       message=run.error_message or "La extracción enviada no tiene un resultado validado persistido.")
        return None

    def _reuse_known_people(self):
        """Las personas válidas ocupan su cupo; sin política, un canal preferido ya guardado termina la etapa."""
        existing_eligible = [item for item in self.ranked_people() if validate_contact(
            item, self.company, self.assessment, self.facts(), self.campaign.limits, utc_now(), self.roles,
            campaign=self.campaign)]
        if existing_eligible:
            selected = self.selected()
            additions = {}
            for item in existing_eligible:
                if item.id not in selected and len(selected) < self.effort.people:
                    selected.add(item.id)
                    additions[f"{PERSON_KEY}{item.id}"] = 1
            self.checkpoint(attempts=additions)
        if self.policy is None and self.readiness() == BusinessStatus.READY_PREFERRED:
            return self.finish("preferred_channel_found")
        return None

    def _search_apollo(self):
        """Busca candidatos del dominio; el segundo intento acota los cargos, sin paginación."""
        access, company = self.apollo_access, self.company
        if self.policy is not None and self.goal_reached():
            return None
        if self.campaign.config_snapshot.role_taxonomy is None:
            requests = [people_search_request(company, self.roles, access.account_ref, by_roles=bool(index))
                        for index in range(self.effort.people_queries)]
        else:
            families = role_families(company, self.assessment, self.campaign, evidence=self.facts())
            requests = []
            for with_seniority in (True, False):
                group = [family for family in families if bool(family.seniorities) == with_seniority]
                titles = list(dict.fromkeys(title for family in group for title in family.titles_en + family.titles_es))
                if titles:
                    seniorities = list(dict.fromkeys(level for family in group for level in family.seniorities))
                    requests.append(people_search_request(company, titles, access.account_ref, by_roles=True,
                                                         seniorities=seniorities))
        for request in requests[:self.effort.people_queries]:
            self.perform(request, ApolloSearchResponse, credits=0,
                         count_key=PEOPLE_SEARCH_KEY, cap=self.effort.people_queries,
                         consumed={"people_queries": 1}, funding=access.funding_source,
                         parse=lambda data, request_id: self.save_candidates(
                             parse_search(company, data, request_id, utc_now())))
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
        # Primero las personas resueltas por Apollo; un apellido ofuscado nunca se usa como nombre completo.
        queries = [f'"{item.name}" "{company.name}" {item.title or "cargo actual"}' for item in self.ranked_people()
                   if item.name and item.name_complete is True and item.relevant_function is True]
        queries += [f'"{company.name}" {" ".join(self.roles[:4])} equipo directorio {" ".join(campaign.countries)}']
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
        grant = grant_for(self.grants, CLAUDE_PROVIDER, CLAUDE_OPERATION, account)
        usage = reserve_claude(self.budget, fingerprint, payload, account_ref=account,
                               funding_source=self.claude_funding_source, authorization=grant, **self.base)
        self.requests.append(usage.request_id)
        attempts = {HAIKU_KEY: 1, f"{HAIKU_REQUEST_KEY}{usage.request_id}": 1}
        try:
            call = claude.create(usage.request_id, payload, account_ref=account, authorization=grant,
                                 remaining_seconds=seconds_left(self.deadline))
        except ProviderError as error:
            if error.no_send:
                attempts.pop(HAIKU_KEY)
            raise
        finally:
            if self.db.get_usage(usage.request_id).status != UsageStatus.RESERVED:
                self.checkpoint(attempts=attempts)
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
        """Resuelve candidatos pertinentes por ID antes de exigir nombre completo y empleo público.

        Con política, el orden por pertinencia y diversidad de funciones se mantiene y el bucle se corta al
        cumplir el objetivo; un canal utilizable ya no termina la etapa (T16).
        """
        for contact in self.ranked_people():
            if self.policy is not None:
                reached, covered = self.goal()
                if reached:
                    break
                if covered is not None and person_function(
                        contact, self.company, self.assessment, self.campaign, self.facts(), utc_now()) in covered:
                    continue
            report = self._enrich(contact)
            if report is not None:
                return report
        return None

    def _enrich(self, contact):
        company, access = self.company, self.apollo_access
        identifier = person_id(contact, self.facts())
        if (identifier is None or contact.relevant_function is not True or
                contact.identity_status == IdentityStatus.CONTRADICTED or contact.current_employment is False):
            return None
        request = enrichment_request(identifier, access.account_ref)

        def parse(data, request_id):
            try:
                return self.save_candidates([parse_enrichment(contact, company, data, request_id, utc_now())])
            except ContactError as error:
                # Con política, una persona no confirmada no detiene a las demás: queda candidata con su motivo.
                if self.policy is None:
                    raise
                self.parsed_attempts[f"{REJECTED_KEY}{error.code}:{contact.id}"] = 1
                self.warnings.append(f"Apollo no confirmó a una persona candidata: {error.message}")
                return [], []

        self.perform(request, ApolloEnrichmentResponse, credits=access.enrichment_credit_bound,
                     count_key=ENRICHMENTS_KEY, cap=min(self.effort.people, self.effort.enrichments_per_provider),
                     consumed={"enrichments": 1}, funding=access.funding_source, parse=parse)
        if self.policy is None and self.readiness() == BusinessStatus.READY_PREFERRED:
            return self.finish("preferred_channel_found")
        return None


def find_contacts(db: Database, budget: Budget, client: ProviderClient, campaign_id: UUID,
                  company_id: UUID, *, apollo_access: ApolloAccess | None = None,
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
    if campaign.config_snapshot.people_provider != "apollo":
        return ContactReport(**base, status="skipped", business_status=run.business_status,
                             stop_reason="legacy_campaign_read_only")
    if (run.business_status == BusinessStatus.EXCLUDED or assessment is None
            or assessment.priority not in (Priority.MEDIUM, Priority.HIGH)
            or company.identity_status != IdentityStatus.CONFIRMED
            or company.domain is None or is_non_business(company.domain)):
        return ContactReport(**base, status="skipped", business_status=run.business_status,
                             stop_reason="contact_preconditions")
    stage = _ContactStage(db, budget, client, campaign, company, run, assessment, apollo_access=apollo_access,
                          authorizations=authorizations, tavily_account_ref=tavily_account_ref, claude=claude,
                          claude_account_ref=claude_account_ref, claude_funding_source=claude_funding_source,
                          deadline=deadline)
    if not stage.roles and campaign.config_snapshot.role_taxonomy is not None:
        return stage.finish("no_target_roles", status="pending",
                            message="No hay un caso de uso respaldado para seleccionar cargos.")
    try:
        require_apollo_access(campaign, apollo_access, budget)
    except ValueError as error:
        # Se guarda el motivo (T17): la ficha explica el bloqueo y la campaña detiene la pasada de contactos.
        return stage.finish("apollo_access_unverified", status="pending", message=str(error))
    if not stage.roles:
        return ContactReport(**base, status="skipped", stop_reason="no_target_roles")
    return stage.execute()
