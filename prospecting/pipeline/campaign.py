"""Orquestación de campañas: etapas en orden, límites de esfuerzo, parada y reanudación (§7, §9, §13.3).

Cada decisión sale de lo persistido y cada etapa guarda su checkpoint antes de informar avance.
Repetir un clic o reanudar recorre lo mismo sin repetir llamadas: las etapas son idempotentes y
el ledger rechaza solicitudes ya enviadas. Primero califican todas las empresas y después se busca
contacto, de mayor a menor prioridad. Ninguna función contacta a nadie.
"""

from datetime import timedelta
import time
from typing import Callable, Literal
from uuid import UUID

from pydantic import Field

from prospecting.budget import Budget, SpendingAuthorization
from prospecting.contacts import derive_readiness
from prospecting.db import Database
from prospecting.discovery import initial_urls
from prospecting.identity import ExclusionList, ExclusionStatus, exclusions_status
from prospecting.models import (
    BusinessStatus, Campaign, CampaignStatus, Contract, Priority, RunStage, Text, utc_now,
)
from prospecting.pipeline.calls import grant_for, seconds_left
from prospecting.pipeline.contacts import find_contacts
from prospecting.pipeline.discovery import DiscoveryReport, resolve_company_identity, run_discovery
from prospecting.pipeline.qualification import qualify_company
from prospecting.pipeline.research import extract_company_pages, research_company
from prospecting.providers import CLAUDE_OPERATION, CLAUDE_PROVIDER, ClaudeClient, ProviderClient
from prospecting.providers.hunter import HunterAccess
from prospecting.providers.tavily import EXTRACT_OPERATION, PROVIDER as TAVILY, SEARCH_OPERATION
from prospecting.sources import is_search_evidence


# Detienen la campaña hasta ampliar presupuesto o autorización (§14): `paused_budget`.
BUDGET_STOPS = {
    "authorization_required", "authorization_unregistered", "authorization_mismatch", "authorization_conflict",
    "authorization_exceeded", "authorization_unknown", "account_unconfigured", "account_unknown",
    "account_cost_unknown", "account_credits_unknown", "budget_unknown", "budget_exceeded",
    "reservation_overrun", "price_unbounded",
}
# Proveedor no disponible para todas las empresas: se detiene la pasada, no la campaña.
PROVIDER_STOPS = {
    "permission_denied", "quota_exceeded", "rate_limited", "local_error", "local", "http_401", "http_403", "http_429",
}
# Extracción hecha, o fallida de forma que repetirla no ayuda: se sigue con la evidencia guardada.
_EXTRACTION_SETTLED = {
    None, "page_limit", "no_valid_urls", "invalid_input", "provider_error", "timeout", "transport_error",
    "invalid_response", "duplicate_request",
}
_HUMAN_REVIEW = ("exclusion_review", "duplicate_review")
_FINAL = {Priority.EXCLUDED: BusinessStatus.EXCLUDED, Priority.LOW: BusinessStatus.LOW_FIT}


class CompanyProgress(Contract):
    company_id: UUID
    stage: RunStage
    priority: Priority | None = None
    business_status: BusinessStatus | None = None
    stop_reason: Text | None = None
    error_message: Text | None = None


class CampaignReport(Contract):
    campaign_id: UUID
    status: CampaignStatus
    stop_reason: Text | None = None
    exclusions_status: ExclusionStatus
    discovery: DiscoveryReport | None = None
    companies: list[CompanyProgress] = Field(default_factory=list)


def start_campaign(db: Database, campaign: Campaign) -> tuple[Campaign, bool]:
    """Activa una campaña nueva; si ya hay una activa, o esta ya existe, la devuelve sin crear otra (§13.3).

    Un clic duplicado o un rerun de Streamlit reutiliza la campaña en lugar de duplicarla.
    """
    with db.transaction():
        existing = db.get_active_campaign() or db.get_campaign(campaign.id)
        if existing is not None:
            return existing, False
        saved = db.save_campaign(campaign.model_copy(update={"status": CampaignStatus.RUNNING,
                                                             "updated_at": utc_now()}))
    return saved, True


def close_campaign(db: Database, campaign_id: UUID) -> Campaign:
    """Libera una campaña `running` o `paused_budget` como `partial`; conserva todo lo guardado."""
    with db.transaction():
        campaign = db.get_campaign(campaign_id)
        if campaign is None:
            raise ValueError("La campaña no existe.")
        if campaign.status in (CampaignStatus.RUNNING, CampaignStatus.PAUSED_BUDGET):
            campaign = db.save_campaign(campaign.model_copy(update={"status": CampaignStatus.PARTIAL,
                                                                    "updated_at": utc_now()}))
    return campaign


def _progress(db: Database, campaign_id: UUID, company_id: UUID) -> CompanyProgress:
    item = db.get_run_item(campaign_id, company_id)
    assessment = None if item.last_assessment_id is None else db.get_assessment(item.last_assessment_id)
    return CompanyProgress(company_id=company_id, stage=item.stage,
                           priority=None if assessment is None else assessment.priority,
                           business_status=item.business_status, stop_reason=item.stop_reason,
                           error_message=item.error_message)


def _report(db: Database, campaign_id: UUID, *, stop_reason=None, exclusions=None, discovery=None) -> CampaignReport:
    return CampaignReport(
        campaign_id=campaign_id, status=db.get_campaign(campaign_id).status, stop_reason=stop_reason,
        exclusions_status=exclusions_status(exclusions), discovery=discovery,
        companies=[_progress(db, campaign_id, item.company_id) for item in db.list_run_items(campaign_id)],
    )


def _set_status(db: Database, campaign_id: UUID, status: CampaignStatus) -> None:
    campaign = db.get_campaign(campaign_id)
    db.save_campaign(campaign.model_copy(update={"status": status, "updated_at": utc_now()}))


class _Run:
    """Una sesión de ejecución de la campaña; su estado vive en SQLite, no aquí."""

    def __init__(self, db, budget, client, campaign, *, authorizations, tavily_account_ref, claude,
                 claude_account_ref, claude_funding_source, hunter_access, exclusions, progress):
        self.db, self.budget, self.client, self.campaign = db, budget, client, campaign
        self.authorizations, self.tavily_account_ref = authorizations or [], tavily_account_ref
        self.claude, self.claude_account_ref = claude, claude_account_ref
        self.claude_funding_source, self.hunter_access = claude_funding_source, hunter_access
        self.exclusions, self.progress = exclusions, progress
        used = sum(item.consumed_limits.active_seconds for item in db.list_run_items(campaign.id))
        # Tope global (§9): el tiempo ya registrado por las empresas se descuenta al reanudar.
        self.deadline = time.monotonic() + max(0.0, campaign.limits.active_seconds - used)
        self.paused = self.failed = self.stop_reason = None

    # Estado, tiempo y parada comunes a todas las pasadas.

    def out_of_time(self) -> bool:
        if seconds_left(self.deadline) > 0:
            return False
        self.stop_reason = self.stop_reason or "campaign_time_limit"
        return True

    def company_deadline(self, company_id: UUID, levels: tuple[str, ...]) -> float:
        """Tiempo activo de la empresa antes de contactos (§9); contactos registra el suyo aparte."""
        consumed = self.db.get_run_item(self.campaign.id, company_id).consumed_limits
        spent = consumed.active_seconds - consumed.contacts_active_seconds
        allowed = sum(self.campaign.limits.effort[level].active_seconds for level in levels)
        return min(self.deadline, time.monotonic() + max(0.0, allowed - spent))

    def timed(self, company_id: UUID, step: Callable):
        """Ejecuta una etapa y suma su duración al tiempo activo de la empresa, aunque falle."""
        started = time.monotonic()
        try:
            return step()
        finally:
            elapsed = time.monotonic() - started
            with self.db.transaction():
                item = self.db.get_run_item(self.campaign.id, company_id)
                consumed = item.consumed_limits.model_copy(update={
                    "active_seconds": item.consumed_limits.active_seconds + elapsed})
                self.db.save_run_item(item.model_copy(update={"consumed_limits": consumed}))

    def company_capped(self, company_id: UUID) -> bool:
        """El tope por empresa acumula todas sus campañas (§14.6): agotado, no vuelve a tener saldo."""
        company = self.budget.snapshot(self.campaign.id, company_id).company
        return company.exceeded or company.available == 0

    def halt(self, reason: str | None, company_id: UUID | None) -> bool:
        """True si la pasada se detiene; el presupuesto agotado pausa además la campaña."""
        if reason in BUDGET_STOPS:
            if company_id is not None and self.company_capped(company_id):
                return False  # Solo se agotó el tope de esta empresa: la campaña sigue con las demás.
            self.paused = reason
            return True
        if reason in PROVIDER_STOPS:
            self.stop_reason = self.stop_reason or reason
            return True
        return False

    def update(self, company_id: UUID, **changes) -> None:
        item = self.db.get_run_item(self.campaign.id, company_id)
        self.db.save_run_item(item.model_copy(update=changes | {"updated_at": utc_now()}))

    def complete(self, company_id: UUID, business_status: BusinessStatus | None, stop_reason: str | None) -> None:
        self.update(company_id, stage=RunStage.COMPLETED, business_status=business_status, stop_reason=stop_reason)

    def notify(self, company_id: UUID) -> None:
        if self.progress is not None:
            self.progress(_progress(self.db, self.campaign.id, company_id))

    def pending(self, stages: tuple[RunStage, ...]) -> list[UUID]:
        return [item.company_id for item in self.db.list_run_items(self.campaign.id) if item.stage in stages]

    def identity(self, company_id: UUID):
        return self.timed(company_id, lambda: resolve_company_identity(
            self.db, self.campaign.id, company_id, exclusions=self.exclusions))

    def qualify(self, company_id: UUID, levels: tuple[str, ...]):
        return self.timed(company_id, lambda: qualify_company(
            self.db, self.budget, self.claude, self.campaign.id, company_id, account_ref=self.claude_account_ref,
            funding_source=self.claude_funding_source, deadline=self.company_deadline(company_id, levels),
            authorization=grant_for(self.authorizations, CLAUDE_PROVIDER, CLAUDE_OPERATION, self.claude_account_ref)))

    # Pasadas, en el orden del flujo de §7.

    def execute(self) -> DiscoveryReport | None:
        discovery = None
        if not self.db.list_run_items(self.campaign.id):
            if self.out_of_time():
                return None
            discovery = run_discovery(
                self.db, self.budget, self.client, self.campaign.id, account_ref=self.tavily_account_ref,
                authorization=grant_for(self.authorizations, TAVILY, SEARCH_OPERATION, self.tavily_account_ref),
                deadline=self.deadline, exclusions=self.exclusions)
            self.halt(discovery.stop_reason, None)
            if self.paused:
                return discovery
            if not discovery.selected_company_ids:
                failures = [query.stop_reason for query in discovery.queries if query.status == "failed"]
                if failures:
                    self.failed = discovery.stop_reason or failures[0]
                return discovery
        for stage in (self.initial_pass, self.qualification_pass, self.contacts_pass):
            if self.paused or self.out_of_time():
                break
            stage()
        return discovery

    def initial_pass(self) -> None:
        """Análisis inicial (§9): páginas propias aún no leídas o caducadas, identidad y etapa `researched`."""
        limits = self.campaign.limits
        for company_id in self.pending((RunStage.DISCOVERED, RunStage.IDENTITY_RESOLVED)):
            if self.out_of_time():
                return
            if self.db.get_run_item(self.campaign.id, company_id).business_status == BusinessStatus.EXCLUDED:
                self.update(company_id, stage=RunStage.RESEARCHED)
                continue
            company, evidence, now = self.db.get_company(company_id), self.db.list_evidence(company_id), utc_now()
            fresh = {str(item.url) for item in evidence if item.url is not None and not is_search_evidence(item)
                     and now - timedelta(days=limits.cache.web_days) <= item.retrieved_at <= now}
            urls = [url for url in initial_urls(company, evidence, len(evidence) + 1) if url not in fresh]
            report = self.timed(company_id, lambda: extract_company_pages(
                self.db, self.budget, self.client, self.campaign.id, company_id, urls[:limits.effort["initial"].pages],
                account_ref=self.tavily_account_ref, deadline=self.company_deadline(company_id, ("initial",)),
                authorization=grant_for(self.authorizations, TAVILY, EXTRACT_OPERATION, self.tavily_account_ref)))
            if report.stop_reason not in _EXTRACTION_SETTLED:
                self.notify(company_id)
                if self.halt(report.stop_reason, company_id):
                    return
                continue
            self.identity(company_id)
            item = self.db.get_run_item(self.campaign.id, company_id)
            self.update(company_id, stage=max(item.stage, RunStage.RESEARCHED, key=list(RunStage).index))
            self.notify(company_id)

    def qualification_pass(self) -> None:
        """Calificación y, si la evidencia es insuficiente, una ampliación y una recalificación (§7)."""
        if self.claude is None or self.claude_account_ref is None:
            if self.pending((RunStage.RESEARCHED,)):
                self.stop_reason = self.stop_reason or "qualification_unavailable"
            return
        for company_id in self.pending((RunStage.RESEARCHED, RunStage.ASSESSED)):
            if self.out_of_time():
                return
            stop = self.qualify_company(company_id)
            self.notify(company_id)
            if stop:
                return

    def qualify_company(self, company_id: UUID) -> bool:
        report = self.qualify(company_id, ("initial",))
        if report.status == "pending":
            return self.halt(report.reason, company_id)
        if report.priority == Priority.INSUFFICIENT_EVIDENCE:
            identity = self.identity(company_id)
            if not (identity.decision.stop_reason or "").startswith(_HUMAN_REVIEW):
                levels = ("initial", "insufficient_evidence")
                research = self.timed(company_id, lambda: research_company(
                    self.db, self.budget, self.client, self.campaign.id, company_id,
                    account_ref=self.tavily_account_ref, authorizations=self.authorizations,
                    deadline=self.company_deadline(company_id, levels)))
                if research.status == "pending":
                    return self.halt(research.stop_reason, company_id)
                identity = self.identity(company_id)
                report = self.qualify(company_id, levels)
                if report.status == "pending":
                    return self.halt(report.reason, company_id)
            if report.priority == Priority.INSUFFICIENT_EVIDENCE:
                current = self.db.get_run_item(self.campaign.id, company_id).stop_reason
                reason = (identity.decision.stop_reason if identity.decision.status == "pending"
                          else current or "insufficient_evidence")
                self.complete(company_id, BusinessStatus.INSUFFICIENT_EVIDENCE, reason)
        if report.priority in _FINAL:
            self.complete(company_id, _FINAL[report.priority],
                          self.db.get_run_item(self.campaign.id, company_id).stop_reason)
        return False

    def contacts_pass(self) -> None:
        """Contactos de empresas `high` y luego `medium`, por encaje descendente (§9)."""
        queue = []
        for company_id in self.pending((RunStage.ASSESSED, RunStage.CONTACTS_CHECKED)):
            item = self.db.get_run_item(self.campaign.id, company_id)
            assessment = None if item.last_assessment_id is None else self.db.get_assessment(item.last_assessment_id)
            if assessment is not None and assessment.priority in (Priority.HIGH, Priority.MEDIUM):
                queue.append((assessment.priority != Priority.HIGH, -(assessment.fit_score or 0), str(company_id),
                              company_id, assessment))
        for *_, company_id, assessment in sorted(queue):
            if self.out_of_time():
                return
            report = find_contacts(
                self.db, self.budget, self.client, self.campaign.id, company_id, hunter_access=self.hunter_access,
                authorizations=self.authorizations, tavily_account_ref=self.tavily_account_ref, claude=self.claude,
                claude_account_ref=self.claude_account_ref, claude_funding_source=self.claude_funding_source,
                deadline=self.deadline)
            capped = (report.status == "pending" and report.stop_reason in BUDGET_STOPS
                      and self.company_capped(company_id))
            exhausted = capped or (report.stop_reason == "time_limit" and seconds_left(self.deadline) > 0)
            if report.status in ("checked", "already_checked") or exhausted:
                # Agotar el tiempo o el tope de la empresa es parar por cupo (§9, §10.3), no un fallo técnico.
                self.complete(company_id, report.business_status, report.stop_reason)
            elif report.status == "skipped":
                company = self.db.get_company(company_id)
                self.complete(company_id, derive_readiness(
                    assessment, self.db.list_contacts(company_id), self.db.list_evidence(company_id),
                    self.campaign.limits, utc_now(), company), report.stop_reason)
            self.notify(company_id)
            if report.status == "pending" and not exhausted and self.halt(report.stop_reason, company_id):
                return


def run_campaign(db: Database, budget: Budget, client: ProviderClient, campaign_id: UUID, *,
                 authorizations: list[SpendingAuthorization] | None, tavily_account_ref: str,
                 claude: ClaudeClient | None = None, claude_account_ref: str | None = None,
                 claude_funding_source: Literal["free_credit", "prepaid", "new_outlay"] = "prepaid",
                 hunter_access: HunterAccess | None = None, exclusions: ExclusionList | None = None,
                 progress: Callable[[CompanyProgress], None] | None = None) -> CampaignReport:
    """Ejecuta o reanuda una campaña de principio a fin, sin pedir aprobación entre empresas (§6).

    Descubre si aún no hay empresas; después análisis inicial, calificación con una ampliación
    acotada y contactos. Termina en `completed` si todas las empresas tienen resultado; `partial`
    si alguna quedó pendiente o se agotó el tiempo global; `paused_budget` si falta presupuesto o
    autorización; `failed` si el descubrimiento no deja empresas por error o ante una excepción,
    que se relanza. Una interrupción deja la campaña `running` para reanudarla.
    """
    with db.transaction():
        campaign = db.get_campaign(campaign_id)
        if campaign is None:
            raise ValueError("La campaña no existe.")
        active = db.get_active_campaign()
        blocked = active is not None and active.id != campaign_id
        # Una campaña terminada no se vuelve a ejecutar: repetir el clic solo devuelve su resultado.
        if not blocked and campaign.status != CampaignStatus.COMPLETED:
            db.save_campaign(campaign.model_copy(update={"status": CampaignStatus.RUNNING, "updated_at": utc_now()}))
    if blocked or campaign.status == CampaignStatus.COMPLETED:
        return _report(db, campaign_id, stop_reason="another_campaign_active" if blocked else None,
                       exclusions=exclusions)
    run = _Run(db, budget, client, db.get_campaign(campaign_id), authorizations=authorizations,
               tavily_account_ref=tavily_account_ref, claude=claude, claude_account_ref=claude_account_ref,
               claude_funding_source=claude_funding_source, hunter_access=hunter_access,
               exclusions=exclusions, progress=progress)
    try:
        discovery = run.execute()
    except Exception:
        _set_status(db, campaign_id, CampaignStatus.FAILED)
        raise
    items = db.list_run_items(campaign_id)
    if run.failed:
        status = CampaignStatus.FAILED
    elif run.paused:
        status = CampaignStatus.PAUSED_BUDGET
    elif run.stop_reason is None and all(item.stage == RunStage.COMPLETED for item in items):
        status = CampaignStatus.COMPLETED
    else:
        status = CampaignStatus.PARTIAL
    _set_status(db, campaign_id, status)
    return _report(db, campaign_id, stop_reason=run.failed or run.paused or run.stop_reason,
                   exclusions=exclusions, discovery=discovery)
