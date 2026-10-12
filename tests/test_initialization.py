"""Verifica el arranque local sin claves, proveedores ni datos comerciales."""

from pathlib import Path
import socket
import subprocess
import sys
import tomllib

import pytest
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_initial_screen_without_external_network(monkeypatch, tmp_path):
    """La pantalla funciona y el bloqueo impide conexiones externas."""
    original_connect = socket.socket.connect

    def connect_locally(connection, address):
        # asyncio necesita sockets internos de loopback en Windows.
        if address[0] not in ("127.0.0.1", "::1"):
            raise AssertionError("T00 debe ejecutarse sin conexiones externas.")
        return original_connect(connection, address)

    def reject_connection(*args, **kwargs):
        raise AssertionError("T00 debe ejecutarse sin conexiones externas.")

    monkeypatch.setattr(socket.socket, "connect", connect_locally)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_connection)
    monkeypatch.setattr(socket, "getaddrinfo", reject_connection)

    # Dirección sintética de documentación; se rechaza antes de abrir conexión.
    with socket.socket() as connection, pytest.raises(AssertionError):
        connection.connect(("203.0.113.1", 443))

    import app as screen

    monkeypatch.setattr(screen, "DB_PATH", tmp_path / "synthetic.sqlite3")
    monkeypatch.setattr(screen, "ACCESS_PATH", tmp_path / "access.json")
    monkeypatch.setattr(screen, "EXCLUSIONS_PATH", tmp_path / "exclusions.json")
    app = AppTest.from_string("import app; app.main()").run()

    assert not app.exception
    assert app.title[0].value == "Veryfi Prospecting"
    assert app.subheader[0].value == "Preparar una campaña"
    assert not screen.DB_PATH.exists()


def test_streamlit_is_local_without_telemetry():
    """La configuración versionada limita el servidor al equipo local."""
    with (PROJECT_ROOT / ".streamlit" / "config.toml").open("rb") as config_file:
        config = tomllib.load(config_file)

    assert config["server"]["address"] == "127.0.0.1"
    assert config["server"]["headless"] is True
    assert config["browser"]["gatherUsageStats"] is False
    assert config["client"]["disableDataExport"] is True


def test_prospecting_import_does_not_load_streamlit():
    """Importar el paquete no exige ni carga la interfaz en un proceso nuevo."""
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import prospecting; assert 'streamlit' not in sys.modules",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        timeout=10,
    )
