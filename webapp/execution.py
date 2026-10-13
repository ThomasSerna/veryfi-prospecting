"""Una investigación local por proceso; los permisos no sobreviven a la ejecución."""

from contextlib import contextmanager
import sqlite3
import threading

from pydantic import ValidationError

from prospecting.pipeline import execute_campaign

_LOCK = threading.RLock()
_active_campaign_id = None
_reports = {}


class ExecutionBusy(ValueError):
    pass


def error_message(error):
    if isinstance(error, ValidationError):
        return "Revisa los campos obligatorios y los límites; los datos no cumplen el contrato."
    if isinstance(error, sqlite3.Error):
        return "No se pudo leer o actualizar la base local. Los datos guardados se conservan."
    if isinstance(error, ValueError):
        return str(error)
    return "No se pudo completar la investigación. Los datos guardados se conservan; revisa y reanuda con una nueva autorización."


def _snapshot(campaign_id):
    return {"campaign_id": str(campaign_id), "is_executing": _active_campaign_id is not None,
            "stop_reason": None, "error_message": None} | _reports.get(campaign_id, {})


def snapshot(campaign_id):
    with _LOCK:
        return _snapshot(campaign_id)


def active_campaign_id():
    with _LOCK:
        return _active_campaign_id


@contextmanager
def idle_action():
    """El registro bloquea acciones incluso antes de que el pipeline tome su guarda."""
    with _LOCK:
        if _active_campaign_id is not None:
            raise ExecutionBusy("Hay una investigación en curso. Espera antes de modificar o exportar resultados.")
        yield


def _work(db_path, campaign_id, access, approvals, exclusions_path):
    global _active_campaign_id
    result = {"stop_reason": None, "error_message": None}
    try:
        report = execute_campaign(db_path, campaign_id, access=access, approvals=approvals,
                                  exclusions_path=exclusions_path)
        result["stop_reason"] = report.stop_reason
    except Exception as error:
        result["error_message"] = error_message(error)
    finally:
        with _LOCK:
            _reports[campaign_id] = result
            _active_campaign_id = None


def start_execution(db_path, campaign_id, *, access, approvals, exclusions_path=None):
    global _active_campaign_id
    with _LOCK:
        if _active_campaign_id is not None:
            if _active_campaign_id != campaign_id:
                raise ExecutionBusy("Otra campaña está investigándose en esta instancia.")
            return _snapshot(campaign_id)
        _active_campaign_id = campaign_id
        _reports.pop(campaign_id, None)
        thread = threading.Thread(target=_work, args=(db_path, campaign_id, access, approvals, exclusions_path), daemon=True,
                                  name="veryfi-investigation")
        try:
            thread.start()
        except Exception:
            _active_campaign_id = None
            raise
        return _snapshot(campaign_id)
