"""Etiquetas, cifras y enlaces públicos, sin interpretar reglas comerciales."""

from django import template

from prospecting.sources import validate_public_url
from core.presentation import label as present_label, money as present_money, stop_message

register = template.Library()
register.filter("stop_message", stop_message)


@register.filter
def label(value):
    return present_label(None if value == "" else value)


@register.filter
def money(value):
    return present_money(None if value == "" else value)


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
