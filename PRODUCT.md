# Veryfi Prospecting

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Equipo de ventas de Veryfi: revisa posibles clientes en Latinoamérica, entiende
el caso de uso y decide qué empresas y personas investigar o contactar fuera de la aplicación.

## Product Purpose

Descubrir empresas desde criterios de mercado, calificarlas con evidencia
y encontrar personas pertinentes con canales directos comprobados.
El encaje es una rúbrica explicable, no una probabilidad de compra.

## Operating Context

Servicio Django local en un solo equipo y proceso, sin autenticación ni despliegue.
La investigación continúa al cerrar la pestaña mientras el servidor esté abierto.
El pipeline y SQLite existentes conservan las reglas, resultados, checkpoints y gasto.

## Capabilities and Constraints

- Preparación, historial, investigación, filtros, presupuesto, fichas, revisión y CSV.
- Cada ejecución requiere aprobación nueva por operación, cuenta y tope.
- La aplicación no envía mensajes; ventas contacta fuera de ella.
- Los datos desconocidos permanecen pendientes. Los detalles y la procedencia son consultables.
- Los datos reales y las claves permanecen fuera de Git; las demostraciones son sintéticas.

## Brand Commitments

Veryfi, su logotipo oficial y su guía de marca: https://www.veryfi.com/brand/.
Redacción en español comprensible para ventas, con los detalles técnicos en segundo nivel.

## Evidence on Hand

Los contratos y requisitos están en prospecting/ y docs/IDEA.md.
Las pruebas contienen empresas y contactos explícitamente sintéticos.
El catálogo y las reglas comerciales son provisionales; no presentar validación comercial inventada.

## Product Principles

- La evidencia explica cada oportunidad y cada pendiente.
- Preparar y consultar no consumen proveedores.
- Disponibilidad del contacto y revisión de ventas son decisiones independientes.
- La interfaz conserva el detalle sin exigir conocimientos de programación.
