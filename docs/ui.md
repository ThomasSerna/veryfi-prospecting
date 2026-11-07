# Interfaz local de campañas y revisión

Inicia la aplicación desde la raíz:

```console
uv run --locked python manage.py runserver 127.0.0.1:8000 --noreload
```

Abre [http://127.0.0.1:8000](http://127.0.0.1:8000). Django escucha en `127.0.0.1`;
usa una sola instancia local con la base
`data/prospecting.sqlite3`. La aplicación busca y lee información: no envía mensajes
ni notificaciones para comprobar canales.

Para mostrarla sin claves ni consumo, `uv run --locked --offline python demo.py` la inicia
sobre una base temporal exclusivamente sintética, con un aviso fijo en cada página y CSV
nombrados `demo-sintetica-…`; sin archivo de acceso, la ejecución queda bloqueada
([README](../README.md#demostración-sin-consumo)).

La migración de la interfaz a Django fue aprobada el 13 de octubre de 2026.
Sustituye la interfaz Streamlit descrita en la arquitectura inicial de `IDEA.md`;
el pipeline, sus contratos, reglas y persistencia permanecen iguales.

## Inicio y navegación

El inicio muestra la campaña activa o, si no la hay, la última guardada. El
panel resume su avance y cuenta las empresas encontradas, sin revisar y con
contacto listo; no suma resultados de campañas distintas. Desde «Sin revisar»
se puede abrir la siguiente empresa pendiente cuando no hay una investigación
en curso. Si no existen campañas, se ofrece preparar la primera.

El avance dibuja un segmento por empresa encontrada y enciende los terminados;
sin empresas no muestra un porcentaje. Las cifras ruedan hasta su valor, que
permanece en el documento para lectores de pantalla. Durante una investigación,
el inicio vuelve a leer su propia página cada dos segundos y actualiza en su
sitio avance, cifras, estado, navegación y presupuesto, sin recargar ni repetir
la entrada; al terminar muestra el estado final y habilita la revisión. Con
movimiento reducido, el contenido aparece en su estado final y los cambios solo
se funden.

El historial está en `/campaigns/` y se abre desde el inicio o el menú. La
navegación comienza cerrada y reúne Resumen, Historial y Nueva campaña. Su botón
comparte la línea del logotipo en la barra superior; al señalarlo, el icono
anticipa la apertura del cajón y, durante una investigación, muestra un punto que
late. Al abrirla, el contenido queda detrás de una capa oscurecida y desenfocada.
Con JavaScript, Escape, el fondo o el botón cierran el menú y devuelven el foco;
sin JavaScript funciona el control nativo de apertura y cierre. La barra superior
muestra la ruta y, en la ficha, Anterior y Siguiente; no resume el presupuesto,
que se consulta en la sección Presupuesto de cada campaña. Un importe desconocido
o pendiente conserva esa condición.

Las propuestas estáticas de [campaña](../static/prototypes/campaign.html) y
[ficha](../static/prototypes/company.html) siguen disponibles en el servidor
local bajo `/static/prototypes/` como referencia histórica. Contienen únicamente
datos sintéticos y controles ilustrativos desactivados; no investigan ni guardan
cambios. Las vistas operativas ya aplican la nueva dirección.

## Preparar y ejecutar

1. En Mercado y Alcance, selecciona países, segmentos, palabras clave opcionales y
   un máximo de 1–20 empresas. Revisa los criterios y topes en Resumen.
   Crear la campaña guarda los criterios y la instantánea de configuración sin tráfico.
2. Consulta el presupuesto y las cuentas comprobadas. Ejecutar requiere claves en el
   entorno y un archivo válido `data/provider-access.json`.
3. El responsable autoriza explícitamente cada operación habilitada, con cuenta, tope
   económico y de créditos, responsable y referencia. La ejecución crea permisos
   nuevos dentro de una sesión de `Budget`; no recupera permisos guardados.
4. La campaña avanza secuencialmente en un hilo del servidor. Durante descubrimiento el
   progreso es indeterminado; después se muestran las etapas y resultados parciales tras
   guardarlos en SQLite. La pantalla consulta el estado cada dos segundos mientras se ejecuta.

El historial recupera campañas y permite reanudar o cerrar una campaña de Apollo
interrumpida conservando resultados y consumo. Las campañas anteriores a Apollo
solo se consultan o exportan; si una sigue activa, debe cerrarse explícitamente para
preparar otra. Una campaña en estado `running` o `paused_budget` bloquea preparar
otra, incluso si el hilo de investigación está detenido; la pantalla ofrece abrirla
para retomarla o cerrarla cuando corresponda. Los clics duplicados no repiten solicitudes
enviadas. Cerrar la pestaña no detiene la campaña; detener o reiniciar el servidor sí.
No existe cola persistente ni reanudación automática: tras reiniciar, revisa el estado
guardado y autoriza de nuevo. El último informe general está en memoria y se pierde al
reiniciar; los errores y motivos por empresa, resultados y gasto permanecen en SQLite.
Una interrupción
durante descubrimiento puede dejar respuestas pagadas sin resultados guardados:
reanudar termina con `duplicate_request` si la primera búsqueda ya fue enviada, sin
repetirla ni borrar su reserva. Consulta [Orquestación](campaign.md) para los límites.

## Acceso local a proveedores

`data/` está ignorado por Git. `provider-access.json` solo guarda cuentas, cupos y
comprobaciones de acceso; las claves viven en variables de entorno. La aplicación
no carga `.env` automáticamente. Define `TAVILY_API_KEY`, `ANTHROPIC_API_KEY` y
`APOLLO_API_KEY` antes de iniciar Django; con un
`.env` local, añade `--env-file .env` a `uv run --locked` para pasarlas al proceso.
Si la interfaz indica «Clave no configurada en el servidor» con el `.env` presente, se inició sin `--env-file`.
La interfaz habilita únicamente las operaciones cuya variable local tiene un valor configurado,
sin mostrarlo ni probarlo por red. Ese indicador no demuestra permisos ni saldo:
las comprobaciones de acceso y cupo proceden del archivo local.

Este ejemplo es **exclusivamente sintético**: no comprueba cuentas, no concede permisos
y sus cifras no sustituyen los cupos reales. Muestra la forma validada de `ProviderAccess`:

```json
{
  "account_allowances": [
    {
      "provider": "tavily",
      "account_ref": "tavily-sintetica",
      "funding_source": "free_credit",
      "credit_limit": "100",
      "cost_limit_usd": "0",
      "source_reference": "Cupo exclusivamente sintético",
      "observed_at": "2026-10-11T12:00:00Z",
      "credit_valuation": null
    },
    {
      "provider": "anthropic",
      "account_ref": "claude-sintetica",
      "funding_source": "prepaid",
      "credit_limit": "0",
      "cost_limit_usd": "1",
      "source_reference": "Cupo exclusivamente sintético",
      "observed_at": "2026-10-11T12:00:00Z",
      "credit_valuation": null
    },
    {
      "provider": "apollo",
      "account_ref": "apollo-sintetica",
      "funding_source": "free_credit",
      "credit_limit": "30",
      "cost_limit_usd": "0",
      "source_reference": "Cupo exclusivamente sintético",
      "observed_at": "2026-10-11T12:00:00Z",
      "credit_valuation": null
    }
  ],
  "tavily_account_ref": "tavily-sintetica",
  "claude_account_ref": "claude-sintetica",
  "claude_funding_source": "prepaid",
  "apollo_access": {
    "account_ref": "apollo-sintetica",
    "enabled_operations": ["people_search", "people_enrichment"],
    "funding_source": "free_credit",
    "source_reference": "Acceso exclusivamente sintético",
    "observed_at": "2026-10-11T12:00:00Z",
    "work_email_verified": true,
    "access_verified": true,
    "enrichment_credit_bound": "1",
    "plan": "free"
  }
}
```

Cada proveedor habilitado necesita una cuenta con la misma referencia y financiación;
las referencias de consumo son únicas. Tavily usa crédito gratuito y Haiku la
financiación declarada en `claude_funding_source`. Un cupo desconocido permanece
desconocido; el presupuesto bloquea llamadas cuyo costo o créditos no estén acotados.
Los cupos son la asignación inicial comprobada, no el saldo restante ni un permiso:
el ledger descuenta el consumo anterior, también tras un reinicio. No reinicies una
cuenta o una base para renovar el saldo.

Para la ejecución real, `apollo_access` debe acreditar correo laboral, acceso a
`people_search` y `people_enrichment`, saldo y facturación de la cuenta; el adaptador
actual admite el plan `free` y reserva un crédito por enriquecimiento. Las marcas del
ejemplo son sintéticas y no deben copiarse como comprobaciones reales. Una clave
presente no demuestra acceso. Antes de investigar, la aplicación exige una clave con
formato HTTP válido, un cupo de créditos conocido para esa cuenta y al menos un crédito
disponible después de descontar el consumo y las reservas pendientes. Si la exposición
de créditos es desconocida o faltan estas condiciones, la
ejecución se bloquea; consulta y demo siguen disponibles, sin recurrir a Hunter. La
búsqueda se registra con cota de cero créditos. Las cuentas con créditos de pago
necesitan `credit_valuation` comprobada, con `unit_value_usd`, `source_reference` y
`observed_at`, para acotar el costo.

Si el archivo local procede de la integración anterior, conserva las cuentas y cupos
de Tavily y Anthropic, retira `hunter_access` y el cupo de Hunter del archivo y agrega
la cuenta y comprobación reales de Apollo cuando estén disponibles. No completes
campos con los valores sintéticos del ejemplo: la configuración antigua no habilita
una ejecución nueva. Cambiar ese archivo no borra el ledger histórico de SQLite;
conserva la base y sus archivos auxiliares.

El presupuesto muestra consumo confirmado, estimado, reservado y disponible en formato
comercial legible, además del desglose por cuenta. Una reserva incierta se conserva hasta conciliarla.
El archivo de acceso no habilita operaciones adicionales ni altera límites del catálogo.
La lista opcional de exclusiones está en `data/exclusions.json`: si falta o no está
validada, la interfaz muestra su estado y no afirma que se aplicó una lista validada.

## Resultados y revisión

La vista de campaña abre con un pulso de la investigación: un segmento por empresa
encontrada, la cifra de investigadas y tres cifras con su barra (sin revisar,
contacto listo y aceptadas), además de una barra apilada de prioridades cuya
leyenda filtra la tabla. La tabla permite buscar y filtrar por país, segmento,
prioridad y disponibilidad desde una sola barra; toda la fila abre la ficha y el
nombre sigue siendo el único enlace para teclado y lectores de pantalla. Las dos
descargas están en el encabezado. Durante una investigación, la vista consulta el
estado cada dos segundos y compara cada sección en su sitio: las empresas nuevas
entran en su fila, las que cambian de puesto se desplazan hasta él y las que
cambian de datos se iluminan, sin repetir la entrada. Al terminar, la página se
lee de nuevo y se actualiza en su sitio; si no puede, se recarga. La ficha de
empresa organiza Resumen,
Contactos y Evidencia con píldoras de referencia cruzada que informan el origen o dominio y el
número de fuente (`Fuente original · dominio.com #1`, `Apollo #2`), mostrando encaje,
cobertura, criterios con etiquetas semánticas (`Señal fuerte`, `Señal parcial`, `Incompatible`,
`Sin evidencia`) junto a una bola de Harvey, caso de uso, contactos y motivos de
detención sin jerga técnica. Al seguir una píldora, la fuente citada se ilumina
un instante. A la derecha se mantienen el mejor match y la revisión de ventas.
Datos desconocidos se muestran separados de cero.

En una campaña con `rubric_v2`, la tabla conserva el orden de la lectura pública:
prioridad, necesidad documental `1` y score descendente, con desempate estable.
La exportación mantiene ese orden. Las campañas con `rubric_v1` conservan su
orden anterior; la candidata v2 sigue pendiente de su evaluación académica.

La pestaña Contactos lista a todas las personas encontradas, ordenadas por porcentaje de
match, con su desglose, sus datos pendientes y la marca de las descartadas por regla. Cada
persona muestra su etapa (Candidata, Identidad verificada, Pertinente, Pertinente con canal
o Lista) y, si Apollo no la confirmó al enriquecerla, el motivo. Encima, un resumen indica el
objetivo del nivel y cuántas personas son candidatas, pertinentes y listas; sin
`people_policy` se omite el objetivo. La tabla de la campaña muestra cuántas personas tiene
cada empresa, cuántas son pertinentes y listas, y su mejor match. El match
ordena la revisión; «listo» sigue dependiendo de las reglas de persona y canal. Si falta
un `config/contact_match.json` válido, la ficha lo avisa y muestra a las personas sin
porcentaje ([Porcentaje de match](contacts.md#porcentaje-de-match)).

Cada persona muestra la vigencia de su empleo ([Vigencia del empleo](contacts.md#vigencia-del-empleo-t18)):
el estado (vigente según fuente corporativa o pública, declarado por Apollo, inferido del
historial de Hunter, contradicho o sin comprobar), el motivo en lenguaje comercial, las
fuentes que lo sustentan y la marca «Requiere revisión humana» en los casos ambiguos.
Si la persona no está descartada por regla y su empleo no está comprobado, el aviso
aparece sobre su tarjeta. Un correo de Apollo nunca se presenta como empleo confirmado.

El estado técnico de campaña/etapa, la disponibilidad comercial y la revisión humana
son independientes. Guarda aceptado, rechazado o pendiente con notas y fecha; esto
no recalifica ni cambia la rúbrica. La decisión se elige en un control de tres
opciones y la confirmación aparece como aviso flotante que se retira solo; con
movimiento reducido queda en la página. Las correcciones están disponibles cuando la
campaña ha terminado o está interrumpida, y bloqueadas durante ejecución.

La confirmación manual solo permite canales `linkedin` u `other` existentes de una
persona con identidad, cargo y empleo pertinentes vigentes; si falta la evidencia del
puesto, el formulario queda deshabilitado y explica el motivo. Declara canal directo
comprobado y añade notas de verificación. El pipeline guarda evidencia
manual, fecha y disponibilidad recalculada en una sola transacción. Una URL de perfil
por sí sola no basta; la confirmación tampoco elimina una verificación negativa.

## Exportación CSV

La descarga principal incluye personas actualmente listas con canales utilizables
según las reglas. Al pulsar la descarga, la vista abre una conexión
nueva, consulta SQLite y recalcula frescura; el CSV no reutiliza los bytes de una
pantalla anterior. La descarga bloquea si hay una investigación en curso.
La revisión humana se incluye, pero no exige `accepted` ni reemplaza las reglas
de listo. La opción explícita de
todos los resultados conserva pendientes y empresas sin personas. Los filtros
visuales no cambian la exportación de la campaña.

El CSV tiene una fila por persona; cuando se exporta todo, una empresa sin personas
conserva una fila con esos campos vacíos. Incluye IDs, estados técnicos y comerciales,
score y cobertura, criterios, canales, fuentes con fechas, revisión, advertencias y
motivos. También incluye el porcentaje de match de cada persona, su versión, el motivo
de descarte y el desglose; las filas de cada empresa siguen ese orden. Las columnas
`employment_status` y `employment_reason` llevan el estado y el motivo de la vigencia
del empleo, recalculados al descargar. `person_stage` lleva la etapa de la persona;
`people_candidates`, `people_relevant`, `people_ready`, `people_target` y
`people_policy_version` repiten en cada fila los conteos y el objetivo de su empresa. Un valor desconocido queda vacío, nunca se
convierte en cero.

La descarga usa UTF-8 con BOM, `csv` estándar y todos los campos entrecomillados.
Los textos con prefijos peligrosos para hojas de cálculo se neutralizan anteponiendo
un apóstrofo y un tabulador (`'\t`), también si hay espacios o controles antes del
prefijo. Incluye teléfonos que empiezan por `+`. La fuente original no cambia en
SQLite. Todas las descargas pasan por este mismo camino seguro; no se exporta HTML arbitrario.

Las pruebas de la interfaz, revisión, confirmación y CSV usan proveedores simulados
y SQLite temporal, sin red. Los dos lotes reales de la T09 se ejecutaron desde la interfaz
y su exportación se generó sobre esos datos ([Evaluación de la T09](evaluation.md)).
Ninguno produjo una persona lista, así que la revisión humana y la confirmación manual de
canales solo se han verificado con datos sintéticos.

## Verificación de campaña y ficha del 7 de noviembre de 2026

- `node --test tests/js_navigation.test.cjs tests/js_execution.test.cjs tests/js_motion.test.cjs tests/js_dashboard.test.cjs`:
  19 pruebas pasaron con DOM sintético. Las nuevas cubren el traslado de filas
  sin recrearlas, los desplegables abiertos y la entrada terminada que el sondeo
  no revierte, y el sondeo de campaña que compara secciones y termina sin
  recargar. Se retiró la prueba del presupuesto de la barra superior, que ya no existe.
- La suite completa pasó con **1258 pruebas**; `uv lock --check` y
  `uv run --locked python manage.py check` también pasaron, con bases temporales
  y datos sintéticos.
- En Chrome 157 sin interfaz, sobre la demo sintética, se revisaron campaña y
  ficha a 1440, 1280 y 390 px sin desbordamiento global. Se comprobaron las
  flechas entre pestañas y Tab hacia el panel, Escape en los filtros, el retorno
  del foco al botón del menú y el salto a una fuente desde su píldora. Con
  movimiento reducido no quedó ninguna animación activa y la confirmación de
  guardado apareció como aviso en la página.
- Un arnés temporal fuera del repositorio simuló una investigación sintética de
  siete empresas, sin proveedores. El pulso, la tabla y la barra de filtros
  conservaron sus nodos, ninguna animación de entrada se reinició y, al terminar,
  la página se actualizó sin recargar y habilitó las descargas.
- El detector de Impeccable no dejó advertencias de geometría animada tras
  sustituir anchos y alturas por transformaciones y recortes. Mantiene avisos
  consultivos por medidas fuera de la paleta mínima de `DESIGN.md` y por Inter,
  la fuente elegida. Quedan pendientes Firefox, Safari, un lector de pantalla
  real, el zoom al 200 %, la revisión con ventas y una investigación con
  proveedores reales.

## Verificación del movimiento del resumen del 7 de noviembre de 2026

- `node --test tests/js_navigation.test.cjs tests/js_execution.test.cjs tests/js_motion.test.cjs tests/js_dashboard.test.cjs`:
  17 pruebas pasaron con DOM sintético. Cubren la actualización en su sitio del
  sondeo, que conserva nodos y estilos del puntero, el brillo por proximidad y
  la navegación.
- `uv run --locked python manage.py check` pasó, igual que 195 pruebas
  seleccionadas de interfaz, inicialización, ejecución web, arquitectura e
  identificadores persistidos, con bases temporales y datos sintéticos.
- En Chrome 157 sin interfaz, sin claves y con bases temporales exclusivamente
  sintéticas, se revisaron cuadros de la entrada a velocidad reducida, el brillo
  por proximidad, la inclinación, el reflejo del botón, el foco por teclado, el
  cajón con su indicador, el estado vacío, el historial y la campaña. En 1440 y
  390 px no hubo desbordamiento global; con movimiento reducido, el inicio
  apareció en su estado final sin animaciones activas.
- Un arnés temporal fuera del repositorio simuló una campaña sintética en curso
  durante 36 s, con sondeos cada dos segundos. El panel destacado, la tarjeta de
  revisión, el primer segmento y el botón conservaron sus nodos; no se reinició
  ninguna animación de entrada y solo corrieron las señales de cambio.
- El detector de Impeccable no dejó advertencias tras retirar una transición de
  altura; conserva avisos consultivos por medidas fuera de la paleta mínima de
  `DESIGN.md`. Quedan pendientes Firefox, Safari, un lector de pantalla real, el
  zoom al 200 %, la revisión con ventas y una investigación con proveedores reales.

## Verificación del prototipo del 7 de noviembre de 2026

- `uv run --locked python manage.py check` pasó. Pasaron 171 pruebas
  seleccionadas de interfaz, inicialización, ejecución web, arquitectura e
  identificadores persistidos, con bases temporales y datos sintéticos.
- `node --test tests/js_navigation.test.cjs tests/js_execution.test.cjs tests/js_motion.test.cjs`:
  14 pruebas pasaron con DOM sintético. La reducción de movimiento y la
  alternativa sin JavaScript se revisaron mediante código y pruebas, sin
  emulación manual en el navegador.
- En una demo temporal sin claves ni llamadas a proveedores, se revisó el inicio
  a 1280, 1366, 1440 y 390 px sin desbordamiento global, y se comprobó la
  separación del historial. Se comprobaron el cierre del menú con Escape, el
  retorno y la contención del foco, y la visibilidad del presupuesto y el aviso
  sintético. Las propuestas se revisaron a 1440 y 390 px; sus tablas desplazan
  contenido sin desplazar la página.
- La revisión independiente de código no encontró hallazgos materiales; incluyó
  los flujos de autorización y sondeo.
- La revisión visual independiente no observó otros defectos materiales en las
  capturas iniciales. Tras corregir el logotipo, confirmó que Veryfi y Prospecting
  se leen sin solapamientos en inicio e historial a 390 px. Sigue pendiente la
  revisión del usuario antes de extender las distribuciones de campaña y ficha.
- Se comprobaron ocho pares principales de la paleta, con un contraste mínimo de
  7.70:1. Esta comprobación no es una auditoría completa de la interfaz.
- El detector de diseño señaló Inter, el resplandor radial y la deriva de la
  versión anterior de `DESIGN.md`; no interpretó las plantillas Django. Quedan
  pendientes el zoom real al 200 %, un lector de pantalla real, la evaluación
  con ventas y las llamadas a proveedores reales.

## Verificación del rediseño anterior del 7 de noviembre de 2026

- Tras integrar los cambios de `main`, la suite completa pasó con **1209 pruebas**;
  `uv lock --check` y `uv run --locked python manage.py check` también pasaron.
  Las pruebas usan datos sintéticos y bases temporales.
- `node --test tests/js_navigation.test.cjs tests/js_execution.test.cjs`: ocho
  pruebas pasan con DOM y respuestas sintéticas. Cubren navegación, foco,
  resumen de preparación, bloqueos de ejecución y sincronización del presupuesto
  durante el sondeo; no sustituyen un navegador real.
- Se revisaron las cuatro vistas con datos sintéticos a 1440 y 390 px, y se
  midieron a 1366 y 1280 px sin desbordamiento global. En móvil se comprobó el
  cierre del menú con Escape y el retorno del foco; en la ficha, la selección de
  Contactos con flecha derecha y la presencia de la vigencia del empleo con sus
  fuentes. La revisión independiente confirmó los ajustes de desbordamiento en
  el inicio móvil y del contexto visible del presupuesto.
- El zoom real al 200 % no se verificó: el navegador integrado no cambió la escala
  al recibir los atajos. Tampoco se hizo un estudio con ventas ni llamadas reales
  a proveedores para este rediseño.

## Verificación de la reorganización del 13 de octubre de 2026

- Django separa configuración global en `config/`, interfaz en `core/`, plantillas
  en `templates/` y recursos en `static/`. Las vistas permanecen juntas y el
  namespace público `webapp` se conserva; el paquete antiguo ya no existe.
- `uv lock --check`, `uv run --locked python manage.py check` y la suite completa:
  802 pruebas pasan sin red externa, incluidas tres comprobaciones de carga de
  CSS, JavaScript y logotipo con `DEBUG=False` y sin crear una base.
- La comparación del código confirma las mismas implementaciones y aserciones
  anteriores, salvo las ubicaciones. Las plantillas solo cambian referencias;
  CSS, JavaScript y logotipo conservan su contenido. `prospecting/`, el catálogo,
  la persistencia y las dependencias no cambiaron.
- Los comandos de ejecución siguen iguales. No se realizaron llamadas reales a
  proveedores ni otra revisión visual: esta reorganización conserva el diseño.

## Verificación de la migración a Django del 13 de octubre de 2026

- `uv lock --check`, `uv run --locked python manage.py check` y la suite completa:
  799 pruebas pasan. Las pruebas de negocio conservan sus aserciones; se trasladaron
  los escenarios de interfaz a Django y se añadieron casos de CSRF, ejecución en
  un hilo, clics duplicados, bloqueo de acciones y recuperación.
- Se revisaron nueve capturas exclusivamente sintéticas: historial, campaña,
  contactos, evidencia, preparación y autorización, en anchos de 1440, 1280 y 390 px.
  La navegación móvil y las pestañas conservan acceso por teclado; los filtros tienen
  nombres accesibles distintos. No se observaron desbordamientos de página.
- Revisión independiente de código y diseño aprobada; detector de Impeccable sin
  hallazgos. Se usa el logotipo blanco del media pack oficial de Veryfi y los colores
  de su [guía de marca](https://www.veryfi.com/brand/), sin fuentes ni scripts remotos.
- Streamlit y sus dependencias quedaron retirados. `prospecting/`, el catálogo,
  el esquema persistido y el evaluador offline no se modificaron.
- No se ejecutaron proveedores reales desde Django ni se probó con un lector de
  pantalla real. Detener el servidor interrumpe el hilo; no hay cola persistente.

## Verificación histórica de Streamlit del 12 de octubre de 2026

- `uv lock --check` y `uv run --locked pytest`: 709 pruebas pasan, sin red externa;
  incluyen 14 casos de interfaz con `AppTest` y bases temporales.
- Inspección de la interfaz con fixtures explícitamente sintéticas en escritorio
  (1440 píxeles), móvil (390) y panel estrecho (470). La revisión del ancho de
  «Encaje» confirmó que «Desconocido» se muestra completo.
- Descarga desde el navegador y apertura de un CSV sintético en Excel, en modo
  solo lectura: 38 columnas, 3 filas incluida la cabecera y cero celdas con fórmulas.
  Se conservaron las tildes y el texto literal `=1+2` neutralizado.
- No se ejecutaron proveedores reales desde la nueva interfaz, ni se verificó
  LibreOffice o el comportamiento después de editar y volver a guardar el CSV.
