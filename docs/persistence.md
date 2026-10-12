# Contratos y persistencia local

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

La base se crea únicamente cuando la ruta no existe. Reabrir una base compatible
conserva checkpoints y uso; un esquema incompatible, incompleto o corrupto genera
un error, sin recrear tablas. No hay funciones de borrado ni migraciones
automáticas. Conserva la base y sus archivos auxiliares al cerrar la aplicación;
contienen resultados y consumo que no deben descartarse.

La persistencia no calcula puntuaciones ni determina si un prospecto está listo.
El control de gasto corresponde a `Budget`. Mantener dos bases distintas no
coordina el presupuesto global.
