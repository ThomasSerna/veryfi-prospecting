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

## Dirección visual

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

## Sistema visual

- Lienzo oscuro (`--ivory`), paneles grafito (`--surface`), navegación con
  fondo `#10151A` y bordes discretos (`--line`). La variable `--navy`
  conserva `#111315` para otros controles.
- Texto principal (`--ink`), secundario (`--muted`) y acento cian (`--cyan`).
  Verde, azul y violeta distinguen información complementaria; los estados
  también usan texto, no solo color.
- Inter variable se sirve desde `static/fonts/InterVariable.woff2`, con fuentes
  sans locales como alternativa. La fuente procede del
  [repositorio oficial de Inter](https://github.com/rsms/inter) y su licencia
  SIL Open Font License 1.1 está en `static/fonts/Inter-OFL.txt`.
- Paneles con bordes sutiles y radios de `12–16 px`; controles y etiquetas de
  menor radio. Los números de tablas, puntuaciones y presupuesto usan cifras
  tabulares. El logotipo blanco de Veryfi permanece como recurso local y, en
  móvil, se muestra a 52 × 20 px junto al nombre Prospecting.
- El cajón se inspira en el
  [dashboard de AdminCN](https://shadcn-nextjs-admincn-admin-template.vercel.app/dashboard/sales)
  y el movimiento de los paneles, en [21st.dev](https://21st.dev/community/components).
  Se implementan con plantillas Django, CSS y JavaScript locales. El inicio
  combina luz y bordes reactivos al cursor con una inclinación ligera del panel
  destacado.

## Composición y flujos

- La navegación lateral comienza cerrada y ofrece Resumen, Historial y Nueva
  campaña. La barra superior identifica la campaña y muestra su disponible,
  con acceso al presupuesto detallado. Durante el sondeo de la campaña, el
  resumen se actualiza junto con los resultados.
- El inicio muestra el avance y tres indicadores de la campaña destacada; el
  historial está en una vista independiente. Las cifras no suman campañas.
- La preparación organiza los criterios en Mercado, Alcance y Resumen. Guardar
  la campaña no inicia llamadas; la autorización se presenta antes de ejecutar.
- La campaña muestra avance, prioridades, filtros, tabla y presupuesto. El
  progreso usa las empresas encontradas como denominador; durante el
  descubrimiento, si todavía no hay empresas, no inventa un porcentaje.
- La ficha conserva las pestañas Resumen, Contactos y Evidencia, las fuentes
  enlazadas y el panel de revisión. Anterior y Siguiente preservan los filtros.
  Encaje, cobertura, disponibilidad y revisión son conceptos independientes.

## Interacción y accesibilidad

El menú se abre como cajón con el fondo oscurecido y desenfocado. Con JavaScript,
contiene el foco y permite cerrar con Escape, el fondo o su botón, devolviendo el
foco al control; sin JavaScript conserva la apertura y cierre nativos. Los
indicadores y las barras incluyen sus valores en texto. Las pestañas, los
formularios y los avisos conservan etiquetas, foco y estados identificables.
Las transiciones respetan `prefers-reduced-motion` y el movimiento posicional
se desactiva en dispositivos táctiles.

El contenido externo conserva el autoescape de Django. La actualización de
resultados durante la ejecución mantiene las secciones y controles necesarios
para preservar el estado de la interacción. La verificación de esta versión se
registra en [la guía de la interfaz](docs/ui.md).
