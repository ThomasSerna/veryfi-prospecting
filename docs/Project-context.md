# Contexto del proyecto

Veryfi Prospecting: descubrimiento y calificación de clientes potenciales. Este archivo explica qué es el producto, a quién va dirigido, qué decisiones se tomaron y cómo se mide su éxito. Forma parte de la documentación de requisitos: ver el [índice](IDEA.md). Ver también [Business-rules.md](Business-rules.md) (reglas de negocio), [Architecture.md](Architecture.md), [Library-docs.md](Library-docs.md), [Budget-policy.md](Budget-policy.md) y [Roadmap.md](Roadmap.md) (backlog).

Las reglas numéricas de calificación, las metas de evaluación y la arquitectura son propuestas iniciales para implementar y validar; no representan criterios comerciales ya certificados por Veryfi.

## A quién va dirigido

- **Usuarios:** el equipo de ventas de Veryfi revisa los resultados y decide, fuera de la aplicación, a quién contactar. La aplicación no envía mensajes (ver «Experiencia de uso»).
- **Clientes objetivo:** empresas de FinTech/software y de CPG/fidelización en Latinoamérica, con Colombia y México como muestra inicial (ver «Clientes objetivo, señales y personas»).
- **Equipo del proyecto:** tres desarrolladores y una integrante encargada de la documentación académica. El Head of LATAM Engineering de Veryfi puede revisar resultados (ver «Decisiones acordadas y valores iniciales»).

## Idea y resultado esperado

Construir una aplicación que descubra empresas potencialmente interesadas en Veryfi, investigue sus necesidades, explique qué producto podría servirles y encuentre personas pertinentes con medios directos de comunicación. El esfuerzo invertido en encontrar contactos dependerá del encaje de cada empresa, de la evidencia disponible y del presupuesto restante.

El resultado es una lista priorizada de prospectos revisables por ventas. Cada ficha debe responder:

1. ¿Qué empresa es, en qué mercado opera y qué hace?
2. ¿Qué necesidad observable podría resolver Veryfi y con qué producto?
3. ¿Por qué merece atención y qué información falta?
4. ¿Quién sería una persona pertinente, qué función cumple y cómo puede contactarla ventas?
5. ¿De dónde salió cada dato, cuándo se consultó y cuánto costó investigarlo?

**La aplicación no envía correos, mensajes, invitaciones ni WhatsApps, no llama, no agenda reuniones y no ejecuta campañas comerciales.** El equipo de ventas decide y realiza cualquier contacto fuera de la aplicación.

Una empresa atractiva sin canal directo queda como **pendiente de contacto**, no como prospecto listo. Encontrar una persona y encontrar cómo comunicarse con ella son resultados diferentes.

## Decisiones acordadas y valores iniciales

| Tema | Decisión |
|---|---|
| Finalidad | Prototipo académico con posibilidad de evolucionar a piloto para Veryfi |
| Segmentos | FinTech/software y CPG/consumo masivo/fidelización, con criterios y cargos diferentes |
| Mercado | Latinoamérica; primeras pruebas en Colombia y México |
| Tamaño | Priorizar medianas y grandes; admitir pequeñas con necesidad clara |
| Autonomía | El usuario configura una búsqueda; el sistema descubre, evalúa y profundiza automáticamente dentro de sus límites |
| Contacto mínimo | Persona pertinente con al menos un medio directo; preferencia por correo o teléfono |
| LinkedIn | Alternativa útil, de menor prioridad; debe existir una posibilidad de mensajería, no solamente una URL |
| Equipo | Tres desarrolladores, principalmente Python, y una integrante encargada de documentación académica |
| Primer sprint/MVP | 16 de octubre de 2026 |
| Entrega final académica | 6 de noviembre de 2026 |
| Presupuesto | Mantener gastos bajos; máximo USD 20 para todo el primer sprint |
| Modelo de IA | Haiku 5.5 para interpretación y clasificación; el equipo declara acceso API |
| Proveedores de datos | Tavily Search/Extract para empresas y evidencia; Apollo como único proveedor especializado de personas y correos, sujeto a acceso y cupo comprobados. X-Ray Search queda como ampliación condicional |
| Validación | El Head of LATAM Engineering puede revisar resultados y ayudar con ejemplos y exclusiones |

Valores de implementación propuestos: hasta 20 empresas analizadas por ejecución, uno a tres contactos por empresa, ejecución a demanda, interfaz y explicaciones en español, lectura de fuentes en español e inglés. Colombia y México son la muestra inicial; no se afirma cobertura validada de toda Latinoamérica. Brasil/portugués requieren una evaluación posterior.

El MVP utilizó Hunter. La T12 sustituye esa ruta por Apollo People API Search y People Enrichment, complementados con fuentes públicas de Tavily y su interpretación con Haiku. El responsable autorizó desarrollar y probar la migración sin red tras registrar la comprobación local de la fase 0; la ejecución real sigue bloqueada hasta comprobar acceso, costo, cuotas y límites de la cuenta y obtener autorización explícita por operación. La presencia de una clave no demuestra acceso ni concede gasto. No hay retorno automático a Hunter.

El presupuesto posterior al 16 de octubre no está definido. No renovar el cupo de USD 20 automáticamente: mientras no haya una nueva decisión, los siguientes sprints deben usar el remanente, créditos gratuitos y pruebas sin consumo.

## Contexto de Veryfi y relación con la entrega académica

La empresa es **Veryfi Inc. (veryfi.com)**, proveedora de captura documental, extracción de datos mediante OCR/API, enriquecimiento, antifraude y soluciones para programas de fidelización. No es una aplicación genérica de cobranza.

La entrega de análisis de negocio identifica el tiempo invertido en investigar cuentas, conectar necesidades con productos e identificar personas correctas. También señala que faltan mediciones claras del proceso actual. La herramienta cubre ese trabajo de investigación previo a la interacción comercial [D1, pp. 21–25].

Los materiales distinguen promotores técnicos, promotores de negocio y decisores económicos. Por eso el sistema no debe buscar siempre directores de ventas/comercial/finanzas: el cargo depende del problema detectado [D2, pp. 7–9; D3, pp. 11–12].

El anexo de la primera entrega menciona una idea anterior de prospección LATAM para CPG que incluía agendar llamadas. Ese texto es un antecedente documental. La solicitud actual amplía a ambos segmentos y excluye contactar o agendar [D1, p. 30].

Las diapositivas mezclan períodos históricos, productos experimentales y ejemplos posteriores. Sus precios, umbrales de clientes y estados de desarrollo no se convierten automáticamente en reglas actuales. El Head of LATAM Engineering deberá validar el catálogo comercial usado por el prototipo.

La tecnología de Veryfi es lo que se busca vender. Esta aplicación no necesita integrar su API OCR para hacer prospección. Tampoco necesita reproducir su infraestructura AWS/GPU ni sus herramientas internas.

## Clientes objetivo, señales y personas

| Perfil | Señales públicas de encaje | Solución candidata | Personas a investigar |
|---|---|---|---|
| FinTech de gastos/reembolsos | Usuarios suben recibos; gestión de gastos; conciliación con tarjetas | OCR de recibos/facturas, Lens, antifraude | Product Manager, Head/VP of Product, Engineering Manager/Director, CTO |
| Software de pagos/AP/ERP | Recepción de facturas, captura de documentos, conciliación y cuentas por pagar | API documental, captura, validación y enriquecimiento | Producto, Ingeniería, responsable de AP/operaciones financieras según producto |
| CPG y marcas | Promociones que piden tickets, códigos o comprobantes; recompensas por compra | Validación de compras, antifraude, Lens, WhatsApp y datos de productos | Marketing Director, Brand Manager, Loyalty/CRM Manager, Trade Marketing, Consumer Insights |
| Plataformas/agencias de fidelización | Implementan campañas o programas para marcas; necesitan validar compras | Integración de APIs o soluciones de campañas | Producto/Tecnología, responsable de fidelización, director de cuentas pertinente |

El último perfil es un subperfil candidato del segmento de fidelización, pendiente de validación comercial. No ampliar a todos los tipos de agencias.

Reglas de interpretación:

- Una campaña concreta que solicita recibos es evidencia más fuerte que la frase genérica «empresa innovadora».
- Un producto con captura de comprobantes demuestra un caso de uso, no que su proveedor actual falle o que desee cambiarlo.
- Tamaño, financiación y expansión son aproximaciones al potencial; no demuestran presupuesto disponible ni volumen documental.
- No atribuir necesidades solamente por pertenecer a una industria.
- Buscar cargos en español e inglés y verificar función, no solo palabras del título.
- Priorizar quien gestiona el proceso o producto. Compras puede intervenir después; un cargo alto no demuestra autoridad para esta compra.
- Identificar país y alcance del puesto. Un responsable regional puede servir para Colombia y México aunque resida en otro país.
- Separar marca, filial, agencia y matriz. Compartir dominio no autoriza fusionarlas ni asumir que compran juntas.
- Los casos de éxito de Veryfi sirven para aprender patrones y proponer exclusiones. Los retailers mencionados en una promoción no son automáticamente clientes de Veryfi [D4].

## Experiencia de uso

1. **Configurar.** Seleccionar Colombia/México, uno o ambos segmentos y hasta 20 empresas. Ver límites, proveedores disponibles y presupuesto restante antes de ejecutar.
2. **Investigar.** Mostrar etapa, empresas procesadas, consumo y resultados parciales. No pedir aprobación entre empresas.
3. **Revisar.** Tabla filtrable por país, segmento, prioridad y disponibilidad de canal. Al abrir una ficha, mostrar caso de uso, puntuación desglosada, evidencia y contactos. La ficha lista a todas las personas encontradas, ordenadas por un porcentaje de match determinístico con su desglose (§10.3), para que ventas elija a quién contactar.
4. **Corregir.** Marcar aceptado, rechazado o pendiente con motivo. Confirmar manualmente mensajería en LinkedIn cuando sea el único canal. No enviar nada para comprobarlo.
5. **Exportar.** Exportación principal de prospectos listos, y otra opción explícita para todos los resultados con su estado.

La pantalla debe distinguir «listo según reglas» de «aceptado por Veryfi». La revisión humana es posterior al flujo automático; no hace falta revisar cada empresa antes de investigar.

Para exportación: una fila por persona, repetir los datos de la empresa y conservar identificadores. Las empresas sin personas solo aparecerán en la exportación de todos los resultados, con campos vacíos y su motivo. El CSV incluirá enlace/fuente, fechas, estado del canal, puntuación, porcentaje de match de cada persona, revisión y advertencias relevantes. Proteger las celdas de texto contra fórmulas de hoja de cálculo.

## Fuera del alcance de esta entrega

Envío comercial, campañas, CRM completo, integraciones de escritura con CRM, entrenamiento de modelos propios, predicción estadística de compra, scraping automatizado de LinkedIn, agentes que operen cuentas personales, seguimiento continuo programado, infraestructura distribuida y plataforma multiusuario de producción.

La carga de una lista de empresas para investigación puede añadirse después si aporta valor; no sustituye el descubrimiento solicitado. Un portal público o piloto remoto necesita una decisión de despliegue y acceso separada.

## Criterios de éxito

El éxito se mide con las métricas de la revisión comercial y se declara cumplido con los criterios de terminación de cada entrega. Las métricas del flujo enterprise (T21) y el estado actual del backlog están en [Roadmap.md](Roadmap.md).

### Revisión comercial

Pedir al representante una pequeña muestra de cuentas que interesan y no interesan, exclusiones conocidas y criterios de producto/cargo. Su revisión puede requerir apoyo de ventas; no asumir que todo criterio comercial está definido por el título de su cargo.

Para la primera ejecución, intentar hasta 20 empresas repartidas por país/segmento. Ajustar la rúbrica con una parte y reservar empresas diferentes para evaluación. En la entrega final buscar una muestra nueva de 20 empresas si el acceso/cupo lo permite; si no, informar tamaño real y no generalizar cobertura LATAM.

Medir con numerador/denominador y por segmento/país:

- **Precisión de empresas seleccionadas:** cuentas aceptadas por el revisor / cuentas calificadas revisadas.
- **Pertinencia de personas:** personas con empresa, cargo y función correctos / personas revisadas.
- **Cobertura de contacto:** empresas calificadas con al menos un canal útil / empresas calificadas investigadas.
- **Canal preferido:** empresas listas con correo/teléfono/WhatsApp laboral / empresas listas. Separar alternativas.
- **Trazabilidad:** afirmaciones clave realmente respaldadas / afirmaciones clave auditadas. No basta contar URLs.
- **Costo por prospecto aceptado:** costo atribuible del flujo / prospectos aceptados; si no hay aceptados, informar «no calculable», no cero.
- **Tiempo:** duración automática y minutos de revisión por empresa; comparar con investigación manual de muestra equivalente.
- **Fallos y sesgos de cobertura:** empresas sin resultados, canales no encontrados, datos antiguos, cuotas y diferencias de país/segmento.

No medir tasa de respuesta, reuniones ni conversión mediante mensajes: contactar está fuera del alcance. No prometer ahorro de tiempo sin línea base ni interpretar cobertura como recall de todas las empresas del mercado.

Objetivos orientativos para discutir con Veryfi, no resultados prometidos: al menos 80 % de aceptación de empresas calificadas, 90 % de pertinencia de personas revisadas y 100 % de afirmaciones obligatorias con procedencia. Reportar conteos e incertidumbre de muestra. La cobertura de canales se mide primero; no inventar una meta que el acceso gratuito quizá no soporte.

### Criterios de terminación

#### MVP del 16 de octubre

- Una ejecución parte de criterios y descubre empresas reales de los perfiles seleccionados.
- El flujo produce evidencia, score/desglose, asignación de esfuerzo y búsqueda de personas/canales mediante la ruta inicial Tavily + Hunter, cuando el acceso haya sido comprobado; no depende de Apollo ni X-Ray Search.
- Se demuestra al menos un prospecto real completo; se muestran honestamente pendientes y fallos. Si no se obtiene ninguno, la parte de contactabilidad sigue sin validar.
- No aparece como listo ningún registro que incumpla la regla de canal directo.
- UI, revisión y exportación funcionan; no dependen de contactar a nadie.
- Pruebas críticas de score, presupuesto, identidad/canal y recuperación pasan.
- Gasto agregado conciliado no supera USD 20; cuota y margen están visibles.
- Se documentan proveedores accesibles, limitaciones y siguiente mejora prioritaria.

#### Entrega del 6 de noviembre

Además del MVP: revisión documentada con Veryfi, métricas por país/segmento, rúbrica versionada, calificación con Haiku evaluada en un conjunto separado de calibración, manejo de errores probado, instrucciones de ejecución y datos de demostración seguros. El informe distingue resultados medidos, estimaciones y trabajo posterior.

Pasar a piloto requiere, como mínimo, datos suficientes para que ventas lo considere útil, presupuesto operativo, usuarios y responsable de datos definidos y un entorno de acceso apropiado. La entrega académica no se presenta como sistema productivo ya validado.
