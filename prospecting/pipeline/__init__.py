"""Orquestación mínima: único paquete que reserva gasto y llama a proveedores.

Ninguna transacción queda abierta durante una llamada de red. Tavily solo se usa con
crédito gratuito y Haiku con su precio publicado: sin un precio acotado no hay llamada (§14).
Cada etapa vive en su módulo y guarda su propio checkpoint.
"""

from prospecting.pipeline.contacts import ContactReport, find_contacts
from prospecting.pipeline.discovery import (
    DiscoveryReport, ExcludedCandidate, IdentityReport, QueryOutcome, resolve_company_identity, run_discovery,
)
from prospecting.pipeline.qualification import QualificationReport, qualify_company
from prospecting.pipeline.research import ExtractReport, UrlFailure, extract_company_pages

__all__ = [
    "ContactReport", "DiscoveryReport", "ExcludedCandidate", "ExtractReport", "IdentityReport",
    "QualificationReport", "QueryOutcome", "UrlFailure", "extract_company_pages", "find_contacts",
    "qualify_company", "resolve_company_identity", "run_discovery",
]
