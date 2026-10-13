# Veryfi Prospecting

Prototipo académico local para investigar posibles clientes de Veryfi en
Latinoamérica. La interfaz local de Streamlit permite configurar y ejecutar campañas,
consultar progreso, evidencia y presupuesto, revisar empresas, confirmar canales
alternativos existentes y descargar CSV seguro. Reutiliza SQLite y el pipeline de
descubrimiento con Tavily, calificación determinista con Claude Haiku y búsqueda de
personas con Hunter y evidencia pública. La aplicación no envía mensajes ni contacta
a nadie; ventas revisa y contacta fuera de ella.

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

Si las claves están en un `.env` local (ignorado por Git), `uv` las pasa al proceso
de Streamlit con `--env-file`; la aplicación por sí misma no lee ese archivo:

```console
uv run --locked --env-file .env streamlit run app.py
```

Abre [http://127.0.0.1:8501](http://127.0.0.1:8501). La pantalla puede abrirse sin
claves y consultar campañas ya guardadas. Preparar una campaña guarda sus criterios
sin llamar a proveedores; ejecutar o reanudar requiere cuentas y cupos comprobados,
claves en variables de entorno y autorización explícita por operación, cuenta y tope.
Detén el servidor con Ctrl+C. La configuración fija `127.0.0.1`, desactiva la
telemetría y permite iniciar sin abrir un navegador ni pedir un correo.

Usa una sola instancia local de la aplicación con `data/prospecting.sqlite3`.
El procesamiento es secuencial e interactivo: no continúa en segundo plano al cerrar
la aplicación. El historial permite recuperar checkpoints, revisar resultados y
exportar personas actualmente listas o, explícitamente, todos los resultados.

La configuración local de acceso se guarda en `data/provider-access.json`, ignorado
por Git. Contiene cupos y referencias comprobadas, nunca claves ni permisos reutilizables.
Reiniciar la aplicación conserva el consumo y exige permisos nuevos; no renueva el cupo.
La [guía de la interfaz](docs/ui.md) explica el archivo y el flujo completo.

## Evaluación offline

Desde la raíz, evalúa un manifiesto local con instantáneas y etiquetas versionadas:

```console
uv run --locked python evaluate_qualification.py data/evaluation/dataset-v1/manifest.json --output data/evaluation/reports/run-v1
```

El comando comprueba hashes, referencias y separación entre desarrollo y evaluación,
y genera resultados JSON y un informe Markdown. No necesita claves, no llama a
proveedores y no modifica SQLite. Cada salida requiere un directorio nuevo: conserva
los informes anteriores. El [protocolo de evaluación](docs/t10-evaluation.md) describe
los formatos de entrada, las fichas de revisión sin predicción, los denominadores
y la comparación de versiones.

Para generar fichas sin predicción desde un conjunto preparado:

```console
uv run --locked --offline python evaluate_qualification.py data/evaluation/dataset-v1/manifest.json --prepare-blind data/evaluation/blind/dataset-v1
```

Los ejemplos requieren un manifiesto existente; el repositorio no incluye un
conjunto real etiquetado. El replay comprueba la evidencia del payload original;
las instantáneas históricas o formatos de contexto desconocidos se auditan con
sus limitaciones. Una captura incompleta conserva la clasificación válida en las
métricas y declara por separado la pérdida de trazabilidad.

La interfaz no activa la captura opcional. Su
[invocación desde Python](docs/t10-evaluation.md#invocación-de-captura-desde-el-pipeline)
usa `qualify_company(..., evaluation_dir=...)`, la base y presupuesto compartidos
y una autorización vigente. Solo permite capturas bajo el `data/` de este
repositorio; el evaluador offline no inicia esas llamadas.

Las instantáneas, las revisiones originales y los resultados por caso permanecen en
`data/`, fuera de Git. Las métricas distinguen datos sintéticos, resultados reales
guardados e inferencias nuevas, y separan la revisión académica de la atribuida a
Veryfi. Sin etiquetas comerciales documentadas no se presenta precisión comercial.

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
campañas completas y comprueban que reanudar o repetir un clic no repite llamadas, que
las interrupciones conservan el gasto y que el presupuesto y el tiempo acumulado
detienen la ejecución conservando lo guardado. También
ejecutan la pantalla con `AppTest` y verifican que los módulos de datos se importen
sin cargar Streamlit. También comprueban la dirección de las importaciones entre
módulos, que la estructura documentada coincide con el paquete y que los
identificadores guardados en SQLite no cambien. Estas pruebas no demuestran acceso a proveedores ni
validación comercial. Las comprobaciones reales están en
[el registro de proveedores](docs/provider-check.md) y la evaluación de los lotes
ejecutados desde la interfaz, en [la evaluación](docs/evaluation.md); ninguno produjo
una persona lista. Si una política de Windows bloquea `pytest.exe`,
`uv run --locked python -m pytest` ejecuta la misma suite. Los archivos de ejemplo y
`uv.lock` sí se versionan.

## Estructura y responsabilidades

- `app.py`: configuración, ejecución, consulta, revisión y exportación con Streamlit.
- `evaluate_qualification.py`: evaluación offline de instantáneas, etiquetas y trazas locales.
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
- `docs/ui.md`: uso de la interfaz, configuración local de proveedores, revisión y CSV seguro.
- `docs/evaluation.md`: pruebas por riesgo, resultados de los lotes reales, métricas y gasto.
- `docs/t10-evaluation.md`: protocolo, formatos y reproducción de evaluaciones independientes.
- `.streamlit/config.toml`: acceso local, telemetría y exportación integrada de tablas desactivadas.
- `pyproject.toml`, `uv.lock` y `.python-version`: entorno reproducible con uv y Python 3.13.
- `.gitignore` y `.env.example`: protección de archivos locales y nombres de claves sin valores.
- `docs/IDEA.md` y `AGENTS.md`: requisitos y reglas de desarrollo.

La aplicación no carga `.env` automáticamente; `.env.example` solo enumera las variables.
Para ejecutar proveedores, define `TAVILY_API_KEY`, `ANTHROPIC_API_KEY` y, si está
habilitado, `HUNTER_API_KEY` en el entorno del proceso antes de iniciar Streamlit.
`data/`, bases SQLite, credenciales y cachés quedan fuera de Git. Importar los
módulos o iniciar la pantalla no crea una base. Preparar una campaña desde la
interfaz crea la base si falta; abrir `Database` sobre una ruta nueva también la crea.
Conserva la base y sus archivos auxiliares: contienen resultados y consumo ya pagado.

## Integrantes

- Stephanie Jaramillo
- Thomas Serna
- Juan Esteban Palacio
- Juliana Sepulveda
