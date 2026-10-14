# Comprobación de acceso a proveedores

Registro de las pruebas reales mínimas (IDEA.md §11.1). No contiene claves, datos
personales ni listas de empresas; los resultados quedan en la base local bajo `data/`.

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

## Hunter

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
