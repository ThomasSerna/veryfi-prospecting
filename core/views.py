"""Vistas locales: presentan contratos y delegan todas las decisiones al pipeline."""

from functools import wraps
from pathlib import Path
import sqlite3
from uuid import UUID, uuid4

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from pydantic import ValidationError

from prospecting.models import VeryfiConfig
from prospecting.pipeline import (
    confirm_alternative_channel, finish_campaign, list_saved_campaigns, load_provider_access,
    prepare_campaign, read_campaign, review_company,
)
from core import execution
from core.forms import AuthorizationForm, CampaignForm, ConfirmationForm, FilterForm, ReviewForm
from core.presentation import READY, download_csv


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
                         exclusions_path=exclusions_path)


def _global_busy(base):
    if execution.snapshot(None)["is_executing"]:
        return True
    return bool(base["campaigns"] and _campaign_view(base["campaigns"][0].id, base).is_executing)


def _require_idle(view):
    if view.is_executing:
        raise execution.ExecutionBusy("Hay una investigación en curso. Espera antes de modificar o exportar resultados.")


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
    order = {value: index for index, value in enumerate(("high", "medium", "insufficient_evidence", "low", "excluded"))}
    results.sort(key=lambda item: (order.get(None if item.assessment is None else item.assessment.priority, 2),
                                   -(item.assessment.fit_score or 0) if item.assessment else 0, item.company.name))
    form = None if context["access"] is None else AuthorizationForm(access=context["access"], view=view)
    counts = {"total": len(view.companies), "completed": sum(item.run_item.stage == "completed" for item in view.companies),
              "ready": sum(item.business_status in READY for item in view.companies),
              "pending": sum(item.business_status not in READY for item in view.companies),
              "accepted": sum(item.run_item.review_status == "accepted" for item in view.companies)}
    context.update(view=view, campaign=view.campaign, results=results, filter_form=filter_form,
                   authorization_form=form, operation_rows=[] if form is None else form.operation_rows,
                   counts=counts, execution=state, is_executing=state["is_executing"],
                   stop_reason=state["stop_reason"], error_message=state["error_message"])
    return context


def _company_context(request, campaign_id, company_id, *, review_form=None, confirmation_form=None):
    context = _campaign_context(request, campaign_id)
    result = next((item for item in context["view"].companies if item.company.id == company_id), None)
    if result is None:
        raise Http404("La empresa no pertenece a esta campaña.")
    forms = []
    for person in result.contacts:
        for channel_index, channel in enumerate(person.contact.channels):
            if channel.type not in ("linkedin", "other") or channel.normalized_status == "invalid":
                continue
            form = ConfirmationForm(initial={"contact_id": person.contact.id, "channel_type": channel.type, "channel_value": channel.value})
            if (confirmation_form is not None and str(person.contact.id) == request.POST.get("contact_id")
                    and channel.type == request.POST.get("channel_type") and channel.value == request.POST.get("channel_value")):
                form = confirmation_form
            form.auto_id = f"confirm_{person.contact.id}_{channel_index}_%s"
            forms.append({"person": person, "channel": channel, "form": form})
    context.update(result=result, review_form=review_form or ReviewForm(initial={"status": result.run_item.review_status,
                                                                              "reason": result.run_item.review_reason or ""}),
                   confirmation_forms=forms, nav_active="campaigns")
    return context


@require_GET
@_handled
def campaigns(request):
    context = _base()
    context["execution"] = execution.snapshot(context["active_campaign"].id if context["active_campaign"] else None)
    context["execution"]["is_executing"] = _global_busy(context)
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
    context.update(form=form, config=config, nav_active="new_campaign", is_executing=_global_busy(context))
    if request.method == "POST" and form.is_valid():
        with execution.idle_action():
            if _global_busy(context):
                raise execution.ExecutionBusy("Hay una investigación en curso. Espera antes de preparar otra campaña.")
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
        return JsonResponse(context["execution"] | {"status": context["campaign"].status,
                            "html": render_to_string("components/_campaign_results.html", context, request=request)})
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
        if base["access"] is None:
            raise ValueError("Configura el acceso y los cupos comprobados antes de autorizar una investigación.")
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
    return redirect("webapp:campaign", campaign_id=campaign_id)


@require_POST
@_handled
def review(request, campaign_id, company_id):
    form = ReviewForm(request.POST)
    if not form.is_valid():
        return render(request, "pages/company.html", _company_context(request, campaign_id, company_id, review_form=form), status=400)
    with execution.idle_action():
        context = _company_context(request, campaign_id, company_id)
        _require_idle(context["view"])
        review_company(_paths()[0], campaign_id, company_id, status=form.cleaned_data["status"], reason=form.cleaned_data["reason"])
    return redirect("webapp:company", campaign_id=campaign_id, company_id=company_id)


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
    return redirect("webapp:company", campaign_id=campaign_id, company_id=company_id)


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
                               exclusions_path=_paths()[2])
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    prefix = "demo-sintetica-" if settings.PROSPECTING_DEMO else ""
    name = "resultados" if mode == "all" else "prospectos-listos"
    response["Content-Disposition"] = f'attachment; filename="{prefix}{name}-{campaign_id}.csv"'
    response["Cache-Control"] = "no-store"
    return response
