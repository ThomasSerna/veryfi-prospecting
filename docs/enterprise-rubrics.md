# Referencias enterprise de Veryfi y diseño de rúbricas (empresas y personas)

Documento de referencia para las tareas **T13** (calibración de ICP enterprise), **T14** (`rubric_v2` para empresas grandes), **T15** (taxonomía de cargos en Apollo) y **T19** (`contact_match_v2` para priorización de personas). Sintetiza la información de los tres documentos comerciales facilitados por Veryfi y establece cómo se conectan con el registro incremental de perfiles reales en `data/veryfi-reference-profiles.md`.

> **Estado de validación (`AGENTS.md`, `Business-rules.md` y `Roadmap.md`):**
> Los materiales comerciales citados combinan distintos periodos (2022–2026). Según T13, T14 y T19, los niveles de cliente, los pesos propuestos (`rubric_v2` y `contact_match_v2`) y la taxonomía derivada son **propuestas e hipótesis de trabajo** sujetas a ratificación comercial de Veryfi y a evaluación offline antes de sustituir en código las versiones activas (`rubric_v1` y `contact_match_v1`).

---

## 1. Fuentes documentales analizadas

1. **`How Veryfi Sells`** (47 págs., © Veryfi Inc.): niveles de cliente (*Customer Tiers*), movimiento *Inbound (PLG)* vs. *Outbound (Sales-Led)*, ICP detallados para FinTech y CPG (SMB vs. Enterprise), mapa del mercado direccionable (SAM), cajas de herramientas (*Expense Management*, *Bill Pay*, *CPG Brands*), casos de uso de recibos/folios/facturas y estructura de precios *Sales-Led* vs. *Self-Serve*.
2. **`WhatsApp Bot`** (32 págs., © 2025 Veryfi Inc.): problemática de validación de compras en CPG, arquitectura del bot de WhatsApp + OCR API, y casos reales de campañas de fidelización en Latinoamérica (PepsiCo México/Colombia, Grupo Bimbo, Marinela, Nestlé, CremHelado).
3. **`Sales Deck`** (35 págs., © 2026 Veryfi Inc.): posicionamiento de clientes por vertical (*FinTech Software*, *Loyalty Marketing*, *AP Automation*), marcas de CPG en LATAM, captura móvil/web (recibos, códigos impresos en empaques y tapas de botella), *Fraud Prevention Suite* (*upstream*), *Product Intelligence* (enriquecimiento a nivel de SKU) y tarifas de licenciamiento enterprise.

---

## 2. Por qué Veryfi prioriza empresas grandes (Tiers y economía de la oferta)

En `How Veryfi Sells` (págs. 6–7, 27–29, 46) y `Sales Deck` (págs. 30–32), Veryfi separa claramente dos movimientos comerciales:

- **Inbound / Product-Led Growth (Self-Serve):** pensado para **Tier 3** y parte de **Tier 2** con menor volumen (compromiso mínimo de USD 500/mes, hasta ~6.250 recibos o ~3.125 facturas/mes, soporte por correo, sin SLA). No requiere prospección outbound intensiva.
- **Outbound / Sales-Led Motion (equipo de ventas):** enfocado en **Tier 1 y Tier 2**, donde existen contratos anuales, altos volúmenes documentales (>25.000 a >250.000 documentos/mes), módulos fijos de USD 1.500–3.000/mes por producto (*Lens*, *WhatsApp Bot*, *Product Intelligence*, *Business Rules Engine*), integraciones ERP (USD 20.000 de setup) y planes de plataforma/SLA *Silver* (USD 1.000/mes), *Gold* (USD 3.000–5.000/mes) o *Platinum* (USD 10.000/mes).

### Clasificación de niveles de cliente (*Customer Tiers*)

| Nivel | Potencial ACV | Industria general (ingresos anuales) | Empresas de Software / FinTech | Movimiento comercial | Prioridad en Veryfi Prospecting |
|---|---|---|---|---|---|
| **Tier 1** | > USD 250k | > USD 1B en ingresos | > 1.000 empleados · Funding USD 100M+ | **Sales Team (Outbound)** | **Prioridad máxima (objetivo central enterprise)** |
| **Tier 2** | USD 25k – 250k | USD 100M – 1B en ingresos | 100 – 1.000 empleados · Funding USD 25M – 99M | **Sales Team (Outbound)** | **Prioridad alta (objetivo enterprise / mid-market alto)** |
| **Tier 3** | < USD 25k | < USD 100M en ingresos | < 100 empleados · Funding < USD 25M | Marketing vía Self-Serve + TAM | Baja prioridad para outbound (salvo caso de uso B2B2B o agencia multiplicadora) |

---

## 3. Tipos de empresas con las que ha trabajado Veryfi

A partir de los tres documentos, las empresas con las que Veryfi ha trabajado se agrupan en **tres grandes pilares comerciales** más verticales adyacentes del SAM.

> **Regla de negocio (T13 y `Business-rules.md`):**
> Las empresas listadas como clientes en las presentaciones sirven con **doble propósito**:
> 1. **Patrón positivo de referencia (ICP):** muestran qué tipo de modelo de negocio, escala y flujo documental encaja con Veryfi para buscar cuentas **comparables** en Colombia y México.
> 2. **Candidatas a exclusión (`current_customer`):** no deben proponerse como prospectos nuevos de la misma entidad/marca ya atendida; en entidades multinacionales o grupos empresariales debe distinguirse siempre matriz, filial nacional y marca (`scope`: `entity`, `country` o `group`).

### 3.1. Vertical 1: FinTech y Software B2B2B (`fintech_software`)

Empresas tecnológicas cuyo propio producto o plataforma procesa documentos financieros o de gasto para miles de empresas o usuarios finales (*Technology Embedded in your App*):

| Subtipo de empresa | Qué hace la empresa | Flujo documental y productos de Veryfi | Empresas de referencia en los decks |
|---|---|---|---|
| **Gestión de gastos y viajes corporativos (*Travel & Expenses / Spend Management*)** | Tarjetas corporativas, reembolsos de empleados, control de políticas de gasto y viáticos | Captura de recibos en app móvil/web/WhatsApp (`lens`), extracción OCR en tiempo real (`document_ocr_api`), conciliación contra transacciones de tarjeta y detección de recibos duplicados o manipulados (`antifraud`) | **Navan, Ramp, Brex, Zoho, Rydoo, Airbase, Rippling**, *Zeller* (ejemplo de análisis) |
| **Pagos B2B y cuentas por pagar (*Bill Pay*)** | Automatización de pagos a proveedores, gestión de flujo de caja, financiamiento y conciliación | Extracción de facturas (*invoices*, *bills*), órdenes de compra (*POs*), cheques y estados de cuenta; detección de fraude en pagos a proveedores (`document_ocr_api`, `validation_enrichment`, `antifraud`) | **Melio, Mercury, Square, Razorpay, WEX, SquareWorks, Rippling** |
| **ERP, contabilidad y software vertical (construcción, proyectos, RR. HH.)** | Sistemas contables, ERP empresariales o verticales donde clientes cargan facturas, costos de obra, recibos o formularios fiscales | Extracción estructurada de facturas, recibos, órdenes de compra, contratos, W-2/W-8/W-9 y tarjetas de presentación; enriquecimiento de proveedores e integración ERP | **Intuit, Sage, Buildertrend, Deltek, Rippling, DocuPhase** |

### 3.2. Vertical 2: CPG, Consumo Masivo y Loyalty Marketing (`cpg_loyalty`)

Grandes marcas de consumo masivo (alimentos, bebidas, cuidado personal, salud de consumo, licores) y las agencias/plataformas que operan sus programas promocionales y de lealtad (*B2B2C + B2B*):

| Subtipo de empresa | Qué hace la empresa | Flujo documental y productos de Veryfi | Empresas de referencia en los decks |
|---|---|---|---|
| **Grandes marcas CPG en LATAM (alimentos, bebidas, consumo masivo)** | Ejecutan promociones nacionales o programas de lealtad donde el consumidor sube fotos de tickets de supermercado/tienda, empaques con código impreso o tapas de botella para ganar premios o saldo (ej. recargas en Nequi, puntos en app o viajes) | `WhatsApp Bot` end-to-end o integrado a API/CRM, `Lens` (móvil/web para tickets, códigos y tapas), validación instantánea sin *clearing house* manual (de 7–11 días a segundos), `Product Intelligence` / `Product Lookup` (análisis de canasta cruzada a nivel SKU) y `Fraud Prevention` | **PepsiCo** (México y Colombia: *Joy App*, *Frito-Lay*, *Doritos*, *Sabritas*, *Gamesa*), **Grupo Bimbo** (México: *Bimboleto a París*), **Marinela** (México), **Nestlé** (*Nestlé Mayoreo*), **Meals de Colombia / CremHelado** (Grupo Nutresa), **Pastas Doria**, **Postobón**, **Coca-Cola**, **Colgate-Palmolive**, **Unilever**, **Diageo**, **Abbott**, **Lala**, **Yupi**, **Dunkin'** |
| **Agencias de marketing promocional, plataformas de lealtad e inteligencia del consumidor** | Diseñan, operan y auditan campañas de fidelización, *cashback* o paneles de recibos para múltiples marcas de consumo | Infraestructura white-label de captura (`Lens`), `WhatsApp Bot`, `OCR API`, reglas de negocio (`Rules Engine`) y enriquecimiento de SKUs | **Merkle** (*a dentsu company*), **AnnexCloud**, **Consumer Reports**, **Wecheer** |

### 3.3. Vertical 3: Automatización de Cuentas por Pagar (AP Automation) y Operaciones Corporativas

En `Sales Deck` (págs. 3 y 11) y `How Veryfi Sells` (págs. 10, 19–21, 30, 34), Veryfi destaca además **grandes corporaciones no-FinTech** que procesan altos volúmenes de documentos operativos, financieros o logísticos:

| Subtipo de empresa | Qué hace la empresa | Flujo documental y productos de Veryfi | Empresas de referencia en los decks |
|---|---|---|---|
| **Corporativos industriales, retail, manufactura y centros comerciales (*AP Automation*)** | Grandes empresas con alto volumen de proveedores, compras, mantenimiento, órdenes de compra (*POs*), facturas (*Bills*) y remisiones/cartas de porte (*BOL / Proof of Delivery*) | Extracción automatizada de facturas, órdenes de compra y guías de despacho; conciliación (*3-way matching*), reglas de negocio, detección de duplicados/fraude e integración con ERP | **Volvo, The Home Depot, Andersen Windows & Doors, Vicinity Centres, SquareWorks Consulting** |
| **Otros verticales del SAM documentados por Veryfi** | Salud (*Healthcare*: reclamaciones médicas, registros, remisiones), Cadena de suministro (*Supply Chain*: *Bill of Lading*, *Proof of Delivery*), Telecomunicaciones (bitácoras de mantenimiento/conductores), Hotelería (*Hotel Folios*) | `APIs Specialized` y `AnyDocs`, captura móvil en campo (`Lens`) y antifraude documental | Verticales definidos en el mapa SAM (`How Veryfi Sells`, págs. 10, 19–21, 34) |

---

## 4. Descripción de la rúbrica para empresas grandes (`rubric_v2` — T13 y T14)

### 4.1. Cambio de enfoque respecto a `rubric_v1`

La rúbrica inicial (`rubric_v1`) fue diseñada para el MVP general y asignaba solo **20 puntos** a la escala. Dado que Veryfi solicitó enfocar la prospección en **empresas más grandes** (equivalentes a sus clientes *Tier 1* y *Tier 2*), la hipótesis de `rubric_v2` (T14) eleva el peso de la escala a **35 puntos**, manteniendo candados estrictos para que el tamaño nunca sustituya la necesidad documental:

| Criterio (`id`) | Peso en `rubric_v1` | Peso propuesto en `rubric_v2` (hipótesis T14) | Propósito del ajuste |
|---|---:|---:|---|
| **Necesidad documental / validación (`document_need`)** | 35 | **30** | Sigue siendo condición obligatoria: la empresa debe recibir, capturar o validar comprobantes (recibos, facturas, tickets, códigos/tapas, POs/BOLs). |
| **Correspondencia con la oferta (`offer_match`)** | 25 | **20** | Evalúa qué tan directo es el encaje con los productos de Veryfi (`OCR API`, `Lens`, `WhatsApp Bot`, `Fraud Prevention`, `Product Intelligence`). |
| **Escala / potencial enterprise (`scale_potential`)** | 20 | **35** | **Criterio diferenciador enterprise:** prioriza cuentas *Tier 1* y *Tier 2* por empleados, ingresos, volumen transaccional/documental, presencia multimarca o alcance regional en CO/MX. |
| **Capacidad de adopción (`adoption_capacity`)** | 10 | **10** | Evalúa si cuenta con los canales o la infraestructura para integrar Veryfi (app/web/API propia en FinTech; canales digitales/WhatsApp o agencia en CPG; ERP en corporativos). |
| **Momento de oportunidad (`opportunity_timing`)** | 10 | **5** | Señal complementaria (campaña promocional activa, expansión en LATAM, lanzamiento de producto o digitalización de AP). |
| **Total** | **100** | **100** | `null` no equivale a `0`; los criterios sin evidencia quedan en `null` y reducen `coverage`. |

### 4.2. Guía de calificación por criterio en `rubric_v2`

#### 1. `scale_potential` (Peso: 35) — Calibrado con los Customer Tiers de Veryfi
- **`1.0` (Señal fuerte — Escala Enterprise / Tier 1 o Tier 2 consolidado):**
  - **FinTech / Software:** evidencia con fuente de **≥ 250 empleados** (o rango *Tier 2/Tier 1* de 100 a >1.000 empleados acompañado de funding ≥ USD 25M, ingresos ≥ USD 100M o base masiva de clientes empresariales B2B2B en CO/MX/LATAM, comparable a *Navan, Brex, Ramp, Zoho, Intuit, Square, Razorpay*).
  - **CPG / Fidelización:** grupo o marca líder de consumo masivo con operación nacional o multinacional en Colombia y/o México, portafolio multimarca, distribución masiva en supermercados/canal tradicional o ingresos equivalentes a *Tier 1/Tier 2* (≥ USD 100M–1B+, o plantilla ≥ 250–1.000+ empleados, comparable a *PepsiCo, Bimbo, Nestlé, Postobón, Grupo Nutresa/Meals/Doria, Lala, Colgate, Unilever, Diageo*). En agencias/plataformas, operación para múltiples marcas enterprise (comparable a *Merkle* o *AnnexCloud*).
- **`0.5` (Señal parcial — Escala Media / Tier 2 en crecimiento o filial acotada):**
  - **FinTech / Software:** entre **50 y 249 empleados** (o startup serie A/B con tracción regional comprobada pero sin evidenciar aún escala de >100–250 empleados o >USD 25M de funding).
  - **CPG / Fidelización:** marca regional o mediana (50–249 empleados) con presencia comercial comprobada en varios departamentos/estados o cadenas de retail, pero sin escala multinacional/nacional masiva.
- **`0.0` (Incompatible):**
  - Evidencia explícita de microempresa o negocio local sin volumen documental ni capacidad para sostener un caso de uso B2B/B2B2C de escala (< 50 empleados sin plataforma multiplicadora).
- **`null` (Desconocido):**
  - No existe cifra de empleados, ingresos, financiación ni evidencia de escala operativa con fuente y ámbito (matriz, filial o país). **No se inventan rangos ni se asume tamaño por notoriedad de marca sin fuente.**

#### 2. `document_need` (Peso: 30) — Basado en los flujos documentales de los decks
- **`1.0` (Señal fuerte):**
  - **FinTech / Software:** el producto recibe o procesa explícitamente comprobantes subidos por usuarios o empresas (captura de recibos de gastos, facturas de proveedores para *Bill Pay* o *AP*, estados de cuenta para conciliación, formularios o documentos de onboarding/KYC).
  - **CPG / Fidelización:** la marca o agencia ejecuta promociones o programas de lealtad que solicitan al consumidor registrar **tickets/facturas de compra, códigos impresos en empaques o códigos en tapas** (vía WhatsApp, web o app móvil), o requiere validar compras en retail multimarca.
  - **AP Automation corporativo:** evidencia primaria de portal de proveedores, recepción masiva de facturas/órdenes de compra/remisiones (*PO/BOL/Invoice*) o iniciativa explícita de automatización de cuentas por pagar/recepción documental.
- **`0.5` (Señal parcial):**
  - **FinTech / Software:** plataforma de gastos, pagos corporativos, ERP o contabilidad cuyo flujo es compatible con recepción de comprobantes, pero la evidencia solo confirma emisión de facturas electrónicas propias o conciliación bancaria sin detallar captura de documentos de terceros.
  - **CPG / Fidelización:** marca de consumo masivo con programas promocionales, *trade marketing* o dinámicas digitales frecuentes al consumidor, sin que la fuente extraída detalle aún el envío de ticket o código de empaque.
- **`0.0` (Incompatible):**
  - Evidencia explícita de que el modelo de negocio no involucra documentos, comprobantes, facturas de terceros ni dinámicas promocionales de compra.
- **`null` (Desconocido):**
  - Evidencia insuficiente sobre el producto o las campañas de la empresa.

#### 3. `offer_match` (Peso: 20) — Correspondencia con el catálogo de Veryfi
- **`1.0` (Señal fuerte):**
  - El problema observado conecta directamente con al menos una solución específica de Veryfi demostrada en los decks:
    - Captura móvil/web (`lens`) + extracción estructurada (`document_ocr_api`) para apps FinTech/ERP.
    - `loyalty_whatsapp` (`WhatsApp Bot`) + `validation_enrichment` (`Product Intelligence` / *cross-basket insights*) + `antifraud` para promociones CPG en LATAM.
    - Prevención de fraude *upstream* (`antifraud`: detección de duplicados, edición digital o imágenes generadas por IA) en reembolsos, *bill pay* o promociones.
- **`0.5` (Señal parcial):**
  - Encaje plausible con una capacidad de Veryfi, pero falta confirmar si el flujo requiere captura de documentos no estructurados o si opera únicamente con facturación electrónica estructurada XML sin imagen/PDF ni captura en campo.
- **`0.0` / `null`:**
  - `0.0` si busca una solución ajena a Veryfi (p. ej. pasarela de cobro pura o CRM de ventas salientes); `null` si no hay base para determinarlo.

#### 4. `adoption_capacity` (Peso: 10)
- **`1.0`:**
  - En **FinTech/Software**: cuenta con app móvil (iOS/Android), plataforma web, API para desarrolladores o integraciones ERP donde embeber el SDK de *Lens* o consumir la API JSON en <3 segundos.
  - En **CPG/Fidelización**: cuenta con canal oficial de WhatsApp, sitio web promocional/PWA, app de lealtad (ej. *Joy*) o trabaja con agencia digital/CRM integrable (Veryfi ofrece además solución *turnkey end-to-end* de WhatsApp Bot sin exigir equipo móvil propio a la marca).
- **`0.5`:** infraestructura digital básica comprobada, sin detalle del canal de integración.

#### 5. `opportunity_timing` (Peso: 5)
- **`1.0`:** promoción o campaña de fidelización vigente/reciente en CO/MX, lanzamiento de módulo de gastos/cuentas por pagar, expansión regional o búsqueda activa de perfiles en el área del caso de uso.
- **`0.5`:** actividad comercial o digital reciente sin calendario explícito.

### 4.3. Reglas de corte (evitar falsos positivos por tamaño)

Para cumplir los criterios de aceptación de **T14**:
1. **Un gran conglomerado sin caso de uso no recibe prioridad alta:** para `high`, siguen siendo obligatorios `document_need == 1.0` respaldado por fuente primaria, `offer_match >= 0.5`, `coverage >= 0.75` y `fit_score >= 75`. Una empresa con `scale_potential = 1.0` (35 puntos) pero `document_need = 0.5` o sin fuente primaria nunca alcanza `high`.
2. **Separación de matriz, filial y marca (T13):** cada señal de escala (`empleados`, `ingresos`, `presencia`) debe conservar su ámbito (`group`, `entity`, `country`). No se atribuyen los empleados globales de una multinacional a una filial local sin indicar que el dato corresponde al grupo matriz.

---

## 5. Descripción de la rúbrica para la clasificación de personas (`contact_match_v2` y T15)

### 5.1. Roles del ICP Enterprise según Veryfi (`How Veryfi Sells`, págs. 6, 9 y 18)

Los documentos de Veryfi distinguen tres funciones en la decisión de compra y señalan que los cargos cambian según el vertical y el tamaño de la empresa:

| Rol en la compra (`buying_role`) | FinTech y Software Enterprise (`fintech_software`) | CPG y Fidelización Enterprise (`cpg_loyalty`) | AP Automation / Corporativos |
|---|---|---|---|
| **Promotor de negocio (`business_champion` / `NT`)** | **Product Manager, Senior/Group PM, Head of Product, Director of Product, VP of Product** *(evalúan encaje de producto, experiencia de usuario y presupuesto del área)* | **Marketing Director, Brand Manager / Gerente de Marca, Loyalty / CRM Manager, Trade / Shopper Marketing Manager, Digital Marketing Manager** *(dueños del presupuesto de campañas y retención)* | **Accounts Payable (AP) Manager/Lead, Financial Operations Director, Shared Services / CSC Director, Supply Chain / Logistics Operations Lead** |
| **Promotor técnico / de datos (`technical_champion` / `T`)** | **Engineering Director, Engineering Manager, VP of Engineering, CTO, Principal / Lead Software Engineer, Solutions Architect** *(tienen gran influencia en la decisión al evaluar precisión OCR, latencia <3s y facilidad de integración del SDK/API)* | **Consumer Insights / Shopper Insights Manager, Analytics / BI Manager, Marketing Technology (MarTech) Lead, IT / Digital Transformation Manager** *(evalúan datos de canasta cruzada a nivel SKU e integración con CRM/data warehouse)* | **IT Director, ERP / Financial Systems Manager, Enterprise Architect, Automation / RPA Lead** |
| **Comprador económico / Decisor (`economic_buyer` / `EB`)** | **CEO** *(crecimiento de ingresos/upsell)*, **CFO / CRO** *(reducción de riesgo/fraude y costos de proveedores)*, **CIO / CDO** *(mejora de servicio, time-to-market y reducción de carga operativa)*, **Procurement / Compras** *(negociación contractual en Enterprise)* | **CMO / VP de Marketing**, **Director Comercial / General Manager**, **Procurement / Compras de Marketing** | **CFO, VP of Finance, Director de Compras / Procurement, COO** |

> **Regla crítica de selección (`Project-context.md` y T15):**
> - En cuentas enterprise se busca **diversidad de funciones** (objetivo experimental de T16: 3 a 5 personas pertinentes por cuenta, cubriendo al menos dos funciones cuando existan resultados, por ejemplo un *Promotor de negocio* y un *Promotor técnico*).
> - **Compras (`Procurement`)** interviene en la etapa contractual de cuentas Enterprise, pero para abrir la oportunidad (*Outbound SDR / Hunter*, pág. 6) tienen prioridad los **Champions de Producto, Ingeniería, Marketing/Loyalty, Insights o AP/Operaciones** que sufren el problema documental.
> - Un título ejecutivo genérico (ej. *VP* o *Director* de un área ajena como Legal, RR. HH. general o Ventas institucionales) **no** debe dominar el ranking solo por su jerarquía (*seniority*).

### 5.2. Pesos propuestos en `contact_match_v2` (hipótesis T19)

Frente a `contact_match_v1` (Cargo 50, Canal 25, Identidad 15, Empleo 10), la transición a cuentas enterprise con múltiples candidatos de Apollo requiere dar mayor peso a la **vigencia comprobada del empleo** para evitar contactar personas que ya cambiaron de puesto o de empresa:

| Componente | Peso en `contact_match_v1` | Peso propuesto en `contact_match_v2` (T19) | Criterio de evaluación |
|---|---:|---:|---|
| **Pertinencia del cargo (`role`)** | 50 | **40** | Nivel máximo si el cargo y departamento coinciden con los cargos prioritarios elegidos para el caso de uso de la empresa (`selected_role`); intermedio si pertenece al catálogo del segmento (`profile_role`, p. ej. otro rol complementario NT/T/EB del mismo vertical); `0` si la función está fuera del perfil (`outside_profile`, aunque tenga alto *seniority*) o está sin fuente (`unknown`). |
| **Vigencia del empleo (`employment`)** | 10 | **25** | Nivel máximo con evidencia corporativa o pública fechada vigente (`corporate_evidence` / `evidence`); nivel intermedio solo para señales históricas o declaradas sujetas a confirmación según T18; `0` si no está verificado (`unverified`). Si el empleo terminó (`employment_ended`), la persona queda bloqueada y pasa al final. |
| **Calidad del canal (`channel`)** | 25 | **20** | Nivel máximo con canal preferido utilizable (correo corporativo del dominio confirmado y verificado, teléfono directo o WhatsApp profesional anunciado); intermedio con canal alternativo confirmado (ej. LinkedIn con mensajería confirmada por ventas); menor para canales pendientes de confirmación; `0` sin canal o inválido. |
| **Identidad (`identity`)** | 15 | **15** | Nivel máximo con nombre completo e identidad confirmada en la entidad; intermedio con nombre completo pendiente de contraste; `0` si Apollo Search devolvió apellido ofuscado (`last_name_obfuscated`) aún no enriquecido. |
| **Total** | **100** | **100** | El puntaje ordena la revisión para ventas; **no convierte en `listo` un contacto sin canal o sin empleo verificado**. |

### 5.3. Uso de los perfiles reales de ejemplo enviados por Veryfi

Los perfiles reales de LinkedIn compartidos por Veryfi como ejemplos para perfeccionar la clasificación de personas se registran y actualizan en:

- **Archivo local (fuera de Git):** `data/veryfi-reference-profiles.md`

Cada vez que Veryfi envíe más enlaces de perfiles:
1. Se añaden a `data/veryfi-reference-profiles.md` (que actualmente contiene los primeros 3 perfiles recibidos el `2026-11-01`).
2. De cada perfil se identifican manualmente: **segmento de la empresa**, **cargo exacto (ES/EN)**, **departamento**, **nivel de jerarquía (*seniority*)** y **rol en la compra (`business_champion`, `technical_champion` o `economic_buyer`)**.
3. Esos patrones (sin nombres propios ni URLs personales) se incorporan al catálogo de `config/veryfi.json` (T15) y a los casos de prueba de `contact_match_v2` (T19) para asegurar que perfiles equivalentes reciban la máxima puntuación de pertinencia de cargo.
