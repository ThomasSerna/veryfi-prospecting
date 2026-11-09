"""Corroboración dirigida del empleo con Tavily (T24); personas, páginas y respuestas exclusivamente sintéticas."""

import csv
from io import StringIO
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from prospecting.contacts import contact_context, employment_status, names_person_at_company
from prospecting.models import Campaign, Evidence, utc_now
from prospecting.pipeline import contacts as stage_module
from prospecting.pipeline.contacts import (
    EMPLOYMENT_EXTRACT_KEY, EMPLOYMENT_EXTRACTED_KEY, EMPLOYMENT_FRAGMENT_KEY, EMPLOYMENT_PENDING_KEY,
    EMPLOYMENT_QUERIES_KEY, EMPLOYMENT_REQUEST_KEY, EMPLOYMENT_SEARCH_KEY, HAIKU_KEY, WEB_QUERIES_KEY,
)
from prospecting.providers import ClaudeClient
from test_contact_pipeline import contact_case, enable_role_taxonomy  # noqa: F401 (fixture)
from test_multi_contact_pipeline import multi
from test_ui import client, text, ui_paths, url  # noqa: F401 (fixtures)

PRODUCT = ("Head of Product", "Product Manager", "Director of Product", "Senior Product Manager")


def scenario(case, role_config, titles, *, priority="medium", directory=True, hits=None, titles_by_name=None,
             rename=None):
    """Personas enriquecidas por Apollo, un directorio vigente que no las nombra y Tavily/Haiku sintéticos."""
    case = multi(case, role_config, titles, priority=priority)
    case.page_by_url, case.hits = {}, hits or {}
    if directory:
        # Antes de T24, este directorio corporativo vigente impedía toda búsqueda pública de la empresa.
        case.db.save_evidence(Evidence(
            company_id=case.company.id, claim="Texto publicado en la página, extraído por Tavily.", kind="observed",
            source_type="primary", provider="tavily", external_reference="extraccion-sintetica#1.1",
            url=f"https://{case.company.domain}/equipo",
            retrieved_at=utc_now(), excerpt=f"Equipo directivo sintético de {case.company.name}."))

    def search(payload):
        query = payload["query"]
        for name, results in case.hits.items():
            if query.startswith(f'"{name}"'):
                return {"results": results, "usage": {"credits": 1}}
        if query.startswith('"Persona Sintética'):
            return {"results": [], "usage": {"credits": 1}}
        return {"results": [{"url": f"https://{case.company.domain}/equipo", "content": "Equipo sintético"}],
                "usage": {"credits": 1}}

    def extract(payload):
        return {"results": [{"url": url, "raw_content": case.page_by_url.get(
            url, f"Equipo directivo sintético de {case.company.name}.")} for url in payload["urls"]], "usage": {"credits": 1}}

    def model_reply(**payload):
        # Cita a cada persona suministrada que una fuente nombra, con su cargo (o el que publique) y la empresa.
        case.model_calls.append(payload)
        user = payload["messages"][0]["content"]
        context = json.loads(user.split("\n")[0])
        supplied = [json.loads(piece) for piece in user.split("<evidencia>\n")[1].split("\n</evidencia>")[0].splitlines()]
        candidates = []
        for person in context["contacts"]:
            source = next((item for item in supplied if person["name"] in item["excerpt"]), None)
            if source is None:
                continue
            name = (rename or {}).get(person["name"], person["name"])
            facts = [("name", name), ("title", (titles_by_name or {}).get(person["name"], person["title"])),
                     ("employment", case.company.name)]
            candidates.append({"contact_id": person["contact_id"], "name": name, "facts": [
                {"field": field, "value": value, "evidence_id": source["evidence_id"], "quote": source["excerpt"]}
                for field, value in facts]})
        return SimpleNamespace(id="mensaje-sintetico", model=payload["model"], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=500, output_tokens=100),
                               content=[SimpleNamespace(type="text", text=json.dumps({"candidates": candidates}))])

    case.replies |= {"search": search, "extract": extract}
    case.model_reply = model_reply
    sdk = SimpleNamespace(with_options=lambda **kwargs: SimpleNamespace(
        messages=SimpleNamespace(create=lambda **payload: case.model_reply(**payload))))
    case.claude = ClaudeClient(case.budget, sdk_client=sdk)
    case.public = case.public | {"claude": case.claude}
    return case


def hit(case, name, text, *, url=None):
    """Resultado de búsqueda cuyo snippet y página extraída publican `text`."""
    url = url or f"https://{case.company.domain}/equipo/{name.split()[-1].lower()}"
    case.page_by_url[url] = text
    return [{"url": url, "content": text}]


def targeted(case):
    return [payload["query"] for operation, payload, _ in case.calls
            if operation == "search" and payload["query"].startswith('"Persona Sintética')]


def person(case, name):
    people, facts = contact_context(case.campaign, case.db.list_contacts(case.company.id),
                                    case.db.list_evidence(case.company.id))
    contact = next(item for item in people if item.name == name)
    return contact, employment_status(contact, case.company, facts, case.campaign.limits, utc_now())


def attempts(case):
    return case.db.get_run_item(case.campaign.id, case.company.id).attempts


def test_current_directory_without_the_person_no_longer_blocks_the_targeted_search(contact_case, role_config):
    case = scenario(contact_case, role_config, ["Head of Product"])
    case.hits = {"Persona Sintética Uno": hit(case, "Persona Sintética Uno",
                                              f"Persona Sintética Uno es Head of Product de {case.company.name}.")}
    report = case.find(**case.public)
    # El correo de Apollo sin fecha de verificación sigue pendiente: corroborar el empleo no confirma el canal.
    assert report.status == "checked" and report.business_status == "needs_channel_confirmation"
    assert targeted(case) == [f'"Persona Sintética Uno" "{case.company.name}" Head of Product']
    # El directorio vigente sigue omitiendo las consultas genéricas; la extracción general ya leyó el directorio.
    assert [operation for operation, _, _ in case.calls][-2:] == ["search", "extract"]
    assert [payload["urls"] for operation, payload, _ in case.calls if operation == "extract"] == [
        [f"https://{case.company.domain}/equipo/uno"]]
    assert len(case.model_calls) == 2
    contact, status = person(case, "Persona Sintética Uno")
    assert (status.state, status.basis, status.reason) == ("corporate_evidence", "source", None)
    saved = attempts(case)
    assert saved[f"{EMPLOYMENT_SEARCH_KEY}{contact.id}"] == 1 and saved[EMPLOYMENT_QUERIES_KEY] == 1
    assert saved[EMPLOYMENT_EXTRACT_KEY] == 1 and saved[f"{EMPLOYMENT_EXTRACTED_KEY}{contact.id}"] == 1
    assert sum(key.startswith(EMPLOYMENT_FRAGMENT_KEY) for key in saved) == 1
    # Búsqueda, Extract y Haiku de la fase quedan marcados para medir su coste.
    assert sum(key.startswith(EMPLOYMENT_REQUEST_KEY) for key in saved) == 3
    assert WEB_QUERIES_KEY not in saved


def test_person_named_by_the_directory_is_not_searched_again(contact_case, role_config):
    case = scenario(contact_case, role_config, ["Head of Product"], directory=False)
    case.page_by_url[f"https://{case.company.domain}/equipo"] = (
        f"Persona Sintética Uno es Head of Product de {case.company.name}.")
    report = case.find(**case.public)
    assert report.status == "checked" and person(case, "Persona Sintética Uno")[1].state == "corporate_evidence"
    assert targeted(case) == [] and len(case.model_calls) == 1
    assert not any(key.startswith("contacts:employment_") for key in attempts(case))


def test_policy_moves_nominal_queries_out_of_the_general_public_search(contact_case, role_config):
    case = scenario(contact_case, role_config, ["Head of Product"], directory=False)
    case.find(**case.public)
    general = [payload["query"] for operation, payload, _ in case.calls if operation == "search"][:2]
    assert len(general) == 2 and not any(query.startswith('"Persona') for query in general)
    assert targeted(case) == [f'"Persona Sintética Uno" "{case.company.name}" Head of Product']


def test_snapshot_without_the_policy_keeps_the_previous_public_search(contact_case, role_config):
    case = scenario(contact_case, role_config.model_copy(update={"employment_corroboration": None}),
                    ["Head of Product"], directory=False)
    case.find(**case.public)
    queries = [payload["query"] for operation, payload, _ in case.calls if operation == "search"]
    assert queries[0] == f'"Persona Sintética Uno" "{case.company.name}" Head of Product' and len(queries) == 2
    assert [operation for operation, _, _ in case.calls].count("extract") == 1 and len(case.model_calls) == 1
    assert not any(key.startswith("contacts:employment_") for key in attempts(case))


def test_each_person_gets_one_search_and_the_company_cap_leaves_the_rest_pending(contact_case, role_config):
    case = scenario(contact_case, role_config, list(PRODUCT), priority="high")
    limits = case.campaign.limits.model_dump(mode="json")
    limits["effort"]["high"]["employment_queries"] = 2
    case.campaign = Campaign.model_validate(case.campaign.model_dump() | {"limits": limits})
    case.db.save_campaign(case.campaign)
    report = case.find(**case.public)
    assert report.status == "checked"
    queries = targeted(case)
    assert len(queries) == 2 == len(set(queries))
    saved = attempts(case)
    assert saved[EMPLOYMENT_QUERIES_KEY] == 2
    searched = {key.split(":")[-1] for key in saved if key.startswith(EMPLOYMENT_SEARCH_KEY)}
    pending = {key.split(":")[-1] for key in saved if key.startswith(f"{EMPLOYMENT_PENDING_KEY}employment_search_limit:")}
    assert len(searched) == 2 and len(pending) == 1 and not searched & pending
    assert all(saved[f"{EMPLOYMENT_SEARCH_KEY}{id}"] == 1 for id in searched)
    [left] = pending
    contact = next(item for item in case.db.list_contacts(case.company.id) if str(item.id) == left)
    assert (person(case, contact.name)[1].state, person(case, contact.name)[1].reason) == ("provider_claim",
                                                                                           "provider_claim_only")


def test_an_obfuscated_surname_is_never_searched(contact_case, role_config):
    # Media: el objetivo de 2 personas pertinentes se cumple y la tercera queda candidata con «S***».
    case = scenario(contact_case, role_config, ["Head of Product", "Product Manager", "Director of Product"])
    case.find(**case.public)
    assert len(targeted(case)) == 2 and not any("***" in query for query in targeted(case))
    obfuscated = [item for item in case.db.list_contacts(case.company.id) if "*" in (item.name or "")]
    assert obfuscated and all(f"{EMPLOYMENT_SEARCH_KEY}{item.id}" not in attempts(case) for item in obfuscated)


def test_resume_does_not_repeat_the_targeted_search_extract_or_haiku(contact_case, role_config, monkeypatch):
    case = scenario(contact_case, role_config, ["Head of Product"])
    case.hits = {"Persona Sintética Uno": hit(case, "Persona Sintética Uno",
                                              f"Persona Sintética Uno es Head of Product de {case.company.name}.")}
    original = stage_module._ContactStage._extract_employment

    def interrupted(self):
        raise RuntimeError("Interrupción sintética después de la búsqueda dirigida.")

    monkeypatch.setattr(stage_module._ContactStage, "_extract_employment", interrupted)
    with pytest.raises(RuntimeError):
        case.find(**case.public)
    assert len(targeted(case)) == 1 and len(case.model_calls) == 1
    monkeypatch.setattr(stage_module._ContactStage, "_extract_employment", original)
    assert case.find(**case.public).status == "checked"
    assert person(case, "Persona Sintética Uno")[1].state == "corporate_evidence"
    assert len(targeted(case)) == 1
    assert [operation for operation, _, _ in case.calls].count("extract") == 1 and len(case.model_calls) == 2
    assert case.find(**case.public).status == "already_checked"
    assert len(targeted(case)) == 1 and len(case.model_calls) == 2


def test_targeted_search_without_results_keeps_the_provider_claim(contact_case, role_config):
    case = scenario(contact_case, role_config, ["Head of Product"])
    assert case.find(**case.public).business_status == "qualified_no_contact"
    assert len(targeted(case)) == 1 and "extract" not in [operation for operation, _, _ in case.calls][-1:]
    contact, status = person(case, "Persona Sintética Uno")
    assert (status.state, status.reason) == ("provider_claim", "provider_claim_only")
    assert attempts(case)[f"{EMPLOYMENT_SEARCH_KEY}{contact.id}"] == 1
    assert f"{EMPLOYMENT_EXTRACTED_KEY}{contact.id}" not in attempts(case) and len(case.model_calls) == 1


def test_homonym_at_another_company_never_reaches_extract_or_haiku(contact_case, role_config):
    case = scenario(contact_case, role_config, ["Head of Product"])
    case.hits = {"Persona Sintética Uno": hit(case, "Persona Sintética Uno",
                                              "Persona Sintética Uno es Head of Product de Otra Compañía Sintética.",
                                              url="https://noticias-sinteticas.example/nota")}
    assert case.find(**case.public).status == "checked"
    assert len(targeted(case)) == 1 and [operation for operation, _, _ in case.calls].count("extract") == 0
    assert len(case.model_calls) == 1
    _, status = person(case, "Persona Sintética Uno")
    assert (status.state, status.reason) == ("provider_claim", "provider_claim_only")


def test_haiku_rejection_stays_pending_with_its_code_and_the_stage_continues(contact_case, role_config, monkeypatch):
    case = scenario(contact_case, role_config, ["Head of Product"],
                    rename={"Persona Sintética Uno": "Persona Sintética Unoa"})
    case.hits = {"Persona Sintética Uno": hit(case, "Persona Sintética Uno",
                                              f"Persona Sintética Uno es Head of Product de {case.company.name}.")}
    original = stage_module._ContactStage.exhausted_reason

    def interrupted(self):
        raise RuntimeError("Interrupción sintética antes de cerrar la etapa.")

    # Se interrumpe tras la fase: el rechazo ya quedó procesado y reanudar no vuelve a llamar a Haiku.
    monkeypatch.setattr(stage_module._ContactStage, "exhausted_reason", interrupted)
    with pytest.raises(RuntimeError):
        case.find(**case.public)
    contact, status = person(case, "Persona Sintética Uno")
    assert attempts(case)[f"{EMPLOYMENT_PENDING_KEY}identity_mismatch:{contact.id}"] == 1
    assert status.state == "provider_claim" and len(case.model_calls) == 2
    monkeypatch.setattr(stage_module._ContactStage, "exhausted_reason", original)
    report = case.find(**case.public)
    assert report.status == "checked" and len(case.model_calls) == 2 and len(targeted(case)) == 1


def test_departure_page_contradicts_the_apollo_claim(contact_case, role_config):
    case = scenario(contact_case, role_config, ["Head of Product"])
    case.hits = {"Persona Sintética Uno": hit(case, "Persona Sintética Uno",
                                              f"Persona Sintética Uno dejó de ser Head of Product de {case.company.name}.")}
    assert case.find(**case.public).business_status == "qualified_no_contact"
    contact, status = person(case, "Persona Sintética Uno")
    assert (status.state, status.reason) == ("contradicted", "employment_ended") and contact.current_employment is False


def test_page_with_another_title_needs_review(contact_case, role_config):
    case = scenario(contact_case, role_config, ["Head of Product"], titles_by_name={"Persona Sintética Uno": "CFO"})
    case.hits = {"Persona Sintética Uno": hit(case, "Persona Sintética Uno",
                                              f"Persona Sintética Uno es CFO de {case.company.name}.")}
    assert case.find(**case.public).business_status == "qualified_no_contact"
    _, status = person(case, "Persona Sintética Uno")
    assert (status.state, status.reason, status.review_required) == ("contradicted", "title_changed", True)


def test_secondary_page_without_date_stays_pending_for_review(contact_case, role_config):
    case = scenario(contact_case, role_config, ["Head of Product"])
    case.hits = {"Persona Sintética Uno": hit(case, "Persona Sintética Uno",
                                              f"Persona Sintética Uno es Head of Product de {case.company.name}.",
                                              url="https://prensa-sintetica.example/nota")}
    assert case.find(**case.public).business_status == "qualified_no_contact"
    _, status = person(case, "Persona Sintética Uno")
    assert (status.state, status.reason, status.review_required) == ("provider_claim", "undated_source", True)


def test_without_tavily_authorization_no_targeted_search_is_sent(contact_case, role_config):
    case = scenario(contact_case, role_config, ["Head of Product"])
    report = case.find(**case.public, authorizations=[item for item in case.grants if item.provider != "tavily"])
    assert report.status == "pending" and targeted(case) == []
    assert not any(operation in ("search", "extract") for operation, _, _ in case.calls)
    assert HAIKU_KEY in attempts(case)


def test_fragment_must_name_the_person_with_the_company_or_come_from_its_domain(contact_case, role_config):
    case = scenario(contact_case, role_config, ["Head of Product"], directory=False)
    case.find()
    contact = next(item for item in case.db.list_contacts(case.company.id) if item.name_complete)

    def fragment(text, url):
        return Evidence(company_id=case.company.id, claim="Texto publicado en la página, extraído por Tavily.",
                        kind="observed", source_type="secondary", provider="tavily", external_reference="extraccion-sintetica#2.1", url=url,
                        retrieved_at=utc_now(), excerpt=text)

    name = contact.name
    assert names_person_at_company(fragment(f"{name} es Head of Product de {case.company.name}.",
                                            "https://prensa-sintetica.example/nota"), contact, case.company)
    assert names_person_at_company(fragment(f"{name}, Head of Product.", f"https://{case.company.domain}/equipo"),
                                   contact, case.company)
    assert not names_person_at_company(fragment(f"{name} es Head of Product de Otra Compañía.",
                                                "https://prensa-sintetica.example/nota"), contact, case.company)
    assert not names_person_at_company(fragment(f"Equipo de {case.company.name}.", f"https://{case.company.domain}/equipo"),
                                       contact, case.company)



def read_view(case, tmp_path):
    from prospecting.pipeline import read_campaign

    return read_campaign(tmp_path / "synthetic.sqlite3", case.campaign.id)


def test_read_and_csv_report_the_targeted_search_result(contact_case, role_config, tmp_path):
    from core.presentation import export_csv

    case = scenario(contact_case, role_config, list(PRODUCT), priority="high")
    case.hits = {"Persona Sintética Uno": hit(case, "Persona Sintética Uno",
                                              f"Persona Sintética Uno es Head of Product de {case.company.name}.")}
    limits = case.campaign.limits.model_dump(mode="json")
    limits["effort"]["high"]["employment_queries"] = 2
    case.campaign = Campaign.model_validate(case.campaign.model_dump() | {"limits": limits})
    case.db.save_campaign(case.campaign)
    case.find(**case.public)
    view = read_view(case, tmp_path)
    [result] = [item for item in view.companies if item.company.id == case.company.id]
    codes = {person.contact.name: person.employment_corroboration for person in result.contacts}
    assert codes["Persona Sintética Uno"] == "corroborated"
    assert sorted(code for name, code in codes.items() if name != "Persona Sintética Uno" and code) == [
        "employment_search_limit", "searched_not_corroborated"]
    rows = list(csv.DictReader(StringIO(export_csv(view, include_all=True).decode("utf-8-sig"))))
    assert {row["contact_name"]: row["employment_corroboration"] for row in rows}["Persona Sintética Uno"] == "corroborated"


def test_company_page_explains_the_targeted_search_result(ui_paths, client, contact_case, role_config):
    # `ui_paths` va primero: retira las claves del entorno antes de que el caso fije las sintéticas.
    case = scenario(contact_case, role_config, ["Head of Product"])
    case.find(**case.public)
    page = text(client.get(url("company", case.campaign.id, case.company.id)))
    assert "Búsqueda dirigida sin corroboración: ninguna fuente vigente nombra a la persona" in page


def test_summary_and_command_measure_conversion_and_cost_without_personal_data(contact_case, role_config, tmp_path):
    from django.core.management import call_command
    from django.test import override_settings
    from prospecting.pipeline import employment_corroboration_summary

    case = scenario(contact_case, role_config, ["Head of Product", "Engineering Manager"])
    case.hits = {"Persona Sintética Uno": hit(case, "Persona Sintética Uno",
                                              f"Persona Sintética Uno es Head of Product de {case.company.name}.")}
    case.find(**case.public)
    summary = employment_corroboration_summary(tmp_path / "synthetic.sqlite3", case.campaign.id)
    assert (summary.policy_version, summary.people_searched, summary.people_corroborated,
            summary.people_pending_limit, summary.people_rejected) == ("employment_corroboration_v1", 2, 1, 0, 0)
    # Dos búsquedas y una extracción de 1 crédito cada una (respuestas sintéticas) y una llamada a Haiku.
    assert (summary.tavily_requests, summary.tavily_credits_observed, summary.tavily_unobserved) == (3, 3, 0)
    assert summary.haiku_requests == 1 and summary.haiku_cost_usd > 0 and summary.haiku_unestimated == 0
    assert summary.credits_per_corroboration == 3 and summary.haiku_usd_per_corroboration == summary.haiku_cost_usd
    out = StringIO()
    with override_settings(PROSPECTING_DB_PATH=tmp_path / "synthetic.sqlite3"):
        call_command("corroboration_report", "--campaign", str(case.campaign.id), stdout=out)
    report = out.getvalue()
    assert "Personas buscadas: 2; corroboradas: 1" in report and "Persona Sintética" not in report


def test_summary_without_corroborations_leaves_the_cost_undefined(contact_case, role_config, tmp_path):
    from prospecting.pipeline import employment_corroboration_summary

    case = scenario(contact_case, role_config, ["Head of Product"])
    case.find(**case.public)
    summary = employment_corroboration_summary(tmp_path / "synthetic.sqlite3", case.campaign.id)
    assert (summary.people_searched, summary.people_corroborated, summary.tavily_requests) == (1, 0, 1)
    assert summary.credits_per_corroboration is None and summary.haiku_usd_per_corroboration is None


def reject_general_extraction(case):
    """La extracción general no cumple el contrato de hechos citados; las siguientes responden normalmente."""
    answer = case.model_reply

    def reply(**payload):
        if case.model_calls:
            return answer(**payload)
        case.model_calls.append(payload)
        text = json.dumps({"candidates": [{"contact_id": str(uuid4()), "name": "Persona Inexistente", "facts": []}]})
        return SimpleNamespace(id="mensaje-sintetico", model=payload["model"], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=500, output_tokens=100),
                               content=[SimpleNamespace(type="text", text=text)])

    case.model_reply = reply


def test_rejected_general_extraction_is_processed_and_the_corroboration_continues(contact_case, role_config):
    case = scenario(contact_case, role_config, ["Head of Product"])
    case.hits = {"Persona Sintética Uno": hit(case, "Persona Sintética Uno",
                                              f"Persona Sintética Uno es Head of Product de {case.company.name}.")}
    reject_general_extraction(case)
    report = case.find(**case.public)
    assert report.status == "checked" and attempts(case)["contacts:haiku_rejected:invalid_output"] == 1
    assert len(targeted(case)) == 1 and len(case.model_calls) == 2
    assert person(case, "Persona Sintética Uno")[1].state == "corporate_evidence"


def test_rejection_saved_before_the_fix_is_recovered_without_repeating_haiku(contact_case, role_config, monkeypatch):
    case = scenario(contact_case, role_config, ["Head of Product"])
    case.hits = {"Persona Sintética Uno": hit(case, "Persona Sintética Uno",
                                              f"Persona Sintética Uno es Head of Product de {case.company.name}.")}
    reject_general_extraction(case)
    run_haiku = stage_module._ContactStage._run_haiku

    def before_fix(self, *args, rejected=None, **kwargs):
        return run_haiku(self, *args, **kwargs)

    # Conducta anterior: el rechazo deja la empresa pendiente y la extracción sin marcar como procesada.
    monkeypatch.setattr(stage_module._ContactStage, "_run_haiku", before_fix)
    report = case.find(**case.public)
    assert (report.status, report.stop_reason) == ("pending", "invalid_output") and targeted(case) == []
    monkeypatch.setattr(stage_module._ContactStage, "_run_haiku", run_haiku)
    report = case.find(**case.public)
    assert report.status == "checked" and attempts(case)["contacts:haiku_rejected:invalid_output"] == 1
    assert len(targeted(case)) == 1 and len(case.model_calls) == 2


def test_a_sent_extraction_without_result_still_blocks_the_stage(contact_case, role_config, monkeypatch):
    case = scenario(contact_case, role_config, ["Head of Product"])
    case.find(**case.public)
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    stage = stage_module._ContactStage.__new__(stage_module._ContactStage)
    stage.campaign, stage.run = case.campaign, run.model_copy(update={"stop_reason": "request_uncertain"})
    [usage] = [row for row in case.db.list_usage(company_id=case.company.id, provider="anthropic")][:1]
    assert not stage.rejected_before_fix(usage)
    stage.run = run.model_copy(update={"stop_reason": "nominal_association"})
    assert stage.rejected_before_fix(usage)
    stage.campaign = case.campaign.model_copy(update={"config_snapshot": role_config.model_copy(
        update={"employment_corroboration": None})})
    assert not stage.rejected_before_fix(usage)
