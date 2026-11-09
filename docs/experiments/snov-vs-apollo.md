# Comparación experimental de Snov.io y Apollo

Este experimento aísla la búsqueda y el enriquecimiento de personas en la rama
`experiment/snov-benchmark`. La preparación se comprueba con datos sintéticos;
todavía no demuestra acceso real a Snov.io ni compara la calidad o el costo de
ambos proveedores. La evaluación real posterior corresponde a [T23 (#28)](https://github.com/ThomasSerna/veryfi-prospecting/issues/28).

## Método

El lote real debe ser nuevo para ambos proveedores, sobre las mismas empresas y
cargos, con la misma evidencia empresarial y en una ventana temporal común. Se
mantienen el ICP, la rúbrica, las reglas de selección y la definición de contacto
útil. La comparación mide la ruta de contactos, no todo el descubrimiento o la
calificación de empresas. Los antecedentes históricos son contexto, no uno de los
dos brazos del experimento.

Antes de ejecutar se congela una muestra trazable; se prefieren Colombia y México
y los segmentos FinTech y CPG, sin atribuir al proyecto una cobertura que la muestra
no tenga. Se conserva la fecha y fuente de la evidencia compartida y de cada dato
del proveedor. Un dato desconocido queda pendiente: no se convierte en cero ni se
asume que pertenece a una filial por ser de su matriz.

Se aplican las mismas reglas de identidad, pertinencia, empleo y canal a ambos
resultados. La fecha de consulta o actualización del proveedor no prueba que el
empleo esté vigente ni que el correo se haya verificado en esa fecha. Sin evidencia
suficiente, el empleo o el canal quedan pendientes; ambos proveedores pueden
terminar con cero canales útiles.

Para esta comparación, un contacto útil requiere enriquecimiento, nombre completo,
ausencia de conflictos de identidad, función pertinente, empleo respaldado y correo
profesional utilizable. El respaldo laboral necesita una fuente del dominio de la
empresa, con nombre y cargo en el
fragmento y fecha de publicación vigente según `contact_days`. El correo necesita
estado válido y fecha de verificación vigente; una fecha de búsqueda de Snov o de
consulta de Apollo no sustituye esa fecha.

El informe distingue personas encontradas, con nombre completo, pertinentes y con
empleo respaldado; funciones distintas, correos profesionales utilizables, fallos,
latencia y consumo por proveedor. Las capturas conservan las solicitudes por
operación. Cada proporción o costo conserva su numerador y denominador; el costo por
contacto útil es no calculable cuando el denominador es cero. Los resultados
sintéticos se mantienen separados de los reales.

## Preparación sin llamadas reales

Con las dependencias del repositorio instaladas, desde la raíz:

```console
uv run --locked python -m experiments.snov_benchmark fixtures --output <dir>
```

Usa un directorio de salida nuevo. Se guardan el manifiesto, `capture.json`,
`report.json` y el ledger del experimento, todos exclusivamente sintéticos. Esta
prueba no necesita claves y no demuestra cobertura, precios ni acceso real a un
proveedor.

La comprobación previa de una ejecución futura se invoca sin llamar a proveedores:

```console
uv run --locked python -m experiments.snov_benchmark preflight --manifest <json> --access <json> --approvals <json>
```

`preflight` está destinado a entradas de origen `real`: devuelve `ready` o
`blocked` con los motivos, y código 2 si hay bloqueos. `ready` solo acredita las
comprobaciones locales, no una conexión exitosa. Un manifiesto `synthetic` se
bloquea con `origin_mismatch` y nunca se usa como autorización real.

Los archivos JSON se validan con los [contratos del experimento](../../experiments/snov_benchmark/contracts.py):

- **Manifiesto:** `schema_version`, `benchmark_id`, `origin`, `created_at`,
  `source_reference`, `companies`, `limits`, `contact_days` y `config_versions`.
  Cada empresa declara ID, nombre, dominio, país, segmento, fuente y fecha,
  `roles`, `role_families` y la evidencia de empleo disponible. Los alias de las
  familias deben coincidir con los cargos y no repetirse entre familias. Los
  límites son `max_requests`, `max_pages`, `max_people`, `max_polls`,
  `timeout_seconds`, `max_seconds` y `poll_interval_seconds`.
- **Acceso:** una lista con un registro por proveedor. Cada `ProviderAccess`
  identifica `provider`, `account_ref`, `access_verified`, `observed_at`,
  `source_reference` y `funding_source`; incluye `credit_limit`, `cost_limit_usd`,
  `prior_credits_used`, `prior_cost_usd`, `usage_consolidated_verified` y
  `usage_source_reference`. `operation_bounds` y `rate_limits` acotan cada
  operación, con fuente y fecha del costo y límites por minuto, hora y día.
- **Autorización:** `BenchmarkApproval` identifica experimento, hash del manifiesto,
  sesión, responsable, fecha y lista de autorizaciones. Cada entrada identifica
  `provider`, `operation`, `account_ref`, `max_cost_usd`, `max_credits`,
  `responsible`, `source_reference` y `authorized_at`. Todas las entradas
  pertenecen a la misma sesión y responsable.

Las operaciones que deben estar acotadas y autorizadas son:

| Proveedor | Operaciones |
|---|---|
| Apollo | `people_search`, `people_enrichment` |
| Snov.io | `oauth`, `people_search`, `people_search_result`, `people_enrichment`, `people_enrichment_result` |

Para Snov se reserva el máximo del revelado antes de iniciarlo; la consulta del
resultado no reserva de nuevo ese mismo costo. La configuración congelada incluye
la huella `veryfi_sha256` de `config/veryfi.json`; `contact_days` debe coincidir
con la configuración vigente. Para obtener la huella de configuración:

```console
uv run --locked python -c "from pathlib import Path; import hashlib; print(hashlib.sha256(Path('config/veryfi.json').read_bytes()).hexdigest())"
```

El hash del manifiesto se calcula tras validar y normalizar su contenido, no sobre
los bytes originales del archivo. Sustituye la ruta del ejemplo por la del JSON:

```console
uv run --locked python -c "from pathlib import Path; from experiments.snov_benchmark.contracts import BenchmarkManifest, manifest_digest; print(manifest_digest(BenchmarkManifest.model_validate_json(Path('<manifest.json>').read_text(encoding='utf-8'))))"
```

Ninguno de estos archivos contiene claves. Los ejemplos y autorizaciones
sintéticos no habilitan una llamada real. La función `build_fixture_inputs()` en
[fixtures.py](../../experiments/snov_benchmark/fixtures.py) muestra las tres
estructuras con valores ficticios.

## Ejecución real posterior

Una futura ejecución requiere comprobar acceso, operaciones, precios, límites y
créditos de cada cuenta. El responsable del cupo debe autorizar explícitamente en
esa sesión cada proveedor, operación y tope, incluidas las operaciones gratuitas,
OAuth y las operaciones asíncronas de Snov.io. El preflight no obtiene un token ni
comprueba el acceso mediante red. Si falta una condición, la ejecución queda
bloqueada y se registra el motivo.

El acceso y los saldos son evidencia local consolidada: el experimento no consulta
el saldo en vivo. El responsable debe comprobar el consumo previo y reservar cupo
exclusivo para la ejecución. No ejecutes simultáneamente el pipeline u otros
experimentos con las mismas cuentas: el ledger experimental está separado y no
comparte reservas con el presupuesto principal.

Como control conservador del experimento, la comprobación de acceso de cada cuenta
debe tener como máximo 24 horas y la autorización de sesión como máximo una hora;
ambas fechas deben ser no futuras. La autorización debe ser posterior al
manifiesto. Cada intento usa un UUID de sesión nuevo; el marcador de sesiones
utilizadas se conserva bajo `data/experiments/snov-benchmark/.approval-sessions/`.
No borres esos marcadores para reutilizar permisos. Al reanudar, las respuestas
guardadas conservan su fecha de consulta original y `max_seconds` limita el tiempo
activo acumulado. La ejecución real limita Apollo como máximo a 50 solicitudes
por minuto, 200 por hora y 600 por día por operación, y Snov a 60 solicitudes por
minuto compartidas entre sus operaciones; los topes comprobados más estrictos
también se respetan.

Las credenciales se proporcionan en el entorno mediante `SNOV_CLIENT_ID`,
`SNOV_CLIENT_SECRET` y `APOLLO_API_KEY`; no se versionan. Los datos reales y
archivos privados de la evaluación permanecen bajo
`data/experiments/snov-benchmark/`, fuera de Git. No se envían mensajes ni se
automatiza LinkedIn.

Tras completar las condiciones y recibir autorización, el comando previsto es:

```console
uv run --locked python -m experiments.snov_benchmark run --live --manifest <json> --access <json> --approvals <json> --output data/experiments/snov-benchmark/<id>
```

La reserva precede a cada llamada y se mantienen separados los consumos por
proveedor y operación. Un consumo incierto conserva su exposición hasta conciliarlo;
una reanudación requiere autorización nueva. No se recrean ni eliminan las
capturas o registros para repetir un lote.

La salida conserva `capture.json`, una lista de capturas por empresa y proveedor,
y un ledger aislado del producto. Para generar el informe desde una captura
conservada:

```console
uv run --locked python -m experiments.snov_benchmark report --manifest <json> --capture <capture.json> --output <report.json>
```

El archivo de salida debe ser nuevo; el comando no sobrescribe un informe
existente. Sin comprobantes, solo lee el manifiesto y la captura, y guarda el
informe. Los consumos observados permanecen `null` hasta su conciliación, incluso
si la reserva es cero: una cota no demuestra el gasto real.

Cuando se cuente con comprobantes atribuibles, se puede conciliar sin red:

```console
uv run --locked python -m experiments.snov_benchmark report --manifest <json> --capture <capture.json> --output <report-nuevo.json> --receipts <comprobantes.json>
```

El JSON `ReceiptBundle` de [receipts.py](../../experiments/snov_benchmark/receipts.py)
contiene `schema_version` igual a `snov_benchmark_receipts_v1`, `benchmark_id`,
`manifest_sha256`, `origin`, `responsible` y la lista `receipts`. Cada entrada
incluye `request_id` y `confirmation`, con `outcome` (`succeeded` o `failed`),
`final_cost_usd`, `credits`, `outlay_usd`, `source_reference`, `observed_at` y,
si corresponde, `no_send` o `tokens`. La fuente y la fecha deben respaldar el
resultado y el importe de cada solicitud; no se inventa un cero.

Un comprobante debe cubrir todas las solicitudes del proveedor y cuenta elegidos
en ese expediente. Se puede conciliar un proveedor y dejar el otro pendiente. En
Snov, atribuye el cargo del revelado una sola vez a su inicio y registra cero en
la consulta del resultado solo si el comprobante lo respalda. El comando valida
el lote completo antes de aplicarlo al ledger, actualiza `capture.json` y
`state.json`, y archiva el comprobante por su huella en `receipts/`. No llama a
proveedores. Conserva estos archivos privados junto con el expediente.

El informe contiene agregados por proveedor, desgloses por empresa e identificadores
de personas. Trata también el informe como privado y mantenlo bajo `data/` si parte
de capturas reales; no publiques los identificadores ni los datos personales.
`comparison_complete` indica que hay capturas terminadas para cada empresa y
proveedor; no acredita representatividad, validación comercial ni conciliación.

## Referencias públicas

Consultadas el 9 de noviembre de 2026. La documentación pública no confirma los
permisos ni el saldo de una cuenta concreta:

- Snov.io: [acceso y autenticación](https://snov.io/knowledgebase/how-to-use-snov-io-api/),
  [Database Search API](https://snov.io/knowledgebase/how-to-use-database-search-api/)
  y [referencia de métodos](https://snov.io/api).
- Apollo: [People API Search](https://docs.apollo.io/reference/people-api-search) y
  [People Enrichment](https://docs.apollo.io/reference/people-enrichment).

## Resultado y decisión

| Elemento | Estado |
|---|---|
| Muestra real pareada y ventana de consulta | Pendiente |
| Acceso, precios, cupos y autorización por operación | Pendiente |
| Capturas, gastos conciliados y revisión de contactos | Pendiente |
| Comparación y recomendación | Pendiente |

No hay todavía una recomendación para cambiar de proveedor. Una eventual
sustitución requiere una decisión autorizada y una historia de migración separada;
no se habilita fallback ni se fusiona el experimento como funcionalidad de `main`.
