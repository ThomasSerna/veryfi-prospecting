"""Presentación y CSV seguro, independientes de la tecnología de interfaz."""

import csv
from io import StringIO
import json

from prospecting.pipeline import CampaignView, read_campaign


HUNTER_EMPLOYMENT_WARNING = ("Vigencia del puesto inferida de Hunter (correo verificado y fuente vista hace poco); "
                             "confirmar antes de contactar.")

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
}
READY = {"ready_preferred", "ready_alternative"}
STOP_MESSAGES = {
    "budget_exceeded": "Se agotó el presupuesto disponible. Revisa el consumo y concilia antes de reanudar.",
    "company_budget_exceeded": "Se alcanzó el tope de esta empresa. La campaña puede continuar con las demás.",
    "authorization": "Falta un permiso de esta sesión o su tope es insuficiente. Revisa las operaciones y autoriza de nuevo.",
    "account": "La cuenta no tiene un cupo comprobado suficiente. Revisa la configuración y el consumo registrado.",
    "price_unbounded": "No se puede acotar el costo de la operación. Se bloqueó la llamada.",
    "reservation_overrun": "El consumo superó una reserva. Concilia antes de continuar.",
    "budget_unknown": "Hay consumo desconocido. Debe conciliarse antes de continuar.",
    "campaign_time_limit": "Se agotó el tiempo activo de la campaña; se conservaron los resultados parciales.",
    "time_limit": "Se agotó el tiempo de investigación de esta empresa.",
    "duplicate_request": "La solicitud ya fue enviada y no se repite. Revisa su resultado y consumo; una respuesta de descubrimiento no guardada puede haberse perdido.",
    "campaign_already_running": "Otra ejecución sigue en curso en esta instancia. Espera a que termine.",
    "another_campaign_active": "Hay otra campaña activa. Ciérrala conservando los resultados antes de ejecutar esta.",
    "permission_denied": "El proveedor rechazó el acceso. Revisa los permisos de la cuenta.",
    "quota_exceeded": "El proveedor agotó la cuota. Comprueba el saldo y registra la conciliación.",
    "rate_limited": "El proveedor limitó las solicitudes. Conserva el resultado y revisa el plazo de reintento.",
    # Claude informa sus fallos con el código HTTP literal.
    "http_401": "El proveedor rechazó el acceso. Revisa los permisos de la cuenta.",
    "http_403": "El proveedor rechazó el acceso. Revisa los permisos de la cuenta.",
    "http_429": "El proveedor limitó las solicitudes. Conserva el resultado y revisa el plazo de reintento.",
    "timeout": "El proveedor no respondió dentro del plazo. La reserva se conserva hasta conciliar.",
    "invalid_response": "La respuesta del proveedor no cumple el contrato. La empresa queda pendiente.",
    "qualification_unavailable": "La calificación no está disponible. Revisa la configuración de Haiku y su autorización.",
    "insufficient_evidence": "La evidencia reunida no permite decidir; la empresa queda pendiente.",
    "contact_plan_exhausted": "Se agotó el esfuerzo de contactos asignado. Revisa los candidatos y canales encontrados.",
    "exclusion_review": "La exclusión necesita revisión humana antes de seguir investigando.",
    "duplicate_review": "La identidad o un posible duplicado necesita revisión antes de continuar.",
    "assessment_pending": "La calificación quedó pendiente. Revisa el fallo y la evidencia conservada.",
    "no_target_roles": "La calificación no dejó cargos de los perfiles de esta campaña; no se buscaron personas.",
    "contact_preconditions": "La empresa no cumple las condiciones para buscar contactos: identidad confirmada y prioridad alta o media.",
    "domain_unknown": "No se pudo confirmar el dominio oficial; la identidad queda pendiente.",
    "identity_unverified": "Ninguna página propia de la empresa confirmó su identidad; queda pendiente de revisión.",
    "name_unconfirmed": "La página propia no confirmó el nombre de la empresa; la identidad queda pendiente.",
    "country_unconfirmed": "No se confirmó la operación en los países de la campaña; la identidad queda pendiente.",
}
# Paradas previstas: la empresa terminó su plan con un resultado, no quedó pendiente ni falló.
STOP_OUTCOMES = {
    "preferred_channel_found": "Se encontró una persona pertinente con un canal preferido; la búsqueda de contactos terminó.",
    "people_limit": "Se investigó el máximo de personas previsto para esta prioridad; la búsqueda de contactos terminó.",
    "already_checked": "Los contactos ya se habían investigado y se reutilizaron sin repetir consultas.",
    "excluded_account": "La empresa figura en la lista de exclusiones; no se investigó más.",
    "duplicate_of": "Es un duplicado confirmado de otra empresa de esta campaña; se investiga una sola vez.",
    "low_fit": "El encaje es bajo con evidencia suficiente; no se buscaron contactos.",
}


def label(value):
    return "Pendiente" if value is None else LABELS.get(value, str(value))


def money(value):
    return "Desconocido" if value is None else f"USD {value:.6f}"


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
    return "La investigación quedó pendiente. Revisa el error y los datos guardados antes de reanudar."


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
    "contact_name", "title", "buying_role", "contact_eligible", "contact_ready",
    "email", "phone", "whatsapp", "linkedin", "other", "channels", "sources",
    "company_provenance", "contact_provenance", "review_status", "review_reason", "reviewed_at", "warnings",
)


def export_csv(view: CampaignView, *, include_all: bool = False) -> bytes:
    """Una fila por persona; recibe una lectura reciente del pipeline, nunca respuestas crudas."""
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
                "channels": json.dumps([channel.model_dump(mode="json") for channel in channels], ensure_ascii=False),
                "sources": json.dumps(sources, ensure_ascii=False),
                "company_provenance": json.dumps(company.model_dump(mode="json")["provenance"], ensure_ascii=False),
                "contact_provenance": json.dumps({} if contact is None else contact.model_dump(mode="json")["provenance"], ensure_ascii=False),
                "review_status": item.review_status, "review_reason": item.review_reason,
                "reviewed_at": None if item.reviewed_at is None else item.reviewed_at.isoformat(),
                "warnings": " | ".join(
                    ([HUNTER_EMPLOYMENT_WARNING] if person is not None and person.employment_basis == "hunter_signal" else [])
                    + [warning for channel in channels for warning in channel.warnings]),
            }
            row.update({kind: " | ".join(channel.value for channel in channels if channel.type == kind)
                        for kind in ("email", "phone", "whatsapp", "linkedin", "other")})
            writer.writerow({key: csv_text(value) if isinstance(value, str) or value is None else value for key, value in row.items()})
    return output.getvalue().encode("utf-8-sig")



def download_csv(db_path, campaign_id, *, include_all=False, account_allowances=None, exclusions_path=None):
    """Consulta al descargar con una conexión nueva, sin reutilizar una pantalla anterior."""
    current = read_campaign(db_path, campaign_id, account_allowances=account_allowances, exclusions_path=exclusions_path)
    if current.is_executing:
        raise ValueError("La campaña está ejecutándose; espera antes de exportar.")
    return export_csv(current, include_all=include_all)

