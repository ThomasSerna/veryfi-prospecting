"""Informe agregado de la corroboración dirigida del empleo (T24); solo lee la base, sin llamar a proveedores."""

from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from prospecting.pipeline import employment_corroboration_summary


def _value(value, unit=""):
    return "sin definir" if value is None else f"{value}{unit}"


class Command(BaseCommand):
    help = "Resume cuántas afirmaciones de Apollo pasaron a evidencia corporativa y su costo, sin datos personales."

    def add_arguments(self, parser):
        parser.add_argument("--campaign", type=UUID, required=True, help="Identificador de la campaña.")

    def handle(self, *args, **options):
        try:
            summary = employment_corroboration_summary(settings.PROSPECTING_DB_PATH, options["campaign"])
        except ValueError as error:
            raise CommandError(str(error)) from None
        lines = [
            f"Campaña {summary.campaign_id}; política: {summary.policy_version or 'sin corroboración (instantánea anterior)'}.",
            f"Personas buscadas: {summary.people_searched}; corroboradas: {summary.people_corroborated}; "
            f"pendientes por cupo: {summary.people_pending_limit}; rechazos de Haiku: {summary.people_rejected}.",
            f"Tavily: {summary.tavily_requests} solicitudes, {summary.tavily_credits_reserved} créditos reservados, "
            f"{summary.tavily_credits_observed} observados; sin observar: {summary.tavily_unobserved}.",
            f"Haiku: {summary.haiku_requests} solicitudes, USD {summary.haiku_reserved_usd} reservados, "
            f"USD {summary.haiku_cost_usd} estimados o conciliados; sin estimar: {summary.haiku_unestimated}.",
            f"Por empleo verificado: {_value(summary.credits_per_corroboration, ' créditos de Tavily')}; "
            f"Haiku {_value(summary.haiku_usd_per_corroboration, ' USD')}.",
        ]
        self.stdout.write("\n".join(lines))
