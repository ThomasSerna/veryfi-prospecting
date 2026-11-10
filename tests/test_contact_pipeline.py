"""Contactos Apollo exclusivamente sintéticos; ningún transporte real está habilitado."""

import json
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4, uuid5

import pytest

from prospecting.budget import AccountAllowance, Budget, SpendingAuthorization
from prospecting.contacts import contact_context, target_roles
from prospecting.db import Database
from prospecting.models import Assessment, BusinessStatus, Channel, Contact, Evidence, IdentityStatus, RunItem, Usage, utc_now
from prospecting.pipeline import find_contacts, read_campaign
from prospecting.providers import ClaudeClient, HttpResponse, ProviderClient
from prospecting.providers.apollo import APOLLO_OPERATIONS, ApolloAccess, ApolloSearchResponse, parse_search, person_id
from prospecting.providers.tavily import TAVILY_OPERATIONS, contact_search_request


@pytest.fixture
def contact_case(database, config, make_campaign, make_company, make_assessment, monkeypatch):
    for variable in ("APOLLO_API_KEY", "TAVILY_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(variable, "clave-exclusivamente-sintetica")
    campaign = make_campaign(config_snapshot=config.model_copy(update={"people_provider": "apollo"}))
    company, sources = make_company(name="Empresa Sintética", domain="empresa-sintetica.example",
        operating_countries=["CO"], segments=["fintech_software"], identity_status="confirmed", identity_key="entidad-sintetica|CO")
    database.save_campaign(campaign)
    database.save_company(company, evidence=sources)
    database.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id, stage="assessed"))
    assessment = make_assessment(campaign.id, company.id, priority="medium", target_roles=["Product Manager"])
    database.save_assessment(assessment)
    database.save_run_item(database.get_run_item(campaign.id, company.id).model_copy(update={"last_assessment_id": assessment.id}))
    pools = [AccountAllowance(provider=provider, account_ref=f"{provider}-synthetic", funding_source=funding,
        credit_limit="30", cost_limit_usd="3", observed_at=utc_now(), source_reference="Cupo sintético")
        for provider, funding in (("apollo", "free_credit"), ("tavily", "free_credit"), ("anthropic", "prepaid"))]
    budget = Budget(database, config.defaults.budget, pools)
    grants = [budget.authorize(SpendingAuthorization(provider=pool.provider, account_ref=pool.account_ref,
        operation=operation, max_cost_usd="1" if pool.provider == "anthropic" else "0",
        max_credits="0" if operation == "people_search" else "30", responsible="Responsable sintético",
        source_reference="Permiso sintético sin red", authorized_at=utc_now()))
        for pool in pools for operation in {"apollo": ("people_search", "people_enrichment"),
            "tavily": ("search", "extract"), "anthropic": ("messages",)}[pool.provider]]
    access = ApolloAccess(account_ref=pools[0].account_ref, access_verified=True, work_email_verified=True,
        observed_at=utc_now(), source_reference="Acceso exclusivamente sintético")
    case = SimpleNamespace(db=database, campaign=campaign, company=company, assessment=assessment, budget=budget,
        grants=grants, access=access, calls=[], replies={}, model_calls=[], people=[], publish_email=True,
        page_text=None, public_title="Product Manager")

    def response(operation, payload):
        if operation == "people_search":
            return {"people": case.people, "total_entries": len(case.people)}
        if operation == "people_enrichment":
            return {"person": {"id": payload["id"], "first_name": "Persona Sintética", "last_name": "Uno",
                "name": "Persona Sintética Uno", "title": "Product Manager", "match_confidence": "high",
                "email": "persona@empresa-sintetica.example", "email_status": "verified", "organization_id": "org-sintetica",
                "organization": {"id": "org-sintetica", "name": company.name, "primary_domain": company.domain},
                "employment_history": [{"current": True, "organization_id": "org-sintetica", "organization_name": company.name,
                                        "title": "Product Manager"}]}}
        if operation == "search":
            return {"results": [{"url": f"https://{company.domain}/equipo", "content": "Equipo sintético"}], "usage": {"credits": 1}}
        text = f"Persona Sintética Uno es Product Manager de {company.name}."
        if case.publish_email:
            text += " Correo profesional persona@empresa-sintetica.example."
        text = text if case.page_text is None else case.page_text
        return {"results": [{"url": url, "raw_content": text} for url in payload["urls"]], "usage": {"credits": 1}}

    def transport(prepared, timeout, max_bytes):
        assert not database._connection.in_transaction
        path = urlsplit(prepared.full_url).path.split("/")[-1]
        operation = {"api_search": "people_search", "match": "people_enrichment"}.get(path, path)
        payload = json.loads(prepared.data)
        case.calls.append((operation, payload, timeout))
        reply = case.replies.get(operation)
        reply = response(operation, payload) if reply is None else reply(payload) if callable(reply) else reply
        if isinstance(reply, BaseException):
            raise reply
        return reply if isinstance(reply, HttpResponse) else HttpResponse(status=200,
            headers={"Content-Type": "application/json"}, body=json.dumps(reply).encode())

    case.client = ProviderClient(budget, APOLLO_OPERATIONS + TAVILY_OPERATIONS, transport=transport)

    def model_reply(**payload):
        case.model_calls.append(payload)
        user = payload["messages"][0]["content"]
        context = json.loads(user.split("\n")[0])
        supplied = [json.loads(piece) for piece in user.split("<evidencia>\n")[1].split("\n</evidencia>")[0].splitlines()]
        source = next((item for item in supplied if "Persona Sintética Uno" in item["excerpt"]), None)
        known = next((item["contact_id"] for item in context["contacts"] if item["name"] == "Persona Sintética Uno"), None)
        facts = [("name", "Persona Sintética Uno"), ("title", case.public_title), ("employment", company.name)]
        if case.publish_email:
            facts.append(("email", "persona@empresa-sintetica.example"))
        # Sin una fuente que nombre a la persona, Haiku no propone candidatos.
        text = json.dumps({"candidates": [] if source is None else [{"contact_id": known, "name": "Persona Sintética Uno", "facts": [
            {"field": field, "value": value, "evidence_id": source["evidence_id"], "quote": source["excerpt"]}
            for field, value in facts]}]})
        return SimpleNamespace(id="mensaje-sintetico", model=payload["model"], stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=500, output_tokens=100), content=[SimpleNamespace(type="text", text=text)])

    sdk = SimpleNamespace(with_options=lambda **kwargs: SimpleNamespace(messages=SimpleNamespace(create=model_reply)))
    case.claude = ClaudeClient(budget, sdk_client=sdk)
    case.find = lambda **kwargs: find_contacts(database, budget, case.client, case.campaign.id, company.id,
        **({"apollo_access": case.access, "authorizations": case.grants} | kwargs))
    case.public = {"tavily_account_ref": "tavily-synthetic", "claude": case.claude, "claude_account_ref": "anthropic-synthetic"}
    return case


def add_candidate(case, identifier="persona-sintetica", title="Product Manager"):
    case.people.append({"id": identifier, "first_name": "Persona Sintética", "last_name_obfuscated": "U***",
        "title": title, "last_refreshed_at": utc_now().isoformat(), "organization": {"name": case.company.name}})


def enable_role_taxonomy(case, role_config, *, matched=True):
    case.campaign = case.campaign.model_copy(update={"id": uuid4(), "config_snapshot": role_config})
    case.db.save_campaign(case.campaign)
    case.db.save_run_item(RunItem(campaign_id=case.campaign.id, company_id=case.company.id, stage="assessed"))
    matches = []
    if matched:
        source = Evidence(company_id=case.company.id, claim="Caso de uso sintético de gastos", kind="observed", source_type="primary",
                          url=f"https://{case.company.domain}/producto", retrieved_at=utc_now(),
                          excerpt="La empresa permite gestionar recibos y reembolsos.")
        case.db.save_evidence(source)
        matches = [{"profile_id": "expense_reimbursement", "citations": [{"evidence_id": source.id, "quote": source.excerpt}]}]
    case.assessment = Assessment.model_validate(case.assessment.model_dump() | {
        "id": uuid4(), "campaign_id": case.campaign.id, "profile_matches": matches})
    case.db.save_assessment(case.assessment)
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    case.db.save_run_item(run.model_copy(update={"last_assessment_id": case.assessment.id}))


def test_taxonomy_without_evidenced_case_is_pending_without_consumption(contact_case, role_config):
    case = contact_case
    enable_role_taxonomy(case, role_config, matched=False)
    report = case.find(**case.public)
    assert report.status == "pending" and report.stop_reason == "no_target_roles"
    assert case.calls == [] and case.model_calls == [] and case.db.list_usage() == []


def test_taxonomy_search_filters_first_query_and_reuses_processed_requests(contact_case, role_config):
    case = contact_case
    enable_role_taxonomy(case, role_config)
    report = case.find()
    requests = [payload for operation, payload, _ in case.calls if operation == "people_search"]
    assert len(requests) == 2
    assert requests[0]["person_seniorities"]
    assert "person_seniorities" not in requests[1]
    assert all(payload["person_titles"] and payload["include_similar_titles"] is False for payload in requests)
    assert report.business_status == "qualified_no_contact"
    assert case.find().status == "already_checked" and len(case.calls) == 2


def test_later_profile_contradiction_prevents_search_without_rewriting_assessment(contact_case, role_config):
    case = contact_case
    enable_role_taxonomy(case, role_config)
    citation = case.assessment.profile_matches[0].citations[0]
    case.db.save_evidence(Evidence(company_id=case.company.id, kind="observed", source_type="primary", retrieved_at=utc_now(),
        url=f"https://{case.company.domain}/producto", claim="La información sintética anterior queda contradicha.",
        contradiction_ids=[citation.evidence_id]))
    report = case.find()
    assert report.status == "pending" and report.stop_reason == "no_target_roles"
    assert case.calls == [] and case.db.list_usage() == []
    assert case.db.get_assessment(case.assessment.id).profile_matches


@pytest.mark.parametrize("change", ["absent", "access", "work_email", "operation"])
def test_unverified_access_blocks_apollo_and_public_transport(contact_case, change):
    case = contact_case
    access = None if change == "absent" else case.access.model_copy(update={"access_verified": change != "access",
        "work_email_verified": change != "work_email", "enabled_operations": ["people_search"] if change == "operation" else case.access.enabled_operations})
    report = case.find(apollo_access=access, **case.public)
    assert report.status == "pending" and report.stop_reason == "apollo_access_unverified"
    assert case.calls == [] and case.model_calls == [] and case.db.list_usage() == []


def test_legacy_campaign_is_read_only_without_network(contact_case):
    case = contact_case
    case.db._connection.execute("UPDATE campaigns SET config_snapshot=json_remove(config_snapshot, '$.people_provider')")
    assert case.find(**case.public).stop_reason == "legacy_campaign_read_only"
    assert case.calls == [] and case.db.list_usage() == []


def test_missing_apollo_key_blocks_public_route_before_reservation(contact_case, monkeypatch):
    case = contact_case
    monkeypatch.delenv("APOLLO_API_KEY")
    assert case.find(**case.public).stop_reason == "apollo_access_unverified"
    assert case.calls == [] and case.db.list_usage() == []


@pytest.mark.parametrize("change", ["identity", "excluded", "low", "insufficient", "missing_assessment"])
def test_preconditions_prevent_all_calls(contact_case, change):
    case = contact_case
    if change == "identity":
        case.db.save_company(case.company.model_copy(update={"identity_status": IdentityStatus.PENDING, "identity_key": None}))
    elif change == "excluded":
        case.db.save_run_item(case.db.get_run_item(case.campaign.id, case.company.id).model_copy(update={"business_status": BusinessStatus.EXCLUDED}))
    elif change == "missing_assessment":
        case.db._connection.execute("UPDATE run_items SET last_assessment_id=NULL")
    else:
        case.db._connection.execute("UPDATE assessments SET priority=?", ("low" if change == "low" else "insufficient_evidence",))
    assert case.find().status == "skipped" and case.calls == []


def test_search_is_bounded_zero_credit_and_idempotent(contact_case):
    case = contact_case
    assert case.find().business_status == "qualified_no_contact"
    broad, targeted = [item[1] for item in case.calls]
    assert broad == {"q_organization_domains_list": [case.company.domain], "page": 1, "per_page": 10}
    assert targeted["person_titles"][0] == "Product Manager" and targeted["include_similar_titles"] is False
    assert all(row.reserved_credits == row.credits == row.reserved_cost_usd == 0 for row in case.db.list_usage())
    assert case.find().status == "already_checked" and len(case.calls) == 2


def test_zero_credit_search_still_requires_authorization(contact_case):
    case = contact_case
    assert case.find(authorizations=[]).stop_reason == "authorization_required"
    assert case.calls == [] and case.db.list_usage() == []


def test_partial_candidate_reaches_enrichment_without_becoming_ready(contact_case):
    case = contact_case
    add_candidate(case)
    report = case.find()
    assert [item[0] for item in case.calls] == ["people_search", "people_search", "people_enrichment"]
    [contact] = case.db.list_contacts(case.company.id)
    assert contact.name == "Persona Sintética Uno" and contact.name_complete is True
    assert contact.current_employment is None and contact.channels[0].normalized_status == "provider_verified"
    assert contact.channels[0].provider_status == "verified" and contact.channels[0].verified_at is None
    assert report.business_status == "qualified_no_contact"
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    assert run.consumed_limits.people_queries == 2 and run.consumed_limits.enrichments == 1
    assert not any(key.startswith("contacts:person:") for key in run.attempts)


def test_candidate_survives_reopen_and_waits_for_enrichment_authorization(contact_case, tmp_path):
    case = contact_case
    add_candidate(case)
    report = case.find(authorizations=[grant for grant in case.grants if grant.operation == "people_search"])
    assert report.status == "pending" and report.stop_reason == "authorization_required"
    with Database(tmp_path / "synthetic.sqlite3") as reopened:
        [contact] = reopened.list_contacts(case.company.id)
        assert contact.name_complete is False and "U***" in contact.name
        assert person_id(contact, reopened.list_evidence(case.company.id)) == "persona-sintetica"
    assert case.find().status == "checked"
    assert [item[0] for item in case.calls] == ["people_search", "people_search", "people_enrichment"]


def employment_of(case, tmp_path):
    """Lee la campaña como la interfaz: el estado de vigencia se calcula al leer y no se guarda."""
    company = next(item for item in read_campaign(tmp_path / "synthetic.sqlite3", case.campaign.id).companies
                   if item.company.id == case.company.id)
    [person] = company.contacts
    return person, company


def test_enrichment_precedes_public_nominal_job_and_channel_evidence(contact_case, tmp_path):
    case = contact_case
    add_candidate(case)
    report = case.find(**case.public)
    assert report.status == "checked" and report.business_status == "ready_preferred"
    assert [item[0] for item in case.calls] == ["people_search", "people_search", "people_enrichment", "search", "search", "extract"]
    queries = [item[1]["query"] for item in case.calls if item[0] == "search"]
    assert queries[0].startswith('"Persona Sintética Uno"') and all("U***" not in item for item in queries)
    [contact] = case.db.list_contacts(case.company.id)
    assert contact.current_employment is True and contact.channels[0].normalized_status == "provider_verified"
    assert contact.channels[0].published_evidence_ids and len(case.model_calls) == 1
    assert sum(key.startswith("contacts:person:") for key in case.db.get_run_item(case.campaign.id, case.company.id).attempts) == 1
    # T18: la página corporativa extraída con Tavily, y no Apollo, justifica el empleo; no se envía nada.
    person, _ = employment_of(case, tmp_path)
    assert (person.employment.state, person.employment.origin, person.employment.reason) == (
        "corporate_evidence", "apollo", None)
    facts = {item.id: item for item in case.db.list_evidence(case.company.id)}
    assert all(facts[id].source_type == "primary" and facts[id].url.path == "/equipo"
               and facts[id].claim.startswith("Hecho nominal publicado: employment=") for id in person.employment.evidence_ids)


def test_public_page_without_the_person_keeps_the_apollo_claim(contact_case, tmp_path):
    case = contact_case
    case.page_text = f"Equipo directivo sintético de {case.company.name}."
    add_candidate(case)
    report = case.find(**case.public)
    assert report.business_status == "qualified_no_contact"
    person, _ = employment_of(case, tmp_path)
    assert (person.eligible, person.employment.state, person.employment.reason) == (
        False, "provider_claim", "provider_claim_only")
    [contact] = case.db.list_contacts(case.company.id)
    assert contact.current_employment is None and contact.channels[0].provider_status == "verified"


def test_public_departure_contradicts_the_apollo_claim(contact_case, tmp_path):
    case = contact_case
    case.publish_email = False
    case.page_text = f"Persona Sintética Uno dejó de ser Product Manager de {case.company.name} en septiembre."
    add_candidate(case)
    assert case.find(**case.public).business_status == "qualified_no_contact"
    person, _ = employment_of(case, tmp_path)
    assert (person.employment.state, person.employment.reason) == ("contradicted", "employment_ended")
    assert person.contact.current_employment is False and not person.eligible


def test_public_page_with_another_title_contradicts_the_apollo_title(contact_case, tmp_path):
    case = contact_case
    case.publish_email = False
    case.public_title = "CFO"
    case.page_text = f"Persona Sintética Uno es CFO de {case.company.name}."
    add_candidate(case)
    assert case.find(**case.public).business_status == "qualified_no_contact"
    person, _ = employment_of(case, tmp_path)
    assert (person.employment.state, person.employment.reason, person.employment.review_required) == (
        "contradicted", "title_changed", True)
    assert person.contact.identity_status == "contradicted" and not person.eligible


def test_verified_label_without_date_stays_pending_after_public_job_evidence(contact_case):
    case = contact_case
    case.publish_email = False
    add_candidate(case)
    assert case.find(**case.public).business_status == "needs_channel_confirmation"
    [contact] = case.db.list_contacts(case.company.id)
    assert contact.current_employment is True and contact.channels[0].verified_at is None


def test_empty_apollo_results_keep_authorized_public_route(contact_case):
    case = contact_case
    assert case.find(**case.public).business_status == "ready_preferred"
    [contact] = case.db.list_contacts(case.company.id)
    assert contact.id == uuid5(case.company.id, "public_apollo_v1:persona@empresa-sintetica.example")
    assert all(item.provider != "hunter" for item in case.db.list_evidence(case.company.id))


@pytest.mark.parametrize("status,reason", [(401, "permission_denied"), (403, "permission_denied"), (429, "rate_limited")])
def test_apollo_errors_keep_literal_and_do_not_fall_back(contact_case, status, reason):
    case = contact_case
    case.replies["people_search"] = HttpResponse(status=status, headers={"Content-Type": "application/json"},
        body=b'{"error":"Fallo Apollo exclusivamente sintetico"}')
    report = case.find(**case.public)
    assert report.status == "pending" and report.stop_reason == reason and "Fallo Apollo exclusivamente sintetico" in report.error_message
    assert [item[0] for item in case.calls] == ["people_search"] and case.model_calls == []
    run = case.db.get_run_item(case.campaign.id, case.company.id)
    assert run.stage == "assessed" and run.error_stage == "contacts_checked"


@pytest.mark.parametrize("response", [TimeoutError(), HttpResponse(status=200, headers={"Content-Type": "application/json"}, body=b"{")])
def test_sent_unavailable_results_are_never_repeated(contact_case, response):
    case = contact_case
    case.replies["people_search"] = response
    assert case.find().status == "pending"
    rows = [row.model_dump() for row in case.db.list_usage()]
    assert case.find().status == "pending" and len(case.calls) == 1
    assert [row.model_dump() for row in case.db.list_usage()] == rows


def test_wrong_enrichment_identity_preserves_partial_candidate(contact_case):
    case = contact_case
    add_candidate(case)
    case.replies["people_enrichment"] = {"person": {"id": "otra-persona"}}
    report = case.find(**case.public)
    assert report.status == "pending" and report.stop_reason == "identity_mismatch"
    [contact] = case.db.list_contacts(case.company.id)
    assert contact.name_complete is False and contact.channels == []
    assert all(item[0] != "search" for item in case.calls)


def test_medium_enrichment_cap_excludes_irrelevant_candidates(contact_case):
    case = contact_case
    add_candidate(case, "otro-cargo", "Accountant")
    add_candidate(case, "persona-uno")
    add_candidate(case, "persona-dos")
    case.find()
    enriched = [item[1]["id"] for item in case.calls if item[0] == "people_enrichment"]
    assert len(enriched) == 1 and "otro-cargo" not in enriched and len(case.db.list_contacts(case.company.id)) == 3


@pytest.mark.parametrize("people_limit", [1, 3])
def test_high_priority_respects_people_cap_and_distinct_ids_with_shared_mailbox(contact_case, people_limit):
    case = contact_case
    case.db._connection.execute("UPDATE assessments SET priority='high'")
    limits = case.campaign.limits.model_copy(deep=True)
    limits.effort["high"] = limits.effort["high"].model_copy(update={"people": people_limit})
    case.db.save_campaign(case.campaign.model_copy(update={"limits": limits}))
    for index in range(5):
        add_candidate(case, f"persona-sintetica-{index}")
    case.find()
    assert sum(item[0] == "people_enrichment" for item in case.calls) == people_limit
    people = case.db.list_contacts(case.company.id)
    assert len(people) == 5 and sum(bool(item.channels) for item in people) == people_limit
    assert len({person_id(item, case.db.list_evidence(case.company.id)) for item in people}) == 5


def test_search_refresh_does_not_replace_an_enriched_full_name(contact_case):
    from prospecting.contacts import merge_contact

    case = contact_case
    add_candidate(case)
    case.find()
    [known] = case.db.list_contacts(case.company.id)
    [(partial, facts)] = parse_search(case.company, ApolloSearchResponse(
        people=case.people, total_entries=1), uuid4(), utc_now())
    refreshed = merge_contact(known, partial, case.db.list_evidence(case.company.id) + facts)
    assert refreshed.name == known.name and refreshed.name_complete is True
    assert refreshed.identity_status == "confirmed"


def test_unknown_credit_limit_blocks_every_transport(contact_case):
    case = contact_case
    add_candidate(case)
    case.budget.account_allowances[0] = case.budget.account_allowances[0].model_copy(update={"credit_limit": None})
    assert case.find().stop_reason == "apollo_access_unverified"
    assert case.calls == [] and case.db.list_usage() == []


def test_deadline_blocks_every_transport(contact_case):
    case = contact_case
    assert case.find(deadline=0).stop_reason == "time_limit" and case.calls == []


def test_legacy_ready_contact_does_not_stop_or_receive_new_facts(contact_case):
    case = contact_case
    identifier = uuid4()
    source = Evidence(company_id=case.company.id, contact_id=identifier, kind="observed", source_type="primary",
        url=f"https://{case.company.domain}/equipo", retrieved_at=utc_now(), claim="Directorio sintético",
        excerpt=f"Persona Sintética Uno es Product Manager de {case.company.name}.")
    verification = Evidence(company_id=case.company.id, contact_id=identifier, kind="observed", source_type="provider",
        provider="hunter", external_reference="verificacion-legacy-sintetica", retrieved_at=utc_now(), claim="persona@empresa-sintetica.example verificado")
    old = Contact(id=identifier, company_id=case.company.id, name="Persona Sintética Uno", title="Product Manager",
        name_complete=True, current_employment=True, relevant_function=True, identity_status="confirmed",
        provenance={field: [source.id] for field in ("name", "title", "relevant_function")}, employment_evidence_ids=[source.id],
        channels=[Channel(contact_id=identifier, type="email", value="persona@empresa-sintetica.example", evidence_ids=[verification.id],
            retrieved_at=utc_now(), verified_at=utc_now(), normalized_status="verified", professional=True, direct=True)])
    case.db.save_contact(old, evidence=[source, verification])
    old_facts = case.db.list_evidence(case.company.id, contact_id=old.id)
    add_candidate(case)
    assert case.find(**case.public).business_status == "ready_preferred"
    assert case.db.get_contact(old.id) == old and case.db.list_evidence(case.company.id, contact_id=old.id) == old_facts
    all_people, all_facts = case.db.list_contacts(case.company.id), case.db.list_evidence(case.company.id)
    new_people, new_facts = contact_context(case.campaign, all_people, all_facts)
    assert len(new_people) == 1 and new_people[0].id != old.id and verification not in new_facts
    legacy = case.campaign.model_copy(update={"config_snapshot": case.campaign.config_snapshot.model_copy(update={"people_provider": None})})
    assert contact_context(legacy, all_people, all_facts)[0] == [old]


def test_legacy_processed_cache_is_not_reused_by_new_contacts(contact_case, make_campaign):
    case = contact_case
    legacy = make_campaign(config_snapshot=case.campaign.config_snapshot.model_copy(update={"people_provider": None}))
    case.db.save_campaign(legacy)
    roles = target_roles(case.company, case.assessment, case.campaign)
    query = f'"{case.company.name}" {" ".join(roles[:4])} equipo directorio CO'
    request = contact_search_request(query, "tavily-synthetic")
    fingerprint = case.client.fingerprint(request)
    case.db.save_run_item(RunItem(campaign_id=legacy.id, company_id=case.company.id, attempts={f"contacts:processed:{fingerprint}": 1}))
    case.db.save_usage(Usage(campaign_id=legacy.id, company_id=case.company.id, provider="tavily", operation="search",
        account_ref="tavily-synthetic", request_fingerprint=fingerprint, reserved_credits=1, reserved_cost_usd=0,
        funding_source="free_credit", status="succeeded", outcome="succeeded"))
    case.find(**case.public)
    searches = [item for item in case.calls if item[0] == "search"]
    assert len(searches) == 2 and searches[0][1]["query"] == query


@pytest.mark.parametrize("blocked", ["account", "credential"])
def test_direct_public_only_stage_checks_apollo_before_spend(contact_case, monkeypatch, blocked):
    case = contact_case
    limits = case.campaign.limits.model_dump()
    limits["effort"]["medium"]["people_queries"] = 0
    campaign = type(case.campaign).model_validate(case.campaign.model_dump() | {"limits": limits})
    case.db.save_campaign(campaign)
    pools = case.budget.account_allowances
    if blocked == "account":
        pools = [item for item in pools if item.provider != "apollo"]
    else:
        monkeypatch.setenv("APOLLO_API_KEY", "clave-sintetica\x01")
    budget = Budget(case.db, campaign.config_snapshot.defaults.budget, pools)
    report = find_contacts(case.db, budget, case.client, campaign.id, case.company.id,
                           apollo_access=case.access, authorizations=case.grants, **case.public)
    assert report.stop_reason == "apollo_access_unverified"
    assert case.calls == [] and case.model_calls == [] and case.db.list_usage() == []


def test_checkpoint_keeps_an_attempt_written_by_another_connection(database, make_campaign, make_company,
                                                                   monkeypatch, tmp_path):
    """T17, concurrencia local: el checkpoint lee el RunItem dentro de su transacción y no pierde claves ajenas."""
    from contextlib import contextmanager
    import time

    from prospecting.pipeline.contacts import _ContactStage

    campaign = database.save_campaign(make_campaign())
    company, facts = make_company()
    database.save_company(company, evidence=facts)
    database.save_run_item(RunItem(campaign_id=campaign.id, company_id=company.id))
    stage = _ContactStage.__new__(_ContactStage)
    stage.db, stage.campaign, stage.company = database, campaign, company
    stage.tick, stage.evidence_ids = time.monotonic(), []
    original = database.transaction

    @contextmanager
    def racing():
        # Otra conexión guarda una clave justo antes de que el checkpoint abra su transacción.
        with Database(tmp_path / "synthetic.sqlite3") as other:
            with other.transaction():
                item = other.get_run_item(campaign.id, company.id)
                other.save_run_item(item.model_copy(update={"attempts": item.attempts | {"contacts:apollo_enrichments": 1}}))
        with original():
            yield

    monkeypatch.setattr(database, "transaction", racing)
    stage.checkpoint(attempts={"contacts:apollo_search": 1})
    saved = database.get_run_item(campaign.id, company.id).attempts
    assert saved["contacts:apollo_enrichments"] == 1 and saved["contacts:apollo_search"] == 1
