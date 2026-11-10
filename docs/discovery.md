# Descubrimiento e identidad de empresas

## Descubrimiento y extracción con Tavily

Las etapas de `prospecting.pipeline` son las únicas que reservan consumo y llaman a Tavily.
`prospecting/discovery.py` construye consultas y selecciona candidatos;
`prospecting/providers/tavily.py` define las operaciones, valida respuestas y clasifica
errores; `prospecting/identity.py` resuelve identidad y exclusiones. Ninguno de los tres
hace red ni usa la base de datos. Las funciones que llaman a Tavily admiten solamente
crédito gratuito (`funding_source="free_credit"`, USD 0 por llamada) y exigen un
`SpendingAuthorization` registrado para la operación `search` o `extract`:

```python
import time

from prospecting.pipeline import extract_company_pages, run_discovery
from prospecting.providers import ProviderClient
from prospecting.providers.tavily import TAVILY_OPERATIONS

client = ProviderClient(budget, TAVILY_OPERATIONS)
report = run_discovery(db, budget, client, campaign.id, account_ref="cuenta-tavily",
                       authorization=search_grant, deadline=time.monotonic() + 60)
pages = extract_company_pages(db, budget, client, campaign.id, report.selected_company_ids[0],
                              urls, account_ref="cuenta-tavily", authorization=extract_grant)
```

`run_discovery` genera consultas de plantilla (`discovery_queries_v2` en campañas con
`people_provider="apollo"` y `discovery_queries_v1` en campañas históricas) solo para los
países y segmentos de la campaña, con un máximo de 8 consultas `basic` de 10
resultados cada una, y aplica el tope de 60 candidatos brutos. Agrupa los resultados
por host exacto y selecciona hasta `max_companies`, intentando
`target_per_country_segment` por combinación; si una combinación no alcanza esa meta,
el informe lo indica en lugar de rellenarla. Guarda en una sola transacción, para cada
candidato seleccionado, `Company`, `Evidence` y `RunItem` en la etapa `discovered`;
el resto de candidatos solo aparece en el informe. Si la campaña ya tiene empresas
guardadas, la función no vuelve a llamar.

### Filtro local y lectura de identidad (T26, `discovery_policy_v2`)

Las instantáneas con `config_snapshot.discovery_policy` (ausente o `null`: conducta anterior)
aplican, después de la búsqueda y sin cambiar el payload enviado a Tavily ni su huella:

- **Descarte `non_business_site`:** hosts de `non_business_domains` (portales de contenido,
  directorios, bolsas de empleo, marketplaces) y subdominios de contenido (`blog.`, `noticias.`…)
  no se convierten en candidatas. El conteo aparece en `DiscoveryReport.discarded`.
- **Medios, eventos y competidores (tras el lote de T30):** también es `non_business_site` un host
  cuyo nombre contiene un marcador de medio (`media_domain_markers`: `news`, `noticias`, `revista`…);
  la lista incluye medios de negocios, plataformas de eventos y organismos multilaterales observados.
  Un proveedor de OCR/IDP que compite con Veryfi (`competitor_domains`) se descarta con
  `competitor_vendor`.
- **Señal local (tras el lote de T30):** con `local_markers`, en la selección van primero las
  candidatas cuyo resultado sugiere operación en el país de su consulta: ccTLD de ese país o un lugar
  suyo (Colombia, Bogotá, CDMX, Monterrey…) en el título o el fragmento. Es solo un orden: no excluye
  ni confirma el país, que sigue dependiendo de la identidad. Las demás quedan como reservas.
- **Dominios de otro país:** un sufijo de país ajeno a la campaña (`.es`, `.com.pe`) no se
  excluye, porque un ccTLD extranjero solo añade una advertencia ([Business-rules.md](Business-rules.md#identidad-y-exclusiones)).
  En la selección va detrás de las candidatas locales de su combinación, así que solo ocupa
  plaza cuando faltan locales. Los sufijos de uso genérico (`.co`, `.io`, `.ai`…) no cuentan
  como país.
- **Páginas iniciales:** la portada y las páginas propias de «nosotros» o «contacto» van
  primero, dentro del mismo tope de páginas.
- **Consulta de Extract:** la extracción inicial reordena los fragmentos con el nombre inferido,
  «quiénes somos», «contacto» y los países, seguidos de las señales de los perfiles.

Las listas son propuestas pendientes de validación, tomadas de las paradas por identidad de
los lotes reales de T17 y T24.

**Reservas (T27):** con la política, el descubrimiento continúa la misma selección más allá de
`max_companies` y guarda hasta `max_companies` candidatas de reserva en `discovery_reserves`,
sin las cuentas con revisión de exclusión pendiente. `DiscoveryReport.reserves` informa cuántas
se guardaron. Cuando una empresa termina por identidad, la orquestación promueve la siguiente
reserva en el orden de selección ([Orden de trabajo](campaign.md#orden-de-trabajo)).

Límites actuales frente a IDEA §7.1: las consultas son siempre de plantilla, porque
Haiku no reformula consultas aunque falten resultados. El informe con las
combinaciones que no alcanzaron la meta (`DiscoveryReport.combinations`) y los
candidatos descartados por exclusión vive solo en memoria: la interfaz muestra el
motivo de parada, no ese detalle. Lo que persiste es el `RunItem` de cada empresa
seleccionada y la evidencia que la localizó.

Cada empresa queda con identidad `pending`, nombre inferido (evidencia `inference`)
y dominio respaldado por los resultados observados. País de operación y segmento
quedan desconocidos. La evidencia guarda la URL, `provider="tavily"`, la referencia
de la solicitud, el fragmento acotado del buscador y `retrieved_at`.
El fragmento del buscador solo localiza la fuente. En `discovery_queries_v2`,
`select_candidates` prioriza dentro de cada combinación país/segmento los candidatos cuyos
títulos y fragmentos combinan señales documentales y señales corporativas/enterprise frente
a micrositios promocionales o conglomerados sin caso de uso documental, y
`compare_discovery_versions` permite comparar de forma reproducible `v1` frente a `v2` sin
depender de llamadas ni proveedores adicionales.

La calibración del ICP enterprise vive versionada en `config/icp_enterprise.json`
(`icp_enterprise_v1`, cargada con `load_icp_enterprise`), con estado de validación y
autorización de uso `pending`, niveles contiguos `tier_1`/`tier_2`/`tier_3` tomados de
*How Veryfi Sells*, ejemplos positivos y negativos por segmento, cargos de referencia
(`business_champion`, `technical_champion`, `economic_buyer`), política de muestra
independiente y verificación de cobertura frente a exclusiones
(`uncovered_reference_customers`).

`extract_company_pages` valida cada URL: solo admite HTTP(S) hacia nombres públicos
y rechaza IP, `localhost`, credenciales, puertos no estándar, redes sociales y
dominios de gobierno. Respeta el cupo de páginas de `effort.initial`, menos las ya
consumidas (solo cuentan las de solicitudes enviadas al proveedor), y guarda hasta
3 fragmentos de 800 caracteres como máximo por página.
Un fragmento cuenta como fuente `primary` solo si la página pertenece al dominio de
la empresa. Las URLs que Tavily no pudo extraer no generan evidencia.

`research_company(db, budget, client, campaign_id, company_id, account_ref=...,
authorizations=...)` amplía una sola vez la evidencia de una empresa
(`limits.evidence_expansions_per_company`) con el esfuerzo `insufficient_evidence`: una
búsqueda `basic` restringida al dominio de la empresa (`include_domains`, consulta de plantilla
`research_queries_v1` con su nombre, las señales de sus segmentos y los países de la campaña) y
la extracción de hasta 2 páginas propias aún no leídas, primero las que acaba de localizar.
Los resultados de esa búsqueda se guardan como resultados de buscador: solo localizan
páginas. Cada paso guarda su intento (`research:expansion`, `research:web_queries`,
`research:pages`) y suma los límites consumidos; una llamada enviada cuenta aunque falle y
reanudar continúa la misma ampliación sin repetirla. Sin páginas nuevas termina con
`no_new_sources`, sin llamar. La función no cambia la prioridad: después se resuelve la
identidad y se recalifica ([Orquestación de campañas](campaign.md)).

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

Además, `assess_identity` y `resolve_company_identity` extraen de forma determinista sobre
evidencia observada:
- **Estructura societaria (`entity_name`, `entity_type`, `parent_company_id`):** distingue
  razón social (`legal_entity`), filial (`subsidiary`) y marca (`brand`) a partir de
  menciones explícitas ancladas al sujeto de la empresa en páginas primarias (descartando
  menciones de clientes/terceros o nombres genéricos de país/sector), vinculando
  `parent_company_id` cuando la matriz ya está confirmada o registrando una advertencia para
  mantener matriz y filial/marca separadas.
- **Señales de escala (`CompanySize`):** extrae empleados o rangos, ingresos públicos
  (`public_revenue`) y cobertura geográfica (`geographic_coverage`) junto con el alcance de la
  frase donde aparece la cifra (`scope`: `group`, `subsidiary`, `country`, `entity` o
  `unknown` cuando no hay marcador explícito), nivel (`icp_tier`: `tier_1`, `tier_2`,
  `tier_3`, `unknown`) y `evidence_ids`. El nivel solo se asigna cuando el intervalo completo
  cae en el mismo nivel, la moneda de ingresos es explícitamente USD (sin convertir `$` local
  ni unidades ambiguas como «billones»), no hay discrepancia entre empleados e ingresos y una
  cifra de grupo no se aplica a una filial o marca. Nunca usa fragmentos de búsqueda ni
  inventa estimaciones: cuando la escala no consta en fuentes primarias o de proveedor,
  `company.size` permanece en `None`.
