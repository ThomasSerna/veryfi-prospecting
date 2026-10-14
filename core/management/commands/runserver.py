"""Un único proceso local; una recarga interrumpiría la investigación en curso."""

import re

from django.core.management.base import CommandError
from django.core.management.commands.runserver import Command as DjangoRunserver


class Command(DjangoRunserver):
    def handle(self, *args, **options):
        address = options.get("addrport") or "127.0.0.1:8000"
        if not re.fullmatch(r"(?:127\.0\.0\.1:)?[0-9]+", address) or options.get("use_ipv6"):
            raise CommandError("Esta herramienta debe ejecutarse en 127.0.0.1.")
        if not options.get("use_threading", True):
            raise CommandError("El progreso requiere el servidor local con hilos habilitados.")
        options["addrport"] = address
        options["use_reloader"] = False
        return super().handle(*args, **options)

    def check_migrations(self):
        """No hay base ni migraciones Django: prospecting administra su SQLite."""
