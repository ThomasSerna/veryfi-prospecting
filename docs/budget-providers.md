# Presupuesto y cliente de proveedores

`Budget(db, global_limits, account_allowances)` reutiliza la misma base SQLite y
los límites de la configuración. Cada instancia representa una sesión y comienza
sin permisos. Sus métodos `reserve`, `claim`, `begin_send`, `record_result` y
`reconcile` ejecutan transacciones breves propias; no deben llamarse dentro de
`db.transaction()`. `snapshot` muestra importes confirmados, estimados, reservados,
pendientes y disponibles, distinguiendo desconocidos y excesos.

El máximo global es USD 20 y las llamadas automáticas se limitan a USD 15. El
margen de USD 5 no habilita llamadas adicionales. El límite por campaña es USD 2
y el de USD 0,25 por empresa acumula todas sus campañas. Una reserva que supera algún
límite se rechaza con `budget_exceeded`, o con `company_budget_exceeded` si el único
superado es el de la empresa. Las reducciones guardadas en una campaña se respetan.
La distribución IA/web/contactos es orientativa.

Los cupos se proporcionan como objetos `AccountAllowance` validados, con
`provider`, `account_ref`, `funding_source`, `credit_limit`, `cost_limit_usd`,
`source_reference` y `observed_at`. Guarda esa configuración local bajo `data/`,
fuera de Git: los módulos no crean ni cargan automáticamente ese archivo.
Los cupos representan el saldo inicial asignado al registro completo del sprint;
siempre se resta todo el historial, sin renovar cuota por fecha o reinicio.
Una consulta posterior de saldo restante no sustituye ese saldo inicial.
Cada saldo real debe tener una referencia canónica y un único cupo por proveedor
y cuenta. Las configuraciones duplicadas se rechazan, incluso con distintos
orígenes de financiación; cambiar de origen conserva el consumo de toda la cuenta.
El responsable debe identificar los alias que correspondan al mismo saldo.

El crédito gratuito acreditado se imputa como USD 0, pero consume su cupo de créditos.
El prepago cuenta por su costo económico y no vuelve a contar como desembolso.
Los cobros nuevos se registran aparte sin duplicarlos en el acumulado. Cada
llamada utiliza un solo origen; no hay recargas ni mezcla automática de saldos.
Los valores necesarios desconocidos bloquean el envío.

El campo opcional `AccountAllowance.credit_valuation` recibe `CreditValuation`
con `unit_value_usd`, `source_reference` y `observed_at`. Conserva esa valoración
de referencia fija del sprint bajo `data/` y reutilízala al reabrir la base;
los módulos no consultan precios ni guardan la valoración automáticamente.
`snapshot().free_credit_equivalent` muestra el equivalente económico de créditos
gratuitos confirmado, estimado, reservado y pendiente. Si falta la valoración,
la cuenta atribuible o el consumo necesario, queda desconocido. Es informativo:
no se suma al gasto imputable ni modifica las reservas o los topes monetarios.

Cada reserva y reclamación exige `SpendingAuthorization`: proveedor, operación,
cuenta, topes de dinero/créditos, responsable, referencia y fecha del permiso.
Después de la aprobación humana explícita, el llamador registra el permiso con
`budget.authorize(authorization)`. Su fecha debe ser posterior a la creación de
esa instancia y no futura. Los permisos antiguos, no registrados o con topes
alterados se rechazan; construir el objeto no sustituye la aprobación humana.
Los topes se aplican al consumo acumulado de las solicitudes vinculadas al permiso.
Conservar la instancia durante reruns conserva la sesión; crear otra exige un
permiso nuevo. Este puede reclamar una reserva antigua todavía `reserved`,
contándola una sola vez, sin cambiar su identificador, fecha ni historial.

`claim` cambia una reserva a `in_flight` de manera exclusiva, antes de la red.
`begin_send` debe ejecutarse inmediatamente antes del transporte: consume la
prueba en memoria de que esa reclamación todavía no inició una llamada.
`record_result` guarda el resultado técnico y consumo observado. Si vence el
plazo antes del transporte, el cliente registra `failed` y consumo observado cero
con `no_send=True`. Conserva las reservas hasta una conciliación explícita con
`Confirmation(no_send=True)` y costo, créditos y desembolso cero.
Un timeout o error después de iniciar el transporte conserva la reserva y no puede
usar esa prueba de no envío. La prueba se pierde al reconstruir `Budget` antes de
conciliar; el caso queda pendiente de confirmación del consumo. Al reabrir, una
solicitud `in_flight` no se reenvía. `reconcile` recibe una `Confirmation` con
consumo confirmado, referencia y fecha: libera únicamente la diferencia acreditada
y conserva el importe de la reserva original. Un cargo inesperado se registra y
bloquea nuevas llamadas.

El contrato persistido conserva cuenta, importes y fechas, pero no el texto de la
referencia del comprobante de conciliación. El responsable debe conservar los
comprobantes y la configuración financiera bajo `data/`; el módulo no los archiva
automáticamente. No borres la base ni sus archivos auxiliares para liberar saldo.

`ProviderClient` recibe descriptores `OperationSpec` definidos por código para
operaciones explícitas y un transporte opcional para pruebas.
`fingerprint` calcula una huella SHA-256 sin autenticación.
`request_json` exige reserva persistida y autorización, ejecuta un solo intento y
devuelve `ProviderResult` con un modelo Pydantic validado, `observation` y
`http_status` (200 por defecto para resultados anteriores). Devuelve errores tipados
para fallos locales, HTTP, transporte, timeout, formato y tamaño; las claves y
entradas sensibles se omiten de los mensajes. No interpreta permisos o cuota con
una tabla HTTP universal ni reintenta automáticamente.

El transporte estándar utiliza HTTPS verificado, un opener privado sin proxies
heredados ni redirecciones y respuesta máxima de 1 MiB. Cada descriptor fija
`timeout_seconds`, positivo y finito: 10 segundos por defecto.
Descuenta del tiempo restante el empleado
en la preparación y reclamación. Ese timeout no garantiza un plazo absoluto para
DNS o toda la llamada. El cliente no descarga páginas arbitrarias. Los adaptadores
`prospecting/providers/tavily.py` y `prospecting/providers/apollo.py` habilitan únicamente
las operaciones explícitas de lectura; la pantalla no inicia llamadas automáticamente.

Las claves se leen únicamente de variables de entorno antes o durante la ejecución:
`TAVILY_API_KEY`, `ANTHROPIC_API_KEY` y `APOLLO_API_KEY`.
No se carga `.env` automáticamente. Una clave presente no autoriza gasto.
No hay envío comercial, recargas, waterfall ni enriquecimiento móvil de pago.

`Usage` identifica y contabiliza solicitudes, pero no almacena cuerpos HTTP.
Los éxitos repetidos se bloquean para recuperar su resultado guardado; si falta
ese resultado, requieren revisión. Un segundo intento necesita conciliación,
fallo transitorio identificado por el adaptador y otra reserva; después de un
reinicio no se deduce transitoriedad del mensaje guardado. La única prueba persistida
que admite repetir en otra ejecución es una conciliación humana como fallida y sin
consumo (`unconsumed_failure`: créditos, costo y desembolso en cero). Con un permiso
nuevo, la etapa de contactos la repite una sola vez con `retry_of`, sin ocupar otro
intento del nivel de esfuerzo; un segundo fallo ya no se repite.

Los permisos de una misma cuenta se suman antes de ejecutar (`_approve`): Search y
Enrichment de Apollo, o Search y Extract de Tavily, no pueden prometer juntos más
créditos que los disponibles en la cuenta. `RequestLimit` limita las solicitudes por
operación y cuenta en ventanas deslizantes de minuto, hora y día contadas en el ledger
(`Budget.limit_requests`); se comprueba al reservar, reclamar e iniciar el envío, así
que también acota a otra conexión sobre la misma base. Al alcanzarlo, `local_rate_limit`
detiene la pasada sin reservar ni enviar.

## Consumo y respuestas de Apollo

`ApolloAccess` (`prospecting/providers/apollo.py`) registra las operaciones
comprobadas, cuenta, financiación, plan, fecha, referencia y condiciones de acceso.
La referencia de cuenta se usa en el ledger y los permisos; no se envía a Apollo.
La configuración no sustituye `AccountAllowance` ni la autorización explícita de
cada operación en la sesión de ejecución.

Para una cuenta cuyas condiciones se hayan comprobado, People API Search tiene
cota de cero créditos y People Enrichment reserva un crédito por persona. El
adaptador actual admite el plan Free. Antes de ejecutar, verificar disponibilidad,
cuotas, condiciones y facturación de la cuenta; el plan declarado o una clave
presente no bastan. La aplicación bloquea la campaña si falta una clave con formato
HTTP válido, el cupo de esa cuenta es desconocido o queda menos de un crédito tras
descontar consumo y reservas. La
[documentación oficial de créditos](https://docs.apollo.io/docs/api-pricing) explica
el consumo general; el [registro de proveedores](provider-check.md) informa qué
se ha comprobado en la cuenta del equipo.

No asumir consumo exacto por obtener resultados: si Apollo no informa los créditos
observados del enriquecimiento, se mantiene la reserva pendiente hasta conciliar
con un comprobante. Search se registra con cero créditos según la cota documentada.
Un resultado vacío o un timeout tampoco autorizan liberar importes sin confirmar.
No hay reenvío automático. Los errores conservan etapa y motivo sin registrar claves
ni cuerpos HTTP. Las búsquedas y el enriquecimiento no solicitan emails personales,
teléfonos ni waterfall, y no escriben contactos en Apollo.

`ApolloAccess.rate_limits` guarda los límites de solicitudes del plan; por defecto,
los publicados para Free (`FREE_RATE_LIMITS`: 50 por minuto, 200 por hora y 600 por
día en Search y en Enrichment), que con plan `free` solo pueden hacerse más estrictos.
`require_apollo_access`, por el que pasa toda llamada a Apollo, los registra en el
`Budget` de la sesión. Cada fallo de Apollo tiene su motivo (`apollo_api_inaccessible`,
`apollo_invalid_input`, `apollo_timeout`, etc.; ver [Library-docs.md](Library-docs.md#apollo-personas-y-correos-profesionales))
y detiene la pasada de contactos; el código del cuerpo (`ProviderError.provider_code`)
y el `Retry-After` quedan en el mensaje persistido.

### Conciliación con el panel

La respuesta de Apollo no informa créditos. El responsable lee los créditos usados en
el panel (Settings > Billing and credits) antes y después del lote y guarda un
comprobante `apollo_reconciliation_v1` en `data/conciliaciones/`, fuera de Git:

```json
{"version": "apollo_reconciliation_v1", "provider": "apollo", "account_ref": "apollo-cuenta",
 "responsible": "Responsable del cupo",
 "panel_before": {"credits_used": "10", "observed_at": "2026-11-07T15:00:00Z", "source_reference": "Panel antes del lote"},
 "panel_after": {"credits_used": "11", "observed_at": "2026-11-07T15:30:00Z", "source_reference": "Panel después del lote"},
 "attribution": "inferred_from_total", "attribution_note": "El panel solo informa el total de la cuenta.",
 "external_credits": "0", "external_note": null,
 "requests": [{"request_id": "…", "operation": "people_enrichment", "outcome": "succeeded", "credits": "1", "no_send": false}]}
```

Los créditos de las solicitudes más los ajenos al ledger (`external_credits`, con
nota) deben sumar exactamente el salto del panel, y el comprobante debe cubrir todas
las solicitudes de la cuenta creadas entre las dos lecturas. Una atribución por fila
deducida del total (`inferred_from_total`) necesita nota.

```bash
uv run --locked python manage.py reconcile_usage data/conciliaciones/apollo-2026-11-07-t17.json --dry-run
```

Sin `--dry-run`, `reconcile_usage` concilia todas las filas en una transacción o
ninguna; repetir el comprobante no cambia nada y uno que contradiga lo ya conciliado
se rechaza. No crea la base, no llama a proveedores y se niega mientras haya una
investigación o una campaña `running`. Muestra solo la cuenta, conteos y créditos.

El ledger de Hunter es histórico: sus referencias, gastos y comprobantes se
conservan, pero no autorizan nuevas operaciones ni financian solicitudes de Apollo.
