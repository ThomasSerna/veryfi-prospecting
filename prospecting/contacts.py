"""Reglas de personas, canales y condición de listo (§10), sin conocer la fuente; sin red ni persistencia.

Los proveedores y Haiku aportan datos: Python conserva procedencia, valida las
asociaciones y decide si hay un canal utilizable. Nunca se contacta a una persona.
Toda fuente de personas entrega `Contact`, `Channel` y `Evidence` y pasa por estas reglas (§11.3).
"""

from datetime import UTC, datetime, timedelta
import re
import unicodedata
from uuid import UUID

from prospecting.models import (
    Assessment, BusinessStatus, Campaign, CampaignLimits, Channel, ChannelStatus, ChannelType,
    Company, Contact, Evidence, IdentityStatus, Priority,
)
from prospecting.sources import is_search_evidence, url_host, within_domain


class ContactError(Exception):
    """Hecho no respaldado que deja el contacto pendiente, sin corregirlo con IA."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def parse_source_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        if len(value) != 10:
            raise ValueError("La fecha con hora necesita zona horaria.")
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def target_roles(company: Company, assessment: Assessment, campaign: Campaign) -> list[str]:
    """Reutiliza cargos de la evaluación, restringidos a los perfiles de la empresa."""
    allowed = list(dict.fromkeys(role for profile in campaign.config_snapshot.profiles
                                if profile.segment in (company.segments or []) and profile.segment in campaign.segments
                                for role in profile.target_roles))
    selected = [role for role in assessment.target_roles if role in allowed]
    return selected or allowed


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


def apply_target_roles(contact: Contact, roles: list[str], evidence: list[Evidence]) -> tuple[Contact, list[Evidence]]:
    if contact.title is None or not contact.provenance.get("title"):
        return contact, []
    relevant = role_matches(contact.title, roles)
    return contact.model_copy(update={"relevant_function": relevant,
                                      "provenance": contact.provenance | {"relevant_function": contact.provenance["title"]}}), []


def _fresh(value: datetime | None, days: int, now: datetime) -> bool:
    return value is not None and now - timedelta(days=days) <= value <= now


def _corporate(company: Company, fact: Evidence) -> bool:
    host = None if fact.url is None else url_host(str(fact.url))
    return company.domain is not None and host is not None and within_domain(host, company.domain)


def _current_directory(fact: Evidence) -> bool:
    return fact.url is not None and bool(re.search(r"/(?:team|equipo|leadership|directivos|directorio|people|contacto|contact|about|nosotros)(?:[/#?._-]|$)", str(fact.url).lower()))


def employment_fresh(fact: Evidence, company: Company, limits: CampaignLimits, now: datetime) -> bool:
    if any(value is not None and value > now for value in (fact.retrieved_at, fact.published_at, fact.updated_at)):
        return False
    date = fact.updated_at or fact.published_at
    if date is not None:
        return _fresh(date, limits.freshness.employment_days, now)
    return (fact.source_type == "primary" and _corporate(company, fact) and _current_directory(fact)
            and _fresh(fact.retrieved_at, limits.cache.web_days, now))


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


def validate_contact(contact: Contact, company: Company, assessment: Assessment,
                     evidence: list[Evidence], limits: CampaignLimits, now: datetime) -> bool:
    """La identidad y el empleo no se deducen del email ni del momento de consulta."""
    if (company.id != contact.company_id or assessment.company_id != company.id or
            company.identity_status != IdentityStatus.CONFIRMED or
            assessment.priority not in (Priority.HIGH, Priority.MEDIUM) or
            contact.identity_status != IdentityStatus.CONFIRMED or contact.name_complete is not True or
            contact.current_employment is not True or contact.relevant_function is not True or
            not contact.name or not contact.title):
        return False
    for field in ("name", "title", "relevant_function"):
        facts = _valid_refs(contact.provenance.get(field, []), contact, evidence)
        if not facts or any(item.kind != "observed" for item in facts):
            return False
        value = contact.name if field == "name" else contact.title
        if not any(mentions(item.excerpt or item.claim, value) and
                   (mentions(item.excerpt or item.claim, contact.name) or
                    item.source_type == "provider" and item.contact_id == contact.id)
                   for item in facts):
            return False
    if not role_matches(contact.title, assessment.target_roles or [contact.title]):
        return False
    if contact.geographic_scope:
        if not _valid_refs(contact.provenance.get("geographic_scope", []), contact, evidence):
            return False
        scope = fold_words(contact.geographic_scope)
        regional = any(word in scope for word in ("latam", "latinoamerica", "latin america", "global", "mundial"))
        explicit = {code for code, names in {"CO": ("colombia", "co"), "MX": ("mexico", "mx"),
                                            "US": ("united states", "estados unidos", "us"),
                                            "ES": ("espana", "spain"), "AR": ("argentina",), "BR": ("brasil", "brazil")}.items()
                    if any(mentions(scope, name) for name in names)}
        if not regional and explicit and company.operating_countries and not explicit.intersection(company.operating_countries):
            return False
    facts = _valid_refs(contact.employment_evidence_ids, contact, evidence)
    if any(item.kind == "observed" and employment_ended(item.excerpt or item.claim, contact.name, contact.title) for item in facts):
        return False
    return bool(facts) and any(item.kind == "observed" and not is_search_evidence(item) and
                              employment_fresh(item, company, limits, now) for item in facts)


def channel_is_usable(channel: Channel, contact: Contact, evidence: list[Evidence],
                      limits: CampaignLimits, now: datetime, company: Company) -> bool:
    if (channel.contact_id != contact.id or contact.company_id != company.id or
            channel.normalized_status == ChannelStatus.INVALID or
            channel.professional is not True or channel.direct is not True):
        return False
    facts = _valid_refs(channel.evidence_ids, contact, evidence)
    if not facts or any(item.retrieved_at > now for item in facts):
        return False
    structured = [item for item in facts if item.source_type == "provider" and item.provider == "hunter" and
                  item.contact_id == contact.id and item.external_reference is not None and
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
                    if item.updated_at or item.published_at else _current_directory(item))
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
                     limits: CampaignLimits, now: datetime, company: Company) -> BusinessStatus:
    if assessment.priority == Priority.EXCLUDED:
        return BusinessStatus.EXCLUDED
    if assessment.priority == Priority.LOW:
        return BusinessStatus.LOW_FIT
    if assessment.priority == Priority.INSUFFICIENT_EVIDENCE or company.identity_status != IdentityStatus.CONFIRMED:
        return BusinessStatus.INSUFFICIENT_EVIDENCE
    eligible = [contact for contact in contacts if validate_contact(contact, company, assessment, evidence, limits, now)]
    usable = [channel for contact in eligible for channel in contact.channels
              if channel_is_usable(channel, contact, evidence, limits, now, company)]
    if any(channel.type in (ChannelType.EMAIL, ChannelType.PHONE, ChannelType.WHATSAPP) for channel in usable):
        return BusinessStatus.READY_PREFERRED
    if usable:
        return BusinessStatus.READY_ALTERNATIVE
    if any(channel.normalized_status != ChannelStatus.INVALID for contact in eligible for channel in contact.channels):
        return BusinessStatus.NEEDS_CHANNEL_CONFIRMATION
    return BusinessStatus.QUALIFIED_NO_CONTACT


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
        if getattr(new, field) is not None:
            values[field] = getattr(new, field)
    if new.identity_status != IdentityStatus.PENDING:
        values["identity_status"] = new.identity_status
    values["provenance"] = {key: list(dict.fromkeys(old.provenance.get(key, []) + new.provenance.get(key, [])))
                            for key in old.provenance.keys() | new.provenance.keys()}
    values["employment_evidence_ids"] = list(dict.fromkeys(old.employment_evidence_ids + new.employment_evidence_ids))
    values["channels"] = list(channels.values())
    return Contact.model_validate(values)


