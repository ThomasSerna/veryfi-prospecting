# Veryfi Prospecting

Prototipo académico local para investigar posibles clientes de Veryfi en
Latinoamérica. Incluye una pantalla inicial, contratos Pydantic, configuración
versionada y persistencia SQLite. Todavía no
descubre empresas, califica prospectos ni busca contactos. No necesita claves,
no consume APIs de proveedores y no muestra resultados comerciales simulados.

## Instalación

Requisitos: Git y [uv](https://docs.astral.sh/uv/getting-started/installation/).
Python 3.13 queda seleccionado por `.python-version` y `pyproject.toml`.

Desde una terminal:

```console
git clone https://github.com/ThomasSerna/proyecto-sistemas-informacion.git
cd proyecto-sistemas-informacion
uv python install 3.13
uv sync --locked
```

Si ya tienes el repositorio, ejecuta los dos últimos comandos desde su raíz.
`uv sync --locked` crea `.venv/` e instala las versiones de `uv.lock`, incluyendo
pytest. No hace falta activar el entorno ni instalar paquetes con pip.
La instalación necesita Internet para descargar Python y las dependencias.

## Ejecución

Desde la raíz del repositorio:

```console
uv run --locked streamlit run app.py
```

Abre [http://127.0.0.1:8501](http://127.0.0.1:8501). Debes ver el título
«Veryfi Prospecting» y el mensaje «Aplicación inicial funcionando».
Detén el servidor con Ctrl+C. La configuración fija `127.0.0.1`, desactiva la
telemetría y permite iniciar sin abrir un navegador ni pedir un correo.

## Verificación

```console
uv lock --check
uv run --locked pytest
git check-ignore -v .env .env.local .venv/pyvenv.cfg data/prospecting.sqlite3 .streamlit/secrets.toml __pycache__/app.pyc .pytest_cache/v/cache/nodeids local.sqlite3-wal
```

Las pruebas bloquean conexiones externas y usan datos explícitamente sintéticos
y bases temporales. Comprueban contratos, procedencia, relaciones, transacciones,
historial, consumo decimal exacto y recuperación al reabrir SQLite. También
ejecutan la pantalla con `AppTest` y verifican que los módulos de datos se importen
sin cargar Streamlit. Estas pruebas no demuestran acceso a proveedores ni
validación comercial. Los archivos de ejemplo y `uv.lock` sí se versionan.

## Contratos y persistencia local

La pantalla no crea ni consulta una base automáticamente.
La capa de datos puede utilizarse desde Python, sin Streamlit ni claves:

```python
from pathlib import Path

from prospecting.db import Database
from prospecting.models import Campaign, VeryfiConfig

config = VeryfiConfig.model_validate_json(
    Path("config/veryfi.json").read_text(encoding="utf-8")
)
campaign = Campaign(
    countries=["CO"],
    segments=["fintech_software"],
    rubric_version="rubric_v1",
    config_snapshot=config,
)
with Database(Path("data/prospecting.sqlite3")) as db:
    db.save_campaign(campaign)
    assert db.get_campaign(campaign.id) == campaign
```

La configuración contiene un catálogo provisional, los cuatro perfiles de
IDEA.md, `rubric_v1` y los límites iniciales. No representa capacidades ni reglas
certificadas comercialmente. Cada campaña conserva una instantánea de esta
configuración; actualizar el archivo no cambia campañas ya guardadas.

`Database` ofrece `save_campaign/company/evidence/assessment/contact/run_item/usage`,
consultas `get_*` y listas `list_campaigns/evidence/assessments/contacts/run_items/usage`.
`get_active_campaign()` recupera la única campaña `running` o `paused_budget`.
Las consultas devuelven contratos revalidados, no filas SQL.

Cada dato externo conocido necesita procedencia. Al crear una empresa o persona,
usar `save_company(company, evidence=...)` o `save_contact(contact, evidence=...)`
para guardar el registro y su evidencia nueva juntos. Un `RunItem` vincula empresa
y campaña antes de guardar evaluaciones o consumo por empresa. Las referencias
deben existir y pertenecer a la empresa/persona correspondiente.

Una escritura aislada es atómica. `with db.transaction():` agrupa varias
escrituras; cualquier excepción revierte el grupo. Las transacciones no admiten
anidamiento y deben cerrarse antes de llamar a un proveedor. Un fallo de agregado
revierte también su escritura parcial si el llamador captura la excepción dentro
de una transacción mayor.

Las evidencias y evaluaciones son inmutables: repetir su ID y contenido no crea
duplicados; una corrección de evaluación recibe otro ID y `revision_of`.
Empresas con el mismo dominio permanecen separadas. `None` se conserva como
desconocido, distinto de cero o `False`; el consumo desconocido no se rellena.
Dinero y créditos se guardan como texto decimal exacto, sin sumas SQLite `REAL`.

La base se crea únicamente cuando la ruta no existe. Reabrir una base compatible
conserva checkpoints y uso; un esquema incompatible, incompleto o corrupto genera
un error, sin recrear tablas. No hay funciones de borrado ni migraciones
automáticas. Conserva la base y sus archivos auxiliares al cerrar la aplicación;
contienen resultados y consumo que no deben descartarse.

La capa de datos no calcula puntuaciones, no determina si un prospecto está listo
y no aplica reservas, conciliación ni autorización de gasto. Mantener dos bases
distintas no coordina el presupuesto global.

## Estructura y responsabilidades

- `app.py`: pantalla inicial de Streamlit, sin lógica de negocio.
- `prospecting/models.py`: contratos de datos, configuración y validación.
- `prospecting/db.py`: SQLite, integridad, transacciones y consultas.
- `config/veryfi.json`: catálogo provisional, perfiles y rúbrica versionada.
- `tests/`: pruebas de inicialización, contratos y persistencia con datos sintéticos.
- `.streamlit/config.toml`: acceso local y telemetría desactivada.
- `pyproject.toml`, `uv.lock` y `.python-version`: entorno reproducible con uv y Python 3.13.
- `.gitignore` y `.env.example`: protección de archivos locales y nombres de claves sin valores.
- `docs/IDEA.md` y `AGENTS.md`: requisitos y reglas de desarrollo.

La aplicación no lee `.env`; no copies ni rellenes `.env.example` para arrancarla.
`data/`, bases SQLite, credenciales y cachés quedan fuera de Git. Importar los
módulos o iniciar la pantalla no crea una base; abrir `Database` sobre una ruta
nueva sí la crea.

## Integrantes

- Stephanie Jaramillo
- Thomas Serna
- Juan Esteban Palacio
- Juliana Sepulveda
