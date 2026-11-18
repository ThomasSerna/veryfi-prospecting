---
name: Veryfi Prospecting
description: Interfaz editorial para preparar campañas y revisar empresas.
colors:
  navy: "#171C3A"
  ivory: "#E9ECE4"
  canvas: "{colors.ivory}"
  surface: "#F8F9F5"
  text: "{colors.navy}"
  text-muted: "#51566A"
  border: "#BDC3B9"
  border-strong: "#787E79"
  accent: "#00FA6C"
  accent-text: "{colors.navy}"
  info: "#3847A1"
  info-background: "#E3E7FA"
  warning: "#755008"
  warning-background: "#FAF0D8"
  error: "#9C2138"
  error-background: "#FAE5E8"
  success: "#006347"
  success-background: "#D7EFDF"
typography:
  heading:
    fontFamily: "Baskervville, Georgia, serif"
    fontSize: "clamp(2.6rem, 5vw, 4.75rem)"
    fontWeight: 400
    lineHeight: 1.05
  cover-heading:
    fontFamily: "{typography.heading.fontFamily}"
    fontSize: "clamp(3.1rem, 6.9vw, 6rem)"
    fontWeight: 400
    lineHeight: 1
  section-heading:
    fontFamily: "{typography.heading.fontFamily}"
    fontSize: "1.7rem"
    fontWeight: 400
    lineHeight: 1.16
  body:
    fontFamily: "Inter, Arial, Helvetica, sans-serif"
    fontSize: "0.9375rem"
    lineHeight: 1.55
  button:
    fontFamily: "{typography.body.fontFamily}"
    fontSize: "0.875rem"
    fontWeight: 600
  button-small:
    fontFamily: "{typography.body.fontFamily}"
    fontSize: "0.8125rem"
    fontWeight: 600
rounded:
  xs: "3px"
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
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-text}"
  topbar:
    backgroundColor: "{colors.navy}"
---

# Diseño de Veryfi Prospecting

## Identidad

La empresa que ventas está revisando ocupa el lugar de un titular. Su nombre y el
motivo de encaje se leen juntos. El mercado, el estado y las cifras de seguimiento
dan contexto a esa decisión. En campaña, las filas compactas permiten comparar
varias empresas en una misma columna. La composición toma el uso de titulares y
separadores de *Monograph* y la alineación de datos de *orbit*. [Monograph](https://github.com/pablomanjarres/twenty-web-studies/blob/trunk/public/previews/monograph.jpg) · [orbit](https://github.com/pablomanjarres/twenty-web-studies/blob/trunk/public/previews/orbit.jpg)

## Color y tipografía

- La cabecera navy reúne el logotipo blanco de Veryfi y la navegación. El marfil
  predomina en las superficies de lectura. El verde Veryfi con texto navy
  distingue la acción principal. [Guía de marca de Veryfi](https://www.veryfi.com/brand/)
- Baskervville da forma a los titulares de mercados y empresas. Inter se utiliza
  en controles, tablas, datos y texto de lectura. Ambas familias se sirven con la
  aplicación y conservan sus licencias SIL Open Font License. [Baskervville](https://github.com/google/fonts/tree/main/ofl/baskervville) · [Inter](https://github.com/rsms/inter)
- El espaciado agrupa el nombre de cada empresa con sus datos. Los separadores
  finos marcan el comienzo de la fila o sección siguiente. Las cifras tabulares
  permiten comparar puntuaciones y recuentos.
- Los indicadores de prioridad, disponibilidad y revisión incluyen su nombre en
  texto. Una puntuación pendiente se identifica como tal. El color y las barras
  sirven de apoyo.

En el Resumen, el titular de empresa varía entre 3,1 y 6 rem según el ancho de
la pantalla. Los títulos de campaña y ficha van de 2,6 a 4,75 rem, y el título
del Historial, de 3 a 5 rem. En el índice, los nombres de mercado se leen a
1,75 rem. «Empresas», «Encaje comercial» y «Revisión de ventas» abren sus
secciones a 1,7 rem. Los botones usan Inter a 0,875 rem y los compactos a
0,8125 rem. Las etiquetas breves de estado se componen a 0,75 rem.

## Composición por pantalla

| Pantalla | Foco y distribución |
|---|---|
| Resumen | Presenta la campaña activa o la última guardada. La empresa pendiente de revisión tiene acceso directo a su ficha. Durante la investigación se muestra el seguimiento. |
| Historial | La fecha, el mercado y el estado identifican cada campaña del índice. |
| Nueva campaña | Mercado y alcance se completan junto a un resumen de los criterios y topes. La autorización de ejecución tiene su propio paso. |
| Campaña | La campaña preparada da paso a la autorización. Durante la ejecución, la franja de avance precede a los resultados parciales. Al terminar, la lista y sus filtros ocupan el primer plano y la franja aparece debajo. |
| Ficha | El nombre y la explicación del encaje introducen la lectura. Resumen y Contactos organizan el detalle. La decisión de ventas acompaña la ficha en escritorio y pasa al flujo de lectura en móvil. |

## Navegación e interacción

En escritorio, Resumen, Historial y Nueva campaña están visibles en la cabecera.
En móvil se agrupan en un menú operable con teclado. Desde la ficha se puede
avanzar a la siguiente empresa o regresar a la campaña manteniendo la selección
de filtros de la lista de origen.

El sondeo actualiza el estado y el avance durante una investigación. Las
transiciones señalan qué cambió y respetan la preferencia de movimiento reducido.
Los campos, enlaces y controles tienen foco visible. Los avisos de bloqueo, error
y guardado se pueden leer en texto.

La guía de uso describe las autorizaciones, los bloqueos de escritura y las
modalidades de descarga. [Interfaz local de campañas y revisión](docs/ui.md)
