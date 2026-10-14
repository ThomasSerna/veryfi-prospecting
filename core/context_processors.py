"""Contexto común de las plantillas, incluidas las páginas de error."""

from django.conf import settings


def demo_mode(request):
    """El aviso de datos sintéticos solo aparece cuando lo activa el lanzador de demostración."""
    return {"demo_mode": settings.PROSPECTING_DEMO}
