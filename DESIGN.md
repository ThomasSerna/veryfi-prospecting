---
name: Veryfi Prospecting
description: Interfaz local de campañas y revisión comercial.
colors:
  canvas: "#0C0D0F"
  surface: "#151719"
  sidebar: "#111315"
  accent: "#84D6AC"
  accent-hover: "#A0E9C3"
  accent-text: "#10251A"
  text: "#F1F3F4"
  text-muted: "#A0A6B1"
  border: "#282B30"
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
  violet: "#B3A1EE"
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
campaña activa o, si no existe, la última guardada. El progreso y las acciones
pendientes preceden a los indicadores de calidad; el presupuesto tiene un lugar
secundario y conserva el contexto de la campaña consultada.

La interfaz usa un único tema oscuro, inspirado en el
[dashboard de AdminCN](https://shadcn-nextjs-admincn-admin-template.vercel.app/dashboard/sales).
La guía visual se adapta al flujo y los datos reales de Veryfi Prospecting. La
demostración identifica sus datos como exclusivamente sintéticos.

## Sistema visual

- Lienzo oscuro (`--ivory`), paneles grafito (`--surface`), navegación
  (`--navy`) y bordes discretos (`--line`).
- Texto principal (`--ink`), secundario (`--muted`) y acento verde (`--green`).
  Azul y violeta distinguen información
  complementaria; los estados también usan texto, no solo color.
- Inter variable se sirve desde `static/fonts/InterVariable.woff2`, con fuentes
  sans locales como alternativa. La fuente procede del
  [repositorio oficial de Inter](https://github.com/rsms/inter) y su licencia
  SIL Open Font License 1.1 está en `static/fonts/Inter-OFL.txt`.
- Paneles con bordes sutiles y radios de `12–16 px`; controles y etiquetas de
  menor radio. Los números de tablas, puntuaciones y presupuesto usan cifras
  tabulares. El logotipo blanco de Veryfi permanece como recurso local.
- Los componentes de navegación, pestañas, tarjetas y progreso se inspiran en
  [21st.dev](https://21st.dev/community/components) y se implementan con
  plantillas Django, CSS y JavaScript locales.

## Composición y flujos

- La navegación lateral reúne la creación, Resumen, Historial y las campañas
  recientes. La barra superior identifica la campaña y muestra su disponible,
  con acceso al presupuesto detallado. Durante el sondeo de la campaña, el
  resumen se actualiza junto con los resultados.
- El inicio muestra el avance, las empresas por revisar, la disponibilidad de
  contacto, la distribución de prioridades y el historial. Los indicadores
  corresponden a la campaña destacada, no a la suma de todo el historial.
- La preparación organiza los criterios en Mercado, Alcance y Resumen. Guardar
  la campaña no inicia llamadas; la autorización se presenta antes de ejecutar.
- La campaña muestra avance, prioridades, filtros, tabla y presupuesto. El
  progreso usa las empresas encontradas como denominador; durante el
  descubrimiento, si todavía no hay empresas, no inventa un porcentaje.
- La ficha conserva las pestañas Resumen, Contactos y Evidencia, las fuentes
  enlazadas y el panel de revisión. Anterior y Siguiente preservan los filtros.
  Encaje, cobertura, disponibilidad y revisión son conceptos independientes.

## Interacción y accesibilidad

El menú tiene control explícito y, en móvil, se abre como cajón con el fondo
oscurecido y desenfocado. Los indicadores y las barras incluyen sus valores en
texto. Las pestañas, los formularios y los avisos conservan etiquetas, foco y
estados identificables. Las transiciones respetan `prefers-reduced-motion`.

El contenido externo conserva el autoescape de Django. La actualización de
resultados durante la ejecución mantiene las secciones y controles necesarios
para preservar el estado de la interacción. La verificación de esta versión se
registra en [la guía de la interfaz](docs/ui.md).
