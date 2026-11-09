"""Conciliación local atribuida; una cota de reserva nunca se convierte en consumo real."""

import hashlib
import json
import os
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field

from prospecting.budget import Budget, Confirmation
from prospecting.db import Database
from prospecting.models import Contract, Text, VeryfiConfig, utc_now

from .contracts import BenchmarkCapture, manifest_digest
from .pipeline import PROJECT_ROOT, experiment_lock, private_path, read_json, write_json


class ReceiptItem(Contract):
    request_id: UUID
    confirmation: Confirmation


class ReceiptBundle(Contract):
    schema_version: Literal["snov_benchmark_receipts_v1"] = "snov_benchmark_receipts_v1"
    benchmark_id: UUID
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    origin: Literal["synthetic", "real"]
    responsible: Text
    receipts: list[ReceiptItem] = Field(min_length=1)


def apply_receipts(manifest, captures, receipts_path, capture_path):
    """Verifica el comprobante completo de cada proveedor antes de aplicar una transacción."""
    output = Path(capture_path).resolve().parent
    if manifest.origin == "real":
        for path in (receipts_path, capture_path):
            private_path(path)
    bundle = ReceiptBundle.model_validate(read_json(receipts_path))
    if (bundle.benchmark_id != manifest.benchmark_id or bundle.manifest_sha256 != manifest_digest(manifest)
            or bundle.origin != manifest.origin):
        raise ValueError("Los comprobantes pertenecen a otro experimento u origen.")
    identifiers = [item.request_id for item in bundle.receipts]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("El comprobante repite solicitudes.")
    captures = [BenchmarkCapture.model_validate(item.model_dump()) for item in captures]
    ledger_path = output / "ledger.sqlite3"
    if not ledger_path.is_file() or ledger_path.resolve().parent != output:
        raise ValueError("Falta el ledger experimental local; no se crea ni se abren enlaces externos.")
    header = ledger_path.read_bytes()[:100]
    if header[:16] != b"SQLite format 3\x00" or int.from_bytes(header[60:64], "big") != 2:
        raise ValueError("El formato del ledger no está comprobado; no se migra.")
    with experiment_lock(output), Database(ledger_path) as db:
        state = read_json(output / "state.json")
        def stable(values):
            result = []
            for capture in values:
                requests = [{key: value for key, value in record.items()
                    if key not in {"credits", "final_cost_usd", "reconciled_at", "outcome"}} for record in capture["requests"]]
                result.append(capture | {"requests": requests})
            return result
        if (state.get("manifest_sha256") != bundle.manifest_sha256
                or stable(state.get("captures", [])) != stable([item.model_dump(mode="json") for item in captures])):
            raise ValueError("La captura debe coincidir con el checkpoint del expediente.")
        captures = [BenchmarkCapture.model_validate(item) for item in state["captures"]]
        by_request = {}
        for capture in captures:
            for record in capture.requests:
                identifier = UUID(record["request_id"])
                if identifier in by_request:
                    raise ValueError("Las capturas repiten una solicitud.")
                by_request[identifier] = capture, record
        rows = {row.request_id: row for row in db.list_usage(campaign_id=manifest.benchmark_id)}
        groups = {}
        for item in bundle.receipts:
            row = rows.get(item.request_id)
            if row is None or item.request_id not in by_request:
                raise ValueError("El comprobante incluye una solicitud ajena.")
            capture, record = by_request[item.request_id]
            if capture.provider != row.provider or capture.company_id != row.company_id or record["operation"] != row.operation:
                raise ValueError("El comprobante contradice la procedencia de la captura.")
            confirmation = item.confirmation
            if (confirmation.outcome == "unknown" or not (row.finished_at or row.created_at) <= confirmation.observed_at <= utc_now()):
                raise ValueError("La conciliación requiere resultado y fecha comprobados posteriores a la solicitud.")
            groups.setdefault((row.provider, row.account_ref), []).append((item.request_id, confirmation))
        config = VeryfiConfig.model_validate(read_json(PROJECT_ROOT / "config" / "veryfi.json"))
        budget = Budget(db, config.defaults.budget, [])
        updates = []
        for (provider, account), items in groups.items():
            account_rows = [row for row in rows.values() if (row.provider, row.account_ref) == (provider, account)]
            if {identifier for identifier, _ in items} != {row.request_id for row in account_rows}:
                raise ValueError("El comprobante debe cubrir todas las solicitudes del proveedor en este expediente.")
            updates.extend(budget.reconcile_many(items, provider=provider, account_ref=account,
                since=min(row.created_at for row in account_rows), until=max(row.created_at for row in account_rows), apply=False))
        payload = bundle.model_dump(mode="json")
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        archive = output / "receipts"
        archive.mkdir(exist_ok=True)
        archive_path = archive / f"{digest}.json"
        if not archive_path.exists():
            with archive_path.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
        elif read_json(archive_path) != payload:
            raise ValueError("El archivo de comprobante no coincide con su huella.")
        with db.transaction():
            for row in updates:
                db.save_usage(row)
        for row in updates:
            _, record = by_request[row.request_id]
            record.update(credits=str(row.credits), final_cost_usd=str(row.final_cost_usd),
                outcome=row.outcome, reconciled_at=row.reconciled_at.isoformat())
        state["captures"] = [item.model_dump(mode="json") for item in captures]
        write_json(output / "state.json", state)
        write_json(capture_path, state["captures"])
    return captures
