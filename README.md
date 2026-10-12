# Veryfi Prospecting

Prototipo académico local para investigar posibles clientes de Veryfi en
Latinoamérica. Incluye una pantalla inicial, contratos Pydantic, configuración
versionada, persistencia SQLite, reserva/conciliación de presupuesto, un cliente
HTTP JSON compartido, el descubrimiento de empresas candidatas y la extracción
de páginas con Tavily, la resolución de identidad, duplicados y exclusiones, y la
calificación con Claude Haiku y puntuación determinista, que se invocan desde Python.
Todavía no busca contactos. La pantalla no necesita claves, no consume APIs de
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
los límites de la configuración. Cada instancia representa una sesión y comienza
sin permisos. Sus métodos `reserve`, `claim`, `begin_send`, `record_result` y
`reconcile` ejecutan transacciones breves propias; no deben llamarse dentro de
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
Cada saldo real debe tener una referencia canónica y un único cupo por proveedor
y cuenta. Las configuraciones duplicadas se rechazan, incluso con distintos
orígenes de financiación; cambiar de origen conserva el consumo de toda la cuenta.
El responsable debe identificar los alias que correspondan al mismo saldo.

El crédito gratuito acreditado se imputa como USD 0, pero consume su cupo de créditos.
El prepago cuenta por su costo económico y no vuelve a contar como desembolso.
Los cobros nuevos se registran aparte sin duplicarlos en el acumulado. Cada
llamada utiliza un solo origen; no hay recargas ni mezcla automática de saldos.
Los valores necesarios desconocidos bloquean el envío.

El campo opcional `AccountAllowance.credit_valuation` recibe `CreditValuation`
con `unit_value_usd`, `source_reference` y `observed_at`. Conserva esa valoración
de referencia fija del sprint bajo `data/` y reutilízala al reabrir la base;
los módulos no consultan precios ni guardan la valoración automáticamente.
`snapshot().free_credit_equivalent` muestra el equivalente económico de créditos
gratuitos confirmado, estimado, reservado y pendiente. Si falta la valoración,
la cuenta atribuible o el consumo necesario, queda desconocido. Es informativo:
no se suma al gasto imputable ni modifica las reservas o los topes monetarios.

Cada reserva y reclamación exige `SpendingAuthorization`: proveedor, operación,
cuenta, topes de dinero/créditos, responsable, referencia y fecha del permiso.
Después de la aprobación humana explícita, el llamador registra el permiso con
`budget.authorize(authorization)`. Su fecha debe ser posterior a la creación de
esa instancia y no futura. Los permisos antiguos, no registrados o con topes
alterados se rechazan; construir el objeto no sustituye la aprobación humana.
Los topes se aplican al consumo acumulado de las solicitudes vinculadas al permiso.
Conservar la instancia durante reruns conserva la sesión; crear otra exige un
permiso nuevo. Este puede reclamar una reserva antigua todavía `reserved`,
contándola una sola vez, sin cambiar su identificador, fecha ni historial.

`claim` cambia una reserva a `in_flight` de manera exclusiva, antes de la red.
`begin_send` debe ejecutarse inmediatamente antes del transporte: consume la
prueba en memoria de que esa reclamación todavía no inició una llamada.
`record_result` guarda el resultado técnico y consumo observado. Si vence el
plazo antes del transporte, el cliente registra `failed` y consumo observado cero
con `no_send=True`. Conserva las reservas hasta una conciliación explícita con
`Confirmation(no_send=True)` y costo, créditos y desembolso cero.
Un timeout o error después de iniciar el transporte conserva la reserva y no puede
usar esa prueba de no envío. La prueba se pierde al reconstruir `Budget` antes de
conciliar; el caso queda pendiente de confirmación del consumo. Al reabrir, una
solicitud `in_flight` no se reenvía. `reconcile` recibe una `Confirmation` con
consumo confirmado, referencia y fecha: libera únicamente la diferencia acreditada
y conserva el importe de la reserva original. Un cargo inesperado se registra y
bloquea nuevas llamadas.

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

## Descubrimiento y extracción con Tavily

`prospecting/pipeline.py` es el único módulo que reserva consumo y llama a Tavily.
`prospecting/discovery.py` construye consultas, valida respuestas y selecciona
candidatos sin red ni base de datos. Ambas funciones admiten solamente crédito
gratuito (`funding_source="free_credit"`, USD 0 por llamada) y exigen un
`SpendingAuthorization` registrado para la operación `search` o `extract`:

```python
import time

from prospecting.discovery import TAVILY_OPERATIONS
from prospecting.pipeline import extract_company_pages, run_discovery
from prospecting.providers import ProviderClient

client = ProviderClient(budget, TAVILY_OPERATIONS)
report = run_discovery(db, budget, client, campaign.id, account_ref="cuenta-tavily",
                       authorization=search_grant, deadline=time.monotonic() + 60)
pages = extract_company_pages(db, budget, client, campaign.id, report.selected_company_ids[0],
                              urls, account_ref="cuenta-tavily", authorization=extract_grant)
```

`run_discovery` genera consultas de plantilla (`discovery_queries_v1`) solo para los
países y segmentos de la campaña, con un máximo de 8 consultas `basic` de 10
resultados cada una, y aplica el tope de 60 candidatos brutos. Agrupa los resultados
por host exacto y selecciona hasta `max_companies`, intentando
`target_per_country_segment` por combinación; si una combinación no alcanza esa meta,
el informe lo indica en lugar de rellenarla. Guarda en una sola transacción, para cada
candidato seleccionado, `Company`, `Evidence` y `RunItem` en la etapa `discovered`;
el resto de candidatos solo aparece en el informe. Si la campaña ya tiene empresas
guardadas, la función no vuelve a llamar.

Cada empresa queda con identidad `pending`, nombre inferido (evidencia `inference`)
y dominio respaldado por los resultados observados. País de operación y segmento
quedan desconocidos. La evidencia guarda la URL, `provider="tavily"`, la referencia
de la solicitud, el fragmento acotado del buscador y `retrieved_at`.
El fragmento del buscador solo localiza la fuente.

`extract_company_pages` valida cada URL: solo admite HTTP(S) hacia nombres públicos
y rechaza IP, `localhost`, credenciales, puertos no estándar, redes sociales y
dominios de gobierno. Respeta el cupo de páginas de `effort.initial`, menos las ya
consumidas, y guarda hasta 3 fragmentos de 800 caracteres como máximo por página.
Un fragmento cuenta como fuente `primary` solo si la página pertenece al dominio de
la empresa. Las URLs que Tavily no pudo extraer no generan evidencia.

Los fallos se informan con motivos propios de Tavily: `permission_denied`,
`quota_exceeded`, `rate_limited`, `invalid_input`, `provider_error`, `timeout` e
`invalid_response`. No se reintentan automáticamente. Los créditos que devuelve
`usage` se registran como observados; la conciliación sigue siendo manual con
`Budget.reconcile`. Los textos de páginas y buscadores se guardan como datos y no
modifican límites, consultas ni permisos. `docs/provider-check.md` registra la
comprobación real de acceso.

## Identidad, duplicados y exclusiones

La lista de clientes actuales, oportunidades y exclusiones de Veryfi se guarda
localmente en `data/exclusions.json`, fuera de Git. Los módulos no la crean.
Su formato:

```json
{
  "version": "exclusiones-2026-10",
  "validation_status": "validated",
  "source_reference": "Lista entregada por Veryfi",
  "observed_at": "2026-10-11T12:00:00Z",
  "entries": [
    {"id": "e1", "name": "Nombre de la cuenta", "domains": ["dominio.example"],
     "aliases": [], "scope": "entity", "countries": [],
     "reason": "current_customer", "detail": null, "source_reference": "Fila 1"}
  ]
}
```

`scope` admite `entity`, `country` (con `countries` obligatorio) o `group`.
`reason` admite `current_customer`, `open_opportunity` o `excluded`.
`load_exclusions(path)` devuelve `None` si el archivo no existe; un archivo inválido
produce un error de validación. Si la lista falta (`missing`) o no está validada
(`pending`), los informes lo indican con `exclusions_status`: las exclusiones
comerciales no están validadas y no se afirma ausencia de relación con Veryfi.

`run_discovery(..., exclusions=lista)` descarta antes de seleccionar los candidatos
cuyo host coincide con un dominio de la lista (o es un subdominio). No ocupan plaza
y solo aparecen en `report.excluded`. Una coincidencia solo por nombre puede ser un
homónimo: el candidato se guarda con `stop_reason="exclusion_review"` y una
evidencia manual de la coincidencia. Una empresa con identidad confirmada, el
mismo dominio, el mismo nombre o alias y el país de la consulta se reutiliza
(`report.reused_company_ids`); en cualquier otro caso se crea otra empresa.

`resolve_company_identity(db, campaign_id, company_id, exclusions=lista)` no llama a
proveedores: decide con la evidencia guardada.

Para confirmar la identidad hacen falta tres cosas:
- **Fuente primaria:** al menos un fragmento de una página del propio dominio.
- **Nombre:** el nombre inferido aparece en esa página como palabra completa. Si no aparece,
  vale la etiqueta del dominio en su forma observada; en ese caso esa forma pasa a ser
  el nombre y el inferido queda como alias.
- **País de la campaña:** un ccTLD local (`.com.co`, `.net.co`, `.org.co` o `.mx`) o una
  mención en una página propia (texto o ruta como `/colombia` o `/mx/`).

Lo que no se comprueba queda `pending`, sin avanzar de etapa, y se registra el
`stop_reason`: `identity_unverified`, `name_unconfirmed`, `country_unconfirmed`,
`exclusion_review` o `duplicate_review:<id>`. Un ccTLD extranjero sin mención del país
genera una advertencia, pero no una exclusión.

La identidad confirmada recibe la clave `dominio|nombre|países`. Por eso, filiales
con el mismo dominio y distinto nombre, homónimos con distinto dominio y la misma
marca en otro país nunca se fusionan.

Si otra empresa confirmada de la misma campaña ya tiene esa clave, el `RunItem`
queda excluido como `duplicate_of:<id>`. Una coincidencia con el dominio de la lista
también lo excluye (`excluded_account`).

Las exclusiones guardan `business_status="excluded"` antes de cualquier
enriquecimiento. País y segmento se acumulan con su procedencia, y una identidad
confirmada no se degrada desde otra campaña. Repetir la resolución no duplica
evidencia.

## Calificación con Haiku

`qualify_company(db, budget, ClaudeClient(budget), campaign_id, company_id,
account_ref=..., funding_source=..., authorization=...)` califica una empresa de la
campaña. Haiku propone y Python decide:

- **Sin llamada a Haiku:** una empresa excluida recibe `excluded`. Una identidad no
  confirmada o sin evidencia útil recibe `insufficient_evidence`, con los cinco
  criterios en `null`.
- **Solicitud:** usa el modelo `claude-haiku-5-5` con el prompt versionado
  `haiku_assessment_v1`, *thinking* desactivado y *effort* `low`.
  - La salida es JSON con esquema. El límite de entrada es
    `limits.llm.max_input_tokens` (unos 3 caracteres por token) y el de salida,
    `limits.llm.max_output_tokens`.
  - La evidencia de la empresa va como datos delimitados y no confiables: primero
    las fuentes primarias, sin la evidencia de contactos ni las revisiones manuales.
- **Validación:** Haiku devuelve un valor `0`, `0.5`, `1` o `null` por criterio, con
  `evidence_ids` y justificación, además de productos, cargos, contradicciones y datos
  faltantes. Python rechaza los ids no suministrados, los valores conocidos sin
  evidencia y los productos o cargos fuera de la configuración. No los corrige.
- **Puntuación:** Python calcula `fit_score` y `coverage` con los pesos de
  `rubric_v1`. `null` no suma peso ni equivale a cero. La prioridad sigue las reglas
  de IDEA.md §8.2 con los umbrales de la rúbrica: `high` exige además que la
  necesidad documental cite una fuente primaria.
- **Guardado:** se guardan juntos el `Assessment` (modelo exacto, versiones de prompt y
  rúbrica) y el `RunItem` en la etapa `assessed`.
  - `low` fija el resultado comercial `low_fit`.
  - `insufficient_evidence` queda en el `stop_reason`, sin fijarse como resultado
    comercial, porque aún cabe una ampliación de evidencia.
  - Repetir la calificación reutiliza la evaluación guardada.

`ClaudeClient` usa el SDK oficial `anthropic` con la clave de `ANTHROPIC_API_KEY`,
`max_retries=0` y un timeout de 30 s como máximo. Sigue el mismo protocolo de
reserva, reclamación y registro que `ProviderClient`.

- **Presupuesto:** cada llamada reserva el costo máximo con los precios publicados
  (USD 0,10 por millón de tokens de entrada y USD 0,50 por millón de salida): unos
  USD 0,0011 con los límites iniciales. Se registran los tokens y el costo estimado;
  la conciliación sigue siendo manual. El cupo de la cuenta `anthropic` se configura
  con `AccountAllowance`, con origen `prepaid` o `new_outlay` y `cost_limit_usd`.
- **Fallos:** un rechazo (`refusal`), una respuesta truncada (`max_tokens`), un JSON o
  una validación inválidos, o un error HTTP, de red o de timeout dejan la evaluación
  pendiente (`assessment_pending:<motivo>`) con el mensaje literal. Se conserva la
  evidencia y no se reintenta ni se cambia de modelo.

## Estructura y responsabilidades

- `app.py`: pantalla inicial de Streamlit, sin lógica de negocio.
- `prospecting/models.py`: contratos de datos, configuración y validación.
- `prospecting/db.py`: SQLite, integridad, transacciones y consultas.
- `prospecting/budget.py`: cupos, autorización, reserva y conciliación de consumo.
- `prospecting/providers.py`: cliente JSON acotado, cliente de Claude con el SDK oficial y errores de proveedor.
- `prospecting/discovery.py`: consultas, validación de URLs y respuestas de Tavily, selección de candidatos, identidad y exclusiones.
- `prospecting/qualification.py`: rúbrica, puntuación, prioridad, solicitud a Haiku y validación de su respuesta.
- `prospecting/pipeline.py`: reservas, llamadas a proveedores y persistencia del descubrimiento, la extracción, la identidad y la calificación.
- `config/veryfi.json`: catálogo provisional, perfiles y rúbrica versionada.
- `tests/`: pruebas de inicialización, contratos, persistencia, presupuesto, clientes, descubrimiento y calificación con datos sintéticos.
- `docs/provider-check.md`: registro de comprobaciones reales de acceso a proveedores.
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
