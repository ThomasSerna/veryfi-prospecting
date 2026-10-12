"""Dirección de las dependencias y capacidades prohibidas del paquete (§13, §15)."""

import ast
import importlib
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = PROJECT_ROOT / "prospecting"

# Importaciones internas permitidas por módulo. Un módulo nuevo debe declararse aquí.
ALLOWED = {
    "prospecting": set(),
    "prospecting.models": set(),
    "prospecting.db": {"prospecting.models"},
    "prospecting.budget": {"prospecting.db", "prospecting.models"},
    "prospecting.providers": {"prospecting.budget", "prospecting.models"},
    "prospecting.discovery": {"prospecting.models", "prospecting.providers"},
    "prospecting.qualification": {"prospecting.discovery", "prospecting.models"},
    "prospecting.contacts": {
        "prospecting.discovery", "prospecting.models", "prospecting.providers", "prospecting.qualification",
    },
    "prospecting.pipeline": {
        "prospecting.pipeline.contacts", "prospecting.pipeline.discovery", "prospecting.pipeline.qualification",
        "prospecting.pipeline.research",
    },
    "prospecting.pipeline.calls": {"prospecting.budget", "prospecting.models", "prospecting.providers"},
    "prospecting.pipeline.discovery": {
        "prospecting.budget", "prospecting.db", "prospecting.discovery", "prospecting.models",
        "prospecting.pipeline.calls", "prospecting.providers",
    },
    "prospecting.pipeline.research": {
        "prospecting.budget", "prospecting.db", "prospecting.discovery", "prospecting.models",
        "prospecting.pipeline.calls", "prospecting.providers",
    },
    "prospecting.pipeline.qualification": {
        "prospecting.budget", "prospecting.db", "prospecting.models", "prospecting.pipeline.calls",
        "prospecting.providers", "prospecting.qualification",
    },
    "prospecting.pipeline.contacts": {
        "prospecting.budget", "prospecting.contacts", "prospecting.db", "prospecting.discovery",
        "prospecting.models", "prospecting.pipeline.calls", "prospecting.providers", "prospecting.qualification",
    },
}
# Interfaz, envío de mensajes y automatización de navegador quedan fuera del paquete (§1, §15).
FORBIDDEN = {"streamlit", "smtplib", "twilio", "sendgrid", "slack_sdk", "telegram", "selenium", "playwright"}
# Únicas operaciones de proveedor habilitadas: búsqueda, lectura y verificación.
READ_OPERATIONS = {
    ("tavily", "search"), ("tavily", "extract"),
    ("hunter", "domain_search"), ("hunter", "email_finder"), ("hunter", "email_verifier"),
}


def modules() -> dict[str, Path]:
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        parts = path.relative_to(PROJECT_ROOT).with_suffix("").parts
        found[".".join(parts[:-1] if parts[-1] == "__init__" else parts)] = path
    return found


def trees() -> dict[str, ast.Module]:
    return {name: ast.parse(path.read_text(encoding="utf-8")) for name, path in modules().items()}


def imported(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def internal(tree: ast.Module, known: set[str]) -> set[str]:
    return {name for name in imported(tree) if name in known}


def test_every_module_declares_its_allowed_dependencies():
    assert set(modules()) == set(ALLOWED)


def test_internal_imports_follow_the_declared_direction():
    known = set(modules())
    violations = {name: sorted(internal(tree, known) - ALLOWED[name] - {name})
                  for name, tree in trees().items()}
    assert {name: found for name, found in violations.items() if found} == {}


def test_internal_imports_have_no_cycles():
    known = set(modules())
    graph = {name: internal(tree, known) - {name} for name, tree in trees().items()}
    visiting, done = [], set()

    def visit(name):
        if name in visiting:
            raise AssertionError("Importación circular: " + " -> ".join(visiting[visiting.index(name):] + [name]))
        if name in done:
            return
        visiting.append(name)
        for target in sorted(graph[name]):
            visit(target)
        visiting.pop()
        done.add(name)

    for name in sorted(graph):
        visit(name)


def test_package_has_no_interface_messaging_or_browser_automation():
    used = {name: sorted({item.split(".")[0] for item in imported(tree)} & FORBIDDEN)
            for name, tree in trees().items()}
    assert {name: found for name, found in used.items() if found} == {}


def test_only_the_pipeline_reserves_spending():
    """Solo el orquestador reserva gasto antes de llamar a un proveedor (§13.2)."""
    callers = sorted(
        name for name, tree in trees().items() if not name.startswith("prospecting.pipeline")
        and any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "reserve" for node in ast.walk(tree))
    )
    assert callers == []


def test_enabled_provider_operations_only_search_read_or_verify():
    from prospecting.providers import OperationSpec

    specs = set()
    for name in modules():
        for value in vars(importlib.import_module(name)).values():
            items = value if isinstance(value, (list, tuple)) else [value]
            specs.update((item.provider, item.operation) for item in items if isinstance(item, OperationSpec))
    assert specs == READ_OPERATIONS


def test_every_module_imports_without_side_effects(tmp_path):
    script = """
import os
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])

def reject_side_effects(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'sqlite3.connect',
                 'os.mkdir', 'os.remove', 'os.rename', 'os.rmdir', 'os.truncate'}:
        raise AssertionError(f'Efecto secundario al importar: {event}')
    if event == 'open':
        mode, flags = args[1:3]
        if (mode is not None and any(flag in mode for flag in 'wax+')) or (
            flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        ):
            raise AssertionError('La importación intentó escribir un archivo.')

for key in ('TAVILY_API_KEY', 'ANTHROPIC_API_KEY', 'APOLLO_API_KEY', 'HUNTER_API_KEY'):
    os.environ.pop(key, None)
sys.addaudithook(reject_side_effects)
for name in sys.argv[2:]:
    __import__(name)
assert 'streamlit' not in sys.modules
assert 'anthropic' not in sys.modules
assert list(Path.cwd().iterdir()) == []
"""
    process = subprocess.run(
        [sys.executable, "-B", "-c", script, str(PROJECT_ROOT), *sorted(modules())],
        cwd=tmp_path, capture_output=True, text=True, timeout=20,
    )
    assert process.returncode == 0, process.stderr
    assert list(tmp_path.iterdir()) == []
