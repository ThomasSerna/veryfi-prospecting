# Personas y canales profesionales

La búsqueda utiliza Hunter para personas y correos, y Tavily para localizar o
contrastar información pública. `prospecting.contacts` construye solicitudes,
valida respuestas y deriva estados mediante funciones sin red ni persistencia.
`prospecting.pipeline` reserva gasto, llama proveedores y guarda resultados. No
hay envío de mensajes, llamadas comerciales, secuencias ni sincronización de
contactos a otra plataforma. Apollo y X-Ray Search no están habilitados.

## Entrada y flujo

`find_contacts(db, budget, client, campaign_id, company_id, *, hunter_access=None,
authorizations=None, tavily_account_ref=None, claude=None, claude_account_ref=None,
claude_funding_source="prepaid", deadline=None)` investiga una empresa ya guardada
y vinculada a la campaña, con dominio/entidad confirmados y evaluación seleccionada
de prioridad `medium` o `high`. Sin esas precondiciones devuelve `skipped`, sin
investigación adicional. El `deadline`, cuando se suministra, es un plazo absoluto
de `time.monotonic()`; siempre se aplica además el tiempo restante de contactos
de la campaña.

El orden de trabajo es:

1. Reutilizar personas, canales y evidencia guardados. Si ya existe un canal
   preferido utilizable, terminar sin nuevas llamadas.
2. Consultar Domain Search sobre el dominio confirmado, primero por cargos y,
   si queda un segundo intento, por departamentos relacionados. `type="personal"`
   significa un correo nominal del dominio profesional; las direcciones genéricas
   no cuentan como canal de una persona. Cada consulta pide como máximo 10 resultados,
   con `offset=0`, sin recorrer páginas.
3. Complementar con búsquedas y extracción de URLs públicas mediante Tavily,
   dentro del cupo. Si se proporcionó Haiku y su autorización, extraer hechos
   nominales citados de evidencia nueva o ya disponible. Las páginas de LinkedIn
   no se automatizan.
4. Sobre candidatos cuya identidad, cargo y empleo son pertinentes y vigentes,
   usar Finder solo si falta correo profesional. Enviar nombre completo observado
   y dominio confirmado; no construir direcciones por patrón ni solicitar correos privados.
5. Reutilizar la verificación vigente o la publicación nominal corporativa.
   Verifier se consulta únicamente si el correo todavía necesita comprobación,
   queda cupo y la operación está habilitada. Un 202 deja la ejecución pendiente;
   no hay polling automático.
6. Guardar contactos y evidencia con cada resultado, conservar el consumo y
   detenerse al primer correo, teléfono o WhatsApp profesional utilizable.

La prioridad media permite 1 persona, 1 búsqueda Hunter, hasta 1 enriquecimiento
Hunter, 2 consultas web, 2 páginas y 90 segundos adicionales. La alta permite
hasta 3 personas, 2 búsquedas Hunter, 3 enriquecimientos, 4 consultas web, 4 páginas
y 180 segundos. Finder y Verifier comparten el cupo de enriquecimientos; una
verificación también incrementa su contador específico. El máximo inicial es una
verificación por canal. Las reducciones de configuración y los límites económicos
siguen vigentes; esos máximos no obligan a agotarlos.

`ContactReport` devuelve `status` (`checked`, `already_checked`, `pending` o
`skipped`), `business_status`, identificadores de contactos, evidencias y solicitudes,
`stop_reason`, `error_message` y `warnings`. Un rerun recupera el resultado guardado;
una solicitud enviada con resultado faltante o consumo incierto exige revisión y
no se repite. Las cachés de resultados usan inicialmente 7 días para web y 30 para
contactos; reutilizar no vuelve actual una verificación ni un empleo caducados.

## Acceso a Hunter

`HunterAccess` recibe `search_account_ref`, `verification_account_ref`,
`enabled_operations`, `unified_credits`, `automatic_lead_saving_disabled`,
`funding_source`, `source_reference` y `checked_at`. Es un registro de comprobación;
la presencia de `HUNTER_API_KEY` no demuestra acceso ni autoriza una llamada.
El saldo inicial y su valoración pertenecen a `AccountAllowance`; cada permiso
pertenece a la sesión de `Budget` que lo registró.

Usar una referencia canónica por saldo real. Domain Search y Finder comparten la
cuota de búsqueda. Con créditos unificados, Verifier usa la misma referencia;
con cuotas separadas, necesita una referencia distinta para verificación.
Los permisos deben corresponder a la operación y referencia exactas. No reutilizar
cuotas o autorizaciones de una sesión anterior. Véase
[Presupuesto y proveedores](budget-providers.md).

Las únicas operaciones Hunter son `domain_search`, `email_finder` y
`email_verifier`, con Bearer en cabecera. Sus modelos Pydantic validan los campos
utilizados e ignoran campos externos nuevos. Los nombres incompletos, fechas
ausentes o fuentes insuficientes quedan pendientes; no se completan con IA.

Finder y Verifier necesitan comprobar previamente
`automatic_lead_saving_disabled=True`. El
[OpenAPI de Hunter](https://hunter.io/openapi.json) describe guardado automático
de leads, desactivable en la cuenta. El módulo no modifica ese ajuste. Sin su
comprobación, esas operaciones no se habilitan.

La invocación siguiente presupone una base y un `Budget` abiertos, una empresa
calificada y los registros de acceso/cupos comprobados. `session_authorizations`
contiene exclusivamente los objetos que corresponden a permisos explícitos del
responsable en esta sesión, ya registrados mediante `budget.authorize`; este
ejemplo no crea ni concede autorizaciones. Cada proveedor opcional solo se usa
si se proporciona su cuenta y el permiso correspondiente.

```python
from prospecting.contacts import HUNTER_OPERATIONS
from prospecting.pipeline import find_contacts
from prospecting.providers import ClaudeClient, ProviderClient
from prospecting.providers.tavily import TAVILY_OPERATIONS

client = ProviderClient(budget, [*HUNTER_OPERATIONS, *TAVILY_OPERATIONS])
report = find_contacts(
    db, budget, client, campaign_id, company_id,
    hunter_access=hunter_access,
    authorizations=session_authorizations,
    tavily_account_ref=tavily_account_ref,
    claude=ClaudeClient(budget),
    claude_account_ref=claude_account_ref,
    claude_funding_source="prepaid",
)
```

## Validación de personas y canales

Una persona utilizable tiene nombre completo, entidad confirmada, cargo respaldado,
función pertinente y empleo vigente sin contradicciones pendientes. Los cargos
proceden de los perfiles de la campaña y de la evaluación seleccionada. Un título
o el indicador de autoridad del proveedor no asignan automáticamente un papel de
compra; `buying_role` permanece `unknown` sin respaldo específico.

Hunter proporciona candidatos y fuentes del correo. Las fechas `extracted_on`,
`last_seen_on` y `verification.date` se conservan con su significado; ninguna se
convierte en fecha del puesto. Para validar empleo se necesita evidencia fechada
dentro de 180 días o un directorio corporativo actual consultado dentro de la
caché web de 7 días. Una fuente sin vigencia estimable exige revisión. Estos son
valores iniciales del prototipo, reducidos según la configuración guardada de
la campaña.

La extracción pública usa `contacts_extraction_v1` con el mismo Haiku que la
calificación. Cada hecho cita un `evidence_id` suministrado y una cita literal
asociada nominalmente a la persona. Python rechaza referencias inexistentes,
resúmenes del buscador usados como prueba, citas ajenas al fragmento y homónimos
ambiguos. Los candidatos incompletos conservan sus hechos conocidos como pendientes.
Si una fuente contrasta el cargo o la entidad de una persona ya guardada, conserva
ambas evidencias, marca la identidad como contradictoria y suspende listo, sin
reasignar la empresa. El contenido externo no puede
cambiar instrucciones, presupuesto ni condición de listo.

- **Email:** asociación nominal y dominio laboral, con verificación `valid` de
  hasta 30 días; también puede servir la publicación nominal corporativa vigente
  sin verificación negativa. La publicación no garantiza entregabilidad.
- **Estados:** se conservan el original y `verified`, `published_professional`,
  `accept_all`, `unknown`, `invalid` o `manual_confirmed`. `accept_all` y `unknown`
  necesitan otro respaldo utilizable. `invalid` bloquea el canal hasta resolverse
  mediante una observación posterior del proveedor; no lo borra una confirmación manual.
- **Teléfono:** número laboral directo o extensión nominal con país y formato
  comprobados. El formato no garantiza que atienda. No se infiere WhatsApp desde un móvil.
- **WhatsApp:** publicación profesional que anuncie explícitamente ese canal para
  la persona. Una central genérica queda fuera.
- **LinkedIn y otros:** identidad y empleo comprobados, además de confirmación
  manual de acceso directo, con su evidencia. Una URL aislada no basta.

`validate_contact`, `channel_is_usable` y `derive_readiness` aplican estas reglas
sin depender del proveedor. `ready_preferred` necesita correo, teléfono o WhatsApp
utilizable; `ready_alternative`, un canal alternativo confirmado. Un canal pendiente
produce `needs_channel_confirmation`; al agotarse el esfuerzo sin persona/canal
utilizable, `qualified_no_contact`. Los fallos técnicos se registran aparte.

No se ejecutaron llamadas reales a Hunter durante esta implementación. Las pruebas
sin red usan credenciales y datos declarados sintéticos; no demuestran cobertura,
acceso ni consumo de la cuenta del equipo. La clave pública `test-api-key` devuelve
datos ficticios y no sirve para una demostración de prospectos reales.

Los teléfonos se comprueban automáticamente solo para prefijos y longitudes de
Colombia/México; otros formatos necesitan revisión. El registro no almacena cuerpos
HTTP: si se pierde una respuesta enviada antes del checkpoint, conserva el gasto
y requiere revisión. Las solicitudes inciertas tampoco se repiten al crear otra campaña.
