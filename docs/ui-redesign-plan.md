# Plan propuesto de rediseño de la interfaz

Estado: **implementación en curso**. Este documento conserva la propuesta que
guio el rediseño; [DESIGN.md](../DESIGN.md) describe el sistema visual actual y
[la guía de interfaz](ui.md) documenta su uso y verificaciones. El plan no
sustituye los requisitos de producto ni las reglas de negocio.

El 7 de noviembre de 2026 se revisaron en navegador la referencia y las cuatro
pantallas anteriores mediante la demo exclusivamente sintética. Durante la
implementación se generaron referencias visuales sintéticas para inicio, campaña
y ficha; son apoyo de diseño, no validación con usuarios.

La regla existente de bloqueo se aplica a campañas en estado `running` o
`paused_budget`, incluso si el hilo está detenido. La frase «campaña sin terminar»
de la propuesta debe leerse con ese alcance: este rediseño no amplía los estados
que impiden preparar otra campaña.

Las secciones siguientes conservan la propuesta original y sus criterios de
aceptación, no afirman por sí mismas que estos se hayan verificado.

## Objetivo y decisiones confirmadas

El equipo de ventas necesita preparar una búsqueda, seguir su investigación y
revisar empresas y personas con rapidez. La primera pantalla debe ofrecer un
panorama de campañas y facilitar la continuación de una investigación. Una misma
persona prepara la búsqueda y revisa los resultados. El diseño se prioriza para
portátiles de 1366–1440 px y también debe funcionar en pantallas pequeñas.

El usuario confirmó un único tema **oscuro**, inspirado en AdminCN. En la
jerarquía de información van primero el avance y los pendientes, después la
calidad de los prospectos; el consumo ocupa un lugar secundario siempre visible.
El diseño detallado y los componentes concretos de cada vista siguen sujetos a
revisión. Veryfi puede aparecer mediante su nombre, logotipo y acentos de marca
cuando armonicen con la referencia, respetando la integridad del logotipo.

La interfaz se concibe como una herramienta de trabajo, no como un CRM: no se
añaden usuarios, inicio de sesión, pagos, calendario, mensajería, oportunidades,
ingresos ni otras funciones ausentes de la aplicación. Ventas contacta fuera de
ella.

## Dirección visual y referencias

La referencia principal es [AdminCN en 21st.dev](https://21st.dev/@clevision/templates/admincn-shadcn-admin-dashboard-template)
y su [dashboard de ventas](https://shadcn-nextjs-admincn-admin-template.vercel.app/dashboard/sales).
En la vista observada predominan fondo casi negro, paneles grafito con bordes
sutiles y radios moderados, barra superior ligera, tipografía sans legible y
gráficos compactos con acentos de color. El menú lateral se abre sobre la página
desenfocada; sus propios textos permanecen nítidos. Estos rasgos son la guía para
composición, densidad, controles y estados de **toda** la aplicación.
La paleta candidata combina negro y grafito con texto claro, verde suave y un
acento puntual de Veryfi; azul o violeta pueden aparecer en gráficos y estados
cuando ayuden a distinguirlos. Los colores definitivos se resolverán en el
prototipo y deben mantener suficiente contraste.

La inspección de la demo exclusivamente sintética, el 7 de noviembre de 2026,
mostró que el inicio presenta el historial sin destacar la campaña activa y que
en otras vistas los encabezados y avisos pueden desplazar los resultados bajo el
primer pantallazo. El nuevo orden debe recuperar espacio para el trabajo sin
esconder advertencias ni acciones necesarias.

Componentes candidatos de la [comunidad de 21st.dev](https://21st.dev/community/components):

| Referencia | Uso propuesto |
|---|---|
| [Sidebar](https://21st.dev/@manuarora700/components/sidebar) | Navegación compacta y expansión con control explícito; el hover puede complementar, pero no ser la única forma de usarla. |
| [Progressive Blur](https://21st.dev/@ibelick/components/progressive-blur) | Inspiración para el desenfoque de la página detrás del menú y transiciones de capas, sin difuminar información que se esté leyendo. |
| [Stepper](https://21st.dev/@originui/components/stepper) | Mostrar etapas conocidas de preparación o investigación, con estado y texto comprensibles. |
| [Tabs](https://21st.dev/@originui/components/tabs) | Organizar resumen, contactos y evidencia conservando la navegación de la ficha. |
| [Stats cards with links](https://21st.dev/@ephraimduncan/components/stats-cards-with-links) | Indicadores enlazados a filtros reales de la campaña seleccionada. |

La selección definitiva se hará por utilidad y coherencia visual durante el
prototipo. AdminCN se ofrece en un plan de pago; se toma como referencia visual,
sin asumir acceso a su código. Los componentes encontrados están orientados a
React/Tailwind: se adaptarán sus patrones a las plantillas de Django, CSS y
JavaScript locales. Antes de incorporar código de terceros se comprobarán su
licencia, atribución y compatibilidad; no se presupone una integración nativa ni
se añade React, Next.js o un runtime de Tailwind o Motion.

## Estructura y recorrido propuestos

La navegación debe responder a tres preguntas: qué campaña continuar, qué falta
para avanzar y qué empresa conviene revisar. Los nombres y acciones se ajustarán
al comportamiento real de cada estado.

| Superficie | Composición y tarea principal |
|---|---|
| **Inicio e historial** | Barra lateral compacta y retraíble con acceso a Resumen e Historial como anclas de la misma vista, campañas recientes y acción de nueva campaña. Destacar la campaña activa, su etapa y pendientes accionables; debajo, indicadores breves e historial compacto. Sin campaña activa, identificar la última como tal o mostrar un estado vacío. |
| **Preparar campaña** | Agrupar la configuración en Mercado → Alcance → Resumen: países y segmentos; palabras clave y máximo de empresas; criterios, límites y acceso al presupuesto. Explicar que preparar guarda criterios sin iniciar llamadas. Un asistente por pasos solo se adoptará si mejora el recorrido validado, sin autoguardado nuevo. |
| **Campaña** | Encabezado breve, avance real por etapas y pendientes accionables, seguidos por la tabla filtrable. Diferenciar prioridad, encaje y cobertura, disponibilidad y revisión. Destacar la autorización cuando se necesite; conservar presupuesto exacto, cierre y las dos exportaciones según el estado. |
| **Ficha de empresa** | Presentar identidad, caso de uso, señales, encaje y cobertura con referencias a sus fuentes; destacar el contacto pertinente y su disponibilidad real cuando existan. Conservar las pestañas Resumen, Contactos y Evidencia, el panel de decisión y el recorrido anterior/siguiente con filtros. |
| **Estados compartidos** | Rediseñar pantallas vacías, carga, ejecución, errores, permisos ausentes, bloqueos y confirmaciones con el mismo sistema visual. El modo de demostración conserva su aviso explícito en todas las páginas. |

El presupuesto visible debe indicar a qué campaña o cuenta corresponde y
ofrecer el detalle pertinente. Si no hay contexto o un importe se desconoce,
debe decirlo; no mostrar un total global inventado. El espacio para consumo no
debe desplazar el progreso ni ocultar reservas inciertas. El resumen compacto
permanece visible en todas las vistas y da acceso al detalle contable exacto.

Si una campaña activa impide preparar otra, «Nueva campaña» debe explicar el
bloqueo y ofrecer acceso a la campaña existente para retomarla o, cuando esté
permitido, cerrarla conservando sus resultados. Esto también aplica cuando la
investigación no está ejecutándose en ese momento.

### Paneles y gráficos

Se proponen tarjetas pequeñas para etapa, empresas descubiertas o procesadas,
pendientes de revisión y disponibilidad de contacto, acompañadas por una lista
accionable de la campaña activa o seleccionada. La revisión pendiente se calcula
desde el estado de revisión, no desde `counts.pending`, que responde a otra
categoría. Los indicadores con enlace deben conducir a filtros reales de esa
misma campaña. Las distribuciones de prioridad y disponibilidad pueden mostrarse
como barras o segmentos con cifras y etiquetas; deben seguir siendo legibles sin
color y permitir consultar sus datos. El encaje se presenta junto con la
cobertura y significa ajuste observable a la oferta, no probabilidad de compra.

Los gráficos solo se construirán con datos existentes y denominadores definidos.
Descubrimiento tiene avance indeterminado: el máximo configurado no garantiza
que se encuentren o procesen tantas empresas. No se añadirán tendencias,
porcentajes históricos, estimaciones de tiempo ni comparaciones de períodos sin
datos adecuados. Desconocido se muestra como pendiente o no disponible, no como
cero. Las categorías comerciales, los estados técnicos y la revisión humana se
mantienen separados.

## Datos y límites de implementación

La lectura pública `read_campaign` devuelve una `CampaignView` con campaña,
empresas, etapas, evaluaciones, evidencia, contactos, estado comercial,
presupuesto y un indicador de ejecución global. La interfaz combina esta lectura
con el estado del hilo en memoria; el último informe global se pierde al
reiniciar. Permite proponer resúmenes **por campaña**; las métricas exactas y
sus denominadores deben definirse y verificarse al prototipar. La revisión y la
disponibilidad de contacto son decisiones distintas.

El inicio actual usa `list_saved_campaigns`, que devuelve campañas, no un tablero
agregado de resultados. Los indicadores de la campaña destacada requerirían
consultar su lectura pública desde `core/` y medir el costo. La propuesta prioriza
esa campaña y evita cargar los resultados de todo el historial solo para llenar
paneles. Un resumen global necesitaría lecturas adicionales o una agregación cuya
precisión, rendimiento y límites de contrato deben evaluarse antes de implementarla.
No sumar empresas entre campañas como si fueran entidades únicas ni mezclar
rúbricas sin definir el significado del dato. Cualquier cambio de contrato
compartido o de otro módulo requiere la aprobación prevista en
[AGENTS.md](../AGENTS.md).

Se conservan las reglas existentes: iniciar o reanudar requiere autorización
nueva por operación, cuenta y topes; la presencia de una clave no demuestra acceso.
Durante la ejecución se bloquean las acciones que modifican o exportan resultados.
La investigación depende del proceso local y no se promete reanudación automática.
Las exclusiones sin validar, el origen y fecha de cada dato, los fallos y los
motivos de detención deben poder consultarse. La confirmación manual de canales
no envía mensajes. El CSV de listos se recalcula al descargar; el de todos incluye
pendientes y empresas sin personas, y los filtros visuales no modifican el CSV.

## Interacción, movimiento y accesibilidad

- Menú lateral con apertura y cierre explícitos; al abrirlo, desenfoque del
  contenido situado detrás y transición candidata de 180–240 ms. En pantallas
  pequeñas se presenta como cajón, con foco contenido, cierre por teclado y
  retorno del foco al control.
- Movimiento local propuesto: indicador de pestaña de 140–180 ms, cambios de
  progreso de 200–300 ms y confirmaciones de copia o guardado de 120–180 ms.
  Debe explicar cambios reales sin retrasar la lectura; el sondeo no vuelve a
  animar toda la página y no se añaden bucles decorativos.
- Respetar `prefers-reduced-motion`: retirar desplazamientos y desenfoques
  animados cuando corresponda, conservando estados y funcionalidades. Mantener
  una alternativa utilizable si JavaScript o `backdrop-filter` no está disponible.
- Tipografía legible, contraste adecuado en tema oscuro, foco visible, controles
  etiquetados y navegación completa por teclado. Estados y prioridades combinan
  texto y señales visuales; los errores se asocian al campo correspondiente.
  Las tablas y visualizaciones disponen de equivalentes textuales.
- En 1366–1440 px se prioriza la lectura sin desplazamiento horizontal de página.
  En móvil se reorganizan paneles y tablas, conservando acceso a todas las tareas.
  Los datos externos siguen escapados y los recursos se sirven localmente.

## Secuencia propuesta

1. **Diseño y prototipo:** concretar el mapa de pantallas y un prototipo visual
   con datos sintéticos, incluidos inicio, campaña y ficha; revisar dirección,
   jerarquía y estados con el usuario antes de implementar.
2. **Base visual:** definir tokens, tipografía, iconografía, navegación, paneles,
   controles y estados comunes en el stack actual. Actualizar la documentación
   visual cuando se apruebe e implemente la nueva dirección.
3. **Campañas:** aplicar el sistema a historial, preparación, autorización,
   seguimiento, filtros, presupuesto y exportaciones, preservando sus reglas.
4. **Ficha:** reorganizar resumen, contactos, evidencia y revisión secuencial,
   manteniendo trazabilidad, pendientes y permisos actuales.
5. **Movimiento y verificación:** integrar microinteracciones, revisar
   accesibilidad y adaptación, probar flujos y corregir problemas observados.

La implementación se organizará en tareas acordadas según los límites de módulos
y contratos del proyecto. Esta secuencia es una propuesta de trabajo, no cambia
el backlog de GitHub ni las decisiones de negocio.

## Criterios para validar la propuesta

- En una demostración sintética, una persona puede localizar la campaña pertinente,
  reconocer su estado y abrir la siguiente acción disponible sin confundir
  progreso, revisión y disponibilidad de contacto. Es una tarea observable para
  una futura evaluación de usabilidad, no una validación ya realizada.
- Con una campaña activa sin terminar, incluso si el hilo está detenido, la acción
  de crear otra explica el bloqueo y ofrece abrir o retomar la existente y cerrarla
  cuando corresponda, sin perder resultados.
- Puede preparar, autorizar y seguir una campaña; filtrar resultados; revisar una
  empresa y su evidencia; confirmar un canal alternativo permitido; y distinguir
  las dos exportaciones, manteniendo los bloqueos y explicaciones correspondientes.
- El indicador de consumo permanece visible y contextualizado. Los importes y
  gráficos coinciden con los datos disponibles; los desconocidos siguen pendientes.
- Se revisan 1280, 1366, 1440 y 390 px con datos exclusivamente sintéticos,
  incluidos estados vacíos, ejecución, interrupción y error; no hay
  desbordamiento horizontal de página ni controles inaccesibles por teclado.
- Se comprueban foco, contraste, etiquetas, zoom al 200 % y movimiento reducido, además de las
  pruebas de UI, seguridad, presupuesto, persistencia y contratos afectadas. Las
  pruebas funcionales se ejecutan sin red con bases temporales; las llamadas
  reales siguen sujetas a autorización explícita de gasto.

## Decisiones por concretar

- Prototipo y distribución exacta de cada pantalla, especialmente el lugar del
  resumen de consumo y el tamaño de la navegación en portátiles.
- Definición de las tarjetas y gráficos según datos disponibles, incluido si
  aporta valor un resumen entre campañas y cómo evitar lecturas costosas o dobles
  conteos.
- Componentes de 21st.dev elegidos para cada interacción, sus condiciones de uso
  y el grado de adaptación que encaja con el stack local.
- Revisión de la propuesta por el usuario antes de convertirla en implementación.
