"""Etiquetas, cifras y enlaces públicos, sin interpretar reglas comerciales."""

from django import template

from prospecting.sources import validate_public_url
from core.presentation import (
    campaign_short_title, campaign_title, criterion_label, criterion_tone, employment_label, employment_reason,
    ineligible_reason, label as present_label,
    match_label, money as present_money, money_summary as present_money_summary,
    stop_message, stop_tone,
)

register = template.Library()
register.filter("stop_message", stop_message)
register.filter("stop_tone", stop_tone)
register.filter("match_label", match_label)
register.filter("campaign_title", campaign_title)
register.filter("campaign_short_title", campaign_short_title)
register.filter("ineligible_reason", ineligible_reason)
register.filter("criterion_label", criterion_label)
register.filter("criterion_tone", criterion_tone)
register.filter("employment_label", employment_label)
register.filter("employment_reason", employment_reason)


@register.filter
def label(value):
    return present_label(None if value == "" else value)


@register.filter
def money(value):
    return present_money(None if value == "" else value)


@register.filter
def money_summary(value):
    return present_money_summary(None if value == "" else value)


@register.filter
def render_field(field):
    if not hasattr(field, "as_widget"):
        return field
    attrs = {}
    described = []
    if getattr(field, "help_text", None) and getattr(field, "auto_id", None):
        described.append(f"{field.auto_id}_helptext")
    if getattr(field, "errors", None) and getattr(field, "auto_id", None):
        attrs["aria-invalid"] = "true"
        described.append(f"{field.auto_id}_errors")
    if described:
        attrs["aria-describedby"] = " ".join(described)
    return field.as_widget(attrs=attrs) if attrs else field


@register.filter
def public_url(value):
    try:
        return (validate_public_url(str(value)) or "") if value else ""
    except ValueError:
        return ""


@register.filter
def percentage(value):
    return "Desconocido" if value is None or value == "" else f"{value * 100:.0f}%"


@register.filter
def score(value):
    return "Desconocido" if value is None or value == "" else f"{value:.1f}"


@register.filter
def evidence_item(mapping, evidence_id):
    return mapping.get(evidence_id) if isinstance(mapping, dict) else None
