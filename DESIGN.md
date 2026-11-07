---
name: Veryfi Prospecting
description: Interfaz local de campañas y revisión comercial.
colors:
  canvas: "#0D0F14"
  surface: "#15171D"
  sidebar: "#10151A"
  accent: "#80DFF3"
  accent-hover: "#A8ECF9"
  accent-text: "#10252C"
  text: "#F0F2F6"
  text-muted: "#A4AAB8"
  border: "#2B2E38"
  border-strong: "#68727F"
  soft: "#1C1F23"
  info: "#A2C2FF"
  info-background: "#1C2738"
  warning: "#EBCE85"
  warning-background: "#302B1E"
  error: "#FFAAAA"
  error-background: "#352123"
  success: "#98DFB6"
  success-background: "#1C3026"
  violet: "#B7A5FA"
  blue: "#97BDF1"
typography:
  heading:
    fontFamily: "Inter, Arial, Helvetica, sans-serif"
    fontSize: "2rem"
    fontWeight: 600
    lineHeight: 1.18
    letterSpacing: "-0.03em"
  body:
    fontFamily: "Inter, Arial, Helvetica, sans-serif"
    fontSize: "0.9375rem"
    lineHeight: 1.55
rounded:
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
spacing:
  "1": "6px"
  "2": "12px"
  "3": "16px"
  "4": "24px"
  "5": "32px"
  "6": "44px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-text}"
    rounded: "{rounded.sm}"
    padding: "10px 18px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "10px 18px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.xs}"
    padding: "10px 12px"
  navigation-link:
    textColor: "{colors.text-muted}"
    rounded: "{rounded.xs}"
    padding: "10px 12px"
  status-success:
    backgroundColor: "{colors.success-background}"
    textColor: "{colors.success}"
    rounded: "{rounded.xs}"
    padding: "4px 10px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
---

# Diseño de Veryfi Prospecting

## Overview

Herramienta de trabajo para el equipo de ventas: preparar campañas, seguir la
investigación y revisar empresas, personas y evidencia. El inicio destaca la
campaña activa o, si no existe, la última guardada. Sus indicadores resumen
empresas, revisión y contacto listo; el presupuesto conserva el contexto de la
campaña consultada.

La dirección oscura combina grafito, cian y violeta con el nombre Veryfi
Prospecting. El marco compartido, el inicio y el historial aplican esta dirección;
las propuestas de campaña y ficha son estáticas, con datos exclusivamente
sintéticos, y están pendientes de revisión antes de extender sus distribuciones
a las vistas operativas. La demostración identifica sus datos como sintéticos.

<!-- Pendiente: nombre creativo de la dirección (Creative North Star). No está definido; requiere decisión del equipo. -->

## Colors

Paleta oscura de grafito con acento cian. Verde, azul y violeta distinguen
información complementaria; los estados también usan texto, no solo color.

- **Lienzo** (`canvas`, #0D0F14): fondo de página. Variable `--ivory`.
- **Paneles** (`surface`, #15171D): tarjetas, filtros y tablas. Variable `--surface`.
- **Navegación** (`sidebar`, #10151A): fondo del cajón lateral.
  La variable `--navy` conserva #111315 para otros controles.
- **Acento** (`accent`, #80DFF3; `accent-hover`, #A8ECF9; `accent-text`, #10252C):
  acción principal y elemento seleccionado. Variables `--cyan` y `--cyan-hover`.
- **Texto** (`text`, #F0F2F6; `text-muted`, #A4AAB8): variables `--ink` y `--muted`.
- **Bordes** (`border`, #2B2E38; `border-strong`, #68727F): divisiones y controles.
  Variables `--line` y `--line-strong`.
- **Superficie secundaria** (`soft`, #1C1F23): filas, badges y campos deshabilitados.
- **Estados**: `info`, `warning`, `error` y `success`, cada uno con su fondo
  (`*-background`). `violet` y `blue` completan la información complementaria.

## Typography

Inter variable se sirve desde `static/fonts/InterVariable.woff2`, con fuentes sans
locales como alternativa. La fuente procede del
[repositorio oficial de Inter](https://github.com/rsms/inter) y su licencia SIL
Open Font License 1.1 está en `static/fonts/Inter-OFL.txt`.

- **Encabezados** (`heading`): 2rem, peso 600, altura de línea 1.18, interletrado -0.03em.
- **Texto** (`body`): 0.9375rem, altura de línea 1.55.
- Los números de tablas, puntuaciones y presupuesto usan cifras tabulares.

## Layout

- La navegación lateral comienza cerrada y ofrece Resumen, Historial y Nueva
  campaña. La barra superior identifica la campaña y muestra su disponible, con
  acceso al presupuesto detallado. Durante el sondeo de la campaña, el resumen se
  actualiza junto con los resultados.
- El inicio muestra el avance y tres indicadores de la campaña destacada; el
  historial está en una vista independiente. Las cifras no suman campañas.
- La preparación organiza los criterios en Mercado, Alcance y Resumen. Guardar la
  campaña no inicia llamadas; la autorización se presenta antes de ejecutar.
- La campaña muestra avance, prioridades, filtros, tabla y presupuesto. El progreso
  usa las empresas encontradas como denominador; durante el descubrimiento, si
  todavía no hay empresas, no inventa un porcentaje.
- La ficha conserva las pestañas Resumen, Contactos y Evidencia, las fuentes
  enlazadas y el panel de revisión. Anterior y Siguiente preservan los filtros.
  Encaje, cobertura, disponibilidad y revisión son conceptos independientes.

## Elevation & Depth

La jerarquía se construye con bordes sutiles y capas de tono (`surface` sobre
`canvas`). Las sombras aparecen como respuesta a un estado: el desplegable de
filtros, la elevación de un panel al pasar el cursor con puntero fino y el halo
del botón principal.

## Shapes

Paneles con bordes sutiles y radios de 12–16 px (`md` y `lg`). Controles con 8 px
(`sm`) y campos o etiquetas con 6 px (`xs`).

## Components

### Navegación

El menú se abre como cajón con el fondo oscurecido y desenfocado. Con JavaScript,
contiene el foco y permite cerrar con Escape, el fondo o su botón, devolviendo el
foco al control; sin JavaScript conserva la apertura y cierre nativos. El cajón se
inspira en el [dashboard de AdminCN](https://shadcn-nextjs-admincn-admin-template.vercel.app/dashboard/sales)
y el movimiento de los paneles, en [21st.dev](https://21st.dev/community/components).

### Controles, avisos y datos

Los indicadores y las barras incluyen sus valores en texto. Las pestañas, los
formularios y los avisos conservan etiquetas, foco y estados identificables.

### Marca

El logotipo blanco de Veryfi permanece como recurso local y, en móvil, se muestra
a 52 × 20 px junto al nombre Prospecting.

### Movimiento

- **Transiciones:** animaciones fluidas y perceptibles en navegación, pestañas, paneles y cambios de estado.
- **Microinteracciones:** botones, tarjetas y controles responden con movimientos naturales y feedback visual.
- **Contenido dinámico:** entradas escalonadas, contadores animados y transiciones suaves al actualizar resultados o progreso, sin reinicios innecesarios.
- **Jerarquía:** los elementos protagonistas pueden incorporar animaciones elaboradas; los secundarios mantienen movimientos discretos.
- **Implementación:** CSS y JavaScript nativo, priorizando `transform` y `opacity`, respetando `prefers-reduced-motion` y la accesibilidad.

Las transiciones respetan `prefers-reduced-motion`, y el movimiento posicional se
desactiva en dispositivos táctiles. Las animaciones deben comprobarse en el
navegador: el resultado debe transmitir una experiencia interactiva refinada sin
distraer del trabajo comercial.

## Do's and Don'ts

- **Do** acompañar cada estado con texto además del color.
- **Do** mantener el movimiento dentro de `prefers-reduced-motion` y, en táctil, sin desplazamiento posicional.
- **Don't** usar `|safe` ni `mark_safe` en contenido externo; el autoescape de Django se conserva.
- **Don't** usar el color como único indicador de estado.
