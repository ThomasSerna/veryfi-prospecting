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

Las extracciones (autorización en la sesión: ≤ 7 créditos, USD 0) están pendientes de
conciliar con el panel; según `usage`, sumaron 1 crédito. Después de extraer, la resolución
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
llamadas suman unos USD 0,0028, pendientes de conciliar con la consola de Anthropic.

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
| Autorización | Responsable del cupo, en la sesión: 1 `domain_search`, ≤ 3 créditos, USD 0. Finder y Verifier no habilitados (falta comprobar que el guardado automático de leads está desactivado) |
| Endpoint usado | `GET https://api.hunter.io/v2/domain-search` con `Authorization: Bearer` |
| Documentación | [API v2](https://hunter.io/api-documentation/v2), [precios](https://hunter.io/pricing) y [consumo de la API](https://help.hunter.io/en/articles/1970956-hunter-api), consultadas el 2026-10-12 |

| Operación | Parámetros principales | Llamadas | Créditos reservados | Créditos observados | Latencia | Resultado |
|---|---|---:|---:|---:|---|---|
| Domain Search | `domain` confirmado, `type=personal`, `job_titles` de la evaluación, `limit=1` (cupo de personas en prioridad media), `offset=0` | 1 | 1 | 1 (estimado: un correo devuelto) | 0,55 s | 1 persona con nombre completo y cargo pertinente; correo del dominio de la empresa con verificación `valid` de Hunter y un perfil de LinkedIn sin confirmar |

Campaña de prueba: Colombia, `fintech_software`; empresa confirmada de prioridad `medium`.
Resultado comercial: `qualified_no_contact`. Hunter no demuestra que el empleo esté vigente;
las reglas de §10 exigen una fuente fechada o un directorio corporativo actual, que la ruta
pública (Tavily más Haiku) puede aportar. La etapa se ejecutó solo con Hunter. Los datos de
la persona quedan en `data/` y no se reproducen aquí. Conciliado el 2026-10-12 con el panel
de Hunter, verificado por el responsable: 1 crédito usado y 49 disponibles, USD 0. El
comprobante local queda en `data/conciliaciones/`.

### Observaciones y limitaciones

- Precio de Domain Search: la página de precios indica 1 crédito por correo encontrado y
  el artículo de consumo de la API, 1 crédito por cada 1 a 10 correos devueltos. La
  reserva cubre el peor caso (un crédito por resultado pedido). Con `limit=1` ambos
  criterios coinciden, así que esta prueba no resuelve la discrepancia.
- No se probaron Finder, Verifier ni errores reales (401, 403, 429, 451); solo con
  respuestas sintéticas.
