---
name: Veryfi Prospecting
description: Interfaz local de campañas y revisión comercial.
colors:
  canvas: "#f4f5ef"
  surface: "#ffffff"
  soft: "#e9ece4"
  ink: "#171c3a"
  muted: "#45495f"
  line: "#d2d6cc"
  line-strong: "#70748f"
  brand-green: "#00fa6c"
  accent: "#176046"
  aqua-light: "#b4f4e4"
  info: "#39478b"
  info-background: "#e9edf9"
  warning: "#754900"
  warning-background: "#fff1d9"
  error: "#9b2547"
  error-background: "#fce7ee"
  success-background: "#e1f4e7"
typography:
  display:
    fontFamily: "Inter, Arial, Helvetica, sans-serif"
    fontSize: "clamp(2.75rem, 5.2vw, 4.75rem)"
    fontWeight: 680
    lineHeight: 1.04
    letterSpacing: "-0.04em"
  body:
    fontFamily: "Inter, Arial, Helvetica, sans-serif"
    fontSize: "0.9375rem"
    lineHeight: 1.55
rounded:
  xs: "4px"
  sm: "5px"
  md: "8px"
  lg: "12px"
spacing:
  "1": "6px"
  "2": "12px"
  "3": "16px"
  "4": "24px"
  "5": "32px"
  "6": "44px"
components:
  button-primary:
    backgroundColor: "{colors.brand-green}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "10px 18px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "10px 18px"
  status-success:
    backgroundColor: "{colors.success-background}"
    textColor: "{colors.accent}"
---

# Diseño de Veryfi Prospecting

## Overview

La interfaz usa una composición editorial de fondo marfil para preparar campañas,
seguir su avance y revisar empresas, personas y evidencia. El fondo navy distingue la
campaña destacada en Resumen y el panel de avance dentro de una campaña. Encabezados,
reglas horizontales y cifras tabulares ayudan a recorrer las vistas de trabajo.

## Colors

El verde Veryfi (#00fa6c) identifica la acción primaria con texto navy. Los enlaces y
el foco sobre superficies claras usan verde oscuro (#176046). Aqua Light (#b4f4e4)
aporta un matiz a las cabeceras de tabla, al resumen de preparación y a los datos de
encaje de la ficha. [Guía de marca de Veryfi](https://www.veryfi.com/brand/)

`static/css/app.css` define los colores de marca y sus roles. La portada y el panel de
avance reasignan los roles a su esquema navy. Los estados incluyen una etiqueta
textual y recurren a información, advertencia, error o éxito según su significado.

## Typography

Inter variable se sirve localmente desde `static/fonts/InterVariable.woff2`, con
alternativas sans serif del sistema. La licencia SIL Open Font License 1.1 está en
`static/fonts/Inter-OFL.txt`. Los títulos de Resumen e Historial crecen de 2.75 a
4.75 rem según el ancho. Las vistas de campaña, ficha y preparación tienen un máximo
de 4.25 rem. Tablas, puntuaciones y contadores alinean cifras tabulares.

## Layout

- **Navegación.** La barra superior reúne marca, Resumen, Historial y Nueva campaña.
  En pantallas de hasta 680 px los enlaces ocupan una fila bajo la marca. La sección
  actual se indica con `aria-current` y se distingue visualmente. El enlace de salto
  lleva al contenido principal.
- **Resumen.** El relieve cartográfico de Latinoamérica se integra a la derecha del
  panel navy con el texto de campaña a la izquierda. En móvil la imagen queda
  debajo del texto. El avance, Sin revisar y Con contacto listo ocupan la franja
  inferior. Si hay una campaña destacada se ofrece un acceso al historial.
- **Historial.** Las filas agrupan mercado y segmentos junto al nombre de la campaña.
  En pantallas estrechas, el nombre abre la campaña y deja a la vista su estado y fecha.
- **Campaña.** El encabezado sitúa el mercado y las acciones disponibles. El panel
  navy reúne avance y prioridades. La tabla de empresas mantiene la búsqueda y
  los filtros juntos. Según el estado, los enlaces de sección llevan a Empresas y
  Autorización.
- **Ficha.** Identidad, estados y navegación entre empresas preceden Resumen y
  Contactos. La ficha destaca encaje, criterios y fuentes. La revisión de ventas
  y el contacto con mayor match ocupan el lateral donde hay espacio.
- **Preparación.** Mercado y Alcance comparten la vista con un resumen tintado que
  se coloca debajo en pantallas estrechas. La autorización se revisa antes de ejecutar.

## Elevation & Depth

La retícula usa cambios de tono y divisiones finas entre filas y secciones. Las sombras
ayudan a leer los desplegables y los avisos flotantes. La imagen cartográfica es
decorativa y se oculta con colores forzados.

## Shapes

La portada usa 12 px de radio. El panel de avance y el resumen de preparación usan
8 px. Botones y campos usan radios de 4–5 px. Las tablas se leen como registros
continuos con separadores horizontales.

## Components

- **Controles.** Los botones principales usan el verde Veryfi, los secundarios
  un borde y los enlaces una línea de foco visible. Los enlaces con flecha la
  desplazan brevemente al pasar el puntero o al enfocar.
- **Progreso y estados.** Los contadores conservan sus valores en el documento.
  Los segmentos visualizan empresas investigadas. El estado de campaña y los
  avisos de ejecución se anuncian con regiones de estado.
- **Movimiento.** Al abrir una vista, el contenido entra por grupos. La imagen
  cartográfica tiene una entrada única. Con ratón, los rayos cercanos al puntero
  se desplazan unos píxeles y la silueta queda fija. El sondeo actualiza los datos en su sitio,
  con señales breves en segmentos, cifras y filas que cambian. Las pestañas y el
  control de revisión responden al cambio de selección. Con
  `prefers-reduced-motion` se desactivan las animaciones y el desplazamiento suave.
  Los efectos de puntero se limitan a dispositivos con puntero fino.
- **Evidencia.** Las pestañas, criterios y canales conservan sus etiquetas. Un criterio
  muestra una marca visual junto a su nivel de señal. Los enlaces a fuentes permanecen
  accesibles y el autoescape de Django protege el contenido externo.
