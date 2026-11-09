"""Confirmación manual del empleo vigente (T23), con personas, páginas y respuestas exclusivamente sintéticas."""

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from prospecting.contact_extraction import parse_contacts_output
from prospecting.contacts import (
    apply_target_roles, contact_match, derive_readiness, employment_confirmation_titles, employment_status,
    load_contact_match, manual_employment_evidence, mentions, person_function, person_stage, resolve_manual_employment,
    target_roles, validate_contact,
)
from prospecting.db import Database
from prospecting.models import BusinessStatus, ChannelStatus, Evidence, RunItem
from prospecting.pipeline import campaign as bridge
from prospecting.pipeline.contacts import confirm_current_employment
from prospecting.providers.apollo import ApolloEnrichmentResponse, ApolloSearchResponse, parse_enrichment, parse_search


NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)
PERSON_ID = "persona-sintetica"
NAME, TITLE, EMAIL = "Persona Sintética", "CTO", "persona-sintetica@example.com"
DIRECTORY = f"{NAME}, {TITLE} de Empresa sintética, correo {EMAIL}."
SOURCE_URL = "https://example.com/equipo-sintetico"
REASON = "Revisé el directorio corporativo sintético y la persona figura con ese cargo."
V2 = load_contact_match(Path(__file__).resolve().parents[1] / "config" / "contact_match_v2.json")


@pytest.fixture
def case(make_campaign, make_company, make_assessment):
    campaign = make_campaign()
    company, _ = make_company(domain="example.com", entity_name="Empresa sintética", segments=["fintech_software"],
                              identity_status="confirmed")
    assessment = make_assessment(campaign.id, company.id, priority="high", target_roles=[TITLE])
    return SimpleNamespace(campaign=campaign, company=company, assessment=assessment, limits=campaign.limits)


def search(case, **person):
    response = ApolloSearchResponse.model_validate({"total_entries": 1, "people": [{
        "id": PERSON_ID, "first_name": "Persona", "last_name_obfuscated": "S***", "title": TITLE,
        "last_refreshed_at": NOW.isoformat(), "has_email": True, "organization": {"name": "Empresa sintética"},
    } | person]})
    [(contact, facts)] = parse_search(case.company, response, uuid4(), NOW)
    return contact, facts


def apollo_person(case, **person):
    contact, facts = search(case, **({"title": person["title"]} if "title" in person else {}))
    response = ApolloEnrichmentResponse.model_validate({"person": {
        "id": PERSON_ID, "first_name": "Persona", "last_name": "Sintética", "name": NAME, "title": TITLE,
        "match_confidence": "high", "email": EMAIL, "email_status": "verified", "organization_id": "empresa-sintetica",
        "organization": {"id": "empresa-sintetica", "name": "Empresa sintética", "primary_domain": "example.com"},
        "employment_history": [{"current": True, "organization_id": "empresa-sintetica", "title": TITLE}],
    } | person})
    enriched, new = parse_enrichment(contact, case.company, response, uuid4(), NOW)
    return apply_target_roles(enriched, [TITLE]), facts + new


def page(case, excerpt, *, path="/equipo", contact_id=None, source_type="primary", **fields):
    return Evidence(company_id=case.company.id, contact_id=contact_id, url=f"https://example.com{path}",
                    claim="Texto publicado en la página, extraído por Tavily.", provider="tavily",
                    external_reference=f"tavily-sintetico#{uuid4()}", excerpt=excerpt,
                    retrieved_at=fields.pop("retrieved_at", NOW), kind="observed", source_type=source_type, **fields)


def corroborate(case, contact, facts, source, *, title=TITLE, at=NOW):
    cited = [("name", NAME), ("title", title), ("employment", "Empresa sintética"), ("email", EMAIL)]
    output = {"candidates": [{"contact_id": str(contact.id), "name": NAME, "facts": [
        {"field": field, "value": value, "evidence_id": str(source.id), "quote": source.excerpt}
        for field, value in cited if mentions(source.excerpt, value)]}]}
    [(merged, derived)] = parse_contacts_output(json.dumps(output), "end_turn", case.company, case.assessment,
                                                case.campaign, [source], at, uuid4(), contacts=[contact])
    return merged, facts + [source] + derived


def confirm(case, contact, facts, *, title=TITLE, at=NOW):
    """Lo que guardaría la confirmación: el hecho manual citado y, si cambia, el cargo elegido y su pertinencia."""
    fact = manual_employment_evidence(case.company, contact, case.campaign.id, title=title, source_url=SOURCE_URL,
                                      reason=REASON, now=at)
    person = contact.model_copy(update={"title": title,
                                        "employment_evidence_ids": contact.employment_evidence_ids + [fact.id]})
    if title != contact.title:
        person = apply_target_roles(person, [TITLE])
    return person, facts + [fact], fact


def status(case, contact, facts, now=NOW):
    """Calcula el estado y comprueba que ni la persona ni la evidencia cambian al leer."""
    before = (contact.model_dump(), [item.model_dump() for item in facts])
    result = employment_status(contact, case.company, facts, case.limits, now)
    assert (contact.model_dump(), [item.model_dump() for item in facts]) == before
    return result


def verified(contact):
    """Correo de Apollo con verificación vigente sintética, para aislar la condición de listo."""
    return contact.model_copy(update={"channels": [
        channel.model_copy(update={"normalized_status": ChannelStatus.VERIFIED, "verified_at": NOW})
        for channel in contact.channels]})


def title_change(case):
    contact, facts = apollo_person(case)
    merged, facts = corroborate(case, contact, facts, page(case, f"{NAME}, CFO de Empresa sintética."), title="CFO")
    assert (status(case, merged, facts).state, status(case, merged, facts).reason) == ("contradicted", "title_changed")
    return merged, facts


def test_manual_confirmation_turns_an_apollo_claim_into_manual_evidence_and_enables_ready(case):
    contact, facts = apollo_person(case)
    assert status(case, contact, facts).state == "provider_claim"
    assert employment_confirmation_titles(contact, case.company, facts, case.limits, NOW) == [TITLE]
    person, evidence, fact = confirm(case, verified(contact), facts)
    result = status(case, person, evidence)
    assert (result.state, result.origin, result.reason, result.basis) == ("corporate_evidence", "apollo", None, "manual")
    assert result.evidence_ids == [fact.id] and result.confirmed_at == NOW
    assert result.confirmation_expires_at == NOW + timedelta(days=case.limits.cache.contact_days)
    assert (result.confirmation_reason, result.confirmation_source) == (REASON, SOURCE_URL)
    assert person.current_employment is None and person.identity_status == "confirmed"
    assert validate_contact(person, case.company, case.assessment, evidence, case.limits, NOW)
    assert derive_readiness(case.assessment, [person], evidence, case.limits, NOW, case.company) == "ready_preferred"
    assert person_stage(person, case.company, case.assessment, evidence, case.limits, NOW) == "ready"
    match = contact_match(person, case.company, case.assessment, evidence, case.limits, NOW, [TITLE], V2)
    assert next(item.points for item in match.components if item.name == "employment") == 25
    assert employment_confirmation_titles(person, case.company, evidence, case.limits, NOW) == []
    without = status(case, verified(contact), facts)
    assert without.basis is None and not validate_contact(verified(contact), case.company, case.assessment, facts,
                                                          case.limits, NOW)


def test_public_evidence_keeps_source_basis(case):
    contact, facts = apollo_person(case)
    merged, facts = corroborate(case, contact, facts, page(case, DIRECTORY))
    result = status(case, merged, facts)
    assert (result.state, result.basis, result.confirmed_at) == ("corporate_evidence", "source", None)
    assert status(case, contact, apollo_person(case)[1]).basis is None


@pytest.mark.parametrize("scenario", ["claim", "title_change"])
def test_expired_confirmation_reads_exactly_as_without_it(case, scenario):
    contact, facts = apollo_person(case) if scenario == "claim" else title_change(case)
    person, evidence, _ = confirm(case, contact, facts, title=contact.title, at=NOW + timedelta(days=5))
    days = case.limits.cache.contact_days
    inside = NOW + timedelta(days=5 + days)
    assert status(case, person, evidence, inside).basis == "manual"
    expired = inside + timedelta(seconds=1)
    original = status(case, contact, facts, expired)
    assert status(case, person, evidence, expired).model_dump(exclude={"evidence_ids"}) == original.model_dump(
        exclude={"evidence_ids"})
    if scenario == "title_change":
        assert (original.state, original.reason) == ("contradicted", "title_changed")
    assert not validate_contact(verified(person), case.company, case.assessment, evidence, case.limits, expired)


def test_future_or_other_title_confirmations_do_not_apply(case):
    contact, facts = apollo_person(case)
    future, evidence, _ = confirm(case, contact, facts, at=NOW + timedelta(hours=1))
    assert status(case, future, evidence).state == "provider_claim"
    other, evidence, fact = confirm(case, contact, facts)
    other = other.model_copy(update={"title": "VP Engineering"})
    assert not mentions(fact.excerpt, other.title)
    assert status(case, other, evidence).basis is None


@pytest.mark.parametrize("later", ["departure", "other_entity"])
def test_later_departure_or_other_entity_cancels_the_confirmation(case, later):
    contact, facts = apollo_person(case)
    person, evidence, _ = confirm(case, contact, facts)
    if later == "departure":
        news = page(case, f"{NAME} dejó la empresa en octubre.", path="/noticias", contact_id=person.id,
                    source_type="secondary", retrieved_at=NOW + timedelta(days=1))
        evidence = evidence + [news]
    else:
        person = person.model_copy(update={"current_employment": False})
    result = status(case, person, evidence, NOW + timedelta(days=1))
    assert (result.state, result.reason, result.basis) == ("contradicted", "employment_ended", None)
    assert employment_confirmation_titles(person, case.company, evidence, case.limits, NOW + timedelta(days=1)) == []


@pytest.mark.parametrize("chosen", ["CFO", TITLE])
def test_title_change_confirmation_resolves_prior_title_contradictions_only_while_reading(case, chosen):
    merged, facts = title_change(case)
    assert employment_confirmation_titles(merged, case.company, facts, case.limits, NOW) == ["CFO", TITLE]
    stored = [item.model_dump() for item in facts]
    person, evidence, fact = confirm(case, verified(merged), facts, title=chosen)
    result = status(case, person, evidence)
    assert (result.state, result.basis, result.evidence_ids[0]) == ("corporate_evidence", "manual", fact.id)
    assert person.identity_status == "contradicted" and [item.model_dump() for item in facts] == stored
    projected, resolved = resolve_manual_employment(person, evidence, case.limits, NOW)
    assert projected.identity_status == "confirmed" and person.identity_status == "contradicted"
    assert not any(item.contradiction_ids for item in resolved if item.contact_id == person.id)
    assert resolve_manual_employment(projected, resolved, case.limits, NOW) == (projected, resolved)
    match = contact_match(person, case.company, case.assessment, evidence, case.limits, NOW, [TITLE], V2)
    assert match.blocked_reason is None
    assert {item.name: item.level for item in match.components}["identity"] == "confirmed_complete"
    assert next(item.points for item in match.components if item.name == "employment") == 25
    # Sin la confirmación la persona es candidata (identidad contradicha); el cargo objetivo puede quedar listo.
    assert person_stage(verified(merged), case.company, case.assessment, facts, case.limits, NOW) == "candidate"
    stage = person_stage(person, case.company, case.assessment, evidence, case.limits, NOW)
    assert stage == ("ready" if chosen == TITLE else "identity_verified")
    ready = derive_readiness(case.assessment, [person], evidence, case.limits, NOW, case.company)
    assert ready == ("ready_preferred" if chosen == TITLE else "qualified_no_contact")


def test_later_title_contradiction_cancels_the_confirmation(case):
    merged, facts = title_change(case)
    person, evidence, _ = confirm(case, merged, facts, title="CFO")
    assert status(case, person, evidence).basis == "manual"
    later = NOW + timedelta(days=1)
    newer = page(case, f"{NAME}, CFO de Empresa sintética.", path="/equipo-2026", contact_id=person.id,
                 retrieved_at=later, contradiction_ids=[person.provenance["title"][0]])
    result = status(case, person, evidence + [newer], later)
    assert (result.state, result.reason, result.basis) == ("contradicted", "title_changed", None)


def test_taxonomy_reads_the_confirmed_title_without_the_resolved_contradiction(role_config, make_campaign, make_company,
                                                                                make_assessment):
    """En campañas con taxonomía la función se recalcula al leer, también con la contradicción resuelta."""
    campaign = make_campaign(config_snapshot=role_config)
    company, _ = make_company(domain="example.com", entity_name="Empresa sintética", segments=["fintech_software"],
                              identity_status="confirmed", operating_countries=["CO"])
    use_case = Evidence(company_id=company.id, claim="Caso de uso sintético", url="https://example.com/producto",
                        excerpt="La empresa gestiona recibos y reembolsos.", retrieved_at=NOW, kind="observed",
                        source_type="primary")
    assessment = make_assessment(campaign.id, company.id, priority="high", profile_matches=[{
        "profile_id": "expense_reimbursement", "citations": [{"evidence_id": use_case.id, "quote": use_case.excerpt}]}])
    case = SimpleNamespace(campaign=campaign, company=company, assessment=assessment, limits=campaign.limits)
    contact, facts = apollo_person(case, title="Head of Product", employment_history=[
        {"current": True, "organization_id": "empresa-sintetica", "title": "Head of Product"}])
    merged, facts = corroborate(case, contact, [use_case] + facts, page(case, f"{NAME}, CFO de Empresa sintética."),
                                title="CFO")
    assert status(case, merged, facts).reason == "title_changed"
    assert employment_confirmation_titles(merged, company, facts, case.limits, NOW) == ["CFO", "Head of Product"]
    person, evidence, _ = confirm(case, verified(merged), facts, title="Head of Product")
    roles = target_roles(company, assessment, campaign, evidence=evidence)
    assert validate_contact(person, company, assessment, evidence, case.limits, NOW, roles, campaign=campaign)
    assert person_function(person, company, assessment, campaign, evidence, NOW) == "product"
    assert person_stage(person, company, assessment, evidence, case.limits, NOW, roles, campaign=campaign) == "ready"
    assert derive_readiness(assessment, [person], evidence, case.limits, NOW, company, roles,
                            campaign=campaign) == "ready_preferred"
    later = NOW + timedelta(days=case.limits.cache.contact_days + 1)
    assert not validate_contact(person, company, assessment, evidence, case.limits, later, roles, campaign=campaign)


def test_only_apollo_claims_and_title_changes_admit_confirmation(case):
    contact, facts = apollo_person(case)
    # Nombre ofuscado o sin enriquecer: candidata, nunca confirmable.
    candidate, search_facts = search(case)
    assert employment_confirmation_titles(candidate, case.company, search_facts, case.limits, NOW) == []
    # Afirmación vencida (`unknown`) y evidencia corporativa ya vigente.
    later = NOW + timedelta(days=case.limits.cache.contact_days + 1)
    assert employment_status(contact, case.company, facts, case.limits, later).state == "unknown"
    assert employment_confirmation_titles(contact, case.company, facts, case.limits, later) == []
    merged, corroborated = corroborate(case, contact, facts, page(case, DIRECTORY))
    assert employment_confirmation_titles(merged, case.company, corroborated, case.limits, NOW) == []
    # Fuente del puesto contradicha (`contradicted_source`).
    employment = next(item for item in corroborated if item.claim.startswith("Hecho nominal publicado: employment="))
    disputed = corroborated + [page(case, "Directorio sintético corregido.", path="/equipo-2026",
                                    contradiction_ids=[employment.id])]
    assert status(case, merged, disputed).reason == "contradicted_source"
    assert employment_confirmation_titles(merged, case.company, disputed, case.limits, NOW) == []


# Confirmación persistida desde el pipeline: una sola transacción, sin proveedores ni envíos.

CONFIRMED_AT = NOW + timedelta(hours=1)


@pytest.fixture
def saved(tmp_path, make_campaign, make_company, make_assessment, monkeypatch):
    campaign = make_campaign(status="completed")
    company, sources = make_company(domain="example.com", entity_name="Empresa sintética", segments=["fintech_software"],
                                    identity_status="confirmed")
    assessment = make_assessment(campaign.id, company.id, priority="high", target_roles=[TITLE])
    case = SimpleNamespace(campaign=campaign, company=company, assessment=assessment, limits=campaign.limits)
    contact, facts = apollo_person(case)
    contact = verified(contact)
    run = RunItem(campaign_id=campaign.id, company_id=company.id, stage="completed", last_assessment_id=assessment.id,
                  business_status="qualified_no_contact", stop_reason="contact_plan_exhausted",
                  review_status="pending")
    for module in ("prospecting.pipeline.contacts", "prospecting.pipeline.campaign"):
        monkeypatch.setattr(f"{module}.utc_now", lambda: CONFIRMED_AT)
    path = tmp_path / "employment-synthetic.sqlite3"
    with Database(path) as db:
        with db.transaction():
            db.save_campaign(campaign)
            db.save_company(company, evidence=sources)
            db.save_run_item(run.model_copy(update={"last_assessment_id": None}))
            db.save_assessment(assessment)
            db.save_run_item(run)
            db.save_contact(contact, evidence=facts)
        yield SimpleNamespace(db=db, path=path, case=case, campaign=campaign, company=company, contact=contact,
                              run=db.get_run_item(campaign.id, company.id))


def persist(saved, **overrides):
    fields = dict(title=TITLE, source_url=SOURCE_URL, reason=f"  {REASON}  ", confirmed=True)
    return confirm_current_employment(saved.db, saved.campaign.id, saved.contact.id, **(fields | overrides))


def unchanged(saved, evidence):
    assert saved.db.get_contact(saved.contact.id) == saved.contact
    by_id = lambda items: sorted(items, key=lambda item: str(item.id))
    assert by_id(saved.db.list_evidence(saved.company.id)) == by_id(evidence)
    assert saved.db.get_run_item(saved.campaign.id, saved.company.id) == saved.run


def test_confirmation_saves_manual_evidence_and_recalculates_readiness(saved, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Confirmar el empleo no crea clientes de proveedores ni hace tráfico.")

    monkeypatch.setattr("prospecting.providers.ProviderClient.__init__", forbidden)
    monkeypatch.setattr("prospecting.providers.ClaudeClient.__init__", forbidden)
    before = saved.db.list_evidence(saved.company.id)
    run = persist(saved)
    assert run.business_status == "ready_preferred"
    assert run.model_dump(exclude={"business_status", "updated_at"}) == saved.run.model_dump(
        exclude={"business_status", "updated_at"})
    contact = saved.db.get_contact(saved.contact.id)
    [fact] = [item for item in saved.db.list_evidence(saved.company.id) if item.id not in {old.id for old in before}]
    assert contact.model_dump(exclude={"employment_evidence_ids"}) == saved.contact.model_dump(
        exclude={"employment_evidence_ids"})
    assert contact.employment_evidence_ids == saved.contact.employment_evidence_ids + [fact.id]
    assert (fact.source_type, fact.kind, fact.provider, fact.contact_id) == (
        "manual", "observed", "manual_review", saved.contact.id)
    assert fact.external_reference == f"manual-employment:{saved.campaign.id}:{saved.contact.id}:{CONFIRMED_AT.isoformat()}"
    assert str(fact.url) == SOURCE_URL and fact.retrieved_at == CONFIRMED_AT
    assert fact.claim.endswith(f"Motivo: {REASON}") and NAME in fact.excerpt and TITLE in fact.excerpt
    assert [item for item in saved.db.list_evidence(saved.company.id) if item.id != fact.id] == before
    assert saved.db.list_usage(campaign_id=saved.campaign.id) == []
    view = bridge.read_campaign(saved.path, saved.campaign.id)
    [person] = view.companies[0].contacts
    assert person.eligible and person.employment_titles == [] and person.employment.basis == "manual"
    assert person.employment.confirmation_reason == REASON


@pytest.mark.parametrize("overrides, message", [
    ({"confirmed": False}, "explícitamente"), ({"confirmed": None}, "explícitamente"), ({"confirmed": "true"}, "explícitamente"),
    ({"reason": "   "}, "at least 1 character"), ({"source_url": "ftp://example.com/equipo"}, "URL http"),
    ({"source_url": "directorio corporativo"}, "URL http"), ({"source_url": "javascript:alert(1)"}, "URL http"),
    ({"title": "CEO"}, "ya citados"),
])
def test_confirmation_rejects_missing_acceptance_reason_url_or_uncited_title(saved, overrides, message):
    before = saved.db.list_evidence(saved.company.id)
    with pytest.raises(ValueError, match=message):
        persist(saved, **overrides)
    unchanged(saved, before)


def test_offered_titles_come_from_the_read_view(saved):
    view = bridge.read_campaign(saved.path, saved.campaign.id)
    [person] = view.companies[0].contacts
    assert person.employment_titles == [TITLE] and not person.eligible
    assert person.employment.state == "provider_claim"


def test_departure_excluded_company_or_foreign_campaign_cannot_confirm(saved, make_campaign):
    before = saved.db.list_evidence(saved.company.id)
    news = Evidence(company_id=saved.company.id, contact_id=saved.contact.id, url="https://example.com/noticias",
                    provider="tavily", external_reference=f"tavily-sintetico#{uuid4()}", claim="Noticia sintética.",
                    excerpt=f"{NAME} dejó la empresa en octubre.", retrieved_at=NOW, kind="observed",
                    source_type="secondary")
    with saved.db.transaction():
        saved.db.save_evidence(news)
    with pytest.raises(ValueError, match="salida"):
        persist(saved)
    unchanged(saved, before + [news])
    saved.db.save_run_item(saved.run.model_copy(update={"business_status": BusinessStatus.EXCLUDED}))
    with pytest.raises(ValueError, match="no excluida"):
        persist(saved)
    other = make_campaign()
    saved.db.save_campaign(other)
    with pytest.raises(ValueError, match="no pertenece"):
        confirm_current_employment(saved.db, other.id, saved.contact.id, title=TITLE, source_url=SOURCE_URL,
                                   reason=REASON, confirmed=True)


def test_historic_campaign_is_read_only(saved, make_campaign):
    legacy = make_campaign(config_snapshot=saved.campaign.config_snapshot.model_copy(update={"people_provider": None}))
    saved.db.save_campaign(legacy)
    saved.db.save_run_item(RunItem(campaign_id=legacy.id, company_id=saved.company.id))
    with pytest.raises(ValueError, match="histórica"):
        confirm_current_employment(saved.db, legacy.id, saved.contact.id, title=TITLE, source_url=SOURCE_URL,
                                   reason=REASON, confirmed=True)


def test_confirmation_rolls_back_contact_and_evidence_when_the_checkpoint_fails(saved, monkeypatch):
    before = saved.db.list_evidence(saved.company.id)

    def failed_checkpoint(run):
        assert len(saved.db.list_evidence(saved.company.id)) == len(before) + 1
        raise RuntimeError("Fallo sintético después de guardar contacto y evidencia.")

    monkeypatch.setattr(saved.db, "save_run_item", failed_checkpoint)
    with pytest.raises(RuntimeError, match="Fallo sintético"):
        persist(saved)
    monkeypatch.undo()
    unchanged(saved, before)


def test_running_campaign_blocks_the_confirmation(saved):
    before = saved.db.list_evidence(saved.company.id)
    with bridge._EXECUTION:
        with pytest.raises(ValueError, match="ejecutándose"):
            bridge.confirm_current_employment(saved.path, saved.campaign.id, saved.contact.id, title=TITLE,
                                              source_url=SOURCE_URL, reason=REASON, confirmed=True)
    unchanged(saved, before)
