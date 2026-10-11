# Veryfi Prospecting

Prototipo académico local para investigar posibles clientes de Veryfi en
Latinoamérica. Incluye una pantalla inicial, contratos Pydantic, configuración
versionada, persistencia SQLite, reserva/conciliación de presupuesto y un cliente
HTTP JSON compartido. Todavía no
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
historial, consumo decimal exacto y recuperación al reabrir SQLite. Comprueban
reservas concurrentes, cupos de créditos y autorizaciones acumuladas, duplicados,
conciliación y timeouts mediante transportes sintéticos. También
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

La persistencia no calcula puntuaciones ni determina si un prospecto está listo.
El control de gasto corresponde a `Budget`. Mantener dos bases distintas no
coordina el presupuesto global.

## Presupuesto y cliente de proveedores

`Budget(db, global_limits, account_allowances)` reutiliza la misma base SQLite y
los límites de la configuración. Sus métodos `reserve`, `claim`, `record_result`
y `reconcile` ejecutan transacciones breves propias; no deben llamarse dentro de
`db.transaction()`. `snapshot` muestra importes confirmados, estimados, reservados,
pendientes y disponibles, distinguiendo desconocidos y excesos.

El máximo global es USD 20 y las llamadas automáticas se limitan a USD 15. El
margen de USD 5 no habilita llamadas adicionales. El límite por campaña es USD 2
y el de USD 0,25 por empresa acumula todas sus campañas. Las reducciones guardadas
en una campaña se respetan. La distribución IA/web/contactos es orientativa.

Los cupos se proporcionan como objetos `AccountAllowance` validados, con
`provider`, `account_ref`, `funding_source`, `credit_limit`, `cost_limit_usd`,
`source_reference` y `observed_at`. Guarda esa configuración local bajo `data/`,
fuera de Git: los módulos no crean ni cargan automáticamente ese archivo.
Los cupos representan el saldo inicial asignado al registro completo del sprint;
siempre se resta todo el historial, sin renovar cuota por fecha o reinicio.
Una consulta posterior de saldo restante no sustituye ese saldo inicial.

El crédito gratuito acreditado cuenta como USD 0, pero consume su cupo de créditos.
El prepago cuenta por su costo económico y no vuelve a contar como desembolso.
Los cobros nuevos se registran aparte sin duplicarlos en el acumulado. Cada
llamada utiliza un solo origen; no hay recargas ni mezcla automática de saldos.
Los valores necesarios desconocidos bloquean el envío.

Cada reserva y reclamación exige `SpendingAuthorization`: proveedor, operación,
cuenta, topes de dinero/créditos, responsable, referencia y fecha del permiso.
Los topes se aplican al consumo acumulado desde la autorización. Construir este
objeto no sustituye la aprobación humana del responsable para esa sesión.

`claim` cambia una reserva a `in_flight` de manera exclusiva, antes de la red.
`record_result` guarda el resultado técnico y consumo observado. Un timeout o
interrupción conserva la reserva; al reabrir, una solicitud `in_flight` no se
reenvía. `reconcile` recibe una `Confirmation` con consumo confirmado, referencia
y fecha: libera únicamente la diferencia acreditada y conserva el importe de la
reserva original. Un cargo inesperado se registra y bloquea nuevas llamadas.

El contrato persistido conserva cuenta, importes y fechas, pero no el texto de la
referencia del comprobante de conciliación. El responsable debe conservar los
comprobantes y la configuración financiera bajo `data/`; el módulo no los archiva
automáticamente. No borres la base ni sus archivos auxiliares para liberar saldo.

`ProviderClient` recibe descriptores `OperationSpec` definidos por código para
operaciones explícitas y un transporte opcional para pruebas.
`fingerprint` calcula una huella SHA-256 sin autenticación.
`request_json` exige reserva persistida y autorización, ejecuta un solo intento y
devuelve `ProviderResult` con un modelo Pydantic validado. Devuelve errores tipados
para fallos locales, HTTP, transporte, timeout, formato y tamaño; las claves y
entradas sensibles se omiten de los mensajes. No interpreta permisos o cuota con
una tabla HTTP universal ni reintenta automáticamente.

El transporte estándar utiliza HTTPS verificado, un opener privado sin proxies
heredados ni redirecciones, timeout de 10 segundos como máximo por operación
bloqueante y respuesta máxima de 1 MiB. Descuenta del tiempo restante el empleado
en la preparación y reclamación. Ese timeout no garantiza un plazo absoluto para
DNS o toda la llamada. El cliente no descarga páginas arbitrarias ni implementa
integraciones comerciales: la pantalla no tiene operaciones externas habilitadas.

Las claves se leen únicamente de variables de entorno al ejecutar una operación:
`TAVILY_API_KEY`, `ANTHROPIC_API_KEY`, `APOLLO_API_KEY` y `HUNTER_API_KEY`.
No se carga `.env` automáticamente. Una clave presente no autoriza gasto.
No hay envío comercial, recargas, waterfall ni enriquecimiento móvil de pago.

`Usage` identifica y contabiliza solicitudes, pero no almacena cuerpos HTTP.
Los éxitos repetidos se bloquean para recuperar su resultado guardado; si falta
ese resultado, requieren revisión. Un segundo intento necesita conciliación,
fallo transitorio identificado por el adaptador y otra reserva; después de un
reinicio no se deduce transitoriedad del mensaje guardado.

## Estructura y responsabilidades

- `app.py`: pantalla inicial de Streamlit, sin lógica de negocio.
- `prospecting/models.py`: contratos de datos, configuración y validación.
- `prospecting/db.py`: SQLite, integridad, transacciones y consultas.
- `prospecting/budget.py`: cupos, autorización, reserva y conciliación de consumo.
- `prospecting/providers.py`: cliente JSON acotado y errores de proveedor.
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
