# Evaluación de la T09: invariantes y lote real

Informe del 12 de octubre de 2026 (America/Bogota). Separa lo verificado con datos
sintéticos (las pruebas) de lo observado con proveedores reales (dos lotes de 8 empresas).
No contiene claves, datos personales ni nombres de empresas: los resultados reales quedan
en `data/`, fuera de Git. El registro de llamadas y la conciliación están en
[Comprobación de proveedores](provider-check.md#lote-real-de-la-t09).

## Pruebas

```console
uv lock --check
uv run --locked python -m pytest
```

Resultado: 713 pruebas en verde, sin red y con bases temporales. En Windows con Smart App
Control, `pytest.exe` puede quedar bloqueado; `python -m pytest` ejecuta la misma suite.
La T09 añadió cuatro casos: el contenido externo hostil se muestra como texto plano en la
interfaz, dos regresiones del análisis inicial y de la ampliación, y un directorio de
software más. Cada uno falla si se revierte la lógica que protege.

| Riesgo (IDEA §18.1) | Pruebas representativas |
|---|---|
| Puntuación engañosa | `test_qualification.py`: `test_documented_example_scores_88_9_with_90_percent_coverage`, `test_scale_only_scores_100_with_20_percent_coverage_and_does_not_pass`, `test_unknown_is_not_zero` |
| Mal uso del presupuesto | `test_budget.py::test_two_connections_cannot_reserve_the_same_remaining_balance`, `test_providers.py::test_no_balance_cannot_reach_transport`, `test_pipeline.py::test_timeout_keeps_uncertain_reservation` |
| Identidad incorrecta | `test_discovery.py::test_homonyms_and_subsidiaries_get_distinct_keys`, `test_db.py::test_shared_domain_does_not_merge_entities`, `test_contacts.py::test_employment_dates_and_contradictions_block_readiness` |
| Prospecto sin canal útil | `test_contacts.py`: `test_generic_phone_and_unannounced_whatsapp_are_not_usable`, `test_email_outside_the_company_domain_is_never_ready`, `test_primary_publication_can_support_accept_all_but_never_invalid` |
| Canal alternativo | `test_contacts.py::test_linkedin_requires_persisted_manual_confirmation_and_no_send`, `test_manual_confirmation.py::test_confirmation_needs_explicit_boolean_true`, `test_architecture.py::test_package_has_no_interface_messaging_or_browser_automation` |
| Datos incompletos | `test_contacts.py::test_partial_names_and_undated_verification_are_not_promoted`, `test_contact_pipeline.py::test_exhausted_empty_search_is_reused_between_campaigns` |
| Fallos de proveedor | `test_campaign.py::test_unavailable_provider_stops_the_pass_and_keeps_the_literal_reason`, `test_providers.py::test_invalid_response_is_persisted_without_releasing_cost`, `test_discovery.py::test_tavily_errors_have_specific_reasons` |
| Reruns y reinicio | `test_campaign.py`: `test_second_click_and_rerun_reuse_the_campaign_without_new_calls`, `test_interrupted_run_resumes_from_saved_steps_without_repeating_sent_calls` |
| Entrada hostil | `test_pipeline.py::test_hostile_search_content_is_data_only`, `test_qualification.py::test_hostile_evidence_cannot_raise_priority_or_budget` |
| Salida o URL insegura | `test_export.py::test_dangerous_text_is_neutralized_without_losing_content`, `test_providers.py::test_redirect_is_not_followed_and_cannot_receive_credentials`, `test_ui.py::test_hostile_external_text_is_rendered_only_as_plain_text` |
| Trazabilidad | `test_qualification.py::test_invalid_references_are_rejected`, `test_export.py::test_primary_has_only_current_eligible_people_and_preserves_sources_and_identifiers` |
| Reorganización altera datos guardados | `test_persisted_identifiers.py`: `test_request_fingerprints_do_not_change`, `test_sqlite_schema_does_not_change` |
| Dependencias invertidas | `test_architecture.py`: `test_internal_imports_follow_the_declared_direction`, `test_internal_imports_have_no_cycles` |

La prueba de huellas detectó durante la T09 un cambio no intencionado: la lista de
directorios viaja en `exclude_domains` de la búsqueda de descubrimiento, así que ampliarla
cambiaba la huella persistida. La corrección descarta el directorio nuevo solo en local.

Las pruebas no demuestran acceso a proveedores, calidad comercial ni contactabilidad real.

## Lotes reales

Dos campañas desde la interfaz, con Colombia y México, `fintech_software` y `cpg_loyalty`,
8 empresas, sin palabras clave y sin lista de exclusiones validada (`missing`). Hunter solo
con Domain Search. Entre el lote 1 y el lote 2 se corrigieron dos fallos que el lote 1
reveló:

- El análisis inicial y la ampliación daban por leída la página que localizó a la empresa,
  porque la evidencia del nombre inferido cita su URL. Dos sitios promocionales nunca se
  extrajeron y quedaron sin identidad.
- Un directorio de software entró como empresa y llegó a confirmar su identidad.

Resultados por combinación (país y segmento de la consulta que localizó a la empresa):

| Lote | Combinación | Seleccionadas | Identidad confirmada | Prioridad media | Contactos investigados | Personas listas |
|---:|---|---:|---:|---:|---:|---:|
| 1 | CO · FinTech | 2 | 2 | 2 | 2 (1 pendiente por timeout) | 0 |
| 1 | MX · FinTech | 2 | 1 | 1 | 1 | 0 |
| 1 | CO · CPG | 2 | 0 | 0 | 0 | 0 |
| 1 | MX · CPG | 2 | 1 (el directorio) | 0 | 0 | 0 |
| 2 | CO · FinTech | 2 | 2 | 2 | 2 | 0 |
| 2 | MX · FinTech | 2 | 2 | 2 | 2 (1 pendiente) | 0 |
| 2 | CO · CPG | 2 | 0 | 0 | 0 | 0 |
| 2 | MX · CPG | 2 | 1 | 1 | 1 (pendiente por timeout) | 0 |

- **Prioridad**: ninguna empresa llegó a `high` ni a `low`; el resto quedó `insufficient_evidence`.
- **Identidades pendientes**:
  - Lote 1: 4 por `identity_unverified`. Dos sitios no se extrajeron por el fallo corregido; en una
    landing la extracción no devolvió texto y su ampliación expiró; otra extracción quedó sin texto útil.
  - Lote 2: una por país sin confirmar, otra por nombre sin confirmar (un sitio promocional cuyo texto no
    coincide con el dominio) y otra por una extracción sin respuesta.
- **Efecto de la corrección**: una empresa mexicana que el lote 1 dejó pendiente se confirmó en el
  lote 2, y uno de los sitios promocionales obtuvo su primera página primaria.
- **Reutilización**: en el lote 2, 3 de las empresas confirmadas venían de lotes anteriores y se
  reutilizaron sin duplicarlas.
- **Contactos**: la etapa se ejecutó 8 veces sobre 5 empresas calificadas distintas.
  - Hunter devolvió personas en 1 de 8 Domain Search, para una empresa que ya tenía personas desde la T07.
  - Esas dos personas tienen identidad y función pertinente confirmadas, pero ninguna fuente aportó
    evidencia de empleo vigente.
  - La extracción pública con Haiku no produjo candidatos elegibles. Una respuesta citó texto que no
    estaba literalmente en la fuente y se rechazó (`unsupported_quote`), como exige la validación.
- **Exportación**: la de todos los resultados, generada sobre los datos reales, da 9 filas por lote y
  ninguna celda con un prefijo de fórmula sin neutralizar; la de prospectos listos está vacía.

### Métricas iniciales (IDEA §18.2)

| Métrica | Valor |
|---|---|
| Cobertura de contacto | 0 / 5 empresas calificadas distintas (lote 1: 0 / 3; lote 2: 0 / 5) |
| Canal preferido | No calculable: 0 empresas listas |
| Precisión de empresas y pertinencia de personas | Sin medir: requiere la revisión de Veryfi |
| Costo por prospecto aceptado | No calculable: 0 aceptados |
| Tiempo automático | 110 s y 140 s por lote de 8 empresas; sin línea base de investigación manual |
| Identidad confirmada | Lote 1: 3 / 8 empresas reales (más el directorio); lote 2: 5 / 8 |
| Llamadas sin respuesta | Tavily: 6 / 63 (9,5 %) |
| Búsquedas de personas con resultados | Hunter Domain Search: 1 / 8 |

Por segmento, en los dos lotes:

| Segmento | Seleccionadas | Identidad confirmada | Prioridad media |
|---|---:|---:|---:|
| FinTech | 8 | 7 | 7 |
| CPG | 8 | 2 (uno era el directorio) | 1 |

La muestra (16 selecciones y 10 dominios distintos) no permite generalizar la cobertura a
Latinoamérica ni a cada país o segmento.

## Real frente a sintético

| Origen | Qué incluye |
|---|---|
| Real | Las dos campañas, sus llamadas, la conciliación con los paneles y la exportación generada sobre esos datos (solo se contaron filas y celdas) |
| Sintético | Las 713 pruebas y la verificación de revisión humana, confirmación manual y CSV de `docs/ui.md` |

Ninguna persona real se revisó ni se confirmó manualmente.

## Gasto

| Cuenta | Lote 1 | Lote 2 | Total T09 | Estado |
|---|---:|---:|---:|---|
| Tavily `tavily-cuenta-2` (crédito gratuito) | 21 créditos | 24 créditos | 45 créditos | Conciliado: panel 52 / 1.000 |
| Hunter `hunter-cuenta-2` (crédito gratuito) | 1 crédito | 0 créditos | 1 crédito | Conciliado: panel 2 / 50, uno es de la T07 |
| Haiku `anthropic-equipo-prepago` | USD 0,0059353 | USD 0,0086865 | USD 0,0146218 | Conciliado: consola del 13 oct (UTC), 110.418 / 7.160 tokens |

El ledger del proyecto acumula USD 0,0189886 en Haiku y USD 0 en Tavily y Hunter. La
consola de Anthropic muestra además unos USD 0,0019 de uso de la organización que no están en
esta base; según el responsable, son pruebas de otro integrante desde otra instancia. El total
queda muy por debajo del límite de USD 20, del límite operativo de USD 15 y del de USD 2 por
campaña. La interfaz muestra el cupo, el margen y lo pendiente de conciliar.

## Estado frente a los criterios del MVP (IDEA §19)

| Criterio | Estado |
|---|---|
| Ejecución desde criterios que descubre empresas reales de los perfiles | Cumplido: 2 lotes, ambos países y segmentos |
| Evidencia, puntuación con desglose, esfuerzo y búsqueda de personas con Tavily y Hunter | Cumplido |
| Al menos un prospecto real completo | **No cumplido**: la contactabilidad sigue sin validar |
| Ningún registro listo incumple la regla de canal directo | Cumplido: 0 listos, sin relajar reglas |
| UI, revisión y exportación funcionan | Ejecución y exportación con datos reales; revisión y confirmación manual solo con datos sintéticos |
| Pruebas críticas en verde | Cumplido: 713 |
| Gasto conciliado ≤ USD 20, con cuota y margen visibles | Cumplido |
| Proveedores, limitaciones y siguiente mejora documentados | Este informe y `provider-check.md` |

## Limitaciones y siguiente mejora

- **Siguiente mejora prioritaria: la etapa de personas.** Con los cargos de la evaluación, Hunter
  Domain Search encontró personas en 1 de 8 empresas, y ninguna fuente pública aportó empleo vigente
  fechado. Medir frente a esta línea base una fuente adicional de personas (Apollo o X-Ray) y el uso
  de las páginas de equipo corporativas.
- **CPG**: los sitios promocionales casi nunca confirman nombre ni país, así que el segmento quedó con
  una sola empresa calificada.
- **Tavily**: el 9,5 % de las llamadas no respondió en unos 10 s y dejó etapas pendientes sin repetir
  gasto. Conviene revisar el plazo por operación.
- **Lista de exclusiones**: Veryfi aún no la ha entregado, así que las exclusiones comerciales no están
  validadas. El catálogo y la rúbrica siguen siendo una propuesta.
- **Interfaz**:
  - Cualquier interacción con la página durante una ejecución la interrumpe. Es seguro y reanudable,
    pero obliga a autorizar de nuevo.
  - Preparar una campaña mientras otra está activa abre la activa sin avisar.
- **Uso fuera del ledger**: el uso de Anthropic registrado fuera de esta base indica que no todas las
  ejecuciones del equipo pasaron por el mismo control de presupuesto.
