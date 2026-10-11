"""Persistencia local con transacciones, procedencia y contratos revalidados."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Iterator, Sequence
from uuid import UUID

from prospecting.models import (
    Assessment, Campaign, Company, Contact, Evidence, RunItem, RunStage, Usage,
)


_TABLES = {
    Campaign: ("campaigns", ("id",), {"countries", "segments", "filters", "limits", "config_snapshot"}),
    Company: ("companies", ("id",), {"aliases", "operating_countries", "segments", "size", "provenance"}),
    Evidence: ("evidence", ("id",), {"contradiction_ids"}),
    Assessment: ("assessments", ("id",), {"criteria", "products", "target_roles"}),
    Contact: ("contacts", ("id",), {"employment_evidence_ids", "provenance", "channels"}),
    RunItem: ("run_items", ("campaign_id", "company_id"), {"attempts", "consumed_limits"}),
    Usage: ("usage", ("request_id",), {"reserved_tokens", "tokens"}),
}

_SCHEMA = """
CREATE TABLE campaigns (
    id TEXT PRIMARY KEY NOT NULL,
    countries TEXT NOT NULL CHECK(json_valid(countries)),
    segments TEXT NOT NULL CHECK(json_valid(segments)),
    filters TEXT NOT NULL CHECK(json_valid(filters)),
    max_companies INTEGER NOT NULL CHECK(max_companies BETWEEN 1 AND 20),
    limits TEXT NOT NULL CHECK(json_valid(limits)),
    rubric_version TEXT NOT NULL,
    config_snapshot TEXT NOT NULL CHECK(json_valid(config_snapshot)),
    status TEXT NOT NULL CHECK(status IN ('created','running','completed','partial','paused_budget','failed')),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX one_active_campaign ON campaigns((1))
    WHERE status IN ('running','paused_budget');
CREATE TABLE companies (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL, domain TEXT, entity_name TEXT,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('legal_entity','brand','subsidiary','unknown')),
    aliases TEXT CHECK(aliases IS NULL OR json_valid(aliases)),
    operating_countries TEXT CHECK(operating_countries IS NULL OR json_valid(operating_countries)),
    parent_company_id TEXT REFERENCES companies(id),
    segments TEXT CHECK(segments IS NULL OR json_valid(segments)),
    size TEXT CHECK(size IS NULL OR json_valid(size)),
    identity_status TEXT NOT NULL CHECK(identity_status IN ('pending','confirmed','contradicted')),
    identity_key TEXT,
    provenance TEXT NOT NULL CHECK(json_valid(provenance)),
    CHECK(parent_company_id IS NULL OR parent_company_id != id),
    CHECK(identity_key IS NULL OR identity_status = 'confirmed')
);
CREATE UNIQUE INDEX confirmed_identity ON companies(identity_key)
    WHERE identity_status = 'confirmed' AND identity_key IS NOT NULL;
CREATE TABLE contacts (
    id TEXT PRIMARY KEY NOT NULL,
    company_id TEXT NOT NULL REFERENCES companies(id),
    name TEXT, title TEXT,
    name_complete INTEGER CHECK(name_complete IS NULL OR name_complete IN (0,1)),
    current_employment INTEGER CHECK(current_employment IS NULL OR current_employment IN (0,1)),
    relevant_function INTEGER CHECK(relevant_function IS NULL OR relevant_function IN (0,1)),
    identity_status TEXT NOT NULL CHECK(identity_status IN ('pending','confirmed','contradicted')),
    buying_role TEXT NOT NULL CHECK(buying_role IN ('business_champion','technical_champion','economic_buyer','unknown')),
    geographic_scope TEXT,
    employment_evidence_ids TEXT NOT NULL CHECK(json_valid(employment_evidence_ids)),
    provenance TEXT NOT NULL CHECK(json_valid(provenance)),
    channels TEXT NOT NULL CHECK(json_valid(channels)),
    UNIQUE(id, company_id)
);
CREATE INDEX contacts_by_company ON contacts(company_id);
CREATE TABLE evidence (
    id TEXT PRIMARY KEY NOT NULL,
    company_id TEXT NOT NULL REFERENCES companies(id),
    contact_id TEXT,
    claim TEXT NOT NULL, url TEXT, provider TEXT, external_reference TEXT, excerpt TEXT,
    retrieved_at TEXT NOT NULL, published_at TEXT, updated_at TEXT,
    kind TEXT NOT NULL CHECK(kind IN ('observed','inference','unknown')),
    source_type TEXT NOT NULL CHECK(source_type IN ('primary','secondary','provider','manual')),
    contradiction_ids TEXT NOT NULL CHECK(json_valid(contradiction_ids)),
    FOREIGN KEY(contact_id, company_id) REFERENCES contacts(id, company_id),
    CHECK(url IS NOT NULL OR (provider IS NOT NULL AND external_reference IS NOT NULL))
);
CREATE INDEX evidence_by_company ON evidence(company_id, retrieved_at, id);
CREATE INDEX evidence_by_contact ON evidence(contact_id);
CREATE TABLE run_items (
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    company_id TEXT NOT NULL REFERENCES companies(id),
    last_assessment_id TEXT,
    stage TEXT NOT NULL CHECK(stage IN ('discovered','identity_resolved','researched','assessed','contacts_checked','completed')),
    business_status TEXT CHECK(business_status IS NULL OR business_status IN
        ('ready_preferred','ready_alternative','needs_channel_confirmation','qualified_no_contact','insufficient_evidence','low_fit','excluded')),
    attempts TEXT NOT NULL CHECK(json_valid(attempts)),
    consumed_limits TEXT NOT NULL CHECK(json_valid(consumed_limits)),
    stop_reason TEXT, error_message TEXT,
    error_stage TEXT CHECK(error_stage IS NULL OR error_stage IN ('discovered','identity_resolved','researched','assessed','contacts_checked','completed')),
    review_status TEXT NOT NULL CHECK(review_status IN ('pending','accepted','rejected')),
    review_reason TEXT, reviewed_at TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY(campaign_id, company_id),
    FOREIGN KEY(last_assessment_id, campaign_id, company_id)
        REFERENCES assessments(id, campaign_id, company_id)
);
CREATE INDEX runs_by_company ON run_items(company_id);
CREATE TABLE assessments (
    id TEXT PRIMARY KEY NOT NULL,
    campaign_id TEXT NOT NULL, company_id TEXT NOT NULL,
    criteria TEXT NOT NULL CHECK(json_valid(criteria)),
    fit_score REAL CHECK(fit_score IS NULL OR fit_score BETWEEN 0 AND 100),
    coverage REAL NOT NULL CHECK(coverage BETWEEN 0 AND 1),
    priority TEXT NOT NULL CHECK(priority IN ('high','medium','low','insufficient_evidence','excluded')),
    products TEXT NOT NULL CHECK(json_valid(products)),
    target_roles TEXT NOT NULL CHECK(json_valid(target_roles)),
    model_id TEXT, prompt_version TEXT, rubric_version TEXT NOT NULL,
    explanation TEXT NOT NULL, created_at TEXT NOT NULL, revision_of TEXT,
    UNIQUE(id, campaign_id, company_id),
    FOREIGN KEY(campaign_id, company_id) REFERENCES run_items(campaign_id, company_id),
    FOREIGN KEY(revision_of, campaign_id, company_id) REFERENCES assessments(id, campaign_id, company_id),
    CHECK(revision_of IS NULL OR revision_of != id)
);
CREATE INDEX assessments_by_run ON assessments(campaign_id, company_id, created_at, id);
CREATE TABLE usage (
    request_id TEXT PRIMARY KEY NOT NULL,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id), company_id TEXT,
    provider TEXT NOT NULL, operation TEXT NOT NULL, request_fingerprint TEXT NOT NULL,
    account_ref TEXT,
    reserved_cost_usd TEXT, reserved_credits TEXT,
    reserved_tokens TEXT CHECK(reserved_tokens IS NULL OR json_valid(reserved_tokens)),
    tokens TEXT CHECK(tokens IS NULL OR json_valid(tokens)),
    credits TEXT, estimated_cost_usd TEXT, final_cost_usd TEXT, outlay_usd TEXT,
    funding_source TEXT CHECK(funding_source IS NULL OR funding_source IN ('free_credit','prepaid','new_outlay')),
    status TEXT NOT NULL CHECK(status IN ('reserved','in_flight','succeeded','failed','uncertain','reconciled')),
    outcome TEXT CHECK(outcome IS NULL OR outcome IN ('succeeded','failed','unknown')),
    error_message TEXT, created_at TEXT NOT NULL, finished_at TEXT, reconciled_at TEXT,
    FOREIGN KEY(campaign_id, company_id) REFERENCES run_items(campaign_id, company_id)
);
CREATE INDEX usage_by_run ON usage(campaign_id, company_id);
CREATE INDEX usage_by_account ON usage(provider, account_ref, status);
CREATE INDEX usage_by_fingerprint ON usage(request_fingerprint);
"""


def _schema_signature(connection: sqlite3.Connection) -> list[tuple]:
    return [tuple(row) for row in connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    )]


class Database:
    """Abre una base nueva o compatible; nunca recrea datos existentes.

    Las transacciones son locales y breves: ningún llamador debe mantenerlas
    durante una llamada de red.
    """

    def __init__(self, path: Path):
        path = Path(path)
        is_new = not path.exists()
        if is_new:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, autocommit=True)
        self._connection.row_factory = sqlite3.Row
        self._transaction_active = False
        try:
            self._connection.execute("PRAGMA foreign_keys=ON")
            if is_new:
                self._connection.executescript(
                    "BEGIN IMMEDIATE;\n" + _SCHEMA + "\nPRAGMA user_version=1;\nCOMMIT;"
                )
            self._verify_schema()
        except BaseException:
            self._connection.close()
            raise

    def _verify_schema(self) -> None:
        if self._connection.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise sqlite3.DatabaseError("Versión de base de datos incompatible; no se modificó el esquema.")
        with sqlite3.connect(":memory:") as expected:
            expected.executescript(_SCHEMA)
            if _schema_signature(self._connection) != _schema_signature(expected):
                raise sqlite3.DatabaseError("Esquema incompleto o incompatible; no se recreó la base.")
        if self._connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("La base de datos está dañada.")
        if self._connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise sqlite3.IntegrityError("La base contiene relaciones inexistentes.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self) -> None:
        """Cierra la conexión, descartando cualquier transacción no confirmada."""
        self._connection.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Agrupa escrituras; confirma todo o revierte todo, sin anidamiento."""
        if self._transaction_active or self._connection.in_transaction:
            raise ValueError("No se permiten transacciones anidadas.")
        self._connection.execute("BEGIN IMMEDIATE")
        self._transaction_active = True
        try:
            yield
            self._connection.execute("COMMIT")
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        finally:
            self._transaction_active = False

    @contextmanager
    def _atomic(self):
        if not self._transaction_active:
            with self.transaction():
                yield
            return
        # Un fallo capturado por el llamador tampoco deja medio agregado guardado.
        self._connection.execute("SAVEPOINT aggregate_write")
        try:
            yield
            self._connection.execute("RELEASE aggregate_write")
        except BaseException:
            self._connection.execute("ROLLBACK TO aggregate_write")
            self._connection.execute("RELEASE aggregate_write")
            raise

    @staticmethod
    def _validated(model_type, value):
        if not isinstance(value, model_type):
            raise TypeError("La escritura exige el contrato de datos correspondiente.")
        return model_type.model_validate_json(value.model_dump_json())

    @staticmethod
    def _decode(model_type, row):
        if row is None:
            return None
        fields = dict(row)
        for field in _TABLES[model_type][2]:
            if fields[field] is not None:
                fields[field] = json.loads(fields[field])
        for field in ("name_complete", "current_employment", "relevant_function"):
            if field in fields and fields[field] is not None:
                if fields[field] not in (0, 1):
                    raise ValueError("La base contiene un booleano inválido.")
                fields[field] = bool(fields[field])
        return model_type.model_validate_json(json.dumps(fields, allow_nan=False))

    def _load(self, model_type, *keys):
        table, primary_keys, _ = _TABLES[model_type]
        where = " AND ".join(f"{field}=?" for field in primary_keys)
        row = self._connection.execute(
            f"SELECT * FROM {table} WHERE {where}", tuple(str(key) for key in keys)
        ).fetchone()
        return self._decode(model_type, row)

    def _get(self, model_type, *keys):
        model = self._load(model_type, *keys)
        if model is not None:
            self._check_references(model)
        return model

    def _list(self, model_type, *, filters=(), order="id"):
        table = _TABLES[model_type][0]
        where = " AND ".join(f"{field}=?" for field, value in filters)
        rows = self._connection.execute(
            f"SELECT * FROM {table}" + (f" WHERE {where}" if where else "") + f" ORDER BY {order}",
            tuple(str(value) for field, value in filters),
        ).fetchall()
        models = [self._decode(model_type, row) for row in rows]
        for model in models:
            self._check_references(model)
        return models

    def _store(self, model, *, immutable=False):
        model_type = type(model)
        table, primary_keys, json_fields = _TABLES[model_type]
        old = self._load(model_type, *(getattr(model, field) for field in primary_keys))
        if old is not None and immutable:
            if old != model:
                raise ValueError("El identificador ya corresponde a un registro inmutable diferente.")
            return
        values = model.model_dump(mode="json")
        for field in json_fields:
            if values[field] is not None:
                values[field] = json.dumps(values[field], ensure_ascii=False, allow_nan=False)
        columns = list(values)
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{field}=excluded.{field}" for field in columns if field not in primary_keys)
        self._connection.execute(
            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT({','.join(primary_keys)}) DO UPDATE SET {updates}",
            tuple(values.values()),
        )

    def _evidence_refs(self, ids, company_id, *, contact_id=None):
        for evidence_id in ids:
            row = self._connection.execute(
                "SELECT company_id, contact_id FROM evidence WHERE id=?", (str(evidence_id),)
            ).fetchone()
            if row is None or row["company_id"] != str(company_id):
                raise ValueError("Referencia de evidencia inexistente o de otra empresa.")
            if contact_id is not None and row["contact_id"] not in (None, str(contact_id)):
                raise ValueError("La evidencia pertenece a otra persona.")

    def _check_references(self, model):
        if isinstance(model, Company):
            for ids in model.provenance.values():
                self._evidence_refs(ids, model.id)
            if model.size is not None:
                self._evidence_refs(model.size.evidence_ids, model.id)
            parent_id = model.parent_company_id
            visited = {str(model.id)}
            while parent_id is not None:
                if str(parent_id) in visited:
                    raise ValueError("La relación de matriz contiene un ciclo.")
                visited.add(str(parent_id))
                row = self._connection.execute(
                    "SELECT parent_company_id FROM companies WHERE id=?", (str(parent_id),)
                ).fetchone()
                if row is None:
                    raise sqlite3.IntegrityError("La empresa matriz no existe.")
                parent_id = row[0]
        elif isinstance(model, Contact):
            self._evidence_refs(model.employment_evidence_ids, model.company_id, contact_id=model.id)
            for ids in model.provenance.values():
                self._evidence_refs(ids, model.company_id, contact_id=model.id)
            for channel in model.channels:
                if channel.contact_id != model.id:
                    raise ValueError("El canal pertenece a otra persona.")
                self._evidence_refs(channel.evidence_ids, model.company_id, contact_id=model.id)
                self._evidence_refs(channel.published_evidence_ids, model.company_id, contact_id=model.id)
                for evidence_id in channel.published_evidence_ids:
                    row = self._connection.execute(
                        "SELECT source_type, kind FROM evidence WHERE id=?", (str(evidence_id),)
                    ).fetchone()
                    if tuple(row) != ("primary", "observed"):
                        raise ValueError("La publicación profesional necesita una fuente primaria observada.")
                if channel.normalized_status == "verified":
                    provider_ids = self._connection.execute(
                        "SELECT id FROM evidence WHERE company_id=? AND source_type='provider' AND kind='observed'",
                        (str(model.company_id),),
                    ).fetchall()
                    if not set(channel.evidence_ids).intersection(UUID(row[0]) for row in provider_ids):
                        raise ValueError("La verificación necesita evidencia del proveedor.")
                if channel.manual_confirmed_at is not None:
                    manual = self._connection.execute(
                        "SELECT id FROM evidence WHERE company_id=? AND source_type='manual'",
                        (str(model.company_id),),
                    ).fetchall()
                    if not set(channel.evidence_ids).intersection(UUID(row[0]) for row in manual):
                        raise ValueError("La confirmación manual necesita evidencia de revisión.")
        elif isinstance(model, Evidence):
            self._evidence_refs(model.contradiction_ids, model.company_id, contact_id=model.contact_id)
        elif isinstance(model, Assessment):
            for criterion in model.criteria.values():
                self._evidence_refs(criterion.evidence_ids, model.company_id)
            campaign = self._load(Campaign, model.campaign_id)
            if campaign is None:
                raise sqlite3.IntegrityError("La campaña no existe.")
            if model.rubric_version != campaign.rubric_version:
                raise ValueError("La evaluación usa otra versión de rúbrica.")
            product_ids = {product.id for product in campaign.config_snapshot.catalog.products}
            if not set(model.products).issubset(product_ids):
                raise ValueError("La evaluación referencia productos fuera del catálogo de campaña.")
            roles = {role for profile in campaign.config_snapshot.profiles for role in profile.target_roles}
            if not set(model.target_roles).issubset(roles):
                raise ValueError("La evaluación referencia cargos fuera de los perfiles de campaña.")

    def save_campaign(self, campaign: Campaign) -> Campaign:
        campaign = self._validated(Campaign, campaign)
        with self._atomic():
            old = self._load(Campaign, campaign.id)
            if old is not None:
                for field in ("created_at", "rubric_version", "config_snapshot"):
                    if getattr(old, field) != getattr(campaign, field):
                        raise ValueError("La configuración original de campaña es inmutable.")
            count = self._connection.execute(
                "SELECT count(*) FROM run_items WHERE campaign_id=?", (str(campaign.id),)
            ).fetchone()[0]
            if count > campaign.max_companies:
                raise ValueError("El máximo de campaña no puede ser menor que las empresas guardadas.")
            for existing in self.list_campaigns():
                for version, rubric in campaign.config_snapshot.rubrics.items():
                    previous = existing.config_snapshot.rubrics.get(version)
                    if previous is not None and previous != rubric:
                        raise ValueError("Cambiar una rúbrica requiere una versión nueva.")
            self._store(campaign)
        return self.get_campaign(campaign.id)

    def get_campaign(self, id: UUID) -> Campaign | None:
        return self._get(Campaign, id)

    def list_campaigns(self) -> list[Campaign]:
        return self._list(Campaign, order="created_at,id")

    def get_active_campaign(self) -> Campaign | None:
        row = self._connection.execute(
            "SELECT * FROM campaigns WHERE status IN ('running','paused_budget')"
        ).fetchone()
        return self._decode(Campaign, row)

    def save_company(self, company: Company, *, evidence: Sequence[Evidence] = ()) -> Company:
        company = self._validated(Company, company)
        evidence = [self._validated(Evidence, item) for item in evidence]
        if any(item.company_id != company.id or item.contact_id is not None for item in evidence):
            raise ValueError("El agregado de empresa contiene evidencia ajena o de contacto.")
        with self._atomic():
            self._store(company)
            for item in evidence:
                self._store(item, immutable=True)
            for item in evidence:
                self._check_references(item)
            self._check_references(company)
        return self.get_company(company.id)

    def get_company(self, id: UUID) -> Company | None:
        return self._get(Company, id)

    def save_evidence(self, evidence: Evidence) -> Evidence:
        evidence = self._validated(Evidence, evidence)
        with self._atomic():
            self._store(evidence, immutable=True)
            self._check_references(evidence)
        return self._get(Evidence, evidence.id)

    def list_evidence(self, company_id: UUID, *, contact_id: UUID | None = None) -> list[Evidence]:
        filters = [("company_id", company_id)]
        if contact_id is not None:
            filters.append(("contact_id", contact_id))
        return self._list(Evidence, filters=filters, order="retrieved_at,id")

    def save_assessment(self, assessment: Assessment) -> Assessment:
        assessment = self._validated(Assessment, assessment)
        with self._atomic():
            self._store(assessment, immutable=True)
            self._check_references(assessment)
        return self.get_assessment(assessment.id)

    def get_assessment(self, id: UUID) -> Assessment | None:
        return self._get(Assessment, id)

    def list_assessments(self, campaign_id: UUID, company_id: UUID) -> list[Assessment]:
        return self._list(Assessment, filters=[("campaign_id", campaign_id), ("company_id", company_id)], order="created_at,id")

    def save_contact(self, contact: Contact, *, evidence: Sequence[Evidence] = ()) -> Contact:
        contact = self._validated(Contact, contact)
        evidence = [self._validated(Evidence, item) for item in evidence]
        if any(item.company_id != contact.company_id or item.contact_id not in (None, contact.id) for item in evidence):
            raise ValueError("El agregado de contacto contiene evidencia ajena.")
        with self._atomic():
            old = self._load(Contact, contact.id)
            if old is not None:
                if old.company_id != contact.company_id:
                    raise ValueError("Un contacto no se reasigna a otra entidad.")
                old_invalid = {(channel.type, channel.value) for channel in old.channels if channel.normalized_status == "invalid"}
                if not old_invalid.issubset((channel.type, channel.value) for channel in contact.channels):
                    raise ValueError("No se puede retirar un canal con verificación negativa pendiente.")
                for channel in contact.channels:
                    if (channel.type, channel.value) in old_invalid and channel.normalized_status not in ("invalid", "verified"):
                        raise ValueError("La confirmación manual no elimina una verificación negativa.")
                    if (channel.type, channel.value) in old_invalid and channel.normalized_status == "verified":
                        previous = next(item for item in old.channels if (item.type, item.value) == (channel.type, channel.value))
                        if channel.verified_at <= (previous.verified_at or previous.retrieved_at):
                            raise ValueError("Resolver una verificación negativa requiere una verificación posterior.")
                        if set(channel.evidence_ids).issubset(previous.evidence_ids):
                            raise ValueError("Resolver una verificación negativa requiere evidencia nueva.")
            self._store(contact)
            for item in evidence:
                self._store(item, immutable=True)
            for item in evidence:
                self._check_references(item)
            self._check_references(contact)
            if old is not None:
                for previous in old.channels:
                    if previous.normalized_status != "invalid":
                        continue
                    channel = next(item for item in contact.channels if (item.type, item.value) == (previous.type, previous.value))
                    if channel.normalized_status == "verified":
                        new_facts = [self._load(Evidence, id) for id in set(channel.evidence_ids) - set(previous.evidence_ids)]
                        if not any(
                            fact.source_type == "provider" and fact.kind == "observed"
                            and fact.retrieved_at > (previous.verified_at or previous.retrieved_at)
                            for fact in new_facts
                        ):
                            raise ValueError("Resolver una verificación negativa requiere una observación posterior del proveedor.")
        return self.get_contact(contact.id)

    def get_contact(self, id: UUID) -> Contact | None:
        return self._get(Contact, id)

    def list_contacts(self, company_id: UUID) -> list[Contact]:
        return self._list(Contact, filters=[("company_id", company_id)])

    def save_run_item(self, run_item: RunItem) -> RunItem:
        run_item = self._validated(RunItem, run_item)
        with self._atomic():
            campaign = self._load(Campaign, run_item.campaign_id)
            if campaign is None:
                raise sqlite3.IntegrityError("La campaña no existe.")
            old = self._load(RunItem, run_item.campaign_id, run_item.company_id)
            if old is None:
                count = self._connection.execute(
                    "SELECT count(*) FROM run_items WHERE campaign_id=?", (str(run_item.campaign_id),)
                ).fetchone()[0]
                if count >= campaign.max_companies:
                    raise ValueError("La campaña alcanzó el límite de empresas.")
            else:
                stages = list(RunStage)
                if stages.index(run_item.stage) < stages.index(old.stage):
                    raise ValueError("No se puede retroceder el último checkpoint confirmado.")
                if any(run_item.attempts.get(key, 0) < value for key, value in old.attempts.items()):
                    raise ValueError("No se pueden borrar intentos registrados.")
                if any(getattr(run_item.consumed_limits, key) < value for key, value in old.consumed_limits.model_dump().items()):
                    raise ValueError("No se pueden reducir límites ya consumidos.")
                if old.last_assessment_id is not None and run_item.last_assessment_id is None:
                    raise ValueError("No se puede borrar la evaluación seleccionada.")
                if old.business_status is not None and run_item.business_status is None:
                    raise ValueError("No se puede borrar el resultado comercial registrado.")
            self._store(run_item)
        return self.get_run_item(run_item.campaign_id, run_item.company_id)

    def get_run_item(self, campaign_id: UUID, company_id: UUID) -> RunItem | None:
        return self._get(RunItem, campaign_id, company_id)

    def list_run_items(self, campaign_id: UUID) -> list[RunItem]:
        return self._list(RunItem, filters=[("campaign_id", campaign_id)], order="company_id")

    def save_usage(self, usage: Usage) -> Usage:
        usage = self._validated(Usage, usage)
        with self._atomic():
            old = self._load(Usage, usage.request_id)
            if old is not None:
                for field in ("campaign_id", "company_id", "provider", "operation", "request_fingerprint", "created_at"):
                    if getattr(old, field) != getattr(usage, field):
                        raise ValueError("La identidad de la solicitud es inmutable.")
                for field in ("account_ref", "reserved_cost_usd", "reserved_credits", "credits", "final_cost_usd", "outlay_usd", "error_message"):
                    value = getattr(old, field)
                    if value is not None and value != getattr(usage, field):
                        raise ValueError("No se puede borrar o sustituir consumo, reserva o fallo registrado.")
                for field in ("estimated_cost_usd", "funding_source", "outcome", "finished_at", "reconciled_at"):
                    if getattr(old, field) is not None and getattr(usage, field) is None:
                        raise ValueError("No se puede borrar información de consumo ya registrada.")
                for field in ("reserved_tokens", "tokens"):
                    previous = getattr(old, field)
                    current = getattr(usage, field)
                    if previous is not None:
                        if current is None or any(
                            value is not None and value != getattr(current, key)
                            for key, value in previous.model_dump().items()
                        ):
                            raise ValueError("No se puede borrar o sustituir uso de tokens registrado.")
            self._store(usage)
        return self.get_usage(usage.request_id)

    def get_usage(self, request_id: UUID) -> Usage | None:
        return self._get(Usage, request_id)

    def list_usage(self, *, campaign_id: UUID | None = None, company_id: UUID | None = None, provider: str | None = None) -> list[Usage]:
        filters = [(key, value) for key, value in (("campaign_id", campaign_id), ("company_id", company_id), ("provider", provider)) if value is not None]
        return self._list(Usage, filters=filters, order="created_at,request_id")
