# Pruebas de software mínimas

Pruebas que protegen las reglas críticas del proyecto. Forma parte de la documentación de requisitos: ver el [índice](IDEA.md).

Pruebas unitarias/integración sin red por defecto; llamadas reales separadas y explícitas en una sesión con presupuesto.

| Riesgo | Prueba significativa |
|---|---|
| Puntuación engañosa | Desconocido no equivale a cero; ejemplo 88,9/90 %; 100 con cobertura 20 % no pasa |
| Mal uso del presupuesto | Dos intentos de reservar no exceden cupo; sin saldo no hay llamada; timeout conserva reserva |
| Identidad incorrecta | Homónimos, ex-empleado, marca/filial y país no se confunden |
| Prospecto sin canal útil | Perfil URL, central genérica, email inventado/invalid y `accept_all` sin respaldo no pasan |
| Canal alternativo | LinkedIn solo pasa a listo tras confirmación manual; no envía mensajes |
| Datos incompletos | Resultado vacío, nombre parcial y evidencia contradictoria producen pendiente |
| Fallos de proveedor | Permiso denegado, cuota, timeout y JSON inválido conservan etapa y motivo |
| Clics repetidos/reinicio | Repetir clic, reenviar el formulario o reanudar no repite pasos confirmados ni borra el gasto |
| Entrada hostil | Texto de página que pide enviar datos, subir presupuesto o cambiar reglas no altera el flujo |
| Salida/URL insegura | CSV no ejecuta fórmulas; rutas privadas/redirects y HTML arbitrario son rechazados |
| Trazabilidad | Referencias de modelo inexistentes se rechazan; la ficha conserva evidencia al exportar |
| Reorganización altera datos guardados | Huellas, claves de `attempts`, `identity_key`, ids deterministas, textos de resultado de buscador y esquema SQLite no cambian al mover código |
| Dependencias invertidas | Los módulos de negocio no importan `db`, `budget`, `providers` ni `pipeline`; las importaciones no forman ciclos |

## Dónde están y cómo ejecutarlas

- Las pruebas viven en `tests/`. Bloquean conexiones externas y usan datos sintéticos y bases temporales; los comandos están en «Verificación» de [README.md](../README.md#verificación).
- `tests/test_architecture.py` comprueba la dirección de las importaciones, las capacidades prohibidas y que el árbol de [Architecture.md](Architecture.md#estructura-de-carpetas) describa exactamente los módulos del paquete.
- `tests/test_persisted_identifiers.py` fija los identificadores guardados en SQLite ([persistence.md](persistence.md#identificadores-persistidos)).
- [evaluation.md](evaluation.md) relaciona cada riesgo con sus pruebas representativas y con los resultados de los lotes reales.
