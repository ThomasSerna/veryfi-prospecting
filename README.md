# Veryfi Prospecting

Prototipo académico local para investigar posibles clientes de Veryfi en
Latinoamérica. T00 prepara el entorno y muestra una pantalla inicial; todavía no
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

Las pruebas ejecutan la pantalla con `AppTest`, bloquean conexiones externas,
comprueban la configuración local y verifican que el paquete de prospección se
importe sin cargar Streamlit. `AppTest` simula la sesión de UI; no es una prueba
de acceso a proveedores. Los archivos de ejemplo y `uv.lock` sí se versionan.

## Estructura y responsabilidades

- `app.py`: pantalla inicial de Streamlit, sin lógica de negocio.
- `prospecting/`: paquete Python independiente de Streamlit, sin integraciones aún.
- `tests/`: pruebas locales de la inicialización.
- `.streamlit/config.toml`: acceso local y telemetría desactivada.
- `pyproject.toml`, `uv.lock` y `.python-version`: entorno reproducible con uv y Python 3.13.
- `.gitignore` y `.env.example`: protección de archivos locales y nombres de claves sin valores.
- `docs/IDEA.md` y `AGENTS.md`: requisitos y reglas de desarrollo.

T00 no lee `.env`; no copies ni rellenes `.env.example` para arrancar la app.
Las claves se configurarán al implementar la integración correspondiente.
`data/`, bases SQLite, credenciales y cachés quedan fuera de Git; T00 no crea
una base de datos ni archivos para funcionalidades futuras.

La siguiente tarea es T01: contratos mínimos, persistencia SQLite y
configuración del catálogo/rúbrica. No se ha iniciado.

## Integrantes

- Stephanie Jaramillo
- Thomas Serna
- Juan Esteban Palacio
- Juliana Sepulveda
