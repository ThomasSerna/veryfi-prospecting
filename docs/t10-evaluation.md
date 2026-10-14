# Evaluación independiente de la calificación con Haiku

Protocolo de T10, del 13 de octubre de 2026 (America/Bogota), basado en IDEA.md
§8, §12.2, §17.2, §18.2 y §19. La evaluación distingue encaje observable,
aceptación comercial y contactabilidad. Un `high` o `medium` no equivale a una
cuenta aceptada por Veryfi; disponer de un correo tampoco aumenta el encaje.

## Estado de partida y decisiones pendientes

La línea base de producción es `rubric_v1` con `haiku_assessment_v3`. El catálogo
`catalog_v1` conserva su validación pendiente y la rúbrica sigue propuesta. Este
protocolo no cambia pesos, umbrales, catálogo, prompts ni reglas de listo.

[La T09](evaluation.md) documenta dos lotes reales de ocho empresas: 16
selecciones, 10 dominios distintos, cinco empresas calificadas distintas y cero
empresas listas. No midió precisión comercial ni falsos positivos: faltaba la
revisión de Veryfi. Las 713 pruebas de aquel informe usan datos sintéticos.
Los lotes también difieren en el código de extracción y de descarte de
directorios, por lo que no constituyen una comparación controlada de prompts.

La comprobación de T05 en [provider-check.md](provider-check.md#anthropic-claude-haiku-55)
comparó v1, v2 y v3 sobre una misma empresa. V2 confundió facturación y
conciliación bancaria con recepción de comprobantes, citó texto de la consulta
del buscador y produjo una afirmación sin respaldo. V3 corrigió ese caso.
Este antecedente sirve para desarrollo y regresión; no demuestra precisión
general y no puede entrar en el conjunto independiente.

En la copia local examinada el 13 de octubre, la base contenía una campaña
CO/FinTech de dos empresas, no los dos lotes publicados de T09; tampoco estaban
sus comprobantes de conciliación. Antes de reutilizar T09, el responsable debe
localizar sus artefactos originales y los identificadores de campaña, empresa,
evaluación y solicitud. El informe agregado no permite reconstruirlos. No crear
identificadores supuestamente originales ni reemplazar la base local para
resolver esa ausencia. Si los artefactos no aparecen, registrar la limitación y
usar el informe como antecedente documental.

Veryfi aún debe aportar o confirmar ejemplos positivos y negativos, catálogo,
exclusiones, criterios comerciales y una persona disponible para revisar con
el apoyo de ventas que corresponda. Hasta que exista evidencia de esa revisión,
las etiquetas comerciales permanecen pendientes. Las metas orientativas de
80 % de aceptación y 90 % de pertinencia de IDEA §18.2 no son criterios ya
validados ni resultados de T10.

## Selección, separación y revisión humana

El desarrollo reúne los casos T05/T09 recuperables, errores conocidos y fixtures
sintéticas. Registrar qué casos influyeron en una decisión de rúbrica o prompt.
Las empresas usadas en esas decisiones quedan fuera de evaluación independiente,
incluidas sus variantes de nombre, dominio y entidad. Cuando se conozca una
matriz, marca o filial relacionada, registrar y revisar la relación antes de
considerarlas independientes; no inferirla solo por semejanza de nombres.

El objetivo inicial independiente es 20 empresas nuevas: cinco por cada
combinación CO/MX y `fintech_software`/`cpg_loyalty`. Incluir cuentas prometedoras,
negativas y fronterizas sin seleccionar únicamente las clasificadas `high` o
`medium`. Congelar la selección antes de observar sus errores. Registrar
procedimiento de selección, fecha, duplicados descartados y tamaño logrado;
si hay menos casos, informar los conteos y celdas vacías. Esta muestra no permite
afirmar cobertura de toda Latinoamérica.

Cada caso conserva identidad y evidencia fechada. Congelar tanto la evidencia
recuperada como la entrada realmente suministrada a Haiku, incluidos selección
y recortes. Si falta evidencia para resolver un criterio, la referencia es
`null`, no cero. La ausencia de confirmación de identidad es distinta del rechazo
comercial de una empresa correctamente identificada.

La anotación independiente debe preceder a la exposición de la predicción. El
revisor recibe los datos del caso y las fuentes suministradas, sin score,
prioridad, explicación del modelo ni etiquetas sugeridas. Registra:

- Aceptación comercial, rechazo con motivo o decisión pendiente; responsable,
  fecha, referencia y alcance de la revisión de Veryfi.
- Los cinco criterios `0`, `0.5`, `1` o `null`, sus fuentes y justificaciones;
  productos pertinentes, contradicciones y suficiencia de evidencia.
- Qué afirmaciones clave están realmente respaldadas por el fragmento citado.
  Una URL existente no demuestra que respalde la afirmación.

Una revisión por el equipo académico se identifica como tal y no cuenta como
aceptación de Veryfi. Un desacuerdo no resuelto mantiene la etiqueta pendiente;
se registra su resolución posterior como una revisión nueva. La revisión desde
la UI existente muestra la predicción y sirve para retroalimentación de
desarrollo, pero no es una anotación ciega. Nunca describir como ciega una
revisión hecha después de ver el resultado.

El campo que atribuye una etiqueta a Veryfi es un registro documental, no una
autenticación de la identidad del revisor. El equipo debe comprobar su referencia
y el alcance de su participación antes de presentar esa etiqueta como revisión
efectiva de Veryfi. La presencia del valor `Veryfi` no certifica el criterio
comercial ni sustituye esa comprobación.

No se usan nombres ni canales de personas para evaluar la calificación de
empresas. La contactabilidad y la pertinencia de personas conservan las reglas
y métricas de T09; no se relajan para aumentar la aceptación comercial.

## Evidencia, versiones y reproducción

Los casos, entradas, respuestas y revisiones reales viven en `data/`, fuera de
Git. En el repositorio solo quedan el protocolo, el evaluador, fixtures
declaradas sintéticas y conclusiones agregadas sin datos personales. No copiar
contactos, claves ni cuerpos de respuestas con datos personales a pruebas,
logs, commits o informes.

El origen se declara explícitamente. `synthetic` identifica datos o respuestas
simulados. `new_real` identifica una captura prospectiva y `saved_real`
identifica la reproducción de una respuesta real guardada: permite auditarla
sin consumo nuevo, pero no es una nueva llamada ni una nueva observación
independiente. No mezclar esos orígenes en una cifra de calidad real.

El origen es una declaración, no una prueba de acceso o autorización. La captura
prospectiva declara `new_real` si existe una solicitud nueva y `saved_real` si
reutiliza una evaluación o decide sin modelo. Los ejemplos de evaluación se
producen desde el inicio con origen `synthetic`. No reetiquetar una traza original
de un cliente simulado ni sobrescribirla para convertirla en un ejemplo: si su
productor declaró otro origen, conservar el original y documentar explícitamente
la derivación de un artefacto sintético nuevo con hashes nuevos. `called_model` indica que se
intentó el transporte del cliente, que también puede ser simulado en pruebas.
Para describir una ejecución como real hacen falta su procedencia, autorización
y registro de uso, no solo esos campos.

Conservar por ejecución la versión del conjunto y sus etiquetas, el commit,
modelo exacto, parámetros, catálogo, rúbrica, prompt, entrada y respuesta
exactas, hashes y vínculos a evidencia, evaluación y solicitud. Registrar
tiempos, tokens, costo observado o estimado y sus límites de atribución.
Las revisiones apuntan al registro anterior; no sobrescriben una evaluación o
etiqueta para hacerla coincidir con el último criterio comercial.

Un hash detecta cambios en un artefacto; no acredita su origen ni la calidad de
su contenido. Verificar procedencia, fechas, integridad y correspondencia de
identificadores antes de ejecutar la evaluación. No reconstruir una entrada
histórica usando la evidencia actual y llamarla idéntica a la original.

La reproducción offline aplica validación, cálculo de score y métricas sobre
los artefactos guardados. Una nueva consulta a Haiku puede devolver una respuesta
distinta; conservarla como ejecución nueva. Comparar versiones sobre la misma
evidencia congelada, con el mismo conjunto y etiquetas, para separar mejoras de
interpretación de cambios en la investigación de fuentes.

El flujo reutiliza los contratos `Company`, `Evidence`, `Assessment`, `Campaign`
y `Usage`, y la validación y clasificación existentes. No añade una base de
evaluación, proveedor, framework ni UI nueva. Los archivos de evaluación son
artefactos locales que no migran ni recrean el esquema de SQLite.

La captura prospectiva se solicita con el parámetro opcional `evaluation_dir`
de `qualify_company`, apuntando a un directorio bajo el `data/` de este repositorio.
Las rutas se resuelven antes de reservar; una carpeta externa llamada `data`
o una ruta que escape de la raíz protegida se rechaza. Su esquema
es `evaluation_trace_v1` y conserva:

- `input.json`: campaña, empresa y evidencia sin contactos, ids seleccionados,
  payload exacto cuando haya solicitud, versiones, commit, hashes del código y
  fecha de captura.
- `request.json`: solicitud reservada con id/huella. Puede existir sin llamada
  cuando la captura falla después de reservar o se agota el plazo antes del envío.
- `response.json`: respuesta del cliente, incluso si su contenido no supera la
  validación. Solo existe si llegó una respuesta; un timeout no la fabrica.
- `result.json`: evaluación, informe, uso y duración observada; `called_model`
  distingue la llamada de una evaluación reutilizada o decidida sin Haiku.
- `manifest.json`: hashes SHA256, estado completo y errores de captura.

La captura no llama a un proveedor por sí misma. Una instantánea sin respuesta
original o una traza sin solicitud nueva se audita como `audit_only`; una traza
con solicitud pero sin respuesta se identifica como `trace_without_response`.
Ninguna reproduce el modelo. Una evaluación
reutilizada no recibe una latencia ficticia de cero.
Cuando existe llamada, `duration_seconds` mide la etapa completa de calificación,
incluida la preparación y captura; no la latencia exclusiva de Haiku.
Si falta o cambia un artefacto exigido, no presentar la traza como completa.
Un fallo de proveedor puede tener traza completa sin respuesta: conserva el
motivo literal y el consumo incierto en lugar de inventar una salida. Conservar
los errores posteriores al envío junto al gasto y al resultado ya registrados;
no repetir una llamada para disimular una captura incompleta.

### Comprobaciones de reproducción

El replay lee el bloque `<evidencia>` de los mensajes originales y comprueba
identificadores, procedencia y fragmentos contra la instantánea. Los hashes
correctos no bastan si la evidencia declarada difiere de la enviada. No se
reconstruye una solicitud antigua con el prompt actual. Un formato de mensajes
no reconocido queda como `audit_only`, con
`context_reproducibility="unverified_format"`; no admite una comparación de
prompts basada en supuesta igualdad de entrada.

La puntuación y cobertura se recalculan con los criterios y la rúbrica
congelados; una prioridad imposible bajo las condiciones disponibles se
rechaza. `Assessment` histórico no conserva las contradicciones propuestas
por Haiku ni prueba por sí solo una exclusión: las condiciones incompletas se
declaran con `classification_reproducibility="partial_conditions"`, sin
inventarlas. Un contrafactual necesita reproducir primero la clasificación base.

`error_reason` describe el fallo de calificación; `capture_error_reason` y
`capture_metadata.capture_errors` describen pérdidas de captura por separado.
Una evaluación válida persistida sigue contando en TP/FP/FN/TN cuando su
referencia comercial está resuelta, aunque falte la respuesta cruda. Su modo
es `incomplete_trace`, sin replay, y el resumen cuenta `capture_errors`.
Una pérdida de archivos no elimina un falso positivo observado. Sin evaluación
válida el caso permanece pendiente y conserva el motivo técnico original.

### Invocación de captura desde el pipeline

La interfaz y `run_campaign` no activan la captura opcional. Para capturar la
calificación de una empresa ya investigada, usar la etapa existente desde
Python, con la base compartida abierta y el mismo `Budget` y cupos comprobados.
El ejemplo presupone esos objetos, los UUID guardados y un permiso vigente;
no crea campañas, reinicia cupos ni concede autorización:

```python
from pathlib import Path
import time

from prospecting.pipeline import qualify_company
from prospecting.providers import ClaudeClient

report = qualify_company(
    db, budget, ClaudeClient(budget), campaign_id, company_id,
    account_ref=claude_account_ref,
    funding_source=claude_funding_source,
    authorization=session_authorization,
    deadline=time.monotonic() + remaining_active_seconds,
    evaluation_dir=Path("data/evaluation/traces/dataset-v1"),
)
```

`session_authorization` debe proceder de `budget.authorize` con proveedor
`anthropic`, operación `messages`, cuenta y tope explícitamente aprobados en
la sesión. `remaining_active_seconds` respeta los límites restantes de empresa
y campaña; la captura no amplía el plazo. Usar la SQLite existente, no abrir
una base nueva para la evaluación, y no ejecutar simultáneamente la campaña
desde otra instancia. Capturar la etapa de calificación no exige buscar contactos.

Si ya existe una evaluación suficiente, la función la reutiliza y captura una
auditoría histórica; no produce una nueva inferencia ni evalúa otro prompt.
No borrar la evaluación para forzar consumo. Cambiar prompts o el significado
de criterios requiere una propuesta aprobada y respuestas nuevas autorizadas.
Antes de enviar, congelar selección, versiones, evidencia y etiquetas ciegas.
Después, conservar la traza original y enlazar su `manifest.json` mediante
`FileReference` en una versión nueva del conjunto. Un fallo posterior al envío
se registra sin repetir la llamada.

## Uso offline y formatos de entrada

El comando de evaluación lee un manifiesto `evaluation_manifest_v1` con casos,
referencias a instantáneas o trazas y sus etiquetas. Las instantáneas emplean
`evaluation_snapshot_v1`; las etiquetas, `evaluation_label_v1`. Una etiqueta
enlaza su `snapshot_sha256`, conserva el id de evaluación cuando ya se conoce y
declara decisión `accepted`, `rejected` o `pending`, tipo de referencia,
responsable, organización, motivo, fecha y referencia documental. El vínculo al
hash evita aplicar una revisión a otra evidencia sin advertirlo. Las referencias
de archivo contienen `path` relativo al directorio del conjunto y `sha256`
calculado sobre los bytes exactos. No se admiten rutas absolutas ni `..`.

`inventory.historical_group_keys` conserva claves normalizadas del inventario
T05/T09, por ejemplo `domain:empresa.example`, `company:<UUID>`,
`name:empresasintetica` o `group:matrizsintetica`. `group_keys(snapshot, case)`
permite obtenerlas con las mismas reglas del evaluador. Las referencias del
inventario deben acreditar su revisión y cobertura; un inventario vacío mantiene
la independencia pendiente aunque sus campos de estado digan `verified`.

Para un ejemplo mínimo completo, usar una **traza sintética** generada por la
fixture `add_trace(..., origin="synthetic")` de `tests/test_evaluation.py` y
conservar sus archivos originales en `data/evaluation/synthetic-v1/trace/`.
No usar directamente las trazas de clientes simulados que declaran `new_real`.
El caso debe corresponder a CO/FinTech. Este código genera un manifiesto sin
etiquetas y calcula el hash existente; no fabrica evidencia ni hace llamadas:

```python
import hashlib
import json
from pathlib import Path

dataset = Path("data/evaluation/synthetic-v1")

def reference(relative):
    return {
        "path": relative,
        "sha256": hashlib.sha256((dataset / relative).read_bytes()).hexdigest(),
    }

manifest = {
    "schema_version": "evaluation_manifest_v1",
    "dataset_version": "synthetic_v1",
    "created_at": "2026-10-13T12:00:00Z",
    "inventory": {
        "status": "pending",
        "historical_coverage": "pending",
        "reference": "Ejemplo sintético; inventario real T05/T09 pendiente.",
        "historical_group_keys": [],
    },
    "cases": [{
        "case_id": "synthetic_01",
        "split": "development",
        "origin": "synthetic",
        "country": "CO",
        "segment": "fintech_software",
        "group_keys": ["synthetic_group_01"],
        "artifact": reference("trace/manifest.json"),
        "label": None,
    }],
}
with (dataset / "manifest-unreviewed.json").open("x", encoding="utf-8") as stream:
    json.dump(manifest, stream, ensure_ascii=False, indent=2)
```

Los comandos siguientes ilustran exclusivamente un conjunto **sintético**
preparado con los contratos de las pruebas; no identifican una campaña real ni
afirman que ese conjunto exista en `data/`:

```console
uv run --locked python evaluate_qualification.py data/evaluation/synthetic-v1/manifest-unreviewed.json --output data/evaluation/reports/synthetic-v1 --prepare-blind data/evaluation/blind/synthetic-v1
```

Se generan `synthetic_01-blind.json` y `synthetic_01-label-template.json`. La ficha
contiene los datos de empresa necesarios, catálogo y rúbrica con su versión,
sin predicción. `evidence_scope="submitted"` incluye solo la evidencia enviada
cuando se conoce esa selección. `evidence_scope="available_only"` señala que
solo hay evidencia disponible, sin acreditar la entrada original del modelo;
no describir esa ficha como reproducción de la evidencia enviada. La plantilla conserva
`snapshot_sha256`, `assessment_id=null`, `reference_type="academic"`,
`prediction_visible=false`, aceptación pendiente y criterios/auditorías vacíos.
No es una etiqueta válida hasta rellenar responsable, rol, organización,
referencia, fecha y motivo: los `null` de la plantilla no son datos del revisor.

Cuando existe payload original, `submitted_messages` muestra los fragmentos
exactos con los recortes que recibió Haiku. Si solo se conocen los ids
seleccionados, las fuentes disponibles no garantizan esos recortes: la auditoría
histórica sigue siendo exploratoria. No atribuir al modelo un error basado en
texto adicional que no consta en su entrada.

Anotar antes de consultar el informe. Guardar la revisión en un archivo nuevo
dentro del conjunto, por ejemplo `labels/synthetic_01-v1.json`; las etiquetas
de este ejemplo se identifican como sintéticas y académicas. Para evaluarla,
crear una versión nueva del manifiesto con `case.label` igual a
`reference("labels/synthetic_01-v1.json")`, conservando el hash del artefacto
revisado. Usar el mismo procedimiento para el hash de cada etiqueta nueva.
No editar una revisión ya evaluada; `previous_sha256` permite enlazar su versión
anterior. Cambiar `reference_type` a `Veryfi` solo tras verificar esa atribución
y conservar su referencia efectiva.

Cada ejecución requiere directorios nuevos para resultados y fichas. El comando
comprueba hashes y referencias y genera JSON y Markdown; no necesita claves,
no llama a proveedores y no abre ni modifica la base SQLite. Si falta un
artefacto o hay una referencia incompatible, corregir el conjunto mediante una
versión nueva, sin sobrescribir resultados para ocultar el fallo.

Una rúbrica candidata se evalúa por separado:

```console
uv run --locked python evaluate_qualification.py data/evaluation/synthetic-v1/manifest-unreviewed.json --rubric data/evaluation/candidates/synthetic-rubric-v2.json --output data/evaluation/reports/synthetic-rubric-v2
```

El archivo candidato contiene `version` y `rubric`; esta última conserva la
semántica de la rúbrica original y solo puede variar pesos y umbrales. `--rubric`
vuelve a aplicar las reglas deterministas a los mismos valores
guardados; no demuestra cómo interpretaría Haiku una rúbrica o prompt nuevos.
Para medir ese efecto hace falta una respuesta nueva, autorizada y capturada.
La opción `--compare OTHER_MANIFEST` compara ejecuciones conservadas: debe
mantener los casos, evidencia y etiquetas comparables, y declarar cualquier
diferencia que impida atribuir un cambio de resultado a la configuración.

La API offline es `evaluate_manifest(path, candidate=None)` y el informe
Markdown se genera con `render_markdown(report)`. Los casos de
`tests/test_evaluation.py` son el ejemplo ejecutable sintético del formato y de
sus fallos; no reutilizar sus etiquetas como revisión de Veryfi.

## Medición y análisis de errores

Reportar siempre numerador, denominador y casos pendientes, en total y por
país/segmento. Un denominador cero produce «no calculable»; no cero ni una
conclusión favorable. Separar fallo de API, respuesta inválida y abstención por
evidencia insuficiente de un rechazo comercial explícito.

Para la decisión comercial, `high` o `medium` es una selección positiva. La
referencia comercial es la aceptación o el rechazo explícito del revisor
de Veryfi; los casos sin esa revisión no entran en precisión ni falsos positivos.
Conservar los conteos de las demás prioridades y fallos para que los casos
pendientes no desaparezcan del informe.

La matriz TP/FP/FN/TN usa solo casos con prioridad `high`, `medium` o `low` y
referencia comercial resuelta. `low` es la decisión negativa. Las abstenciones
`insufficient_evidence`, las exclusiones y los fallos quedan fuera de esa
matriz y se cuentan aparte. `accepted_not_selected` incluye aceptadas con `low`,
abstención, fallo o exclusión; `accepted_excluded` separa las exclusiones de cuentas
aceptadas. Estos conteos muestran pérdidas sin convertirlas en negativos verdaderos.

| Medida | Interpretación y denominador |
|---|---|
| Precisión de seleccionadas | Aceptadas por Veryfi entre seleccionadas revisadas; equivale a `TP / (TP + FP)` |
| Fracción de seleccionadas rechazadas | `FP / (TP + FP)`; complemento de precisión, distinto de la tasa de falsos positivos |
| Falsos positivos | Seleccionadas rechazadas por Veryfi; mostrar el conteo y `FP / (FP + TN)` sobre negativos de referencia con decisión computable |
| Falsos negativos | Prioridad `low` aceptada por Veryfi; las aceptadas con abstención se informan por separado |
| Desacuerdo por criterio | Valores Haiku distintos de la anotación de referencia entre criterios comparables, distinguiendo `null` de cero |
| Trazabilidad semántica | Afirmaciones realmente respaldadas entre afirmaciones auditadas; separar procedencia faltante de cita que no sustenta el texto |
| Cobertura de evaluación | Casos con referencia comercial resuelta entre casos del conjunto; registrar quién revisó y cuáles siguen pendientes |
| Tiempo y gasto | Duración de las operaciones, minutos de revisión, tokens y costo atribuible; separar lo pagado previamente del costo incremental de reproducir |

El evaluador separa resultados por `origin` y `reference_type` y presenta las
proporciones con intervalos Wilson del 95 %. Un intervalo resume incertidumbre
del conteo, pero no corrige una selección sesgada, etiquetas sin verificar ni
falta de independencia. Sin etiquetas resueltas, hay información de cobertura,
validación y consumo; no hay un resultado de precisión comercial.

El tiempo de revisión y la línea base manual requieren un registro humano
separado con referencia; el evaluador no los obtiene de `duration_seconds`.
Si faltan, declarar que no se midieron y no calcular ahorro. La duración capturada
de calificación tampoco equivale al tiempo total del flujo de descubrimiento y
contactos; ese tiempo necesita su medición propia.

La matriz de prioridades requiere una referencia por criterio y condiciones de
clasificación comparables; aceptación comercial por sí sola no determina si la
prioridad esperada es `high` o `medium`. No interpretar el score como
probabilidad de compra ni sensibilidad de esta muestra como recall del mercado.
Si el conjunto se enriqueció deliberadamente con negativos, dejar constancia:
sus métricas describen ese conjunto, no la prevalencia comercial de LATAM.

Clasificar cada error por su evidencia: identidad/exclusión, fuente ausente o
recortada, interpretación de criterio, producto sin respaldo, afirmación
inventada, contradicción, regla de clasificación o fallo técnico. Antes de
cambiar un prompt, comprobar si el fallo procede de lo que llegó al modelo.
Los ids válidos y las pruebas de invariantes no sustituyen esa comprobación
semántica.

## Ajustes, autorización y conclusión

Un candidato de cambio nace de errores documentados del conjunto de desarrollo
o retroalimentación verificable de Veryfi. Registrar problema, casos afectados,
cambio propuesto, efecto esperado y aprobación cuando corresponda. Cambiar
pesos, umbrales, catálogo o arquitectura exige la aprobación establecida en
AGENTS.md; no modificar IDEA.md implícitamente. Un ajuste de prompt conserva
una versión nueva y sus regresiones, sin borrar v3 ni evaluaciones anteriores.

Evaluar el candidato sobre desarrollo antes de abrir el conjunto independiente.
Congelar configuración y decisión de comparación, y ejecutar el conjunto
independiente una vez para sustentar la conclusión. Si sus errores se usan para
el siguiente ajuste, esos casos pasan a desarrollo y se necesita un conjunto
independiente nuevo. No probar reiteradamente variantes sobre el mismo holdout
y seguir llamándolo independiente.

Las comparaciones reales pasan por `prospecting.pipeline` y sus reservas y
registro de gasto. Cada llamada exige autorización de la sesión con proveedor,
operación y tope. La autorización de T05/T09 no autoriza nuevas llamadas; la
reproducción offline es la opción inicial. No activar Tavily, Hunter, Apollo
ni otro modelo como consecuencia de ejecutar el evaluador.

La conclusión debe indicar versiones y cantidad de casos, revisiones reales
disponibles, métricas y errores, incertidumbre por tamaño/selección, gasto y
limitaciones. Una muestra sin etiquetas de Veryfi puede verificar el mecanismo
y describir errores técnicos; no valida precisión comercial. Una prueba
sintética verifica cálculos y contratos; no valida Haiku con datos reales.

T10 queda comercialmente pendiente hasta disponer de revisión documentada de
Veryfi, un conjunto independiente verificable y una conclusión sustentada.
La falta de validación o presupuesto se registra explícitamente, sin inventar
resultados ni compensarla relajando las reglas del flujo.

## Pendientes de cierre y entrega

| Pendiente | Evidencia necesaria para resolverlo | Estado |
|---|---|---|
| Inventario histórico T05/T09 y ajustes v1–v3 | Artefactos originales e IDs de campaña, empresa, evaluación y solicitud; alias, dominios y grupos conocidos | Pendiente; el informe agregado no demuestra independencia |
| Conjunto independiente | Selección congelada de hasta 20 empresas nuevas, cinco por celda CO/MX × FinTech/CPG; procedimiento, fecha y solapamientos comprobados | Pendiente; informar tamaño logrado y casos incompletos |
| Referencias de Veryfi | Revisor y rol comprobados, fecha, procedencia, aceptación separada de criterios/productos y motivos; nuevas versiones para correcciones | Pendiente; la revisión académica o desde UI no acredita validación de Veryfi |
| Calidad comercial | Evaluaciones reales y etiquetas comparables; métricas, intervalos, pérdidas, errores y costos atribuibles en `evaluation.md` | Pendiente; fixtures solo verifican el mecanismo |
| MVP y T11 | Demostración documentada de al menos un prospecto real completo, informe reproducible y límites de producción | [Informe de entrega](delivery.md), README verificado y límites de producción listos (14 oct). El prospecto real sigue pendiente: T09 y el lote de la entrega (14 oct) terminaron con cero listos, por falta de evidencia de empleo vigente. La demo sintética no lo sustituye |
| Catálogo, exclusiones y gasto | Confirmación documentada de Veryfi y conciliación del uso histórico, incluido el observado fuera del ledger | Pendiente; no activar nuevas fuentes ni multiplicar el cupo |

Recuperar originales sin modificar la base existente y conservarlos inmutables
bajo `data/`; los grupos agrupan para particionar sin fusionar entidades.
Si faltan identificadores históricos, mantener `inventory.status` o
`historical_coverage` pendiente. Ninguna autorización de T05/T09 habilita nuevas
consultas. La conclusión agregada distinguirá resultados reales de simulados,
costo de evaluación de costo total y estimado de conciliado. Sin línea base
manual no hay ahorro demostrado. Apollo y X-Ray no son requisitos de este cierre.
