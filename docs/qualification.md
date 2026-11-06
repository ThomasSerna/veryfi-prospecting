# Calificación con Haiku

`qualify_company(db, budget, ClaudeClient(budget), campaign_id, company_id,
account_ref=..., funding_source=..., authorization=..., evaluation_dir=None)` califica una empresa de la
campaña. Haiku propone y Python decide:

- **Sin llamada a Haiku:** una empresa excluida recibe `excluded`. Una identidad no
  confirmada o sin evidencia útil recibe `insufficient_evidence`, con los cinco
  criterios en `null`.
- **Solicitud:** usa el modelo `claude-haiku-5-5`, *thinking* desactivado y
  *effort* `low`. Las campañas sin taxonomía conservan `haiku_assessment_v3` con
  `rubric_v1` y `haiku_assessment_v4` con `rubric_v2`. Las campañas con
  `role_taxonomy_v1` usan `haiku_assessment_v5`, con el criterio de escala de la
  rúbrica elegida y perfiles respaldados por citas.
  V1 sigue predeterminada hasta cumplir la [condición de activación de v2](Business-rules.md#candidata-enterprise-rubric_v2).
  - La salida es JSON con esquema. El límite de entrada es
    `limits.llm.max_input_tokens` (9.000 tokens) y el de salida,
    `limits.llm.max_output_tokens`. La evidencia se selecciona con 2 caracteres por token,
    calibrados el 2026-10-14 con 15 solicitudes reales (de 2,11 a 2,26 caracteres por token
    facturado, incluido el prompt de la salida estructurada). Hasta ese día se estimaban 3 y el
    límite era de 6.000 tokens, por lo que las solicitudes llegaban a unos 8.200 tokens. Las
    campañas preparadas antes conservan 6.000 en su instantánea: si se reanudan, sus solicitudes
    nuevas se limitan a 12.000 caracteres.
  - El prompt limita cada justificación a 25 palabras, la explicación a dos frases y
    los datos pendientes a tres. Una versión nueva del prompt genera una evaluación
    nueva que revisa la anterior (`revision_of`); la anterior se conserva.
  - Un `1` exige una afirmación explícita, y ante la duda entre dos niveles se elige
    el menor. Para `document_need`, el `1` exige que el producto reciba o procese
    comprobantes; emitir facturas o conciliar bancos es, como máximo, `0.5`. La
    explicación solo puede afirmar hechos de la evidencia citada.
  - La evidencia de la empresa va como datos delimitados y no confiables: primero
    las fuentes primarias, sin la evidencia de contactos ni las revisiones manuales.
    Los resultados del buscador llegan marcados como `search_result` y sin el texto
    de la consulta, que no es un hecho sobre la empresa.
- **Validación:** Haiku devuelve un valor `0`, `0.5`, `1` o `null` por criterio, con
  `evidence_ids` y justificación, además de productos, cargos, contradicciones y datos
  faltantes. Python rechaza los ids no suministrados, los valores conocidos sin
  evidencia, los productos o cargos fuera de la configuración y los `1` que solo se
  apoyan en resultados del buscador. No los corrige.
- **Perfiles:** v5 propone `profile_matches` con `profile_id` y citas literales
  (`evidence_id`, `quote`). Python acepta solo perfiles de la empresa y la campaña,
  respaldados por evidencia empresarial observada suministrada, sin contradicción,
  distinta de revisiones manuales y resultados de búsqueda. Los productos compartidos
  no prueban por sí solos un perfil.
  Sin perfil respaldado, la lista queda vacía y no se busca en Apollo.
- **Puntuación:** Python calcula `fit_score` y `coverage` con los pesos de la
  rúbrica de la instantánea de campaña. `null` no suma peso ni equivale a cero. La prioridad sigue las reglas
  de IDEA.md §8.2 con los umbrales de la rúbrica: `high` exige además que la
  necesidad documental cite una fuente primaria.
- **Guardado:** se guardan juntos el `Assessment` (modelo exacto, versiones de prompt y
  rúbrica) y el `RunItem` en la etapa `assessed`.
  - `low` fija el resultado comercial `low_fit`.
  - `insufficient_evidence` queda en el `stop_reason`, sin fijarse como resultado
    comercial, porque aún cabe una ampliación de evidencia.
  - Repetir la calificación reutiliza la evaluación guardada. La única excepción es una
    evaluación `insufficient_evidence` con evidencia de empresa posterior (no manual ni de
    contactos) que entra en la solicitud, como la de la ampliación: entonces se consulta de
    nuevo a Haiku y la evaluación nueva revisa la anterior (`revision_of`).

En v2, el contexto de tamaño distingue entidad, filial y grupo. La señal numérica
de empleados solo se prepara con identidad y ámbito aplicable y con evidencia
observada primaria o de proveedor sin contradicción; un dato de grupo no se aplica
automáticamente a una filial ni se infiere que la cuenta sea la matriz. El prompt
exige respaldo en la evidencia suministrada, considera la financiación solo como
contexto y conserva `null` cuando falta información o hay contradicción sobre el
mismo dato y ámbito. Los otros cuatro criterios mantienen su significado v1. La
revisión manual de reglas de T14 no acredita cómo responderá Haiku a v4.

`ClaudeClient` (`prospecting/providers/claude.py`) usa el SDK oficial `anthropic` con la clave de `ANTHROPIC_API_KEY`,
`max_retries=0` y un timeout de 30 s como máximo. Sigue el mismo protocolo de
reserva, reclamación y registro que `ProviderClient`. El modelo y la forma común de
la solicitud estructurada están en `prospecting/haiku.py`; el prompt y su validación,
en `prospecting/qualification.py`.

- **Presupuesto:** cada llamada reserva el costo máximo con los precios publicados
  (USD 0,10 por millón de tokens de entrada y USD 0,50 por millón de salida). La
  entrada se acota con los bytes UTF-8 del payload que se envía más 1.000 tokens para
  el prompt que Anthropic inyecta con las salidas estructuradas; la salida, con
  `max_tokens`. La estimación de caracteres por token solo dimensiona el prompt y no
  basta como cota: el 2026-10-12 un payload de 13.757 bytes se facturó como 6.175
  tokens (unos 2,2 bytes por token), por encima de los 6.000 que se reservaban. Con los
  límites iniciales una calificación reserva como máximo unos USD 0,0025. Se registran
  los tokens y el costo estimado; la conciliación sigue siendo manual. El cupo de la
  cuenta `anthropic` se configura con `AccountAllowance`, con origen `prepaid` o
  `new_outlay` y `cost_limit_usd`.
- **Fallos:** un rechazo (`refusal`), una respuesta truncada (`max_tokens`), un JSON o
  una validación inválidos, o un error HTTP, de red o de timeout dejan la evaluación
  pendiente (`assessment_pending:<motivo>`) con el mensaje literal. Se conserva la
  evidencia y no se reintenta ni se cambia de modelo.

## Captura optativa para evaluación

El argumento `evaluation_dir=Path("data/evaluation/traces")` conserva una traza
por invocación en un subdirectorio nuevo con identificador UUID. Sin ese argumento
el flujo sigue funcionando sin crear artefactos de evaluación. La captura no
autoriza consumo ni cambia la solicitud, la reserva o las reglas de reutilización.
Solo admite rutas bajo el `data/` de este repositorio, resueltas antes de reservar;
una carpeta externa con ese nombre no cumple la protección.

`input.json` guarda campaña, empresa, evidencia de empresa, ids seleccionados,
payload exacto, versiones, commit y hashes del código. Después de reservar se
guarda `request.json`; `response.json` conserva el texto original y el motivo de
terminación, incluso si no supera la validación. `result.json` contiene el informe,
la evaluación si existe, el consumo y la duración medida de la invocación.
`manifest.json` registra hashes e integridad de la captura. No se copian claves,
autorizaciones ni registros de contactos.

Reutilizar una evaluación o decidir sin Haiku produce una instantánea sin respuesta
cruda, duración de inferencia ni consumo inventados. Esos artefactos sirven para
auditar el resultado guardado; no reconstruyen una llamada histórica.

Si falla la captura antes del envío, no se consulta al proveedor. Una reserva ya
creada se conserva sin envío para conciliación. Si falla después de la llamada,
el gasto y los checkpoints se conservan y el informe y la ficha registran la
traza incompleta. No se repite una llamada para reparar archivos faltantes ni
se descarta una evaluación válida por ese fallo.

El [protocolo de evaluación](t10-evaluation.md) describe la revisión atribuida,
las particiones independientes y la lectura offline de estos artefactos. Una
captura comprobada con transporte sintético no demuestra una ejecución real.
La interfaz no activa esta captura: el protocolo incluye la invocación explícita
de la etapa con la base y el presupuesto compartidos. Una pérdida de captura
se informa aparte de la clasificación conservada y no elimina sus métricas
comerciales observadas; impide presentar un replay exacto.
