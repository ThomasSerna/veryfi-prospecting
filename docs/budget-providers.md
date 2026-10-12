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
`timeout_seconds`, positivo y finito: 10 segundos por defecto; Hunter Verifier
usa 25 segundos para permitir su procesamiento de hasta 20 segundos.
Descuenta del tiempo restante el empleado
en la preparación y reclamación. Ese timeout no garantiza un plazo absoluto para
DNS o toda la llamada. El cliente no descarga páginas arbitrarias. Los adaptadores
`prospecting/providers/tavily.py` y `prospecting/providers/hunter.py` habilitan únicamente
las operaciones explícitas de lectura; la pantalla no inicia llamadas automáticamente.

Las claves se leen únicamente de variables de entorno al ejecutar una operación:
`TAVILY_API_KEY`, `ANTHROPIC_API_KEY`, `APOLLO_API_KEY` y `HUNTER_API_KEY`.
No se carga `.env` automáticamente. Una clave presente no autoriza gasto.
No hay envío comercial, recargas, waterfall ni enriquecimiento móvil de pago.

`Usage` identifica y contabiliza solicitudes, pero no almacena cuerpos HTTP.
Los éxitos repetidos se bloquean para recuperar su resultado guardado; si falta
ese resultado, requieren revisión. Un segundo intento necesita conciliación,
fallo transitorio identificado por el adaptador y otra reserva; después de un
reinicio no se deduce transitoriedad del mensaje guardado.

## Consumo y respuestas de Hunter

`HunterAccess` (`prospecting/providers/hunter.py`) registra operaciones disponibles, fecha y referencia de la
comprobación, financiación y la referencia canónica de cada saldo real. Sus
referencias `search_account_ref` y `verification_account_ref` se utilizan como
`account_ref` del ledger y de los permisos, sin enviarse a Hunter.
Domain Search y Finder comparten el mismo saldo de búsqueda. En una cuenta con
créditos unificados también lo comparte Verifier; en una cuenta con cuotas
separadas, el saldo de verificación tiene otra referencia y otro `AccountAllowance`.
No crear alias o cupos por operación para un mismo saldo, ni sumar búsquedas y
verificaciones de cuotas independientes como si fueran créditos intercambiables.

Las cotas documentadas son 1 crédito para Domain Search con hasta 10 resultados y
1 para Finder. El cobro por llamada de Domain Search se comprobó con la cuenta real el
2026-10-12: una consulta con 3 correos costó 1 crédito, aunque la página de precios
mencione un crédito por correo (véase `docs/provider-check.md`). Verifier reserva 0,5 créditos unificados o 1 crédito de su cuota
separada, según la cuenta comprobada. Finder incluye la verificación del correo
encontrado. Estos valores no comprueban acceso ni saldo en la cuenta del equipo;
el origen y la valoración económica deben quedar acreditados antes del gasto.
Consulta la [referencia de consumo de la API](https://help.hunter.io/en/articles/1970956-hunter-api)
y la [distinción entre créditos de verificación](https://help.hunter.io/en/articles/1935055-how-many-credits-are-used-to-verify-an-email).

No asumir consumo exacto por obtener resultados: las reservas y estimaciones se
mantienen hasta conciliación con un comprobante del proveedor. Un resultado vacío
o una verificación desconocida tampoco autorizan liberar importes sin confirmar.

Para `hunter/email_verifier`, HTTP 202 conserva `Usage` como `uncertain`, con
`outcome="unknown"`, y el saldo reservado. Un cuerpo 202 inválido también mantiene
esa incertidumbre. No hay polling ni reenvío automático: el candidato queda
pendiente. HTTP 222 se trata como fallo aunque pertenezca al rango 2xx. El mensaje
de `errors[]` conserva `id`, `code` y `details` después de omitir claves, entradas
sensibles, correos, números y URLs; no se guarda el cuerpo HTTP.

Finder y Verifier solo pueden habilitarse tras comprobar que el guardado automático
de leads está desactivado en la cuenta. El
[OpenAPI oficial de Hunter](https://hunter.io/openapi.json) describe ese efecto y
su desactivación a nivel de cuenta; no se supone un parámetro de petición para
desactivarlo. La comprobación de acceso no cambia ajustes de la cuenta desde el código.
