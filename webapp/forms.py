"""Formularios de ventas; los contratos del pipeline conservan la validación final."""

from decimal import Decimal
import os
from django import forms
from pydantic import ValidationError

from prospecting.models import Campaign, CampaignFilters
from prospecting.pipeline import AuthorizationInput, provider_operations
from webapp.presentation import label


class CampaignForm(forms.Form):
    draft_id = forms.UUIDField(widget=forms.HiddenInput)
    countries = forms.MultipleChoiceField(label="Países", widget=forms.CheckboxSelectMultiple)
    segments = forms.MultipleChoiceField(label="Tipo de empresa", widget=forms.CheckboxSelectMultiple)
    keywords = forms.CharField(label="¿Qué quieres encontrar?", required=False, max_length=1000,
                              help_text="Palabras o frases opcionales, separadas por comas.")
    max_companies = forms.IntegerField(label="Empresas a investigar", min_value=1, max_value=20)

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
            self.campaign = Campaign(
                id=self.campaign_id, countries=cleaned["countries"], segments=cleaned["segments"],
                filters=CampaignFilters(keywords=[word.strip() for word in cleaned["keywords"].split(",") if word.strip()]),
                max_companies=cleaned["max_companies"], config_snapshot=self.config, rubric_version="rubric_v1",
            )
        except ValidationError:
            raise forms.ValidationError("Revisa los criterios y el máximo de empresas permitido.") from None
        return cleaned


class FilterForm(forms.Form):
    q = forms.CharField(label="Buscar empresa", required=False, max_length=200)
    countries = forms.MultipleChoiceField(label="País", required=False, widget=forms.CheckboxSelectMultiple)
    segments = forms.MultipleChoiceField(label="Tipo de empresa", required=False, widget=forms.CheckboxSelectMultiple)
    priorities = forms.MultipleChoiceField(label="Prioridad", required=False, widget=forms.CheckboxSelectMultiple)
    availability = forms.MultipleChoiceField(label="Disponibilidad de contacto", required=False, widget=forms.CheckboxSelectMultiple)

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
    status = forms.ChoiceField(label="Tu decisión", choices=[(value, label(value)) for value in ("pending", "accepted", "rejected")])
    reason = forms.CharField(label="Motivo de tu decisión", max_length=4000, widget=forms.Textarea(attrs={"rows": 3}))


class ConfirmationForm(forms.Form):
    contact_id = forms.UUIDField(widget=forms.HiddenInput)
    channel_type = forms.ChoiceField(choices=[("linkedin", "LinkedIn"), ("other", "Otro canal")], widget=forms.HiddenInput)
    channel_value = forms.CharField(max_length=2048, widget=forms.HiddenInput)
    reason = forms.CharField(label="¿Cómo comprobaste el acceso directo?", max_length=4000, widget=forms.Textarea(attrs={"rows": 3}))
    confirmed = forms.BooleanField(label="He comprobado que puedo contactar directamente a esta persona por este canal, sin enviar mensajes.")


OPERATION_LABELS = {
    ("tavily", "search"): "Buscar empresas y fuentes en la web",
    ("tavily", "extract"): "Leer las páginas encontradas",
    ("anthropic", "messages"): "Analizar evidencia y posibles contactos",
    ("hunter", "domain_search"): "Buscar contactos profesionales por empresa",
    ("hunter", "email_finder"): "Encontrar el correo de una persona",
    ("hunter", "email_verifier"): "Comprobar el estado de un correo",
}


class AuthorizationForm(forms.Form):
    responsible = forms.CharField(label="Responsable del presupuesto", max_length=200)
    reference = forms.CharField(label="Referencia de esta autorización", max_length=1000,
                                help_text="Una referencia local de la aprobación; nunca claves o datos de contactos.")
    confirmed = forms.BooleanField(label="Soy responsable del presupuesto y autorizo únicamente las operaciones y topes seleccionados.")

    def __init__(self, *args, access, view, **kwargs):
        self.operations, self.operation_rows = provider_operations(access), []
        super().__init__(*args, **kwargs)
        for provider, operation, account_ref in self.operations:
            key = f"{provider}_{operation}"
            key_name = {"tavily": "TAVILY_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "hunter": "HUNTER_API_KEY"}[provider]
            key_present = bool(os.environ.get(key_name, "").strip())
            self.fields[f"allow_{key}"] = forms.BooleanField(label=OPERATION_LABELS.get((provider, operation), operation), required=False, disabled=not key_present)
            self.fields[f"cost_{key}"] = forms.DecimalField(label="Tope en USD", min_value=Decimal(0), max_digits=18,
                                                           decimal_places=6, initial=Decimal(0), required=False)
            self.fields[f"credits_{key}"] = forms.DecimalField(label="Tope de créditos", min_value=Decimal(0), max_digits=18,
                                                              decimal_places=6, initial=Decimal(0), required=False)
            account = next(item for item in view.budget.accounts if (item.provider, item.account_ref) == (provider, account_ref))
            self.operation_rows.append({"provider": provider, "operation": operation, "account_ref": account_ref,
                                        "label": OPERATION_LABELS.get((provider, operation), operation),
                                        "key_present": key_present, "key_name": key_name, "account": account,
                                        "allow": self[f"allow_{key}"], "cost": self[f"cost_{key}"], "credits": self[f"credits_{key}"]})

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
