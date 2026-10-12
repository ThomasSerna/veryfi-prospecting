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

Campaña de comprobación: Colombia, `fintech_software`, `web_queries=1` y `max_companies=5`.
Conciliado el 2026-10-11 con el panel de Tavily, verificado por el responsable: 1 / 1.000
créditos, USD 0. El comprobante local queda en `data/conciliaciones/`. Mantener *pay as you
go* desactivado evita cargos fuera del crédito gratuito (§14).

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
