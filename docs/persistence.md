# Contratos y persistencia local

Abrir la pantalla no crea una base. Si ya existe, consulta el historial y los
resultados; preparar una campaña crea un borrador y la base si falta.
La capa de datos puede utilizarse desde Python, sin Django ni claves:

```python
from pathlib import Path

from prospecting.contacts import load_contact_match
from prospecting.db import Database
from prospecting.models import Campaign, VeryfiConfig

config = VeryfiConfig.model_validate_json(
    Path("config/veryfi.json").read_text(encoding="utf-8")
)
config = config.model_copy(update={
    "contact_match": load_contact_match(Path("config/contact_match_v2.json")),
})
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
IDEA.md, la taxonomía de cargos `role_taxonomy_v1`, `rubric_v1`, la candidata
`rubric_v2` y los límites iniciales. No representa capacidades ni reglas
certificadas comercialmente. Cada campaña
conserva una instantánea de esta configuración; actualizar el archivo no cambia
campañas ya guardadas. V2 no es el valor predeterminado mientras no cumpla la
[condición de activación](Business-rules.md#candidata-enterprise-rubric_v2).

La taxonomía de cargos, sus fuentes y su estado de validación también forman parte
de esa instantánea. Cuando falta, la campaña conserva el comportamiento anterior;
no se reconstruyen casos de uso históricos a partir de productos o cargos. En las
evaluaciones nuevas, `profile_matches` guarda el `profile_id` y sus citas literales
con `evidence_id`; las referencias se verifican para la empresa y campaña. Si después
aparece una contradicción, la evaluación histórica se conserva y la pertinencia se
recalcula con la evidencia disponible para la campaña.

La preparación de campañas nuevas incorpora la configuración validada de
`contact_match_v2` en `config_snapshot.contact_match`. El ejemplo de bajo nivel la
incorpora explícitamente antes de guardar; `Database.save_campaign` no la añade.
La instantánea conserva pesos y versión, aunque después cambie el archivo de
configuración. El campo es opcional para leer campañas anteriores sin reescribirlas ni
modificar el esquema SQLite; ausente o `null` identifica la ruta histórica v1.

La instantánea identifica la generación de contactos mediante `people_provider`:
las campañas anteriores, sin ese campo, son históricas; las nuevas utilizan `apollo`.
Los contactos y referencias de Apollo y de la extracción pública nueva se aíslan de
los históricos, aunque la misma empresa se reutilice; la evidencia empresarial sin
contacto asociado permanece compartida. Las campañas históricas se
pueden consultar y exportar, pero no reanudar con Apollo. Si una permanece activa,
debe cerrarse explícitamente antes de crear otra. Esta separación no recrea la base
ni cambia el esquema SQLite; conserva resultados, procedencia y consumo anteriores.

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

`RunItem.consumed_limits` conserva el esfuerzo ya utilizado. `active_seconds`
acumula el tiempo activo de la empresa y `contacts_active_seconds` permite limitar
la etapa de contactos por separado. Este último campo es un número finito,
no negativo, con valor predeterminado `0.0`: las bases anteriores cuyo JSON no lo
incluye se leen sin recrear tablas ni migrar el esquema. Al guardar, ningún
contador ni tiempo consumido puede reducirse. El tiempo no se borra al reanudar.

Los contactos se guardan mediante `save_contact(contact, evidence=...)` con sus
referencias de nombre, cargo, empleo y canales. Una asociación laboral o un canal
incompleto permanece pendiente; persistirlos no los vuelve utilizables.
`employment_evidence_ids` prueba el vínculo laboral, mientras que cada canal
conserva su propia evidencia, estado original del proveedor, estado normalizado y
fechas. La fecha de consulta de un proveedor no sustituye la fecha de verificación
del correo ni demuestra empleo vigente. La evaluación de estas condiciones está
descrita en [Personas y canales](contacts.md). El estado de vigencia del empleo
(`employment_status`, T18) no se guarda: se recalcula al leer a partir de estas
referencias, así que no cambia el esquema ni los identificadores persistidos, y los
registros históricos de Hunter se leen sin volver a llamar al proveedor.

Al fusionar la misma persona se conservan fuentes, canales y advertencias
anteriores. Una verificación negativa no desaparece por una publicación o una
confirmación manual: requiere una observación posterior del proveedor y su
evidencia. El checkpoint de contactos conserva el resultado comercial separado
de `error_stage`, `error_message` y `stop_reason`; una interrupción técnica no
borra la calificación ni el consumo.

La revisión humana guarda `review_status` (`accepted`, `rejected` o `pending`),
`review_reason` y `reviewed_at` en el `RunItem` de esa campaña. No cambia la evaluación,
la rúbrica ni las referencias de evidencia. El estado comercial vigente que ve la
interfaz se recalcula al consultar y al pulsar la descarga, con una conexión nueva;
puede diferir del checkpoint si un canal o una fuente caducó. Una descarga no
reutiliza resultados precalculados ni se permite durante ejecución.

Confirmar un canal alternativo existente guarda una nueva `Evidence` con
`source_type="manual"`, la fecha y el motivo de confirmación del canal, y el `business_status`
recalculado del `RunItem` en una sola transacción. Si falla una escritura, se revierte
todo. Se conservan las fuentes, advertencias y verificaciones negativas; la
confirmación no demuestra identidad ni empleo por sí sola.

Confirmar manualmente el empleo (T23) guarda en una sola transacción:

- una nueva `Evidence` con `source_type="manual"`, `provider="manual_review"`, la URL
  consultada por ventas en `url`, la fecha en `retrieved_at`, el motivo en `claim` y
  persona, cargo y entidad en `excerpt`;
- su id añadido a `employment_evidence_ids` y, si se eligió otro cargo ya citado, ese
  `title`;
- el `business_status` recalculado del `RunItem`.

No cambia el esquema ni reescribe fuentes, contradicciones, `identity_status`,
`current_employment` ni datos del proveedor. Su vigencia y la resolución de un cambio de cargo
se calculan al leer ([Personas y canales](contacts.md#confirmación-manual-del-empleo-t23)).

`data/provider-access.json` contiene `ProviderAccess`: cupos iniciales comprobados
y referencias de acceso. No contiene claves ni permisos. Cada ejecución crea
autorizaciones frescas después de abrir `Budget`; el consumo permanece en `Usage`
y sigue descontándose de los cupos al reiniciar. La sesión firmada de Django solo
guarda el borrador de la campaña en preparación (`draft_id`); los filtros viajan en
la URL.

La base se crea únicamente cuando la ruta no existe. Una base v1 compatible se
migra transaccionalmente a v2 al abrirla: añade la columna JSON `profile_matches`
a `assessments` con `[]` para registros históricos. Reabrir una base compatible
conserva checkpoints y uso; un esquema incompatible, incompleto o corrupto genera
un error, sin recrear tablas. Una migración fallida se revierte. No hay funciones de
borrado. Conserva la base y sus archivos auxiliares al cerrar la aplicación;
contienen resultados y consumo que no deben descartarse.

La persistencia no calcula puntuaciones ni determina si un prospecto está listo.
El control de gasto corresponde a `Budget`. Mantener dos bases distintas no
coordina el presupuesto global.

## Identificadores persistidos

La reanudación y la deduplicación comparan valores ya guardados en SQLite.
Reorganizar código los conserva exactamente; cambiar uno es un cambio de
conducta, con su propia versión y aprobación. `tests/test_persisted_identifiers.py`
y las instantáneas de las pruebas del pipeline los fijan:

- `Usage.request_fingerprint`: SHA-256 de proveedor, operación, cuenta, query o
  payload, método, endpoint y cabeceras. El payload de Haiku incluye el esquema
  JSON; el de contactos v1 contiene los nombres de las clases `HaikuContacts`,
  `HaikuContactCandidate` y `CitedContactFact`, conservados para el historial.
  La búsqueda de descubrimiento envía
  `NON_BUSINESS_DOMAINS` en `exclude_domains`: ampliar esa lista cambia la huella, así que
  los directorios nuevos van en `LOCAL_NON_BUSINESS_DOMAINS`, que solo se aplica localmente.
  Las búsquedas Apollo con los filtros de la taxonomía producen huellas según su
  payload; un cambio en el catálogo que no altere la solicitud no fuerza otra llamada.
  Los payloads y huellas históricos se conservan.
- Claves de `RunItem.attempts`: `tavily_extract`, las de la ampliación de evidencia
  (`research:expansion`, `research:web_queries`, `research:pages`) y las de contactos
  (`contacts:person:`, `request:`, `processed:`, `haiku`, `haiku_request:`,
  `verify:`, `domain_search`, `web_queries`, `pages`, `extract`, `hunter_enrichments`).
  `verify:`, `domain_search` y `hunter_enrichments` son históricas de Hunter: ningún
  flujo nuevo las escribe, pero se conservan para leer las campañas anteriores.
- `Company.identity_key` (`dominio|nombre|países`), con índice único.
- Ids `uuid5` de contactos de Hunter (`hunter:<id>`), de contactos públicos
  (`public:<canal>`) y de la evidencia de exclusión.
- Marcadores de resultados de buscador, que nunca prueban un hecho: `claim` que
  empieza por `Tavily devolvió esta página` y `external_reference` que empieza
  por `contacts_search:`.
- Versiones: `discovery_queries_v1`, `discovery_queries_v2`, `icp_enterprise_v1`,
  `research_queries_v1`, `role_taxonomy_v1`, `haiku_assessment_v3`,
  `haiku_assessment_v4`, `haiku_assessment_v5`, `contacts_extraction_v1`,
  `contacts_extraction_v2`, `rubric_v1`, `rubric_v2`, `people_policy_v1`,
  `employment_corroboration_v1` y el esquema SQLite `user_version=2`.
  Las instantáneas sin taxonomía conservan los prompts v3/v4 según rúbrica y
  `contacts_extraction_v1`; las nuevas usan v5 y `contacts_extraction_v2` sin
  reinterpretar solicitudes ni evaluaciones históricas.

Estos valores de Hunter siguen identificando el historial y no se reinterpretan
como operaciones, contactos ni consumo de Apollo. La nueva ruta conserva sus propios
identificadores sin reescribir el ledger anterior:

- `people_provider="apollo"` en la instantánea de las campañas nuevas; el campo
  ausente identifica campañas históricas.
- `contact_match_v2` en `config_snapshot.contact_match` identifica los pesos y el
  algoritmo de match de las campañas nuevas; un campo ausente o `null` selecciona la
  lectura histórica `contact_match_v1`.
- Claves `contacts:apollo_search` y `contacts:apollo_enrichments` para los intentos
  de búsqueda y enriquecimiento; las claves compartidas mantienen su significado.
- Clave `contacts:apollo_rejected:<código>:<contact_id>` (T16) para una persona que
  People Enrichment no confirmó; su llamada queda procesada y no se repite. Desde T17 el
  código de entidad indica la condición que falló (`ENTITY_MISMATCH_CODES`:
  `entity_mismatch_no_organization`, `entity_mismatch_domain`, `entity_mismatch_organization_id`,
  `entity_mismatch_name`, `entity_mismatch_not_current`); `entity_mismatch` sigue identificando
  los rechazos anteriores. Las
  etapas de persona y los conteos por empresa no se guardan: se recalculan al leer.
- `uuid5(company_id, "apollo:<id>")` para candidatos Apollo y
  `uuid5(company_id, "public_apollo_v1:<valor_del_canal>")` para contactos públicos nuevos
  con correo o LinkedIn, separados de los identificadores históricos.
- Referencias `apollo_v1:<id>:<request_id>#<campo>` para hechos de Apollo y
  `apollo_public_v1:<request_id>#contact:<campo>` para hechos públicos de la generación
  nueva; conservan la procedencia y no convierten una búsqueda en verificación.
- La responsabilidad citada por `contacts_extraction_v2` usa
  `apollo_public_v1:<request_id>#contact:responsibilities:<source_id>` para enlazar
  la fuente original. La variante no Apollo usa el prefijo `public_extraction_v2`.
  Este sufijo solo identifica el nuevo hecho de responsabilidad; las demás
  referencias históricas mantienen su formato.
- Confirmación manual del empleo (T23): `external_reference` con el formato
  `manual-employment:<campaign_id>:<contact_id>:<fecha ISO>` y `provider="manual_review"`.
  `claim` empieza por `Empleo vigente confirmado manualmente por ventas, sin enviar mensajes,
  llamadas ni invitaciones. Motivo: ` seguido del motivo. Las reglas reconocen la confirmación
  y leen su motivo con estos valores.
- Corroboración dirigida del empleo (T24): `employment_corroboration_v1` en
  `config_snapshot.employment_corroboration` (ausente o `null`: sin la fase) y los topes
  `employment_queries` y `employment_pages` de `limits.effort`, ausentes en las instantáneas
  anteriores. Claves de `RunItem.attempts`:
  - `contacts:employment_queries`: búsquedas dirigidas de la empresa;
  - `contacts:employment_search:<contact_id>`: búsquedas que recibió la persona;
  - `contacts:employment_extract`: la extracción única de la fase;
  - `contacts:employment_fragment:<evidence_id>`: fragmento nuevo de esa extracción;
  - `contacts:employment_extracted:<contact_id>`: persona enviada a Haiku por la fase;
  - `contacts:employment_request:<request_id>`: solicitud de la fase, para medir su costo;
  - `contacts:employment_pending:<código>:<contact_id>`: `employment_search_limit` o el
    código del rechazo de Haiku.

  Las llamadas siguen usando `contacts:request:`, `contacts:processed:` y
  `contacts:haiku_request:`; la fase no escribe `contacts:haiku`.
- Fallos conciliados sin consumo (T17): una fila `RECONCILED`, `failed` y con créditos,
  costo y desembolso en cero admite un único reintento con `retry_of` en otra ejecución;
  la decisión se toma de esos valores persistidos, nunca del texto del error.

Fuera de SQLite, `data/provider-access.json` admite `ApolloAccess.rate_limits` (opcional;
sin él rigen los límites del plan Free) y los comprobantes de `data/conciliaciones/` usan el
formato `apollo_reconciliation_v1` ([budget-providers.md](budget-providers.md#conciliación-con-el-panel)).

El porcentaje de match de contactos no se guarda en SQLite: se recalcula al leer con
la versión y los pesos de la instantánea, o con `config/contact_match.json` para las
campañas anteriores sin instantánea de match ([Personas y canales](contacts.md#porcentaje-de-match)).
Las mismas entradas y fecha reproducen el resultado de cada versión; la evidencia y su
vigencia se vuelven a comprobar en la fecha de consulta. Los resultados y configuraciones
externas que no se guardaron en campañas anteriores no se pueden reconstruir con certeza.
Del mismo modo,
la calibración del ICP enterprise (`config/icp_enterprise.json`, `icp_enterprise_v1`) vive
versionada fuera de SQLite, y los campos adicionales de escala en `CompanySize`
(`public_revenue`, `geographic_coverage`, `scope`, `icp_tier`) tienen valores
predeterminados compatibles con los registros JSON ya persistidos.
