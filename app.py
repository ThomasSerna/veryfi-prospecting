"""Interfaz local de campañas, revisión humana y exportación segura."""

import csv
from decimal import Decimal
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from pydantic import ValidationError
import streamlit as st

from prospecting.models import Campaign, CampaignFilters, VeryfiConfig
from prospecting.pipeline import (
    AuthorizationInput, CampaignView, confirm_alternative_channel, execute_campaign,
    finish_campaign, list_saved_campaigns, load_provider_access, prepare_campaign,
    provider_operations, read_campaign, review_company,
)
from prospecting.sources import validate_public_url


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "prospecting.sqlite3"
ACCESS_PATH = ROOT / "data" / "provider-access.json"
EXCLUSIONS_PATH = ROOT / "data" / "exclusions.json"
CONFIG_PATH = ROOT / "config" / "veryfi.json"

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
    "timeout": "El proveedor no respondió dentro del plazo. La reserva se conserva hasta conciliar.",
    "invalid_response": "La respuesta del proveedor no cumple el contrato. La empresa queda pendiente.",
    "qualification_unavailable": "La calificación no está disponible. Revisa la configuración de Haiku y su autorización.",
    "insufficient_evidence": "La evidencia reunida no permite decidir; la empresa queda pendiente.",
    "contact_plan_exhausted": "Se agotó el esfuerzo de contactos asignado. Revisa los candidatos y canales encontrados.",
    "exclusion_review": "La exclusión necesita revisión humana antes de seguir investigando.",
    "duplicate_review": "La identidad o un posible duplicado necesita revisión antes de continuar.",
    "assessment_pending": "La calificación quedó pendiente. Revisa el fallo y la evidencia conservada.",
}


def label(value):
    return "Pendiente" if value is None else LABELS.get(value, str(value))


def money(value):
    return "Desconocido" if value is None else f"USD {value:.6f}"


def stop_message(reason):
    key = next((key for key in STOP_MESSAGES if reason == key or reason.startswith(key + "_") or reason.startswith(key + ":")), None)
    return STOP_MESSAGES.get(key, "La investigación quedó pendiente. Revisa el error y los datos guardados antes de reanudar.")


def show_stop(reason):
    st.text(stop_message(reason))
    st.text(f"Motivo registrado: {reason}")


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
                "warnings": " | ".join(warning for channel in channels for warning in channel.warnings),
            }
            row.update({kind: " | ".join(channel.value for channel in channels if channel.type == kind)
                        for kind in ("email", "phone", "whatsapp", "linkedin", "other")})
            writer.writerow({key: csv_text(value) if isinstance(value, str) or value is None else value for key, value in row.items()})
    return output.getvalue().encode("utf-8-sig")


def show_error(error):
    st.error("No se pudo completar la operación. Los datos guardados se conservan.")
    if isinstance(error, ValidationError):
        st.text("Revisa los campos obligatorios y los límites; los datos no cumplen el contrato.")
    elif isinstance(error, sqlite3.Error):
        st.text("No se pudo leer o actualizar SQLite. Conserva la base y revisa su compatibilidad.")
    else:
        st.text(str(error))


def configuration_form(config):
    st.subheader("Preparar una campaña")
    st.caption("Selecciona el mercado y la muestra. Preparar guarda los criterios sin consumir proveedores.")
    with st.form("campaign_configuration"):
        left, right = st.columns(2)
        countries = left.multiselect("Países", config.defaults.countries, default=config.defaults.countries, format_func=label, placeholder="Seleccionar países")
        segments = right.multiselect("Segmentos", config.defaults.segments, default=config.defaults.segments, format_func=label, placeholder="Seleccionar segmentos")
        keywords = st.text_input("Palabras clave opcionales", help="Separa las palabras o frases con comas.")
        maximum = st.number_input("Máximo de empresas", min_value=1, max_value=config.defaults.max_companies, value=config.defaults.max_companies)
        st.caption(f"Topes: {money(config.defaults.budget.campaign_usd)} por campaña · {money(config.defaults.budget.company_usd)} por empresa.")
        submitted = st.form_submit_button("Preparar campaña", type="primary")
    if submitted:
        campaign = Campaign(id=st.session_state.setdefault("draft_id", uuid4()), countries=countries, segments=segments,
                            filters=CampaignFilters(keywords=[word.strip() for word in keywords.split(",") if word.strip()]),
                            max_companies=maximum, config_snapshot=config, rubric_version="rubric_v1")
        saved = prepare_campaign(DB_PATH, campaign)
        st.session_state["campaign_to_open"] = saved.id
        st.rerun()


def budget_panel(view):
    budget = view.budget
    columns = st.columns(4)
    columns[0].metric("Confirmado · campaña", money(budget.campaign.confirmed))
    columns[1].metric("Estimado · campaña", money(budget.campaign.estimated))
    columns[2].metric("Reservado · campaña", money(budget.campaign.reserved))
    columns[3].metric("Disponible · campaña", money(budget.campaign.available))
    st.caption(f"Acumulado global: {money(budget.global_budget.exposure)} / {money(budget.global_budget.limit)} · "
               f"Límite operativo: {money(budget.operating.limit)} · Margen: {money(view.campaign.limits.budget.uncertainty_usd)}. "
               f"Pendiente de conciliación: {money(budget.campaign.pending)}. "
               "La estimación no reemplaza la facturación; desconocido no equivale a cero.")
    with st.expander("Detalle de presupuesto y cuentas"):
        st.text(f"Exposición operativa: {money(budget.operating.exposure)} · Disponible: {money(budget.operating.available)}")
        st.text(f"Desembolso global: {money(budget.outlay_usd)} · Equivalente de créditos gratuitos: {money(budget.free_credit_equivalent.exposure)}")
        for account in budget.accounts:
            st.text(f"{account.provider} · {account.account_ref} · {account.funding_source}")
            st.text(f"Créditos confirmados: {account.credits.confirmed} · Estimados: {account.credits.estimated} · "
                    f"Reservados: {account.credits.reserved} · Pendientes: {account.credits.pending} · "
                    f"Disponibles: {account.credits.available if account.credits.available is not None else 'Desconocido'}")
            st.text(f"Costo confirmado: {money(account.cost.confirmed)} · Estimado: {money(account.cost.estimated)} · "
                    f"Reservado: {money(account.cost.reserved)} · Pendiente: {money(account.cost.pending)}")
    if budget.reservation_overrun or budget.operating.unknown or budget.campaign.unknown:
        st.warning("Hay consumo incierto o una reserva excedida. Se conserva hasta su conciliación; no se libera para ejecutar otra vez.")


def result_rows(view):
    return [{"company": result.company.name, "countries": ", ".join(label(code) for code in result.company.operating_countries or []),
             "segments": ", ".join(label(segment) for segment in result.company.segments or []),
             "priority": label(None if result.assessment is None else result.assessment.priority),
             "fit_score": None if result.assessment is None else result.assessment.fit_score,
             "coverage": None if result.assessment is None else result.assessment.coverage,
             "stage": label(result.run_item.stage), "status": label(result.business_status), "review": label(result.run_item.review_status)}
            for result in view.companies]


def execute_form(view, access):
    if view.is_executing or view.campaign.status == "completed":
        return
    if access is None:
        st.info("Para ejecutar, configura los cupos y el acceso comprobado en data/provider-access.json y las claves en variables de entorno.")
        return
    with st.expander("Autorizar y ejecutar la campaña", expanded=view.campaign.status == "created"):
        st.caption("Cada ejecución o reanudación necesita autorización nueva del responsable. No se pide aprobación entre empresas.")
        approvals = []
        with st.form(f"authorization_{view.campaign.id}"):
            responsible = st.text_input("Responsable del cupo")
            reference = st.text_input("Referencia de la autorización", help="Referencia local de esta aprobación; no escribas claves ni datos de contactos.")
            for provider, operation, account_ref in provider_operations(access):
                account = next(item for item in view.budget.accounts if (item.provider, item.account_ref) == (provider, account_ref))
                st.text(f"{provider} / {operation} · Cuenta: {account_ref}")
                key_name = {"tavily": "TAVILY_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "hunter": "HUNTER_API_KEY"}[provider]
                key_present = bool(os.environ.get(key_name, "").strip())
                st.caption("Clave local configurada; acceso y cupo según el archivo comprobado." if key_present
                           else f"Falta configurar {key_name} en el entorno del servidor.")
                enabled = st.checkbox(f"Autorizar {provider} / {operation}", key=f"allow_{provider}_{operation}", disabled=not key_present)
                left, right = st.columns(2)
                cost = left.number_input("Tope USD de la operación", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"cost_{provider}_{operation}")
                credits = right.number_input("Tope de créditos de la operación", min_value=0.0, value=0.0, step=0.5, key=f"credits_{provider}_{operation}")
                st.caption(f"Saldo controlado: {money(account.cost.available)} · "
                           f"Créditos: {account.credits.available if account.credits.available is not None else 'Sin cupo conocido'}. "
                           "Los topes se validan antes de cualquier llamada.")
                if enabled:
                    approvals.append((provider, operation, account_ref, cost, credits))
            confirmed = st.checkbox("Soy responsable del cupo y autorizo únicamente las operaciones y topes seleccionados.")
            submitted = st.form_submit_button("Autorizar y ejecutar" if view.campaign.status == "created" else "Autorizar y reanudar", type="primary")
        if submitted:
            if not confirmed or not responsible.strip() or not reference.strip() or not approvals:
                st.error("Indica responsable, referencia, al menos una operación y confirma la autorización explícita.")
                return
            permissions = [AuthorizationInput(provider=provider, operation=operation, account_ref=account,
                                              max_cost_usd=Decimal(str(cost)), max_credits=Decimal(str(credits)),
                                              responsible=responsible, source_reference=reference)
                           for provider, operation, account, cost, credits in approvals]
            with st.status("Investigando · el descubrimiento tiene progreso indeterminado", expanded=True) as status:
                progress = st.empty()
                partial = st.empty()

                def update(event):
                    current = read_campaign(DB_PATH, view.campaign.id, account_allowances=access.account_allowances, exclusions_path=EXCLUSIONS_PATH)
                    count = sum(result.run_item.stage == "completed" for result in current.companies)
                    progress.progress(count / max(len(current.companies), 1), text=f"{count} de {len(current.companies)} empresas terminadas · {label(event.stage)}")
                    partial.dataframe(result_rows(current), hide_index=True, column_config=table_columns(), alt="Resultados parciales de la campaña")
                    status.update(label=f"Investigando · {label(event.stage)} · exposición de campaña {money(current.budget.campaign.exposure)}")

                report = execute_campaign(DB_PATH, view.campaign.id, access=access, approvals=permissions, progress=update, exclusions_path=EXCLUSIONS_PATH)
                status.update(label=label(report.status), state="error" if report.status == "failed" else "complete", expanded=False)
                if report.stop_reason:
                    show_stop(report.stop_reason)


def table_columns():
    return {"company": st.column_config.TextColumn("Empresa", width="medium"), "countries": "País", "segments": "Segmento",
            "priority": st.column_config.TextColumn("Prioridad", width="small"),
            "fit_score": st.column_config.NumberColumn("Encaje", format="%.1f", width=110),
            "coverage": st.column_config.NumberColumn("Cobertura", format="percent"),
            "stage": "Etapa", "status": st.column_config.TextColumn("Disponibilidad", width="medium"),
            "review": st.column_config.TextColumn("Revisión humana", width="small")}


def show_contact(person, view):
    contact = person.contact
    st.text(f"{contact.name or 'Nombre pendiente'} · {contact.title or 'Cargo pendiente'}")
    st.text(f"Función en la compra: {label(contact.buying_role)} · Persona pertinente y vigente: {'Sí' if person.eligible else 'Pendiente'}")
    for channel in contact.channels:
        st.text(f"{label(channel.type)}: {channel.value}")
        st.text(f"Estado: {label(channel.normalized_status)} · Original del proveedor: {channel.provider_status or 'Sin dato'}")
        st.text(f"Consulta: {channel.retrieved_at.isoformat()} · Verificación: {channel.verified_at.isoformat() if channel.verified_at else 'Sin fecha'}")
        st.text(f"Confirmación manual: {channel.manual_confirmed_at.isoformat() if channel.manual_confirmed_at else 'Pendiente'}")
        if channel.type == "email":
            st.caption("La publicación corporativa ofrece un contacto; no garantiza entregabilidad.")
        if channel.type in ("phone", "whatsapp"):
            st.caption("El formato comprobado no garantiza que el canal atienda.")
        for warning in channel.warnings:
            st.text(warning)
        if channel.type not in ("linkedin", "other") or channel.normalized_status == "invalid":
            continue
        key = f"confirm_{contact.id}_{channel.type}_{channel.value}"
        with st.form(key):
            reason = st.text_area("Motivo de la confirmación", key=f"reason_{key}")
            confirmed = st.checkbox("He comprobado desde mi cuenta que puedo contactar directamente a esta persona por este canal, sin enviar mensajes.", key=f"checked_{key}")
            submitted = st.form_submit_button("Guardar confirmación manual", disabled=view.is_executing or not person.eligible)
        if submitted:
            confirm_alternative_channel(DB_PATH, view.campaign.id, contact.id, channel.type, channel.value, reason=reason, confirmed=confirmed)
            st.rerun()


def company_detail(result, view):
    company, item, assessment = result.company, result.run_item, result.assessment
    st.subheader("Ficha de empresa")
    st.text(company.name)
    st.text(f"Entidad: {company.entity_name or 'Pendiente'} · Dominio: {company.domain or 'Pendiente'}")
    st.text(f"Estado técnico: {label(item.stage)} · Disponibilidad actual: {label(result.business_status)} · Revisión: {label(item.review_status)}")
    if result.business_status != item.business_status:
        st.warning("La disponibilidad actual difiere de la guardada: se vuelve a comprobar la vigencia al consultar y exportar.")
    if item.stop_reason:
        show_stop(item.stop_reason)
    if item.error_message:
        st.text(f"Fallo en {label(item.error_stage)}: {item.error_message}")
    if assessment:
        st.text(assessment.explanation)
        st.text(f"Productos candidatos: {', '.join(assessment.products) or 'Pendientes'} · Rúbrica: {assessment.rubric_version}")
        st.caption("El encaje mide compatibilidad con las reglas propuestas, no probabilidad de compra.")
        with st.expander("Puntuación y criterios", expanded=True):
            st.dataframe([{"criterion": label(name), "value": criterion.value, "reason": criterion.justification,
                           "evidence_ids": ", ".join(str(id) for id in criterion.evidence_ids)}
                          for name, criterion in assessment.criteria.items()], hide_index=True,
                         column_config={"criterion": "Criterio", "value": "Valor", "reason": "Justificación", "evidence_ids": "Evidencia"},
                         placeholder="Desconocido", alt="Desglose de la puntuación")
    with st.expander("Evidencia y procedencia"):
        for fact in result.evidence:
            st.text(f"{fact.id} · {fact.source_type} · {fact.retrieved_at.isoformat()}")
            st.text(fact.claim)
            if fact.excerpt:
                st.text(fact.excerpt)
            if fact.published_at or fact.updated_at:
                st.text(f"Publicación: {fact.published_at} · Actualización: {fact.updated_at}")
            if fact.provider:
                st.text(f"Proveedor: {fact.provider} · Referencia: {fact.external_reference}")
            if fact.contradiction_ids:
                st.text(f"Contradicciones: {', '.join(str(id) for id in fact.contradiction_ids)}")
            url = validate_public_url(str(fact.url)) if fact.url else None
            if url:
                st.link_button("Abrir fuente pública", url)
    with st.expander("Personas y canales", expanded=True):
        if not result.contacts:
            st.info("Todavía no hay personas identificadas. La empresa conserva su calificación y motivo.")
        for person in result.contacts:
            show_contact(person, view)
    with st.form(f"review_{company.id}"):
        status = st.selectbox("Revisión humana", ["pending", "accepted", "rejected"],
                              index=["pending", "accepted", "rejected"].index(item.review_status), format_func=label)
        reason = st.text_area("Motivo de la revisión", value=item.review_reason or "")
        submitted = st.form_submit_button("Guardar revisión", disabled=view.is_executing)
    if submitted:
        review_company(DB_PATH, view.campaign.id, company.id, status=status, reason=reason)
        st.rerun()


def results_panel(view):
    st.subheader("Resultados y revisión")
    st.caption("Listo según reglas y aceptado por Veryfi son decisiones distintas. Fechas de procedencia en UTC.")
    if not view.companies:
        st.info("La campaña aún no tiene empresas descubiertas.")
        return
    columns = st.columns(4)
    countries = columns[0].multiselect("Filtrar país", view.campaign.countries, format_func=label, placeholder="Todos")
    segments = columns[1].multiselect("Filtrar segmento", view.campaign.segments, format_func=label, placeholder="Todos")
    priorities = columns[2].multiselect("Filtrar prioridad", ["high", "medium", "low", "insufficient_evidence", "excluded"], format_func=label, placeholder="Todas")
    availability = columns[3].multiselect("Filtrar canal", sorted({result.business_status for result in view.companies if result.business_status}), format_func=label, placeholder="Todos")
    filtered = [result for result in view.companies
                if (not countries or set(countries).intersection(result.company.operating_countries or []))
                and (not segments or set(segments).intersection(result.company.segments or []))
                and (not priorities or result.assessment is not None and result.assessment.priority in priorities)
                and (not availability or result.business_status in availability)]
    order = {value: index for index, value in enumerate(("high", "medium", "insufficient_evidence", "low", "excluded"))}
    filtered.sort(key=lambda result: (order.get(None if result.assessment is None else result.assessment.priority, 2),
                                     -(result.assessment.fit_score or 0) if result.assessment else 0, result.company.name))
    st.dataframe(result_rows(view.model_copy(update={"companies": filtered})), hide_index=True,
                 column_config=table_columns(), column_order=["company", "priority", "status", "review", "fit_score", "coverage", "countries", "segments", "stage"],
                 placeholder="Desconocido", alt="Empresas de la campaña")
    if filtered:
        by_id = {result.company.id: result for result in filtered}
        selected = st.selectbox("Abrir ficha", list(by_id), format_func=lambda id: by_id[id].company.name,
                                key=f"company_selection_{view.campaign.id}")
        company_detail(by_id[selected], view)
    else:
        st.info("Ninguna empresa coincide con estos filtros.")


def download_csv(db_path, campaign_id, *, include_all=False, account_allowances=None, exclusions_path=None):
    """Se ejecuta al descargar, en su propio hilo y con una conexión nueva, sin llamadas Streamlit."""
    current = read_campaign(db_path, campaign_id, account_allowances=account_allowances, exclusions_path=exclusions_path)
    if current.is_executing:
        raise ValueError("La campaña está ejecutándose; espera antes de exportar.")
    return export_csv(current, include_all=include_all)


def downloads(view, access):
    st.subheader("Exportar campaña")
    st.caption("La descarga incluye la campaña completa, sin limitarse a los filtros de la tabla. La revisión humana se conserva en el CSV.")
    if view.is_executing:
        st.info("La exportación estará disponible cuando termine o se interrumpa la investigación.")
        return
    path, campaign_id = DB_PATH, view.campaign.id
    accounts = None if access is None else access.account_allowances
    exclusions_path = EXCLUSIONS_PATH
    left, right = st.columns(2)
    left.download_button("Descargar prospectos listos", lambda: download_csv(path, campaign_id, account_allowances=accounts, exclusions_path=exclusions_path), file_name=f"prospectos-listos-{view.campaign.id}.csv",
                         mime="text/csv", on_click="ignore", disabled=not any(person.eligible and person.usable_channels
                         for result in view.companies if result.business_status in READY for person in result.contacts))
    right.download_button("Descargar todos los resultados", lambda: download_csv(path, campaign_id, include_all=True, account_allowances=accounts, exclusions_path=exclusions_path), file_name=f"resultados-{view.campaign.id}.csv",
                          mime="text/csv", on_click="ignore", disabled=not view.companies)


def main():
    st.set_page_config(page_title="Veryfi Prospecting", page_icon=":material/travel_explore:", layout="wide")
    st.title("Veryfi Prospecting")
    st.caption("Investiga empresas, revisa evidencia y prepara prospectos para ventas. El contacto se realiza fuera de la aplicación.")
    try:
        config = VeryfiConfig.model_validate_json(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        st.error("No se pudo validar config/veryfi.json. Corrige la configuración antes de continuar.")
        return
    try:
        campaigns = list_saved_campaigns(DB_PATH)
        access = None
        if ACCESS_PATH.exists():
            try:
                access = load_provider_access(ACCESS_PATH)
            except ValueError as error:
                show_error(error)
        if "campaign_to_open" in st.session_state:
            st.session_state["selected_campaign"] = st.session_state.pop("campaign_to_open")
        if "selected_campaign" not in st.session_state:
            active = next((campaign for campaign in campaigns if campaign.status in ("running", "paused_budget")), None)
            st.session_state["selected_campaign"] = active.id if active else campaigns[-1].id if campaigns else None
        by_id = {campaign.id: campaign for campaign in campaigns}
        st.sidebar.title("Campañas")
        selected = st.sidebar.selectbox("Historial", [None, *reversed(by_id)], key="selected_campaign",
                                       format_func=lambda id: "Nueva campaña" if id is None else f"{by_id[id].created_at:%d/%m %H:%M} UTC · {label(by_id[id].status)} · {str(id)[:8]}")
        if selected is None and st.session_state.get("last_selection") is not None:
            st.session_state["draft_id"] = uuid4()
        st.session_state["last_selection"] = selected
        st.sidebar.caption("Instancia local · una campaña activa · datos y consumo persistidos en SQLite")
        if selected is None:
            configuration_form(config)
            return
        view = read_campaign(DB_PATH, selected, account_allowances=None if access is None else access.account_allowances, exclusions_path=EXCLUSIONS_PATH)
        st.subheader("Campaña")
        st.text(f"{label(view.campaign.status)} · {str(view.campaign.id)}")
        st.caption(f"{', '.join(label(code) for code in view.campaign.countries)} · "
                   f"{', '.join(label(segment) for segment in view.campaign.segments)} · Hasta {view.campaign.max_companies} empresas")
        if view.exclusions_status != "validated":
            st.warning("Lista de exclusiones ausente o sin confirmar. El estado se conserva explícitamente; no se supone que no existan exclusiones.")
        if view.is_executing:
            st.info("Hay una investigación en curso en esta instancia. La revisión, el cierre y la exportación esperan a que termine o se interrumpa.")
        if view.campaign.status in ("running", "partial", "paused_budget", "failed"):
            st.caption("Reanudar conserva checkpoints y consumo. Si se interrumpió el descubrimiento, las respuestas todavía no guardadas pueden perderse y las consultas enviadas no se repiten.")
        budget_panel(view)
        execute_form(view, access)
        view = read_campaign(DB_PATH, selected, account_allowances=None if access is None else access.account_allowances, exclusions_path=EXCLUSIONS_PATH)
        if view.campaign.status in ("running", "paused_budget") and st.button("Cerrar campaña conservando resultados", disabled=view.is_executing):
            finish_campaign(DB_PATH, selected)
            st.rerun()
        results_panel(view)
        downloads(view, access)
    except Exception as error:
        show_error(error)


if __name__ == "__main__":
    main()
