---
name: Veryfi Prospecting
description: Interfaz local de campañas y revisión comercial.
colors:
  canvas: "#0D1026"
  surface: "#171C3A"
  surface-top: "#1A2544"
  surface-hover: "#1B213F"
  soft: "#1E2444"
  accent: "#00FA6C"
  accent-alt: "#2DB5D2"
  accent-text: "#171C3A"
  text: "#E9ECE4"
  text-muted: "#B9BDB1"
  text-disabled: "#9B9C98"
  border: "#2D3352"
  border-strong: "#70748F"
  info: "#9BA6E8"
  info-background: "#262C56"
  warning: "#FFC56D"
  warning-background: "#3B2A12"
  error: "#FF7585"
  error-background: "#461C24"
  success: "#00D181"
  success-background: "#0A3723"
  unreviewed: "#FFC56D"
  blue: "#9BA6E8"
  blue-pale: "#C9D0E7"
  sky: "#7081F0"
  sky-dark: "#4553BA"
  navy-medium: "#45495F"
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
empresas, revisión y contacto listo; el presupuesto se consulta en cada campaña.

La dirección oscura usa la paleta de Veryfi: navy, marfil, verde Veryfi y
turquesa, con Sky, Gold y Magenta para la información y los estados. El marco compartido, el inicio, el historial, la campaña y la ficha
aplican esta dirección. Las vistas de trabajo usan menos texto que el inicio:
cifras, barras, iconos y estados con su etiqueta. Las propuestas estáticas de
campaña y ficha en `static/prototypes/` quedan como referencia histórica, con
datos exclusivamente sintéticos. La demostración identifica sus datos como sintéticos.

<!-- Pendiente: nombre creativo de la dirección (Creative North Star). No está definido; requiere decisión del equipo. -->

## Colors

Paleta de la [guía de marca de Veryfi](https://www.veryfi.com/brand/) para fondos
oscuros, consultada el 7 de noviembre de 2026, más el turquesa #2DB5D2 del degradado
del botón principal de veryfi.com. Veryfi no usa negro: el lienzo y el velo del
cajón son navy. Los estados también usan texto, no solo color.

`static/css/app.css` declara los colores de marca como primitivas (`--veryfi-*`) y
los componentes usan solo roles (`--canvas`, `--accent`…); probar otra paleta es
reasignar esos roles. Los navy derivados se escriben en OKLCH con el matiz de Navy
(274°); aquí figura su equivalente hexadecimal.

- **Lienzo** (`canvas`, #0D1026): Navy oscurecido para el fondo de página. Variable `--canvas`.
- **Paneles** (`surface`, Navy #171C3A): tarjetas, tablas y el cajón lateral.
  `surface-top` (#1A2544) aclara hacia el turquesa la parte superior del resumen y del pulso.
- **Superficies secundarias** (`soft`, #1E2444; `surface-hover`, #1B213F): filas,
  badges, campos y la opción actual del menú.
- **Acento** (`accent`, Veryfi Green #00FA6C; `accent-alt`, #2DB5D2; `accent-text`,
  Navy): foco, selección, pestaña activa y botón principal. El botón usa el degradado
  verde-turquesa de veryfi.com con texto navy (11.78:1).
- **Texto** (`text`, Ivory #E9ECE4; `text-muted`, Ivory Medium #B9BDB1;
  `text-disabled`, Ivory Dark #9B9C98): variables `--ink`, `--muted` y `--disabled-ink`.
- **Bordes** (`border`, #2D3352; `border-strong`, Navy Light #70748F): divisiones y
  controles. Variables `--line` y `--line-strong`.
- **Estados**: `success` (Forest Light #00D181), `info` (Sky Light #9BA6E8),
  `warning` (Gold #FFC56D) y `error` (Magenta Light #FF7585), cada uno con su fondo
  (`*-background`). Sin revisar usa `unreviewed` (Gold) y Contacto listo, `success`.
- **Datos**: encaje, match y Empresas usan `blue` (Sky Light); `blue-pale` (#C9D0E7)
  marca prioridad media y cobertura.
- **Prioridad**: escala Sky (#9BA6E8 alta, #7081F0 media, #4553BA baja) y navy
  (#70748F evidencia insuficiente, #45495F excluidas). Se acompaña de barras de
  señal y del texto de la prioridad.

## Typography

Inter variable se sirve desde `static/fonts/InterVariable.woff2`, con fuentes sans
locales como alternativa. La fuente procede del
[repositorio oficial de Inter](https://github.com/rsms/inter) y su licencia SIL
Open Font License 1.1 está en `static/fonts/Inter-OFL.txt`. Las tipografías de marca
de Veryfi (NB International y DIN Pro) son comerciales y no se incluyen.

- **Encabezados** (`heading`): 2rem, peso 600, altura de línea 1.18, interletrado -0.03em.
- **Texto** (`body`): 0.9375rem, altura de línea 1.55.
- Los números de tablas, puntuaciones y presupuesto usan cifras tabulares.

## Layout

- La navegación lateral comienza cerrada y ofrece Resumen, Historial y Nueva
  campaña. Su botón queda alineado con el logotipo en la barra superior, que
  muestra la ruta y, en la ficha, Anterior y Siguiente. La barra superior no
  resume el presupuesto: cada campaña muestra el suyo.
- El inicio muestra el avance y tres indicadores de la campaña destacada; el
  historial está en una vista independiente. Las cifras no suman campañas.
- La preparación organiza los criterios en Mercado, Alcance y Resumen. Guardar la
  campaña no inicia llamadas; la autorización se presenta antes de ejecutar.
- La campaña abre con un pulso: un segmento por empresa encontrada, la cifra de
  investigadas, Sin revisar, Contacto listo y Aceptadas, y una barra apilada de
  prioridades con su leyenda enlazada a filtros. Debajo, la tabla con búsqueda y
  filtros en una sola barra, y el presupuesto. El progreso usa las empresas
  encontradas como denominador; durante el descubrimiento, si todavía no hay
  empresas, no inventa un porcentaje. Las descargas están en el encabezado.
- La ficha presenta identidad y estados en el encabezado, conserva las pestañas
  Resumen, Contactos y Evidencia, las fuentes enlazadas y, a la derecha, el mejor
  match y la revisión de ventas. Anterior y Siguiente preservan los filtros.
  Encaje, cobertura, disponibilidad y revisión son conceptos independientes.

## Elevation & Depth

La jerarquía se construye con bordes sutiles y capas de tono (`surface` sobre
`canvas`). Las sombras aparecen como respuesta a un estado: el desplegable de
filtros, la confirmación flotante, la elevación de un panel del inicio al pasar
el cursor con puntero fino y el halo del botón principal. Los paneles de trabajo
(pulso de campaña, revisión) no se elevan: solo orientan su borde hacia el puntero.

## Shapes

Paneles con bordes sutiles y radios de 12–16 px (`md` y `lg`). Controles con 8 px
(`sm`) y campos o etiquetas con 6 px (`xs`). Búsqueda, filtros, contadores y
etiquetas de mercado o producto usan forma de píldora; las fuentes, 13 px para
seguir legibles si su texto ocupa dos líneas.

## Components

### Navegación

El menú se abre como cajón con el fondo oscurecido y desenfocado. Con JavaScript,
contiene el foco y permite cerrar con Escape, el fondo o su botón, devolviendo el
foco al control; sin JavaScript conserva la apertura y cierre nativos. El cajón se
inspira en el [dashboard de AdminCN](https://shadcn-nextjs-admincn-admin-template.vercel.app/dashboard/sales)
y el movimiento de los paneles, en [21st.dev](https://21st.dev/community/components).
El botón del menú, sin caja propia, comparte la línea del logotipo; al señalarlo,
su carril se llena de verde y el chevrón empuja hacia el cajón, a partir del icono
animado `panel-left-open` de [lucide-animated](https://github.com/pqoqubbw/icons)
(MIT), recreado en CSS. Durante una investigación muestra un punto que late.

### Campaña

- **Pulso:** estado, cifra de investigadas con rodillo, un segmento por empresa y
  tres cifras con su barra (Sin revisar en dorado, Contacto listo en verde,
  Aceptadas en marfil). En curso, un haz recorre el borde.
- **Prioridad:** barra apilada y leyenda con recuento; cada entrada filtra la tabla.
- **Tabla:** avatar con la inicial tintado por prioridad, nombre con flecha al
  señalar, encaje con barra y cobertura, prioridad con barras de señal (3, 2 o 1),
  disponibilidad, revisión con icono (círculo, marca o cruz) y contactos con su
  mejor match. Toda la fila abre la ficha; el nombre es el único enlace.
- **Presupuesto:** libro de cuatro importes con el disponible destacado y las
  cuentas en un desplegable.

### Ficha

- **Encabezado:** avatar, nombre, dominio, países y segmentos con iconos, y los
  tres estados (prioridad, disponibilidad y revisión) separados.
- **Pestañas:** una línea medida desde cada etiqueta marca la activa y una
  pastilla sigue al puntero; el panel entra desde el lado de la pestaña elegida.
  Siguen el patrón de teclado de pestañas (flechas, Inicio y Fin) y el panel
  recibe el foco con Tab.
- **Encaje:** cifra grande con barra graduada en cuartos, cobertura, explicación y
  productos. Cada criterio muestra una bola de Harvey (llena, media, vacía o
  punteada) junto a su etiqueta textual.
- **Contactos:** persona con match en barra, etapa en cinco pasos más su etiqueta,
  y canales como filas con icono, estado y copia; Directo y Utilizable se marcan
  con iconos y conservan su texto para lectores de pantalla.
- **Evidencia:** número de fuente como referencia citable; al llegar desde una
  píldora, la fuente se ilumina un instante.
- **Lateral:** mejor match y revisión fijos al desplazarse. La decisión es un
  control segmentado (Pendiente, Aceptado, Rechazado) cuyo fondo se desliza a la
  opción elegida.

### Controles, avisos y datos

Los indicadores y las barras incluyen sus valores en texto. Las pestañas, los
formularios y los avisos conservan etiquetas, foco y estados identificables. Los
avisos de campaña y ficha llevan icono y título en una línea. Guardar una revisión,
confirmar un canal o cerrar una campaña se confirma con un aviso flotante que se
retira solo; con movimiento reducido queda como aviso en la página.

### Marca

El logotipo blanco de Veryfi permanece como recurso local y, en móvil, se muestra
a 52 × 20 px junto al nombre Prospecting.

### Movimiento

- **Transiciones:** animaciones fluidas y perceptibles en navegación, pestañas, paneles y cambios de estado.
- **Microinteracciones:** botones, tarjetas y controles responden con movimientos naturales y feedback visual.
- **Contenido dinámico:** entradas escalonadas, contadores animados y transiciones suaves al actualizar resultados o progreso, sin reinicios innecesarios.
- **Jerarquía:** los elementos protagonistas pueden incorporar animaciones elaboradas; los secundarios mantienen movimientos discretos.
- **Implementación:** CSS y JavaScript nativo, priorizando `transform` y `opacity`, respetando `prefers-reduced-motion` y la accesibilidad.

Las transiciones respetan `prefers-reduced-motion`. Se desactivan las respuestas
al movimiento del puntero táctil; el fondo de Resumen puede animarse en estos
dispositivos. Las animaciones deben comprobarse en el navegador: el resultado debe
transmitir una experiencia interactiva refinada sin distraer del trabajo comercial.

En Resumen, incluso sin campañas, un lienzo WebGL local aporta círculos suaves
verdes y turquesas sobre navy, adaptados de [veryfi.com](https://www.veryfi.com/)
(consultado el 9 de noviembre de 2026). Tiene opacidad 0,55, velocidad del 100 %
de la referencia y resolución del área visible dividida por 15 y redondeada; el
dibujo se limita a 30 fotogramas por segundo. El lienzo queda fuera de la región
del sondeo. La animación se pausa si la página está oculta o el panel de Resumen
sale de la vista y queda estática con movimiento reducido. Con colores forzados o
si falla WebGL se conserva el fondo habitual. El fondo no descarga recursos
externos ni añade dependencias.

En campaña y ficha, el movimiento explica cambios y no decora: una entrada en
cascada corta al abrir la vista (de 0,5 a 0,9 s, sin bloquear la interacción) y,
durante el sondeo, solo se animan las diferencias. Una empresa nueva sube a su
fila con un destello verde, una fila que cambia de puesto se desliza (FLIP) y una
fila cuyo contenido cambia se ilumina; las cifras que crecen muestran `+n`. Al
terminar la investigación, la página se actualiza en su sitio sin recargarse.
Con movimiento reducido, todo llega en su estado final y los cambios solo se
funden o cambian de color.

## Do's and Don'ts

- **Do** acompañar cada estado con texto además del color.
- **Do** respetar `prefers-reduced-motion` y reservar las respuestas al puntero para dispositivos con puntero fino que detecten el paso del cursor.
- **Do** preferir en las vistas de trabajo una cifra, una barra o un icono con su etiqueta breve antes que una frase explicativa.
- **Don't** usar `|safe` ni `mark_safe` en contenido externo; el autoescape de Django se conserva.
- **Don't** usar el color como único indicador de estado.
- **Don't** reiniciar animaciones de entrada durante el sondeo ni animar alturas o anchos.
