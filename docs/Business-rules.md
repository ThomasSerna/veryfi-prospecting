# Reglas de negocio

Reglas vigentes de descubrimiento, identidad, evidencia, calificación, esfuerzo de búsqueda, personas y canales. Forma parte de la documentación de requisitos: ver el [índice](IDEA.md). Las cifras son propuestas iniciales (`rubric_v1`, `contact_match_v1`) pendientes de validación con Veryfi. El flujo de etapas está en [Architecture.md](Architecture.md#flujo-de-investigación). Los topes de gasto están en [Budget-policy.md](Budget-policy.md).

T14 propone `rubric_v2` para evaluación académica; su activación queda condicionada a la comparación indicada más abajo. `rubric_v1` sigue vigente para las campañas históricas y como valor predeterminado mientras no se cumpla esa condición. Los issues T16 (parada y número de personas por cuenta), T18 (vigencia del empleo) y T19 (`contact_match_v2`) proponen modificar otras reglas de este archivo.

## Descubrimiento

Usar Tavily Search como primera opción. Construir consultas combinando país, perfil y señal de necesidad: gestión de gastos con recibos, plataformas de pagos con facturas, promociones con tickets o programas de puntos por compras. Empezar con plantillas; Haiku solo reformula cuando los resultados sean insuficientes y quede presupuesto. La reformulación con Haiku no está implementada en el MVP: el descubrimiento usa solo plantillas, y el informe de combinaciones que no alcanzan su meta vive en memoria, sin mostrarse en la interfaz.

Fuentes candidatas: páginas de producto, centros de ayuda, campañas y sus condiciones, directorios sectoriales públicos, asociaciones FinTech, noticias corporativas y vacantes. Los directorios y noticias generan candidatos; confirmar identidad y actividad en una fuente primaria cuando sea posible.

Para una ejecución con ambos países y segmentos, intentar cinco empresas por combinación (CO/FinTech, CO/CPG, MX/FinTech, MX/CPG). Es una estrategia de prueba, no una cuota obligatoria: informar si alguna combinación no ofrece suficientes resultados y no rellenar con empresas inventadas.

Límites iniciales: ocho consultas de descubrimiento, hasta diez resultados por consulta y hasta sesenta candidatos brutos antes de deduplicar/seleccionar un máximo de veinte empresas para análisis. No interpretar «20 empresas» como «20 prospectos garantizados».

## Identidad y exclusiones

Resolver nombre, dominio oficial, país de operación y segmento. El dominio es una señal de identidad, acompañado de nombre/entidad/país y alias verificados. No deduplicar solo por nombre ni solo por dominio cuando existan filiales o marcas distintas.

Aplicar una lista local de clientes actuales, oportunidades en curso y exclusiones suministrada por Veryfi. Guardar motivo, fuente y alcance de la exclusión: entidad, país o grupo. Si esa lista aún no existe, mostrar «exclusiones comerciales no validadas»; no afirmar que se comprobó ausencia de relación previa.

Excluir antes del enriquecimiento: entidades inequívocamente fuera del país/segmento elegido, dominios no empresariales, duplicados confirmados y cuentas explícitamente excluidas. Identidad ambigua pasa a pendiente. Un tamaño desconocido o pequeño no produce exclusión automática. En la implementación, una empresa sin operación comprobada en los países de la campaña queda pendiente (`country_unconfirmed`), no excluida: un ccTLD extranjero solo añade una advertencia, y sin identidad confirmada no se buscan personas.

## Evidencia

Guardar hechos atómicos, cada uno con texto breve, URL o referencia de proveedor, fecha de consulta y, si existe, fecha de publicación/actualización. Mantener separadas afirmación observada, inferencia y dato desconocido.

No tratar el resumen del buscador como confirmación definitiva de cargo o canal: sirve para localizar la fuente. Un dato de proveedor puede usarse como tal, identificándolo, aunque no traiga URL pública; conservar referencia de registro y estado que devolvió.

Reutilizar evidencia vigente entre ejecuciones. Valor inicial de caché: treinta días para páginas/búsquedas y treinta días para datos de contacto. Consultar una página hoy no convierte en actual una noticia antigua. Si hay contradicciones o indicios de cambio de cargo, suspender la condición de listo y revisar.

## Calificación explicable

### Qué significa la puntuación

La puntuación mide **encaje observable con la oferta**, no probabilidad de compra, solvencia ni intención demostrada. Mostrar aparte cobertura de información, calidad de fuentes y disponibilidad de contacto. Encontrar un email no aumenta el encaje comercial.

Primera rúbrica, pendiente de calibración con Veryfi:

| Criterio | Peso | 1: señal fuerte | 0,5: señal parcial |
|---|---:|---|---|
| Necesidad documental/validación | 35 | Producto o programa explícitamente recibe/procesa comprobantes relevantes | Flujo documental compatible, sin detalle completo |
| Correspondencia con una oferta | 25 | Relación concreta entre problema y capacidad validada de Veryfi | Relación plausible con una capacidad, requiere confirmación |
| Escala/potencial | 20 | Operación amplia o volumen relevante documentado | Empresa mediana o despliegue limitado con evidencia |
| Capacidad de adoptar la solución | 10 | Producto digital, integración o canal apropiado comprobado | Infraestructura parcial compatible |
| Momento de oportunidad | 10 | Lanzamiento, expansión o campaña vigente relevante | Iniciativa reciente, sin calendario claro |

Valor `0`: evidencia explícita incompatible con ese criterio. Valor `null`: no se pudo determinar. Ausencia de noticias, de ingresos públicos o de emails no se convierte en cero. Guardar la evidencia y la justificación del nivel asignado.

El significado de los criterios depende del segmento: en FinTech se observa el producto y su procesamiento documental; en CPG, la mecánica de campañas y validación. No exigir equipo de desarrollo propio a una marca que podría usar una solución de campaña gestionada.

Para ordenar tamaño, usar inicialmente rangos de empleados como aproximación operativa: menos de 50, 50–249 y 250 o más. No son definiciones legales de empresa pequeña/mediana/grande. Conservar cifras, rangos y fuentes originales. No inventar empleados, ingresos, ACV o volumen para completar la rúbrica.

### Cálculo y clasificación

Con pesos que suman 100 y valores conocidos entre 0 y 1:

```text
known_weight = suma de pesos de criterios cuyo valor no es null
coverage = known_weight / 100
fit_score = 100 * suma(peso * valor conocido) / known_weight
si known_weight == 0: fit_score = null; coverage = 0
```

Reglas, en este orden:

1. Exclusión confirmada: `excluded` y motivo, sin búsqueda de personas.
2. Identidad o criterios de necesidad/correspondencia desconocidos, o contradicción material: `insufficient_evidence`.
3. `fit_score >= 75`, `coverage >= 0.75`, necesidad igual a 1, correspondencia al menos 0,5 y una fuente primaria que respalde el caso de uso: `high`.
4. `fit_score >= 50`, `coverage >= 0.60`, necesidad y correspondencia al menos 0,5: `medium`.
5. Evidencia suficiente (`coverage >= 0.60`) y fallo de los umbrales de encaje anteriores: `low`.
6. En cualquier otro caso: `insufficient_evidence`.

Ejemplo: valores 1, 1, 0,5, 1 y null producen 80 puntos ponderados sobre 90 conocidos: encaje 88,9 y cobertura 90 %. Si cumple las condiciones de evidencia, prioridad alta. Una empresa de la que solo conocemos la escala tendría puntuación 100, pero cobertura 20 % y quedaría con evidencia insuficiente.

Los umbrales son la versión `rubric_v1`. No cambiarlos silenciosamente entre ejecuciones. Guardar versión, entradas y resultado; los ajustes humanos generan una nueva evaluación o una revisión registrada.

### Candidata enterprise `rubric_v2`

La hipótesis aprobada para evaluación académica conserva la fórmula, los umbrales y el significado de necesidad, correspondencia con la oferta, adopción y oportunidad de `rubric_v1`. Sus pesos son necesidad **30**, oferta **20**, escala **35**, adopción **10** y oportunidad **5**. No equivale a una validación comercial de Veryfi. La puntuación sigue midiendo encaje observable; `null` no es cero y el tamaño por sí solo no permite prioridad alta.

Solo cambia la interpretación de escala, siempre con fuente, fecha y ámbito aplicable a la cuenta:

- `1`: al menos 250 empleados, ingresos explícitos de al menos USD 100 millones o una operación enterprise B2B2B, agencia multimarca enterprise o distribución CPG nacional/multinacional sustentada. Una señal fuerte válida prevalece sobre una parcial.
- `0,5`: 50–249 empleados o alcance regional documentado, sin una señal fuerte válida.
- `0`: menos de 50 empleados y evidencia explícita de una operación micro/local sin modelo multiplicador. Pocos empleados por sí solos no bastan.
- `null`: faltan señales o ámbito aplicable, hay una contradicción sin resolver sobre el mismo hecho y ámbito, o el intervalo de empleados cruza niveles sin otra señal suficiente.

Los datos de una matriz no se atribuyen a su filial o marca; los datos de grupo solo puntúan si la cuenta es el propio grupo y su identidad está confirmada. No se deduce esa relación por falta de una matriz registrada. La financiación es contexto y no puntúa. Dentro de cada prioridad de v2, la necesidad documental `1` precede al score descendente en la cola, la tabla y el informe; v1 conserva su comportamiento.

La activación en campañas nuevas requiere una comparación offline sobre 12 casos de desarrollo y 20 independientes, revisados a ciegas y atribuidos académicamente. Se requieren tres casos de desarrollo y cinco de evaluación por combinación de país/segmento, país y segmento respaldados para cada cuenta, independencia verificada y etiquetas completas. En evaluación, v2 debe mejorar la posición media de las aceptadas con escala `1`, sin añadir empresas rechazadas a `high` o `medium` frente a v1 ni perder seleccionadas aceptadas con necesidad `1`. Si falta una condición o esa cohorte, la activación queda pendiente; si la comparación falla, se informa y se requiere una nueva decisión, sin ajuste automático. El [protocolo](t10-evaluation.md) explica el procedimiento y sus límites: no valida respuestas de Haiku ni criterios comerciales de Veryfi.

## Esfuerzo de búsqueda y parada

La prioridad decide cuánto investigar, no autoriza gasto ilimitado. Todos los números siguientes son topes iniciales por empresa y deben poder reducirse desde configuración.

| Etapa/nivel | Búsqueda web | Extracción de páginas | Personas/enriquecimiento | Tope de tiempo activo |
|---|---:|---:|---|---:|
| Análisis inicial | Hasta 2 consultas | Hasta 3 páginas | Sin enriquecimiento | 90 s |
| Evidencia insuficiente | 1 consulta adicional | Hasta 2 páginas adicionales | Ninguno hasta recalificar | 45 s adicionales |
| Prioridad media | Hasta 2 consultas adicionales | Hasta 2 páginas adicionales | 1 persona; hasta 1 enriquecimiento por proveedor habilitado | 90 s adicionales |
| Prioridad alta | Hasta 4 consultas adicionales | Hasta 4 páginas adicionales | Hasta 3 personas; hasta 3 enriquecimientos por proveedor habilitado | 180 s adicionales |
| Prioridad baja/excluida | Ninguna adicional | Ninguna adicional | Ninguno | Detener |

En campañas con `role_taxonomy_v1`, buscar personas por los casos de uso respaldados en la evaluación y por el dominio confirmado. Sin un caso de uso respaldado, la búsqueda queda pendiente. Permitir como máximo dos consultas al proveedor especializado para prioridad media y alta, ambas con cargos específicos: agrupar los que tienen seniority inequívoco y los especialistas o cargos de jerarquía ambigua sin exigir ese filtro. Cada consulta trae hasta 10 candidatos de la primera página. Los límites de personas y enriquecimientos permanecen vigentes. No ampliar la búsqueda silenciosamente ni repetir búsquedas agotadas. Las campañas históricas sin taxonomía conservan sus reglas anteriores.

Secuencia de menor a mayor esfuerzo:

1. Revisar evidencia ya obtenida, páginas corporativas y canales laborales publicados.
2. Consultar Apollo People API Search sobre el dominio confirmado, con cargos de los casos de uso respaldados, si la cuenta tiene acceso y cupo; complementar candidatos con búsqueda web pública mediante Tavily cuando haga falta.
3. Conservar la identidad parcial como pendiente y seleccionar candidatos con función pertinente encontrados por el dominio. Enriquecerlos solo con autorización y dentro de los límites; no solicitar correos personales ni inventar apellidos.
4. Con Apollo People Enrichment, obtener los datos profesionales disponibles y contrastar independientemente nombre completo, entidad, cargo, vigencia y canal. Una respuesta de Search por sí sola no hace contactable al candidato; no fabricar direcciones.
5. Usar teléfono directo/extensión o WhatsApp profesional publicado cuando haya asociación explícita a la persona.
6. Mantener LinkedIn como alternativa; si es el único canal, pedir confirmación humana de que ventas puede usar mensajería.

Detener la empresa cuando se consiga un contacto pertinente con correo/teléfono utilizable. Si solo hay LinkedIn, agotar únicamente el cupo restante de ese nivel para intentar un canal preferido. Hasta tres personas es un máximo, no una obligación de consumir más después de encontrar un resultado útil.

También detener por tiempo, presupuesto, cuota, falta de nuevas fuentes, proveedor no disponible o límite de intentos. Guardar `stop_reason`. Una búsqueda «exhaustiva» significa agotar ese plan acotado, no explorar toda la web.

Tope inicial global de ejecución: 45 minutos, además de los límites de llamadas y dinero. Los tiempos son objetivos de operación; medirlos en pruebas y conservar resultados parciales al alcanzarlos.

## Persona y canal útiles

### Requisitos de la persona

Nombre completo identificado, empresa/entidad correcta, cargo respaldado, función relevante y evidencia de relación vigente sin contradicciones pendientes. Guardar función en la compra como `business_champion`, `technical_champion`, `economic_buyer` o `unknown`; un título por sí solo no confirma autoridad de compra.

La taxonomía versionada distingue familias, equivalencias de cargos y funciones, pero sus categorías de compra son objetivos de búsqueda, no una atribución individual. Priorizar promotores de negocio, técnicos y posibles compradores económicos, en ese orden; entre candidatos de calidad comparable favorecer familias distintas. Un título inequívocamente ajeno queda fuera; un título ambiguo permanece pendiente salvo que responsabilidades nominales citadas de una fuente corporativa vigente respalden una función del caso de uso. Aceptar un responsable regional que cubra el país de la cuenta aunque resida fuera de Colombia o México, si el alcance está respaldado.

Cuando Apollo o una búsqueda web entreguen identificadores o nombres incompletos, conservarlos como candidatos; no completar apellidos con IA. Resolver identidad con evidencia del proveedor o fuentes públicas antes de marcar listo.

### Reglas por canal

| Canal | Cuándo cuenta como directo utilizable | Qué no basta |
|---|---|---|
| Email laboral | Asociación a la persona y verificación válida vigente del proveedor; o publicación nominal en fuente corporativa actual sin verificación negativa | Patrón inferido, correo de otra persona, dirección genérica, dato inválido |
| Teléfono | Número laboral directo o central con extensión nominal, fuente que vincule a la persona y formato/país comprobados | Central general sin ruta a la persona; número cuyo titular se desconoce |
| WhatsApp | Fuente profesional que lo anuncie como canal de esa persona | Suponer que todo móvil tiene WhatsApp |
| LinkedIn | Identidad/cargo comprobados y vendedor confirma mensajería disponible desde su cuenta | URL aislada, asumir InMail disponible o mandar invitación para probar |
| Otro canal | Vía profesional nominal y acceso directo confirmado manualmente | Formulario genérico de empresa o red social sin mensajería comprobada |

La publicación corporativa de un email prueba que se ofrece como contacto, no garantiza entregabilidad. La validación de formato de un teléfono no prueba que atienda. Mostrar siempre esta diferencia. No enviar mensajes, hacer llamadas ni generar notificaciones para verificar un canal.

Conservar estado original del proveedor y un estado normalizado: `verified`, `published_professional`, `accept_all`, `unknown`, `invalid` o `manual_confirmed`. `accept_all`/`unknown` no son por sí solos verificados. Si además existe publicación nominal corporativa vigente, conservar ambos hechos y la advertencia; una verificación `invalid` bloquea ese canal hasta resolverla.

Frescura propuesta: verificación de email hasta 30 días; evidencia fechada del puesto preferiblemente dentro de 365 días, o directorio corporativo actual consultado. Si la fuente no permite estimar vigencia, marcar incertidumbre y requerir revisión antes de listo. Estos plazos son reglas del prototipo, no garantías del proveedor.

La vigencia inferida que se aplicó a los datos históricos de Hunter se conserva en el [Historial](#historial).

### Estados de negocio

- `ready_preferred`: encaje alto/medio, persona pertinente y correo/teléfono/WhatsApp profesional utilizable.
- `ready_alternative`: mismos requisitos, pero solamente canal alternativo directo confirmado.
- `needs_channel_confirmation`: existe candidato a canal, por ejemplo LinkedIn, pero falta comprobar acceso o asociación.
- `qualified_no_contact`: empresa de encaje alto/medio sin persona/canal utilizable después del cupo.
- `insufficient_evidence`: no se puede decidir con información suficiente.
- `low_fit`: encaje bajo con evidencia suficiente.
- `excluded`: exclusión confirmada.

Las interrupciones técnicas no son estados comerciales: registrar aparte la ejecución y `stop_reason`. Una empresa puede estar calificada y haber quedado sin contacto por falta de cuota.

Porcentaje de match de contactos: Python ordena a todas las personas encontradas de cada empresa con un puntaje de 0 a 100 que suma cargo, canal, identidad y vigencia del empleo, según las reglas de §10.1 y §10.2, sin IA. Los pesos están versionados en `config/contact_match.json`; la propuesta inicial del equipo (`contact_match_v1`) prioriza la pertinencia del cargo. Se calcula al consultar, no altera estos estados ni la condición de listo, y un dato pendiente suma 0 sin contarse como incumplimiento. Una identidad contradicha, un empleo no vigente o un alcance geográfico incompatible llevan a la persona al final.

## Historial

### Vigencia inferida de Hunter

Vigencia inferida histórica de Hunter: sin evidencia fechada del puesto, una persona con identidad, nombre completo y cargo pertinente confirmados también se considera vigente si tiene un correo nominal del dominio confirmado verificado `valid` dentro de los 30 días y Hunter informó una fuente con `still_on_page` y `last_seen_on` dentro del plazo de vigencia del puesto. Un empleo marcado como no vigente, una salida nominal o evidencia contradictoria la anulan. La interfaz y el CSV la muestran como inferida: el buzón y la fuente no prueban el cargo actual, que ventas confirma antes de contactar. Esta regla conserva la lectura histórica y no se aplica a Apollo.
