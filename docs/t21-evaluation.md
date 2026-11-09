# Evaluación enterprise con Apollo frente a Hunter (T21)

Estado del 8 de noviembre de 2026 (America/Bogota). T21 sigue abierta: se ha
preparado la evaluación sin red, pero todavía no hay un lote real independiente
de T21 ni una revisión comercial atribuible a Veryfi. Las pruebas sintéticas
comprueban cálculos y contratos; no miden la calidad comercial ni demuestran un
resultado real de Apollo.

## Condiciones previas

El equipo decidió evaluar `rubric_v2` primero con el protocolo académico de T14
y usar una muestra diferente para el lote de T21. La activación de v2 en campañas
nuevas requiere superar la condición de [Business-rules.md](Business-rules.md#candidata-enterprise-rubric_v2).
Las campañas conservan `rubric_v1` como opción predeterminada hasta entonces.

La auditoría local encontró dos informes de T14, ambos solo de desarrollo, con
12 casos en total y la activación pendiente. En ambos faltan revisiones completas,
independencia comprobada y una cohorte enterprise aceptada evaluable. Los tres
manifiestos examinados mantienen pendiente el inventario o su cobertura histórica;
no se encontró un protocolo congelado ni un marcador de apertura del conjunto
independiente. Cerrar el issue técnico T14 no acredita que su condición de
activación se haya cumplido. El procedimiento y los criterios completos están en
[t10-evaluation.md](t10-evaluation.md#comparación-manual-enterprise-de-t14).

El 8 de noviembre se ejecutó de nuevo, sin red, la partición de desarrollo:

```console
uv run --locked python evaluate_qualification.py data/evaluation/t14-v1/manifest-review-ready.json --rubric data/evaluation/t14-v1/candidate.json --manual-reviews data/evaluation/t14-v1/manual-reviews-ready.json --partition development --output data/evaluation/t21/t14-development-audit-2026-11-08
```

Terminó con código 0 y dejó el informe privado en el directorio de salida. El
resultado mantiene `independence_pending`, `incomplete_reviews` y
`no_accepted_enterprise_cohort`; las posiciones medias son `null` y el gate sigue
`pending` por `development_only`. No se abrió la partición independiente. Para
repetir la auditoría, usa un directorio de salida nuevo; los artefactos originales
permanecen en `data/` y no se versionan.

La base local examinada conserva una campaña antigua, dos empresas, un contacto
y 17 registros de consumo, sin operaciones Apollo. No se recuperaron los originales
ni respaldos de los lotes históricos durante esta auditoría. Sus informes son
antecedentes documentales, no trazas aptas por sí solas para replay o para acreditar
la independencia de una muestra. No se reemplaza ni recrea la base para suplirlos.

No hay cuentas o roles de evaluación ni una persona revisora confirmados por
Veryfi. Tampoco existe autorización de esta sesión para un lote real. Antes de
ejecutarlo se necesitan el gate de T14 superado, una selección independiente,
acceso y cupos comprobados, y autorización explícita del responsable para cada
proveedor, operación y tope. Una autorización pasada no habilita consumo nuevo.

Se comprobó la celda Colombia/FinTech con el plan pendiente y sin llamadas a
proveedores. El preflight quedó `blocked` por `authorization_required`,
`independence_pending`, `ledger_consolidation_pending`,
`ledger_schema_unverified` y `t14_gate_pending`. La captura y el reporte
agregado están en `data/evaluation/t21/preflight-2026-11-08-final/`; el reporte
indica QA incompleto, cobertura real pendiente y validación comercial pendiente.
Su etiqueta de origen `real` identifica el plan previsto, no una llamada o una
observación real del lote T21.

Comandos registrados para esa comprobación, que ya tienen salida y no se pueden
repetir con las mismas rutas:

```console
uv run --locked python evaluate_enterprise_pipeline.py run data/evaluation/t21/inputs-2026-11-08/plan.json --country CO --segment fintech_software --db data/prospecting.sqlite3 --access data/provider-access.json --approvals data/evaluation/t21/inputs-2026-11-08/approvals-not-authorized.json --output data/evaluation/t21/preflight-2026-11-08-final
uv run --locked python evaluate_enterprise_pipeline.py report data/evaluation/t21/preflight-2026-11-08-final/capture.json --output data/evaluation/t21/preflight-2026-11-08-final/aggregate.json
```

El archivo de autorización indicado no existía deliberadamente. Cambiar las
entradas o completar las condiciones puede habilitar una ejecución real; no se
trata de un modo de simulación.

## Captura y reporte

`evaluate_enterprise_pipeline.py` prepara y ejecuta una celda por invocación.
Antes de la ejecución comprueba el gate de T14, la independencia, el ledger, el
acceso y la autorización. Con un plan y una configuración válidos, los bloqueos
de esas condiciones generan `preflight.json` y `capture.json` con estado `blocked`
y código 2, sin abrir SQLite ni llamar a proveedores. Si el plan o la configuración
no se pueden validar, el comando informa el error y puede no crear salidas. Si las
condiciones se cumplen, `run` ejecuta la campaña real y puede consumir los cupos
autorizados: no es un comando de simulación.

El plan privado `pipeline_evaluation_plan_v1` registra responsable, fecha y fuente,
política de selección, los cuatro identificadores de campaña y el inventario
histórico. La configuración, los archivos del gate T14 y las capturas anteriores
se referencian mediante ruta relativa al plan y SHA-256 de los bytes; el ledger
incluye su huella y la comprobación atribuida. El plan puede incluir capturas
anteriores para contrastar sus entidades; al preparar la campaña el evaluador
excluye también las empresas de otras campañas presentes en el ledger. Un
inventario o una cobertura histórica sin verificar mantienen la independencia
pendiente.

La autorización privada `pipeline_approval_session_v1` identifica una sesión y la
campaña de esa celda, la fecha UTC y la lista `approvals`. Cada autorización de
la lista contiene proveedor, operación, referencia de cuenta, topes en USD y
créditos, responsable y referencia de la autorización. Cada celda y reanudación
requiere una autorización nueva; el programa marca la sesión como utilizada en
`data/.t21-approvals/` antes de ejecutar y rechaza su reutilización. Esos
archivos no contienen claves. El ledger debe existir, estar consolidado y ser
compatible con el esquema vigente, sin escrituras WAL o journal pendientes; el
comando no recrea la base para pasar la comprobación.

Ejemplo de rutas locales para una celda, una vez preparada y autorizada:

```console
uv run --locked python evaluate_enterprise_pipeline.py run data/evaluation/t21/plan.json --country CO --segment fintech_software --db data/prospecting.sqlite3 --access data/provider-access.json --approvals data/evaluation/t21/approval-co-fintech.json --output data/evaluation/t21/run-co-fintech
```

Las rutas son ejemplos y deben apuntar a los archivos privados comprobados para
esa ejecución. El directorio de salida debe ser nuevo. Se conservan allí el
preflight y la captura con sus motivos; una interrupción o campaña parcial requiere
revisar el estado antes de reanudar con otra autorización.

Para generar un JSON agregado a partir de capturas conservadas:

```console
uv run --locked python evaluate_enterprise_pipeline.py report data/evaluation/t21/run-co-fintech/capture.json --output data/evaluation/t21/report-co-fintech.json
```

Se pueden indicar varias capturas antes de `--output`. El reporte verifica sus
huellas, no abre SQLite ni llama proveedores y no sobrescribe la salida. Las
capturas reales permanecen en `data/`; no se mezclan con capturas sintéticas. El
reporte no convierte una captura bloqueada en una observación real ni acredita
revisión comercial por sí solo.

En el JSON, `qa_status=reproducible` se refiere a la integridad de las capturas
recibidas; no implica que la campaña haya terminado ni que la muestra esté
completa. `real_coverage=measured` indica que hay capturas reales disponibles,
incluso si falta parte de la muestra. Consulta `sample.complete`, las celdas y
`campaign_statuses` antes de interpretar esa cobertura; la validación comercial
se informa aparte.

## Selección y medición

El objetivo es una muestra de 20 empresas nuevas: cinco por cada combinación de
Colombia/México y `fintech_software`/`cpg_loyalty`. Antes de ejecutar se congelan
la política de selección y los identificadores de campaña. Cada celda conserva
todas las empresas seleccionadas por descubrimiento, incluidas las negativas,
sin sustituirlas por su resultado. Las identidades de las cuatro celdas no están
congeladas de antemano; esta limitación debe constar junto con el procedimiento,
las fechas, las fuentes y los solapamientos revisados.

Quedan fuera los casos de las particiones de desarrollo y evaluación de T14 y los
utilizados para calibración; se contrastan también alias, dominios y relaciones
de matriz, filial o marca. Si los antecedentes no permiten verificar la
independencia o faltan celdas, esa condición se declara pendiente.

Se busca diversidad de tamaño dentro de esas cuatro combinaciones sin imponer
cuotas inventadas. La señal de tamaño solo se asigna con fuente, fecha y ámbito
aplicable a la cuenta; lo no respaldado queda desconocido, no se imputa como cero
ni se atribuye de la matriz a la filial. Se publican el tamaño conseguido, las
celdas vacías y los casos pendientes.

El informe debe conservar numerador y denominador de cada medida, en total y por
país, segmento y tamaño cuando exista respaldo:

- Empresas seleccionadas, identificadas, calificadas, investigadas en personas y
  aceptadas o rechazadas por una revisión comercial atribuible.
- Personas candidatas y pertinentes, funciones representadas, identidades y empleos
  verificados, correos profesionales y otros canales utilizables, y personas listas.
  Una búsqueda de personas, un correo utilizable y una empresa aceptada son medidas
  diferentes; el dato declarado por un proveedor no confirma el empleo.
- Fallos por etapa y motivo, duplicados, puestos obsoletos y empresas grandes sin
  caso de uso respaldado. Las abstenciones y los casos pendientes no se convierten
  en rechazos comerciales.
- Duración automática y tiempo de revisión cuando esté registrado; créditos y costo
  atribuible por proveedor y operación, distinguiendo reserva, consumo observado,
  conciliado y pendiente. Con denominador cero, el costo por contacto útil es
  «no calculable»; los créditos gratuitos se informan sin tratarlos como precio
  monetario conocido.

La revisión académica se identifica como tal. Sin revisión atribuible a Veryfi,
aceptación de empresas y pertinencia comercial permanecen pendientes. No se calcula
ahorro de tiempo sin una línea base manual equivalente. No se envían mensajes para
comprobar canales o empleo.

## Antecedentes disponibles

| Fuente | Alcance y resultado documentado |
|---|---|
| [T09](evaluation.md#lotes-reales), 12 de octubre | Dos lotes, 16 selecciones y 10 dominios distintos; Hunter devolvió personas en 1 de 8 búsquedas y hubo 0 empresas listas entre 5 empresas calificadas distintas. Los lotes compartieron empresas y cambiaron el código entre sí. |
| [T11](evaluation.md#lote-real-de-la-entrega-t11), 14 de octubre | Ocho selecciones; Hunter devolvió personas en 2 de 4 búsquedas y hubo 0 empresas listas entre 4 calificadas. Tres empresas se reutilizaron de lotes anteriores. |
| [T17](provider-check.md#lotes-reales-de-apollo-de-la-t17), 8 de noviembre | Siete selecciones en dos lotes; una empresa llegó a contactos. Apollo devolvió 20 resultados de búsqueda, nueve con función pertinente; tres enriquecimientos se rechazaron por `entity_mismatch`. Cero personas listas y tres créditos Apollo conciliados. |

Las 24 selecciones de T09/T11 no son 24 empresas distintas. T17 es una prueba de
acceso en una sola empresa investigada en contactos, insuficiente para estimar la
cobertura de Apollo. Los tres rechazos no conservan la respuesta original ni la
condición específica que falló, por lo que no se puede reconstruir su causa.

El costo por contacto útil de T17 no es calculable: no hubo personas listas. Para
comparar el costo del flujo completo se conservan por separado los créditos de
Tavily y Apollo y el costo estimado de Haiku del [registro de proveedores](provider-check.md#lotes-reales-de-apollo-de-la-t17).
Los antecedentes de Hunter están en [evaluation.md](evaluation.md); no se hacen
nuevas llamadas a Hunter.

## Verificación técnica

El 8 de noviembre pasaron 341 pruebas relacionadas con la evaluación, T14,
contactos, presupuesto, conciliación, arquitectura, persistencia y exportación:

```console
uv run --locked pytest tests/test_enterprise_pipeline_evaluation.py tests/test_enterprise_pipeline_safety.py tests/test_enterprise_evaluation.py tests/test_enterprise_qualification.py tests/test_multi_contact_pipeline.py tests/test_contact_ranking_pipeline.py tests/test_employment_status.py tests/test_apollo_migration.py tests/test_budget.py tests/test_reconciliation.py tests/test_architecture.py tests/test_persisted_identifiers.py tests/test_export.py
```

Después del último ajuste de privacidad del agregado se repitieron los dos módulos
de T21: 29 pruebas aprobadas. Este resultado no se suma a las 341 anteriores.

```console
uv run --locked pytest tests/test_enterprise_pipeline_evaluation.py tests/test_enterprise_pipeline_safety.py
```

Las pruebas usan datos sintéticos y bases temporales, sin llamadas a proveedores;
no sustituyen el lote real ni la revisión comercial.

## Comparación y cierre

La comparación offline de `rubric_v1` y `rubric_v2` sigue el protocolo de T14
sobre evidencia y revisiones comparables. Reaplicar pesos a valores guardados no
reproduce cómo respondería Haiku a otro prompt. La comparación offline de
`contact_match_v1` y `contact_match_v2` sobre personas ya observadas describe su
ordenación; no demuestra qué personas se habrían descubierto o enriquecido con
otro orden.

El informe final distinguirá evidencia original recuperada de agregados históricos,
versiones y fechas, resultados sintéticos, observaciones reales y revisión de
Veryfi. Incluirá los cambios simultáneos de muestra, descubrimiento, rúbrica,
selección de personas y proveedor: una comparación antes/después no demuestra por
sí sola qué cambio causó una diferencia ni permite generalizar a Latinoamérica.

El cierre técnico exige resultados reproducibles con denominadores y procedencia,
comprobación de seguridad y presupuesto, y conciliación o estado explícito de cada
consumo. La validación comercial requiere una muestra independiente respaldada y
revisión atribuible de Veryfi. Si faltan el gate, los originales, la muestra, las
autorizaciones o la revisión, se indican como pendientes; completar pruebas sin red
no sustituye esos resultados.
