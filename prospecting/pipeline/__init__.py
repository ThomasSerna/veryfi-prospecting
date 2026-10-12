"""Orquestación mínima: único paquete que reserva gasto y llama a proveedores.

Ninguna transacción queda abierta durante una llamada de red. Tavily solo se usa con
crédito gratuito y Haiku con su precio publicado: sin un precio acotado no hay llamada (§14).
Cada etapa vive en su módulo y guarda su propio checkpoint.
"""

from prospecting.pipeline.campaign import (
    AuthorizationInput, CampaignReport, CampaignView, CompanyProgress, CompanyResult, ContactResult, ProviderAccess,
    close_campaign, confirm_alternative_channel, execute_campaign, finish_campaign, list_saved_campaigns,
    load_provider_access, prepare_campaign, provider_operations, read_campaign, review_company, run_campaign,
    start_campaign,
)
from prospecting.pipeline.contacts import ContactReport, find_contacts
from prospecting.pipeline.discovery import (
    DiscoveryReport, ExcludedCandidate, IdentityReport, QueryOutcome, resolve_company_identity, run_discovery,
)
from prospecting.pipeline.qualification import QualificationReport, qualify_company
from prospecting.pipeline.research import (
    ExtractReport, ResearchReport, UrlFailure, extract_company_pages, research_company,
)

__all__ = [
    "AuthorizationInput", "CampaignReport", "CampaignView", "CompanyProgress", "CompanyResult", "ContactResult",
    "ProviderAccess", "ContactReport", "DiscoveryReport", "ExcludedCandidate", "ExtractReport",
    "IdentityReport", "QualificationReport", "QueryOutcome", "ResearchReport", "UrlFailure", "close_campaign",
    "extract_company_pages", "find_contacts", "qualify_company", "research_company", "resolve_company_identity",
    "run_campaign", "run_discovery", "start_campaign", "confirm_alternative_channel", "execute_campaign",
    "finish_campaign", "list_saved_campaigns", "load_provider_access", "prepare_campaign", "provider_operations",
    "read_campaign", "review_company",
]
