"""Vistas locales: presentan contratos y delegan todas las decisiones al pipeline."""

from functools import wraps
from pathlib import Path
import sqlite3
from urllib.parse import urlencode
from uuid import UUID, uuid4

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from pydantic import ValidationError

from prospecting.models import VeryfiConfig
from prospecting.pipeline import (
    confirm_alternative_channel, finish_campaign, list_saved_campaigns, load_provider_access,
    prepare_campaign, read_campaign, review_company,
)
from core import execution
from core.forms import AuthorizationForm, CampaignForm, ConfirmationForm, FilterForm, ReviewForm
from core.presentation import READY, download_csv, evidence_pill, label

SAVED_MESSAGES = {
    "closed": "Campaña cerrada.",
    "review": "Revisión guardada.",
    "channel": "Canal confirmado.",
}
FILTER_KEYS = ("q", "countries", "segments", "priorities", "availability")
PRIORITY_ORDER = {value: index for index, value in enumerate(("high", "medium", "insufficient_evidence", "low", "excluded"))}


def _paths():
    return (Path(settings.PROSPECTING_DB_PATH), Path(settings.PROSPECTING_ACCESS_PATH),
            Path(settings.PROSPECTING_EXCLUSIONS_PATH))


def _base():
    db_path, access_path, _ = _paths()
    campaigns = list_saved_campaigns(db_path)
    access, access_error = None, None
    if access_path.exists():
        try:
            access = load_provider_access(access_path)
        except ValueError as error:
            access_error = execution.error_message(error)
    active = next((item for item in campaigns if item.status in ("running", "paused_budget")), None)
    return {"campaigns": list(reversed(campaigns)), "active_campaign": active,
            "access": access, "access_error": access_error, "nav_active": "campaigns"}


def _error_response(request, error, status=400):
    return render(request, "pages/error.html", {"message": execution.error_message(error)}, status=status)


def _handled(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except execution.ExecutionBusy as error:
            return _error_response(request, error, 409)
        except (ValueError, OSError, sqlite3.Error, ValidationError) as error:
            return _error_response(request, error, 400 if request.method == "POST" else 503)
        except Http404:
            raise
        except Exception as error:
            return _error_response(request, error, 503)
    return wrapped


def _campaign_view(campaign_id, base):
    db_path, _, exclusions_path = _paths()
    if not any(item.id == campaign_id for item in base["campaigns"]):
        raise Http404("La campaña no existe.")
    return read_campaign(db_path, campaign_id, account_allowances=None if base["access"] is None else base["access"].account_allowances,
                         exclusions_path=exclusions_path, contact_match_path=Path(settings.PROSPECTING_CONTACT_MATCH_PATH))


def _global_busy(base):
    if execution.snapshot(None)["is_executing"]:
        return True
    return bool(base["campaigns"] and _campaign_view(base["campaigns"][0].id, base).is_executing)


def _require_idle(view):
    if view.is_executing:
        raise execution.ExecutionBusy("Hay una investigación en curso. Espera antes de modificar o exportar resultados.")


def _clean_filter_query(filter_form):
    if not filter_form.is_valid():
        return "", 0
    selected = filter_form.cleaned_data
    pairs = []
    active_groups = 0
    for key in FILTER_KEYS:
        val = selected.get(key)
        if not val:
            continue
        active_groups += 1
        if isinstance(val, (list, tuple, set)):
            for item in val:
                pairs.append((key, item))
        else:
            pairs.append((key, val))
    return urlencode(pairs), active_groups


def _company_sort_key(item):
    return (PRIORITY_ORDER.get(None if item.assessment is None else item.assessment.priority, 2),
            -(item.assessment.fit_score or 0) if item.assessment else 0, item.company.name)


def _campaign_insights(view):
    """Resume la campaña leída sin confundir avance, revisión y contacto."""
    total = len(view.companies)
    completed = sum(item.run_item.stage == "completed" for item in view.companies)
    priorities = dict.fromkeys((*PRIORITY_ORDER, "pending"), 0)
    for item in view.companies:
        priority = ("excluded" if item.business_status == "excluded" else
                    item.assessment.priority if item.assessment is not None else "pending")
        priorities[priority] += 1
    distribution = [{"value": value, "label": "Sin calificar" if value == "pending" else label(value), "count": count,
                     "percent": round(count * 100 / total) if total else 0, "tone": value,
                     "query": ("availability=excluded" if value == "excluded" else
                               "" if value == "pending" else urlencode({"priorities": value}))}
                    for value, count in priorities.items()]
    return {"total": total, "completed": completed,
            "review_pending": sum(item.run_item.review_status == "pending" for item in view.companies),
            "ready": sum(item.business_status in READY for item in view.companies),
            "needs_confirmation": sum(item.business_status == "needs_channel_confirmation" for item in view.companies),
            "progress": round(completed * 100 / total) if total else None,
            "next_review": next((item for item in view.companies if item.run_item.review_status == "pending"), None),
            "priority_distribution": distribution}


def _campaign_context(request, campaign_id):
    context = _base()
    view = _campaign_view(campaign_id, context)
    state = execution.snapshot(campaign_id)
    state["is_executing"] = state["is_executing"] or view.is_executing
    filter_form = FilterForm(request.GET, view=view)
    results = list(view.companies)
    if filter_form.is_valid():
        selected = filter_form.cleaned_data
        results = [item for item in results if
                   (not selected["q"] or selected["q"].casefold() in item.company.name.casefold())
                   and (not selected["countries"] or set(selected["countries"]).intersection(item.company.operating_countries or []))
                   and (not selected["segments"] or set(selected["segments"]).intersection(item.company.segments or []))
                   and (not selected["priorities"] or item.assessment is not None and item.assessment.priority in selected["priorities"])
                   and (not selected["availability"] or item.business_status in selected["availability"])]
    else:
        results = []
    if view.campaign.rubric_version != "rubric_v2":
        results.sort(key=_company_sort_key)
    filter_query, active_filter_count = _clean_filter_query(filter_form)
    legacy_readonly = view.campaign.config_snapshot.people_provider != "apollo"
    apollo = None if context["access"] is None else context["access"].apollo_access
    apollo_blocked = apollo is None or not apollo.access_verified or not apollo.work_email_verified
    form = None if legacy_readonly or apollo_blocked else AuthorizationForm(access=context["access"], view=view)
    counts = {"total": len(view.companies), "completed": sum(item.run_item.stage == "completed" for item in view.companies),
              "ready": sum(item.business_status in READY for item in view.companies),
              "pending": sum(item.business_status not in READY for item in view.companies),
              "accepted": sum(item.run_item.review_status == "accepted" for item in view.companies)}
    saved_key = request.GET.get("saved", "")
    context.update(view=view, campaign=view.campaign, results=results, filter_form=filter_form,
                   filter_query=filter_query, has_active_filters=active_filter_count > 0,
                   active_filter_count=active_filter_count,
                   legacy_readonly=legacy_readonly, apollo_blocked=apollo_blocked,
                   authorization_form=form, operation_rows=[] if form is None else form.operation_rows,
                   counts=counts, execution=state, is_executing=state["is_executing"],
                   campaign_insights=_campaign_insights(view), budget_view=view.budget, budget_campaign=view.campaign,
                   stop_reason=state["stop_reason"], error_message=state["error_message"],
                   saved_notice=SAVED_MESSAGES.get(saved_key))
    return context


def _company_context(request, campaign_id, company_id, *, review_form=None, confirmation_form=None):
    context = _campaign_context(request, campaign_id)
    result = next((item for item in context["view"].companies if item.company.id == company_id), None)
    if result is None:
        raise Http404("La empresa no pertenece a esta campaña.")
    sequence = context["results"]
    if not any(item.company.id == company_id for item in sequence):
        sequence = (context["view"].companies if context["view"].campaign.rubric_version == "rubric_v2"
                    else sorted(context["view"].companies, key=_company_sort_key))
    idx = next((i for i, item in enumerate(sequence) if item.company.id == company_id), 0)
    prev_company = sequence[idx - 1].company if idx > 0 else None
    next_company = sequence[idx + 1].company if idx + 1 < len(sequence) else None
    forms = []
    for person in ([] if context["legacy_readonly"] else result.contacts):
        for channel_index, channel in enumerate(person.contact.channels):
            if channel.type not in ("linkedin", "other") or channel.normalized_status == "invalid":
                continue
            form = ConfirmationForm(initial={"contact_id": person.contact.id, "channel_type": channel.type, "channel_value": channel.value})
            if (confirmation_form is not None and str(person.contact.id) == request.POST.get("contact_id")
                    and channel.type == request.POST.get("channel_type") and channel.value == request.POST.get("channel_value")):
                form = confirmation_form
            form.auto_id = f"confirm_{person.contact.id}_{channel_index}_%s"
            forms.append({"person": person, "channel": channel, "form": form})
    evidence_items = {fact.id: evidence_pill(fact, index) for index, fact in enumerate(result.evidence, start=1)}
    context.update(result=result, review_form=review_form or ReviewForm(initial={"status": result.run_item.review_status,
                                                                              "reason": result.run_item.review_reason or ""}),
                   confirmation_forms=forms, nav_active="campaigns",
                   prev_company=prev_company, next_company=next_company,
                   sequence_position=idx + 1, sequence_total=len(sequence),
                   evidence_items=evidence_items)
    return context


@require_GET
@_handled
def campaigns(request):
    context = _base()
    highlighted = context["active_campaign"] or next(iter(context["campaigns"]), None)
    view = _campaign_view(highlighted.id, context) if highlighted else None
    state = execution.snapshot(highlighted.id if highlighted else None)
    state["is_executing"] = state["is_executing"] or bool(view and view.is_executing)
    context.update(highlighted_campaign=highlighted, highlighted_view=view,
                   highlighted_is_active=context["active_campaign"] is not None,
                   campaign_insights=_campaign_insights(view) if view else None,
                   budget_view=view.budget if view else None, budget_campaign=highlighted,
                   execution=state, is_executing=state["is_executing"])
    return render(request, "pages/campaigns.html", context)


@require_http_methods(["GET", "POST"])
@_handled
def new_campaign(request):
    context = _base()
    try:
        config = VeryfiConfig.model_validate_json(Path(settings.PROSPECTING_CONFIG_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError):
        return _error_response(request, ValueError("No se pudo validar la configuración de búsqueda. Revisa el archivo local antes de continuar."), 503)
    if request.method == "GET" or not request.session.get("draft_id"):
        request.session["draft_id"] = str(uuid4())
    draft_id = UUID(request.session["draft_id"])
    form = CampaignForm(request.POST if request.method == "POST" else None, config=config, campaign_id=draft_id)
    # Solo hay una campaña activa por base (§13.3): otra sin terminar se anuncia en lugar de abrirse sin aviso.
    active = context["active_campaign"]
    blocking = active if active is not None and active.id != draft_id else None
    budget_campaign = active or next(iter(context["campaigns"]), None)
    view = _campaign_view(budget_campaign.id, context) if budget_campaign else None
    busy = execution.snapshot(None)["is_executing"] or bool(view and view.is_executing)
    context.update(form=form, config=config, nav_active="new_campaign", is_executing=busy,
                   blocking_campaign=blocking, budget_view=view.budget if view else None,
                   budget_campaign=budget_campaign)
    if request.method == "POST" and form.is_valid():
        with execution.idle_action():
            if _global_busy(context):
                raise execution.ExecutionBusy("Hay una investigación en curso. Espera antes de preparar otra campaña.")
            if blocking is not None:
                raise execution.ExecutionBusy("Hay una campaña sin terminar. Retómala o ciérrala conservando sus "
                                              "resultados antes de preparar otra.")
            saved = prepare_campaign(_paths()[0], form.campaign)
        return redirect("webapp:campaign", campaign_id=saved.id)
    return render(request, "pages/new_campaign.html", context, status=400 if request.method == "POST" else 200)


@require_GET
@_handled
def campaign(request, campaign_id):
    return render(request, "pages/campaign.html", _campaign_context(request, campaign_id))


@require_GET
@_handled
def company(request, campaign_id, company_id):
    return render(request, "pages/company.html", _company_context(request, campaign_id, company_id))


@require_GET
def status(request, campaign_id):
    try:
        context = _campaign_context(request, campaign_id)
        payload = context["execution"] | {"status": context["campaign"].status, "html": ""}
        if request.GET.get("compact") != "1":
            payload["html"] = render_to_string("components/_campaign_results.html", context, request=request)
        return JsonResponse(payload)
    except (ValueError, OSError, sqlite3.Error, ValidationError) as error:
        return JsonResponse({"error_message": execution.error_message(error), "is_executing": execution.snapshot(campaign_id)["is_executing"]}, status=503)
    except Http404:
        raise
    except Exception as error:
        return JsonResponse({"error_message": execution.error_message(error), "is_executing": execution.snapshot(campaign_id)["is_executing"]}, status=503)


@require_POST
def execute(request, campaign_id):
    try:
        base = _base()
        view = _campaign_view(campaign_id, base)
        current = execution.snapshot(campaign_id)
        if current["is_executing"]:
            if execution.active_campaign_id() == campaign_id:
                return JsonResponse(current, status=202)
            raise execution.ExecutionBusy("Otra campaña está investigándose en esta instancia.")
        if view.is_executing:
            raise execution.ExecutionBusy("Hay una investigación en curso en esta instancia.")
        if view.campaign.config_snapshot.people_provider != "apollo":
            raise ValueError("La campaña histórica solo permite consulta y exportación.")
        if base["access"] is None or base["access"].apollo_access is None:
            raise ValueError("Configura el acceso y los cupos comprobados antes de autorizar una investigación.")
        apollo = base["access"].apollo_access
        if not apollo.access_verified or not apollo.work_email_verified:
            raise ValueError("Apollo bloqueado: falta comprobar acceso, correo laboral y cuota.")
        form = AuthorizationForm(request.POST, access=base["access"], view=view)
        if not form.is_valid():
            return JsonResponse(current | {"error_message": "Revisa la autorización, los campos obligatorios y los topes seleccionados.",
                                "errors": {name: list(messages) for name, messages in form.errors.items()}}, status=400)
        state = execution.start_execution(_paths()[0], campaign_id, access=base["access"], approvals=form.approvals,
                                          exclusions_path=_paths()[2])
        return JsonResponse(state, status=202)
    except execution.ExecutionBusy as error:
        return JsonResponse({"is_executing": True, "stop_reason": None, "error_message": execution.error_message(error)}, status=409)
    except (ValueError, OSError, sqlite3.Error, ValidationError) as error:
        return JsonResponse({"is_executing": False, "stop_reason": None, "error_message": execution.error_message(error)}, status=400)
    except Http404:
        raise
    except Exception as error:
        return JsonResponse({"is_executing": False, "stop_reason": None, "error_message": execution.error_message(error)}, status=503)


@require_POST
@_handled
def close(request, campaign_id):
    with execution.idle_action():
        base = _base()
        _require_idle(_campaign_view(campaign_id, base))
        finish_campaign(_paths()[0], campaign_id)
    return redirect(f"{reverse('webapp:campaign', kwargs={'campaign_id': campaign_id})}?saved=closed")


@require_POST
@_handled
def review(request, campaign_id, company_id):
    form = ReviewForm(request.POST)
    if not form.is_valid():
        return render(request, "pages/company.html", _company_context(request, campaign_id, company_id, review_form=form), status=400)
    target_id = company_id
    with execution.idle_action():
        context = _company_context(request, campaign_id, company_id)
        _require_idle(context["view"])
        review_company(_paths()[0], campaign_id, company_id, status=form.cleaned_data["status"], reason=form.cleaned_data["reason"])
        next_raw = request.POST.get("next_company_id", "").strip()
        if next_raw:
            try:
                candidate = UUID(next_raw)
                if any(item.company.id == candidate for item in context["view"].companies):
                    target_id = candidate
            except ValueError:
                pass
    query = context["filter_query"]
    suffix = f"?{query}&saved=review" if query else "?saved=review"
    return redirect(f"{reverse('webapp:company', kwargs={'campaign_id': campaign_id, 'company_id': target_id})}{suffix}")


@require_POST
@_handled
def confirm_channel(request, campaign_id, company_id):
    form = ConfirmationForm(request.POST)
    if not form.is_valid():
        return render(request, "pages/company.html", _company_context(request, campaign_id, company_id, confirmation_form=form), status=400)
    with execution.idle_action():
        context = _company_context(request, campaign_id, company_id)
        _require_idle(context["view"])
        contact_id = form.cleaned_data["contact_id"]
        person = next((person for person in context["result"].contacts if person.contact.id == contact_id), None)
        if person is None:
            raise Http404("La persona no pertenece a esta empresa.")
        if not person.eligible:
            raise ValueError("La persona no es elegible según la evidencia y las exclusiones actuales.")
        confirm_alternative_channel(_paths()[0], campaign_id, contact_id, form.cleaned_data["channel_type"],
                                    form.cleaned_data["channel_value"], reason=form.cleaned_data["reason"], confirmed=form.cleaned_data["confirmed"])
    query = context["filter_query"]
    suffix = f"?{query}&saved=channel" if query else "?saved=channel"
    return redirect(f"{reverse('webapp:company', kwargs={'campaign_id': campaign_id, 'company_id': company_id})}{suffix}#contacts")


@require_GET
@_handled
def export(request, campaign_id):
    mode = request.GET.get("mode", "ready")
    if mode not in ("ready", "all"):
        return _error_response(request, ValueError("Selecciona prospectos listos o todos los resultados."), 400)
    with execution.idle_action():
        base = _base()
        view = _campaign_view(campaign_id, base)
        _require_idle(view)
        content = download_csv(_paths()[0], campaign_id, include_all=mode == "all",
                               account_allowances=None if base["access"] is None else base["access"].account_allowances,
                               exclusions_path=_paths()[2],
                               contact_match_path=Path(settings.PROSPECTING_CONTACT_MATCH_PATH))
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    prefix = "demo-sintetica-" if settings.PROSPECTING_DEMO else ""
    name = "resultados" if mode == "all" else "prospectos-listos"
    response["Content-Disposition"] = f'attachment; filename="{prefix}{name}-{campaign_id}.csv"'
    response["Cache-Control"] = "no-store"
    return response
