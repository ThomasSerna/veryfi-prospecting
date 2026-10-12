# Descubrimiento e identidad de empresas

## Descubrimiento y extracción con Tavily

Las etapas de `prospecting.pipeline` son las únicas que reservan consumo y llaman a Tavily.
`prospecting/discovery.py` construye consultas y selecciona candidatos;
`prospecting/providers/tavily.py` define las operaciones, valida respuestas y clasifica
errores; `prospecting/identity.py` resuelve identidad y exclusiones. Ninguno de los tres
hace red ni usa la base de datos. Ambas funciones admiten solamente crédito
gratuito (`funding_source="free_credit"`, USD 0 por llamada) y exigen un
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
