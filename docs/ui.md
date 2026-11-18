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

El Resumen se centra en la campaña activa o, si no la hay, en la última guardada.
«Retomar revisión» abre la ficha de la primera empresa pendiente cuando la campaña
admite decisiones. Las cifras de avance, revisión y disponibilidad corresponden
a esa misma campaña. Una empresa con contacto listo puede seguir pendiente de revisión.

En una campaña preparada, «Abrir campaña» lleva a los criterios y a la
autorización. Durante una investigación, «Seguir investigación» abre el avance
y los resultados parciales. El Resumen actualiza el estado cada dos segundos.
Si aún no hay empresas descubiertas, el avance queda indeterminado. Al terminar
la ejecución se habilita la revisión. «Ver resultados» abre una campaña ya
revisada o una campaña histórica de consulta. Para empezar desde una base vacía,
elige «Preparar campaña».

La cabecera de escritorio ofrece Resumen, Historial y Nueva campaña. En móvil,
el menú reúne esos accesos. El historial (`/campaigns/`) permite identificar una
campaña por su mercado, fecha y estado antes de abrirla.

## Preparar y ejecutar

1. En Mercado y Alcance, selecciona países, segmentos, palabras clave opcionales y
   un máximo de 1–20 empresas. Revisa los criterios y topes en Resumen.
   Crear la campaña guarda los criterios y la instantánea de configuración, incluida
   la propuesta `contact_match_v3`, sin tráfico. La versión y sus pesos no cambian al
   editar después el archivo local. Si la configuración v3 falta o no es válida, se
   informa el error y no se guarda la campaña nueva.
   En Cuentas objetivo puedes pegar hasta 20 empresas, una por línea, como
   `dominio, nombre, país` (el nombre y el país son opcionales; el país es `CO` o `MX`).
   Con cuentas objetivo la campaña investiga exactamente esas empresas, sin buscar otras
   en la web, y el máximo de empresas pasa a ser su número. Una línea inválida se señala
   con su número y no se guarda nada.
2. Revisa las operaciones y sus topes en la autorización. Ejecutar requiere claves en
   el entorno y un archivo válido `data/provider-access.json`.
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
    "plan": "free",
    "rate_limits": {
      "people_search": {"per_minute": 50, "per_hour": 200, "per_day": 600},
      "people_enrichment": {"per_minute": 50, "per_hour": 200, "per_day": 600}
    }
  }
}
```

`rate_limits` es opcional: sin él rigen los límites publicados para el plan Free, y con
plan `free` solo se admiten valores iguales o más estrictos. Solo se aceptan cupos de
Tavily, Anthropic y Apollo: un cupo de un proveedor retirado, como Hunter, invalida el
archivo y bloquea la ejecución hasta quitarlo (T17).

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
de Tavily y Anthropic, retira `hunter_access` y el cupo de Hunter del archivo (ya no se
cargan) y agrega
la cuenta y comprobación reales de Apollo cuando estén disponibles. No completes
campos con los valores sintéticos del ejemplo: la configuración antigua no habilita
una ejecución nueva. Cambiar ese archivo no borra el ledger histórico de SQLite;
conserva la base y sus archivos auxiliares.

La autorización muestra el disponible asociado a cada operación. Una reserva incierta se
conserva hasta conciliarla. El archivo de acceso no habilita operaciones adicionales ni
altera límites del catálogo. La lista opcional de exclusiones está en
`data/exclusions.json`: si falta o no está validada, no se afirma que se aplicó una
lista validada.

## Resultados y revisión

En una campaña preparada se revisan las autorizaciones y topes antes de ejecutar.
Durante la investigación, la franja de avance aparece antes de la lista de
resultados parciales e indica cuántas empresas encontradas han terminado. La
pantalla consulta el estado cada dos segundos y se actualiza al finalizar.

En la campaña terminada, los resultados aparecen primero y la franja de avance
queda debajo. La lista reúne nombre, dominio, encaje, prioridad, disponibilidad,
revisión y cantidad de contactos. Puedes buscar por nombre y
filtrar por país, segmento, prioridad o disponibilidad. Abre el nombre para leer
la ficha. «Volver a la campaña», «Anterior», «Siguiente» y «Guardar y siguiente»
respetan los filtros vigentes al abrirla. Desde «Descargar» puedes elegir entre
todas las empresas y las listas para contacto.

La ficha abre con el nombre de la empresa y el motivo de encaje cuando se conoce.
Resumen recoge la puntuación, productos, cobertura y criterios. Cada criterio
lleva una etiqueta como «Señal fuerte», «Señal parcial», «Incompatible» o «Sin
evidencia». Contactos reúne a las personas encontradas. La decisión de ventas
se presenta junto al detalle en escritorio y dentro del recorrido de lectura en
móvil. Los fallos de lectura identifican la etapa, la URL y el motivo. Los datos
pendientes se muestran como tales.

En una campaña con `rubric_v2`, la tabla conserva el orden de la lectura pública:
prioridad, necesidad documental `1` y score descendente, con desempate estable.
La exportación mantiene ese orden. Las campañas con `rubric_v1` conservan su
orden anterior; la candidata v2 sigue pendiente de su evaluación académica.

La pestaña Contactos lista a las personas encontradas con nombre, cargo y match, con
separación entre ellas. Cada canal identificado muestra su tipo y valor, ofrece copiarlo
y conserva visibles la fecha y las notas de una comprobación anterior.
Cuando la acción está disponible, un botón «Confirmar canal» por persona abre un panel
para seleccionar el canal y registrar la comprobación. Se conservan las señales de
descarte y contradicción.
El desglose del match permanece en el CSV.
En la lectura con v3, las personas no descartadas y la pertinencia preceden al porcentaje.
La ficha, los listados y el CSV muestran v3 también para campañas anteriores, sin
reescribir su instantánea. La investigación conserva la versión de su campaña; el orden
histórico puede diferir del mostrado. El match no sustituye las reglas de «listo»
([Porcentaje de match](contacts.md#porcentaje-de-match)).
La [vigencia del empleo](contacts.md#vigencia-del-empleo-t18) distingue lo comprobado
de lo pendiente o contradictorio; un correo no confirma por sí solo el empleo.

El estado técnico de campaña/etapa, la disponibilidad comercial y la revisión humana
son independientes. La revisión guarda para la empresa la decisión de ventas
(aceptado, rechazado o pendiente), con sus notas y fecha. Tras guardar se muestra
una confirmación. La puntuación sigue la rúbrica de la campaña. Las correcciones
están disponibles cuando la campaña ha terminado o está interrumpida y se bloquean
durante la ejecución.

La confirmación manual admite cualquier tipo de canal existente, aunque la persona aún
no tenga identidad, cargo o empleo confirmados. En el panel se elige uno de sus canales
que no esté marcado como inválido y se escriben notas de comprobación obligatorias;
se guarda la fecha, sin casilla adicional. La confirmación respeta las exclusiones y no
elimina una verificación negativa; está bloqueada durante la ejecución y en campañas
históricas. La comprobación de correo, teléfono o WhatsApp conserva la validación del
proveedor. LinkedIn y otros canales conservan la confirmación manual existente.

La ficha no ofrece confirmar el empleo por separado. La API y las confirmaciones de
empleo ya guardadas se conservan ([Confirmación manual del empleo](contacts.md#confirmación-manual-del-empleo-t23)).

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
del empleo, recalculados al descargar. Con una confirmación manual vigente (T23),
`employment_basis` vale `manual` y `employment_confirmed_at`,
`employment_confirmation_reason` y `employment_confirmation_source` llevan su fecha, motivo y
URL. Con evidencia pública vale `source`, y sin vigencia comprobada queda vacía.
`employment_corroboration` lleva el resultado de la búsqueda dirigida (T24): `corroborated`,
`searched_not_corroborated`, `employment_search_limit` o el código del rechazo; queda vacía
si la persona no se buscó ni quedó pendiente.
`function_id` lleva la función del cargo y
`people_functions` la lista JSON de funciones representadas por personas pertinentes.
`person_stage` lleva la etapa de la persona;
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
canales solo se han verificado con datos sintéticos. La confirmación manual del empleo (T23)
se verificó con pruebas sin red y en el navegador local sobre una base temporal
exclusivamente sintética; no se ha usado con personas reales. El resultado y la columna
de la corroboración dirigida (T24) se verificaron con pruebas sin red.

## Verificación del rediseño editorial

En Chromium se recorrieron Resumen, Historial, Nueva campaña, Campaña y Ficha
con la demo sintética a 1440 y 390 px. También se comprobó el zoom del navegador
al 200 %. Desde una lista filtrada se abrió una empresa, se usó «Guardar y
siguiente» y se volvió a la campaña conservando los filtros. Se descargaron
ambos CSV, «Descargar listos» y «Descargar todos».

Se comprobó la navegación con teclado, el menú sin JavaScript y la preferencia
de movimiento reducido. Los pares de texto y fondo medidos cumplieron el umbral
AA de contraste. La revisión con un lector de pantalla real queda pendiente.

## Verificaciones de versiones anteriores

Los siguientes registros corresponden al diseño y las funciones disponibles en la
fecha de cada comprobación.

### Verificación de la paleta de Veryfi del 7 de noviembre de 2026

- La paleta procede de las imágenes de la [guía de marca](https://www.veryfi.com/brand/)
  y de las variables y el degradado del botón principal de veryfi.com, consultados ese día.
  Solo cambian colores; la distribución, el texto y la conducta se conservan.
- Contraste calculado (WCAG 2.x): texto marfil sobre lienzo 15.71:1 y sobre paneles
  13.91:1; texto secundario 7.89:1 como mínimo; estados sobre su fondo entre 5.60:1
  (error) y 8.82:1 (aviso); texto navy sobre verde 11.78:1 y sobre turquesa 6.85:1;
  bordes de controles 3.63:1.
- `node --test tests/js_navigation.test.cjs tests/js_execution.test.cjs tests/js_motion.test.cjs tests/js_dashboard.test.cjs`:
  19 pruebas pasaron. Pasaron 185 pruebas de inicialización, interfaz, rediseño,
  campaña, demostración, arquitectura e identificadores persistidos, y
  `uv run --locked python manage.py check`.
- En Chrome 157 sin interfaz, sobre la demo sintética, se revisaron inicio, historial,
  nueva campaña, campaña, ficha (Resumen, Contactos y Evidencia) y el cajón abierto a
  1440 px, y las mismas vistas con 512 px, el ancho mínimo de esa ventana. Los
  estilos calculados confirmaron que las mezclas `color-mix()` se resuelven, también
  en los destellos de Web Animations que leen `--accent`. Una simulación de
  deuteranopía y protanopía sobre la campaña mantuvo legibles los estados por su
  texto e iconos.
- El detector de Impeccable quedó sin halos de color sin desplazamiento tras retirar
  los de la línea de pestañas y la etapa lista. Mantiene el aviso por el degradado
  verde-turquesa, que reproduce el de veryfi.com, y los previos por Inter, la
  primera columna de la ficha y la sombra de los desplegables; su lectura de
  contraste del pie del resumen se toma durante la entrada (calculado: 9.81:1).
  Quedan pendientes Firefox, Safari, 390 px reales, un lector de pantalla y la
  revisión con ventas.

### Verificación de campaña y ficha del 7 de noviembre de 2026

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

### Verificación del movimiento del resumen del 7 de noviembre de 2026

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

### Verificación del prototipo del 7 de noviembre de 2026

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

### Verificación del rediseño anterior del 7 de noviembre de 2026

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

### Verificación de la reorganización del 13 de octubre de 2026

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

### Verificación de la migración a Django del 13 de octubre de 2026

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

### Verificación histórica de Streamlit del 12 de octubre de 2026

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
