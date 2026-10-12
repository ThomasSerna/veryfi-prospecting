# Orquestación de campañas

`prospecting/pipeline/campaign.py` recorre una campaña completa desde Python: descubre
empresas, reúne evidencia, califica, amplía una vez la evidencia insuficiente y busca
contactos. Decide siempre con lo guardado en SQLite, así que repetir un clic, un rerun de
Streamlit o reanudar tras un cierre no duplica la campaña ni repite llamadas. Ninguna
función envía mensajes ni contacta a nadie.

La interfaz de Streamlit usa este mismo pipeline y esta misma base; su configuración
local, permisos y exportaciones se describen en [Interfaz local](ui.md).

## Invocación

La llamada presupone una base y un `Budget` abiertos, y permisos explícitos del responsable
del cupo registrados en esta sesión con `budget.authorize`. El ejemplo no concede permisos:
`session_authorizations` contiene solo los ya aprobados.

```python
from prospecting.identity import load_exclusions
from prospecting.pipeline import run_campaign, start_campaign
from prospecting.providers import ClaudeClient, ProviderClient
from prospecting.providers.hunter import HUNTER_OPERATIONS
from prospecting.providers.tavily import TAVILY_OPERATIONS

campaign, created = start_campaign(db, campaign)
client = ProviderClient(budget, [*TAVILY_OPERATIONS, *HUNTER_OPERATIONS])
report = run_campaign(
    db, budget, client, campaign.id,
    authorizations=session_authorizations,
    tavily_account_ref=tavily_account_ref,
    claude=ClaudeClient(budget), claude_account_ref=claude_account_ref, claude_funding_source="prepaid",
    hunter_access=hunter_access,                          # opcional
    exclusions=load_exclusions("data/exclusions.json"),  # opcional
    progress=print,                                       # opcional
)
```

- `start_campaign(db, campaign)` guarda la campaña como `running`. Si ya hay una campaña
  activa (`running` o `paused_budget`), o esa campaña ya existe, la devuelve con `created=False`
  sin crear otra.
- `run_campaign(...)` ejecuta o reanuda la campaña y devuelve `CampaignReport`: estado, motivo
  de parada, estado de la lista de exclusiones, informe de descubrimiento (solo cuando se
  ejecutó en esa llamada) y un `CompanyProgress` por empresa, con etapa, prioridad, resultado
  comercial, `stop_reason` y error. Si otra campaña está activa, no hace nada y devuelve
  `stop_reason="another_campaign_active"`. Una campaña `completed` no se vuelve a ejecutar.
  Mientras otra ejecución sigue en curso en el mismo proceso (por ejemplo, otra sesión de
  Streamlit), tampoco hace nada y devuelve `stop_reason="campaign_already_running"`.
- `close_campaign(db, campaign_id)` pasa una campaña `running` o `paused_budget` a `partial`.
  Conserva todos los datos y libera el lugar de campaña activa.
- `progress`, si se suministra, recibe un `CompanyProgress` después de que cada paso de una
  empresa queda guardado.

Cada proveedor se usa solo si se proporcionan su cuenta y su permiso: sin `claude` no se
califica y la campaña queda `partial` con `qualification_unavailable`; sin `hunter_access`
los contactos usan únicamente la ruta pública.

## Puente de la interfaz

Las funciones exportadas por `prospecting.pipeline` reciben la ruta de la base y los
IDs o contratos validados; abren y cierran SQLite dentro del pipeline. La interfaz no
crea clientes ni reserva gasto:

- `prepare_campaign(db_path, campaign)` guarda un borrador `created` sin tráfico y
  puede crear la base. Reutiliza una campaña activa o el mismo ID.
- `list_saved_campaigns(db_path)` devuelve el historial; una base ausente da una lista
  vacía. `read_campaign(...)` devuelve `CampaignView`, con presupuesto, evidencia,
  evaluaciones y contactos, y recalcula disponibilidad y canales utilizables a la
  fecha de consulta. Consultar no crea una base ni cambia los datos.
- `execute_campaign(db_path, campaign_id, access=..., approvals=...)` crea un `Budget`
  con los cupos comprobados, registra permisos frescos de `AuthorizationInput` y
  ejecuta la misma orquestación que `run_campaign`, bajo la misma guarda de ejecución.
  Un archivo de acceso no concede autorización de gasto.
- `finish_campaign(...)` cierra conservando datos; `review_company(...)` guarda estado,
  motivo y fecha sin recalificar; `confirm_alternative_channel(...)` añade evidencia
  manual y recalcula disponibilidad de forma atómica, sin llamar a proveedores.

Las correcciones y el cierre están bloqueados mientras la ejecución sigue activa en
el proceso. Las APIs anteriores desde Python se conservan.

## Orden de trabajo

1. **Descubrimiento**, solo si la campaña aún no tiene empresas
   ([Descubrimiento](discovery.md)).
2. **Análisis inicial** de cada empresa: extrae hasta `effort.initial.pages` páginas del
   propio dominio que el buscador ya localizó y, si queda cupo, la portada con el host
   observado. No vuelve a extraer páginas leídas dentro de `cache.web_days`. Después resuelve
   identidad y deja la empresa en la etapa `researched`.
3. **Calificación** de todas las empresas. Si el resultado es `insufficient_evidence`, se
   amplía la evidencia una sola vez (`research_company`) y se recalifica. No se amplía
   cuando la identidad espera revisión humana (`exclusion_review` o `duplicate_review`).
   `excluded`, `low_fit` e `insufficient_evidence` tras la ampliación cierran la empresa.
4. **Contactos**: primero las empresas `high` y después las `medium`, por encaje descendente
   ([Personas y canales](contacts.md)). La empresa se cierra con el resultado comercial
   derivado.

Una empresa cerrada queda en la etapa `completed` con su `business_status` y su `stop_reason`.

## Límites de tiempo

- **Por empresa**, antes de contactos: `effort.initial.active_seconds` para el análisis
  inicial y la primera calificación, más `effort.insufficient_evidence.active_seconds` con la
  ampliación. Se cuentan con `active_seconds − contacts_active_seconds`; la etapa de
  contactos aplica su propio cupo.
- **Por campaña**: `limits.active_seconds` (45 minutos iniciales) menos el tiempo ya
  registrado por sus empresas. Al agotarse, la ejecución se detiene con
  `campaign_time_limit` y la campaña queda `partial`.

El tiempo de cada etapa se suma a `RunItem.consumed_limits.active_seconds` aunque falle. El
tiempo del descubrimiento solo cuenta dentro de la sesión que lo ejecuta.

## Parada y estado de la campaña

- **Presupuesto o autorización** (`budget_exceeded`, `authorization_required`,
  `authorization_exceeded`, `price_unbounded`, `account_*`…): la campaña pasa a
  `paused_budget` y se detiene sin más tráfico. Reanudar exige otra sesión de `Budget` con
  cupo o permisos nuevos. Si la reserva solo supera el tope de una empresa, `Budget` lo
  informa como `company_budget_exceeded`: esa empresa se detiene y las demás continúan; en
  contactos se cierra con el resultado comercial derivado (por ejemplo, `qualified_no_contact`).
- **Proveedor no disponible** (`permission_denied`, `quota_exceeded`, `rate_limited`, error
  local, HTTP 401/403/429 de Haiku): se detiene la pasada en curso. La empresa conserva su
  etapa, `stop_reason` y el mensaje literal del error.
- **Fallos de una empresa** (timeout, respuesta inválida, salida de Haiku no válida): la
  empresa queda pendiente con su motivo y las demás continúan. Una llamada enviada sin
  resultado guardado no se repite: requiere revisión y conciliación.

Estados finales: `completed` si todas las empresas están cerradas; `partial` si alguna quedó
pendiente o se agotó el tiempo global; `paused_budget` por presupuesto o autorización;
`failed` si el descubrimiento no dejó empresas por errores o ante una excepción inesperada,
que se relanza. Una interrupción (por ejemplo, cerrar la aplicación) deja la campaña
`running`; `start_campaign` la devuelve y `run_campaign` la reanuda.

## Limitaciones

- `Campaign` no guarda un motivo de parada propio: el motivo está en `CampaignReport` y en el
  `stop_reason` de cada empresa.
- Las consultas de descubrimiento omitidas por una parada no se reintentan al reanudar.
- No hay reintentos automáticos: un segundo intento exige conciliar antes el fallo
  ([Presupuesto y proveedores](budget-providers.md)).
- El procesamiento es secuencial e interactivo; no continúa en segundo plano al cerrar la
  aplicación.
- La guarda de ejecución única es por proceso: dos procesos distintos sobre la misma base
  no se coordinan entre sí.
- El descubrimiento guarda las empresas al terminar. Si se interrumpe a mitad, al reanudar
  las búsquedas ya enviadas no se repiten y sus resultados aún no persistidos se pierden.
  La primera huella repetida produce `duplicate_request`, omite las consultas restantes
  y termina `failed` si no hay empresas. El ledger y las reservas se conservan; la interfaz
  explica esta limitación y no fabrica resultados.
- Las pruebas sin red cubren interrupción de descubrimiento, tiempo acumulado al reanudar,
  excepción inesperada con checkpoints conservados y guarda liberada, y campaña completa
  con `HunterAccess` sintético. No demuestran acceso real ni contactabilidad comercial.
- El [registro de proveedores](provider-check.md) documenta una campaña real del
  2026-10-12, incluida ampliación con `include_domains`, que terminó `completed` desde
  Python. Sus resultados comerciales fueron `insufficient_evidence` y
  `qualified_no_contact`: ninguna persona quedó lista. La interfaz y su puente se
  verifican con datos sintéticos, sin una nueva campaña real.
