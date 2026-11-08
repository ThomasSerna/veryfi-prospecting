"""Concilia el consumo de Apollo con un comprobante del panel; no llama a proveedores ni crea la base."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from prospecting.pipeline import load_provider_access, reconcile_usage


class Command(BaseCommand):
    help = "Concilia solicitudes de Apollo con un comprobante apollo_reconciliation_v1 de data/conciliaciones/."

    def add_arguments(self, parser):
        parser.add_argument("receipt", type=Path, help="Ruta del comprobante JSON.")
        parser.add_argument("--dry-run", action="store_true", help="Comprueba el comprobante sin escribir en la base.")

    def handle(self, *args, **options):
        try:
            access = load_provider_access(settings.PROSPECTING_ACCESS_PATH)
            summary = reconcile_usage(settings.PROSPECTING_DB_PATH, options["receipt"], access=access,
                                      apply=not options["dry_run"])
        except ValueError as error:
            raise CommandError(str(error)) from None
        mode = "Conciliación aplicada" if summary.applied else "Prueba sin escribir"
        lines = [
            f"{mode} para la cuenta {summary.account_ref}.",
            f"Salto del panel: {summary.panel_delta} créditos; ajenos al ledger: {summary.external_credits}.",
            f"Solicitudes conciliadas ahora: {summary.reconciled_now}; ya conciliadas: {summary.already_reconciled}.",
            *(f"{operation}: {credits} créditos." for operation, credits in sorted(summary.credits_by_operation.items())),
            f"Créditos disponibles: {'desconocido' if summary.available_credits is None else summary.available_credits}; "
            f"pendientes: {summary.pending_credits}.",
        ]
        if summary.reservation_overrun:
            lines.append("Aviso: hay consumo conciliado mayor que su reserva; revísalo antes de autorizar más gasto.")
        self.stdout.write("\n".join(lines))
