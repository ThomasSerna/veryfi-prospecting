# Presupuesto y control de gasto

Política de gasto del proyecto: topes, distribución de la reserva y reglas de reserva y conciliación. Forma parte de la documentación de requisitos: ver el [índice](IDEA.md). La implementación (`Budget`, `SpendingAuthorization` y el cliente de proveedores) está en [budget-providers.md](budget-providers.md); lo comprobado con cuentas reales y su conciliación, en [provider-check.md](provider-check.md). Los costos de cada servicio están en [Library-docs.md](Library-docs.md).

**USD 20 es el máximo agregado del primer sprint, entre todos los desarrolladores, Haiku, datos, pruebas y ejecuciones. No es un cupo por agente, cuenta, empresa ni corrida.** No se autoriza comprar suscripciones ni recargar automáticamente por describir este plan.

Distribución de planificación, no cotización ni compra:

| Partida | Reserva máxima inicial |
|---|---:|
| Interpretación y clasificación con Haiku | USD 3 |
| Búsqueda/extracción web | USD 2 |
| Obtención/verificación de contactos | USD 10 |
| Margen para incertidumbre, errores o cargos adicionales | USD 5 |
| Total | USD 20 |

Priorizar créditos gratuitos. Si un proveedor exige una compra mínima que no cabe, usar otra vía; una reserva de USD 10 no implica que exista un plan comprable por ese valor. Las reservas pueden redistribuirse por decisión del equipo sin aumentar el total.

Implementación del control:

1. Contabilizar tanto créditos consumidos como costo económico estimado; distinguir crédito gratuito, saldo prepagado y nuevo desembolso. No contar dos veces compra y consumo del mismo saldo, pero tampoco ignorar consumo de una cuenta ya financiada.
2. Designar a una persona responsable del cupo compartido. Preferir que las pruebas reales salgan de una sola instancia/control de presupuesto; las demás usan fixtures. Bases independientes no coordinan por sí solas un límite global.
3. Antes de cada llamada, reservar una cota superior de costo y de créditos según la operación/configuración real. Para LLM incluir entrada, máximo de salida y tokens facturables adicionales aplicables.
4. Rechazar la llamada si gasto conciliado + reservas + nueva reserva supera el límite operativo. Limitar operación automática a USD 15, dejando USD 5 de margen hasta conciliación.
5. Conciliar con respuesta y saldo del proveedor. Mostrar estimado y confirmado por separado. Si no se puede acotar un precio, no habilitar esa operación pagada.
6. Mantener un límite inicial por campaña de USD 2 y por empresa de USD 0,25, siempre subordinados al acumulado global. El límite puede reducir cantidad de resultados; nunca se elimina para cumplir una cuota de prospectos.
7. Deshabilitar recargas, waterfall de costo variable y teléfonos enriquecidos de pago en el primer sprint. Usar topes del proveedor cuando estén disponibles.
8. Consolidar la autorización por cuenta (T17): los permisos de sesión de todas las operaciones de una misma cuenta (Apollo Search y Enrichment; Tavily Search y Extract) se suman antes de compararlos con el cupo disponible de esa cuenta, y el costo de todos los permisos se suma contra los topes global, operativo y de campaña. Cada proveedor mantiene su cuenta y su cupo: Apollo para personas, Tavily para la web y Haiku para interpretar.
9. Limitar las solicitudes antes de reservar, por operación y cuenta, con los límites del plan comprobado; para Apollo Free, 50 por minuto, 200 por hora y 600 por día [W2]. Se cuentan en el ledger con ventanas deslizantes. Al alcanzar el límite no se reserva ni se envía nada: la empresa queda pendiente y se reanuda más tarde.
10. Una llamada enviada sin resultado no se repite de forma automática. Solo se repite una vez, en otra ejecución con autorización nueva, después de que una persona la concilie con el panel como fallida y sin consumo.

Referencia de costos para comprender órdenes de magnitud, no garantizar facturas: Tavily publica 1.000 créditos gratuitos mensuales; una búsqueda básica usa uno [W1]. Haiku 5.5 publica USD 0,10/M tokens de entrada y USD 0,50/M de salida para prompts de hasta 100.000 tokens [W4]. Con esos supuestos, 100 consultas al límite de 9.000 tokens de entrada y 1.000 de salida serían USD 0,14 de inferencia, antes de otros consumos. El dato de contacto y la política de consulta pueden pesar más que la inferencia; medir el flujo completo.

El indicador de gasto de la aplicación es una estimación controlada, no reemplaza la facturación. Capturar consumo real al final de cada sesión de pruebas. Si un tercero cambia condiciones o falta acceso, detener y registrar la limitación.
