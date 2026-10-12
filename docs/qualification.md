# Calificación con Haiku

`qualify_company(db, budget, ClaudeClient(budget), campaign_id, company_id,
account_ref=..., funding_source=..., authorization=...)` califica una empresa de la
campaña. Haiku propone y Python decide:

- **Sin llamada a Haiku:** una empresa excluida recibe `excluded`. Una identidad no
  confirmada o sin evidencia útil recibe `insufficient_evidence`, con los cinco
  criterios en `null`.
- **Solicitud:** usa el modelo `claude-haiku-5-5` con el prompt versionado
  `haiku_assessment_v3`, *thinking* desactivado y *effort* `low`.
  - La salida es JSON con esquema. El límite de entrada es
    `limits.llm.max_input_tokens` (unos 3 caracteres por token) y el de salida,
    `limits.llm.max_output_tokens`.
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
- **Puntuación:** Python calcula `fit_score` y `coverage` con los pesos de
  `rubric_v1`. `null` no suma peso ni equivale a cero. La prioridad sigue las reglas
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

`ClaudeClient` (`prospecting/providers/claude.py`) usa el SDK oficial `anthropic` con la clave de `ANTHROPIC_API_KEY`,
`max_retries=0` y un timeout de 30 s como máximo. Sigue el mismo protocolo de
reserva, reclamación y registro que `ProviderClient`. El modelo y la forma común de
la solicitud estructurada están en `prospecting/haiku.py`; el prompt y su validación,
en `prospecting/qualification.py`.

- **Presupuesto:** cada llamada reserva el costo máximo con los precios publicados
  (USD 0,10 por millón de tokens de entrada y USD 0,50 por millón de salida): unos
  USD 0,0011 con los límites iniciales. Se registran los tokens y el costo estimado;
  la conciliación sigue siendo manual. El cupo de la cuenta `anthropic` se configura
  con `AccountAllowance`, con origen `prepaid` o `new_outlay` y `cost_limit_usd`.
- **Fallos:** un rechazo (`refusal`), una respuesta truncada (`max_tokens`), un JSON o
  una validación inválidos, o un error HTTP, de red o de timeout dejan la evaluación
  pendiente (`assessment_pending:<motivo>`) con el mensaje literal. Se conserva la
  evidencia y no se reintenta ni se cambia de modelo.
