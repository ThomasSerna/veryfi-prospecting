"""Formularios de ventas; los contratos del pipeline conservan la validación final."""

from decimal import Decimal, ROUND_DOWN
import os
import re
from django import forms
from django.core.validators import URLValidator
from pydantic import ValidationError

from prospecting.models import Campaign, CampaignFilters, TargetAccount
from prospecting.pipeline import AuthorizationInput, provider_operations
from core.presentation import label

FUNDING_LABELS = {
    "free_credit": "Crédito gratuito",
    "prepaid": "Prepago en USD",
    "paid_credit": "Créditos de pago",
}


def parse_target_accounts(text: str) -> list[TargetAccount]:
    """Una cuenta por línea: `dominio, nombre, país`; acepta una URL pegada y conserva solo su host."""
    accounts = []
    for number, line in enumerate(text.splitlines(), start=1):
        parts = [part.strip() for part in line.split(",")]
        if not any(parts):
            continue
        host = re.sub(r"^[a-z]+://", "", parts[0], flags=re.I).split("/")[0].split("?")[0]
        try:
            accounts.append(TargetAccount(domain=host, name=(parts[1] if len(parts) > 1 else "") or None,
                                          countries=[part.upper() for part in parts[2:] if part]))
        except ValidationError:
            raise ValueError(f"Cuenta objetivo inválida en la línea {number}: usa dominio, nombre y país (CO o MX).") from None
    return accounts


class CampaignForm(forms.Form):
    draft_id = forms.UUIDField(widget=forms.HiddenInput)
    countries = forms.MultipleChoiceField(label="Países", widget=forms.CheckboxSelectMultiple)
    segments = forms.MultipleChoiceField(label="Segmentos", widget=forms.CheckboxSelectMultiple)
    keywords = forms.CharField(label="Palabras clave (opcional)", required=False, max_length=1000,
                              help_text="Separadas por comas.")
    max_companies = forms.IntegerField(label="Máximo de empresas", min_value=1, max_value=20)
    target_accounts = forms.CharField(
        label="Cuentas objetivo (opcional)", required=False, max_length=4000,
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": "empresa.com, Nombre de la empresa, MX"}),
        help_text="Una por línea: dominio, nombre y país (CO o MX); el nombre y el país son opcionales. "
                  "Con cuentas objetivo se investigan exactamente esas empresas, sin buscar otras en la web.")

    def __init__(self, *args, config, campaign_id, **kwargs):
        self.config, self.campaign_id = config, campaign_id
        super().__init__(*args, **kwargs)
        self.fields["countries"].choices = [(value, label(value)) for value in config.defaults.countries]
        self.fields["segments"].choices = [(value, label(value)) for value in config.defaults.segments]
        self.fields["countries"].initial = config.defaults.countries
        self.fields["segments"].initial = config.defaults.segments
        self.fields["max_companies"].initial = config.defaults.max_companies
        self.fields["max_companies"].max_value = config.defaults.max_companies
        self.fields["draft_id"].initial = campaign_id

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        if cleaned["draft_id"] != self.campaign_id:
            raise forms.ValidationError("Este borrador cambió. Abre una nueva búsqueda y vuelve a preparar sus criterios.")
        try:
            accounts = parse_target_accounts(cleaned["target_accounts"])
        except ValueError as error:
            raise forms.ValidationError(str(error)) from None
        try:
            self.campaign = Campaign(
                id=self.campaign_id, countries=cleaned["countries"], segments=cleaned["segments"],
                filters=CampaignFilters(keywords=[word.strip() for word in cleaned["keywords"].split(",") if word.strip()],
                                        target_accounts=accounts),
                # Con cuentas objetivo se investigan exactamente esas: el máximo es su número.
                max_companies=len(accounts) or cleaned["max_companies"], config_snapshot=self.config,
                rubric_version="rubric_v2",
            )
        except ValidationError:
            raise forms.ValidationError("Revisa los criterios, las cuentas objetivo (sin dominios repetidos y con "
                                        "países de la campaña) y el máximo de empresas permitido.") from None
        return cleaned


class FilterForm(forms.Form):
    q = forms.CharField(label="Buscar empresa", required=False, max_length=200,
                        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Buscar empresa", "autocomplete": "off"}))
    countries = forms.MultipleChoiceField(label="País", required=False, widget=forms.CheckboxSelectMultiple)
    segments = forms.MultipleChoiceField(label="Tipo de empresa", required=False, widget=forms.CheckboxSelectMultiple)
    priorities = forms.MultipleChoiceField(label="Prioridad", required=False, widget=forms.CheckboxSelectMultiple)
    availability = forms.MultipleChoiceField(label="Disponibilidad", required=False, widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, view, **kwargs):
        super().__init__(*args, **kwargs)
        values = {
            "countries": view.campaign.countries, "segments": view.campaign.segments,
            "priorities": ["high", "medium", "low", "insufficient_evidence", "excluded"],
            "availability": sorted({result.business_status for result in view.companies if result.business_status}),
        }
        for name, choices in values.items():
            self.fields[name].choices = [(value, label(value)) for value in choices]


class ReviewForm(forms.Form):
    status = forms.ChoiceField(label="Decisión", widget=forms.RadioSelect,
                               choices=[(value, label(value)) for value in ("pending", "accepted", "rejected")])
    reason = forms.CharField(label="Notas", max_length=4000, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        # Las etiquetas acompañan a la leyenda «Decisión», que no lleva dos puntos.
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)


class ConfirmationForm(forms.Form):
    contact_id = forms.UUIDField(widget=forms.HiddenInput)
    channel = forms.ChoiceField(label="Canal")
    reason = forms.CharField(label="Notas de comprobación", max_length=4000, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, channels=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["channel"].choices = [(f"{item.type}:{item.value}", f"{label(item.type)}: {item.value}")
                                          for item in channels if item.normalized_status != "invalid"]

    def clean(self):
        cleaned = super().clean()
        if "channel" in cleaned:
            cleaned["channel_type"], _, cleaned["channel_value"] = cleaned["channel"].partition(":")
        return cleaned


class EmploymentConfirmationForm(forms.Form):
    """Confirmación manual del empleo (T23): el cargo sale de los ya citados; Python valida la persona."""

    contact_id = forms.UUIDField(widget=forms.HiddenInput)
    title = forms.CharField(label="Cargo vigente", max_length=500, widget=forms.HiddenInput)
    source_url = forms.URLField(label="Fuente consultada (URL)", max_length=2048, assume_scheme="https",
                                validators=[URLValidator(schemes=["http", "https"])])
    reason = forms.CharField(label="Motivo de la confirmación", max_length=4000, widget=forms.Textarea(attrs={"rows": 2}))
    confirmed = forms.BooleanField(
        label="Comprobé el empleo vigente en esa fuente sin enviar mensajes, llamar ni enviar invitaciones")

    def __init__(self, *args, titles=(), **kwargs):
        super().__init__(*args, **kwargs)
        if len(titles) > 1:
            # Con un cambio de cargo, ventas elige cuál de los cargos ya citados es el vigente.
            self.fields["title"].widget = forms.RadioSelect(choices=[(value, value) for value in titles])


OPERATION_LABELS = {
    ("tavily", "search"): "Buscar empresas y fuentes en la web",
    ("tavily", "extract"): "Leer las páginas encontradas",
    ("anthropic", "messages"): "Analizar evidencia y posibles contactos",
    ("apollo", "people_search"): "Buscar personas por empresa en Apollo",
    ("apollo", "people_enrichment"): "Resolver identidad y correo profesional en Apollo",
}


class AuthorizationForm(forms.Form):
    responsible = forms.CharField(label="Responsable", max_length=200)
    reference = forms.CharField(label="Referencia", max_length=1000)
    confirmed = forms.BooleanField(label="Autorizo las operaciones y topes seleccionados.")

    def __init__(self, *args, access, view, **kwargs):
        self.operations, self.operation_rows = provider_operations(access), []
        super().__init__(*args, **kwargs)
        campaign_avail = view.budget.campaign.available
        for provider, operation, account_ref in self.operations:
            key = f"{provider}_{operation}"
            key_name = {"tavily": "TAVILY_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "apollo": "APOLLO_API_KEY"}[provider]
            key_present = bool(os.environ.get(key_name, "").strip())
            self.fields[f"allow_{key}"] = forms.BooleanField(label=OPERATION_LABELS.get((provider, operation), operation), required=False, disabled=not key_present)
            self.fields[f"cost_{key}"] = forms.DecimalField(label="Tope en USD", min_value=Decimal(0), max_digits=18,
                                                           decimal_places=6, initial=Decimal(0), required=False)
            self.fields[f"credits_{key}"] = forms.DecimalField(label="Tope de créditos", min_value=Decimal(0), max_digits=18,
                                                              decimal_places=6, initial=Decimal(0), required=False)
            account = next(item for item in view.budget.accounts if (item.provider, item.account_ref) == (provider, account_ref))
            avail_cost = account.cost.available
            avail_credits = account.credits.available
            if account.funding_source == "free_credit":
                suggested_cost = "0"
            else:
                candidates = [val for val in (avail_cost, campaign_avail) if val is not None]
                best_cost = min(candidates) if candidates else Decimal(0)
                suggested_cost = str(best_cost.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)) if best_cost > 0 else "0"
            suggested_credits = str(min(avail_credits, Decimal(10))) if avail_credits is not None and avail_credits > 0 else "0"
            self.operation_rows.append({
                "provider": provider, "operation": operation, "account_ref": account_ref,
                "label": OPERATION_LABELS.get((provider, operation), operation),
                "funding_label": FUNDING_LABELS.get(account.funding_source, account.funding_source),
                "suggested_cost": suggested_cost, "suggested_credits": suggested_credits,
                "key_present": key_present, "key_name": key_name, "account": account,
                "allow": self[f"allow_{key}"], "cost": self[f"cost_{key}"], "credits": self[f"credits_{key}"],
            })

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        self.approvals = []
        for provider, operation, account_ref in self.operations:
            key = f"{provider}_{operation}"
            if cleaned[f"allow_{key}"]:
                cost, credits = cleaned[f"cost_{key}"], cleaned[f"credits_{key}"]
                if cost is None or credits is None:
                    raise forms.ValidationError("Indica ambos topes de cada operación autorizada, aunque sean cero.")
                self.approvals.append(AuthorizationInput(
                    provider=provider, operation=operation, account_ref=account_ref,
                    max_cost_usd=cost, max_credits=credits,
                    responsible=cleaned["responsible"], source_reference=cleaned["reference"],
                ))
        if not self.approvals:
            raise forms.ValidationError("Selecciona al menos una operación con clave local configurada.")
        return cleaned
