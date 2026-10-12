# Contratos y persistencia local

Abrir la pantalla no crea una base. Si ya existe, consulta el historial y los
resultados; preparar una campaña crea un borrador y la base si falta.
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
fechas. Una respuesta de Hunter consultada hoy no sustituye la fecha de verificación
del correo ni demuestra empleo vigente. La evaluación de estas condiciones está
descrita en [Personas y canales](contacts.md).

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

`data/provider-access.json` contiene `ProviderAccess`: cupos iniciales comprobados
y referencias de acceso. No contiene claves ni permisos. Cada ejecución crea
autorizaciones frescas después de abrir `Budget`; el consumo permanece en `Usage`
y sigue descontándose de los cupos al reiniciar. `session_state` solo mantiene
selección, filtros y estado visual. Este flujo no cambia el esquema SQLite ni
requiere migraciones.

La base se crea únicamente cuando la ruta no existe. Reabrir una base compatible
conserva checkpoints y uso; un esquema incompatible, incompleto o corrupto genera
un error, sin recrear tablas. No hay funciones de borrado ni migraciones
automáticas. Conserva la base y sus archivos auxiliares al cerrar la aplicación;
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
  JSON; el de contactos contiene los nombres de las clases `HaikuContacts`,
  `HaikuContactCandidate` y `CitedContactFact`.
- Claves de `RunItem.attempts`: `tavily_extract`, las de la ampliación de evidencia
  (`research:expansion`, `research:web_queries`, `research:pages`) y las de contactos
  (`contacts:person:`, `request:`, `processed:`, `haiku`, `haiku_request:`,
  `verify:`, `domain_search`, `web_queries`, `pages`, `extract`, `hunter_enrichments`).
- `Company.identity_key` (`dominio|nombre|países`), con índice único.
- Ids `uuid5` de contactos de Hunter (`hunter:<id>`), de contactos públicos
  (`public:<canal>`) y de la evidencia de exclusión.
- Marcadores de resultados de buscador, que nunca prueban un hecho: `claim` que
  empieza por `Tavily devolvió esta página` y `external_reference` que empieza
  por `contacts_search:`.
- Versiones: `discovery_queries_v1`, `research_queries_v1`, `haiku_assessment_v3`,
  `contacts_extraction_v1`, `rubric_v1` y el esquema SQLite `user_version=1`.
