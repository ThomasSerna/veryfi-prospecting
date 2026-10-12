"""Dirección de las dependencias y capacidades prohibidas del paquete (§13, §15)."""

import ast
import importlib
from importlib.util import resolve_name
from pathlib import Path
import subprocess
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = PROJECT_ROOT / "prospecting"

# Importaciones internas permitidas por módulo. Un módulo nuevo debe declararse aquí.
ALLOWED = {
    "prospecting": set(),
    "prospecting.models": set(),
    "prospecting.db": {"prospecting.models"},
    "prospecting.budget": {"prospecting.db", "prospecting.models"},
    "prospecting.providers": {"prospecting.providers.claude", "prospecting.providers.http"},
    "prospecting.providers.http": {"prospecting.budget", "prospecting.models"},
    "prospecting.providers.claude": {"prospecting.budget", "prospecting.models", "prospecting.providers.http"},
    "prospecting.providers.tavily": {
        "prospecting.discovery", "prospecting.models", "prospecting.providers.http", "prospecting.sources",
        "prospecting.text",
    },
    "prospecting.text": set(),
    "prospecting.sources": {"prospecting.models"},
    "prospecting.haiku": set(),
    "prospecting.discovery": {"prospecting.models", "prospecting.sources", "prospecting.text"},
    "prospecting.identity": {"prospecting.discovery", "prospecting.models", "prospecting.sources", "prospecting.text"},
    "prospecting.qualification": {"prospecting.haiku", "prospecting.models", "prospecting.sources", "prospecting.text"},
    "prospecting.contacts": {"prospecting.models", "prospecting.sources"},
    "prospecting.contact_extraction": {
        "prospecting.contacts", "prospecting.haiku", "prospecting.models", "prospecting.sources",
    },
    "prospecting.providers.hunter": {
        "prospecting.contacts", "prospecting.models", "prospecting.providers.http", "prospecting.sources",
    },
    "prospecting.pipeline": {
        "prospecting.pipeline.contacts", "prospecting.pipeline.discovery", "prospecting.pipeline.qualification",
        "prospecting.pipeline.research",
    },
    "prospecting.pipeline.calls": {
        "prospecting.budget", "prospecting.haiku", "prospecting.models", "prospecting.providers",
    },
    "prospecting.pipeline.discovery": {
        "prospecting.budget", "prospecting.db", "prospecting.discovery", "prospecting.identity", "prospecting.models",
        "prospecting.pipeline.calls", "prospecting.providers", "prospecting.providers.tavily",
    },
    "prospecting.pipeline.research": {
        "prospecting.budget", "prospecting.db", "prospecting.discovery", "prospecting.models",
        "prospecting.pipeline.calls", "prospecting.providers", "prospecting.providers.tavily", "prospecting.sources",
    },
    "prospecting.pipeline.qualification": {
        "prospecting.budget", "prospecting.db", "prospecting.models",
        "prospecting.pipeline.calls", "prospecting.providers", "prospecting.qualification",
    },
    "prospecting.pipeline.contacts": {
        "prospecting.budget", "prospecting.contact_extraction", "prospecting.contacts", "prospecting.db",
        "prospecting.models", "prospecting.pipeline.calls", "prospecting.providers",
        "prospecting.providers.hunter", "prospecting.providers.tavily", "prospecting.sources",
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


def imported(tree: ast.Module, module: str, known: dict[str, Path]) -> set[str]:
    """Módulos que importa `tree`. `module` y `known` (el mapa de `modules()`) fijan el paquete de origen."""
    package = module if known[module].name == "__init__.py" else module.rpartition(".")[0]
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            try:
                base = resolve_name("." * node.level + (node.module or ""), package)
            except ImportError as error:
                raise ImportError(f"{module}:{node.lineno}: {error}") from error
            # Un nombre importado es el submódulo si existe en `known`; si no, un símbolo exportado por `base`.
            names.update(f"{base}.{alias.name}" if f"{base}.{alias.name}" in known else base
                         for alias in node.names)
    return names


def internal(tree: ast.Module, module: str, known: dict[str, Path]) -> set[str]:
    return {name for name in imported(tree, module, known) if name in known}


def undeclared(parsed: dict[str, ast.Module], known: dict[str, Path]) -> dict[str, list[str]]:
    """Importaciones internas de cada módulo que `ALLOWED` no declara."""
    violations = {name: sorted(internal(tree, name, known) - ALLOWED[name] - {name})
                  for name, tree in parsed.items()}
    return {name: found for name, found in violations.items() if found}


def assert_acyclic(parsed: dict[str, ast.Module], known: dict[str, Path]) -> None:
    """Falla con la cadena de importaciones si las dependencias internas forman un ciclo."""
    graph = {name: internal(tree, name, known) - {name} for name, tree in parsed.items()}
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


def prohibited(parsed: dict[str, ast.Module], known: dict[str, Path]) -> dict[str, list[str]]:
    """Módulos de `FORBIDDEN` que importa cada módulo, sea cual sea la forma de la importación."""
    used = {name: sorted({item.split(".")[0] for item in imported(tree, name, known)} & FORBIDDEN)
            for name, tree in parsed.items()}
    return {name: found for name, found in used.items() if found}


def test_every_module_declares_its_allowed_dependencies():
    assert set(modules()) == set(ALLOWED)


def test_internal_imports_follow_the_declared_direction():
    assert undeclared(trees(), modules()) == {}


def test_internal_imports_have_no_cycles():
    assert_acyclic(trees(), modules())


def test_documented_structure_matches_the_package():
    """El árbol de IDEA.md §13.1 describe exactamente los módulos del paquete."""
    idea = (PROJECT_ROOT / "docs" / "IDEA.md").read_text(encoding="utf-8")
    tree = idea.split("### 13.1", 1)[1].split("```text", 1)[1].split("```", 1)[0]
    documented, folder = set(), []
    for line in tree.splitlines():
        entry = line.split()[0] if line.strip() else ""
        depth = (len(line) - len(line.lstrip())) // 2
        if entry.endswith("/"):
            folder[depth:] = [entry.rstrip("/")]
        elif entry.endswith(".py") and folder and folder[0] == "prospecting":
            parts = folder[:depth] + [entry[:-3]]
            documented.add(".".join(parts))
    package = {name for name, path in modules().items() if path.name != "__init__.py"}
    assert documented == package


def test_package_has_no_interface_messaging_or_browser_automation():
    assert prohibited(trees(), modules()) == {}


def test_only_the_pipeline_reserves_spending():
    """Solo `pipeline/calls.py` reserva gasto antes de llamar a un proveedor (§13.2, §14.3)."""
    callers = sorted(
        name for name, tree in trees().items() if name != "prospecting.pipeline.calls"
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


# El analizador se prueba con árboles AST en memoria: no lee el paquete real y solo comparte con él
# las reglas de `ALLOWED` y `FORBIDDEN`. Como en `modules()`, los paquetes se reconocen por `__init__.py`.
KNOWN = {
    "prospecting": Path("prospecting/__init__.py"),
    "prospecting.models": Path("prospecting/models.py"),
    "prospecting.db": Path("prospecting/db.py"),
    "prospecting.discovery": Path("prospecting/discovery.py"),
    "prospecting.identity": Path("prospecting/identity.py"),
    "prospecting.contacts": Path("prospecting/contacts.py"),
    "prospecting.contact_extraction": Path("prospecting/contact_extraction.py"),
    "prospecting.pipeline": Path("prospecting/pipeline/__init__.py"),
    "prospecting.pipeline.calls": Path("prospecting/pipeline/calls.py"),
    "prospecting.pipeline.discovery": Path("prospecting/pipeline/discovery.py"),
    "prospecting.pipeline.stage": Path("prospecting/pipeline/stage/__init__.py"),
    "prospecting.pipeline.stage.step": Path("prospecting/pipeline/stage/step.py"),
}


@pytest.mark.parametrize("source", [
    "import prospecting.models",
    "import prospecting.models as m",
    "from prospecting import models",
    "from prospecting import models as m",
    "from prospecting.models import Campaign",
    "from prospecting.models import Campaign as C",
    "from . import models",
    "from . import models as m",
    "from .models import Campaign",
    "from .models import Campaign as C",
])
def test_absolute_and_relative_imports_give_the_same_dependency(source):
    """Ninguna forma añade además una dependencia artificial al paquete raíz."""
    assert internal(ast.parse(source), "prospecting.db", KNOWN) == {"prospecting.models"}


def test_each_imported_name_is_a_submodule_or_a_symbol_of_its_module():
    tree = ast.parse("from . import models, VERSION")
    assert internal(tree, "prospecting.db", KNOWN) == {"prospecting.models", "prospecting"}


@pytest.mark.parametrize("name, source, target", [
    ("prospecting.discovery", "from .db import Database", "prospecting.db"),
    ("prospecting.discovery", "from . import db", "prospecting.db"),
    ("prospecting.discovery", "from prospecting.db import Database", "prospecting.db"),
    # Las dos dependencias entre módulos de negocio que se permiten no valen en sentido contrario.
    ("prospecting.discovery", "from .identity import Candidate", "prospecting.identity"),
    ("prospecting.contacts", "from . import contact_extraction", "prospecting.contact_extraction"),
])
def test_undeclared_dependencies_are_rejected_in_any_import_form(name, source, target):
    assert undeclared({name: ast.parse(source)}, KNOWN) == {name: [target]}


@pytest.mark.parametrize("name, source, target", [
    ("prospecting.db", "from . import models", "prospecting.models"),
    ("prospecting.db", "from .models import Campaign", "prospecting.models"),
    ("prospecting.identity", "from .discovery import Candidate", "prospecting.discovery"),
    ("prospecting.contact_extraction", "from . import contacts", "prospecting.contacts"),
])
def test_declared_dependencies_are_seen_and_accepted_in_any_import_form(name, source, target):
    tree = ast.parse(source)
    assert internal(tree, name, KNOWN) == {target}
    assert undeclared({name: tree}, KNOWN) == {}


@pytest.mark.parametrize("name, source, target", [
    # Módulo anidado: su paquete es el contenedor, así que `.` es `prospecting.pipeline`.
    ("prospecting.pipeline.calls", "from . import discovery", "prospecting.pipeline.discovery"),
    ("prospecting.pipeline.calls", "from .discovery import Candidate", "prospecting.pipeline.discovery"),
    ("prospecting.pipeline.calls", "from .. import discovery", "prospecting.discovery"),
    ("prospecting.pipeline.calls", "from ..models import Usage", "prospecting.models"),
    ("prospecting.pipeline.stage.step", "from ... import models", "prospecting.models"),
    ("prospecting.pipeline.stage.step", "from ...discovery import Candidate", "prospecting.discovery"),
    # `__init__.py`: su paquete es el propio módulo, así que `.` es `prospecting.pipeline`.
    ("prospecting.pipeline", "from . import calls", "prospecting.pipeline.calls"),
    ("prospecting.pipeline", "from .calls import reserve", "prospecting.pipeline.calls"),
    ("prospecting.pipeline", "from .. import models", "prospecting.models"),
    ("prospecting.pipeline.stage", "from . import step", "prospecting.pipeline.stage.step"),
    ("prospecting.pipeline.stage", "from .. import calls", "prospecting.pipeline.calls"),
    ("prospecting", "from . import models", "prospecting.models"),
])
def test_relative_imports_resolve_from_nested_modules_and_init_files(name, source, target):
    assert internal(ast.parse(source), name, KNOWN) == {target}


def test_a_cycle_made_only_of_relative_imports_is_detected():
    parsed = {
        "prospecting.discovery": ast.parse("from .pipeline import calls"),
        "prospecting.pipeline.calls": ast.parse("from .. import discovery"),
    }
    cycle = "prospecting.discovery -> prospecting.pipeline.calls -> prospecting.discovery"
    with pytest.raises(AssertionError, match=f"Importación circular: {cycle}"):
        assert_acyclic(parsed, KNOWN)


@pytest.mark.parametrize("name, source", [
    ("prospecting.models", "from .. import db"),
    ("prospecting", "from .. import models"),
    ("prospecting.pipeline.calls", "from ... import models"),
    ("prospecting.pipeline", "from ...models import Usage"),
])
def test_a_relative_import_beyond_the_package_fails_explicitly(name, source):
    with pytest.raises(ImportError) as error:
        internal(ast.parse(source), name, KNOWN)
    assert str(error.value).startswith(f"{name}:1:")


def test_forbidden_modules_are_detected_next_to_relative_imports():
    tree = ast.parse("import selenium.webdriver as driver\nfrom smtplib import SMTP\nfrom . import models")
    assert prohibited({"prospecting.db": tree}, KNOWN) == {"prospecting.db": ["selenium", "smtplib"]}
