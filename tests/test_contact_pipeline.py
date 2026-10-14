"""Etapa de contactos con proveedores y personas exclusivamente sintéticos, sin red."""

from datetime import timedelta
from decimal import Decimal
import json
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from prospecting.budget import AccountAllowance, Budget, CreditValuation, SpendingAuthorization
from prospecting.models import BusinessStatus, Channel, Contact, Evidence, IdentityStatus, Priority, RunItem, Usage, utc_now
from prospecting.pipeline import find_contacts
from prospecting.providers import ClaudeClient, HttpResponse
from prospecting.providers.hunter import HUNTER_OPERATIONS, HunterAccess
from prospecting.providers.tavily import TAVILY_OPERATIONS


@pytest.fixture
def contact_case(database, config, make_campaign, make_company, make_assessment, monkeypatch):
    """Una cuenta ficticia por bolsa y un transporte inyectado para todas las operaciones."""
    from prospecting.providers import ProviderClient
    for variable in ("HUNTER_API_KEY", "TAVILY_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(variable, "clave-exclusivamente-sintetica")
    campaign = make_campaign()
    company, sources = make_company(name="Empresa Sintética", domain="empresa-sintetica.example",
                                    operating_countries=["CO"], segments=["fintech_software"],
                                    identity_status="confirmed", identity_key="entidad-sintetica|CO")
    database.save_campaign(campaign)
    database.save_company(company, evidence=sources)
    database.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id, stage="assessed"))
    assessment = make_assessment(campaign.id, company.id, priority="medium", target_roles=["Product Manager"])
    database.save_assessment(assessment)
    run = database.get_run_item(campaign.id, company.id)
    database.save_run_item(run.model_copy(update={"last_assessment_id": assessment.id}))
    now = utc_now()
    pools = [AccountAllowance(provider=provider, account_ref=account, funding_source=funding,
                             credit_limit="30", cost_limit_usd="3", observed_at=now,
                             source_reference="Cupo sintético")
             for provider, account, funding in (("hunter", "hunter-synthetic:unified", "free_credit"),
                                               ("tavily", "tavily-synthetic", "free_credit"),
                                               ("anthropic", "claude-synthetic", "prepaid"))]
    budget = Budget(database, config.defaults.budget, pools)
    grants = [budget.authorize(SpendingAuthorization(
        provider=pool.provider, account_ref=pool.account_ref, operation=operation,
        max_cost_usd="1" if pool.provider == "anthropic" else "0", max_credits="30",
        responsible="Responsable sintético", source_reference="Permiso sintético sin red",
        authorized_at=utc_now(),
    )) for pool in pools for operation in {
        "hunter": ("domain_search", "email_finder", "email_verifier"),
        "tavily": ("search", "extract"), "anthropic": ("messages",),
    }[pool.provider]]
    access = HunterAccess(search_account_ref=pools[0].account_ref,
                          enabled_operations=["domain_search", "email_finder", "email_verifier"],
                          automatic_lead_saving_disabled=True, funding_source="free_credit",
                          checked_at=now, source_reference="Acceso ficticio comprobado")
    case = SimpleNamespace(db=database, campaign=campaign, company=company, assessment=assessment,
                           budget=budget, grants=grants, access=access, calls=[], replies={}, model_calls=[])

    def body(operation, params):
        if operation == "domain_search":
            return {"data": {"domain": company.domain, "organization": company.name, "emails": []}}
        if operation == "email_finder":
            return {"data": {"domain": company.domain, "company": company.name,
                             "first_name": "Persona Sintética", "last_name": "Uno",
                             "email": "persona@empresa-sintetica.example",
                             "verification": {"status": "valid", "date": utc_now().date().isoformat()}}}
        if operation == "email_verifier":
            return {"data": {"email": params["email"], "status": "valid",
                             "verification": {"status": "valid", "date": utc_now().date().isoformat()}}}
        if operation == "search":
            return {"results": [{"url": f"https://{company.domain}/equipo", "content": "Equipo sintético"}],
                    "usage": {"credits": 1}}
        return {"results": [{"url": url, "raw_content": nominal_text(case)} for url in params["urls"]],
                "usage": {"credits": 1}}

    def transport(prepared, timeout, max_bytes):
        assert not database._connection.in_transaction
        path = urlsplit(prepared.full_url).path.split("/")[-1].replace("-", "_")
        params = json.loads(prepared.data) if prepared.data else {
            key: values[0] for key, values in parse_qs(urlsplit(prepared.full_url).query).items()}
        case.calls.append((path, params, timeout))
        reply = case.replies.get(path, body(path, params))
        if isinstance(reply, BaseException):
            raise reply
        if callable(reply):
            reply = reply(params)
        if isinstance(reply, HttpResponse):
            return reply
        return HttpResponse(status=200, headers={"Content-Type": "application/json"}, body=json.dumps(reply).encode())

    case.client = ProviderClient(budget, HUNTER_OPERATIONS + TAVILY_OPERATIONS, transport=transport)

    def model_reply(**payload):
        case.model_calls.append(payload)
        if hasattr(case, "model_override"):
            text = case.model_override
        else:
            user = payload["messages"][0]["content"]
            context = json.loads(user.split("\n")[0])
            sources = [json.loads(piece) for piece in user.split("<evidencia>\n")[1].split("\n</evidencia>")[0].splitlines()]
            source = sources[0]
            text = json.dumps({"candidates": [{
                "contact_id": context["contacts"][0]["contact_id"] if context["contacts"] else None,
                "name": "Persona Sintética Uno", "facts": [
                    {"field": field, "value": value, "evidence_id": source["evidence_id"], "quote": source["excerpt"]}
                    for field, value in (("name", "Persona Sintética Uno"), ("title", "Product Manager"),
                                         ("employment", company.name), ("email", "persona@empresa-sintetica.example"))]}]})
        return SimpleNamespace(id="mensaje-sintetico", model=payload["model"], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=500, output_tokens=100),
                               content=[SimpleNamespace(type="text", text=text)])
    sdk = SimpleNamespace(with_options=lambda **kwargs: SimpleNamespace(messages=SimpleNamespace(create=model_reply)))
    case.claude = ClaudeClient(budget, sdk_client=sdk)
    case.find = lambda **kwargs: find_contacts(
        database, budget, case.client, case.campaign.id, company.id,
        **({"hunter_access": case.access, "authorizations": case.grants} | kwargs))
    return case


def nominal_text(case):
    return f"Persona Sintética Uno es Product Manager de {case.company.name}. Correo profesional persona@empresa-sintetica.example."


def seed_contact(case, status=None, *, current=True, partial=False):
    id = uuid4()
    source = Evidence(company_id=case.company.id, contact_id=id, claim="Directorio corporativo exclusivamente sintético",
                      url=f"https://{case.company.domain}/equipo", excerpt=nominal_text(case),
                      retrieved_at=utc_now(), kind="observed", source_type="primary")
    channels, sources = [], [source]
    if status is not None:
        fact = Evidence(company_id=case.company.id, contact_id=id, claim="Verificación sintética del correo persona@empresa-sintetica.example",
                        provider="hunter", external_reference="verificacion-sintetica", retrieved_at=utc_now(),
                        kind="observed", source_type="provider")
        sources.append(fact)
        channels.append(Channel(contact_id=id, type="email", value="persona@empresa-sintetica.example",
                                evidence_ids=[fact.id], retrieved_at=utc_now(), normalized_status=status,
                                verified_at=utc_now() if status in ("verified", "invalid") else None,
                                professional=True, direct=True))
    contact = Contact(id=id, company_id=case.company.id, name="Persona Sintética Uno", title="Product Manager",
                      name_complete=not partial, current_employment=current, relevant_function=True,
                      identity_status="pending" if partial else "confirmed", channels=channels,
                      provenance={field: [source.id] for field in ("name", "title", "relevant_function")},
                      employment_evidence_ids=[source.id])
    case.db.save_contact(contact, evidence=sources)
    return contact


def test_cached_ready_contact_stops_before_any_network(contact_case):
    contact = seed_contact(contact_case, "verified")
    report = contact_case.find()
    assert report.status == "checked" and report.business_status == "ready_preferred"
    assert report.contact_ids == [contact.id] and contact_case.calls == []
    assert contact_case.db.get_run_item(contact_case.campaign.id, contact_case.company.id).stage == "contacts_checked"
    assert contact_case.find().status == "already_checked"


@pytest.mark.parametrize("change", ["identity", "excluded", "low", "insufficient", "missing_assessment"])
def test_preconditions_prevent_all_calls(contact_case, change):
    case = contact_case
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    if change == "identity":
        case.db.save_company(case.company.model_copy(update={"identity_status": IdentityStatus.PENDING, "identity_key": None}))
    elif change == "excluded":
        case.db.save_run_item(run.model_copy(update={"business_status": BusinessStatus.EXCLUDED}))
    else:
        if change == "missing_assessment":
            # Otra empresa sintética de la campaña aún no calificada.
            case.db._connection.execute("UPDATE run_items SET last_assessment_id=NULL")
        else:
            case.db._connection.execute("UPDATE assessments SET priority=?", ("low" if change == "low" else "insufficient_evidence",))
    assert case.find().status == "skipped" and case.calls == []


def test_domain_search_and_public_extraction_complete_nominal_contact(contact_case):
    case = contact_case
    case.replies["domain_search"] = {"data": {"domain": case.company.domain, "organization": case.company.name, "emails": [{
        "value": "persona@empresa-sintetica.example", "type": "personal", "first_name": "Persona Sintética", "last_name": "Uno",
        "position": "Product Manager", "verification": {"status": "valid", "date": utc_now().date().isoformat()}}]}}
    report = case.find(tavily_account_ref="tavily-synthetic", claude=case.claude, claude_account_ref="claude-synthetic")
    assert report.status == "checked" and report.business_status == "ready_preferred"
    assert [operation for operation, _, _ in case.calls] == ["domain_search", "search", "search", "extract"]
    assert len(case.model_calls) == 1 and len(case.db.list_contacts(case.company.id)) == 1
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    assert run.consumed_limits.people_queries == 1 and run.consumed_limits.web_queries == 2
    assert run.consumed_limits.pages == 1 and run.consumed_limits.contacts_active_seconds >= 0
    assert sum(key.startswith("contacts:person:") for key in run.attempts) == 1
    calls = len(case.calls)
    assert case.find().status == "already_checked" and len(case.calls) == calls


def test_public_only_route_does_not_require_hunter(contact_case):
    case = contact_case
    report = case.find(hunter_access=None, tavily_account_ref="tavily-synthetic", claude=case.claude,
                       claude_account_ref="claude-synthetic")
    assert report.business_status == "ready_preferred"
    assert all(operation in ("search", "extract") for operation, _, _ in case.calls)


def test_finder_only_for_identified_person_without_email(contact_case):
    case = contact_case
    seed_contact(case)
    report = case.find()
    assert report.business_status == "ready_preferred"
    assert [operation for operation, _, _ in case.calls] == ["domain_search", "email_finder"]
    assert case.calls[1][1]["full_name"] == "Persona Sintética Uno" and case.calls[1][1]["max_duration"] == "6"
    usage = case.db.list_usage(provider="hunter")
    assert all(item.credits is None and item.reserved_credits == 1 for item in usage)


def test_medium_finder_does_not_add_verifier_after_exhausting_enrichment(contact_case):
    case = contact_case
    seed_contact(case)
    case.replies["email_finder"] = {"data": {"domain": case.company.domain, "first_name": "Persona Sintética", "last_name": "Uno",
                                            "email": "persona@empresa-sintetica.example", "verification": {"status": "unknown"}}}
    report = case.find()
    assert report.business_status == "needs_channel_confirmation"
    assert [operation for operation, _, _ in case.calls] == ["domain_search", "email_finder"]
    assert case.db.get_run_item(case.campaign.id, case.company.id).consumed_limits.enrichments == 1


def test_verifier_uses_fractional_credit_and_specific_timeout(contact_case):
    case = contact_case
    seed_contact(case, "unknown")
    report = case.find()
    assert report.business_status == "ready_preferred"
    assert [operation for operation, _, _ in case.calls] == ["domain_search", "email_verifier"]
    assert case.calls[-1][2] == 25.0
    usage = case.db.list_usage(provider="hunter")[-1]
    assert usage.reserved_credits == Decimal("0.5") and usage.credits is None


def test_pending_verification_conserves_reserve_and_never_polls(contact_case):
    case = contact_case
    seed_contact(case, "unknown")
    case.replies["email_verifier"] = HttpResponse(status=202, headers={"Content-Type": "application/json"}, body=b'{"data":{}}')
    report = case.find()
    assert report.status == "pending" and report.stop_reason == "verification_pending"
    usage = case.db.list_usage(provider="hunter")[-1]
    assert usage.status == "uncertain" and usage.reserved_credits == Decimal("0.5")
    assert case.db.get_run_item(case.campaign.id, case.company.id).stage == "assessed"
    count = len(case.calls)
    assert case.find().status == "pending" and len(case.calls) == count


@pytest.mark.parametrize("reply", [TimeoutError(), HttpResponse(status=222, headers={"Content-Type": "application/json"}, body=b'{"errors":[{"id":"smtp_error","details":"Fallo SMTP sintetico"}]}'), HttpResponse(status=200, headers={"Content-Type": "application/json"}, body=b'{')])
def test_failed_verification_keeps_contact_and_checkpoint(contact_case, reply):
    case = contact_case
    contact = seed_contact(case, "unknown")
    case.replies["email_verifier"] = reply
    report = case.find()
    assert report.status == "pending" and case.db.get_contact(contact.id) is not None
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    assert run.stage == "assessed" and run.error_stage == "contacts_checked" and run.error_message
    assert case.db.list_usage(provider="hunter")[-1].reserved_credits == Decimal("0.5")
    count = len(case.calls)
    assert case.find().status == "pending" and len(case.calls) == count


def test_no_authorization_balance_or_price_prevents_transport(contact_case):
    case = contact_case
    report = case.find(authorizations=[])
    assert report.status == "pending" and report.stop_reason == "authorization_required" and case.calls == []
    case.budget.account_allowances[0] = case.budget.account_allowances[0].model_copy(update={"credit_limit": Decimal(0)})
    assert case.find().stop_reason == "budget_exceeded" and case.calls == []
    case.access = case.access.model_copy(update={"funding_source": "prepaid"})
    assert case.find().stop_reason == "price_unbounded" and case.calls == []


def test_automatic_lead_saving_blocks_finder_and_verifier(contact_case):
    case = contact_case
    seed_contact(case)
    report = case.find(hunter_access=case.access.model_copy(update={"automatic_lead_saving_disabled": False}))
    assert report.business_status == "qualified_no_contact"
    assert [operation for operation, _, _ in case.calls] == ["domain_search"]


def test_missing_persisted_result_never_repeats_sent_operation(contact_case):
    case = contact_case
    from prospecting.providers.hunter import domain_search_request
    request = domain_search_request(case.company, ["Product Manager"], case.access.search_account_ref)
    usage = Usage(campaign_id=case.campaign.id, company_id=case.company.id, provider="hunter", operation="domain_search",
                  account_ref=case.access.search_account_ref, request_fingerprint=case.client.fingerprint(request),
                  reserved_credits="1", reserved_cost_usd="0", funding_source="free_credit", status="succeeded", outcome="succeeded")
    case.db.save_usage(usage)
    report = case.find()
    assert report.status == "pending" and report.stop_reason == "result_unavailable" and case.calls == []


def test_exhausted_empty_search_is_reused_between_campaigns(contact_case, make_campaign, make_assessment):
    case = contact_case
    assert case.find().business_status == "qualified_no_contact"
    previous_calls = len(case.calls)
    case.campaign = make_campaign()
    case.db.save_campaign(case.campaign)
    case.db.save_run_item(RunItem(campaign_id=case.campaign.id, company_id=case.company.id, stage="assessed"))
    assessment = make_assessment(case.campaign.id, case.company.id, priority="medium", target_roles=["Product Manager"])
    case.db.save_assessment(assessment)
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    case.db.save_run_item(run.model_copy(update={"last_assessment_id": assessment.id}))
    assert case.find().status == "checked" and len(case.calls) == previous_calls
    assert len(case.db.list_usage()) == 1


def test_invalid_haiku_output_cannot_be_repeated_or_become_checked(contact_case):
    case = contact_case
    case.model_override = '{"candidates":[{"contact_id":null,"name":"Inventado Sintético","facts":[]}]}'
    args = dict(tavily_account_ref="tavily-synthetic", claude=case.claude, claude_account_ref="claude-synthetic")
    assert case.find(**args).status == "pending"
    calls = len(case.calls)
    assert case.find(**args).status == "pending"
    assert len(case.model_calls) == 1 and len(case.calls) == calls and case.db.list_contacts(case.company.id) == []


def test_time_limit_preserves_previous_data_without_transport(contact_case):
    case = contact_case
    contact = seed_contact(case)
    report = case.find(deadline=0.0)
    assert report.status == "pending" and report.stop_reason == "time_limit" and case.calls == []
    assert case.db.get_contact(contact.id) is not None


def test_zero_reduced_people_limit_stops_without_any_call(contact_case):
    case = contact_case
    limits = case.campaign.limits.model_copy(deep=True)
    limits.effort["medium"] = limits.effort["medium"].model_copy(update={"people": 0})
    case.db.save_campaign(case.campaign.model_copy(update={"limits": limits}))
    assert case.find().stop_reason == "people_limit" and case.calls == []


def high_priority(case):
    assessment = case.assessment.model_copy(update={"id": uuid4(), "priority": Priority.HIGH,
                                                  "revision_of": case.assessment.id})
    case.db.save_assessment(assessment)
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    case.db.save_run_item(run.model_copy(update={"last_assessment_id": assessment.id}))


def test_high_priority_bounds_people_and_second_department_query(contact_case):
    case = contact_case
    high_priority(case)
    case.replies["domain_search"] = {"data": {"domain": case.company.domain, "organization": case.company.name,
        "emails": [{"value": f"persona-{index}@empresa-sintetica.example", "type": "personal",
                    "first_name": "Persona Sintética", "last_name": f"Candidato{index}", "position": "Product Manager"}
                   for index in range(10)]}}
    report = case.find()
    assert report.business_status == "qualified_no_contact" and len(case.db.list_contacts(case.company.id)) == 3
    assert len(case.calls) == 2 and case.calls[0][1]["job_titles"] == "Product Manager"
    assert case.calls[1][1]["department"] == "product" and "job_titles" not in case.calls[1][1]
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    assert run.consumed_limits.people_queries == 2
    assert sum(key.startswith("contacts:person:") for key in run.attempts) == 3


def test_first_useful_domain_result_stops_high_priority(contact_case):
    case = contact_case
    high_priority(case)
    contact = seed_contact(case, "unknown")
    case.replies["domain_search"] = {"data": {"domain": case.company.domain, "organization": case.company.name, "emails": [{
        "value": "persona@empresa-sintetica.example", "type": "personal", "first_name": "Persona Sintética", "last_name": "Uno",
        "position": "Product Manager", "verification": {"status": "valid", "date": utc_now().date().isoformat()}}]}}
    report = case.find(tavily_account_ref="tavily-synthetic", claude=case.claude, claude_account_ref="claude-synthetic")
    assert report.business_status == "ready_preferred" and report.contact_ids == [contact.id]
    assert [operation for operation, _, _ in case.calls] == ["domain_search"] and case.model_calls == []


@pytest.mark.parametrize("status,reason", [(401, "permission_denied"), (429, "quota_exceeded"), (451, "privacy_restricted")])
def test_hunter_unavailable_without_public_route_keeps_stage_and_literal_error(contact_case, status, reason):
    case = contact_case
    case.replies["domain_search"] = HttpResponse(status=status, headers={"Content-Type": "application/json"},
        body=b'{"errors":[{"id":"synthetic_error","details":"Fallo sintetico conservado"}]}')
    report = case.find()
    assert report.status == "pending" and report.stop_reason == reason and "Fallo sintetico conservado" in report.error_message
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    assert run.stage == "assessed" and case.db.list_contacts(case.company.id) == []


def test_unavailable_hunter_can_complete_through_authorized_public_route(contact_case):
    case = contact_case
    case.replies["domain_search"] = HttpResponse(status=401, headers={"Content-Type": "application/json"},
        body=b'{"errors":[{"id":"unauthorized","details":"Sin permiso sintetico"}]}')
    report = case.find(tavily_account_ref="tavily-synthetic", claude=case.claude, claude_account_ref="claude-synthetic")
    assert report.business_status == "ready_preferred" and report.status == "checked"
    assert report.warnings and "Sin permiso sintetico" in report.warnings[0]


@pytest.mark.parametrize("status", [401, 429])
@pytest.mark.parametrize("priority", ["medium", "high"])
def test_handled_hunter_failure_resumes_public_route_without_another_domain_search(
        contact_case, make_assessment, status, priority):
    case = contact_case
    assessment = make_assessment(case.campaign.id, case.company.id, priority=priority,
                                 target_roles=["Product Manager"])
    case.db.save_assessment(assessment)
    item = case.db.get_run_item(case.campaign.id, case.company.id)
    case.db.save_run_item(item.model_copy(update={"last_assessment_id": assessment.id}))
    case.replies["domain_search"] = HttpResponse(status=status, headers={"Content-Type": "application/json"},
        body=b'{"errors":[{"id":"synthetic_error","details":"Fallo Hunter sintetico conservado"}]}')
    args = {"tavily_account_ref": "tavily-synthetic", "claude": case.claude,
            "claude_account_ref": "claude-synthetic"}
    hunter_only = [grant for grant in case.grants if grant.provider == "hunter"]
    first = case.find(authorizations=hunter_only, **args)
    assert first.status == "pending" and first.stop_reason == "authorization_required"
    [usage] = case.db.list_usage()
    assert usage.outcome == "failed" and usage.status == "failed"
    saved = case.db.get_run_item(case.campaign.id, case.company.id)
    assert saved.attempts[f"contacts:processed:{usage.request_fingerprint}"] == 1
    assert [operation for operation, _, _ in case.calls] == ["domain_search"]
    resumed = case.find(**args)
    assert resumed.status == "checked" and resumed.business_status == "ready_preferred"
    assert any("Fallo Hunter sintetico conservado" in warning for warning in resumed.warnings)
    assert [operation for operation, _, _ in case.calls].count("domain_search") == 1
    assert case.db.get_usage(usage.request_id) == usage
    assert case.db.get_run_item(case.campaign.id, case.company.id).attempts["contacts:domain_search"] == 1
    before = len(case.calls)
    assert case.find(**args).status == "already_checked" and len(case.calls) == before


@pytest.mark.parametrize("marked_processed", [False, True])
def test_uncertain_hunter_failure_blocks_same_campaign_even_after_public_authorization(contact_case, marked_processed):
    case = contact_case
    case.replies["domain_search"] = TimeoutError()
    args = {"tavily_account_ref": "tavily-synthetic", "claude": case.claude,
            "claude_account_ref": "claude-synthetic"}
    first = case.find(authorizations=[grant for grant in case.grants if grant.provider == "hunter"], **args)
    assert first.status == "pending" and first.stop_reason == "timeout"
    [usage] = case.db.list_usage()
    saved = case.db.get_run_item(case.campaign.id, case.company.id)
    assert usage.status == "uncertain" and f"contacts:processed:{usage.request_fingerprint}" not in saved.attempts
    if marked_processed:
        case.db.save_run_item(saved.model_copy(update={"attempts": saved.attempts | {
            f"contacts:processed:{usage.request_fingerprint}": 1}}))
    resumed = case.find(**args)
    assert resumed.status == "pending"
    assert resumed.stop_reason == ("request_uncertain" if marked_processed else "timeout")
    assert [operation for operation, _, _ in case.calls] == ["domain_search"]
    assert case.db.get_usage(usage.request_id) == usage


def test_existing_corporate_directory_is_used_without_rebuying_web_data(contact_case):
    case = contact_case
    case.db.save_evidence(Evidence(company_id=case.company.id, claim="Directorio corporativo sintético",
                         url=f"https://{case.company.domain}/equipo", excerpt=nominal_text(case),
                         retrieved_at=utc_now(), source_type="primary", kind="observed"))
    report = case.find(tavily_account_ref="tavily-synthetic", claude=case.claude, claude_account_ref="claude-synthetic")
    assert report.business_status == "ready_preferred" and [operation for operation, _, _ in case.calls] == ["domain_search"]
    assert len(case.model_calls) == 1


def test_unsafe_search_urls_are_not_extracted_or_used_as_contact(contact_case):
    case = contact_case
    case.replies["search"] = {"results": [{"url": "http://127.0.0.1/private", "content": nominal_text(case)},
                                           {"url": "https://linkedin.com/in/perfil-sintetico", "content": nominal_text(case)}],
                              "usage": {"credits": 1}}
    report = case.find(tavily_account_ref="tavily-synthetic", claude=case.claude, claude_account_ref="claude-synthetic")
    assert report.business_status == "qualified_no_contact" and all(operation != "extract" for operation, _, _ in case.calls)
    assert case.model_calls == []


def test_linkedin_ready_only_with_persisted_manual_confirmation(contact_case):
    case = contact_case
    contact = seed_contact(case)
    manual = Evidence(company_id=case.company.id, contact_id=contact.id, claim="Mensajería directa confirmada, prueba sintética",
                      provider="manual", external_reference="confirmacion-sintetica", retrieved_at=utc_now(),
                      kind="observed", source_type="manual")
    channel = Channel(contact_id=contact.id, type="linkedin", value="https://linkedin.com/in/persona-sintetica",
                      evidence_ids=[manual.id], retrieved_at=utc_now(), normalized_status="manual_confirmed",
                      manual_confirmed_at=utc_now(), manual_confirmation_reason="Confirmación exclusivamente sintética",
                      professional=True, direct=True)
    case.db.save_contact(contact.model_copy(update={"channels": [channel]}), evidence=[manual])
    access = case.access.model_copy(update={"enabled_operations": ["domain_search"]})
    report = case.find(hunter_access=access)
    assert report.business_status == "ready_alternative"
    assert [operation for operation, _, _ in case.calls] == ["domain_search"]


def test_cached_eligible_person_has_priority_over_new_unresolved_candidate(contact_case):
    case = contact_case
    cached = seed_contact(case)
    case.replies["domain_search"] = {"data": {"domain": case.company.domain, "organization": case.company.name, "emails": [{
        "value": "otra-persona@empresa-sintetica.example", "type": "personal", "first_name": "Otra Persona",
        "last_name": "Sintética", "position": "Product Manager"}]}}
    report = case.find()
    assert report.business_status == "ready_preferred" and report.contact_ids == [cached.id]
    assert [operation for operation, _, _ in case.calls] == ["domain_search", "email_finder"]


def test_uncertain_request_is_not_repeated_by_a_new_campaign(contact_case, make_campaign, make_assessment):
    case = contact_case
    case.replies["domain_search"] = TimeoutError()
    assert case.find().status == "pending"
    assert case.db.list_usage()[0].status == "uncertain"
    case.campaign = make_campaign()
    case.db.save_campaign(case.campaign)
    case.db.save_run_item(RunItem(campaign_id=case.campaign.id, company_id=case.company.id, stage="assessed"))
    assessment = make_assessment(case.campaign.id, case.company.id, priority="medium", target_roles=["Product Manager"])
    case.db.save_assessment(assessment)
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    case.db.save_run_item(run.model_copy(update={"last_assessment_id": assessment.id}))
    case.replies.pop("domain_search")
    report = case.find()
    assert report.status == "pending" and report.stop_reason == "request_uncertain"
    assert len(case.calls) == 1 and len(case.db.list_usage()) == 1


def test_separate_verification_pool_is_not_funded_by_search_credits(contact_case):
    case = contact_case
    seed_contact(case, "unknown")
    verification = AccountAllowance(provider="hunter", account_ref="hunter-synthetic:verification",
                                    funding_source="free_credit", credit_limit="0", observed_at=utc_now(),
                                    source_reference="Bolsa de verificación sintética sin saldo")
    case.budget.account_allowances.append(verification)
    case.access = case.access.model_copy(update={"unified_credits": False,
                                               "verification_account_ref": verification.account_ref})
    case.grants.append(case.budget.authorize(SpendingAuthorization(
        provider="hunter", operation="email_verifier", account_ref=verification.account_ref,
        max_cost_usd="0", max_credits="1", responsible="Responsable sintético",
        source_reference="Permiso sintético de bolsa independiente", authorized_at=utc_now())))
    report = case.find()
    assert report.status == "pending" and report.stop_reason == "budget_exceeded"
    assert [operation for operation, _, _ in case.calls] == ["domain_search"]
    case.budget.account_allowances[-1] = verification.model_copy(update={"credit_limit": Decimal(1)})
    report = case.find()
    assert report.business_status == "ready_preferred"
    usage = case.db.list_usage()[-1]
    assert usage.account_ref == verification.account_ref and usage.reserved_credits == Decimal(1)


def test_prepaid_hunter_reserves_exact_economic_cost_without_recharging(contact_case):
    case = contact_case
    seed_contact(case, "unknown")
    valuation = CreditValuation(unit_value_usd="0.10", source_reference="Valoración exclusivamente sintética", observed_at=utc_now())
    case.budget.account_allowances[0] = case.budget.account_allowances[0].model_copy(
        update={"funding_source": "prepaid", "credit_valuation": valuation})
    case.access = case.access.model_copy(update={"funding_source": "prepaid"})
    permits = [case.budget.authorize(SpendingAuthorization(
        provider="hunter", operation=operation, account_ref=case.access.search_account_ref,
        max_cost_usd="0.20", max_credits="2", responsible="Responsable sintético",
        source_reference="Permiso sintético prepago", authorized_at=utc_now()))
        for operation in ("domain_search", "email_verifier")]
    report = case.find(authorizations=permits)
    assert report.business_status == "ready_preferred"
    usage = case.db.list_usage()
    assert [item.reserved_cost_usd for item in usage] == [Decimal("0.10"), Decimal("0.05")]
    assert all(item.funding_source == "prepaid" and item.outlay_usd is None and item.final_cost_usd is None for item in usage)


@pytest.mark.parametrize("title,entity", [("Engineering Director", "Empresa Sintética"),
                                         ("Product Manager", "Otra Entidad Sintética")])
def test_public_contradiction_suspends_ready_alternative_and_preserves_both_facts(contact_case, title, entity):
    case = contact_case
    contact = seed_contact(case)
    manual = Evidence(company_id=case.company.id, contact_id=contact.id, claim="Mensajería nominal sintética confirmada",
                      provider="manual", external_reference="revision-sintetica", retrieved_at=utc_now(),
                      kind="observed", source_type="manual")
    channel = Channel(contact_id=contact.id, type="linkedin", value="https://linkedin.com/in/persona-sintetica",
                      evidence_ids=[manual.id], retrieved_at=utc_now(), normalized_status="manual_confirmed",
                      manual_confirmed_at=utc_now(), manual_confirmation_reason="Acceso sintético confirmado",
                      professional=True, direct=True)
    case.db.save_contact(contact.model_copy(update={"channels": [channel]}), evidence=[manual])
    source = Evidence(company_id=case.company.id, claim="Cambio laboral exclusivamente sintético",
                      url=f"https://{case.company.domain}/equipo-actual", retrieved_at=utc_now(),
                      excerpt=f"Persona Sintética Uno es {title} de {entity}.", kind="observed", source_type="primary")
    case.db.save_evidence(source)
    case.model_override = json.dumps({"candidates": [{"contact_id": str(contact.id), "name": "Persona Sintética Uno", "facts": [
        {"field": field, "value": value, "quote": source.excerpt, "evidence_id": str(source.id)}
        for field, value in (("name", "Persona Sintética Uno"), ("title", title), ("employment", entity))]}]})
    report = case.find(claude=case.claude, claude_account_ref="claude-synthetic")
    assert report.status == "checked" and report.business_status == "qualified_no_contact"
    saved = case.db.get_contact(contact.id)
    assert saved.identity_status == "contradicted" and saved.company_id == case.company.id
    assert any(item.contradiction_ids for item in case.db.list_evidence(case.company.id))
    assert saved.channels[0].manual_confirmed_at == channel.manual_confirmed_at
    assert [operation for operation, _, _ in case.calls] == ["domain_search"]


_GENERATED = re.compile(r"[0-9a-f]{64}|[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}")


def persisted(case):
    """Lo que la reanudación compara: claves de intentos, consumo y referencias, sin ids ni fechas."""
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    return {
        "attempts": sorted(f"{_GENERATED.sub('<id>', key)}={value}" for key, value in run.attempts.items()),
        "usage": [(item.provider, item.operation, item.account_ref, str(item.status), str(item.reserved_credits),
                   str(item.reserved_cost_usd), item.funding_source, item.company_id == case.company.id)
                  for item in case.db.list_usage()],
        "evidence": sorted((_GENERATED.sub("<id>", item.external_reference or ""), item.source_type, item.kind,
                            item.claim.startswith("Tavily devolvió esta página"))
                           for item in case.db.list_evidence(case.company.id)),
        "searches": [params for operation, params, _ in case.calls if operation == "search"],
    }


PUBLIC_SEARCH = {"search_depth": "basic", "topic": "general", "max_results": 10, "include_usage": True,
                 "exclude_domains": ["linkedin.com"]}
COMPANY_FACTS = [("", "primary", "observed", False)] * 4
HUNTER_USAGE = ("hunter", "domain_search", "hunter-synthetic:unified", "succeeded", "1", "0", "free_credit", True)
EXPECTED_PERSISTED = {
    "public": {
        "attempts": [
            "contacts:extract=1", "contacts:haiku=1", "contacts:haiku_request:<id>=1", "contacts:pages=1",
            "contacts:person:<id>=1", *["contacts:processed:<id>=1"] * 4, *["contacts:request:<id>=1"] * 3,
            "contacts:web_queries=2",
        ],
        "usage": [
            ("tavily", "search", "tavily-synthetic", "succeeded", "1", "0", "free_credit", True),
            ("tavily", "search", "tavily-synthetic", "succeeded", "1", "0", "free_credit", True),
            ("tavily", "extract", "tavily-synthetic", "succeeded", "1", "0", "free_credit", True),
            ("anthropic", "messages", "claude-synthetic", "succeeded", "0", "0.0009145", "prepaid", True),
        ],
        "evidence": [
            *COMPANY_FACTS, ("<id>", "provider", "inference", False), ("<id>#1.1", "primary", "observed", False),
            *[(f"<id>#1.1#contact:{field}", "primary", "observed", False)
              for field in ("email", "employment", "name", "title")],
            *[("contacts_search:<id>:0", "secondary", "observed", True)] * 2,
        ],
        "searches": [
            {"query": '"Empresa Sintética" Product Manager equipo directorio CO'} | PUBLIC_SEARCH,
            {"query": '"Empresa Sintética" equipo producto ingeniería marketing contacto profesional'} | PUBLIC_SEARCH,
        ],
    },
    "finder": {
        "attempts": ["contacts:domain_search=1", "contacts:hunter_enrichments=1", "contacts:person:<id>=1",
                     *["contacts:processed:<id>=1"] * 2, *["contacts:request:<id>=1"] * 2],
        "usage": [HUNTER_USAGE, ("hunter", "email_finder", "hunter-synthetic:unified", "succeeded", "1", "0",
                                 "free_credit", True)],
        "evidence": [*COMPANY_FACTS, ("", "primary", "observed", False), ("<id>#email", "provider", "observed", False)],
        "searches": [],
    },
    "verifier": {
        "attempts": ["contacts:domain_search=1", "contacts:hunter_enrichments=1", "contacts:person:<id>=1",
                     *["contacts:processed:<id>=1"] * 2, *["contacts:request:<id>=1"] * 2,
                     "contacts:verify:<id>=1"],
        "usage": [HUNTER_USAGE, ("hunter", "email_verifier", "hunter-synthetic:unified", "succeeded", "0.5", "0",
                                 "free_credit", True)],
        "evidence": [*COMPANY_FACTS, ("", "primary", "observed", False),
                     ("<id>#verification", "provider", "observed", False),
                     ("verificacion-sintetica", "provider", "observed", False)],
        "searches": [],
    },
}


@pytest.mark.parametrize("route", ["public", "finder", "verifier"])
def test_persisted_keys_and_ledger_do_not_change(contact_case, route):
    case = contact_case
    if route == "public":
        case.find(hunter_access=None, tavily_account_ref="tavily-synthetic", claude=case.claude,
                  claude_account_ref="claude-synthetic")
    else:
        seed_contact(case, "unknown" if route == "verifier" else None)
        case.find()
    assert persisted(case) == EXPECTED_PERSISTED[route]
