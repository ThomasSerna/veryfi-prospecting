# Diseño de Veryfi Prospecting

## Dirección confirmada

Herramienta de trabajo B2B para el equipo de ventas (Operate): campañas, resultados y fichas de empresa con jerarquía editorial clara, densidad de información controlada y flujo secuencial de revisión comercial.
Tema aprobado: superficies de lectura luminosas (`#FFFFFF` y `#E9ECE4`) con barra lateral ejecutiva en azul marino (`#171C3A`) e identidad oficial de Veryfi.
La primera pantalla muestra campañas reales guardadas o un estado vacío accionable que guía la creación de la primera campaña. Los datos de demostración se identifican explícitamente como sintéticos.

## Identidad y tokens visuales

- **Paleta principal**:
  - Navy `#171C3A` (`--navy`) para navegación principal, encabezados y contraste tipográfico primario.
  - Ivory `#E9ECE4` (`--bg`, `--bg-elevated`) para el lienzo general y superficies de contexto secundario.
  - Blanco `#FFFFFF` (`--surface`) para áreas de lectura, tablas de resultados y paneles de ficha.
  - Veryfi Green `#00FA6C` (`--green`) para la acción principal de cada pantalla con texto `#171C3A` y acabado de elevación sutil (`--green-hover: #00E060`).
- **Estados semánticos accesibles**:
  - Todas las etiquetas de estado (`.status`), prioridad (`.priority`) y decisión humana (`.review`) combinan color de alto contraste, texto explícito e indicador geométrico (`::before`: punto sólido, doble anillo, rombo o trazo) para no depender nunca solo del color.
  - Los controles deshabilitados mantienen contraste mínimo ≥ 4,5:1 (`#DCE1DD` sobre `#4A5268`).
- **Tipografía y escala**:
  - Escala tipográfica íntegra en unidades `rem` (`>= 0.75rem`) para respetar las preferencias de tamaño de fuente del navegador.
  - Números tabulares (`font-variant-numeric: tabular-nums`) en métricas, porcentajes de encaje/match, presupuestos y tablas contables.
  - Formato monetario dual: resumen legible (`USD 5.00`) en tarjetas principales acompañado de la cifra contable exacta de 6 decimales (`USD 5.000000`) para conciliación y auditoría.
- **Logotipo**:
  - Logotipo oficial de Veryfi sin deformación, efectos ni alteraciones de color; ancho mínimo de `90 px`.

Referencia: https://www.veryfi.com/brand/ (consultada el 13 de octubre de 2026).

## Composición, flujos y arquitectura de información

- **Estructura general**:
  - Barra lateral oscura con acceso directo a creación, listado e historial reciente con nombres comerciales legibles (`CO, MX · FinTech y software`).
  - Encabezado superior con migas de pan contextuales y una única acción primaria destacada por vista.
- **Vista adaptativa de campaña (`campaign.html`)**:
  - **Orden DOM = orden visual**: estructura lineal sin `display: contents` ni reordenamiento artificial con CSS `order`, garantizando lectura coherente con teclado y lector de pantalla.
  - **Promoción contextual de autorización**: cuando una campaña recién creada (`created`) aún no tiene empresas descubiertas, el paso de autorización (`Paso 2 · Autorizar la investigación`) se promueve al inicio de la vista con asistente de un clic (`Usar topes disponibles`), agrupación semántica `<fieldset><legend>` por operación y referencia explícita a la variable de entorno requerida.
  - **Filtros inteligentes**: ocultos cuando la campaña aún no tiene empresas ni filtros activos; resumen en vivo de opciones seleccionadas y contador de filtros aplicados.
  - **Actualización en vivo no destructiva**: el sondeo periódico durante la ejecución actualiza únicamente las secciones de estado, tabla y presupuesto mediante `DOMParser`, preservando el foco, los desplegables `<details>` abiertos y la posición de desplazamiento horizontal de la tabla. En páginas distintas de la campaña se consulta `?compact=1` sin renderizar HTML innecesario.
- **Ficha de empresa y bucle de revisión continua (`company.html`)**:
  - **Navegación secuencial integrada**: barra superior (`.topbar`) con miga de pan de retorno a la campaña conservando los filtros activos (`?filter_query`) y selector segmentado `← Anterior · Empresa N de M · Siguiente →`.
  - **Tres pestañas enfocadas sin títulos duplicados**: *Resumen* (con métricas y productos integrados, criterios con etiquetas semánticas `Señal fuerte` / `Señal parcial` / `Incompatible` / `Sin evidencia` y píldoras de referencia con origen o dominio), *Contactos* (ordenados por porcentaje de match, rol integrado en el subtítulo, metadatos de canal en línea, botón de copiado rápido y explicación explícita cuando una persona aún no es elegible para confirmación manual) y *Evidencia* (con resaltado visual `:target` al saltar desde una píldora de fuente).
  - **Panel lateral de decisión humana**: flujo continuo con botones *Guardar revisión* y *Guardar y pasar a la siguiente →*, confirmando cada acción mediante avisos de estado accesibles.

## Movimiento, accesibilidad y diseño adaptable

- **Microinteracciones funcionales**:
  - Transiciones breves de `150–200 ms` (`cubic-bezier(0.22, 1, 0.36, 1)`) en cambios de pestañas, apertura de secciones, foco, selección de operaciones y confirmación de copiado.
  - Respeto estricto de `prefers-reduced-motion: reduce`.
- **Accesibilidad y seguridad de presentación**:
  - Asociación automática de errores de formulario con `aria-invalid="true"` y `aria-describedby`.
  - En móvil (`<= 760 px`), la apertura del menú lateral marca `#workspace-main` como `inert` para aislar el foco dentro del cajón de navegación.
  - Autoescape estricto en todas las plantillas y filtros de presentación, sin `|safe` ni `mark_safe`.
- **Responsive**:
  - Diseño fluido verificado en anchos de `390 px`, `760 px`, `950 px`, `1280 px` y `1440 px` sin desbordamientos horizontales de página.
