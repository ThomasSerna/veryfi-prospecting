# Veryfi Prospecting: descubrimiento y calificación de clientes potenciales

Versión 2.0 — 1 de noviembre de 2026. Fechas en America/Bogota. Reestructuración en archivos temáticos; las decisiones y los valores de la versión 1.6 no cambian.

Documento de producto, plan de implementación y guía para agentes de código del proyecto de Sistemas de Información para Veryfi. Recoge las decisiones tomadas con el equipo. Las reglas numéricas de calificación, las metas de evaluación y la arquitectura son propuestas iniciales para implementar y validar; no representan criterios comerciales ya certificados por Veryfi.

Este archivo es el índice de la documentación de requisitos: indica qué hay en cada archivo y dónde está hoy cada sección de la versión 1.6.

## La idea en pocas líneas

Aplicación local que descubre empresas de Latinoamérica potencialmente interesadas en Veryfi, las califica con evidencia y propone personas pertinentes con un canal directo. Ventas revisa y contacta fuera de la aplicación: la aplicación no envía mensajes. Una empresa atractiva sin canal directo queda pendiente de contacto, no como prospecto listo. El detalle está en [Project-context.md](Project-context.md).

## Dónde está cada cosa

| Archivo | Para qué sirve |
|---|---|
| [Project-context.md](Project-context.md) | Qué es el producto, a quién va dirigido, decisiones acordadas, alcance excluido y criterios de éxito |
| [Business-rules.md](Business-rules.md) | Reglas de descubrimiento, identidad, evidencia, calificación, esfuerzo de búsqueda, personas y canales |
| [Architecture.md](Architecture.md) | Pila tecnológica, límites del sistema, estructura de carpetas, flujo de datos y esquema SQLite |
| [Library-docs.md](Library-docs.md) | Cómo se usan Tavily, Apollo, Claude Haiku y las librerías del proyecto |
| [Budget-policy.md](Budget-policy.md) | Topes de gasto, reservas y conciliación |
| [Testing.md](Testing.md) | Pruebas mínimas por riesgo |
| [Roadmap.md](Roadmap.md) | Copia y guía del backlog de GitHub: estado, siguiente tarea y dependencias |

Guías técnicas, que describen el código: [persistence.md](persistence.md), [budget-providers.md](budget-providers.md), [discovery.md](discovery.md), [qualification.md](qualification.md), [contacts.md](contacts.md), [campaign.md](campaign.md) y [ui.md](ui.md). Registros e informes: [provider-check.md](provider-check.md), [evaluation.md](evaluation.md), [t10-evaluation.md](t10-evaluation.md) y [delivery.md](delivery.md). También: [README.md](../README.md), [AGENTS.md](../AGENTS.md), [PRODUCT.md](../PRODUCT.md) y [DESIGN.md](../DESIGN.md).

## Convenciones

- Los números `§N` de la versión 1.6 son identificadores estables: el código, las pruebas, la configuración y las guías los citan. El mapa siguiente indica dónde está hoy cada sección.
- Las decisiones, los valores y la arquitectura de los archivos de requisitos son propuestas; cambiarlos exige justificación y aprobación (ver [AGENTS.md](../AGENTS.md)). El backlog vigente está en los [issues de GitHub](https://github.com/ThomasSerna/veryfi-prospecting/issues) y su copia en [Roadmap.md](Roadmap.md).
- Pendiente de documentar: las citas [D1] a [D4] de las secciones 3 y 5 no tienen definición en las fuentes originales, que solo definen W1 a W8. Se conservan tal cual.

## Mapa de secciones

Cada fila indica dónde está hoy una sección de la versión 1.6. Los ítems `§14.1` a `§14.7` son los de la lista numerada «Implementación del control».

| Sección | Título original | Dónde está hoy |
|---|---|---|
| §1 | Idea y resultado esperado | [Project-context.md: Idea y resultado esperado](Project-context.md#idea-y-resultado-esperado) |
| §2 | Decisiones acordadas y valores iniciales | [Project-context.md: Decisiones acordadas y valores iniciales](Project-context.md#decisiones-acordadas-y-valores-iniciales) |
| §3 | Contexto de Veryfi y relación con la entrega académica | [Project-context.md: Contexto de Veryfi y relación con la entrega académica](Project-context.md#contexto-de-veryfi-y-relación-con-la-entrega-académica) |
| §4 | Alcance funcional | [Roadmap.md: Alcance por fases](Roadmap.md#alcance-por-fases); [Project-context.md: Fuera del alcance de esta entrega](Project-context.md#fuera-del-alcance-de-esta-entrega) |
| §4.1 | Primer sprint (alcance original) | [Roadmap.md: Primer sprint (alcance original)](Roadmap.md#primer-sprint-alcance-original) |
| §4.2 | Hasta la entrega final | [Roadmap.md: Hasta la entrega final](Roadmap.md#hasta-la-entrega-final) |
| §4.3 | Fuera del alcance de esta entrega | [Project-context.md: Fuera del alcance de esta entrega](Project-context.md#fuera-del-alcance-de-esta-entrega) |
| §5 | Clientes objetivo, señales y personas | [Project-context.md: Clientes objetivo, señales y personas](Project-context.md#clientes-objetivo-señales-y-personas) |
| §6 | Experiencia de uso | [Project-context.md: Experiencia de uso](Project-context.md#experiencia-de-uso) |
| §7 | Flujo de investigación | [Architecture.md: Flujo de investigación](Architecture.md#flujo-de-investigación); [Business-rules.md: Descubrimiento](Business-rules.md#descubrimiento) |
| §7.1 | Descubrimiento | [Business-rules.md: Descubrimiento](Business-rules.md#descubrimiento) |
| §7.2 | Identidad y exclusiones | [Business-rules.md: Identidad y exclusiones](Business-rules.md#identidad-y-exclusiones) |
| §7.3 | Evidencia | [Business-rules.md: Evidencia](Business-rules.md#evidencia) |
| §8 | Calificación explicable | [Business-rules.md: Calificación explicable](Business-rules.md#calificación-explicable) |
| §8.1 | Qué significa la puntuación | [Business-rules.md: Qué significa la puntuación](Business-rules.md#qué-significa-la-puntuación) |
| §8.2 | Cálculo y clasificación | [Business-rules.md: Cálculo y clasificación](Business-rules.md#cálculo-y-clasificación) |
| §9 | Esfuerzo de búsqueda y parada | [Business-rules.md: Esfuerzo de búsqueda y parada](Business-rules.md#esfuerzo-de-búsqueda-y-parada) |
| §10 | Persona y canal útiles | [Business-rules.md: Persona y canal útiles](Business-rules.md#persona-y-canal-útiles) |
| §10.1 | Requisitos de la persona | [Business-rules.md: Requisitos de la persona](Business-rules.md#requisitos-de-la-persona) |
| §10.2 | Reglas por canal | [Business-rules.md: Reglas por canal](Business-rules.md#reglas-por-canal); [Business-rules.md: Historial](Business-rules.md#historial) |
| §10.3 | Estados de negocio | [Business-rules.md: Estados de negocio](Business-rules.md#estados-de-negocio) |
| §11 | Proveedores y estrategia de integración | [Library-docs.md: Proveedores y estrategia de integración](Library-docs.md#proveedores-y-estrategia-de-integración) |
| §11.1 | Comprobación de acceso del primer día | [Library-docs.md: Comprobación de acceso del primer día](Library-docs.md#comprobación-de-acceso-del-primer-día) |
| §11.2 | Extensión futura: X-Ray Search para descubrimiento de contactos | [Roadmap.md: Propuestas fuera del backlog](Roadmap.md#propuestas-fuera-del-backlog) |
| §11.3 | Evolución de la búsqueda de contactos | [Library-docs.md: Evolución de la búsqueda de contactos](Library-docs.md#evolución-de-la-búsqueda-de-contactos) |
| §12 | Uso de IA y protección de decisiones | [Library-docs.md: Uso de IA y protección de decisiones](Library-docs.md#uso-de-ia-y-protección-de-decisiones) |
| §12.1 | Haiku | [Library-docs.md: Haiku](Library-docs.md#haiku) |
| §12.2 | Evaluación y decisiones en Python | [Library-docs.md: Evaluación y decisiones en Python](Library-docs.md#evaluación-y-decisiones-en-python) |
| §12.3 | Agentes y código normal | [Architecture.md: Agentes y código normal](Architecture.md#agentes-y-código-normal) |
| §13 | Arquitectura mínima | [Architecture.md: Pila tecnológica](Architecture.md#pila-tecnológica); [Architecture.md: Dirección de las dependencias](Architecture.md#dirección-de-las-dependencias) |
| §13.1 | Estructura orientativa | [Architecture.md: Estructura de carpetas](Architecture.md#estructura-de-carpetas) |
| §13.2 | Contratos compartidos | [Architecture.md: Contratos compartidos](Architecture.md#contratos-compartidos); [Architecture.md: Contrato funcional](Architecture.md#contrato-funcional) |
| §13.3 | Ejecución y recuperación | [Architecture.md: Ejecución y recuperación](Architecture.md#ejecución-y-recuperación) |
| §14 | Presupuesto y control de gasto | [Budget-policy.md](Budget-policy.md) |
| §14.1–§14.7 | Implementación del control (ítems 1 a 7 de la lista numerada) | [Budget-policy.md](Budget-policy.md) |
| §15 | Seguridad y tratamiento de datos | [Architecture.md: Seguridad y tratamiento de datos](Architecture.md#seguridad-y-tratamiento-de-datos) |
| §16 | Plan de implementación y responsables | [Roadmap.md: Plan de implementación y responsables](Roadmap.md#plan-de-implementación-y-responsables) |
| §16.1 | Primer sprint: 10–16 de octubre | [Roadmap.md: Responsables por módulo](Roadmap.md#responsables-por-módulo); [Roadmap.md: Primer sprint: 10–16 de octubre](Roadmap.md#primer-sprint-1016-de-octubre) |
| §16.2 | Hitos propuestos originalmente | [Roadmap.md: Hitos propuestos originalmente](Roadmap.md#hitos-propuestos-originalmente) |
| §17 | Guía de trabajo para agentes de código | [Roadmap.md: Cómo trabajar una tarea](Roadmap.md#cómo-trabajar-una-tarea) |
| §17.1 | Instrucciones comunes | [Roadmap.md: Instrucciones comunes](Roadmap.md#instrucciones-comunes) |
| §17.2 | Backlog ejecutable | [Roadmap.md: Estado de un vistazo](Roadmap.md#estado-de-un-vistazo); [Roadmap.md: Refactorización modular (sin issues)](Roadmap.md#refactorización-modular-sin-issues); [Roadmap.md: Backlog ejecutable](Roadmap.md#backlog-ejecutable) |
| §17.3 | Plantilla para asignar una tarea | [Roadmap.md: Plantilla para asignar una tarea](Roadmap.md#plantilla-para-asignar-una-tarea) |
| §18 | Pruebas y evaluación | [Testing.md](Testing.md); [Project-context.md: Revisión comercial](Project-context.md#revisión-comercial) |
| §18.1 | Pruebas de software mínimas | [Testing.md](Testing.md) |
| §18.2 | Revisión comercial | [Project-context.md: Revisión comercial](Project-context.md#revisión-comercial) |
| §19 | Criterios de terminación | [Project-context.md: Criterios de terminación](Project-context.md#criterios-de-terminación) |
| §20 | Riesgos y decisiones que pueden cambiar | [Roadmap.md: Riesgos y decisiones que pueden cambiar](Roadmap.md#riesgos-y-decisiones-que-pueden-cambiar) |
| §21 | Fuentes y estado de verificación | [Library-docs.md: Fuentes y estado de verificación](Library-docs.md#fuentes-y-estado-de-verificación) |

## Historial de versiones

- Versión 2.0 — 1 de noviembre de 2026. Reestructuración en archivos temáticos; las decisiones y los valores no cambian.
- Versión 1.6 — 1 de noviembre de 2026. Fechas en America/Bogota.
