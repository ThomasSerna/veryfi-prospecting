# Comprobación de acceso a proveedores

Registro de las pruebas reales mínimas (IDEA.md §11.1). No contiene claves, datos
personales ni listas de empresas; los resultados quedan en la base local bajo `data/`.

## Apollo: comprobación previa de T12

El 2026-11-01 (America/Bogota) se revisaron únicamente metadatos locales. Existe
`data/provider-access.json`, pero no contiene `apollo_access` ni un cupo de Apollo.
`APOLLO_API_KEY` no estaba presente en el entorno del proceso; el nombre de la
variable sí aparece en `.env`. Esta revisión no comprueba el valor de una clave.

El responsable indicó que dispone de un plan Free. La verificación del correo laboral,
los permisos de People API Search y People Enrichment, el saldo, las tarifas y la
facturación de esa cuenta aún no están comprobados. No se autorizaron ni realizaron
llamadas reales a Apollo. La ejecución real queda bloqueada hasta comprobar acceso y
límites y obtener autorización de gasto por operación; la migración sin red fue
autorizada. No se recurre a Hunter automáticamente.

Documentación oficial consultada el 2026-11-01:

- [People API Search](https://docs.apollo.io/reference/people-api-search) busca
  candidatos sin consumir créditos; puede ocultar el apellido y no entrega correo
  ni teléfono. Una coincidencia de dominio puede corresponder a un empleo anterior.
- [People Enrichment](https://docs.apollo.io/reference/people-enrichment) acepta el
  identificador de la persona. Sin teléfono ni waterfall, la cota es un crédito
  bajo las condiciones vigentes documentadas; los [planes heredados](https://docs.apollo.io/docs/api-pricing)
  pueden diferir y deben comprobarse en la cuenta.
- El [esquema de Apollo](https://docs.apollo.io/openapi/apollo-rest-api.json) no
  documenta una fecha de verificación de correo para la persona. Una fecha genérica
  de actualización del perfil no demuestra la fecha del correo ni del puesto.
- Los [límites de API](https://docs.apollo.io/reference/rate-limits) publicados
  para Free son 50 solicitudes por minuto, 200 por hora y 600 por día, por equipo
  y endpoint. El acceso efectivo y sus límites siguen pendientes de comprobación.

Para T15 se volvió a consultar People API Search el 2026-11-06: documenta
`person_titles[]`, `person_seniorities[]` e `include_similar_titles`; sumar títulos
o niveles amplía los resultados y el total de títulos incluidos y excluidos debe ser
menor que 100. La referencia de ese endpoint no documenta un filtro de departamento.
Esta consulta documental no verifica el acceso de la cuenta ni sus resultados reales.

## Apollo: preparación de T17

El 2026-11-07 (America/Bogota) se revisaron de nuevo solo metadatos locales. Se retiró de
`data/provider-access.json` el cupo de Hunter, tras copiar el archivo en
`data/backups/provider-access-2026-11-07-antes-t17.json`; el ledger de SQLite no se tocó.
El archivo sigue sin `apollo_access` ni cupo de Apollo, así que la ejecución real continúa
bloqueada. Hasta esta fecha no se ha hecho ninguna llamada real a Apollo. El lote real de T17
depende de que el responsable compruebe el panel y autorice proveedor, operación y tope; su
resultado está en «Lotes reales de Apollo de la T17».

Documentación oficial consultada el 2026-11-07 ([Library-docs.md](Library-docs.md#apollo-personas-y-correos-profesionales)):
People API Search cuesta 0 créditos y oculta el apellido, el correo y el teléfono.
People Enrichment cuesta de 0 a 1 crédito sin teléfono ni waterfall y su respuesta no
informa el consumo. Organization Search y Organization Enrichment cuestan 1 crédito (por
página y por organización). Los límites Free son 50, 200 y 600 solicitudes por minuto,
hora y día. Un 403 `API_INACCESSIBLE` indica un plan o una clave sin acceso, y la respuesta
a créditos agotados no está documentada.

### Limitaciones de la cuenta

- Search y Enrichment exigen una cuenta registrada con correo laboral; el plan Free puede
  tener requisitos adicionales de elegibilidad que solo se ven en la cuenta.
- El saldo de créditos solo se ve en el panel (Settings > Billing and credits): ninguna
  respuesta de la API lo informa y `api_usage_stats` solo muestra el uso de los límites de
  tasa. Por eso cada enriquecimiento queda pendiente con 1 crédito hasta conciliarlo con
  `manage.py reconcile_usage`.
- Search devuelve candidatos con apellido ofuscado, sin correo ni teléfono; un dominio
  coincidente puede corresponder a un empleo anterior. No hay filtro de departamento.
- El esquema no informa la fecha de verificación del correo; `last_refreshed_at` no prueba
  el cargo ni el empleo vigente.
- Los límites se aplican por equipo: otro uso de la misma cuenta fuera de esta base consume
  el mismo cupo de solicitudes, y el ledger local no lo ve.
- Planes heredados o de pago pueden tener otros precios y límites; el adaptador solo admite
  el plan Free y sus límites, o unos más estrictos.
- El panel de créditos de la parte principal de Apollo (Settings) queda inaccesible hasta
  terminar el asistente de registro; el portal de desarrolladores (`developer.apollo.io`,
  API Keys y Usage) sí muestra plan, créditos, claves y límites desde el principio.

## Lotes reales de Apollo de la T17

| Campo | Valor observado |
|---|---|
| Fecha | 2026-11-08 (America/Bogota): lote 1 de 00:11 a 00:16 y lote 2 de 00:20 a 00:23 |
| Cuenta | Se descartó una primera cuenta registrada con correo no laboral y en prueba del plan Professional: no cumple el requisito de correo laboral y el adaptador solo admite Free. Se usó una cuenta nueva (`apollo-eafit`) registrada con correo institucional, en su propio espacio de trabajo, plan Free, 0 de 85 créditos usados (la página de facturación no era visible hasta terminar el registro), con límites de 50/200/600 en People Search y People Enrichment y una clave sin master key creada para el proyecto. Revisado por el responsable y el agente en el portal de desarrolladores |
| Ejecución | Desde la interfaz Django (`uv run --locked --env-file .env python manage.py runserver 127.0.0.1:8000 --noreload`), Colombia, `fintech_software` y `cpg_loyalty`, sin palabras clave ni lista de exclusiones validada. Lote 1 (campaña `5df50e7e`): máximo 2 empresas, `completed`. Lote 2 (campaña `62b40bb2`): máximo 5 empresas, `partial` |
| Autorización | Responsable del cupo, en el chat y en la interfaz. Lote 1: Tavily `search` ≤ 10 y `extract` ≤ 10 créditos, Haiku ≤ USD 0,05, Apollo `people_search` 0 y `people_enrichment` ≤ 10 créditos. Lote 2: Tavily ≤ 25 y ≤ 25, Haiku ≤ USD 0,05, Apollo `people_enrichment` ≤ 25; `people_search` se registró por error con tope de 10 en lugar de 0, sin efecto en el gasto porque Search reserva y registra 0 créditos |

| Operación | Llamadas | Sin respuesta (timeout) | Créditos reservados | Créditos observados o conciliados | Costo | Latencia |
|---|---:|---:|---:|---:|---:|---|
| Tavily Search (lotes 1 y 2) | 25 | 1 | 25 | 24 observados + 1 pendiente | USD 0 | 0,3–10,3 s (incluye el timeout) |
| Tavily Extract (lotes 1 y 2) | 14 | 0 | 14 | 5 observados | USD 0 | 0,4–2,0 s |
| Haiku `messages` (lote 2) | 2 | 0 | — | — | USD 0,0048 reservado, USD 0,0020 estimado | 2,1–7,5 s |
| Apollo People Search (lote 2) | 2 | 0 | 0 | 0 conciliados | USD 0 | 0,4–0,8 s |
| Apollo People Enrichment (lote 2) | 3 | 0 | 3 | 3 conciliados | USD 0 | 0,5–0,6 s |

Ninguna llamada a Apollo falló ni superó su tope: la clave, People Search y People Enrichment
funcionan con la cuenta Free de correo institucional. Ningún consumo superó su tope.

**Resultados.** En el lote 1, Tavily devolvió dos sitios que no eran empresas colombianas con
encaje (un proveedor de software español y un sitio de contenidos); ambos se detuvieron por
identidad sin confirmar (`name_unconfirmed`, `identity_unverified`), sin llamar a Haiku ni a
Apollo. En el lote 2, de cinco empresas, tres se detuvieron por identidad o país sin confirmar,
una quedó pendiente por el timeout de Tavily y solo una gran empresa de consumo masivo, con
prioridad media y encaje 65, llegó a contactos. People Search devolvió 20 candidatos con el
apellido ofuscado y sin correo, como documenta Apollo; 9 tenían una función pertinente. Los 3
enriquecimientos que permite la prioridad media se rechazaron con `entity_mismatch`: Apollo no
confirmó el empleo actual en la entidad del dominio de la empresa, así que no se asignó ningún
dato. Resultado: 0 identidades verificadas, 0 canales y 0 personas listas
(`qualified_no_contact`, `enrichment_limit`).

### Conciliación

- **Apollo**: el portal de desarrolladores pasó de 0 a 3 créditos usados (2026-11-08 00:28,
  America/Bogota) y mostró 3 solicitudes a Enrichment y 2 a Search en el día, exactamente las
  del ledger. Se concilió con `manage.py reconcile_usage` y el comprobante
  `data/conciliaciones/apollo-2026-11-08-t17.json` (`apollo_reconciliation_v1`, atribución por
  solicitud: el salto de 3 créditos solo puede corresponder a los 3 enriquecimientos, con cota de 1
  cada uno). Primero se ejecutó con `--dry-run`; repetirlo no cambió nada. La cuenta queda con 3
  créditos confirmados, 0 pendientes y 82 disponibles en el ledger. El panel mostró después un
  límite de 95 créditos; el cupo registrado se mantiene en 85 por prudencia.
- **Tavily**: el panel (Overview, clave del proyecto) mostró 29 de 1.000 créditos usados tras los
  dos lotes; según el responsable estaba en 0 antes de empezar, porque el plan gratuito había
  renovado sus créditos. Las respuestas informaron 11 créditos en el lote 1 y 18 en el lote 2, que
  suman exactamente 29, así que la búsqueda con timeout se concilió como fallida y sin consumo.
  Las 39 filas se conciliaron en una transacción; el comprobante está en
  `data/conciliaciones/tavily-2026-11-08-t17.json`. El ledger de `tavily-cuenta-2` acumula
  102 créditos confirmados: el cupo registrado no se renueva con el panel.
- **Haiku**: las 2 llamadas se conciliaron con el costo estimado de los tokens que informó la API
  (USD 0,0020453), sin captura de la consola, porque el responsable lo aceptó, como en T11. El
  comprobante está en `data/conciliaciones/anthropic-2026-11-08-t17.json`. Tras la conciliación,
  el único consumo sin conciliar del ledger es la fila histórica de Hunter de la T07.
- Antes de cada lote y de la conciliación se guardaron copias de la base en `data/backups/`.

### Observaciones y limitaciones

- Apollo cobró los 3 enriquecimientos aunque el sistema rechazó a las tres personas: el costo por
  contacto útil de este lote no está definido (0 listos). Con prioridad media solo se permiten
  3 enriquecimientos, así que el rechazo de los primeros agotó el tope de la empresa.
- En estos lotes el sistema no guardaba qué condición de `entity_mismatch` falló (dominio
  principal, organización u historial de empleo actual), y la respuesta de Apollo no se
  conserva. No se puede saber sin otra llamada si la regla es demasiado estricta para grupos
  con filiales o marcas, como una embotelladora frente a la marca global. Desde el 2026-11-08
  cada rechazo guarda el código de la condición (`entity_mismatch_domain`, etc.; ver
  [contacts.md](contacts.md)), así que el próximo lote o T21 lo mostrarán sin datos personales.
- El descubrimiento con dos segmentos y sin palabras clave devolvió sitios sin encaje en 5 de
  7 empresas: el sistema los detuvo antes de gastar en Haiku y Apollo, pero llegar a Apollo
  exigió un segundo lote.
- Es una muestra de una empresa: no mide cobertura de Apollo ni calidad de contactos. La
  comparación con la línea base corresponde a T21.

## Lote real de la T24

| Campo | Valor observado |
|---|---|
| Fecha | 2026-11-09 (America/Bogota): ejecución de 01:42 a 01:44 y reanudación de 01:52 a 01:53 |
| Cuentas | Las de T17: Apollo Free de correo institucional (`apollo-eafit`), `tavily-cuenta-2` y Haiku prepagado |
| Ejecución | Desde la interfaz Django local, campaña nueva `cec467b6` con `employment_corroboration_v1`: Colombia y México, `fintech_software` y `cpg_loyalty`, sin palabras clave, máximo 5 empresas. Antes de cada ejecución se copió la base en `data/backups/` |
| Autorización | Responsable del cupo, en el chat del 2026-11-08, para todo el lote: Tavily `search` ≤ 40 y `extract` ≤ 25 créditos, Haiku ≤ USD 0,05, Apollo `people_search` 0 y `people_enrichment` ≤ 15. La reanudación usó los topes restantes (26, 15, USD 0,04, 0 y 12) |

| Operación | Llamadas | Créditos reservados | Créditos observados | Costo |
|---|---:|---:|---:|---|
| Tavily Search | 17 | 17 | 17 | USD 0 (crédito gratuito) |
| Tavily Extract | 11 | 11 | 4 | USD 0 (crédito gratuito) |
| Haiku `messages` | 2 | — | — | USD 0,0048 reservado, USD 0,0022 estimado |
| Apollo People Search | 2 | 0 | — | USD 0 |
| Apollo People Enrichment | 3 | 3 | Pendiente de conciliar con el panel | USD 0 |

Ninguna llamada falló ni superó su tope.

**Resultados.** De cinco empresas, cuatro se detuvieron por nombre o país sin confirmar, antes de
gastar en Haiku o Apollo. Una cuenta de prioridad alta llegó a contactos. People Search devolvió
8 candidatos y People Enrichment confirmó a 3 personas pertinentes. Por primera vez en un lote real
no hubo rechazos de entidad. Las tres quedaron con el empleo solo declarado por Apollo
(`provider_claim_only`).

En la primera ejecución, la extracción general con Haiku devolvió un hecho sin asociación nominal
(`nominal_association`). La conducta anterior dejó la empresa pendiente, sin llegar a la fase de
T24. Se corrigió ese bloqueo (`contacts:haiku_rejected:<código>`, [contacts.md](contacts.md#corroboración-dirigida-del-empleo-t24))
y se reanudó la empresa. La fase buscó a las 3 personas (1 búsqueda cada una): 20 resultados, sin
ninguno del dominio corporativo. Los 3 snippets elegidos nombraban a la persona junto a la empresa.
La extracción única de esas 3 URL no devolvió contenido (0 créditos observados), así que Haiku no
se llamó.

`manage.py corroboration_report`: 3 personas buscadas, 0 corroboradas, 0 pendientes por cupo,
0 rechazos de Haiku; 4 solicitudes de Tavily en la fase (3 créditos observados). El costo por empleo
verificado queda sin definir. Resultado comercial: 0 personas listas (`qualified_no_contact`,
`people_target_reached`), las tres en «búsqueda dirigida sin corroboración».

### Conciliación

Antes de conciliar se guardó una copia de la base en `data/backups/`.

- **Apollo**: el panel pasó de 3 a 6 créditos usados, según la lectura del responsable del
  2026-11-09. Se concilió con `manage.py reconcile_usage` (primero con `--dry-run`) y el comprobante
  `data/conciliaciones/apollo-2026-11-09-t24.json` (`apollo_reconciliation_v1`, atribución por
  solicitud: el salto de 3 corresponde a los 3 enriquecimientos). Repetirlo no cambia nada. La cuenta
  queda con 0 créditos pendientes y 79 disponibles en el ledger.
- **Tavily**: el panel pasó de 29 a 50 créditos usados. Las 28 filas del lote informaron 21 créditos
  (17 de búsqueda y 4 de extracción), exactamente el salto. Se conciliaron en una transacción; el
  comprobante está en `data/conciliaciones/tavily-2026-11-09-t24.json`.
- **Haiku**: las 2 llamadas se conciliaron con el costo estimado de los tokens que informó la API
  (USD 0,0021728), sin captura de la consola, porque el responsable lo aceptó el 2026-11-09, como en
  T11 y T17. El comprobante está en `data/conciliaciones/anthropic-2026-11-09-t24.json`.
- Las 35 solicitudes del lote quedaron conciliadas. En todo el ledger solo sigue sin conciliar la fila
  histórica de Hunter de la T07.

### Observaciones y limitaciones

- Es una sola empresa con tres personas: no mide la tasa de conversión de T24.
- Las páginas que encontró la búsqueda dirigida no eran del dominio corporativo, y Tavily Extract no
  devolvió su texto. El motivo literal de cada URL solo figura en los avisos de la ejecución, que no
  se guardan.
- Aunque Extract hubiera devuelto texto, una página no corporativa sin fecha publicada habría dejado
  a la persona en `undated_source` (revisión humana), no en `corporate_evidence`.

## Lotes reales de calibración con cuentas objetivo (15 y 16 de noviembre de 2026)

Tres campañas desde la interfaz Django local, con las cuentas de T24 (`apollo-eafit`, `tavily-cuenta-2`,
`anthropic-equipo-prepago`), solo `cpg_loyalty`, Colombia y México, y cuentas objetivo elegidas por el equipo
(empresas grandes de consumo masivo que no figuran entre las referencias de clientes). Antes se copió la base en
`data/backups/prospecting-2026-11-15-antes-calibracion-cuentas-objetivo.sqlite3`. Autorización: el responsable
del cupo, en la sesión de trabajo del 15 y 16 de noviembre, autorizó gastar en Tavily, Apollo y Haiku hasta
calibrar; los topes de cada ejecución se fijaron en la interfaz y están en la tabla. Los nombres de empresas y
personas permanecen en `data/`.

| Campaña | Cuentas | Topes autorizados | Resultado |
|---|---:|---|---|
| `c16b84f8` (15 nov, 22:05) | 4 | Tavily 50 + 20, Haiku USD 0,15, Apollo 14 | 4 de 4 identidades confirmadas. Primera ejecución detenida por `HTTP 401. invalid x-api-key` de Anthropic; al reanudar con la clave corregida, 3 evaluadas y las 3 en `insufficient_evidence`; 1 atascada en `duplicate_request` por la llamada rechazada |
| `fabbce01` (16 nov, 02:12) | 6 | Tavily 70 + 30, Haiku USD 0,30, Apollo 20 | 2 `ready_preferred`, 1 `needs_channel_confirmation`, 1 `insufficient_evidence`, 2 pendientes por citas de Haiku rechazadas |
| `2a915279` (16 nov, 09:30) | 7 | Tavily 80 + 30, Haiku USD 0,40, Apollo 22 | 1 `ready_preferred`, 1 `needs_channel_confirmation`, 1 `qualified_no_contact` (sin perfil respaldado), 3 `insufficient_evidence`, 1 atascada en `duplicate_request` |

| Operación | `c16b84f8` | `fabbce01` | `2a915279` | Total |
|---|---:|---:|---:|---:|
| Tavily Search, llamadas y créditos informados | 6 | 25 | 19, más 1 sin respuesta | 50, más 1 incierta |
| Tavily Extract, llamadas / créditos informados | 7 / 3 | 17 / 10 | 16 / 7 | 40 / 20 |
| Haiku `messages`, llamadas / costo estimado | 3 (más 1 rechazada) / USD 0,00321 | 14 / USD 0,02807 | 13 / USD 0,02104 | 30 / USD 0,05232 |
| Apollo People Search, llamadas (0 créditos) | 0 | 6 | 4 | 10 |
| Apollo People Enrichment, llamadas y créditos reservados | 0 | 7 | 4 | 11 |

Ninguna llamada superó su tope. Apollo y Haiku quedaron conciliados con los paneles el 16 de noviembre; Tavily
sigue pendiente por una diferencia de 3 créditos ([conciliación](#conciliación-de-los-lotes-de-calibración)).

Qué se midió, sobre 11 empresas distintas (13 ejecuciones de empresa en las dos últimas campañas):

- **Por primera vez hay personas listas con datos reales:** 3 empresas en `ready_preferred`, con 7 personas con
  correo `verified` por Apollo, y 2 en `needs_channel_confirmation`, con 4 personas con solo LinkedIn. Todas
  viven en el país de la campaña según Apollo. En las 13 campañas anteriores el total era 0.
- **Causa de fondo de los resultados anteriores:** con 9.000 tokens de entrada, el prompt de calificación y su
  esquema (más de 100 cargos permitidos) dejaban sitio para 2 fragmentos de evidencia. La primera campaña lo
  mostró: 3 de 3 evaluadas quedaron en `insufficient_evidence` con una promoción legible entre su evidencia.
  Con 30.000 tokens entran unos 40 fragmentos; las solicitudes reales midieron unos 17.000 tokens de entrada.
- **La web abierta sin país devolvía homónimos** (hoteles, relojes y la ficha de empresa del propio buscador).
  Con el país, una señal del segmento obligatoria y `tavily.com` descartado dejaron de leerse.
- **Citas de Haiku:** 2 empresas quedaron pendientes porque un perfil citaba un resultado de búsqueda o una
  evidencia no suministrada, y una campaña falló al guardar una cita tomada de texto con saltos de línea. Ahora
  el perfil sin respaldo se descarta y la cita se comprueba igual en la calificación, los cargos y la base.
- **Orden de personas:** una gerente de programas de lealtad quedó sin enriquecer detrás de un director
  comercial. Desde entonces las funciones `preferred` (lealtad/CRM y datos de marketing) van primero. No se
  volvió a medir: ninguna empresa de la tercera campaña devolvió esos cargos.

Límites de lo medido:

- Todas las calificadas quedaron en prioridad `medium`: ninguna evidencia respaldó la escala (`scale_potential`
  desconocido), aunque son empresas grandes. Apollo podría aportar el tamaño, pero no se consulta.
- En una de las 3 empresas listas, todos los criterios se apoyan en una sola página de terceros (las bases de
  una promoción) que Haiku describe como no operada directamente por la marca. El 16 de noviembre se leyó esa
  página a mano en el navegador, sin proveedores de pago: las bases nombran a una agencia de promociones como
  organizadora, limitan la participación a productos de una línea de la marca en un minorista y nombran a la
  filial mexicana de la empresa. La promoción sí es de la marca; quien recibe y valida los tickets es la agencia,
  así que ventas debe confirmar quién decide sobre ese proceso. Es una lectura manual, no evidencia guardada.
- Ninguna calificada puede llegar a prioridad alta sin evidencia de escala: en `rubric_v2` ese criterio pesa 35 y,
  sin él, la cobertura máxima es 0,65, por debajo del 0,75 que exige la prioridad alta. La investigación no
  hace ninguna búsqueda dirigida al tamaño.
- 5 de 11 empresas no mostraron evidencia de promociones con comprobantes: sus sitios corporativos no las
  publican y la búsqueda abierta no las encontró. No prueba que no existan.
- Una llamada a Haiku rechazada (clave inválida) bloqueaba esa empresa en la campaña con `duplicate_request`
  incluso después de conciliarla, porque la calificación nunca pedía el reintento. Corregido el 16 de noviembre:
  tras conciliar el fallo sin consumo, la calificación la repite una sola vez con un permiso nuevo, como ya hacía
  la etapa de contactos. Solo se ha probado con datos sintéticos.
- Sigue sin salida una llamada a Haiku que respondió pero cuyo resultado no llegó a guardarse (una empresa de la
  tercera campaña, por el fallo de la cita con saltos de línea ya corregido): la respuesta se pagó, no se conserva
  y la solicitud no se repite. Esa empresa solo puede evaluarse en una campaña nueva.
- No hubo revisión comercial: ninguna persona ni empresa fue aceptada o rechazada por Veryfi.

### Conciliación de los lotes de calibración

Lecturas de los paneles entregadas por el responsable el 16 de noviembre de 2026 (19:58, America/Bogota). Antes
de conciliar se copió la base en `data/backups/prospecting-2026-11-16-antes-conciliacion-calibracion.sqlite3`.

- **Apollo: conciliado.** El portal de desarrolladores pasó de 6 a 17 créditos usados y mostró 11 solicitudes de
  People Enrichment en el día. El salto de 11 corresponde a los 11 enriquecimientos. Se concilió con
  `manage.py reconcile_usage` (primero con `--dry-run`) y el comprobante
  `data/conciliaciones/apollo-2026-11-16-calibracion.json`: 21 solicitudes, 0 créditos pendientes y 68
  disponibles en el ledger, con el cupo registrado en 85 (el panel muestra un límite de 95).
- **Haiku: conciliado y, por primera vez, verificado en la consola.** La consola de Claude informa 453.748 tokens
  de Haiku 5.5 el 16 de noviembre (UTC), exactamente la suma de entrada y salida de las 30 respuestas del ledger
  (436.395 y 17.353). Costo final: USD 0,0523160. La llamada rechazada con `HTTP 401` no aparece en la consola y
  se concilió como fallida y sin consumo. Comprobante: `data/conciliaciones/anthropic-2026-11-16-calibracion.json`.
  El saldo de la organización es USD 4,91.
- **Uso de Anthropic fuera de este ledger:** la consola muestra 1.743 tokens el 15 de noviembre (UTC) que no
  corresponden a ninguna fila (1.327 de entrada y 416 de salida según los totales de 30 días). Al precio
  publicado son unos USD 0,00034. No se ha descontado del cupo registrado.
- **Tavily: pendiente.** El panel muestra 142 de 1.000 créditos. Las respuestas de noviembre suman 145 en el
  ledger (29 de T17, 21 de T24, 25 de T30 y 70 de estos lotes), más la búsqueda sin respuesta. Desde la lectura
  posterior a T30 (73) el panel subió 69 frente a 70 informados; con los 2 de T30, la diferencia acumulada es de
  3 créditos que no se pueden atribuir a solicitudes concretas. Las 126 filas siguen sin conciliar y la búsqueda
  sin respuesta, en `uncertain`; sus créditos informados y su reserva ya se descuentan del cupo, que queda como
  cota superior del consumo real.
- El panel de Tavily muestra el aviso «To continue using Tavily, please provide a billing address». No se ha
  comprobado si bloquea nuevas llamadas.
- **Tavily, cierre del 16 de noviembre:** el responsable aceptó conciliar con los créditos informados. Las 126
  filas de T30 (25 créditos) y de estos lotes (70) quedaron conciliadas con el comprobante
  `data/conciliaciones/tavily-2026-11-16-t30-y-calibracion-informados.json`, sin verificación exacta en el panel,
  que muestra 3 créditos menos; el ledger queda como cota superior. La búsqueda sin respuesta sigue en `uncertain`
  con su reserva de 1 crédito, porque no informó consumo.
- En todo el ledger quedan sin conciliar esa búsqueda sin respuesta y la fila histórica de Hunter de la T07.

## Lote real de verificación de `haiku_assessment_v7` y FinTech (16 de noviembre de 2026)

| Campo | Valor observado |
|---|---|
| Fecha | 2026-11-16 (America/Bogota): ejecución de 20:18 a 20:22 |
| Cuentas | `apollo-eafit`, `tavily-cuenta-2` y `anthropic-equipo-prepago` |
| Ejecución | Desde la interfaz Django local, campaña nueva `25638dd8` con `rubric_v2` y `haiku_assessment_v7`: Colombia y México, `fintech_software` y `cpg_loyalty`, 10 cuentas objetivo (4 de FinTech y 6 de consumo masivo, 3 de ellas ya investigadas en los lotes de calibración). Antes se copió la base en `data/backups/prospecting-2026-11-16-antes-lote-verificacion-v7.sqlite3`. Los nombres permanecen en `data/` |
| Autorización | Responsable del cupo, en el chat del 2026-11-16: Tavily `search` ≤ 60 y `extract` ≤ 30 créditos, Haiku ≤ USD 0,30, Apollo `people_search` 0 y `people_enrichment` ≤ 15 créditos |

| Operación | Llamadas | Créditos reservados | Créditos informados o conciliados | Costo |
|---|---:|---:|---:|---|
| Tavily Search | 29, una sin respuesta | 29 | 28 informados, más 1 atribuido a la búsqueda sin respuesta | USD 0 (crédito gratuito) |
| Tavily Extract | 23 | 23 | 11 | USD 0 (crédito gratuito) |
| Haiku `messages` | 23 | — | — | USD 0,0449948 estimado y conciliado |
| Apollo People Search | 10 | 0 | 0 | USD 0 |
| Apollo People Enrichment | 13 | 13 | 13 conciliados | USD 0 |

Ninguna llamada superó su tope. La campaña quedó `partial`.

**Resultados.** Las 10 evaluaciones usaron `haiku_assessment_v7`.

- **FinTech (4 cuentas, primera ejecución real con las reglas nuevas):** 1 `ready_preferred` con 2 personas, 1
  `needs_channel_confirmation` con 3 personas, 1 marcada `ready_preferred` cuya etapa de contactos se detuvo por el
  timeout de Tavily y 1 pendiente porque Haiku citó evidencia que no se le suministró
  (`assessment_pending:unknown_evidence`). Las 3 calificadas quedaron en prioridad media con los perfiles
  `payments_ap_erp` o `expense_reimbursement` y cargos de producto e ingeniería.
- **Consumo masivo (6 cuentas):** las 2 repetidas con personas dieron lo mismo que con `haiku_assessment_v6`
  (1 `ready_preferred` con 3 personas y 1 `needs_channel_confirmation` con 2), ahora con dos perfiles reconocidos
  en vez de uno, y reutilizaron las personas guardadas sin llamar a Apollo. De las nuevas, 1 quedó en
  `needs_channel_confirmation` con 1 persona de 3 enriquecimientos, 1 en `qualified_no_contact` y 2 en
  `insufficient_evidence` (una de ellas ya lo estaba en el lote anterior).

### Conciliación

Lecturas de los paneles entregadas por el responsable el 16 de noviembre (20:30, America/Bogota). Antes se copió la
base en `data/backups/prospecting-2026-11-16-antes-conciliacion-lote-verificacion-v7.sqlite3`.

- **Apollo**: el portal pasó de 17 a 30 créditos usados; el salto de 13 corresponde a los 13 enriquecimientos. Se
  concilió con `manage.py reconcile_usage` (primero con `--dry-run`) y el comprobante
  `data/conciliaciones/apollo-2026-11-16-lote-verificacion-v7.json`. La cuenta queda con 0 créditos pendientes y 55
  disponibles en el ledger.
- **Tavily**: el panel pasó de 142 a 182 créditos, un salto de 40. Las respuestas informaron 39 (28 de búsqueda y 11
  de extracción); el crédito restante se atribuyó, por inferencia del total, a la búsqueda sin respuesta, que
  conserva resultado desconocido. Las 52 filas se conciliaron en una transacción; comprobante en
  `data/conciliaciones/tavily-2026-11-16-lote-verificacion-v7.json`. En noviembre el ledger suma 185 créditos y el panel 182; las filas de T30 y de
  los lotes de calibración se conciliaron después con los créditos informados.
- **Haiku**: las 23 llamadas se conciliaron con el costo estimado de los tokens que informó la API (USD 0,0449948),
  sin captura de la consola, porque el responsable lo aceptó el 2026-11-16. Comprobante en
  `data/conciliaciones/anthropic-2026-11-16-lote-verificacion-v7.json`.

### Observaciones y limitaciones

- En la cuenta global de consumo masivo, el dominio corporativo agrupa empleados de todo el mundo: de 3
  enriquecimientos quedó 1 persona, con un cargo de alcance norteamericano. Ventas debe revisar si es pertinente.
- En la cuenta `qualified_no_contact`, Apollo rechazó a las personas con `entity_mismatch_domain`: el dominio dado
  como cuenta objetivo no es el que Apollo asocia a sus empleados. Gastó 3 créditos sin resultado y deja sin medir
  el orden preferente de lealtad/CRM, que eran justo los cargos pedidos.
- Esa misma cuenta es la primera con escala respaldada (cobertura 0,95); quedó en prioridad media porque su encaje,
  68, no llega a 75.
- No se revisó por qué una cuenta de FinTech con personas con correo quedó en `needs_channel_confirmation`.
- No hubo revisión comercial de ninguna cuenta ni persona.

## Campaña real final de la T32 (19 de noviembre de 2026)

| Campo | Valor observado |
|---|---|
| Fecha | 2026-11-19 (America/Bogota): campaña principal de 07:58 a 08:05 y reanudación a las 08:08; segunda pasada a las 08:13 y tercera a las 08:16 |
| Cuentas | `apollo-eafit`, `tavily-cuenta-2` y `anthropic-equipo-prepago` |
| Base | Aislada a petición del equipo, para empezar desde cero sin datos de campañas anteriores: `data/t32/prospecting.sqlite3` (campaña principal y segunda pasada) y `data/t32-coca/prospecting.sqlite3` (tercera pasada), abiertas con `PROSPECTING_DB_PATH`. La base histórica no se modificó; antes se copió en `data/backups/prospecting-2026-11-19-antes-t32.sqlite3` |
| Cupos | Como una base nueva no ve el consumo anterior, cada base usa su propio archivo de acceso (`PROSPECTING_ACCESS_PATH`) con el saldo restante, no el inicial: Tavily 741 créditos (1.000 menos los 259 del ledger histórico), Haiku USD 2,8649 (USD 2,9981 menos USD 0,1331819) y Apollo 65 (panel: 30 de 95 usados). La tercera base descuenta además lo reservado en la primera |
| Ejecución | Desde la interfaz Django local. Campaña principal `ae38a5ed`: Colombia y México, `fintech_software` y `cpg_loyalty`, 20 cuentas objetivo (10 por país; 16 de consumo masivo y 4 FinTech/ERP), con `discovery_policy_v2`, `channel_policy_v2`, `employment_policy_v2` y `contact_match_v3`. Segunda pasada `386fffb7` y tercera `00ab01ea`: solo la cuenta de Coca-Cola, México y `cpg_loyalty`. Los nombres de las cuentas permanecen en `data/` |
| Autorización | Responsable del cupo, en el chat del 2026-11-19: Tavily `search` ≤ 200 y `extract` ≤ 150 créditos, Haiku ≤ USD 2, Apollo `people_search` 0 y `people_enrichment` ≤ todo el saldo del panel (65). La reanudación y las dos pasadas siguientes usaron topes dentro del saldo de esa autorización |

| Operación | Llamadas | Créditos reservados | Créditos informados o conciliados | Costo |
|---|---:|---:|---:|---|
| Tavily Search | 67 (59 + 2 + 6), 3 sin respuesta | 67 | 64 informados, más 3 atribuidos a las búsquedas sin respuesta | USD 0 (crédito gratuito) |
| Tavily Extract | 52 (46 + 2 + 4) | 52 | 20 | USD 0 (crédito gratuito) |
| Haiku `messages` | 44 (39 + 2 + 3) | — | — | USD 0,1595844 reservado; USD 0,0618933 estimado y conciliado (496.813 tokens de entrada y 24.424 de salida) |
| Apollo People Search | 20 (16 + 2 + 2) | 0 | 0 | USD 0 |
| Apollo People Enrichment | 19 (14 + 3 + 2) | 19 | 19 conciliados | USD 0 |

Ninguna operación superó su tope. La campaña principal quedó `partial`; las dos pasadas de Coca-Cola, `completed`.

**Muestra.** Lista de cuentas objetivo armada por el equipo con empresas grandes de Colombia y México que
podrían necesitar a Veryfi. La identidad sale de la declaración, así que no hubo paradas por identidad ni
reservas. Se dejaron fuera los clientes de referencia de `config/icp_enterprise.json`. Coca-Cola se incluyó
por pedido expreso del contacto de Veryfi, aunque `docs/enterprise-rubrics.md` la cita entre las empresas
con las que Veryfi ha trabajado. 5 de las 20 cuentas ya se habían investigado en lotes anteriores; las
otras 15 son nuevas. La muestra no es aleatoria ni representa a Latinoamérica.

**Resultados de la campaña principal** (por país declarado; el segmento es el previsto en la lista):

| Grupo | Empresas | Calificadas | Con personas pertinentes | Con personas listas | Personas pertinentes | Personas listas |
|---|---:|---:|---:|---:|---:|---:|
| México · consumo masivo | 8 | 2 | 1 | 0 | 2 | 0 |
| México · FinTech/ERP | 2 | 2 | 2 | 1 | 4 | 2 |
| Colombia · consumo masivo | 8 | 3 | 3 | 2 | 6 | 3 |
| Colombia · FinTech/ERP | 2 | 2 | 1 | 1 | 2 | 2 |
| **Total** | **20** | **9** | **7** | **4** | **14** | **7** |
| Cuentas repetidas | 5 | 5 | 4 | 3 | 8 | 5 |
| Cuentas nuevas | 15 | 4 | 3 | 1 | 6 | 2 |

- Todas las calificadas quedaron en prioridad media; ninguna en alta. 11 cerraron en
  `insufficient_evidence`: 9 por `unknown_need_or_match` tras la ampliación, 1 por `insufficient_evidence`
  tras reintentar un timeout y 1 pendiente con `assessment_pending:search_only_strong_signal` («Un criterio
  con valor 1 se apoya solo en resultados de búsqueda»).
- Estados comerciales: 4 `ready_preferred`, 3 `needs_channel_confirmation` y 2 `qualified_no_contact` con
  `no_target_roles` («No hay un caso de uso respaldado para seleccionar cargos»).
- Cobertura de contacto: 4 de 9 calificadas con al menos una persona lista. Canal preferido: 7 de 7
  personas listas con correo nominal que Apollo informa como verificado (`channel_policy_v2`). Su empleo
  vigente lo declara Apollo (`provider_claim` con `employment_policy_v2`); la búsqueda web no lo corroboró
  en ningún caso (12 personas buscadas, 0 corroboradas, `manage.py corroboration_report`). Funciones: 3 de
  marketing en consumo masivo y 4 de producto e ingeniería en FinTech/ERP.
- Ninguna persona lista carece de canal directo ni de empleo vigente según la regla; se comprobó en el CSV
  exportado, solo con conteos.
- Tiempo automático: 402 s activos en la campaña principal (unos 7 minutos de reloj) y 57 s en las dos pasadas.
  Minutos de revisión: no medidos, porque aún no hay revisión comercial.

**Coca-Cola.** Necesitó tres pasadas:

1. En la campaña principal, declarada como «Coca-Cola México», quedó calificada (encaje 96,2) pero sin
   perfil citado, y por tanto `no_target_roles`. Parte de su evidencia venía de páginas de Coca-Cola España
   (`coca-cola.com/es/es`): el dominio es global y la ampliación sobre él mezcla países.
2. En la segunda pasada, en la misma base, Haiku citó `cpg_brands`, pero con una página de España. Apollo
   devolvió personas del dominio correcto y las 3 enriquecidas se rechazaron con `entity_mismatch_name`: el
   nombre declarado («Coca-Cola México») no coincide con el que Apollo da a la organización. Como la cuenta
   reutiliza la empresa guardada con ese nombre, no se puede corregir en esa base.
3. En la tercera pasada, en una base aparte y declarada como «Coca-Cola», quedó `ready_preferred` con
   prioridad media (encaje 53,8). El perfil `cpg_brands` se apoya en los términos de una promoción de Coca-Cola
   México (compra mínima de productos participantes y escaneo de la tarjeta Spin Premia en el punto de venta).
   Hay 1 persona lista, de la familia de lealtad y CRM, con correo verificado por Apollo y empleo declarado
   por Apollo.

Con la tercera pasada, la T32 suma 5 empresas con personas listas y 8 personas listas.

**Costo por persona lista.** Haiku: USD 0,0618933 / 8 = USD 0,0077. Tavily: 87 créditos / 8 = 10,9 créditos.
Apollo: 19 créditos / 8 = 2,4 créditos. Tavily y Apollo usan crédito gratuito (USD 0). El costo por
prospecto aceptado no es calculable mientras ventas no revise.

**Fallos de proveedor.** 3 búsquedas de Tavily con «Timeout del proveedor; consumo pendiente.»: dos
durante la calificación y una durante los contactos de una cuenta que ya estaba lista. 22 URL que Tavily
Extract no pudo leer: 20 con «Failed to fetch url», 1 con «404 page not found» y 1 con «Error fetching
content». La reanudación cerró una de las cuentas caídas por timeout. La otra quedó con la evaluación
pendiente. La tercera, ya lista, quedó con `request_uncertain` hasta la conciliación.

### Conciliación

Lecturas de los paneles entregadas por el responsable el 19 de noviembre. Antes se copiaron las dos bases
en `data/backups/t32-2026-11-19-antes-conciliacion.sqlite3` y
`data/backups/t32-coca-2026-11-19-antes-conciliacion.sqlite3`. Las 202 filas de las dos bases quedaron
conciliadas.

- **Apollo**: el panel pasó de 30 a 49 de 95 créditos; el salto de 19 corresponde a los 19
  enriquecimientos. Se concilió con `manage.py reconcile_usage`, primero con `--dry-run`, con un comprobante
  por base que declara como ajenos al ledger los créditos de la otra base:
  `data/conciliaciones/apollo-2026-11-19-t32.json` (17 + 2 ajenos) y
  `data/conciliaciones/apollo-2026-11-19-t32-coca.json` (2 + 17 ajenos).
- **Tavily**: el panel pasó de 182 a 269 créditos, un salto de 87. Las respuestas informaron 84; los 3
  créditos restantes se atribuyeron, por inferencia del total, a las 3 búsquedas sin respuesta, que
  conservan resultado desconocido. Las 119 filas se conciliaron con `Budget.reconcile_many`;
  comprobante en `data/conciliaciones/tavily-2026-11-19-t32.json`.
- **Haiku**: las 44 llamadas se conciliaron con el costo estimado de los tokens (USD 0,0618933), sin
  captura de la consola, que el responsable dejó como opcional. Comprobante en
  `data/conciliaciones/anthropic-2026-11-19-t32.json`.
- **Base histórica**: el ledger de `data/prospecting.sqlite3` no registra este consumo. Antes de otra
  campaña en esa base hay que descontar de su archivo de acceso lo gastado aquí: Tavily 87 créditos, Apollo
  19 y Haiku USD 0,0618933. El acumulado del proyecto sube a unos USD 0,197 de USD 20.

### Comparación con T24, T30 y v7

- **Qué mejoró.** T24 y T30 terminaron con 0 personas listas, y el lote v7 con 3 cuentas `ready_preferred`
  sobre 10, una de ellas con los contactos cortados por timeout.
  La T32 deja 4 de 20 en la campaña principal y 5 con Coca-Cola, con 8 personas listas. La lista de cuentas
  objetivo elimina las caídas por identidad que frenaron T24 y T30 (T30: 3 de 10 confirmadas), y las
  políticas de canal y empleo v2 permiten llegar a listo con datos de Apollo.
- **Qué sigue bloqueando.**
  - La calificación de grandes marcas de consumo masivo: las 11 cuentas con evidencia insuficiente son de
    consumo masivo (11 de 16), y en la mayoría sus sitios corporativos no muestran promociones con
    comprobantes.
  - La exigencia de un perfil citado antes de buscar cargos.
  - La corroboración web del empleo (0 de 12).
  - Los dominios globales, que mezclan países en la evidencia y en Apollo.
  - La comprobación de nombre de Apollo, sensible al nombre declarado en la cuenta.
- **Qué no se puede concluir.**
  - La muestra fue elegida por el equipo e incluye 5 cuentas ya investigadas, que rindieron mucho
    más que las nuevas (3 de 5 frente a 1 de 15 con personas listas).
  - No mide la cobertura del descubrimiento web ni generaliza a Latinoamérica.
  - La precisión de las empresas y la pertinencia de las personas quedan pendientes de la revisión de ventas.

### Observaciones y limitaciones

- No hubo revisión comercial: falta que ventas revise las empresas y personas en la ficha y que se
  registre su decisión, como pide la T32.
- Coca-Cola quedó en una base aparte, así que su resultado no aparece en la campaña principal; cada base
  se abre con su propio servidor local.
- Al declarar cuentas objetivo conviene usar el nombre con que Apollo identifica a la organización (aquí,
  «Coca-Cola» y no «Coca-Cola México»), porque una empresa ya guardada conserva el nombre de su primera
  declaración.
- Sin envío de mensajes, llamadas ni invitaciones.

## Lote real de la T30

| Campo | Valor observado |
|---|---|
| Fecha | 2026-11-09 (America/Bogota): ejecución de 21:04 a 21:05 |
| Cuentas | Las de T24: Apollo Free (`apollo-eafit`), `tavily-cuenta-2` y Haiku prepagado (`anthropic-equipo-prepago`) |
| Ejecución | Desde la interfaz Django local, campaña nueva `47b4d12a` con `discovery_policy_v2` (T26 y T27) y `channel_policy_v2` (T28): Colombia y México, `fintech_software` y `cpg_loyalty`, sin palabras clave, máximo 5 empresas. Antes se copió la base en `data/backups/prospecting-2026-11-09-antes-t30.sqlite3` |
| Autorización | Responsable del cupo, en el chat del 2026-11-09: Tavily `search` ≤ 60 y `extract` ≤ 40 créditos, Haiku ≤ USD 0,15, Apollo `people_search` 0 y `people_enrichment` ≤ 20 créditos |

| Operación | Llamadas | Créditos reservados | Créditos informados | Costo |
|---|---:|---:|---:|---|
| Tavily Search | 17 | 17 | 17 | USD 0 (crédito gratuito) |
| Tavily Extract | 19 | 19 | 8 | USD 0 (crédito gratuito) |
| Haiku `messages` | 3 | — | — | USD 0,0071850 reservado, USD 0,0032574 conciliado |
| Apollo People Search | 0 | — | — | — |
| Apollo People Enrichment | 0 | — | — | — |

Ninguna llamada falló ni superó su tope. Ninguna empresa llegó a la etapa de contactos, así que Apollo
no se llamó.

**Resultados.** Se investigaron 10 empresas: las 5 seleccionadas y las 5 reservas de T27. De ellas, 3
confirmaron identidad (T24: 1 de 5). Las reservas funcionaron como se esperaba: 5 empresas caídas por
identidad cedieron su plaza (`discovery:replaced_by:`) y otras 2 quedaron con
`discovery:reserve_exhausted`, sin promover dos veces ninguna reserva. Paradas por identidad:
`country_unconfirmed` 4 y `name_unconfirmed` 3. Las 3 empresas confirmadas no llegaron a contactos:
dos cerraron en `insufficient_evidence` y una quedó en `assessed` con `no_target_roles` («No hay un caso
de uso respaldado para seleccionar cargos»), que deja la campaña en `partial`. Resultado comercial:
0 personas pertinentes y 0 listas; el costo por persona lista no es calculable (denominador cero).

Por primera vez se conservaron los fallos de Tavily Extract (T29): 6 URL de la investigación de empresas
con el motivo literal `Failed to fetch url`.

### Conciliación

- **Haiku**: las 3 llamadas se conciliaron con el costo estimado de los tokens (USD 0,0032574), sin
  captura de la consola, porque el responsable lo aceptó el 2026-11-09, como en T11, T17 y T24. El
  comprobante está en `data/conciliaciones/anthropic-2026-11-09-t30.json`.
- **Tavily: pendiente.** El panel pasó de 50 a 73 créditos usados (lectura del responsable, repetida
  tras el lote), un salto de 23. Las 36 respuestas informaron 25 créditos (17 de búsqueda y 8 de
  extracción) y no hay otro uso de la cuenta fuera del ledger. No se puede atribuir la diferencia de
  2 créditos a solicitudes concretas, y el ledger no admite conciliar una fila con un crédito distinto
  del informado por su respuesta. Las filas quedan sin conciliar con ese motivo; los créditos
  informados ya se descuentan del cupo.
- **Apollo**: sin consumo en este lote.

### Observaciones y limitaciones

- La mejora de identidad (de 1 a 3 confirmadas) no se tradujo en personas: el freno pasó a la calidad
  de las candidatas. Tavily devolvió sobre todo proveedores globales sin presencia comprobada en
  Colombia o México (`payhawk.com`, `abbyy.com`, `xtract.app`), sitios ajenos al perfil
  (`enterprise.com`, `eventbrite.com`, `idbinvest.org`), un medio de noticias (`dcnewsnow.com`) y un
  dominio de Perú (`netwoo.pe`), que entró como reserva porque no quedaban candidatas locales.
- T28 no se pudo medir: ninguna persona llegó a evaluarse con `channel_policy_v2`.
- Es una muestra pequeña y de un solo lote: no permite atribuir con confianza cuánto aportó cada
  cambio frente a la variación de los resultados de Tavily entre lotes.

## Tavily

| Campo | Valor observado |
|---|---|
| Fecha | 2026-10-11 (America/Bogota) |
| Cuenta | Plan gratuito del equipo (`tavily-equipo-plan-gratuito`); el responsable informó 1.000 créditos sin uso en el panel |
| Origen de financiación | `free_credit`; desembolso USD 0 |
| Autorización | Responsable del cupo, en la sesión: Search `basic` ≤ 8 créditos y Extract `basic` ≤ 2 créditos, USD 0 |
| Endpoints usados | `POST https://api.tavily.com/search` y `POST https://api.tavily.com/extract`, con `Authorization: Bearer` |
| Documentación | [Search](https://docs.tavily.com/documentation/api-reference/endpoint/search), [Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract) y [créditos](https://docs.tavily.com/documentation/api-credits), consultadas el 2026-10-11 |

### Llamadas

| Operación | Parámetros principales | Llamadas | Créditos reservados | Créditos según `usage` | Latencia | Resultado |
|---|---|---:|---:|---:|---|---|
| Search | `search_depth=basic`, `topic=general`, `country=colombia`, `max_results=10`, `include_usage=true`, `exclude_domains` | 2 | 2 | 2 | 5,0 s en total | 20 resultados, 19 hosts candidatos y 5 seleccionados |
| Extract | `extract_depth=basic`, `format=text`, `query`, `chunks_per_source=3`, `timeout=6`, `include_usage=true` | 2 (1 URL cada una) | 2 | 0 | 0,4 s cada una | 3 fragmentos por URL, de 500 a 800 caracteres; sin `failed_results` |

Campaña de prueba: Colombia, `fintech_software`, `web_queries=2` y `max_companies=5`.
Consumo registrado: 4 créditos reservados y 2 observados. El costo económico es USD 0.

### Conciliación y cierre de la cuenta

El 2026-10-11, a petición del responsable del cupo, las 4 solicitudes se conciliaron con
`Budget.reconcile` usando los `usage.credits` de las respuestas: 1 crédito por búsqueda y 0 por
extracción, es decir, 2 créditos confirmados y USD 0. El uso **no se verificó en el panel
de Tavily**. El comprobante local queda en `data/conciliaciones/`, fuera de Git.

Después de la conciliación, el proyecto deja de usar esta cuenta. Su consumo se conserva
en el registro con su referencia propia y no se mezcla con el de otra cuenta.

### Cuenta actual (`tavily-cuenta-2`)

| Campo | Valor observado |
|---|---|
| Fecha | 2026-10-11 (America/Bogota) |
| Cuenta | Plan gratuito «Researcher»; el panel mostraba 0 / 1.000 créditos y *pay as you go* desactivado |
| Origen de financiación | `free_credit`; desembolso USD 0 |
| Autorización | Responsable del cupo, en la sesión: 1 búsqueda `basic` de comprobación, ≤ 1 crédito, USD 0 |

| Operación | Parámetros principales | Llamadas | Créditos reservados | Créditos según `usage` | Latencia | Resultado |
|---|---|---:|---:|---:|---|---|
| Search | Los mismos de la tabla anterior | 1 | 1 | 1 | 2,2 s | 10 resultados, 10 hosts candidatos y 5 seleccionados, uno reutilizado de una campaña anterior |
| Extract | Los mismos de la tabla anterior; portada `https://<dominio>/` más las URLs observadas, 3 páginas como máximo por empresa | 7 (una por empresa pendiente) | 7 | 1 | 0,5–1,8 s | 23 fragmentos guardados. 5 portadas sin `www` fallaron con «Failed to fetch url» (no se cobran). Un directorio se rechazó localmente sin llamar |

Campaña de comprobación: Colombia, `fintech_software`, `web_queries=1` y `max_companies=5`.
La búsqueda se concilió el 2026-10-11 con el panel de Tavily, verificado por el responsable:
1 / 1.000 créditos, USD 0. El comprobante local queda en `data/conciliaciones/`.

Las extracciones (autorización en la sesión: ≤ 7 créditos, USD 0) sumaron 1 crédito según
`usage`; se conciliaron el 2026-10-12 con el panel (véase «Orquestación de campaña»). Después de extraer, la resolución
local de identidad confirmó 1 empresa más. El resto quedó pendiente por país o nombre no
confirmados. Mantener *pay as you go* desactivado evita cargos fuera del crédito gratuito (§14).

### Observaciones y limitaciones

- La respuesta incluyó `usage.credits` y `request_id`. En Extract, `usage.credits` fue 0 con
  una URL por llamada, como anticipa la documentación: cobra 1 crédito por cada 5
  extracciones exitosas. La reserva sigue siendo de 1 crédito por llamada.
- Calidad de candidatos: de los 5 seleccionados, dos son empresas colombianas con producto
  pertinente. Los otros tres son un directorio de software, un artículo de blog de un
  proveedor y un dominio `.es` de fuera del país. La selección por host no distingue
  directorios ni país; queda para resolver identidad y exclusiones.
- Las pruebas no observaron errores 401, 429 ni 432/433; esos casos solo se verifican con
  respuestas sintéticas.
- Los créditos se observaron en la respuesta; el saldo del panel después de las llamadas no
  se volvió a consultar, ni siquiera para la conciliación.

## Anthropic (Claude Haiku 5.5)

| Campo | Valor observado |
|---|---|
| Fecha | 2026-10-11 (America/Bogota) |
| Cuenta | `anthropic-equipo-prepago`; saldo prepago; cupo asignado por el responsable: USD 3 (partida de IA, §14) |
| Autorización | Responsable del cupo, en la sesión: 3 autorizaciones de 1 llamada `messages` a `claude-haiku-5-5`, ≤ USD 0,005 cada una (prompts v1, v2 y v3) |
| Cliente | SDK oficial `anthropic==1.11.0`, `max_retries=0`, timeout ≤ 30 s |
| Parámetros | `thinking={"type": "disabled"}`, `output_config.effort="low"`, salida JSON con esquema (`output_config.format`), `max_tokens=1000`, prompts `haiku_assessment_v1` a `haiku_assessment_v3` |
| Documentación | Referencia oficial de la API de Claude (modelos, precios y parámetros), consultada el 2026-10-11 |

| Prompt | Tokens de entrada | Tokens de salida | Costo reservado | Costo estimado | Latencia | Resultado |
|---|---:|---:|---:|---:|---|---|
| v1 | 5.288 | 939 | USD 0,0011 | USD 0,000998 | 9,6 s | Respuesta válida; todas las referencias existen; evaluación `medium` (encaje 55,6, cobertura 90 %) de la empresa confirmada de la campaña de prueba |
| v2 | 5.347 | 736 | USD 0,0011 | USD 0,000903 | 6,0 s | Respuesta válida y referencias existentes; justificaciones de 11–14 palabras (antes 20–38). Misma empresa y evidencia: evaluación `high` (encaje 75,0, en el umbral; cobertura 90 %) |
| v3 | 5.508 | 679 | USD 0,0011 | USD 0,000890 | 5,5 s | Respuesta válida; todas las citas son fuentes primarias. Misma empresa y evidencia: evaluación `medium` (encaje 55,6; cobertura 90 %), con `document_need` 0,5 justificado por la falta de captura de comprobantes |

El costo estimado sale de los tokens que informó la respuesta y del precio publicado. Las tres
llamadas suman USD 0,0027913; se conciliaron el 2026-10-12 con la consola de Anthropic, que
mostró exactamente 16.143 tokens de entrada y 2.354 de salida.

### Observaciones y limitaciones

- El API aceptó el esquema (con `enum` que incluye `null` y `format: uuid`), el *thinking*
  desactivado y el *effort* `low`.
- Con v1, la salida usó 939 de 1.000 tokens y se arriesgaba a quedar truncada. Con v2 usó
  736 y con v3, 679, que dejan margen. Una respuesta truncada deja la evaluación pendiente;
  no se inventa.
- La entrada usó unos 5.300 de los 6.000 tokens reservados, con unos 3,4 caracteres por
  token. El presupuesto de caracteres (3 por token) deja margen, aunque estrecho.
- **Calidad:** con la misma evidencia, `document_need` pasó de 0,5 (v1) a 1 (v2), y la
  prioridad, de `medium` a `high`. Las referencias de v2 existen, pero los fragmentos citados
  hablan de facturación electrónica y conciliación bancaria, no de recibir o procesar
  comprobantes. Además, la explicación de v2 afirma una «captura de recibos» que no aparece
  en esas páginas. Su justificación de `offer_match` citaba el resumen del buscador y
  repetía el texto de la consulta («gestión de gastos que escanea recibos»). La validación
  automática comprueba referencias, no si la fuente respalda la afirmación.
- **Corrección (v3):** la evidencia del buscador llega a Haiku sin la consulta y marcada
  como `search_result`. Un `1` exige una afirmación explícita (en `document_need`, recibir o
  procesar comprobantes) y Python rechaza los `1` apoyados solo en resultados de búsqueda.
  Con la misma evidencia, v3 volvió a `document_need` 0,5 y a `medium`, citando solo
  fuentes primarias y sin afirmaciones ausentes de las páginas.
- Son tres llamadas sobre una sola empresa: muestran que el prompt influye en la
  clasificación cerca de los umbrales, pero no miden calidad ni calibración (T10). La
  revisión humana de §6 sigue siendo necesaria.

## Hunter (histórico)

Registro de la ruta anterior a T12. Hunter ya no se llama ni se puede autorizar; desde T17 la
configuración rechaza su cupo. Las cifras se conservan como línea base.

| Campo | Valor observado |
|---|---|
| Fecha | 2026-10-12 (America/Bogota) |
| Cuenta | `hunter-equipo-plan-gratuito`; plan Free; el responsable informó 50 créditos sin uso en el panel |
| Origen de financiación | `free_credit`; desembolso USD 0 |
| Autorización | Responsable del cupo, en la sesión: 2 autorizaciones de 1 `domain_search`, ≤ 3 créditos cada una, USD 0 (comprobación y medición de precio). Finder y Verifier no habilitados (falta comprobar que el guardado automático de leads está desactivado) |
| Endpoint usado | `GET https://api.hunter.io/v2/domain-search` con `Authorization: Bearer` |
| Documentación | [API v2](https://hunter.io/api-documentation/v2), [precios](https://hunter.io/pricing) y [consumo de la API](https://help.hunter.io/en/articles/1970956-hunter-api), consultadas el 2026-10-12 |

| Operación | Parámetros principales | Llamadas | Créditos reservados | Créditos observados | Latencia | Resultado |
|---|---|---:|---:|---:|---|---|
| Domain Search | `domain` confirmado, `type=personal`, `job_titles` de la evaluación, `limit=1`, `offset=0` | 1 | 1 | 1 | 0,55 s | 1 persona con nombre completo y cargo pertinente; correo del dominio de la empresa con verificación `valid` de Hunter y un perfil de LinkedIn sin confirmar |
| Domain Search (medición de precio) | Mismo dominio, sin filtro de cargo, `limit=3`; sin guardar contactos | 1 | 3 | 1 según el panel | 0,58 s | 3 correos nuevos devueltos; el panel pasó de 1 a 2 créditos usados |

Campaña de prueba: Colombia, `fintech_software`; empresa confirmada de prioridad `medium`.
Resultado comercial: `qualified_no_contact`. Hunter no demuestra que el empleo esté vigente;
las reglas de §10 exigen una fuente fechada o un directorio corporativo actual, que la ruta
pública (Tavily más Haiku) puede aportar. La etapa se ejecutó solo con Hunter. Los datos de
la persona quedan en `data/` y no se reproducen aquí. Conciliado el 2026-10-12 con el panel
de Hunter, verificado por el responsable: 1 crédito usado y 49 disponibles, USD 0. El
comprobante local queda en `data/conciliaciones/`.

### Observaciones y limitaciones

- **Precio de Domain Search, medido:** la página de precios indica 1 crédito por correo
  encontrado, y el artículo de consumo de la API, 1 crédito por cada 1 a 10 correos
  devueltos. Una búsqueda con 3 correos nuevos costó 1 crédito, así que en la API se cobra
  por llamada. Por eso el código conserva `limit=10` con una reserva de 1 crédito y no
  estima consumo de Hunter (la respuesta no lo informa). Las correcciones que asumían un
  cobro por correo se revirtieron el mismo día.
- La llamada de medición quedó registrada con 3 créditos observados, una estimación por
  correo de las correcciones revertidas, mientras el panel cobró 1. El registro no permite
  sustituir un consumo ya anotado, así que esa fila queda sin conciliar: sobrestima el
  consumo en 2 créditos, del lado prudente. La primera llamada sí quedó conciliada.
- No se probaron Finder, Verifier ni errores reales (401, 403, 429, 451); solo con
  respuestas sintéticas.

## Orquestación de campaña (T07)

| Campo | Valor observado |
|---|---|
| Fecha | 2026-10-12 (America/Bogota) |
| Autorización | Responsable del cupo, en la sesión: Tavily `search` ≤ 12 créditos y `extract` ≤ 8 créditos (`tavily-cuenta-2`, USD 0); Haiku `messages` ≤ USD 0,01 (`anthropic-equipo-prepago`); Hunter `domain_search` ≤ 4 créditos (`hunter-equipo-plan-gratuito`, USD 0). Finder y Verifier, deshabilitados |
| Campaña | Colombia, `fintech_software`, `max_companies=2`, `discovery.web_queries=1`; sin lista de exclusiones (`missing`) |
| Ejecución | `start_campaign` y `run_campaign` sobre la base local, en 28,1 s; estado final `completed` |

| Operación | Llamadas | Créditos reservados | Créditos según `usage` | Costo reservado | Costo estimado | Latencia |
|---|---:|---:|---:|---:|---:|---|
| Tavily Search (descubrimiento, ampliación y contactos) | 4 | 4 | 4 | USD 0 | USD 0 | 2,2–3,5 s |
| Tavily Extract (inicial, ampliación y contactos) | 4 | 4 | 1 | USD 0 | USD 0 | 0,3–5,5 s |
| Haiku `messages` (calificación y extracción de contactos) | 2 | — | — | USD 0,0022 | USD 0,0016 | 2,9–5,6 s |
| Hunter Domain Search | 1 | 1 | sin dato | USD 0 | USD 0 | 0,8 s |

Resultado: el descubrimiento devolvió 9 resultados y seleccionó 2 empresas, una reutilizada
de una campaña anterior. Una quedó con identidad pendiente por país sin confirmar: se amplió
una vez su evidencia con la búsqueda restringida al dominio (`include_domains`, aceptada por
Tavily con 1 crédito) y una página más, y siguió sin confirmar el país, así que terminó como
`insufficient_evidence`. La otra se calificó `medium`; Domain Search y la ruta pública no
dieron una persona con empleo vigente demostrable, y terminó como `qualified_no_contact`
(`contact_plan_exhausted`). Repetir `run_campaign` sobre la campaña terminada no creó ninguna
solicitud. Los datos de empresas y personas quedan en `data/` y no se reproducen aquí.

### Observaciones y limitaciones

- La calificación usó 6.175 tokens de entrada, por encima de los 6.000 que reserva la
  llamada; el costo estimado (USD 0,000961) siguió dentro de la reserva porque la salida usó
  687 de 1.000 tokens. Con la salida al máximo, el costo superaría la reserva y el registro
  bloquearía nuevas llamadas hasta revisarlo. El payload medía 13.757 bytes (unos 2,2 por
  token): desde entonces la reserva usa esos bytes más 1.000 tokens de margen.
- La extracción de contactos con Haiku devolvió 10 tokens de salida, sin candidatos.
- Conciliación del 2026-10-12, con los paneles que mostró el responsable: Tavily 7 / 1.000
  créditos (2 antes de la prueba), igual a `usage`; Hunter 1 de 50 en un ciclo iniciado ese día
  a las 15:49 y sin uso previo según el responsable, que usa su cuenta personal: el registro lo
  anota con la referencia `hunter-equipo-plan-gratuito`, que ya tenía consumo de otra cuenta,
  y sobrestima el uso. Las 2 llamadas a Haiku se conciliaron con el uso que informó la API,
  aceptado por el responsable porque la consola aún no las mostraba.

## Lote real de la T09

| Campo | Valor observado |
|---|---|
| Fecha | 2026-10-12 (America/Bogota): lote 1 a las 22:25 y lote 2 a las 22:57 |
| Ejecución | Desde la interfaz Streamlit de entonces, retirada el 13 de octubre al migrar a Django; dos campañas de 8 empresas con Colombia y México, `fintech_software` y `cpg_loyalty`, sin palabras clave ni lista de exclusiones (`missing`). Lote 1 en 110 s y lote 2 en 140 s; ambos terminaron `partial` |
| Cuentas | `data/provider-access.json` con los paneles vistos por el responsable a las 21:58: Tavily 7 / 1.000 créditos y *pay as you go* desactivado; Hunter 49 de 50 disponibles; Anthropic, cupo prepago de USD 3. La cuenta de Hunter es la que T07 anotó como `hunter-equipo-plan-gratuito`; desde la T09 se registra como `hunter-cuenta-2` |
| Autorización | Responsable del cupo, en la interfaz y para cada lote: Tavily `search` ≤ 50 créditos y `extract` ≤ 30 (`tavily-cuenta-2`, USD 0); Haiku `messages` ≤ USD 0,08 (`anthropic-equipo-prepago`); Hunter `domain_search` ≤ 16 créditos (`hunter-cuenta-2`, USD 0). Finder y Verifier, deshabilitados |

| Operación | Lote | Llamadas | Sin respuesta (timeout) | Créditos reservados | Créditos conciliados | Costo reservado | Costo conciliado | Latencia de las respuestas |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Tavily Search | 1 | 19 | 1 | 19 | 19 | USD 0 | USD 0 | 1,1–4,6 s |
| Tavily Extract | 1 | 11 | 1 | 11 | 2 | USD 0 | USD 0 | 0,4–1,7 s |
| Haiku `messages` | 1 | 7 | 0 | — | — | USD 0,0140338 | USD 0,0059353 | 1,6–8,5 s |
| Hunter Domain Search | 1 | 3 | 0 | 3 | 1 | USD 0 | USD 0 | 0,4–0,6 s |
| Tavily Search | 2 | 19 | 1 | 19 | 19 | USD 0 | USD 0 | 1,4–4,4 s |
| Tavily Extract | 2 | 14 | 3 | 14 | 5 | USD 0 | USD 0 | 0,4–1,7 s |
| Haiku `messages` | 2 | 9 | 0 | — | — | USD 0,0205942 | USD 0,0086865 | 1,3–5,4 s |
| Hunter Domain Search | 2 | 5 | 0 | 5 | 0 | USD 0 | USD 0 | 0,3–0,6 s |

Las 8 búsquedas de descubrimiento de cada lote respondieron. Entre los dos lotes se corrigió el
análisis inicial: la página que había localizado a cada empresa no se extraía porque la evidencia
del nombre inferido la daba por leída. El lote 2 se ejecutó con esa corrección y sin el directorio
de software que el lote 1 tomó por empresa. Los resultados están en
[la evaluación de la T09](evaluation.md); las empresas y personas quedan en `data/`.

### Conciliación

- **Tavily**: el panel pasó de 7 a 28 créditos tras el lote 1 y a 52 tras el lote 2. El ledger de
  `tavily-cuenta-2` confirma 52. Las respuestas informaron 20 y 23 créditos. De las 6 llamadas sin
  respuesta, el panel cobró 1 por lote: se anotó a la búsqueda con timeout de cada lote y 0 a las
  extracciones. Esa atribución por fila es una inferencia (una búsqueda básica cobra 1; la
  extracción, 1 por cada 5 URLs exitosas); el total por cuenta es exacto.
- **Hunter**: el panel pasó de 1 a 2 créditos tras el lote 1 y siguió en 2 tras el lote 2. De las 8
  búsquedas, solo la que devolvió personas cobró 1 crédito: una Domain Search sin resultados no
  consume crédito.
- **Haiku**: la consola del 13 de octubre (UTC) mostró 43.133 tokens de entrada y 3.244 de salida,
  exactamente los del lote 1, que se concilió con el costo estimado de esos tokens. Tras
  el lote 2 la consola sumó 110.418 y 7.160 tokens ese día; los 67.285 y 3.916 restantes son
  exactamente los del lote 2, conciliado del mismo modo.
- **Uso fuera del ledger**: la consola del 12 de octubre (UTC) suma 43.428 y 3.820 tokens; el ledger
  de esta base, 28.413 y 3.051. La diferencia (15.015 y 769 tokens, unos USD 0,0019) es uso de la
  organización registrado en otra parte. Según el responsable, corresponde a pruebas de otro
  integrante desde otra instancia; esta base no puede comprobarlo.
- Los comprobantes están en `data/conciliaciones/` (`*-t09-lote1.json` y `*-t09-lote2.json`).

### Observaciones y limitaciones

- 6 de 63 llamadas a Tavily (9,5 %) no respondieron en el plazo del cliente, unos 10 s; las que
  respondieron tardaron 4,6 s como máximo. Ninguna se repitió: dejaron pendientes la identidad de dos
  empresas y los contactos de otras dos.
- Hunter devolvió personas en 1 de 8 búsquedas con los cargos de la evaluación. Las empresas
  reutilizadas del lote 1 volvieron a consultar Hunter porque la nueva evaluación propuso otros
  cargos y cambió la huella de la solicitud.
- La reserva de Haiku, acotada por los bytes del payload, fue unas 2,4 veces el costo estimado.
- La fila de Hunter de la T07 con 3 créditos anotados sigue sin conciliar (sobrestima 2 créditos).

## Lote real de la entrega (T11)

| Campo | Valor observado |
|---|---|
| Fecha | 2026-10-14 (America/Bogota), de 07:47 a 07:49 |
| Ejecución | Desde la interfaz Django (`uv run --locked --env-file .env python manage.py runserver 127.0.0.1:8000 --noreload`); campaña `fd1660c9` con Colombia, México, `fintech_software` y `cpg_loyalty`, 8 empresas, sin palabras clave ni lista de exclusiones (`missing`). Terminó `partial`, con unos 100 s de llamadas |
| Cuentas | `data/provider-access.json` actualizado con los paneles vistos por el responsable a las 07:39–07:40: Tavily 52 / 1.000 créditos y *pay as you go* desactivado; Hunter 48 restantes de 50; consola de Anthropic con USD 0,02 en 30 días y saldo de la organización de USD 4,98. El cupo de Haiku pasó de USD 3 a USD 2,9981 para descontar el uso fuera del ledger de T09 |
| Autorización | Responsable del cupo, en el chat y en la interfaz: Tavily `search` ≤ 50 créditos y `extract` ≤ 30 (`tavily-cuenta-2`, USD 0); Haiku `messages` ≤ USD 0,08 (`anthropic-equipo-prepago`); Hunter `domain_search` ≤ 16 créditos (`hunter-cuenta-2`, USD 0). Finder y Verifier, deshabilitados |

| Operación | Llamadas | Sin respuesta (timeout) | Créditos reservados | Créditos conciliados | Costo reservado | Costo conciliado | Latencia de las respuestas |
|---|---:|---:|---:|---:|---:|---:|---|
| Tavily Search | 17 (8 de descubrimiento) | 0 | 17 | 17 | USD 0 | USD 0 | 1,6–3,8 s |
| Tavily Extract | 12 | 0 | 12 | 4 | USD 0 | USD 0 | 0,4–1,9 s |
| Haiku `messages` | 10 | 0 | — | — | USD 0,0226414 | USD 0,0094070 | 1,7–10,8 s |
| Hunter Domain Search | 4 | 0 | 4 | 2 | USD 0 | USD 0 | 0,4–0,8 s |

Ningún consumo superó su tope. Los resultados están en [la evaluación](evaluation.md#lote-real-de-la-entrega-t11);
las empresas y personas quedan en `data/`.

### Conciliación

- **Tavily**: el panel pasó de 52 a 73 créditos (08:23). La suma de las respuestas, 17 de búsqueda
  y 4 de extracción, coincide con el salto de 21; el ledger de `tavily-cuenta-2` confirma 73.
- **Hunter**: el panel pasó de 2 a 4 créditos usados (08:24). Dos de las cuatro búsquedas
  devolvieron personas y se anotó 1 crédito a cada una; las otras dos, 0. La respuesta no informa
  créditos: la atribución por fila es una inferencia, pero el total por cuenta es exacto.
- **Haiku**: 72.970 tokens de entrada y 4.220 de salida por el precio publicado. Se concilió con el
  uso que informó la API, sin captura de la consola, porque el responsable lo aceptó, como en T07.
  El ledger acumula USD 0,0283956.
- Los comprobantes están en `data/conciliaciones/` (`*-2026-10-14-t11.json`). Antes del lote y de
  la conciliación se guardaron copias de la base en `data/backups/`.

### Observaciones y limitaciones

- Ninguna llamada quedó sin respuesta, frente al 9,5 % de T09.
- La reserva de Haiku volvió a ser unas 2,4 veces el costo conciliado.
- Las solicitudes a Haiku usaron entre 3.388 y 8.721 tokens de entrada. El límite de 6.000 se
  aplica como presupuesto de caracteres, y 23 de las 31 llamadas registradas en esta base lo
  superaron en tokens. El gasto sigue acotado por la reserva, que se calcula por bytes. Tras el
  lote se calibró la estimación en 2 caracteres por token y el límite pasó a 9.000 tokens, con
  las mismas solicitudes ([calificación](qualification.md)).
