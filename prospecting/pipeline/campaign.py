"""Orquestación de campañas: etapas en orden, límites de esfuerzo, parada y reanudación (§7, §9, §13.3).

Cada decisión sale de lo persistido y cada etapa guarda su checkpoint antes de informar avance.
Repetir un clic o reanudar recorre lo mismo sin repetir llamadas: las etapas son idempotentes y
el ledger rechaza solicitudes ya enviadas. Primero califican todas las empresas y después se busca
contacto, de mayor a menor prioridad. Ninguna función contacta a nadie.
"""

from datetime import timedelta
from pathlib import Path
import threading
import time
from typing import Callable, Literal
from uuid import UUID

from pydantic import Field, StrictBool, ValidationError, model_validator

from prospecting.budget import AccountAllowance, Budget, BudgetSnapshot, FundingSource, SpendingAuthorization
from prospecting.contacts import channel_is_usable, derive_readiness, validate_contact
from prospecting.db import Database
from prospecting.discovery import initial_urls
from prospecting.identity import ExclusionList, ExclusionStatus, exclusions_status, load_exclusions
from prospecting.models import (
    Assessment, BusinessStatus, Campaign, CampaignStatus, Channel, ChannelType, Company, Contact, Contract,
    Evidence, Money, Priority, RunItem, RunStage, Text, utc_now,
)
from prospecting.pipeline.calls import grant_for, seconds_left
from prospecting.pipeline.contacts import find_contacts
from prospecting.pipeline.discovery import DiscoveryReport, resolve_company_identity, run_discovery
from prospecting.pipeline.qualification import qualify_company
from prospecting.pipeline.research import extract_company_pages, research_company
from prospecting.providers import CLAUDE_OPERATION, CLAUDE_PROVIDER, ClaudeClient, ProviderClient
from prospecting.providers.hunter import HUNTER_OPERATIONS, HunterAccess, PROVIDER as HUNTER
from prospecting.providers.tavily import EXTRACT_OPERATION, PROVIDER as TAVILY, SEARCH_OPERATION, TAVILY_OPERATIONS
from prospecting.sources import is_search_evidence


# Detienen la campaña hasta ampliar presupuesto o autorización (§14): `paused_budget`.
BUDGET_STOPS = {
    "authorization_required", "authorization_unregistered", "authorization_mismatch", "authorization_conflict",
    "authorization_exceeded", "authorization_unknown", "account_unconfigured", "account_unknown",
    "account_cost_unknown", "account_credits_unknown", "budget_unknown", "budget_exceeded",
    "reservation_overrun", "price_unbounded",
}
# Solo se agotó el tope de una empresa: esa empresa se detiene y la campaña sigue.
COMPANY_BUDGET_STOP = "company_budget_exceeded"
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
# Una ejecución a la vez por proceso (§13.3): Streamlit atiende todas sus sesiones en un solo proceso.
_EXECUTION = threading.Lock()
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


class ProviderAccess(Contract):
    """Cupos comprobados de la instalación local; nunca contiene claves ni permisos."""

    account_allowances: list[AccountAllowance]
    tavily_account_ref: Text
    claude_account_ref: Text
    claude_funding_source: FundingSource = "prepaid"
    hunter_access: HunterAccess | None = None

    @model_validator(mode="after")
    def validate_accounts(self):
        accounts = {(item.provider, item.account_ref): item for item in self.account_allowances}
        if len(accounts) != len(self.account_allowances):
            raise ValueError("Las cuentas de consumo deben tener referencias únicas.")
        expected = [(TAVILY, self.tavily_account_ref, "free_credit"),
                    (CLAUDE_PROVIDER, self.claude_account_ref, self.claude_funding_source)]
        hunter = self.hunter_access
        if hunter is not None:
            if any(operation in ("email_finder", "email_verifier") for operation in hunter.enabled_operations) and not hunter.automatic_lead_saving_disabled:
                raise ValueError("Debe estar comprobada la desactivación del guardado automático de Hunter.")
            expected.extend((provider, account, hunter.funding_source) for provider, _, account in
                            provider_operations(self) if provider == HUNTER)
        if any(accounts.get((provider, account)) is None or
               accounts[provider, account].funding_source != funding for provider, account, funding in expected):
            raise ValueError("Cada proveedor habilitado necesita una cuenta y financiación comprobadas.")
        if any(item.observed_at > utc_now() for item in self.account_allowances):
            raise ValueError("Los cupos comprobados no pueden tener fecha futura.")
        return self


class AuthorizationInput(Contract):
    """Aprobación explícita del formulario; la fecha se asigna en la nueva sesión de Budget."""

    provider: Text
    operation: Text
    account_ref: Text
    max_cost_usd: Money
    max_credits: Money
    responsible: Text
    source_reference: Text


class ContactResult(Contract):
    contact: Contact
    eligible: StrictBool
    usable_channels: list[Channel]


class CompanyResult(Contract):
    company: Company
    run_item: RunItem
    assessment: Assessment | None
    evidence: list[Evidence]
    contacts: list[ContactResult]
    business_status: BusinessStatus | None


class CampaignView(Contract):
    campaign: Campaign
    companies: list[CompanyResult]
    budget: BudgetSnapshot
    is_executing: StrictBool
    exclusions_status: ExclusionStatus


def provider_operations(access: ProviderAccess) -> list[tuple[str, str, str]]:
    """Operaciones acotadas para mostrar y autorizar; no consulta ningún proveedor."""
    operations = [(TAVILY, SEARCH_OPERATION, access.tavily_account_ref),
                  (TAVILY, EXTRACT_OPERATION, access.tavily_account_ref),
                  (CLAUDE_PROVIDER, CLAUDE_OPERATION, access.claude_account_ref)]
    if access.hunter_access is not None:
        hunter = access.hunter_access
        operations.extend((HUNTER, operation,
                           hunter.verification_account_ref or hunter.search_account_ref
                           if operation == "email_verifier" else hunter.search_account_ref)
                          for operation in hunter.enabled_operations)
    return operations


def load_provider_access(path: Path) -> ProviderAccess:
    """Un archivo ausente o inválido bloquea la ejecución, sin mostrar datos del JSON."""
    try:
        return ProviderAccess.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError):
        raise ValueError("No se pudo leer la configuración válida de cupos y acceso a proveedores.") from None


def _saved_database(db_path: Path) -> Database:
    """Consultar y corregir jamás crea una base que no existe."""
    if not Path(db_path).is_file():
        raise ValueError("La base local no existe; primero prepara una campaña.")
    return Database(Path(db_path))


def list_saved_campaigns(db_path: Path) -> list[Campaign]:
    if not Path(db_path).exists():
        return []
    with _saved_database(db_path) as db:
        return db.list_campaigns()


def prepare_campaign(db_path: Path, campaign: Campaign) -> Campaign:
    """Única acción de la interfaz que puede crear la base; guarda un borrador sin tráfico."""
    campaign = Campaign.model_validate(campaign)
    with Database(Path(db_path)) as db, db.transaction():
        existing = db.get_active_campaign() or db.get_campaign(campaign.id)
        if existing is not None:
            return existing
        return db.save_campaign(campaign.model_copy(update={"status": CampaignStatus.CREATED}))


def read_campaign(db_path: Path, campaign_id: UUID, *, account_allowances: list[AccountAllowance] | None = None,
                  exclusions_path: Path | None = None) -> CampaignView:
    """Lectura para la UI/CSV; recalcula persona, canales y disponibilidad con la fecha actual."""
    exclusions = None if exclusions_path is None else load_exclusions(exclusions_path)
    with _saved_database(db_path) as db:
        campaign = db.get_campaign(campaign_id)
        if campaign is None:
            raise ValueError("La campaña no existe.")
        budget = Budget(db, campaign.config_snapshot.defaults.budget, account_allowances or []).snapshot(campaign_id)
        companies, now = [], utc_now()
        with db.transaction():
            for item in db.list_run_items(campaign_id):
                company = db.get_company(item.company_id)
                assessment = None if item.last_assessment_id is None else db.get_assessment(item.last_assessment_id)
                evidence, contacts = db.list_evidence(company.id), db.list_contacts(company.id)
                results = []
                for contact in contacts:
                    eligible = item.business_status != BusinessStatus.EXCLUDED and assessment is not None and validate_contact(
                        contact, company, assessment, evidence, campaign.limits, now)
                    usable = [channel for channel in contact.channels if eligible and channel_is_usable(
                        channel, contact, evidence, campaign.limits, now, company)]
                    results.append(ContactResult(contact=contact, eligible=eligible, usable_channels=usable))
                status = None if assessment is None else derive_readiness(
                    assessment, contacts, evidence, campaign.limits, now, company)
                if item.business_status == BusinessStatus.EXCLUDED:
                    status = BusinessStatus.EXCLUDED
                companies.append(CompanyResult(company=company, run_item=item, assessment=assessment,
                                               evidence=evidence, contacts=results, business_status=status))
        return CampaignView(campaign=campaign, companies=companies, budget=budget,
                            is_executing=_EXECUTION.locked(), exclusions_status=exclusions_status(exclusions))


def _approve(budget: Budget, access: ProviderAccess, approvals: list[AuthorizationInput], campaign_id: UUID
             ) -> list[SpendingAuthorization]:
    allowed = set(provider_operations(access))
    inputs = [AuthorizationInput.model_validate(item) for item in approvals]
    keys = [(item.provider, item.operation, item.account_ref) for item in inputs]
    if len(keys) != len(set(keys)) or any(key not in allowed for key in keys):
        raise ValueError("Cada permiso debe corresponder a una única operación y cuenta habilitadas.")
    snapshot = budget.snapshot(campaign_id)
    costs = (snapshot.global_budget, snapshot.operating, snapshot.campaign)
    if snapshot.reservation_overrun or any(amount.unknown or amount.exceeded for amount in costs):
        raise ValueError("El consumo pendiente necesita conciliación antes de ejecutar.")
    for item in inputs:
        account = next(account for account in snapshot.accounts if
                       (account.provider, account.account_ref) == (item.provider, item.account_ref))
        if account.cost.unknown or account.credits.unknown:
            raise ValueError("Hay consumo de la cuenta sin conciliar; no se autoriza tráfico.")
        if item.max_cost_usd > 0 and any(amount.available is None or item.max_cost_usd > amount.available
                                       for amount in (*costs, account.cost)):
            raise ValueError("El permiso supera el cupo económico disponible.")
        if item.max_credits > 0 and (account.credits.available is None or
                                     item.max_credits > account.credits.available):
            raise ValueError("El permiso supera los créditos comprobados disponibles.")
    return [budget.authorize(SpendingAuthorization(**item.model_dump(), authorized_at=utc_now())) for item in inputs]


def execute_campaign(db_path: Path, campaign_id: UUID, *, access: ProviderAccess,
                     approvals: list[AuthorizationInput], progress: Callable[[CompanyProgress], None] | None = None,
                     exclusions_path: Path | None = None) -> CampaignReport:
    """Una acción explícita crea permisos de sesión frescos; ningún permiso se persiste o reutiliza."""
    access = ProviderAccess.model_validate(access)
    exclusions = None if exclusions_path is None else load_exclusions(exclusions_path)
    with _saved_database(db_path) as db:
        campaign = db.get_campaign(campaign_id)
        if campaign is None:
            raise ValueError("La campaña no existe.")
        if not _EXECUTION.acquire(blocking=False):
            return _report(db, campaign_id, stop_reason="campaign_already_running", exclusions=exclusions)
        try:
            campaign = db.get_campaign(campaign_id)
            active = db.get_active_campaign()
            if campaign.status == CampaignStatus.COMPLETED or (active is not None and active.id != campaign_id):
                return _report(db, campaign_id, stop_reason="another_campaign_active" if
                               active is not None and active.id != campaign_id else None, exclusions=exclusions)
            budget = Budget(db, campaign.config_snapshot.defaults.budget, access.account_allowances)
            authorizations = _approve(budget, access, approvals, campaign_id)
            client = ProviderClient(budget, TAVILY_OPERATIONS + HUNTER_OPERATIONS)
            return _execute(db, campaign_id, exclusions, lambda saved: _Run(
                db, budget, client, saved, authorizations=authorizations, tavily_account_ref=access.tavily_account_ref,
                claude=ClaudeClient(budget), claude_account_ref=access.claude_account_ref,
                claude_funding_source=access.claude_funding_source, hunter_access=access.hunter_access,
                exclusions=exclusions, progress=progress))
        finally:
            _EXECUTION.release()


def finish_campaign(db_path: Path, campaign_id: UUID) -> Campaign:
    if not _EXECUTION.acquire(blocking=False):
        raise ValueError("La campaña está ejecutándose; espera antes de cerrarla.")
    try:
        with _saved_database(db_path) as db:
            return close_campaign(db, campaign_id)
    finally:
        _EXECUTION.release()


def review_company(db_path: Path, campaign_id: UUID, company_id: UUID, *,
                   status: Literal["accepted", "rejected", "pending"], reason: str) -> RunItem:
    if not _EXECUTION.acquire(blocking=False):
        raise ValueError("La campaña está ejecutándose; espera antes de revisarla.")
    try:
        with _saved_database(db_path) as db, db.transaction():
            item = db.get_run_item(campaign_id, company_id)
            if item is None:
                raise ValueError("La empresa no pertenece a esta campaña.")
            now = utc_now()
            updated = RunItem.model_validate(item.model_dump() | {
                "review_status": status, "review_reason": reason, "reviewed_at": now, "updated_at": now,
            })
            return db.save_run_item(updated)
    finally:
        _EXECUTION.release()


def confirm_alternative_channel(db_path: Path, campaign_id: UUID, contact_id: UUID,
                                channel_type: ChannelType, channel_value: str, *, reason: str,
                                confirmed: bool) -> RunItem:
    from prospecting.pipeline.contacts import confirm_alternative_channel as confirm_channel

    if not _EXECUTION.acquire(blocking=False):
        raise ValueError("La campaña está ejecutándose; espera antes de confirmar canales.")
    try:
        with _saved_database(db_path) as db:
            return confirm_channel(db, campaign_id, contact_id, channel_type, channel_value,
                                   reason=reason, confirmed=confirmed)
    finally:
        _EXECUTION.release()


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

    def halt(self, reason: str | None) -> bool:
        """True si la pasada se detiene; el presupuesto agotado pausa además la campaña.

        `company_budget_exceeded` (solo el tope de esa empresa) no detiene nada: la campaña
        sigue con las demás.
        """
        if reason in BUDGET_STOPS:
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
            self.halt(discovery.stop_reason)
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
            # El nombre inferido (`inference`) cita la URL del resultado sin haber leído la página.
            fresh = {str(item.url) for item in evidence if item.url is not None and item.kind == "observed"
                     and not is_search_evidence(item)
                     and now - timedelta(days=limits.cache.web_days) <= item.retrieved_at <= now}
            urls = [url for url in initial_urls(company, evidence, len(evidence) + 1) if url not in fresh]
            report = self.timed(company_id, lambda: extract_company_pages(
                self.db, self.budget, self.client, self.campaign.id, company_id, urls[:limits.effort["initial"].pages],
                account_ref=self.tavily_account_ref, deadline=self.company_deadline(company_id, ("initial",)),
                authorization=grant_for(self.authorizations, TAVILY, EXTRACT_OPERATION, self.tavily_account_ref)))
            if report.stop_reason not in _EXTRACTION_SETTLED:
                self.notify(company_id)
                if self.halt(report.stop_reason):
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
            return self.halt(report.reason)
        if report.priority == Priority.INSUFFICIENT_EVIDENCE:
            identity = self.identity(company_id)
            if not (identity.decision.stop_reason or "").startswith(_HUMAN_REVIEW):
                levels = ("initial", "insufficient_evidence")
                research = self.timed(company_id, lambda: research_company(
                    self.db, self.budget, self.client, self.campaign.id, company_id,
                    account_ref=self.tavily_account_ref, authorizations=self.authorizations,
                    deadline=self.company_deadline(company_id, levels)))
                if research.status == "pending":
                    return self.halt(research.stop_reason)
                identity = self.identity(company_id)
                report = self.qualify(company_id, levels)
                if report.status == "pending":
                    return self.halt(report.reason)
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
            # El tope por empresa acumula todas sus campañas (§14.6): agotado, no vuelve a tener saldo.
            capped = report.status == "pending" and report.stop_reason == COMPANY_BUDGET_STOP
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
            if report.status == "pending" and not exhausted and self.halt(report.stop_reason):
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
    que se relanza. Una interrupción deja la campaña `running` para reanudarla. Mientras otra
    ejecución sigue en curso en este proceso, no hace nada y devuelve `campaign_already_running`.
    """
    if not _EXECUTION.acquire(blocking=False):
        if db.get_campaign(campaign_id) is None:
            raise ValueError("La campaña no existe.")
        return _report(db, campaign_id, stop_reason="campaign_already_running", exclusions=exclusions)
    try:
        return _execute(db, campaign_id, exclusions, lambda campaign: _Run(
            db, budget, client, campaign, authorizations=authorizations, tavily_account_ref=tavily_account_ref,
            claude=claude, claude_account_ref=claude_account_ref, claude_funding_source=claude_funding_source,
            hunter_access=hunter_access, exclusions=exclusions, progress=progress))
    finally:
        _EXECUTION.release()


def _execute(db: Database, campaign_id: UUID, exclusions: ExclusionList | None,
             build: Callable[[Campaign], _Run]) -> CampaignReport:
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
    run = build(db.get_campaign(campaign_id))
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
