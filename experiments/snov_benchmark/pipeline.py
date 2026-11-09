"""Orquesta exclusivamente el experimento; nunca abre la base operativa."""

from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4, uuid5

from prospecting.budget import AccountAllowance, Budget, BudgetError, Observation, RequestLimit
from prospecting.contacts import ContactError
from prospecting.db import Database
from prospecting.models import Campaign, RunItem, Usage, VeryfiConfig, utc_now
from prospecting.providers.apollo import FREE_RATE_LIMITS

from .contracts import (
    BenchmarkApproval, BenchmarkCapture, BenchmarkManifest, ProviderAccess, company_model, manifest_digest,
)
from .providers import (
    apollo_reveal_request, apollo_search_request, parse_apollo_reveal, parse_apollo_search,
    parse_snov_reveal, parse_snov_search, parse_snov_task, snov_auth_request,
    snov_poll_request, snov_reveal_request, snov_search_request,
)
from .transport import BenchmarkProviderError, BenchmarkTransport, decode_response


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data" / "experiments" / "snov-benchmark"
OPERATIONS = {
    "apollo": {"people_search", "people_enrichment"},
    "snov": {"oauth", "people_search", "people_search_result", "people_enrichment", "people_enrichment_result"},
}


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except RecursionError:
        raise ValueError("El JSON supera la profundidad permitida.") from None


def write_json(path, value):
    """Sustituye solo un checkpoint propio y completo, sin truncarlo ante una caída."""
    path = Path(path)
    pending = path.with_name(path.name + ".tmp")
    with pending.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)


def private_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to(DATA_ROOT.resolve()) or path == DATA_ROOT.resolve():
        raise ValueError("Los expedientes reales deben permanecer bajo data/experiments/snov-benchmark/.")
    return path


def load_inputs(manifest_path, access_path, approvals_path):
    inputs = (
        BenchmarkManifest.model_validate(read_json(manifest_path)),
        [ProviderAccess.model_validate(item) for item in read_json(access_path)],
        BenchmarkApproval.model_validate(read_json(approvals_path)),
    )
    if inputs[0].origin == "real":
        for path in (manifest_path, access_path, approvals_path):
            private_path(path)
    return inputs


def preflight(manifest, access, approval, *, live=False, now=None):
    """Comprueba evidencia local; no crea directorios, abre SQLite ni autentica."""
    now = now or utc_now()
    blockers = []
    if (manifest.origin == "real") != live:
        blockers.append("origin_mismatch")
    if manifest.created_at > now or any(company.observed_at > now for company in manifest.companies):
        blockers.append("future_manifest")
    if approval.benchmark_id != manifest.benchmark_id or approval.manifest_sha256 != manifest_digest(manifest):
        blockers.append("approval_manifest_mismatch")
    if not now - timedelta(hours=1) <= approval.approved_at <= now:
        blockers.append("authorization_expired")
    if approval.approved_at < manifest.created_at:
        blockers.append("authorization_predates_manifest")
    if live and (DATA_ROOT / ".approval-sessions" / f"{approval.session_id}.json").exists():
        blockers.append("authorization_reused")
    if {item.provider for item in access} != set(OPERATIONS) or len(access) != 2:
        blockers.append("access_missing")
    grants = {(item.provider, item.operation, item.account_ref): item for item in approval.approvals}
    if len(grants) != len(approval.approvals):
        blockers.append("duplicate_authorization")
    expected = set()
    for item in access:
        expected.update((item.provider, operation, item.account_ref) for operation in OPERATIONS[item.provider])
        if not item.access_verified or not item.usage_consolidated_verified:
            blockers.append("access_unverified")
        if set(item.operation_bounds) != OPERATIONS[item.provider]:
            blockers.append("unexpected_operations")
        if not now - timedelta(days=1) <= item.observed_at <= now:
            blockers.append("access_expired")
        if item.prior_credits_used > item.credit_limit or item.prior_cost_usd > item.cost_limit_usd:
            blockers.append("account_exhausted")
        for operation in OPERATIONS[item.provider]:
            bound = item.operation_bounds.get(operation)
            if bound is None or operation not in item.rate_limits:
                blockers.append("operation_unbounded")
                continue
            if not bound.source_reference or not bound.observed_at <= now:
                blockers.append("price_unverified")
            if item.funding_source == "free_credit" and bound.cost_usd != 0:
                blockers.append("funding_mismatch")
            if operation == "people_enrichment" and bound.credits < 1:
                blockers.append("reveal_unbounded")
            if item.provider == "snov" and operation == "people_enrichment_result" and (bound.credits or bound.cost_usd):
                blockers.append("reveal_double_reservation")
            grant = grants.get((item.provider, operation, item.account_ref))
            if grant and (grant.max_cost_usd < bound.cost_usd or grant.max_credits < bound.credits):
                blockers.append("authorization_insufficient")
            if live:
                rate = item.rate_limits[operation]
                if item.provider == "snov" and rate.per_minute > 60:
                    blockers.append("rate_unverified")
                if item.provider == "apollo" and any(getattr(rate, name) > getattr(FREE_RATE_LIMITS[operation], name)
                        for name in ("per_minute", "per_hour", "per_day")):
                    blockers.append("rate_unverified")
        if live:
            required = ["APOLLO_API_KEY"] if item.provider == "apollo" else ["SNOV_CLIENT_ID", "SNOV_CLIENT_SECRET"]
            if any(not os.environ.get(name, "").strip() for name in required):
                blockers.append("credentials_missing")
    if set(grants) != expected:
        blockers.append("authorization_required")
    if any(item.authorized_at != approval.approved_at for item in approval.approvals):
        blockers.append("authorization_session_mismatch")
    config_path = PROJECT_ROOT / "config" / "veryfi.json"
    config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
    if manifest.config_versions.get("veryfi_sha256") != config_hash:
        blockers.append("config_changed")
    config = VeryfiConfig.model_validate(read_json(config_path))
    if len(manifest.companies) > config.defaults.max_companies:
        blockers.append("sample_limit")
    if manifest.contact_days != config.defaults.cache.contact_days:
        blockers.append("freshness_changed")
    return sorted(set(blockers))


@contextmanager
def experiment_lock(output):
    """El bloqueo del sistema se libera también si termina el proceso."""
    with (output / ".lock").open("a+b") as stream:
        try:
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("Otra ejecución usa este expediente.") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class _Stop(Exception):
    def __init__(self, code, message, *, uncertain=False):
        super().__init__(message)
        self.code, self.uncertain = code, uncertain


class _Runner:
    def __init__(self, manifest, access, approval, output, transport, db, state):
        self.manifest, self.output, self.transport, self.db, self.state = manifest, output, transport, db, state
        self.access = {item.provider: item for item in access}
        self.last_tick = time.monotonic()
        self.deadline = self.last_tick + max(0, manifest.limits.max_seconds - state.get("active_seconds", 0))
        self.observed_at = utc_now()
        config = VeryfiConfig.model_validate(read_json(PROJECT_ROOT / "config" / "veryfi.json"))
        campaign = Campaign(id=manifest.benchmark_id, countries=sorted({c.country for c in manifest.companies}),
            segments=sorted({c.segment for c in manifest.companies}), max_companies=len(manifest.companies),
            config_snapshot=config)
        previous = db.get_campaign(campaign.id)
        if previous is None:
            db.save_campaign(campaign)
        elif previous.config_snapshot != campaign.config_snapshot:
            raise ValueError("La configuración del ledger cambió.")
        for company in manifest.companies:
            if db.get_company(company.company_id) is None:
                model, facts = company_model(company)
                db.save_company(model, evidence=facts)
            if db.get_run_item(campaign.id, company.company_id) is None:
                db.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.company_id))
        allowances = [AccountAllowance(provider=item.provider, account_ref=item.account_ref,
            funding_source=item.funding_source, credit_limit=item.credit_limit, cost_limit_usd=item.cost_limit_usd,
            source_reference=item.source_reference, observed_at=item.observed_at) for item in access]
        self.budget = Budget(db, config.defaults.budget, allowances)
        self.grants = {}
        for item in approval.approvals:
            grant = item.model_copy(update={"authorized_at": utc_now(),
                "source_reference": f"{item.source_reference}; sesión {approval.session_id}; aprobado {approval.approved_at.isoformat()}"})
            self.grants[item.provider, item.operation] = self.budget.authorize(grant)
        self.budget.limit_requests([RequestLimit(provider=item.provider, operation=operation, account_ref=item.account_ref,
            window_seconds=window, max_requests=getattr(rate, name))
            for item in access for operation, rate in item.rate_limits.items()
            for window, name in ((60, "per_minute"), (3600, "per_hour"), (86400, "per_day"))])
        self._opening_balances(campaign, access)

    def _opening_balances(self, campaign, access):
        """Representa consumo previo comprobado; nunca lo informa como gasto nuevo del lote."""
        opening_id = uuid5(campaign.id, "opening-balances")
        if self.db.get_campaign(opening_id) is None:
            self.db.save_campaign(campaign.model_copy(update={"id": opening_id}))
        for item in access:
            request_id = uuid5(opening_id, item.provider)
            previous = self.db.get_usage(request_id)
            if previous is not None:
                if (previous.account_ref != item.account_ref or previous.funding_source != item.funding_source
                        or previous.credits != item.prior_credits_used or previous.final_cost_usd != item.prior_cost_usd):
                    raise ValueError("El saldo de apertura no se sustituye al reanudar.")
                continue
            self.db.save_usage(Usage(request_id=request_id, campaign_id=opening_id, provider=item.provider,
                operation="opening_balance", account_ref=item.account_ref,
                request_fingerprint=hashlib.sha256(item.usage_source_reference.encode()).hexdigest(),
                reserved_cost_usd=item.prior_cost_usd, reserved_credits=item.prior_credits_used,
                final_cost_usd=item.prior_cost_usd, credits=item.prior_credits_used, outlay_usd="0",
                funding_source=item.funding_source, status="reconciled", outcome="succeeded",
                created_at=item.observed_at, finished_at=item.observed_at, reconciled_at=item.observed_at))

    def save(self):
        tick = time.monotonic()
        self.state["active_seconds"] = self.state.get("active_seconds", 0) + tick - self.last_tick
        self.last_tick = tick
        write_json(self.output / "state.json", self.state)

    def _limits(self, company_id, provider):
        if time.monotonic() >= self.deadline:
            raise _Stop("time_limit", "Se agotó el tiempo del experimento.")
        rows = self.db.list_usage(campaign_id=self.manifest.benchmark_id, provider=provider)
        if sum(row.company_id == company_id for row in rows) >= self.manifest.limits.max_requests:
            raise _Stop("request_limit", "Se agotó el tope de solicitudes del brazo.")
        # Snov comparte tasa entre endpoints; se aplica conservadoramente a ambos proveedores.
        access = self.access[provider]
        for seconds, name in ((60, "per_minute"), (3600, "per_hour"), (86400, "per_day")):
            maximum = min(getattr(rate, name) for rate in access.rate_limits.values())
            if sum(row.created_at >= utc_now() - timedelta(seconds=seconds) for row in rows) >= maximum:
                raise _Stop("rate_limit", "Se alcanzó la tasa local comprobada.")

    def call(self, company, capture, spec, logical_key):
        cache_key = f"{company.company_id}:{spec.provider}:{logical_key}"
        old = self.state["calls"].get(cache_key)
        if old is not None:
            if old.get("response") is not None:
                self.observed_at = datetime.fromisoformat(old["observed_at"])
                return old["response"]
            if old.get("failure") is not None:
                failure = old["failure"]
                raise _Stop(failure["code"], failure["message"], uncertain=failure["uncertain"])
            raise _Stop("uncertain_request", "La solicitud previa requiere revisión; no se repite.", uncertain=True)
        self._limits(company.company_id, spec.provider)
        access = self.access[spec.provider]
        bound = access.operation_bounds[spec.operation]
        fingerprint = hashlib.sha256(cache_key.encode()).hexdigest()
        grant = self.grants[spec.provider, spec.operation]
        usage = self.budget.reserve(Usage(campaign_id=self.manifest.benchmark_id, company_id=company.company_id,
            provider=spec.provider, operation=spec.operation, account_ref=access.account_ref,
            request_fingerprint=fingerprint, reserved_cost_usd=bound.cost_usd, reserved_credits=bound.credits,
            funding_source=access.funding_source, status="reserved"), grant)
        record = {"request_id": str(usage.request_id), "operation": spec.operation, "logical_task": logical_key,
            "reserved_credits": str(bound.credits), "reserved_cost_usd": str(bound.cost_usd),
            "credits": None, "final_cost_usd": None, "elapsed_seconds": None, "outcome": "unknown"}
        capture.requests.append(record)
        self.state["calls"][cache_key] = {"request_id": str(usage.request_id), "response": None}
        self.save()
        sent = False
        start = time.monotonic()
        try:
            self.budget.claim(usage.request_id, fingerprint, grant)
            self.budget.begin_send(usage.request_id, deadline=self.deadline)
            sent = True
            response = self.transport.send(spec, timeout_seconds=min(self.manifest.limits.timeout_seconds,
                max(0.001, self.deadline - time.monotonic())), max_bytes=1_048_576)
            raw = decode_response(response)
            self.observed_at = utc_now()
            self.budget.record_result(usage.request_id, Observation(outcome="succeeded"))
            record["outcome"] = "succeeded"
            self.state["calls"][cache_key]["response"] = raw
            self.state["calls"][cache_key]["observed_at"] = self.observed_at.isoformat()
            return raw
        except (BenchmarkProviderError, BudgetError) as error:
            code = getattr(error, "code", "provider_error")
            message = str(error)
            uncertain = sent and code in {"timeout", "transport_error", "invalid_response", "response_too_large"}
            if sent:
                self.budget.record_result(usage.request_id, Observation(
                    outcome="unknown" if uncertain else "failed", error_message=message))
            record.update(error=message, outcome="unknown" if uncertain else "failed",
                http_status=getattr(error, "http_status", None), retry_after=getattr(error, "retry_after", None))
            self.state["calls"][cache_key]["failure"] = {"code": code, "message": message, "uncertain": uncertain}
            raise _Stop(code, message, uncertain=uncertain) from None
        finally:
            record["elapsed_seconds"] = time.monotonic() - start
            record["observed_at"] = utc_now().isoformat()
            self.save()

    def authenticate(self, company, capture):
        if not self.transport.snov_authenticated:
            key = "oauth:" + str(uuid4())
            self.call(company, capture, snov_auth_request(), key)

    def poll(self, company, capture, task_hash, *, reveal=False):
        prefix = f"poll:{'reveal' if reveal else 'search'}:{task_hash}:"
        previous_calls = [value for key, value in self.state["calls"].items()
            if key.startswith(f"{company.company_id}:snov:{prefix}")]
        for old in previous_calls:
            if (old.get("response") or {}).get("status") == "completed":
                self.observed_at = datetime.fromisoformat(old["observed_at"])
                return old["response"]
            if old.get("response") is None:
                raise _Stop("uncertain_request", "El polling previo requiere revisión.", uncertain=True)
        previous = len(previous_calls)
        for index in range(previous, self.manifest.limits.max_polls):
            self.authenticate(company, capture)
            raw = self.call(company, capture, snov_poll_request(task_hash, reveal=reveal), prefix + str(index))
            if raw.get("status") == "completed":
                return raw
            if raw.get("status") != "in_progress":
                raise _Stop("invalid_status", "Snov devolvió un estado de tarea no reconocido.")
            wait = self.manifest.limits.poll_interval_seconds
            if time.monotonic() + wait >= self.deadline:
                raise _Stop("time_limit", "La tarea sigue pendiente al agotar el tiempo.")
            time.sleep(wait)
        raise _Stop("poll_limit", "La tarea sigue pendiente al agotar el polling.")

    def arm(self, company, capture):
        seen = set()
        for page in range(1, self.manifest.limits.max_pages + 1):
            if capture.provider == "snov":
                self.authenticate(company, capture)
                task = parse_snov_task(self.call(company, capture, snov_search_request(company, page), f"search:{page}"))
                raw = self.poll(company, capture, task)
                parsed = parse_snov_search(raw, company, self.observed_at)
                candidates, total_pages = parsed.candidates, parsed.total_pages
            else:
                raw = self.call(company, capture, apollo_search_request(company, page), f"search:{page}")
                candidates = parse_apollo_search(raw, company, self.observed_at)
                total_pages = (raw["total_entries"] + 9) // 10
            for person in candidates:
                if person.id in seen:
                    continue
                seen.add(person.id)
                capture.candidates.append(person)
                self.save()
                if person.domain != company.domain and (capture.provider == "snov" or person.domain is not None):
                    capture.errors.append({"code": "entity_mismatch", "stage": "search", "message": "Dominio ajeno; no se revela."})
                    continue
                reveals = sum(key.startswith(f"{company.company_id}:{capture.provider}:reveal:")
                    for key in self.state["calls"])
                cached_reveal = f"{company.company_id}:{capture.provider}:reveal:{person.id}" in self.state["calls"]
                if reveals >= self.manifest.limits.max_people and not cached_reveal:
                    continue
                if capture.provider == "snov":
                    self.authenticate(company, capture)
                    task = parse_snov_task(self.call(company, capture, snov_reveal_request(person.source_reference), f"reveal:{person.id}"))
                    raw = self.poll(company, capture, task, reveal=True)
                    enriched = parse_snov_reveal(raw, person, self.observed_at).person
                else:
                    raw = self.call(company, capture, apollo_reveal_request(person), f"reveal:{person.id}")
                    enriched = parse_apollo_reveal(raw, company, person, self.observed_at)
                if enriched is not None:
                    capture.candidates[-1] = enriched
                self.save()
            if not candidates or total_pages is not None and page >= total_pages:
                break
        capture.status = "completed"


def run_benchmark(manifest, access, approval, output, *, live=False, transport=None):
    """Un permiso habilita un intento; la evidencia de proveedor queda sin conciliar."""
    blockers = preflight(manifest, access, approval, live=live)
    if blockers:
        raise ValueError("Preflight bloqueado: " + ", ".join(blockers))
    if not live and transport is None:
        raise ValueError("El modo sintético exige transporte simulado explícito.")
    if not live and isinstance(transport, BenchmarkTransport):
        raise ValueError("El modo sintético no admite el transporte real.")
    output = private_path(output) if live else Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with experiment_lock(output):
        ledger_path = output / "ledger.sqlite3"
        if ledger_path.resolve().parent != output:
            raise ValueError("El ledger no puede ser un enlace fuera del expediente.")
        digest = manifest_digest(manifest)
        access_values = [{name: item.model_dump(mode="json")[name] for name in (
            "provider", "account_ref", "funding_source", "credit_limit", "cost_limit_usd", "prior_credits_used", "prior_cost_usd")}
            | {"bounds": {name: (str(bound.cost_usd), str(bound.credits)) for name, bound in item.operation_bounds.items()},
               "rates": {name: rate.model_dump() for name, rate in item.rate_limits.items()}} for item in access]
        access_hash = hashlib.sha256(json.dumps(sorted(access_values, key=lambda item: item["provider"]), sort_keys=True).encode()).hexdigest()
        path = output / "state.json"
        if path.exists():
            state = read_json(path)
            if state.get("manifest_sha256") != digest or state.get("origin") != manifest.origin:
                raise ValueError("El expediente pertenece a otra muestra u origen.")
            if state.get("access_sha256") != access_hash:
                raise ValueError("Las cuentas, cupos o costos del expediente no se pueden sustituir.")
            if not ledger_path.exists() and state.get("calls"):
                raise ValueError("Falta el ledger de solicitudes existentes; no se recrea.")
        else:
            if ledger_path.exists():
                raise ValueError("Un ledger existente sin checkpoint no se abre ni se recrea.")
            state = {"manifest_sha256": digest, "origin": manifest.origin, "access_sha256": access_hash,
                "calls": {}, "captures": [], "active_seconds": 0}
        marker_root = DATA_ROOT / ".approval-sessions" if live else output / ".approval-sessions"
        marker_root.mkdir(parents=True, exist_ok=True)
        with (marker_root / f"{approval.session_id}.json").open("x", encoding="utf-8") as stream:
            json.dump({"benchmark_id": str(manifest.benchmark_id), "manifest_sha256": digest,
                "output": str(output), "approved_at": approval.approved_at.isoformat(),
                "approval": approval.model_dump(mode="json"),
                "access": [item.model_dump(mode="json") for item in access]}, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        captures = [BenchmarkCapture.model_validate(item) for item in state["captures"]]
        if ledger_path.exists():
            header = ledger_path.read_bytes()[:100]
            if header[:16] != b"SQLite format 3\x00" or int.from_bytes(header[60:64], "big") != 2:
                raise ValueError("El ledger experimental tiene un formato no comprobado; no se migra.")
        write_json(path, state)
        with Database(ledger_path) as db:
            runner = _Runner(manifest, access, approval, output, transport or BenchmarkTransport(), db, state)
            halted = {item.provider for item in captures if item.status == "uncertain"}
            for company in manifest.companies:
                for provider in ("apollo", "snov"):
                    capture = next((item for item in captures if item.company_id == company.company_id and item.provider == provider), None)
                    if capture is None:
                        capture = BenchmarkCapture(benchmark_id=manifest.benchmark_id, manifest_sha256=digest,
                            provider=provider, company_id=company.company_id, origin=manifest.origin, observed_at=utc_now())
                        captures.append(capture)
                    if capture.status in {"completed", "uncertain"}:
                        continue
                    if provider in halted:
                        capture.status = "blocked"
                        capture.errors = [{"code": "previous_provider_failure", "stage": "contacts",
                            "message": "El proveedor se detuvo en otra empresa; revisar antes de continuar."}]
                        continue
                    capture.candidates = []
                    capture.errors = []
                    # Los checkpoints incluyen el brazo activo antes de cualquier solicitud.
                    original_save = runner.save
                    def save():
                        capture.observed_at = utc_now()
                        state["captures"] = [item.model_dump(mode="json") for item in captures]
                        original_save()
                    runner.save = save
                    try:
                        runner.arm(company, capture)
                    except (_Stop, BudgetError, ContactError, ValueError) as error:
                        capture.status = "uncertain" if getattr(error, "uncertain", False) else "blocked"
                        capture.errors.append({"code": getattr(error, "code", "invalid_response"),
                            "stage": "contacts", "message": str(error) if isinstance(error, (_Stop, BudgetError, ContactError)) else "Respuesta inválida; revisar captura privada."})
                        halted.add(provider)
                    finally:
                        capture.observed_at = utc_now()
                        runner.save()
                        write_json(output / "capture.json", [item.model_dump(mode="json") for item in captures])
                        runner.save = original_save
            state["captures"] = [item.model_dump(mode="json") for item in captures]
            runner.save()
            write_json(output / "capture.json", state["captures"])
        return captures
