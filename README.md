# Veryfi Prospecting

Prototipo académico local para investigar posibles clientes de Veryfi en
Latinoamérica. Incluye una pantalla inicial, contratos Pydantic, configuración
versionada, persistencia SQLite, reserva/conciliación de presupuesto, un cliente
HTTP JSON compartido, el descubrimiento de empresas candidatas y la extracción
de páginas con Tavily, la resolución de identidad, duplicados y exclusiones, y la
calificación con Claude Haiku y puntuación determinista, la búsqueda de personas
y canales profesionales con Hunter y evidencia pública, y la orquestación de campañas
que recorre esas etapas con límites de esfuerzo y reanudación; todo se invoca desde Python.
La pantalla no necesita claves, no consume APIs de
proveedores y no muestra resultados comerciales simulados.

## Instalación

Requisitos: Git y [uv](https://docs.astral.sh/uv/getting-started/installation/).
Python 3.13 queda seleccionado por `.python-version` y `pyproject.toml`.

Desde una terminal:

```console
git clone https://github.com/ThomasSerna/veryfi-prospecting.git
cd veryfi-prospecting
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
historial, consumo decimal exacto y recuperación al reabrir SQLite. Comprueban
reservas concurrentes, cupos de créditos y autorizaciones acumuladas, duplicados,
conciliación y timeouts mediante transportes sintéticos. Verifican identidad,
vigencia y estados de canales, la extracción pública citada,
límites de contactos y respuestas pendientes de Hunter sin repetir consumo. Recorren
campañas completas y comprueban que reanudar o repetir un clic no repite llamadas, y que
el presupuesto y el tiempo detienen la ejecución conservando lo guardado. También
ejecutan la pantalla con `AppTest` y verifican que los módulos de datos se importen
sin cargar Streamlit. También comprueban la dirección de las importaciones entre
módulos, que la estructura documentada coincide con el paquete y que los
identificadores guardados en SQLite no cambien. Estas pruebas no demuestran acceso a proveedores ni
validación comercial. Los archivos de ejemplo y `uv.lock` sí se versionan.

## Estructura y responsabilidades

- `app.py`: pantalla inicial de Streamlit, sin lógica de negocio.
- `prospecting/models.py`: contratos de datos, configuración y validación.
- `prospecting/db.py`: SQLite, integridad, transacciones y consultas.
- `prospecting/budget.py`: cupos, autorización, reserva y conciliación de consumo.
- `prospecting/text.py`, `sources.py` y `haiku.py`: texto externo, política de URLs y fuentes, y forma común de las solicitudes a Haiku.
- `prospecting/providers/`: cliente JSON acotado y errores de proveedor (`http.py`), cliente de Claude con el SDK oficial, precios y tope de reserva (`claude.py`) y formato de Tavily (`tavily.py`) y Hunter (`hunter.py`).
- `prospecting/discovery.py`: consultas de plantilla y selección de empresas candidatas.
- `prospecting/identity.py`: identidad, duplicados y exclusiones.
- `prospecting/qualification.py`: rúbrica, puntuación, prioridad, solicitud a Haiku y validación de su respuesta.
- `prospecting/contacts.py`: reglas de personas, canales y condición de listo, independientes de la fuente.
- `prospecting/contact_extraction.py`: extracción de contactos públicos con Haiku y validación de sus citas.
- `prospecting/pipeline/`: etapas que reservan gasto, llaman a proveedores y guardan resultados, un módulo por etapa (descubrimiento e identidad, extracción y ampliación de evidencia, calificación y contactos), las llamadas con reserva compartidas en `calls.py` y la orquestación de campañas en `campaign.py`.
- `config/veryfi.json`: catálogo provisional, perfiles y rúbrica versionada.
- `tests/`: pruebas de inicialización, contratos, persistencia, presupuesto, clientes, descubrimiento, calificación, contactos y orquestación con datos sintéticos.
- `docs/provider-check.md`: registro de comprobaciones reales de acceso a proveedores.
- `docs/persistence.md`: contratos de datos y persistencia local en SQLite.
- `docs/budget-providers.md`: presupuesto, autorizaciones, conciliación y cliente de proveedores.
- `docs/discovery.md`: descubrimiento y extracción con Tavily, identidad, duplicados y exclusiones.
- `docs/qualification.md`: calificación con Haiku, puntuación y prioridad.
- `docs/contacts.md`: invocación desde Python, acceso a Hunter, personas, canales y límites de búsqueda.
- `docs/campaign.md`: orquestación de campañas, límites de tiempo, parada y reanudación.
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
