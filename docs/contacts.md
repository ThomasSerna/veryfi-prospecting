# Personas y canales profesionales

La búsqueda utiliza Apollo para personas y correos, y Tavily para localizar o
contrastar información pública. `prospecting.providers.apollo` construye las
solicitudes de Apollo y convierte sus respuestas; `prospecting.contact_extraction`
prepara la extracción con Haiku y valida sus citas; `prospecting.contacts` aplica las
reglas de persona, canal y listo, independientes de la fuente. Los tres son funciones
sin red ni persistencia.
`prospecting.pipeline` reserva gasto, llama proveedores y guarda resultados. No
hay envío de mensajes, llamadas comerciales, secuencias ni sincronización de
contactos a otra plataforma. X-Ray Search no está habilitado.

## Entrada y flujo

`find_contacts(db, budget, client, campaign_id, company_id, *, apollo_access=None,
authorizations=None, tavily_account_ref=None, claude=None, claude_account_ref=None,
claude_funding_source="prepaid", deadline=None)` investiga una empresa ya guardada
y vinculada a la campaña, con dominio/entidad confirmados y evaluación seleccionada
de prioridad `medium` o `high`. Sin esas precondiciones devuelve `skipped`, sin
investigación adicional. El `deadline`, cuando se suministra, es un plazo absoluto
de `time.monotonic()`; siempre se aplica además el tiempo restante de contactos
de la campaña.

El orden de trabajo es:

1. Reutilizar personas, canales y evidencia de la generación Apollo. Las campañas sin
   política de varias personas terminan si ya existe un canal preferido utilizable;
   las que tienen política comprueban además el objetivo de personas y funciones.
2. Consultar People API Search sobre el dominio confirmado y con cargos específicos
   de los casos de uso respaldados. Se agrupan cargos con seniority inequívoco y
   especialistas o jerarquías ambiguas sin ese filtro, hasta dos consultas. Cada
   consulta pide como máximo 10 candidatos en la primera página. Search no devuelve
   correo ni teléfono; sus nombres pueden ser parciales y permanecen pendientes.
3. Enriquecer selectivamente los candidatos pertinentes con un identificador observado
   de Apollo, autorización y cupo. People Enrichment no solicita emails personales,
   teléfonos ni waterfall. No completar apellidos con IA ni construir direcciones.
4. Complementar con búsquedas y extracción de URLs públicas mediante Tavily,
   dentro del cupo. Si se proporcionó Haiku y su autorización, extraer hechos
   nominales citados de evidencia nueva o ya disponible. Las páginas de LinkedIn
   no se automatizan.
5. Comprobar independientemente identidad, empresa actual, cargo, vigencia y canal.
   Una fecha de consulta no es una fecha de verificación: un correo sin esta fecha
   permanece pendiente salvo publicación nominal corporativa vigente.
6. Guardar contactos y evidencia con cada resultado y conservar el consumo. Con
   `people_policy_v1`, seguir enriqueciendo hasta el objetivo de personas pertinentes
   o el tope (ver [Varias personas por cuenta](#varias-personas-por-cuenta-t16)). Las
   instantáneas sin esa política se detienen al primer correo, teléfono o WhatsApp
   profesional utilizable.

Todos los candidatos devueltos se guardan con su procedencia, también los que
superan el cupo. En campañas con taxonomía, la pertinencia se calcula en una copia:
un cargo claramente fuera del perfil resulta `relevant_function=False` y uno
ambiguo sin respaldo de función queda `None`. Ninguno es elegible. El cupo de personas
(`contacts:person:`) solo lo ocupa quien supera `validate_contact` al investigarla,
así un candidato poco pertinente hallado primero no desplaza a uno idóneo hallado
después. En campañas con `contact_match_v2`, la pertinencia y el match ordenan los
candidatos; solo a igualdad de ambas se alternan funciones. Se excluyen del
enriquecimiento las personas descartadas por identidad, empleo o alcance, pero las
que tienen datos pendientes siguen siendo investigables. Las búsquedas nominales en
la web omiten a quien ya se sabe fuera del perfil. Esta selección no amplía topes:
consultas, páginas y enriquecimientos siguen contándose igual y las llamadas hechas
no se recuperan.

La prioridad media permite hasta 3 personas, 2 búsquedas Apollo, 3 enriquecimientos
Apollo, 2 consultas web, 2 páginas y 90 segundos adicionales. La prioridad alta permite
hasta 5 personas, 2 búsquedas Apollo, 5 enriquecimientos, 4 consultas web, 4 páginas
y 180 segundos. Las campañas guardadas antes de T16 conservan sus topes (media 1/1,
alta 3/3). Las reducciones de configuración y los límites económicos siguen
vigentes; esos máximos no obligan a agotarlos.

### Varias personas por cuenta (T16)

`config/veryfi.json` define `people_policy` (`people_policy_v1`, pendiente de
validación comercial): objetivo de 2 personas pertinentes en media y 3 en alta, y
`min_functions=2`. La configuración exige la taxonomía de cargos, Apollo y que cada
objetivo no supere el tope de personas del nivel; si la campaña reduce ese tope, el
objetivo baja con él. Las instantáneas sin `people_policy` conservan la parada
anterior.

`person_stage` y `people_progress` (`prospecting.contacts`) clasifican a cada persona
al leer: `candidate`, `identity_verified`, `relevant`, `channel_usable` o `ready`
([Etapas de persona](Business-rules.md#etapas-de-persona)). Una persona pertinente
tiene identidad confirmada con nombre completo, función pertinente, empleo no
contradicho y alcance compatible; no necesita canal ni `corporate_evidence`, que siguen
siendo requisitos de `ready`. `function_ids` agrupa las pertinentes por el
`function_id` de su familia de cargos.

Con política, la etapa de contactos:

- ocupa el cupo `contacts:person:` como antes, pero un canal preferido ya no la termina;
- omite People Search si el objetivo ya se cumple con datos vigentes;
- comprueba el objetivo antes de cada enriquecimiento. Con v2 ordena por pertinencia y
  match y, a igualdad de ambos, favorece funciones distintas; las campañas anteriores
  conservan su orden. Si hay personas suficientes de una sola función y queda un
  candidato viable de otra por intentar, solo enriquece candidatos de otras funciones;
- registra un rechazo de identidad o entidad de People Enrichment (`identity_unconfirmed`,
  `identity_mismatch`, `entity_mismatch`) como resultado procesado con la clave
  `contacts:apollo_rejected:<código>:<contact_id>`. Desde T17 el rechazo de entidad guarda
  la primera condición que falla, en este orden: `entity_mismatch_no_organization` (sin
  organización actual), `entity_mismatch_domain` (otro dominio principal),
  `entity_mismatch_organization_id` (organización contradictoria), `entity_mismatch_name`
  (nombre distinto) o `entity_mismatch_not_current` (sin empleo actual en esa organización).
  Solo se guarda el código, sin datos de la respuesta; los rechazos anteriores conservan
  `entity_mismatch`. La persona queda candidata con su
  motivo, la etapa continúa y la llamada no se repite al reanudar. Sin política, ese
  rechazo sigue dejando la empresa pendiente;
- ejecuta después la búsqueda y extracción públicas dentro de sus cupos;
- termina con `people_target_reached`, `enrichment_limit` (tope agotado sin objetivo) o
  `contact_plan_exhausted`.

No hay paginación: siguen dos búsquedas de hasta 10 candidatos. Cada enriquecimiento
reserva su crédito antes de llamar y respeta permisos, cupos de cuenta, topes de
campaña y empresa y el tiempo de contactos. Una cuenta alta puede usar hasta 7
llamadas a Apollo (2 búsquedas y 5 enriquecimientos), frente a los 200 por hora
publicados del plan Free. Las pruebas son sintéticas: el rendimiento con datos
reales queda por medir en T17/T21.

`ContactReport` devuelve `status` (`checked`, `already_checked`, `pending` o
`skipped`), `business_status`, identificadores de contactos, evidencias y solicitudes,
`stop_reason`, `error_message` y `warnings`. Un rerun recupera el resultado guardado;
una solicitud enviada con resultado faltante o consumo incierto exige revisión y
no se repite. Las cachés de resultados usan inicialmente 30 días para web y 30 para
contactos; reutilizar no vuelve actual una verificación ni un empleo caducados.

## Acceso a Apollo

`ApolloAccess` registra la referencia de cuenta, operaciones habilitadas, origen de
financiación, referencia y fecha de comprobación, plan, correo laboral, acceso y
tope de créditos de enriquecimiento. La presencia de `APOLLO_API_KEY` no demuestra
acceso ni autoriza una llamada. El saldo inicial y su valoración pertenecen a
`AccountAllowance`; cada permiso pertenece a la sesión de `Budget` que lo registró.
Si falta comprobar acceso, cuota o facturación, la ejecución real se bloquea sin
recurrir a Hunter. El adaptador admite el plan Free y la campaña necesita al menos
un crédito disponible después de descontar el consumo y las reservas. La consulta
del historial y la demo siguen disponibles.

La comprobación compartida de `pipeline/calls.py` también se aplica al invocar
`find_contacts` directamente, aunque el límite de búsquedas sea cero. Si falla,
el informe queda `pending` con `apollo_access_unverified` y el mensaje literal, que se
guardan en la empresa (T17), y no se llama a ningún proveedor. Si el cupo se agota a mitad
de la pasada, la campaña la detiene con ese motivo. La misma comprobación registra los
límites de solicitudes de `ApolloAccess.rate_limits` (por defecto, los del plan Free) antes
de cualquier reserva.

Cada fallo de Apollo tiene un motivo propio y detiene la pasada de contactos
([campaign.md](campaign.md#parada-y-estado-de-la-campaña)). Una llamada enviada sin
resultado (por ejemplo, un timeout) deja la empresa en `request_uncertain`; conciliada con
el panel como fallida y sin consumo (`manage.py reconcile_usage`,
[budget-providers.md](budget-providers.md#conciliación-con-el-panel)), se repite una sola vez
al reanudar, sin ocupar otro intento del nivel de esfuerzo.

Usar una referencia canónica por saldo real. Las operaciones admitidas son
`people_search` y `people_enrichment`; sus permisos deben corresponder a la operación
y cuenta exactas. La búsqueda tiene cota de cero créditos y el enriquecimiento, de
un crédito por persona, únicamente para las condiciones comprobadas de la cuenta.
No reutilizar permisos de otra sesión. Véase [Presupuesto y proveedores](budget-providers.md).
Los modelos Pydantic validan los campos utilizados; nombres incompletos, fechas
ausentes o fuentes insuficientes quedan pendientes.

La invocación siguiente presupone una base y un `Budget` abiertos, una empresa
calificada y los registros de acceso/cupos comprobados. `session_authorizations`
contiene exclusivamente los objetos que corresponden a permisos explícitos del
responsable en esta sesión, ya registrados mediante `budget.authorize`; este
ejemplo no crea ni concede autorizaciones. Apollo necesita el acceso comprobado;
Tavily y Haiku solo se usan si se proporcionan sus cuentas y permisos.

```python
from prospecting.pipeline import find_contacts
from prospecting.providers import ClaudeClient, ProviderClient
from prospecting.providers.apollo import APOLLO_OPERATIONS
from prospecting.providers.tavily import TAVILY_OPERATIONS

client = ProviderClient(budget, [*APOLLO_OPERATIONS, *TAVILY_OPERATIONS])
report = find_contacts(
    db, budget, client, campaign_id, company_id,
    apollo_access=apollo_access,
    authorizations=session_authorizations,
    tavily_account_ref=tavily_account_ref,
    claude=ClaudeClient(budget),
    claude_account_ref=claude_account_ref,
    claude_funding_source="prepaid",
)
```

## Validación de personas y canales

Una persona utilizable tiene nombre completo, entidad confirmada, cargo respaldado,
función pertinente y empleo vigente sin contradicciones pendientes. En campañas con
`role_taxonomy_v1`, `target_roles` reúne los cargos de familias asociadas a perfiles
con citas verificadas en la evaluación; sin perfil respaldado no hay consulta Apollo.
Las familias incluyen variantes ES/EN, departamentos, seniority, funciones y
exclusiones; el departamento es clasificación interna, no un filtro de People API
Search. Los cargos genéricos sin función no bastan. Un título o el indicador de
autoridad del proveedor no asignan automáticamente un papel de compra;
`buying_role` permanece `unknown` sin respaldo específico.

El catálogo editable está en `config/veryfi.json` bajo `role_taxonomy`: sus doce
familias identifican perfiles, títulos, niveles admitidos, términos de función,
exclusiones, procedencia, fecha y estado de validación. `function_id` agrupa las
variantes de jerarquía de una misma función para seleccionar diversidad. Una lista
de seniorities vacía indica que no se exige ese filtro. La configuración se valida
al cargarla; las campañas ya creadas conservan su instantánea. Las familias siguen
pendientes de validación comercial y no incluyen nombres ni enlaces de personas.
El archivo privado de perfiles contiene enlaces, pero no cargos normalizados
verificables: su extracción manual sigue pendiente. Las familias operativas son
propuestas basadas en el ICP y los documentos comerciales, sin atribuirlas a un
perfil privado concreto.

La pertinencia se calcula según la instantánea y las evidencias de cada campaña,
también al recuperar candidatos o consultar ficha y CSV. Un cargo ambiguo requiere
responsabilidades citadas nominalmente de una fuente corporativa vigente para
acreditar la función. Un responsable regional puede servir aunque resida fuera del
país de la cuenta si su ámbito lo cubre. Las campañas sin taxonomía conservan sus
reglas y solicitudes históricas.

Apollo proporciona candidatos y datos profesionales sujetos a validación. Una fecha
de consulta o de actualización del perfil no se convierte en fecha del puesto ni
de verificación del correo. Para validar empleo se necesita evidencia fechada
dentro de 365 días o un directorio corporativo actual consultado dentro de la
caché web de 30 días. Una fuente sin vigencia estimable exige revisión. Estos son
valores iniciales del prototipo, reducidos según la configuración guardada de
la campaña.

### Vigencia del empleo (T18)

`employment_status` separa lo que declara el proveedor de la evidencia pública del
puesto. Se calcula al leer, sin red ni IA, para todas las personas (elegibles o no), y
no se guarda: no cambia `current_employment`, el esquema ni los identificadores
persistidos. Solo `corporate_evidence` habilita a la persona en `validate_contact`; los
demás estados la dejan fuera de listo con un motivo visible en la ficha y el CSV.

| Estado | Cuándo | Efecto |
|---|---|---|
| `corporate_evidence` | Un hecho del puesto observado de una fuente `primary` o `secondary` (nunca del proveedor ni del buscador), vigente según `employment_freshness`, que nombra a la persona con nombre completo, sin contradicciones en ningún sentido y con `current_employment=True`. Para personas de Apollo, además, una fuente pública vigente nombra a la persona con su cargo actual | Habilita a la persona |
| `provider_claim` | Apollo declara el empleo actual (`#enrichment` dentro de `cache.contact_days`) o el historial de Hunter lo infiere (`origin="hunter"`) | No habilita; pide evidencia corporativa |
| `contradicted` | Salida nominal o `current_employment=False`, una fuente corporativa con otro cargo o una fuente del puesto contradicha | No habilita; bloquea listo con su motivo |
| `unknown` | Sin evidencia vigente ni afirmación reciente del proveedor | No habilita |

`employment_freshness` clasifica cada fuente del puesto como `fresh`, `stale`, `future`
o `undated`, con las ventanas de arriba. Los motivos (`reason`) son: `employment_ended`,
`title_changed`, `contradicted_source`, `future_date`, `stale_source`,
`undated_source`, `ambiguous_source` (la fuente no nombra a la persona),
`title_unconfirmed` (ninguna fuente vigente confirma el cargo que declara Apollo),
`incomplete_name` (apellido ofuscado o nombre parcial), `provider_claim_only`,
`historical_inference` y `no_employment_evidence`. `review_required` marca los casos
ambiguos que necesitan revisión humana: `title_changed`, `undated_source`,
`ambiguous_source`, `title_unconfirmed` e `historical_inference`. `evidence_ids`
apunta a las fuentes que justifican el estado o su motivo.

Nunca cuentan como evidencia del puesto el correo ni su verificación, el
`provider_status`, la fecha `last_refreshed_at` de Apollo ni un hecho del proveedor. Una
contradicción se revisa en ambos sentidos: el hecho que contradice y el que es
contradicho. Las páginas corporativas y directorios que localiza Tavily en la
etapa de contactos son la vía de corroboración; T18 no añade llamadas ni proveedores.

### Confirmación manual del empleo (T23)

Ventas puede confirmar desde la ficha el empleo vigente de una persona, sin enviar mensajes,
llamadas ni invitaciones. `employment_confirmation_titles` decide a quién se le ofrece y con
qué cargos: personas de Apollo enriquecidas, con nombre completo sin `*` y sin
`current_employment=False`, en `provider_claim` de Apollo (se confirma el cargo actual) o en
`title_changed` (se elige uno de los cargos ya citados en sus fuentes de título, de Apollo o
de la extracción pública). Quedan fuera `employment_ended`, `contradicted_source`, `unknown`,
quien ya tiene `corporate_evidence` y las campañas históricas. `read_campaign` lo publica en
`ContactResult.employment_titles`, vacío con exclusión confirmada o ambigua o sin evaluación.

`confirm_current_employment` exige aceptación explícita, un motivo y una URL http(s). En una
sola transacción guarda una `Evidence` `manual` (`manual_employment_evidence`) y añade su id a
`employment_evidence_ids`; en `title_changed` guarda además el cargo elegido como `title`. Sin
taxonomía, también recalcula la pertinencia de ese cargo. Por último guarda el
`business_status` recalculado. No toca `identity_status`, `current_employment`, las fuentes,
sus `contradiction_ids` ni los datos de Apollo. Un fallo revierte todo, y el candado de
ejecución la bloquea mientras corre una campaña.

`employment_status` acepta la confirmación cuando es la más reciente de la persona, está
citada, no es futura, tiene menos de `cache.contact_days` días y su fragmento nombra a la
persona y su cargo actual. El resultado es `corporate_evidence` con `basis="manual"` y
`confirmed_at`, `confirmation_expires_at`, `confirmation_reason` y `confirmation_source`; la
evidencia pública vigente se muestra con `basis="source"`. `resolve_manual_employment` aplica al
leer, sin guardarla, una proyección que usan `employment_status`, `validate_contact`,
`person_stage`, `contact_match` y `matched_role_family`:

- quita de las copias los enlaces de contradicción hacia las fuentes de cargo de la persona
  observadas hasta la confirmación;
- si eso resolvió una contradicción, lee la identidad como confirmada.

Los controles de gasto siguen leyendo la identidad guardada. Al vencer, la persona se lee igual
que sin la confirmación. Una salida nominal, `current_employment=False` o una contradicción de
cargo observada después la anulan. Si el cargo guardado cambia, deja de aplicar.

La vigencia inferida de Hunter se conserva solo para leer registros históricos:
correo nominal del dominio confirmado verificado `valid` dentro de `email_days` y
una fuente de Hunter con `still_on_page=True` y `last_seen_on` dentro de
`employment_days`. Desde T18 es `provider_claim` con origen `hunter` y motivo
`historical_inference`, y ya no deja lista a la persona en ninguna campaña. En una
campaña Apollo, `contact_context` no muestra a esas personas.

La extracción pública usa `contacts_extraction_v2` para campañas con taxonomía y
`contacts_extraction_v1` para instantáneas históricas, con el mismo Haiku que la
calificación. La versión nueva puede citar responsabilidades para evaluar una
función ambigua, sin una llamada adicional de IA. Si toda la evidencia vigente
cabe en el límite de entrada, se envía completa y en el mismo orden de siempre,
con la misma huella para el mismo prompt. Si hay que recortar,
entran primero las fuentes primarias de directorios o páginas de equipo, luego las
que mencionan un cargo objetivo o una persona conocida, y las más recientes antes,
para no perder información nominal. Cada hecho cita un `evidence_id` suministrado y una cita literal
asociada nominalmente a la persona. Python rechaza referencias inexistentes,
resúmenes del buscador usados como prueba, citas ajenas al fragmento y homónimos
ambiguos. Los candidatos incompletos conservan sus hechos conocidos como pendientes.
Una responsabilidad derivada conserva el identificador de su fuente original. Solo
respalda la función mientras esa fuente corporativa y la cita sigan disponibles,
vigentes y sin contradicciones, incluidas las posteriores; una responsabilidad
negada no valida la función.
Si una fuente contrasta el cargo o la entidad de una persona ya guardada, conserva
ambas evidencias, marca la identidad como contradictoria y suspende listo, sin
reasignar la empresa. El contenido externo no puede
cambiar instrucciones, presupuesto ni condición de listo.

- **Email:** asociación nominal y dominio confirmado de la empresa (un correo de otro
  dominio no cuenta aunque una fuente lo marque como profesional), con verificación vigente de
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

## Porcentaje de match

`read_campaign` devuelve a todas las personas guardadas de cada empresa, también a las
que no superan `validate_contact`, con un match determinístico de 0 a 100. El cálculo
no usa red ni IA y no convierte a una persona en elegible o lista. Ordena la revisión y
ayuda a priorizar el enriquecimiento, pero no es una probabilidad de respuesta ni de compra.

Cada persona suma cuatro componentes. Las campañas nuevas guardan la propuesta
`contact_match_v2`, pendiente de validación comercial con Veryfi. Las campañas anteriores
sin instantánea de match usan `contact_match_v1`, propuesta del equipo del 15 de octubre:

| Componente | `contact_match_v1` | `contact_match_v2` |
|---|---|---|
| Cargo | Elegido en la calificación, 50; otro de los perfiles respaldados, 35; fuera de perfil o desconocido, 0 | Elegido, 40; otro respaldado, 28; fuera de perfil o desconocido, 0 |
| Canal | Preferido utilizable, 25; alternativo confirmado, 18; preferido sin comprobar, 10; alternativo sin confirmar, 7; ninguno, 0 | Preferido utilizable, 20; alternativo confirmado, 14; preferido sin comprobar, 8; alternativo sin confirmar, 6; ninguno, 0 |
| Identidad | Nombre completo e identidad confirmada, 15; nombre completo sin confirmar, 8; nombre incompleto, 0 | Los mismos niveles y puntos que v1 |
| Vigencia del empleo | Evidencia del puesto, 10; inferencia histórica de Hunter, 6; sin comprobar, 0 | `corporate_evidence`, 25; `provider_claim`, `contradicted` o `unknown`, 0 |

El canal preferido es correo, teléfono o WhatsApp; el alternativo es LinkedIn u otro
canal directo. Un canal `invalid` o marcado como no profesional no suma. En v2,
`provider_claim` y `unknown` se muestran pendientes: la afirmación de un proveedor
no prueba empleo vigente. `contradicted` descarta a la persona. En v1 se conserva la
interpretación histórica: `corporate_evidence` corresponde a evidencia del puesto y
`provider_claim` de Hunter a `hunter_signal`; las afirmaciones de Apollo quedan sin
comprobar. El proveedor no añade puntos en v2.

Ambas versiones llevan al final a las personas con identidad contradictoria, salida o
empleo no vigente, o alcance respaldado incompatible con la empresa; v2 también descarta
las demás contradicciones del empleo. El desglose no se oculta. V1 ordena por descarte,
puntaje descendente, elegibilidad, posición del cargo, nombre e id. V2 ordena primero por
descarte y pertinencia del cargo, después por puntaje descendente; a igualdad de pertinencia
y puntaje alterna funciones y desempata por elegibilidad, cargo, nombre e id. El orden no
depende del orden de guardado.

La ficha muestra el porcentaje, su desglose y la versión; la tabla de la campaña, el
número de personas y el mejor match no descartado. El CSV añade `contact_match`,
`contact_match_version`, `contact_match_blocked` y `contact_match_detail`. La ficha y
el CSV también muestran la función que la taxonomía asocia al cargo con fuente y las
funciones representadas entre las personas pertinentes; esto no acredita empleo ni
autoridad de compra.

### Configurar los pesos

`config/contact_match_v2.json` contiene la propuesta para campañas nuevas;
`config/contact_match.json` conserva v1 para las anteriores. La preparación valida el
archivo v2 y guarda su configuración en la instantánea de la campaña. Para usar otro
archivo v2, indica su ruta en `PROSPECTING_CONTACT_MATCH_PATH` antes de preparar la
campaña. Esa variable no modifica las campañas ya guardadas ni sus exportaciones.
Si el archivo v2 falta, es inválido o contiene otra versión, no se guarda la campaña
nueva y se informa el error.

Cada versión fija sus componentes, niveles y puntos mediante una huella validada: no
se pueden cambiar los pesos conservando el mismo nombre de versión. Los cuatro pesos
suman 100, el máximo de cada componente coincide con su peso y los niveles marcados
como pendientes suman 0. Un cambio de puntos o niveles necesita una versión nueva y
su implementación explícita; no basta con editar el JSON.

El match se recalcula sin llamadas ni gasto con la evidencia y fecha de consulta actuales.
Las mismas entradas y fecha producen el mismo resultado, pero una fuente que caduca o
una contradicción nueva puede cambiarlo. Para campañas anteriores, si el archivo v1 falta,
no es válido o declara otra versión, se muestran las personas sin porcentaje, la ficha
avisa y las columnas de match del CSV quedan vacías; no se inventan pesos.

Las pruebas sin red usan credenciales y datos declarados sintéticos; no demuestran
cobertura, acceso ni consumo de Apollo. Las llamadas históricas a Hunter de T07, T09
y la entrega están en [Comprobación de proveedores](provider-check.md). Las pruebas
reales de Apollo requieren comprobar la cuenta y obtener autorización de gasto.

Los teléfonos se comprueban automáticamente solo para prefijos y longitudes de
Colombia/México; otros formatos necesitan revisión. El registro no almacena cuerpos
HTTP: si se pierde una respuesta enviada antes del checkpoint, conserva el gasto
y requiere revisión. Las solicitudes inciertas tampoco se repiten al crear otra campaña.
