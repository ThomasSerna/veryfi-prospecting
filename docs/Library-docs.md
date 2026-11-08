# Librerías y servicios de terceros

Cómo usa el proyecto cada librería y servicio externo. Forma parte de la documentación de requisitos: ver el [índice](IDEA.md). Describe lo que hace el repositorio y no repite la documentación oficial: las fuentes y sus fechas de consulta originales están en «Fuentes y estado de verificación». Lo que el repositorio no respalda figura como «por verificar».

## Resumen

| Componente | Rol | Versión o plan | Variable de entorno | Dónde está en el código |
|---|---|---|---|---|
| Tavily | Búsqueda y extracción web | Plan gratuito del equipo; 1.000 créditos gratuitos mensuales publicados [W1] | `TAVILY_API_KEY` | `prospecting/providers/tavily.py` |
| Apollo | Personas y correos profesionales | Plan Free declarado por el responsable; acceso y límites por comprobar | `APOLLO_API_KEY` | `prospecting/providers/apollo.py` |
| Anthropic (Claude Haiku) | Interpretación y clasificación | `claude-haiku-5-5` con `anthropic==1.11.0` | `ANTHROPIC_API_KEY` | `prospecting/providers/claude.py` y `prospecting/haiku.py` |
| Django | Interfaz local | `django==5.2.18` | `DJANGO_SECRET_KEY` (opcional) | `config/`, `core/`, `templates/` y `static/` |
| Pydantic | Contratos y validación | `pydantic==2.13.5` | Ninguna | `prospecting/models.py` y los adaptadores de `providers/` |
| SQLite | Persistencia | Módulo `sqlite3` de la biblioteca estándar | `PROSPECTING_DB_PATH` (ruta, opcional) | `prospecting/db.py` |
| pytest | Pruebas | `pytest==9.1.1` (desarrollo) | Ninguna | `tests/` |
| uv | Entorno y dependencias | `uv.lock` | Ninguna | `pyproject.toml` |

Las claves se leen solo de variables de entorno; `.env.example` lista los nombres sin valores. La aplicación no carga `.env` automáticamente y una clave presente no autoriza gasto.

## Servicios externos

### Tavily: búsqueda y extracción web

- **Rol:** descubre candidatos y localiza evidencia pública. El resumen de un resultado de búsqueda sirve para localizar la fuente, no para confirmar hechos de una empresa o persona.
- **Operaciones habilitadas** (`TAVILY_OPERATIONS`): `POST https://api.tavily.com/search` y `POST https://api.tavily.com/extract`, con `Authorization: Bearer` y la clave de `TAVILY_API_KEY`. Solo se usa con crédito gratuito y sin Research ni Crawl amplio por defecto [W1].
- **Búsqueda** (`search_request`): `search_depth=basic`, `topic=general`, `country` (`colombia` o `mexico`), `max_results` según los límites de la campaña, sin respuesta generada, sin contenido bruto ni imágenes, `include_usage=true` y `exclude_domains` con los dominios no empresariales (`NON_BUSINESS_DOMAINS`). Cota de reserva: 1 crédito por consulta.
- **Extracción** (`extract_request`): `extract_depth=basic`, `format=text`, hasta 3 fragmentos por fuente (`chunks_per_source`), `timeout` de 6 s e `include_usage=true`. Cota de reserva: 1 crédito por cada 5 URL.
- **Respuesta:** se valida con Pydantic y admite hasta 20 resultados; títulos de hasta 160 caracteres, resúmenes de 300 y fragmentos de 800. Se convierte en `SearchHit` y `Evidence` con procedencia; solo `prospecting.pipeline` reserva y llama.
- **Más detalle:** [discovery.md](discovery.md) (etapas) y [provider-check.md](provider-check.md) (llamadas reales y conciliación). Las pruebas usan transportes sintéticos (`tests/test_providers.py`, `tests/test_pipeline.py`).

### Apollo: personas y correos profesionales

- **Rol:** único proveedor especializado de personas y canales desde T12; reemplazó a Hunter.
- **Operaciones habilitadas** (`APOLLO_OPERATIONS`): `people_search` en `POST https://api.apollo.io/api/v1/mixed_people/api_search` y `people_enrichment` en `POST https://api.apollo.io/api/v1/people/match`. Autenticación con la cabecera `x-api-key` (sin prefijo) y `Cache-Control: no-cache`; la clave se lee de `APOLLO_API_KEY`.
- **Búsqueda** (`people_search_request`): exige una empresa con identidad confirmada y dominio; envía `q_organization_domains_list`, `page=1` y `per_page=10`. Con taxonomía añade desde la primera consulta `person_titles` y `include_similar_titles=false`; usa `person_seniorities` solo para familias con nivel sustentado. Cada solicitud admite menos de 100 títulos únicos. El departamento es clasificación interna, no un filtro enviado a People API Search. Devuelve hasta 10 candidatos, con el apellido ofuscado, sin correo ni teléfono; no verifica identidad ni empleo.
- **Enriquecimiento** (`enrichment_request`): solo con un identificador observado de Apollo; envía `reveal_personal_emails=false`, `reveal_phone_number=false`, `run_waterfall_email=false` y `run_waterfall_phone=false`. Cota de reserva: 1 crédito por persona (`enrichment_credit_bound`); la búsqueda se registra con cota de cero créditos.
- **Costos documentados** [W2, consultado el 2026-11-07]: People API Search cuesta 0 créditos. People Enrichment cuesta de 1 a 9 créditos sin waterfall: 1 por datos demográficos o correo y 8 más si devuelve un móvil. No cobra el crédito demográfico cuando `match_confidence` es `none`, y una solicitud sin datos que consuman crédito cuesta 0. Como el teléfono y el waterfall van desactivados, la cota de 1 crédito es un máximo prudente y el consumo real puede ser 0. La respuesta no informa los créditos consumidos: se concilian con el panel (Settings > Billing and credits) mediante `manage.py reconcile_usage` ([budget-providers.md](budget-providers.md)).
- **Acceso:** `ApolloAccess` (cuenta, plan `free`, operaciones habilitadas, `work_email_verified`, `access_verified`, fecha, referencia y `rate_limits`) vive en `data/provider-access.json` y no sustituye el cupo ni la autorización de cada sesión. Sin acceso comprobado la ejecución real queda bloqueada, sin retorno a Hunter. Search y Enrichment exigen una cuenta registrada con correo laboral.
- **Límites de solicitudes** [W2]: por equipo y endpoint, en ventanas fijas de minuto, hora y día. Plan Free: Search y Enrichment individual, 50 por minuto, 200 por hora y 600 por día. Apollo informa límite, uso y restante con las cabeceras `x-rate-limit-minute`, `x-rate-limit-hourly`, `x-rate-limit-24-hour`, `x-minute-usage`, `x-hourly-usage`, `x-24-hour-usage`, `x-minute-requests-left`, `x-hourly-requests-left` y `x-24-hour-requests-left`, y `retry-after` en un 429. El sistema no depende de esas cabeceras: `ApolloAccess.rate_limits` (por defecto `FREE_RATE_LIMITS`, que no se pueden aflojar con plan `free`) se aplica antes de reservar, contando el ledger en ventanas deslizantes (`local_rate_limit`).
- **Errores** (`classify_apollo_error`) [W2]: 401, clave inválida o ausente (`permission_denied`); 403 con `API_INACCESSIBLE`, plan o clave sin acceso al endpoint (`apollo_api_inaccessible`); otro 403, `permission_denied`; 429 con `USAGE.RATE_LIMIT.API_RATE_LIMIT_EXCEEDED` o `USAGE.RATE_LIMIT.PLATFORM_RATE_LIMIT`, `rate_limited`; 400 y 422, `apollo_invalid_input`; 404, `apollo_not_found`; 5xx y redirecciones, `apollo_provider_error`; tiempo de espera, `apollo_timeout`; transporte, `apollo_transport_error`; JSON o esquema inválidos, `apollo_invalid_response`. Apollo no documenta la respuesta a créditos agotados: un 4xx no documentado se trata como fallo de la pasada (fail closed). Todos estos motivos detienen la pasada de contactos. El código literal del cuerpo y el `Retry-After` quedan en el mensaje persistido.
- **Procedencia:** cada hecho lleva la referencia `apollo_v1:<id>:<request_id>#<campo>`; una fecha de actualización del perfil no demuestra empleo vigente ni verificación del correo.
- **No se hace:** escribir en Apollo, secuencias o mensajes, teléfonos ni waterfall. Organization Search (1 crédito por página) y Organization Enrichment (1 crédito por organización) no están habilitadas: la identidad de la empresa sale de la evidencia de Tavily y sumarlas añadiría consumo sin cambiar la decisión; solo podrían añadirse si se justifica, hay acceso y se autoriza el consumo. Tampoco se usa `POST /api/v1/usage_stats/api_usage_stats`: no consume créditos, pero solo informa el uso de los límites de tasa, no el saldo de créditos.
- **Más detalle:** [contacts.md](contacts.md) y [budget-providers.md](budget-providers.md#consumo-y-respuestas-de-apollo).

### Anthropic: Claude Haiku

- **Modelo único:** `claude-haiku-5-5` (`MODEL_ID` en `prospecting/haiku.py`), sin escalamiento automático a otro modelo.
- **Cliente** (`ClaudeClient`): SDK oficial `anthropic==1.11.0`, `max_retries=0` y plazo de 30 s (`CLAUDE_TIMEOUT_SECONDS`). La clave se lee de `ANTHROPIC_API_KEY` y se pasa de forma explícita; no se usan perfiles locales. Proveedor `anthropic`, operación `messages`.
- **Solicitud** (`structured_request`): respuesta JSON con esquema (`output_config.format`), esfuerzo bajo, razonamiento extendido desactivado y `max_tokens` por llamada.
- **Límites:** entrada de hasta 9.000 tokens y salida de hasta 1.000 (`LlmLimits`). La evidencia que cabe en el prompt se calcula con 2 caracteres por token (`CHARS_PER_TOKEN`). La cota de entrada para reservar el gasto es el tamaño en bytes del payload serializado más 1.000 tokens por el prompt que Anthropic inyecta con las salidas estructuradas (`input_token_bound`, `INJECTED_PROMPT_TOKENS`).
- **Precio para reservar:** USD 0,10 por millón de tokens de entrada y USD 0,50 por millón de salida (`CLAUDE_PRICES_PER_MTOK`, [W4]); sin un precio acotado no hay llamada.
- **Prompts versionados** junto a su validador: `haiku_assessment_v5` y `contacts_extraction_v2` para campañas con taxonomía; `haiku_assessment_v3/v4` y `contacts_extraction_v1` para instantáneas históricas. Las respuestas se validan con Pydantic y las referencias y citas deben corresponder a la evidencia suministrada.
- **Seguridad:** Haiku propone y Python decide. No recibe claves, shell, archivos ni herramientas de comunicación. El contenido externo se serializa con `prompt_json`, que escapa `<` para que ningún texto cierre el bloque de evidencia. Solo `pipeline` invoca `ClaudeClient`.
- **Más detalle:** [qualification.md](qualification.md).

### LinkedIn, X-Ray Search y otras alternativas

- **Hunter:** ya no se usa; su historial y consumo se conservan (ver «Historial»).
- **LinkedIn** [W5]: no hay API abierta de Sales Navigator ni se automatiza el sitio. Los perfiles se revisan a mano y un canal de LinkedIn solo cuenta como utilizable tras la confirmación manual de mensajería.
- **X-Ray Search:** no está habilitado ([contacts.md](contacts.md)). Es una evaluación opcional y, si se implementara, respetaría las restricciones de «Evolución de la búsqueda de contactos». La propuesta original está en [Roadmap.md](Roadmap.md#propuestas-fuera-del-backlog).
- **Exa y Brave Search API** [W6, W7]: alternativas evaluadas; no están integradas.
- **Snov.io:** evaluación planeada en el [backlog](Roadmap.md#exploración-t22-abierta) (T22), en una rama experimental aislada; no se integra en `main`.

## Librerías

### Django

- Versión 5.2.18. `INSTALLED_APPS` solo tiene `core` y `django.contrib.staticfiles`, y `DATABASES` está vacío: no hay ORM, migraciones, cuentas ni administración.
- Servidor de desarrollo local: `manage.py runserver 127.0.0.1:8000 --noreload`. `core/management/commands/runserver.py` usa loopback por defecto, desactiva el recargador, exige el servidor con hilos y rechaza otras direcciones. `ALLOWED_HOSTS` solo admite `127.0.0.1`, `localhost` y `[::1]`, `DEBUG = False` y `LoopbackMiddleware` responde 403 a cualquier conexión que no sea loopback. No es apto para producción [W8].
- Sesión firmada en cookie (`signed_cookies`) con `HttpOnly` y `SameSite=Strict`, y protección CSRF activa. La sesión solo guarda el borrador de la campaña.
- Las plantillas no usan `|safe` ni `mark_safe`; el autoescape protege el contenido externo (`tests/test_initialization.py`).
- Rutas configurables por entorno: `PROSPECTING_DB_PATH`, `PROSPECTING_ACCESS_PATH`, `PROSPECTING_EXCLUSIONS_PATH`, `PROSPECTING_CONFIG_PATH` y `PROSPECTING_CONTACT_MATCH_PATH`. `PROSPECTING_DEMO=1` solo lo activa `demo.py`. Si falta `DJANGO_SECRET_KEY`, se genera una clave por proceso.
- Más detalle: [ui.md](ui.md).

### Pydantic

- Versión 2.13.5. `Contract` (en `prospecting/models.py`) prohíbe campos extra y revalida las instancias que llegan desde otro módulo (`extra="forbid"`, `revalidate_instances="always"`).
- Valida las respuestas de Tavily, Apollo y Haiku en los adaptadores y en los validadores de cada módulo. El esquema JSON que se envía a Haiku sale de modelos Pydantic.

### SQLite

- Módulo `sqlite3` de la biblioteca estándar, gestionado solo por `prospecting/db.py`. Esquema, restricciones e índices: [Architecture.md](Architecture.md#esquema-sqlite); reglas de escritura e identificadores guardados: [persistence.md](persistence.md).

### Biblioteca estándar

- `urllib` para el transporte de los proveedores: HTTPS verificado, un opener privado sin proxies heredados ni redirecciones, respuesta máxima de 1 MiB (`MAX_RESPONSE_BYTES`) y plazo de 10 s por operación salvo que su descriptor fije otro ([budget-providers.md](budget-providers.md)).
- `hashlib` para las huellas SHA-256 de las solicitudes; `csv`, `json` y `datetime` para exportación, serialización y fechas.

### Herramientas de desarrollo

- **uv:** `uv sync --locked` instala las versiones de `uv.lock`; todo se ejecuta con `uv run --locked`. No se usa `pip`.
- **pytest 9.1.1:** `uv run --locked pytest`; `pyproject.toml` fija `testpaths = ["tests"]` y `pythonpath = ["."]`. Pruebas sin red; ver [Testing.md](Testing.md).
- **Node.js:** opcional, solo para `node --test tests/js_execution.test.cjs`.
- **graphify:** mantiene el grafo local `graphify-out/` (ignorado por Git). `graphify update .` actualiza el código sin coste y `graphify query "<pregunta>"` consulta el grafo; los `.md` nuevos o modificados requieren la pasada semántica de la skill (`.codex/skills/graphify`).

## Proveedores y estrategia de integración

Acceso, planes y consumo se deben verificar con las cuentas del equipo antes de activar cada integración. La comprobación de Apollo y sus fuentes están en `docs/provider-check.md`.

| Componente | Elección inicial y función | Condición y alternativa |
|---|---|---|
| Búsqueda/evidencia | Tavily Search/Extract | Usar créditos gratuitos primero, búsqueda básica y URLs seleccionadas. Sin Research/Crawl amplio por defecto [W1] |
| Personas y correo | Apollo People API Search y People Enrichment | Buscar por dominio y cargos, enriquecer selectivamente y conservar procedencia y fechas. Search no entrega email/teléfono; habilitar solo con acceso y consumo comprobados [W2] |
| Interpretación y clasificación | Haiku 5.5 | Extraer hechos, evaluar criterios, relacionar casos de uso y producir explicación breve con referencias; Python aplica el cálculo y las reglas [W4] |
| Revisión de perfiles | LinkedIn manual | No depender de una API abierta de Sales Navigator ni automatizar el sitio [W5] |

Alternativas evaluadas, no integraciones obligatorias: Exa para descubrimiento semántico de empresas/personas y Brave Search API para búsqueda general [W6, W7]. Cambiar de buscador solo si la evaluación muestra una limitación concreta; no integrar varios a la vez por previsión.

Apollo (T12): usar `mixed_people/api_search` y `people/match`, verificando la correspondencia actual entre persona y empresa incluso si aparece un empleo anterior. Mantener desactivados enriquecimiento de móvil y waterfall de costo variable. Una fecha de consulta no sustituye una fecha de verificación del correo ni demuestra vigencia laboral. Si falta una fecha de verificación fiable, el correo queda pendiente salvo publicación nominal corporativa vigente. Verificar parámetros, respuesta, disponibilidad y consumo en la cuenta antes de las llamadas reales [W2].

No añadir endpoints de secuencias, envío, creación de campañas ni sincronización de contactos a plataformas externas. Las integraciones de prospección usan lectura/búsqueda/enriquecimiento aunque algunas llamadas HTTP sean POST.

### Comprobación de acceso del primer día

Probar una muestra mínima y registrar para cada proveedor: cuenta disponible, endpoints permitidos, crédito inicial, límite, costo real de la llamada y resultado. Crear un pequeño registro `docs/provider-check.md` sin secretos ni datos personales innecesarios.

Si Apollo no tiene acceso o cupo comprobados, bloquear su ejecución y explicar el motivo sin recurrir a Hunter; la consulta del historial y la demo sintética siguen disponibles. No comprar planes ni sustituir contactos reales por datos inventados. La obtención automática de canales directos debe demostrarse con resultados reales para considerarla validada.

### Evolución de la búsqueda de contactos

T06 implementó Tavily para evidencia pública y Hunter para personas/canales. T12 reemplaza Hunter por Apollo como único proveedor especializado activo. La validación de identidad, puesto, canal, procedencia y estado comercial reutiliza los contratos `Contact`, `Channel` y `Evidence` (§13.2); no construir una plataforma genérica de conectores.

La sustitución de T12 no autoriza gasto ni demuestra por sí sola mayor cobertura. La comparación de cobertura, pertinencia, actualidad, consumo y fallos requiere una muestra y autorización independientes. X-Ray Search sigue siendo una extensión opcional, sin contacto comercial automático.

## Uso de IA y protección de decisiones

### Haiku

Haiku recibe un catálogo breve de capacidades autorizadas de Veryfi, datos de campaña y evidencia recuperada. Devuelve un objeto validable con hechos, `evidence_ids`, criterios, productos candidatos, cargos sugeridos, incertidumbres y una explicación corta. En campañas con taxonomía propone además perfiles respaldados por citas literales; Python comprueba sus referencias, pertenencia y contradicciones. Debe poder devolver `null`/desconocido o ningún perfil respaldado.

No usar su memoria como fuente de contactos, empresas o cargos actuales. No permitir que invente URLs ni referencias: cada `evidence_id` debe existir en el conjunto suministrado. La validación programática comprueba referencias y valores; la revisión de calidad comprueba que la fuente respalde la afirmación.

Límite por petición: 9.000 tokens de entrada y 1.000 de salida, con esfuerzo bajo cuando esté soportado. El límite inicial de 6.000 tokens se elevó el 14 de octubre de 2026: las solicitudes reales medidas usaban unos 2,2 caracteres por token y, en el lote de la entrega, ocuparon entre 3.388 y 8.721 tokens de entrada (`docs/provider-check.md`); aplicar 6.000 reales habría reducido la evidencia de cada calificación a unos cuatro fragmentos. Partir/seleccionar evidencia antes de enviar páginas completas. Registrar modelo exacto, versión de prompt, uso y costo. Revisar parámetros actuales del modelo; no copiar configuraciones de modelos anteriores sin verificar [W4].

### Evaluación y decisiones en Python

Haiku evalúa los criterios de la rúbrica y la pertinencia de los cargos usando la evidencia suministrada. Python valida la respuesta, calcula la puntuación y cobertura, aplica umbrales y decide el esfuerzo de búsqueda. Las decisiones de presupuesto, exclusión, parada y condición de listo permanecen en código determinista.

Si una respuesta de Haiku falla o no supera la validación después de los intentos permitidos, conservar la evidencia y marcar la evaluación como pendiente. No escalar automáticamente a un modelo más caro.

Con un conjunto separado de validación, medir errores, latencia y costo total del flujo. La confianza del modelo sirve como señal técnica; no mostrarla como porcentaje de compra ni asumir calibración para este dominio sin medición.

## Fuentes y estado de verificación

### Documentación externa oficial

- **W1.** [Tavily: créditos y costos](https://docs.tavily.com/documentation/api-credits).
- **W2.** Apollo: [búsqueda de personas](https://docs.apollo.io/reference/people-api-search), [enriquecimiento](https://docs.apollo.io/reference/people-enrichment), [créditos](https://docs.apollo.io/docs/api-pricing), [límites de solicitudes](https://docs.apollo.io/reference/rate-limits), [códigos de estado](https://docs.apollo.io/reference/status-codes) y [uso de la API](https://docs.apollo.io/reference/view-api-usage-stats); límites, costos y errores consultados el 2026-11-07.
- **W3.** [Hunter: API, fuentes, Finder y Verifier](https://hunter.io/api-documentation).
- **W4.** [Claude Haiku 5.5: modelo, parámetros y precios](https://platform.claude.com/docs/en/models/haiku-5-5/overview).
- **W5.** LinkedIn: [acceso Sales Navigator/SNAP](https://learn.microsoft.com/en-us/linkedin/sales/) y [restricciones de automatización](https://www.linkedin.com/help/linkedin/answer/a1341387/prohibition-of-scraping-software?intendedLocale=en&lang=en-us).
- **W6.** Exa: [búsqueda](https://exa.ai/docs/reference/search) y [precios](https://exa.ai/pricing).
- **W7.** [Brave Search API](https://brave.com/search/api/).
- **W8.** [Django: `runserver`, servidor de desarrollo no apto para producción](https://docs.djangoproject.com/en/5.2/ref/django-admin/#runserver).

La versión inicial (10 de octubre) solo verificó documentación pública. Después se ejecutaron llamadas reales con las cuentas del equipo, dentro de los topes autorizados y sin comprar servicios; su gasto y conciliación están en `docs/provider-check.md`. La cobertura medida y sus límites están en `docs/evaluation.md` y `docs/delivery.md`. Este archivo fija el plan y las decisiones; el estado de la implementación se documenta en esos archivos.

## Historial

### Hunter

Hunter fue la primera ruta de T06. Sus resultados, procedencia y consumo históricos permanecen disponibles para consulta y exportación; no se realizan nuevas llamadas ni se cambia su origen [W3]. Las campañas anteriores a Apollo no se reanudan con el proveedor nuevo: si una permanece activa, se cierra explícitamente antes de iniciar otra.
