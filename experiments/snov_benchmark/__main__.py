"""CLI experimental: ninguna operación realiza red salvo run --live autorizado."""

import argparse
import json
from pathlib import Path
import sys
import sqlite3

from pydantic import ValidationError
from prospecting.budget import BudgetError

from .contracts import BenchmarkCapture, BenchmarkManifest
from .pipeline import load_inputs, preflight, private_path, read_json, run_benchmark, write_json
from .report import report_capture


def main(argv=None):
    parser = argparse.ArgumentParser(description="Benchmark aislado Snov.io vs Apollo; fixtures sin red.")
    commands = parser.add_subparsers(dest="command", required=True)
    fixtures = commands.add_parser("fixtures", help="Ejecuta únicamente datos y transporte sintéticos.")
    fixtures.add_argument("--output", required=True)
    for name in ("preflight", "run"):
        command = commands.add_parser(name)
        for item in ("manifest", "access", "approvals"):
            command.add_argument("--" + item, required=True)
        if name == "run":
            command.add_argument("--live", action="store_true", required=True)
            command.add_argument("--output", required=True)
    report = commands.add_parser("report", help="Calcula métricas de capturas guardadas, sin red.")
    report.add_argument("--manifest", required=True)
    report.add_argument("--capture", required=True)
    report.add_argument("--output", required=True)
    report.add_argument("--receipts", help="Comprobantes atribuidos para conciliar el ledger local, sin red.")
    args = parser.parse_args(argv)
    try:
        if args.command == "fixtures":
            from .fixtures import build_fixture_inputs, FixtureTransport
            manifest, access, approval = build_fixture_inputs()
            captures = run_benchmark(manifest, access, approval, args.output, transport=FixtureTransport())
            report_data = report_capture(manifest, captures)
            write_json(Path(args.output) / "manifest.json", manifest.model_dump(mode="json"))
            write_json(Path(args.output) / "report.json", report_data)
            print("Fixtures sintéticos ejecutados sin red; informe guardado.")
            return 0 if all(item.status == "completed" for item in captures) else 2
        if args.command == "report":
            target = Path(args.output).resolve()
            if target.exists():
                raise ValueError("El informe requiere un archivo nuevo; no se sobrescriben entradas ni resultados.")
            manifest = BenchmarkManifest.model_validate(read_json(args.manifest))
            if manifest.origin == "real":
                for path in (args.manifest, args.capture, args.output):
                    private_path(path)
            captures = [BenchmarkCapture.model_validate(item) for item in read_json(args.capture)]
            report_capture(manifest, captures)
            if args.receipts:
                from .receipts import apply_receipts
                captures = apply_receipts(manifest, captures, args.receipts, args.capture)
            with target.open("x", encoding="utf-8") as stream:
                json.dump(report_capture(manifest, captures), stream, ensure_ascii=False, indent=2, allow_nan=False)
            print("Informe y conciliación guardados; no se realizaron llamadas." if args.receipts
                  else "Informe guardado; no se realizaron llamadas.")
            return 0
        manifest, access, approval = load_inputs(args.manifest, args.access, args.approvals)
        blockers = preflight(manifest, access, approval, live=True)
        if args.command == "preflight":
            print(json.dumps({"status": "blocked" if blockers else "ready", "blockers": blockers}, ensure_ascii=False))
            return 2 if blockers else 0
        captures = run_benchmark(manifest, access, approval, args.output, live=True)
        write_json(Path(args.output) / "report.json", report_capture(manifest, captures))
        print("Capturas e informe guardados; revisar consumo pendiente de conciliación.")
        return 0 if all(item.status == "completed" for item in captures) else 2
    except ValidationError:
        print("Entrada inválida: revisar contratos y campos requeridos, sin mostrar datos privados.", file=sys.stderr)
    except (OSError, ValueError, BudgetError, sqlite3.Error) as error:
        # Las entradas y respuestas pueden contener datos personales; no imprimir su contenido.
        print(str(error) if isinstance(error, (ValueError, BudgetError)) and not isinstance(error, json.JSONDecodeError)
              else "No se pudo leer o guardar el expediente; revisar rutas y formato JSON.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
