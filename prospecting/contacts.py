"""Reglas de personas, canales y condición de listo (§10), sin conocer la fuente; sin red ni persistencia.

Los proveedores y Haiku aportan datos: Python conserva procedencia, valida las
asociaciones y decide si hay un canal utilizable. Nunca se contacta a una persona.
Toda fuente de personas entrega `Contact`, `Channel` y `Evidence` y pasa por estas reglas (§11.3).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
from typing import Annotated, Literal, Self
import unicodedata
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, model_validator

from prospecting.models import (
    Assessment, BusinessStatus, Campaign, CampaignLimits, Channel, ChannelStatus, ChannelType,
    Company, Contact, Contract, Evidence, IdentityStatus, Priority, Text,
)
from prospecting.sources import is_search_evidence, url_host, within_domain


class ContactError(Exception):
    """Hecho no respaldado que deja el contacto pendiente, sin corregirlo con IA."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def contact_context(campaign: Campaign, contacts: list[Contact], evidence: list[Evidence]
                    ) -> tuple[list[Contact], list[Evidence]]:
    """Separa personas nuevas y legado; la evidencia empresarial permanece compartida."""
    apollo_ids = {item.contact_id for item in evidence if item.contact_id is not None and (
        item.provider == "apollo" and (item.external_reference or "").startswith("apollo_v1:")
        or (item.external_reference or "").startswith("apollo_public_v1:"))}
    apollo = campaign.config_snapshot.people_provider == "apollo"
    selected = [item for item in contacts if (item.id in apollo_ids) == apollo]
    selected_ids = {item.id for item in selected}
    facts = [item for item in evidence if (item.contact_id is None or item.contact_id in selected_ids)
             and (item.provider != "hunter" if apollo else item.provider != "apollo")]
    return selected, facts


def parse_source_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        if len(value) != 10:
            raise ValueError("La fecha con hora necesita zona horaria.")
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def target_roles(company: Company, assessment: Assessment, campaign: Campaign, *,
                 evidence: list[Evidence] | None = None) -> list[str]:
    """Todos los cargos de los perfiles de la empresa, primero los elegidos en la evaluación."""
    if campaign.config_snapshot.role_taxonomy is not None:
        return list(dict.fromkeys(title for family in role_families(company, assessment, campaign, evidence=evidence)
                                  for title in family.titles_en + family.titles_es))
    allowed = list(dict.fromkeys(role for profile in campaign.config_snapshot.profiles
                                if profile.segment in (company.segments or []) and profile.segment in campaign.segments
                                for role in profile.target_roles))
    selected = [role for role in assessment.target_roles if role in allowed]
    return list(dict.fromkeys(selected + allowed))


def role_families(company: Company, assessment: Assessment, campaign: Campaign, *,
                  evidence: list[Evidence] | None = None) -> list:
    """Familias del caso de uso sustentado, sin atribuir autoridad a la persona."""
    taxonomy = campaign.config_snapshot.role_taxonomy
    if taxonomy is None or assessment.company_id != company.id or assessment.campaign_id != campaign.id:
        return []
    allowed = {profile.id for profile in campaign.config_snapshot.profiles
               if profile.segment in (company.segments or []) and profile.segment in campaign.segments}
    matches = assessment.profile_matches
    if evidence is not None:
        by_id = {fact.id: fact for fact in evidence if fact.company_id == company.id}
        contradicted = {identifier for fact in by_id.values() for identifier in fact.contradiction_ids}
        matches = [match for match in matches if all(
            citation.evidence_id in by_id and citation.evidence_id not in contradicted
            and not by_id[citation.evidence_id].contradiction_ids
            and by_id[citation.evidence_id].contact_id is None and by_id[citation.evidence_id].kind == "observed"
            and not is_search_evidence(by_id[citation.evidence_id])
            and any(citation.quote in text for text in
                    (by_id[citation.evidence_id].claim, by_id[citation.evidence_id].excerpt or ""))
            for citation in match.citations)]
    profiles = allowed.intersection(match.profile_id for match in matches)
    priority = {"business_champion": 0, "technical_champion": 1, "economic_buyer": 2}
    return sorted((family for family in taxonomy.families if profiles.intersection(family.profile_ids)),
                  key=lambda family: priority[family.buying_role])


def fold_words(value: str) -> str:
    plain = "".join(char for char in unicodedata.normalize("NFKD", value.casefold())
                    if not unicodedata.combining(char))
    return re.sub(r"[^\w@.+]+", " ", plain).strip()


def mentions(text: str, value: str) -> bool:
    return bool(value.strip()) and bool(re.search(r"(?<!\w)" + re.escape(fold_words(value)) + r"(?!\w)", fold_words(text)))


def organization_matches(company: Company, name: str | None) -> bool:
    return name is not None and fold_words(name) in {fold_words(item) for item in
                                               [company.name, company.entity_name, *(company.aliases or [])] if item}


def full_name(first: str | None, last: str | None) -> tuple[str | None, bool]:
    name = " ".join(item.strip() for item in (first, last) if item and item.strip()) or None
    complete = bool(first and last and complete_name(name or ""))
    return name, complete


def complete_name(name: str) -> bool:
    return len(name.split()) >= 2 and not any(re.fullmatch(r"[^\W\d_]\.?", item) for item in name.split())


def professional_email(email: str, domain: str | None) -> bool:
    if "@" not in email:
        return False
    local, host = email.rsplit("@", 1)
    generic = {"info", "contact", "contacto", "sales", "ventas", "support", "soporte", "hello", "hola",
               "admin", "administracion", "marketing", "hr", "rrhh", "noreply", "no-reply"}
    return host.lower() == domain and local.lower() not in generic


def phone_country_of(phone: str) -> str | None:
    if re.fullmatch(r"\+57[0-9]{10}", phone):
        return "CO"
    if re.fullmatch(r"\+52[0-9]{10}", phone):
        return "MX"
    return None


def nominal_channel_association(text: str, name: str, value: str, extension: str | None = None) -> bool:
    """Exige titular en la cláusula del canal o una continuación nominal inmediata."""
    clauses = re.split(r"[.;!?]\s+|\n+", text)
    for index, clause in enumerate(clauses):
        if value not in clause:
            continue
        before, _, after = clause.partition(value)
        labels = list(re.finditer(r"\b(?:correo|email|e-mail|teléfono|telefono|phone|whatsapp|central|conmutador|switchboard|recepción)\b", before, re.I))
        label = labels[-1] if labels else None
        owner = "" if label is None else re.sub(r"^\s*(?:(?:laboral|profesional|nominal|directo|general)\s*)*", "", before[label.end():], flags=re.I)
        if label and (fold_words(label[0]) in ("central", "conmutador", "switchboard", "recepcion") or
                      mentions(before[label.end():], "general")):
            extension_match = None if not extension else re.search(
                r"\b(?:extensión|extension|ext|anexo)\.?\s*[:#]?\s*" + re.escape(extension) +
                r"\b(?:\s+(?:de|para|of|for)\s+([^,;]+))?", clause, re.I)
            if (not extension_match or not mentions(clause, name) or
                    extension_match[1] and not mentions(extension_match[1], name)):
                continue
        if label and fold_words(owner) and not mentions(owner, name):
            continue
        if label is None and ":" in before and not mentions(before.rsplit(":", 1)[0].rsplit(",", 1)[-1], name):
            continue
        owner_after = re.match(r"\s*(?:de|para|of|for)\s+(.+)", after, re.I)
        if owner_after and not mentions(owner_after[1], name):
            continue
        if mentions(clause, name):
            return True
        if (index > 0 and mentions(clauses[index - 1], name) and
                re.fullmatch(r"\s*(?:correo profesional|teléfono nominal|telefono nominal|whatsapp profesional)\s*:?\s*", before, re.I)
                and re.fullmatch(r"[\s.,:;!?]*", after)):
            return True
    return False


def role_matches(title: str | None, roles: list[str]) -> bool:
    if not title:
        return False
    equivalents = {"cto": "chief technology officer", "director de tecnologia": "chief technology officer",
                   "chief technical officer": "chief technology officer"}
    observed = fold_words(title)
    if re.search(r"\b(?:assistant\s+to|asistente(?:\s+ejecutiv[oa])?\s+(?:de|del))\b", observed):
        return False
    return any(mentions(observed, role) or
               equivalents.get(fold_words(role), fold_words(role)) == equivalents.get(observed, observed)
               for role in roles)


def role_position(title: str | None, roles: list[str]) -> int:
    """Posición del primer cargo objetivo que encaja con el título; sin encaje, al final."""
    return next((index for index, role in enumerate(roles) if role_matches(title, [role])), len(roles))


def apply_target_roles(contact: Contact, roles: list[str]) -> Contact:
    if contact.title is None or not contact.provenance.get("title"):
        return contact
    relevant = role_matches(contact.title, roles)
    return contact.model_copy(update={"relevant_function": relevant,
                                      "provenance": contact.provenance | {"relevant_function": contact.provenance["title"]}})


def _fresh(value: datetime | None, days: int, now: datetime) -> bool:
    return value is not None and now - timedelta(days=days) <= value <= now


def _corporate(company: Company, fact: Evidence) -> bool:
    host = None if fact.url is None else url_host(str(fact.url))
    return company.domain is not None and host is not None and within_domain(host, company.domain)


def current_directory(fact: Evidence) -> bool:
    return fact.url is not None and bool(re.search(r"/(?:team|equipo|leadership|directivos|directorio|people|contacto|contact|about|nosotros)(?:[/#?._-]|$)", str(fact.url).lower()))


EmploymentFreshness = Literal["fresh", "future", "stale", "undated"]


def employment_freshness(fact: Evidence, company: Company, limits: CampaignLimits,
                         now: datetime) -> EmploymentFreshness:
    """Vigencia temporal de una fuente del puesto; solo «fresh» respalda el empleo.

    Una fecha futura invalida la fuente; una fecha del puesto vale `employment_days`; sin ella, solo un
    directorio corporativo consultado dentro de la caché web es vigente y otra página queda sin fecha.
    """
    if any(value is not None and value > now for value in (fact.retrieved_at, fact.published_at, fact.updated_at)):
        return "future"
    date = fact.updated_at or fact.published_at
    if date is not None:
        return "fresh" if _fresh(date, limits.freshness.employment_days, now) else "stale"
    if fact.source_type == "primary" and _corporate(company, fact) and current_directory(fact):
        return "fresh" if _fresh(fact.retrieved_at, limits.cache.web_days, now) else "stale"
    return "undated"


def employment_fresh(fact: Evidence, company: Company, limits: CampaignLimits, now: datetime) -> bool:
    return employment_freshness(fact, company, limits, now) == "fresh"


def employment_ended(text: str, name: str, title: str | None) -> bool:
    """Solo una salida o un cargo anterior atribuidos a la persona contradicen vigencia."""
    subject, role = re.escape(fold_words(name)), re.escape(fold_words(title or ""))
    words = fold_words(text)
    former = r"(?:former|previous|ex|anterior|antiguo)\s+" + role + r"\b"
    departure = (r"(?:dejo\s+de\s+(?:ser|trabajar)|ya\s+no\s+(?:es|trabaja)|dejo\s+(?:el\s+puesto|la\s+empresa)|"
                 r"renuncio|salio\s+de|se\s+retiro|left|departed|resigned|no\s+longer|ceased\s+to)\b")
    return bool(re.search(r"(?<!\w)" + subject + r"\s+(?:(?:es|is|era|was|fue)\s+)?(?:" + former + "|" + departure + ")",
                          words) or re.search(r"\b" + former + r"\s+" + subject + r"(?!\w)", words))


def _valid_refs(ids: list[UUID], contact: Contact, evidence: list[Evidence]) -> list[Evidence]:
    by_id = {item.id: item for item in evidence}
    if not ids or any(id not in by_id for id in ids):
        return []
    facts = [by_id[id] for id in ids]
    if any(item.company_id != contact.company_id or item.contact_id not in (None, contact.id) or item.contradiction_ids or is_search_evidence(item) for item in facts):
        return []
    return facts


def _family_title(title: str, family) -> bool:
    observed = fold_words(title)
    if any(mentions(observed, excluded) for excluded in family.excluded_titles):
        return False
    # El ámbito regional puede acompañar un cargo; otras palabras cambian su función.
    observed = " ".join(re.sub(r"\b(?:regional|global)\b", "", observed).split())
    scope = r"(?:latam|latin america|latinoamerica|colombia|mexico|regional|global|worldwide|and|y|de|para|for|in|en|co|mx)"
    return any(re.fullmatch(re.escape(fold_words(alias)) + r"(?:\s+" + scope + r")*", observed)
               for alias in family.titles_en + family.titles_es)


def matched_role_family(contact: Contact, company: Company, assessment: Assessment, campaign: Campaign,
                        evidence: list[Evidence], now: datetime):
    """Devuelve familia y fuentes observadas; una responsabilidad no se deduce del título."""
    families = role_families(company, assessment, campaign, evidence=evidence)
    if not contact.title or not contact.name or not families:
        return None, []
    contradicted = {identifier for fact in evidence if fact.company_id == company.id for identifier in fact.contradiction_ids}
    title_facts = _valid_refs(contact.provenance.get("title", []), contact, evidence)
    title_facts = [fact for fact in title_facts if fact.id not in contradicted and fact.kind == "observed" and fact.retrieved_at <= now
                   and mentions(fact.excerpt or fact.claim, contact.title)
                   and (mentions(fact.excerpt or fact.claim, contact.name) or
                        fact.source_type == "provider" and fact.contact_id == contact.id)]
    if not title_facts:
        return None, []
    if re.search(r"\b(?:assistant\s+to|asistente(?:\s+ejecutiv[oa])?\s+(?:de|del))\b", fold_words(contact.title)):
        return None, []
    for family in families:
        if _family_title(contact.title, family):
            return family, [fact.id for fact in title_facts]
    for fact in evidence:
        if (fact.contact_id != contact.id or not fact.claim.startswith("Hecho nominal publicado: responsibilities=")
                or fact.id in contradicted or not _valid_refs([fact.id], contact, evidence) or fact.kind != "observed"
                or fact.source_type != "primary" or not _corporate(company, fact)
                or not employment_fresh(fact, company, campaign.limits, now)
                or not mentions(fact.excerpt or "", contact.name)
                or employment_ended(fact.excerpt or "", contact.name, contact.title)):
            continue
        reference = re.fullmatch(
            r"(?:apollo_public_v1|public_extraction_v2):[^#]+#contact:responsibilities:"
            r"([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})", fact.external_reference or "")
        originals = [] if reference is None else _valid_refs([UUID(reference[1])], contact, evidence)
        if (not originals or originals[0].id in contradicted or originals[0].kind != "observed"
                or originals[0].source_type != "primary" or not _corporate(company, originals[0])
                or not employment_fresh(originals[0], company, campaign.limits, now)
                or originals[0].url != fact.url or not fact.excerpt
                or fact.excerpt not in (originals[0].excerpt or "")[:800]):
            continue
        for family in families:
            responsibility = fact.claim.split("responsibilities=", 1)[1]
            if (not any(mentions(contact.title, excluded) for excluded in family.excluded_titles)
                    and not re.search(r"\b(?:no|not|never|nunca|sin|neither)\b",
                                      fold_words(responsibility + " " + (fact.excerpt or "")))
                    and any(mentions(responsibility, term) for term in family.function_terms)):
                return family, [fact.id]
    return None, []


def apply_campaign_roles(contact: Contact, company: Company, assessment: Assessment, campaign: Campaign,
                         evidence: list[Evidence], now: datetime) -> Contact:
    """Reclasifica en una copia según la campaña; nunca reutiliza un booleano global como prueba."""
    if campaign.config_snapshot.role_taxonomy is None:
        return contact
    family, ids = matched_role_family(contact, company, assessment, campaign, evidence, now)
    relevant = True if family is not None else None
    if contact.title and contact.provenance.get("title"):
        all_families = campaign.config_snapshot.role_taxonomy.families
        rejected = (not role_families(company, assessment, campaign, evidence=evidence)
                    or re.search(r"\b(?:assistant\s+to|asistente(?:\s+ejecutiv[oa])?\s+(?:de|del))\b", fold_words(contact.title))
                    or any(mentions(contact.title, excluded) for item in role_families(company, assessment, campaign, evidence=evidence)
                           for excluded in item.excluded_titles)
                    or any(_family_title(contact.title, item) for item in all_families))
        if family is None and rejected:
            relevant, ids = False, contact.provenance["title"]
    provenance = {field: list(values) for field, values in contact.provenance.items() if field != "relevant_function"}
    if ids:
        provenance["relevant_function"] = ids
    return contact.model_copy(update={"relevant_function": relevant, "provenance": provenance})


def validate_contact(contact: Contact, company: Company, assessment: Assessment,
                     evidence: list[Evidence], limits: CampaignLimits, now: datetime,
                     roles: list[str] | None = None, *, campaign: Campaign | None = None) -> bool:
    """La identidad y el empleo no se deducen del email ni del momento de consulta.

    `roles` son los cargos de los perfiles (`target_roles`); sin ellos solo valen los elegidos en la evaluación.
    """
    taxonomy = campaign is not None and campaign.config_snapshot.role_taxonomy is not None
    if taxonomy:
        contact = apply_campaign_roles(contact, company, assessment, campaign, evidence, now)
    if (company.id != contact.company_id or assessment.company_id != company.id or
            company.identity_status != IdentityStatus.CONFIRMED or
            assessment.priority not in (Priority.HIGH, Priority.MEDIUM) or
            contact.identity_status != IdentityStatus.CONFIRMED or contact.name_complete is not True or
            contact.current_employment is False or contact.relevant_function is not True or
            not contact.name or not contact.title):
        return False
    apollo = [item for item in evidence if item.contact_id == contact.id and item.provider == "apollo"
              and (item.external_reference or "").startswith("apollo_v1:")]
    if apollo and not any((item.external_reference or "").endswith("#enrichment") for item in apollo):
        return False
    for field in ("name", "title", "relevant_function"):
        facts = _valid_refs(contact.provenance.get(field, []), contact, evidence)
        if not facts or any(item.kind != "observed" for item in facts):
            return False
        if taxonomy and field == "relevant_function":
            continue
        value = contact.name if field == "name" else contact.title
        if not any(mentions(item.excerpt or item.claim, value) and
                   (mentions(item.excerpt or item.claim, contact.name) or
                    item.source_type == "provider" and item.contact_id == contact.id)
                   for item in facts):
            return False
    if not taxonomy and not role_matches(contact.title, roles if roles is not None else assessment.target_roles):
        return False
    if contact.geographic_scope and (not _valid_refs(contact.provenance.get("geographic_scope", []), contact, evidence)
                                     or not _scope_covers(contact.geographic_scope, company)):
        return False
    return employment_status(contact, company, evidence, limits, now).state == "corporate_evidence"


def _scope_covers(scope: str, company: Company) -> bool:
    """Un alcance regional o que nombra un país de operación de la empresa."""
    scope = fold_words(scope)
    regional = any(mentions(scope, word) for word in ("latam", "latinoamerica", "latin america", "global", "mundial"))
    explicit = {code for code, names in {"CO": ("colombia", "co"), "MX": ("mexico", "mx"),
                                        "US": ("united states", "estados unidos", "us"),
                                        "ES": ("espana", "spain"), "AR": ("argentina",), "BR": ("brasil", "brazil")}.items()
                if any(mentions(scope, name) for name in names)}
    return regional or bool(explicit.intersection(company.operating_countries or []))


def _employment_contradicted(contact: Contact, evidence: list[Evidence]) -> bool:
    """Empleo marcado como no vigente o una salida nominal observada de la persona."""
    return contact.current_employment is False or bool(contact.name) and any(
        item.contact_id == contact.id and item.kind == "observed" and
        employment_ended(item.excerpt or item.claim, contact.name, contact.title) for item in evidence)


EmploymentState = Literal["corporate_evidence", "provider_claim", "contradicted", "unknown"]
EmploymentReason = Literal[
    "employment_ended", "title_changed", "contradicted_source", "future_date", "stale_source", "undated_source",
    "ambiguous_source", "title_unconfirmed", "incomplete_name", "provider_claim_only", "historical_inference",
    "no_employment_evidence",
]
# Fallos de corroboración en orden de gravedad: se informa el primero presente.
_CORROBORATION_ORDER = ("future_date", "stale_source", "undated_source", "ambiguous_source", "title_unconfirmed")
_FRESHNESS_REASONS = {"future": "future_date", "stale": "stale_source", "undated": "undated_source"}
_REVIEW_REASONS = frozenset({"title_changed", "undated_source", "ambiguous_source", "title_unconfirmed",
                             "historical_inference"})


class EmploymentStatus(Contract):
    """Vigencia del empleo calculada al leer, sin guardarse ni decidir gasto (T18).

    Solo `corporate_evidence` habilita a la persona: una afirmación de proveedor (Apollo o el historial
    de Hunter) nunca prueba el puesto. `reason` explica por qué no hay evidencia vigente.
    """

    state: EmploymentState
    origin: Literal["apollo", "hunter"] | None = None
    reason: EmploymentReason | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    review_required: StrictBool = False


def _employment(state: EmploymentState, origin: str | None, reason: str | None, ids) -> EmploymentStatus:
    return EmploymentStatus(state=state, origin=origin, reason=reason, evidence_ids=list(dict.fromkeys(ids)),
                            review_required=reason in _REVIEW_REASONS)


def _hunter_history_claim(contact: Contact, company: Company, evidence: list[Evidence],
                          limits: CampaignLimits, now: datetime) -> list[UUID]:
    """Vigencia inferida del historial de Hunter: buzón verificado y fuente aún publicada y vista hace poco.

    Se conserva para leer registros históricos; es una afirmación del proveedor y no prueba el puesto.
    """
    if not contact.name or _employment_contradicted(contact, evidence):
        return []
    if not any(channel.type == ChannelType.EMAIL and channel.normalized_status == ChannelStatus.VERIFIED and
               _fresh(channel.verified_at, limits.freshness.email_days, now) and
               channel_is_usable(channel, contact, evidence, limits, now, company) for channel in contact.channels):
        return []
    return [item.id for item in evidence
            if item.provider == "hunter" and item.source_type == "provider" and item.kind == "observed" and
            item.contact_id == contact.id and item.retrieved_at <= now and
            re.search(r"#\d+:source:\d+$", item.external_reference or "") and
            "still_on_page=True" in (item.excerpt or "") and
            _fresh(item.updated_at, limits.freshness.employment_days, now) and
            _valid_refs([item.id], contact, evidence)]


def _title_confirmed(contact: Contact, company: Company, fact: Evidence, by_id: dict[UUID, Evidence],
                     limits: CampaignLimits, now: datetime) -> bool:
    """El cargo actual figura junto al nombre en una fuente pública vigente, no solo en el proveedor."""
    sources = [fact] + [by_id[id] for id in contact.provenance.get("title", []) if id in by_id]
    return any(item.source_type in ("primary", "secondary") and item.kind == "observed" and not is_search_evidence(item)
               and employment_freshness(item, company, limits, now) == "fresh"
               and mentions(item.excerpt or item.claim, contact.name or "")
               and mentions(item.excerpt or item.claim, contact.title or "") for item in sources)


def employment_status(contact: Contact, company: Company, evidence: list[Evidence],
                      limits: CampaignLimits, now: datetime) -> EmploymentStatus:
    """Separa lo que declara el proveedor de la evidencia pública del puesto (T18, §10.2).

    Orden: contradicción, evidencia corporativa o pública vigente, afirmación del proveedor y desconocido.
    Ni el correo, ni su verificación, ni la fecha de actualización del perfil de Apollo prueban el empleo.
    """
    by_id = {item.id: item for item in evidence if item.company_id == contact.company_id}
    own = [item for item in by_id.values() if item.contact_id == contact.id]
    apollo = any(item.provider == "apollo" and (item.external_reference or "").startswith("apollo_v1:") for item in own)
    origin = "apollo" if apollo else None
    cited = [by_id[id] for id in contact.employment_evidence_ids if id in by_id]
    # 1. Contradicción: salida nominal, cargo distinto o fuente del puesto contradicha (en ambos sentidos).
    ended = [item.id for item in own + cited if contact.name and item.kind == "observed"
             and employment_ended(item.excerpt or item.claim, contact.name, contact.title)]
    if _employment_contradicted(contact, evidence) or ended:
        return _employment("contradicted", origin, "employment_ended", ended)
    title_ids = set(contact.provenance.get("title", []))
    changed = [item.id for item in own if title_ids.intersection(item.contradiction_ids)]
    if changed:
        return _employment("contradicted", origin, "title_changed", changed)
    disputed = {id for item in by_id.values() for id in item.contradiction_ids}
    conflicting = [item.id for item in cited if item.contradiction_ids or item.id in disputed]
    if conflicting:
        return _employment("contradicted", origin, "contradicted_source", conflicting)
    # 2. Evidencia del puesto: fuente pública u corporativa observada, vigente y nominal; nunca un proveedor.
    failures: dict[str, list[UUID]] = {}
    justified = []
    complete = contact.name_complete is True and bool(contact.name) and "*" not in (contact.name or "")
    if complete:
        for item in _valid_refs(contact.employment_evidence_ids, contact, evidence):
            if item.kind != "observed" or item.source_type not in ("primary", "secondary"):
                continue
            freshness = employment_freshness(item, company, limits, now)
            if freshness != "fresh":
                failures.setdefault(_FRESHNESS_REASONS[freshness], []).append(item.id)
            elif not mentions(item.excerpt or item.claim, contact.name):
                failures.setdefault("ambiguous_source", []).append(item.id)
            elif apollo and not _title_confirmed(contact, company, item, by_id, limits, now):
                failures.setdefault("title_unconfirmed", []).append(item.id)
            else:
                justified.append(item.id)
        if justified and contact.current_employment is True:
            return _employment("corporate_evidence", origin, None, justified)
    reason = next((item for item in _CORROBORATION_ORDER if item in failures), None)
    failed = failures.get(reason, []) if reason else []
    if not complete:
        reason, failed = "incomplete_name", []
    # 3. Afirmación del proveedor: Apollo declara el empleo actual o el historial de Hunter lo infiere.
    claim = [item.id for item in own if apollo and item.provider == "apollo" and item.source_type == "provider"
             and item.kind == "observed" and (item.external_reference or "").endswith("#enrichment")
             and _fresh(item.retrieved_at, limits.cache.contact_days, now)]
    if claim:
        return _employment("provider_claim", "apollo", reason or "provider_claim_only", claim + failed)
    hunter = _hunter_history_claim(contact, company, evidence, limits, now)
    if hunter:
        return _employment("provider_claim", "hunter", "historical_inference", hunter)
    # 4. Sin evidencia vigente ni afirmación reciente del proveedor.
    stale_claim = [item.id for item in own if apollo and item.provider == "apollo" and item.source_type == "provider"
                   and (item.external_reference or "").endswith("#enrichment")]
    if reason is None and stale_claim:
        reason, failed = "stale_source", stale_claim
    return _employment("unknown", origin, reason or "no_employment_evidence", failed)


def channel_is_usable(channel: Channel, contact: Contact, evidence: list[Evidence],
                      limits: CampaignLimits, now: datetime, company: Company) -> bool:
    if (channel.contact_id != contact.id or contact.company_id != company.id or
            channel.normalized_status == ChannelStatus.INVALID or
            channel.professional is not True or channel.direct is not True):
        return False
    facts = _valid_refs(channel.evidence_ids, contact, evidence)
    if not facts or any(item.retrieved_at > now for item in facts):
        return False
    structured = [item for item in facts if item.source_type == "provider" and item.provider in ("hunter", "apollo") and
                  item.contact_id == contact.id and item.external_reference is not None and
                  (item.provider != "apollo" or item.external_reference.startswith("apollo_v1:")) and
                  "#contact:" not in item.external_reference and not item.claim.startswith("Hecho nominal publicado:")]
    if channel.type == ChannelType.EMAIL:
        # El correo laboral pertenece al dominio confirmado de la empresa; sin dominio no hay canal (§10.2).
        if not professional_email(channel.value, company.domain):
            return False
        if channel.normalized_status == ChannelStatus.VERIFIED:
            if _fresh(channel.verified_at, limits.freshness.email_days, now) and any(
                item.kind == "observed" and channel.value in (item.claim + " " + (item.excerpt or "")) for item in structured):
                return True
        published = _valid_refs(channel.published_evidence_ids, contact, evidence)
        return any(item.source_type == "primary" and item.kind == "observed" and
                   nominal_channel_association(item.excerpt or item.claim, contact.name or "", channel.value)
                   and _fresh(item.retrieved_at, limits.cache.web_days, now) and
                   (_fresh(item.updated_at or item.published_at, limits.freshness.email_days, now)
                    if item.updated_at or item.published_at else current_directory(item))
                   for item in published)
    if channel.type in (ChannelType.LINKEDIN, ChannelType.OTHER):
        return channel.manual_confirmed_at is not None and _fresh(channel.manual_confirmed_at, limits.cache.contact_days, now) and any(
            item.source_type == "manual" and item.kind == "observed" for item in facts)
    if channel.type == ChannelType.PHONE:
        return channel.phone_country == phone_country_of(channel.value) and phone_country_of(channel.value) is not None and any(
            item.kind == "observed" and channel.value in (item.excerpt or item.claim) and
            (item in structured or
             nominal_channel_association(item.excerpt or item.claim, contact.name or "", channel.value, channel.extension)) and
            _fresh(item.retrieved_at, limits.cache.contact_days, now) for item in facts)
    return any(item.source_type == "primary" and item.kind == "observed" and
               nominal_channel_association(item.excerpt or item.claim, contact.name or "", channel.value, channel.extension) and
               mentions(item.excerpt or item.claim, "whatsapp") and _fresh(item.retrieved_at, limits.cache.web_days, now)
               for item in facts)


def derive_readiness(assessment: Assessment, contacts: list[Contact], evidence: list[Evidence],
                     limits: CampaignLimits, now: datetime, company: Company,
                     roles: list[str] | None = None, *, campaign: Campaign | None = None) -> BusinessStatus:
    if assessment.priority == Priority.EXCLUDED:
        return BusinessStatus.EXCLUDED
    if assessment.priority == Priority.LOW:
        return BusinessStatus.LOW_FIT
    if assessment.priority == Priority.INSUFFICIENT_EVIDENCE or company.identity_status != IdentityStatus.CONFIRMED:
        return BusinessStatus.INSUFFICIENT_EVIDENCE
    eligible = [contact for contact in contacts if validate_contact(contact, company, assessment, evidence, limits, now, roles,
                                                               campaign=campaign)]
    usable = [channel for contact in eligible for channel in contact.channels
              if channel_is_usable(channel, contact, evidence, limits, now, company)]
    if any(channel.type in (ChannelType.EMAIL, ChannelType.PHONE, ChannelType.WHATSAPP) for channel in usable):
        return BusinessStatus.READY_PREFERRED
    if usable:
        return BusinessStatus.READY_ALTERNATIVE
    if any(channel.normalized_status != ChannelStatus.INVALID for contact in eligible for channel in contact.channels):
        return BusinessStatus.NEEDS_CHANNEL_CONFIRMATION
    return BusinessStatus.QUALIFIED_NO_CONTACT


# Porcentaje de match: ordena a las personas para que ventas elija; no decide elegibilidad,
# listo ni gasto. El código fija componentes y niveles; config/contact_match.json, sus puntos.
MatchComponentName = Literal["role", "channel", "identity", "employment"]
MATCH_LEVELS = {
    "role": ("selected_role", "profile_role", "outside_profile", "unknown"),
    "channel": ("preferred_usable", "alternative_usable", "preferred_unconfirmed", "alternative_unconfirmed", "none"),
    "identity": ("confirmed_complete", "complete_pending", "incomplete"),
    "employment": ("evidence", "hunter_signal", "unverified"),
}
# Dato desconocido: suma 0 y se muestra pendiente, nunca como «no cumple».
PENDING_LEVELS = frozenset({"unknown", "none", "incomplete", "unverified"})
BlockedReason = Literal["identity_contradicted", "employment_ended", "scope_mismatch"]
_PREFERRED = (ChannelType.EMAIL, ChannelType.PHONE, ChannelType.WHATSAPP)
Points = Annotated[StrictInt, Field(ge=0, le=100)]


class MatchComponentConfig(Contract):
    weight: Annotated[StrictInt, Field(gt=0, le=100)]
    levels: dict[Text, Points]


class ContactMatchConfig(Contract):
    """Pesos versionados: cambiar un número exige cambiar `version` (docs/contacts.md)."""

    version: Text
    validation_status: Literal["proposed", "validated"]
    source_reference: Text
    components: dict[MatchComponentName, MatchComponentConfig]

    @model_validator(mode="after")
    def validate_points(self) -> Self:
        if set(self.components) != set(MATCH_LEVELS):
            raise ValueError("El match necesita los componentes role, channel, identity y employment.")
        if sum(item.weight for item in self.components.values()) != 100:
            raise ValueError("Los pesos del match deben sumar 100.")
        for name, item in self.components.items():
            if set(item.levels) != set(MATCH_LEVELS[name]):
                raise ValueError(f"El componente {name} necesita exactamente los niveles {', '.join(MATCH_LEVELS[name])}.")
            if max(item.levels.values()) != item.weight:
                raise ValueError(f"El nivel más alto de {name} debe valer su peso, sin superarlo.")
            if any(points for level, points in item.levels.items() if level in PENDING_LEVELS):
                raise ValueError("Un dato pendiente no suma puntos.")
        return self


class MatchComponent(Contract):
    name: MatchComponentName
    level: Text
    points: Points
    weight: Points
    pending: StrictBool


class ContactMatch(Contract):
    version: Text
    score: Points
    components: list[MatchComponent]
    blocked_reason: BlockedReason | None = None


def _v1_employment_level(status: EmploymentStatus) -> str:
    """Niveles históricos de `contact_match_v1`: «hunter_signal» solo nombra el origen de Hunter."""
    if status.state == "corporate_evidence":
        return "evidence"
    if status.state == "provider_claim" and status.origin == "hunter":
        return "hunter_signal"
    return "unverified"


def load_contact_match(path: Path) -> ContactMatchConfig:
    """Falla si el archivo falta o no es válido: nunca se usan pesos por defecto."""
    return ContactMatchConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


def contact_match(contact: Contact, company: Company, assessment: Assessment, evidence: list[Evidence],
                  limits: CampaignLimits, now: datetime, roles: list[str], config: ContactMatchConfig, *,
                  campaign: Campaign | None = None) -> ContactMatch:
    """Match determinístico, sin red ni IA, con las mismas reglas de persona y canal (§10)."""
    selected = [role for role in assessment.target_roles if role in roles]
    taxonomy = campaign is not None and campaign.config_snapshot.role_taxonomy is not None
    if taxonomy:
        contact = apply_campaign_roles(contact, company, assessment, campaign, evidence, now)
    if not contact.title or not contact.provenance.get("title") or taxonomy and contact.relevant_function is None:
        role = "unknown"
    elif taxonomy:
        role = ("selected_role" if role_matches(contact.title, selected) else "profile_role") if contact.relevant_function is True else "outside_profile"
    elif role_matches(contact.title, selected):
        role = "selected_role"
    elif role_matches(contact.title, roles):
        role = "profile_role"
    else:
        role = "outside_profile"
    usable = [item for item in contact.channels if channel_is_usable(item, contact, evidence, limits, now, company)]
    candidates = [item for item in contact.channels
                  if item.normalized_status != ChannelStatus.INVALID and item.professional is not False]
    if any(item.type in _PREFERRED for item in usable):
        channel = "preferred_usable"
    elif usable:
        channel = "alternative_usable"
    elif any(item.type in _PREFERRED for item in candidates):
        channel = "preferred_unconfirmed"
    elif candidates:
        channel = "alternative_unconfirmed"
    else:
        channel = "none"
    identity = ("confirmed_complete" if contact.identity_status == IdentityStatus.CONFIRMED and contact.name_complete is True
                else "complete_pending" if contact.name_complete is True else "incomplete")
    employment = _v1_employment_level(employment_status(contact, company, evidence, limits, now))
    components = [MatchComponent(name=name, level=level, points=config.components[name].levels[level],
                                 weight=config.components[name].weight, pending=level in PENDING_LEVELS)
                  for name, level in (("role", role), ("channel", channel), ("identity", identity),
                                      ("employment", employment))]
    # Solo un alcance respaldado que excluye los países de la empresa bloquea; uno sin fuente queda pendiente.
    scoped = bool(contact.geographic_scope and _valid_refs(contact.provenance.get("geographic_scope", []), contact, evidence))
    blocked = ("identity_contradicted" if contact.identity_status == IdentityStatus.CONTRADICTED
               else "employment_ended" if _employment_contradicted(contact, evidence)
               else "scope_mismatch" if scoped and not _scope_covers(contact.geographic_scope, company) else None)
    return ContactMatch(version=config.version, score=sum(item.points for item in components),
                        components=components, blocked_reason=blocked)


def match_sort_key(match: ContactMatch | None, eligible: bool, contact: Contact, roles: list[str]):
    """Mayor match primero y bloqueadas al final; empates por elegibilidad, cargo, nombre e id."""
    return (match is None, match is not None and match.blocked_reason is not None, -(match.score if match else 0),
            not eligible, role_position(contact.title, roles), fold_words(contact.name or ""), str(contact.id))


def merge_contact(old: Contact, new: Contact, evidence: list[Evidence]) -> Contact:
    """Fusiona únicamente la identidad ya resuelta; preserva fuentes y negativos."""
    if old.id != new.id or old.company_id != new.company_id:
        raise ContactError("identity_mismatch", "La fusión requiere la misma persona y entidad confirmadas.")
    if old.name_complete is True and new.name_complete is True and fold_words(old.name or "") != fold_words(new.name or ""):
        raise ContactError("identity_mismatch", "Un canal compartido no autoriza fusionar nombres completos distintos.")
    channels = {(item.type, item.value): item for item in old.channels}
    for item in new.channels:
        previous = channels.get((item.type, item.value))
        if previous is not None:
            if item.provider_status is None and previous.provider_status is not None:
                item = item.model_copy(update={"provider_status": previous.provider_status,
                                               "normalized_status": previous.normalized_status,
                                               "verified_at": previous.verified_at})
            if item.manual_confirmed_at is None and previous.manual_confirmed_at is not None:
                item = item.model_copy(update={"manual_confirmed_at": previous.manual_confirmed_at,
                                               "manual_confirmation_reason": previous.manual_confirmation_reason,
                                               "direct": previous.direct})
            if previous.normalized_status == ChannelStatus.INVALID:
                later = item.normalized_status == ChannelStatus.VERIFIED and item.verified_at is not None and item.verified_at > (previous.verified_at or previous.retrieved_at)
                if not later or not any(fact.id in item.evidence_ids and fact.id not in previous.evidence_ids and
                                        fact.source_type == "provider" and fact.kind == "observed" and
                                        fact.retrieved_at > (previous.verified_at or previous.retrieved_at) for fact in evidence):
                    item = item.model_copy(update={"normalized_status": ChannelStatus.INVALID,
                                                   "provider_status": previous.provider_status, "verified_at": previous.verified_at})
            item = item.model_copy(update={"evidence_ids": list(dict.fromkeys(previous.evidence_ids + item.evidence_ids)),
                                           "published_evidence_ids": list(dict.fromkeys(previous.published_evidence_ids + item.published_evidence_ids)),
                                           "warnings": list(dict.fromkeys(previous.warnings + item.warnings))})
        channels[item.type, item.value] = item
    values = old.model_dump()
    for field in ("name", "title", "name_complete", "current_employment", "relevant_function", "geographic_scope"):
        if field in ("name", "name_complete") and old.name_complete is True and new.name_complete is not True:
            continue
        if getattr(new, field) is not None:
            values[field] = getattr(new, field)
    if new.identity_status != IdentityStatus.PENDING:
        values["identity_status"] = new.identity_status
    values["provenance"] = {key: list(dict.fromkeys(old.provenance.get(key, []) + new.provenance.get(key, [])))
                            for key in old.provenance.keys() | new.provenance.keys()}
    values["employment_evidence_ids"] = list(dict.fromkeys(old.employment_evidence_ids + new.employment_evidence_ids))
    values["channels"] = list(channels.values())
    return Contact.model_validate(values)


