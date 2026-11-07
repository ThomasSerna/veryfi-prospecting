"""Presentación y CSV seguro, independientes de la tecnología de interfaz."""

import csv
from io import StringIO
import json
from urllib.parse import urlsplit

from prospecting.pipeline import CampaignView, read_campaign
from prospecting.sources import validate_public_url


HUNTER_EMPLOYMENT_WARNING = ("Vigencia inferida del historial de Hunter (correo verificado y fuente vista hace poco); "
                             "no prueba el puesto ni deja lista a la persona.")

LABELS = {
    "CO": "Colombia", "MX": "México",
    "fintech_software": "FinTech y software", "cpg_loyalty": "Consumo masivo y fidelización",
    "created": "Preparada", "running": "En investigación", "completed": "Terminada",
    "partial": "Parcial", "paused_budget": "Pausada por presupuesto o autorización", "failed": "Fallida",
    "discovered": "Descubrimiento", "identity_resolved": "Identidad resuelta", "researched": "Evidencia reunida",
    "assessed": "Calificación", "contacts_checked": "Contactos investigados",
    "high": "Alta", "medium": "Media", "low": "Baja",
    "ready_preferred": "Listo · canal preferido", "ready_alternative": "Listo · canal alternativo",
    "needs_channel_confirmation": "Falta confirmar canal", "qualified_no_contact": "Calificada sin contacto",
    "insufficient_evidence": "Evidencia insuficiente", "low_fit": "Encaje bajo", "excluded": "Excluida",
    "accepted": "Aceptado", "rejected": "Rechazado", "pending": "Pendiente",
    "verified": "Verificado", "published_professional": "Publicado profesionalmente",
    "accept_all": "Dominio acepta cualquier correo", "unknown": "Desconocido", "invalid": "Inválido",
    "manual_confirmed": "Confirmado manualmente", "email": "Correo", "phone": "Teléfono",
    "whatsapp": "WhatsApp", "linkedin": "LinkedIn", "other": "Otro canal",
    "business_champion": "Impulsor de negocio", "technical_champion": "Impulsor técnico",
    "economic_buyer": "Responsable económico",
    "document_need": "Necesidad documental", "offer_match": "Encaje con Veryfi",
    "scale_potential": "Potencial de escala", "adoption_capacity": "Capacidad de adopción",
    "opportunity_timing": "Momento de la oportunidad",
    "document_ocr_api": "OCR y API documental", "lens": "Lens", "antifraud": "Antifraude",
    "validation_enrichment": "Validación y enriquecimiento",
    "loyalty_whatsapp": "Soluciones de fidelización y WhatsApp",
    "name": "Nombre", "title": "Cargo", "domain": "Dominio", "entity_name": "Entidad",
    "entity_type": "Tipo de entidad", "operating_countries": "Países de operación", "segments": "Segmentos",
    "size": "Tamaño", "current_employment": "Empleo actual", "relevant_function": "Función pertinente",
    "geographic_scope": "Alcance geográfico",
    "primary": "Fuente original", "provider": "Proveedor",
    "search_result": "Búsqueda", "manual": "Confirmación manual",
}
CRITERION_LABELS = {
    1: "Señal fuerte",
    0.5: "Señal parcial",
    0: "Incompatible",
}
CRITERION_TONES = {
    1: "strong",
    0.5: "partial",
    0: "none",
}
MATCH_LABELS = {
    "role": "Cargo", "channel": "Canal", "identity": "Identidad", "employment": "Vigencia del empleo",
    "role:selected_role": "Cargo elegido en la calificación", "role:profile_role": "Otro cargo de los perfiles",
    "role:outside_profile": "Cargo fuera de los perfiles", "role:unknown": "Cargo pendiente",
    "channel:preferred_usable": "Correo, teléfono o WhatsApp utilizable",
    "channel:alternative_usable": "Canal alternativo confirmado",
    "channel:preferred_unconfirmed": "Correo, teléfono o WhatsApp sin comprobar",
    "channel:alternative_unconfirmed": "LinkedIn u otro canal sin confirmar", "channel:none": "Sin canal profesional",
    "identity:confirmed_complete": "Nombre completo e identidad confirmada",
    "identity:complete_pending": "Nombre completo; identidad sin confirmar",
    "identity:incomplete": "Nombre incompleto o pendiente",
    "employment:evidence": "Vigente según evidencia del puesto",
    "employment:hunter_signal": "Inferida del historial de Hunter; no prueba el puesto",
    "employment:unverified": "Sin comprobar",
    "identity_contradicted": "su identidad tiene contradicciones",
    "employment_ended": "una fuente indica que ya no ocupa el puesto",
    "scope_mismatch": "su alcance geográfico no cubre los países de la empresa",
}
# Vigencia del empleo (T18): estado, origen y motivo calculados al leer; solo la evidencia del puesto habilita.
EMPLOYMENT_LABELS = {
    "corporate_evidence": "Vigente según fuente corporativa o pública",
    "provider_claim:apollo": "Declarado por Apollo; sin evidencia del puesto",
    "provider_claim:hunter": "Inferido del historial de Hunter; sin evidencia del puesto",
    "contradicted": "Contradicho por una fuente",
    "unknown": "Sin comprobar",
}
EMPLOYMENT_REASONS = {
    "employment_ended": "Una fuente indica que ya no ocupa el puesto o que trabaja en otra entidad.",
    "title_changed": "Una fuente corporativa muestra otro cargo; revisa cuál está vigente.",
    "contradicted_source": "La fuente del puesto tiene contradicciones pendientes.",
    "future_date": "La fuente del puesto tiene una fecha futura.",
    "stale_source": "La fuente del puesto está vencida.",
    "undated_source": "La fuente no permite estimar la vigencia del puesto; requiere revisión.",
    "ambiguous_source": "La fuente no nombra a la persona; requiere revisión.",
    "title_unconfirmed": "Ninguna fuente vigente confirma el cargo actual; requiere revisión.",
    "incomplete_name": "Falta el nombre completo para contrastar el puesto.",
    "provider_claim_only": "Solo el proveedor declara el empleo; falta una fuente corporativa vigente.",
    "historical_inference": "Inferencia histórica de Hunter: correo verificado y fuente aún publicada, sin fecha del puesto.",
    "no_employment_evidence": "Sin evidencia del puesto.",
}
READY = {"ready_preferred", "ready_alternative"}
# Etapas acumuladas de persona (T16): «Pertinente» no exige canal ni evidencia del puesto; «Lista» sí.
PERSON_STAGE_LABELS = {
    "candidate": "Candidata",
    "identity_verified": "Identidad verificada",
    "relevant": "Pertinente",
    "channel_usable": "Pertinente con canal",
    "ready": "Lista",
}
ENRICHMENT_REJECTIONS = {
    "identity_unconfirmed": "Apollo no confirmó una coincidencia de identidad alta.",
    "identity_mismatch": "Apollo devolvió datos de otra persona; no se asignaron.",
    "entity_mismatch": "Apollo no confirmó que trabaje actualmente en esta entidad.",
}
STOP_MESSAGES = {
    "budget_exceeded": "Presupuesto disponible agotado.",
    "company_budget_exceeded": "Se alcanzó el tope de esta empresa.",
    "authorization": "Permiso ausente o tope insuficiente; autoriza de nuevo.",
    "account": "Cupo de cuenta insuficiente.",
    "price_unbounded": "Costo de operación no acotado.",
    "reservation_overrun": "Consumo superior a la reserva.",
    "budget_unknown": "Hay consumo pendiente de conciliación.",
    "campaign_time_limit": "Tiempo máximo de campaña alcanzado.",
    "time_limit": "Tiempo máximo de empresa alcanzado.",
    "duplicate_request": "La solicitud ya fue enviada y no se repite.",
    "campaign_already_running": "Otra ejecución sigue en curso.",
    "another_campaign_active": "Hay otra campaña activa.",
    "permission_denied": "El proveedor rechazó el acceso.",
    "quota_exceeded": "El proveedor agotó la cuota.",
    "rate_limited": "El proveedor limitó las solicitudes.",
    # Claude informa sus fallos con el código HTTP literal.
    "http_401": "El proveedor rechazó el acceso.",
    "http_403": "El proveedor rechazó el acceso.",
    "http_429": "El proveedor limitó las solicitudes.",
    "timeout": "Tiempo de espera agotado en el proveedor.",
    "invalid_response": "Respuesta inválida del proveedor; falta evidencia válida.",
    "qualification_unavailable": "Calificación no disponible.",
    "insufficient_evidence": "La evidencia no permite decidir.",
    "contact_plan_exhausted": "Búsqueda de contactos agotada.",
    "enrichment_limit": "Se agotó el tope de enriquecimientos antes de completar el objetivo de personas.",
    "exclusion_review": "Exclusión pendiente de revisión.",
    "duplicate_review": "Posible duplicado pendiente de revisión.",
    "assessment_pending": "La calificación quedó pendiente.",
    "no_target_roles": "Sin cargos objetivo en esta campaña.",
    "contact_preconditions": "No cumple las condiciones para buscar contactos.",
    "domain_unknown": "Dominio oficial sin confirmar.",
    "identity_unverified": "No se confirmó su identidad en fuentes propias.",
    "name_unconfirmed": "Nombre de la empresa sin confirmar.",
    "country_unconfirmed": "Operación en países de la campaña sin confirmar.",
}
# Paradas previstas: la empresa terminó su plan con un resultado, no quedó pendiente ni falló.
STOP_OUTCOMES = {
    "preferred_channel_found": "Se encontró un canal preferido.",
    "people_target_reached": "Se alcanzó el objetivo de personas pertinentes.",
    "people_limit": "Se alcanzó el máximo de personas evaluadas.",
    "already_checked": "Contactos reutilizados de una consulta previa.",
    "excluded_account": "Incluida en la lista de exclusiones.",
    "duplicate_of": "Es un duplicado confirmado en esta campaña.",
    "low_fit": "El encaje es bajo.",
}


def label(value):
    return "Pendiente" if value is None else LABELS.get(value, str(value))


def criterion_label(value):
    """Traduce el multiplicador de la rúbrica (1, 0.5, 0, None) a una etiqueta comercial legible."""
    if value is None or value == "":
        return "Sin evidencia"
    return CRITERION_LABELS.get(value, str(value))


def criterion_tone(value):
    """Variante semántica de presentación para el nivel de un criterio."""
    if value is None or value == "":
        return "unknown"
    return CRITERION_TONES.get(value, "unknown")


def evidence_pill(fact, number: int) -> dict[str, str | int]:
    """Resumen informativo de una fuente para píldoras de referencia cruzada."""
    source_type = getattr(fact, "source_type", None)
    provider = getattr(fact, "provider", None)
    if source_type == "provider" and provider:
        origin = str(provider).capitalize()
    else:
        origin = label(source_type)
    host = ""
    raw_url = getattr(fact, "url", None)
    if raw_url:
        try:
            valid = validate_public_url(str(raw_url))
            if valid:
                parsed = urlsplit(valid).hostname or ""
                host = parsed[4:] if parsed.startswith("www.") else parsed
        except ValueError:
            host = ""
    summary = f"{origin} · {host}" if host else origin
    claim = (getattr(fact, "claim", "") or "").strip()
    retrieved = getattr(fact, "retrieved_at", None)
    date_str = retrieved.strftime("%Y-%m-%d") if hasattr(retrieved, "strftime") else ""
    title = f"{claim} ({date_str})" if claim and date_str else (claim or summary)
    return {
        "number": number,
        "label": f"{summary} #{number}",
        "title": title,
    }


def match_label(value):
    """Componentes, niveles y bloqueos del match; el texto de un nivel depende de su componente."""
    key = f"{value.name}:{value.level}" if hasattr(value, "level") else str(value)
    return MATCH_LABELS.get(key, key)


def employment_label(status):
    """Estado de la vigencia del empleo; una afirmación del proveedor nombra su origen."""
    if status is None or status == "":
        return "Sin comprobar"
    key = f"{status.state}:{status.origin}" if status.state == "provider_claim" else status.state
    return EMPLOYMENT_LABELS.get(key, EMPLOYMENT_LABELS["unknown"])


def employment_reason(status):
    """Motivo en lenguaje comercial; vacío cuando la evidencia del puesto está vigente."""
    reason = getattr(status, "reason", None)
    return "" if reason is None else EMPLOYMENT_REASONS.get(reason, "Comprobación de empleo pendiente.")


def money(value):
    return "Desconocido" if value is None else f"USD {value:.6f}"


def money_summary(value):
    """Formato compacto para titulares de presupuesto; conserva hasta 6 decimales si hay fracciones de centavo."""
    if value is None:
        return "Desconocido"
    full = f"{value:.6f}"
    whole, decimals = full.split(".")
    trimmed = decimals.rstrip("0")
    if len(trimmed) <= 2:
        return f"USD {value:.2f}"
    return f"USD {whole}.{trimmed}"


def campaign_title(campaign):
    """Nombre legible para ventas a partir de países y segmentos."""
    if campaign is None:
        return "Campaña"
    countries = ", ".join(label(code) for code in getattr(campaign, "countries", ()) or ())
    segments = ", ".join(label(seg) for seg in getattr(campaign, "segments", ()) or ())
    if countries and segments:
        return f"{countries} · {segments}"
    return countries or segments or f"Campaña {str(campaign.id)[:8]}"


def campaign_short_title(campaign):
    """Etiqueta breve para barra lateral y migas de pan."""
    if campaign is None:
        return "Campaña"
    codes = ", ".join(getattr(campaign, "countries", ()) or ())
    segs = list(getattr(campaign, "segments", ()) or ())
    first_seg = label(segs[0]) if segs else ""
    if len(segs) > 1:
        first_seg = f"{first_seg} +{len(segs) - 1}"
    if codes and first_seg:
        return f"{codes} · {first_seg}"
    return codes or first_seg or f"Campaña {str(campaign.id)[:8]}"


def ineligible_reason(person):
    """Explica en lenguaje comercial por qué una persona aún no admite confirmación manual."""
    if person is None or getattr(person, "eligible", False):
        return ""
    match = getattr(person, "match", None)
    if match is not None and getattr(match, "blocked_reason", None):
        return f"No disponible para confirmación manual porque {match_label(match.blocked_reason)}."
    contact = getattr(person, "contact", None)
    if contact is None:
        return "Faltan datos comprobados de la persona."
    if not contact.name_complete or contact.identity_status != "confirmed":
        return "Requiere nombre completo e identidad confirmada."
    employment = getattr(person, "employment", None)
    if employment is not None and employment.state != "corporate_evidence":
        return f"Requiere evidencia vigente del puesto. {employment_reason(employment)}".strip()
    if not contact.current_employment:
        return "Requiere empleo actual confirmado."
    if not contact.relevant_function:
        return "Requiere cargo pertinente."
    return "Comprobaciones pendientes."


def person_stage_label(stage):
    return PERSON_STAGE_LABELS.get(stage, "Etapa pendiente")


def enrichment_rejection(code):
    return ENRICHMENT_REJECTIONS.get(code, "Apollo no confirmó a esta persona.") if code else ""


def people_summary(people):
    """Resumen de personas de una empresa; sin política no hay objetivo, nunca un objetivo de cero."""
    if people is None:
        return ""
    parts = [f"{people.candidates} candidatas", f"{people.relevant} pertinentes", f"{people.ready} listas"]
    if people.target is not None:
        parts.insert(0, f"Objetivo {people.target}")
    return " · ".join(parts)


def _stop_key(reason, messages):
    return next((key for key in messages if reason == key or reason.startswith(key + "_") or reason.startswith(key + ":")), None)


def stop_message(reason):
    for messages in (STOP_OUTCOMES, STOP_MESSAGES):
        key = _stop_key(reason, messages)
        if key is not None:
            # Un motivo compuesto (`etapa:motivo`) añade la explicación del motivo interno cuando la tiene.
            inner = reason[len(key) + 1:] if reason.startswith(key + ":") else ""
            detail = _stop_key(inner, STOP_MESSAGES) if inner else None
            return messages[key] if detail is None else f"{messages[key]} {STOP_MESSAGES[detail]}"
    return "La investigación quedó pendiente."


def stop_tone(reason):
    """Una parada prevista se informa; las demás piden revisar antes de seguir."""
    return "info" if _stop_key(reason, STOP_OUTCOMES) is not None else "warning"


def csv_text(value):
    """Prefijo de texto y tabulación: impide fórmulas al abrir el CSV en hojas de cálculo."""
    if value is None:
        return ""
    text = str(value)
    stripped = text.lstrip()
    prefix = text[:len(text) - len(stripped)]
    if (any(ord(char) < 32 for char in prefix) or stripped and (ord(stripped[0]) < 32 or ord(stripped[0]) == 127)
            or stripped.startswith(("=", "+", "-", "@", "＝", "＋", "－", "＠", "\ufeff"))):
        return "'\t" + text
    return text


CSV_FIELDS = (
    "campaign_id", "company_id", "contact_id", "company_name", "domain", "entity_name",
    "countries", "segments", "stage", "business_status", "stored_business_status", "stop_reason", "error_message",
    "fit_score", "coverage", "priority", "products", "assessment_id", "rubric_version", "criteria",
    "contact_name", "title", "buying_role", "contact_eligible", "contact_ready", "person_stage",
    "people_candidates", "people_relevant", "people_ready", "people_target", "people_policy_version",
    "employment_status", "employment_reason",
    "contact_match", "contact_match_version", "contact_match_blocked", "contact_match_detail",
    "email", "phone", "whatsapp", "linkedin", "other", "channels", "sources",
    "company_provenance", "contact_provenance", "review_status", "review_reason", "reviewed_at", "warnings",
)


def export_csv(view: CampaignView, *, include_all: bool = False) -> bytes:
    """Una fila por persona, en el orden de match de la lectura; recibe una lectura reciente, nunca respuestas crudas."""
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writeheader()
    for result in view.companies:
        if not include_all and result.business_status not in READY:
            continue
        people = result.contacts if include_all else [person for person in result.contacts if person.eligible and person.usable_channels]
        for person in people or ([None] if include_all else []):
            company, item, assessment = result.company, result.run_item, result.assessment
            contact = None if person is None else person.contact
            match = None if person is None else person.match
            channels = [] if person is None else contact.channels if include_all else person.usable_channels
            sources = [fact.model_dump(mode="json") for fact in result.evidence
                       if fact.contact_id is None or contact is not None and fact.contact_id == contact.id]
            row = {
                "campaign_id": view.campaign.id, "company_id": company.id, "contact_id": None if contact is None else contact.id,
                "company_name": company.name, "domain": company.domain, "entity_name": company.entity_name,
                "countries": " | ".join(company.operating_countries or []), "segments": " | ".join(company.segments or []),
                "stage": item.stage, "business_status": result.business_status, "stored_business_status": item.business_status,
                "stop_reason": item.stop_reason, "error_message": item.error_message,
                "fit_score": None if assessment is None else assessment.fit_score,
                "coverage": None if assessment is None else assessment.coverage,
                "priority": None if assessment is None else assessment.priority,
                "products": " | ".join([] if assessment is None else assessment.products),
                "assessment_id": None if assessment is None else assessment.id, "rubric_version": view.campaign.rubric_version,
                "criteria": json.dumps({} if assessment is None else assessment.model_dump(mode="json")["criteria"], ensure_ascii=False),
                "contact_name": None if contact is None else contact.name, "title": None if contact is None else contact.title,
                "buying_role": None if contact is None else contact.buying_role,
                "contact_eligible": None if person is None else person.eligible,
                "contact_ready": None if person is None else person.eligible and bool(person.usable_channels),
                "person_stage": None if person is None else person.stage,
                # Conteos de la empresa; sin evaluación o sin política quedan vacíos, nunca 0 inventado.
                "people_candidates": None if result.people is None else result.people.candidates,
                "people_relevant": None if result.people is None else result.people.relevant,
                "people_ready": None if result.people is None else result.people.ready,
                "people_target": None if result.people is None else result.people.target,
                "people_policy_version": None if result.people is None else result.people.policy_version,
                "employment_status": None if person is None else person.employment.state,
                "employment_reason": None if person is None else person.employment.reason,
                # Sin match la celda queda vacía, nunca 0.
                "contact_match": None if match is None else match.score,
                "contact_match_version": None if match is None else match.version,
                "contact_match_blocked": None if match is None else match.blocked_reason,
                "contact_match_detail": None if match is None else json.dumps(
                    [item.model_dump(mode="json") for item in match.components], ensure_ascii=False),
                "channels": json.dumps([channel.model_dump(mode="json") for channel in channels], ensure_ascii=False),
                "sources": json.dumps(sources, ensure_ascii=False),
                "company_provenance": json.dumps(company.model_dump(mode="json")["provenance"], ensure_ascii=False),
                "contact_provenance": json.dumps({} if contact is None else contact.model_dump(mode="json")["provenance"], ensure_ascii=False),
                "review_status": item.review_status, "review_reason": item.review_reason,
                "reviewed_at": None if item.reviewed_at is None else item.reviewed_at.isoformat(),
                "warnings": " | ".join(
                    ([HUNTER_EMPLOYMENT_WARNING] if person is not None and person.employment.state == "provider_claim"
                     and person.employment.origin == "hunter" else [])
                    + [warning for channel in channels for warning in channel.warnings]),
            }
            row.update({kind: " | ".join(channel.value for channel in channels if channel.type == kind)
                        for kind in ("email", "phone", "whatsapp", "linkedin", "other")})
            writer.writerow({key: csv_text(value) if isinstance(value, str) or value is None else value for key, value in row.items()})
    return output.getvalue().encode("utf-8-sig")


def download_csv(db_path, campaign_id, *, include_all=False, account_allowances=None, exclusions_path=None,
                 contact_match_path=None):
    """Consulta al descargar con una conexión nueva, sin reutilizar una pantalla anterior."""
    current = read_campaign(db_path, campaign_id, account_allowances=account_allowances, exclusions_path=exclusions_path,
                            contact_match_path=contact_match_path)
    if current.is_executing:
        raise ValueError("La campaña está ejecutándose; espera antes de exportar.")
    return export_csv(current, include_all=include_all)
