"""Verifica el arranque Django local sin claves, proveedores ni datos comerciales."""

import os
from pathlib import Path
import re
import socket
import subprocess
import sys

import django
import pytest
from django.conf import settings
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.core.management.commands.runserver import Command as DjangoRunserver
from django.test import Client, override_settings
from django.urls import reverse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_initial_screen_without_external_network(monkeypatch, tmp_path):
    """La pantalla funciona y el bloqueo impide conexiones externas."""
    def reject_connection(*args, **kwargs):
        raise AssertionError("La interfaz debe ejecutarse sin conexiones externas.")

    monkeypatch.setattr(socket.socket, "connect", reject_connection)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_connection)
    monkeypatch.setattr(socket, "getaddrinfo", reject_connection)
    for key in ("TAVILY_API_KEY", "ANTHROPIC_API_KEY", "HUNTER_API_KEY", "APOLLO_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    with socket.socket() as connection, pytest.raises(AssertionError):
        connection.connect(("203.0.113.1", 443))

    database_path = tmp_path / "synthetic.sqlite3"
    with override_settings(PROSPECTING_DB_PATH=database_path, PROSPECTING_ACCESS_PATH=tmp_path / "access.json",
                           PROSPECTING_EXCLUSIONS_PATH=tmp_path / "exclusions.json"):
        client = Client(SERVER_NAME="localhost")
        response = client.get(reverse("webapp:campaigns"))
        assert response.status_code == 200
        assert "Veryfi Prospecting" in response.content.decode()
        assert client.get(reverse("webapp:new_campaign")).status_code == 200
    assert not database_path.exists()


def test_secrets_and_local_data_stay_out_of_git():
    """Las claves y los datos reales solo viven en `.env` y `data/`, ignorados por Git (§15)."""
    ignored = set((PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    assert {".env", ".env.*", "!.env.example", "/data/", ".venv/"} <= ignored
    example = [line for line in (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert example and all(re.fullmatch(r"[A-Z][A-Z0-9_]*=", line) for line in example)


def test_external_content_is_never_marked_safe():
    """El autoescape de Django protege el contenido externo; ninguna plantilla ni vista lo desactiva (§15)."""
    sources = [*(PROJECT_ROOT / "templates").rglob("*.html"), *(PROJECT_ROOT / "core").rglob("*.py")]
    assert sources
    unsafe = re.compile(r"\|\s*safe(?:seq)?\b|mark_safe|SafeString|autoescape\s+off")
    assert [path.name for path in sources if unsafe.search(path.read_text(encoding="utf-8"))] == []


def test_django_configuration_has_no_orm_or_authentication_and_is_local():
    """El arranque documentado y el acceso web quedan limitados a loopback."""
    assert all(database["ENGINE"] == "django.db.backends.dummy" for database in settings.DATABASES.values())
    assert not any(app in settings.INSTALLED_APPS for app in ("django.contrib.auth", "django.contrib.admin"))
    assert settings.ALLOWED_HOSTS == ["127.0.0.1", "localhost", "[::1]"]
    assert settings.DEBUG is False
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Strict"
    assert settings.CSRF_COOKIE_SAMESITE == "Strict"
    assert "runserver 127.0.0.1:8000 --noreload" in (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    client = Client(SERVER_NAME="localhost")
    assert client.get("/", REMOTE_ADDR="203.0.113.1").status_code == 403
    assert client.get("/", HTTP_HOST="example.com").status_code == 400


@pytest.mark.parametrize("asset, marker", [
    ("css/app.css", b"--navy"),
    ("js/app.js", b"'use strict'"),
    ("img/veryfi-logo.svg", b"<svg"),
])
def test_root_templates_and_static_assets_load_without_debug_or_database(tmp_path, asset, marker):
    """La nueva ubicación carga plantillas, etiquetas y recursos sin crear datos."""
    database_path = tmp_path / "synthetic.sqlite3"
    with override_settings(DEBUG=False, PROSPECTING_DB_PATH=database_path,
                           PROSPECTING_ACCESS_PATH=tmp_path / "access.json",
                           PROSPECTING_EXCLUSIONS_PATH=tmp_path / "exclusions.json"):
        client = Client(SERVER_NAME="localhost")
        page = client.get(reverse("webapp:campaigns"))
        assert page.status_code == 200
        assert f"/static/{asset}" in page.content.decode()
        response = client.get(f"/static/{asset}")
        try:
            assert response.status_code == 200
            assert marker in b"".join(response.streaming_content)
        finally:
            response.close()
    assert not database_path.exists()


def test_prospecting_import_does_not_load_web_frameworks():
    """Importar el negocio no exige ni carga la interfaz en un proceso nuevo."""
    subprocess.run(
        [sys.executable, "-c", "import sys; import prospecting; assert 'streamlit' not in sys.modules; "
         "assert 'django' not in sys.modules"],
        cwd=PROJECT_ROOT, check=True, timeout=10,
    )


def test_runserver_defaults_to_loopback_and_disables_reloader(monkeypatch):
    calls = []
    monkeypatch.setattr(DjangoRunserver, "handle", lambda self, *args, **options: calls.append(options))
    assert get_commands()["runserver"] == "core"
    call_command("runserver")
    assert len(calls) == 1
    assert calls[0]["addrport"] == "127.0.0.1:8000" and calls[0]["use_reloader"] is False


@pytest.mark.parametrize("address", ["0.0.0.0:8000", "192.168.1.2:8000", "[::]:8000"])
def test_runserver_rejects_nonlocal_bindings_without_launching(monkeypatch, address):
    def forbidden(*args, **kwargs):
        pytest.fail("No debe arrancar un servidor que acepte acceso remoto.")

    monkeypatch.setattr(DjangoRunserver, "handle", forbidden)
    with pytest.raises(CommandError, match="127.0.0.1"):
        call_command("runserver", address)
