"""Modelo único y forma común de las solicitudes estructuradas a Haiku (§12.1).

Cada prompt vive junto a su validador; aquí solo se fijan el modelo, la estimación de
caracteres por token y la forma de la solicitud. Sin escalado a un modelo más caro.
"""

import json


MODEL_ID = "claude-haiku-5-5"
# Caracteres de texto (sistema, mensaje y esquema) por token de entrada facturado. Medido el
# 2026-10-14 en 15 solicitudes reales de calificación, reconstruidas por su huella: entre 2,11 y 2,26,
# incluido el prompt que inyecta la salida estructurada. Con 3, las solicitudes superaban el límite.
CHARS_PER_TOKEN = 2


def prompt_json(value) -> str:
    """JSON determinista con `<` escapado: ningún texto externo puede cerrar el bloque de evidencia."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c")


def structured_request(system: str, user: str, schema: dict, max_tokens: int) -> dict:
    """Una respuesta JSON con esquema, sin razonamiento extendido y con esfuerzo bajo."""
    return {
        "model": MODEL_ID,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "thinking": {"type": "disabled"},
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": schema}},
    }
