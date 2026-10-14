# Entrega y condiciones del piloto

Estado al 14 de octubre de 2026 (America/Bogota). Informe de la entrega según IDEA §15,
§17.2, §19 y §4.3. Separa resultados medidos, estimaciones y trabajo posterior, y lo real
de lo sintético. No contiene claves, datos personales ni nombres de empresas reales: esos
datos permanecen en `data/`, fuera de Git.

El prototipo es académico. No se presenta como un sistema productivo validado: el catálogo,
la rúbrica y las reglas son propuestas pendientes de validación por Veryfi.

## Qué se entrega

| Pieza | Dónde | Estado |
|---|---|---|
| Código del prototipo | `prospecting/`, `core/`, `config/`, `templates/`, `static/` | Funciona en una instancia local; ver límites |
| Instalación, ejecución y verificación | [README](../README.md) | Comprobadas desde un clon limpio en Windows |
| Demostración sin consumo | `demo.py` ([README](../README.md#demostración-sin-consumo)) | Datos exclusivamente sintéticos |
| Guías técnicas | [persistencia](persistence.md), [presupuesto](budget-providers.md), [descubrimiento](discovery.md), [calificación](qualification.md), [contactos](contacts.md), [campañas](campaign.md), [interfaz](ui.md) | Vigentes |
| Proveedores reales | [Comprobación de proveedores](provider-check.md) | Llamadas, gasto y conciliación |
| Evaluación | [Lotes T09](evaluation.md), [protocolo T10](t10-evaluation.md), `evaluate_qualification.py` | Mecanismo listo; validación comercial pendiente |
| Producto y diseño | `PRODUCT.md`, `DESIGN.md` | Contexto de ventas y decisiones visuales |

## Estado frente a los criterios de terminación

### MVP del 16 de octubre

| Criterio (IDEA §19) | Estado | Evidencia |
|---|---|---|
| Ejecución que parte de criterios y descubre empresas reales | Cumplido | Dos lotes de T09 y el lote de la entrega, con Colombia, México y ambos segmentos |
| Evidencia, puntuación con desglose, esfuerzo y búsqueda de personas con Tavily y Hunter | Cumplido | [Evaluación T09](evaluation.md#lotes-reales) y [lote de la entrega](evaluation.md#lote-real-de-la-entrega-t11) |
| Al menos un prospecto real completo | **No cumplido** | Los dos lotes de T09 y el de la entrega terminaron con 0 personas listas |
| Ningún registro listo incumple la regla de canal directo | Cumplido | 0 listos sin relajar reglas; pruebas de §18.1 |
| UI, revisión y exportación | Parcial | Ejecución y exportación con datos reales; revisión y confirmación manual solo con datos sintéticos (pruebas y demo) |
| Pruebas críticas en verde | Cumplido | 941 pruebas sin red; ver reproducibilidad |
| Gasto conciliado ≤ USD 20, con cupo y margen visibles | Cumplido | [T09](#proveedores-reales-t09) y [lote de la entrega](#lote-real-de-la-entrega) |
| Proveedores, limitaciones y siguiente mejora documentados | Cumplido | Este informe, `provider-check.md` y `evaluation.md` |

### Entrega del 6 de noviembre

| Criterio (IDEA §19) | Estado | Evidencia |
|---|---|---|
| Revisión documentada con Veryfi | Pendiente | No hay etiquetas, catálogo ni exclusiones confirmados por Veryfi |
| Métricas por país y segmento | Parcial | Tablas de T09 y del lote de la entrega sobre 24 selecciones; sin precisión comercial |
| Rúbrica versionada | Cumplido | `rubric_v1` (propuesta), prompt `haiku_assessment_v3`, catálogo `catalog_v1` pendiente de validación |
| Calificación con Haiku evaluada en un conjunto separado | Pendiente | Evaluador offline y protocolo listos; falta el conjunto independiente y la revisión |
| Manejo de errores probado | Cumplido | Fallos simulados en pruebas; los timeouts reales de Tavily conservaron etapa, motivo y reservas |
| Instrucciones de ejecución | Cumplido | README verificado desde un clon limpio |
| Datos de demostración seguros | Cumplido | `demo.py`: base temporal sintética, sin claves ni ejecución |

## Resultados medidos

### Reproducibilidad y pruebas

Verificación del 14 de octubre en Windows 11 con uv 0.13.0, Python 3.13.16 y Node.js 24.21.0,
sobre un clon limpio del repositorio:

- `uv sync --locked`, `uv lock --check` y `manage.py check` sin errores.
- `uv run --locked pytest`: **932 pruebas aprobadas en 51,9 s**, sin red y con bases temporales.
  Tras corregir los mensajes de parada, la suite local suma 941 pruebas aprobadas.
- `node --test tests/js_execution.test.cjs`: 2 de 2.
- `git check-ignore` confirma que `.env`, `.venv/`, `data/`, bases SQLite y cachés quedan fuera de Git.
- `demo.py` responde en `127.0.0.1:8000` con el aviso de datos sintéticos.
- Con el clon en una ruta de más de 100 caracteres, cuatro módulos de prueba no cargan
  (`ModuleNotFoundError` en `anthropic`) por el límite de 260 caracteres de Windows. El README
  lo advierte. No se verificaron macOS ni Linux.

Recorrido de la demostración en el navegador integrado: los siete estados comerciales, la
confirmación manual de LinkedIn que pasa a `ready_alternative`, la revisión aceptada, los dos
CSV con prefijo `demo-sintetica-` y la fórmula neutralizada, el texto hostil mostrado como
texto plano, la consola sin errores y el ancho de 390 px sin desbordamiento horizontal.

### Proveedores reales (T09)

Dos campañas del 12 de octubre, de 8 empresas cada una, con Colombia, México y ambos
segmentos ([detalle](evaluation.md#lotes-reales)):

| Medida | Valor |
|---|---|
| Identidad confirmada | Lote 1: 3 / 8 (más un directorio tomado por empresa, corregido); lote 2: 5 / 8 |
| Empresas calificadas distintas (`medium`) | 5; ninguna `high` ni `low` |
| Por segmento, prioridad media | FinTech 7 / 8 selecciones; CPG 1 / 8 |
| Búsquedas de Hunter con personas | 1 / 8 Domain Search |
| Cobertura de contacto | 0 / 5 empresas calificadas; 0 personas listas |
| Llamadas a Tavily sin respuesta | 6 / 63 (9,5 %) |
| Tiempo automático | 110 s y 140 s por lote |
| Reserva de Haiku frente a costo conciliado | Unas 2,4 veces |

Gasto conciliado con los paneles: Tavily 45 créditos gratuitos en T09 (panel 52 / 1.000),
Hunter 1 crédito gratuito (panel 2 / 50) y Haiku USD 0,0146218. El ledger acumula
USD 0,0189886 en Haiku; la consola muestra unos USD 0,0019 más de otra instancia del equipo,
fuera de este control. El total queda muy por debajo de USD 20, del límite operativo de
USD 15 y del de USD 2 por campaña.

No se midieron precisión de empresas, pertinencia de personas ni costo por prospecto aceptado:
requieren revisión de Veryfi y al menos un prospecto aceptado.

### Lote real de la entrega

Campaña del 14 de octubre, autorizada por el responsable del cupo, con 8 empresas, Colombia,
México y ambos segmentos ([resultados](evaluation.md#lote-real-de-la-entrega-t11),
[llamadas y conciliación](provider-check.md#lote-real-de-la-entrega-t11)):

| Medida | Valor |
|---|---|
| Identidad confirmada | 6 / 8 |
| Prioridad | 4 `medium`, 1 `low`, 3 `insufficient_evidence` |
| Búsquedas de Hunter con personas | 2 / 4 |
| Personas con correo verificado | 3, sin evidencia de empleo vigente |
| Personas listas | **0** |
| Llamadas sin respuesta | 0 / 43 |
| Tiempo automático | Unos 100 s |
| Gasto conciliado | 21 créditos de Tavily, 2 de Hunter y USD 0,0094070 de Haiku, dentro de los topes autorizados |

El acumulado conciliado queda en 73 créditos de Tavily (de 1.000), 4 de Hunter (de 50) y
USD 0,0283956 de Haiku en este ledger, más unos USD 0,0019 de otra instancia.

## Estimaciones

Valores para planear; no son mediciones ni compromisos:

- Un lote de 8 empresas como los observados consumiría del orden de 20 a 25 créditos de Tavily,
  USD 0,01 de Haiku y 0 a 2 créditos de Hunter Domain Search. Depende de las empresas, de los
  timeouts y de la cobertura de Hunter.
- Con los precios publicados de Haiku 5.5, 100 solicitudes de 6.000 tokens de entrada y 1.000
  de salida costarían unos USD 0,11 (IDEA §14). El dato de contacto puede pesar más que la inferencia.
- El indicador de gasto de la interfaz es una estimación controlada que no reemplaza la
  facturación: las reservas son cotas superiores hasta conciliar.
- No hay línea base de investigación manual: no se estima ahorro de tiempo. La muestra no
  permite generalizar cobertura a Latinoamérica, a cada país ni a cada segmento.

## Límites de producción

El prototipo no está preparado para un uso productivo. Estos límites son de diseño, no fallos:

- **Servidor**: es el servidor de desarrollo de Django, no apto para producción [W8]. Escucha
  solo en `127.0.0.1` y rechaza conexiones externas; no tiene HTTPS.
- **Usuarios y permisos**: no hay autenticación, cuentas, roles ni registro de quién revisa.
  Cualquier proceso local con acceso al equipo puede usar la interfaz.
- **Ejecución**: una instancia, una campaña activa y procesamiento secuencial en un hilo del
  servidor. Detener el servidor interrumpe la investigación; no hay cola persistente ni
  reanudación automática. Dos procesos sobre la misma base no se coordinan.
- **Datos**: SQLite local en `data/`, sin copias de seguridad automáticas, cifrado, política
  de retención ni eliminación programada.
- **Presupuesto**: el control vive en cada base. Instancias distintas no comparten el límite
  global; T09 ya registró uso de Anthropic fuera de este ledger. Los cupos se cargan a mano
  en `data/provider-access.json` y cada ejecución exige autorización nueva.
- **Reglas comerciales**: catálogo, rúbrica, umbrales y cargos son propuestas; la lista de
  exclusiones de Veryfi no existe aún. Los plazos de vigencia (30 días para correos, 180
  para cargos) son reglas del prototipo, no garantías de los proveedores.
- **Vigencia**: no hay revalidación periódica de cargos ni canales; la disponibilidad se
  recalcula al consultar con la fecha actual, sin nuevas llamadas.
- **Tamaño de las solicitudes a Haiku**: el límite de 6.000 tokens de entrada se aplica como
  presupuesto de caracteres. 23 de las 31 llamadas registradas lo superaron en tokens (máximo
  8.721). El gasto sigue acotado por la reserva, pero el límite de IDEA §12.1 no se cumple en tokens.
- **Observabilidad**: no hay monitoreo, alertas ni registro centralizado de errores.
- **Contacto**: la aplicación nunca envía mensajes ni verifica canales escribiendo a nadie.
  LinkedIn se confirma solo manualmente; no se automatiza ni se extraen perfiles.
- **Datos personales**: el tratamiento de contactos profesionales en cada país, su base legal,
  retención y eliminación no se han acordado con Veryfi (IDEA §15).

Limitaciones conocidas de la interfaz, observadas en T09: interactuar con la página durante
una ejecución la interrumpe de forma segura y preparar otra campaña con una activa abre la
activa sin avisar.

La demostración reveló que la ficha de una empresa lista, excluida o de encaje bajo mostraba
el aviso genérico «La investigación quedó pendiente…». Se corrigió el 14 de octubre: las
paradas previstas tienen mensaje propio en tono informativo y los pendientes de identidad,
mensajes específicos. Otros motivos técnicos poco frecuentes conservan el texto genérico.

## Condiciones mínimas para un piloto

Propuesta según IDEA §19, §15 y §4.3. Las metas de §18.2 (80 % de aceptación de empresas,
90 % de pertinencia de personas y 100 % de afirmaciones con procedencia) son orientativas para
discutir con Veryfi, no resultados obtenidos.

| Condición | Estado actual |
|---|---|
| Prospectos reales completos que ventas considere útiles, revisados y aceptados | No cumplido: 0 listos en T09 y en el lote de la entrega |
| Revisión documentada de Veryfi: catálogo, exclusiones, ejemplos etiquetados y criterios de cargo | Pendiente |
| Calificación evaluada en un conjunto independiente, con métricas por país y segmento | Pendiente; protocolo en `t10-evaluation.md` |
| Etapa de personas mejorada y medida frente a la línea base: Hunter con personas en 1 de 8 búsquedas (T09) y 2 de 4 (entrega), sin empleo vigente demostrado | Pendiente |
| Presupuesto operativo y responsable del cupo, con cuentas de la organización y condiciones de uso verificadas | Sin presupuesto posterior al 16 de octubre (IDEA §2); cuentas gratuitas del equipo |
| Usuarios definidos y responsable de datos; fuentes permitidas, retención y eliminación acordadas | Pendiente de acordar con Veryfi |
| Entorno de acceso apropiado: autenticación, permisos, HTTPS, servidor de aplicaciones, almacenamiento con respaldo, trabajos persistentes y monitoreo | No existe; requiere una decisión de despliegue y acceso separada (IDEA §4.3) |

## Trabajo posterior

En orden de prioridad según la evidencia disponible:

1. **Etapa de personas**: es el cuello de botella medido. En el lote de la entrega Hunter halló
   tres personas pertinentes con correo verificado, pero ninguna con evidencia de empleo vigente.
   Buscar esa evidencia con procedencia (directorios y páginas de equipo corporativas actuales o
   fuentes fechadas) y evaluar una fuente adicional (Apollo, T12, o X-Ray Search, T13) frente a
   esta línea base, sin relajar las reglas de listo ni ampliar el presupuesto implícitamente.
2. **Cierre comercial de T10**: revisión atribuible de Veryfi, conjunto independiente de hasta
   20 empresas nuevas y conclusión sustentada.
3. **Lista de exclusiones y catálogo** confirmados por Veryfi.
4. **Identidad en CPG**: los sitios promocionales rara vez confirman nombre y país.
5. **Plazo de Tavily**: en T09 el 9,5 % de las llamadas no respondió en unos 10 s; en el lote
   de la entrega, ninguna. Vigilarlo antes de cambiar el plazo.
6. **Tamaño de las solicitudes a Haiku**: calibrar la conversión de caracteres a tokens para
   respetar el límite de entrada.

## Datos locales al cerrar la entrega

Inventario de la copia local revisada el 14 de octubre, solo con conteos:

- `data/prospecting.sqlite3`: 6 campañas (2 preparadas, 1 terminada y 3 parciales de 8
  empresas: los dos lotes de T09, compatibles con sus registros, y el de la entrega), 27
  empresas, 3 contactos y 33 evaluaciones. El ledger registra 158 solicitudes; una de Hunter de
  T07 sigue sin conciliar.
- `data/backups/`: 7 copias de la base previas a T07, T09, el lote de la entrega y sus
  conciliaciones, y la versión anterior del archivo de acceso.
- `data/conciliaciones/`: 16 comprobantes de los paneles y del uso informado por los proveedores.
- `data/provider-access.json`: cupos y referencias comprobadas, sin claves.

T10 registró que la copia que examinó no contenía los lotes de T09. Esta copia sí parece
contenerlos; el responsable de T10 debe confirmar sus identificadores antes de usarlos.

Recomendación (IDEA §15): conservar estos archivos hasta cerrar T10 y la conciliación. Después,
conservar el ledger y los comprobantes como trazabilidad del gasto y eliminar los contactos
reales y los extractos que no se necesiten. No se ha borrado nada: eliminar datos locales
requiere autorización explícita del equipo.

## Guion de la demostración

1. **Propósito y límites** (1 min): investiga y prepara oportunidades; ventas contacta fuera
   de la aplicación. Encaje no es probabilidad de compra.
2. **Demostración sintética** (`uv run --locked --offline python demo.py`, 5–7 min):
   - Historial y campaña: siete empresas ficticias, filtros, prioridades y presupuesto sin consumo.
   - Empresa sintética Pagos: listo con canal preferido; encaje 88,9 y cobertura 90 %, el
     ejemplo de IDEA §8.2, con criterios, evidencia y procedencia.
   - Empresa sintética Promociones: solo LinkedIn; la confirmación manual declara acceso sin
     enviar nada y la empresa pasa a listo con canal alternativo.
   - Empresa sintética Facturas: evidencia insuficiente; el texto hostil se muestra como texto.
   - Empresa sintética Cliente Actual y Logística: exclusión y encaje bajo.
   - Revisión «Aceptado» y descarga de los dos CSV.
3. **Resultados reales** (2 min): presentar en agregado las tablas de [T09](evaluation.md) y
   del lote de la entrega, y por qué ninguna persona quedó lista. Sin capturas con empresas o
   personas reales.
4. **Límites y condiciones del piloto** (2 min): las dos secciones anteriores.
