"""Confirmación manual local con personas, canales y evidencia exclusivamente sintéticos."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from prospecting.contacts import channel_is_usable, derive_readiness
from prospecting.db import Database
from prospecting.identity import ExclusionList
from prospecting.models import Channel, ChannelStatus, ChannelType, Contact, Evidence, IdentityStatus, RunItem, utc_now
from prospecting.pipeline.contacts import confirm_alternative_channel


@pytest.fixture
def manual_case(tmp_path, make_campaign, make_company, make_assessment):
    now = utc_now()
    campaign = make_campaign(status="completed")
    company, sources = make_company(domain="example.com", entity_name="Empresa sintética",
                                    segments=["fintech_software"], identity_status="confirmed")
    assessment = make_assessment(campaign.id, company.id, priority="high", target_roles=["CTO"])
    contact_id = uuid4()
    source = Evidence(company_id=company.id, contact_id=contact_id, kind="observed", source_type="primary",
                      provider="anthropic", external_reference=f"apollo_public_v1:synthetic:{contact_id}",
                      url="https://example.com/team", retrieved_at=now,
                      claim="Directorio profesional sintético actual.",
                      excerpt="Persona Sintética Uno, CTO de Empresa sintética. Perfil nominal de mensajería.")
    channel = Channel(contact_id=contact_id, type="linkedin", value="https://www.linkedin.com/in/synthetic-person",
                      evidence_ids=[source.id], retrieved_at=now, direct=False,
                      provider_status="profile_found", warnings=["Acceso a mensajería sintético pendiente."])
    invalid = Channel(contact_id=contact_id, type="email", value="persona-sintetica@example.com",
                      evidence_ids=[source.id], retrieved_at=now, normalized_status="invalid",
                      provider_status="invalid", professional=True, direct=True,
                      warnings=["Verificación negativa sintética pendiente."])
    contact = Contact(id=contact_id, company_id=company.id, name="Persona Sintética Uno", title="CTO",
                      name_complete=True, current_employment=True, relevant_function=True, identity_status="confirmed",
                      employment_evidence_ids=[source.id],
                      provenance={field: [source.id] for field in ("name", "title", "relevant_function")},
                      channels=[channel, invalid])
    run = RunItem(campaign_id=campaign.id, company_id=company.id, stage="completed",
                  business_status="needs_channel_confirmation", last_assessment_id=assessment.id,
                  attempts={"contacts:person:" + str(contact.id): 1}, consumed_limits={"active_seconds": 2.0},
                  review_status="accepted", review_reason="Aceptación sintética con canal pendiente.", reviewed_at=now,
                  stop_reason="contact_plan_exhausted", error_message="Fallo sintético conservado.", error_stage="contacts_checked")
    path = tmp_path / "manual-synthetic.sqlite3"
    with Database(path) as db:
        with db.transaction():
            db.save_campaign(campaign)
            db.save_company(company, evidence=sources)
            db.save_run_item(run.model_copy(update={"last_assessment_id": None}))
            db.save_assessment(assessment)
            db.save_run_item(run)
            db.save_contact(contact, evidence=[source])
        yield SimpleNamespace(db=db, path=path, campaign=campaign, company=company, assessment=assessment,
                              contact=contact, source=source, channel=channel, run=run)


def confirm(case, **overrides):
    fields = dict(channel_type=case.channel.type, channel_value=case.channel.value,
                  reason="  Acceso nominal profesional comprobado manualmente, sin envío.  ", confirmed=True)
    return confirm_alternative_channel(case.db, case.campaign.id, case.contact.id, **(fields | overrides))


@pytest.mark.parametrize("channel_type", ["linkedin", "other"])
def test_confirmation_is_observed_persisted_and_preserves_original_fields(manual_case, channel_type, monkeypatch):
    case = manual_case
    channel = case.channel.model_copy(update={"type": ChannelType(channel_type)})
    previous = case.contact.model_copy(update={"channels": [channel, case.contact.channels[1]]})
    case.db.save_contact(previous)
    for variable in ("TAVILY_API_KEY", "APOLLO_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(variable, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Confirmar manualmente no crea clientes ni hace tráfico.")

    monkeypatch.setattr("prospecting.providers.ProviderClient.__init__", forbidden)
    monkeypatch.setattr("prospecting.providers.ClaudeClient.__init__", forbidden)
    before = utc_now()
    saved_run = confirm(case, channel_type=channel_type)
    after = utc_now()
    saved = case.db.get_contact(previous.id)
    updated = saved.channels[0]
    new_ids = set(updated.evidence_ids) - set(channel.evidence_ids)
    manual = next(fact for fact in case.db.list_evidence(case.company.id) if fact.id in new_ids)
    assert saved_run.business_status == "ready_alternative"
    assert saved_run.model_dump(exclude={"business_status", "updated_at"}) == case.run.model_dump(exclude={"business_status", "updated_at"})
    assert saved.model_dump(exclude={"channels"}) == previous.model_dump(exclude={"channels"})
    assert saved.channels[1] == previous.channels[1]
    assert updated.provider_status == channel.provider_status and updated.warnings == channel.warnings
    assert updated.retrieved_at == channel.retrieved_at and updated.normalized_status == "manual_confirmed"
    assert set(channel.evidence_ids) <= set(updated.evidence_ids) and len(new_ids) == 1
    assert updated.professional is True and updated.direct is True
    assert before <= updated.manual_confirmed_at <= after
    assert manual.retrieved_at == updated.manual_confirmed_at and manual.source_type == "manual"
    assert manual.kind == "observed" and manual.provider == "manual_review"
    assert str(case.campaign.id) in manual.external_reference and str(case.contact.id) in manual.external_reference
    assert updated.manual_confirmation_reason == "Acceso nominal profesional comprobado manualmente, sin envío."
    assert updated.manual_confirmation_reason in manual.excerpt and case.contact.name in manual.claim
    assert channel.value in manual.claim and manual.contact_id == case.contact.id
    assert case.db.get_assessment(case.assessment.id) == case.assessment
    assert case.db.list_usage(campaign_id=case.campaign.id) == []
    with Database(case.path) as reopened:
        assert reopened.get_contact(case.contact.id) == saved
        assert reopened.get_run_item(case.campaign.id, case.company.id) == saved_run


@pytest.mark.parametrize("confirmed", [False, None, 1, "true"])
def test_confirmation_needs_explicit_boolean_true(manual_case, confirmed):
    with pytest.raises(ValueError, match="explícita"):
        confirm(manual_case, confirmed=confirmed)
    assert manual_case.db.get_contact(manual_case.contact.id) == manual_case.contact


@pytest.mark.parametrize("reason", ["", " \t\n ", None, 7])
def test_confirmation_needs_nonempty_text_reason(manual_case, reason):
    with pytest.raises(ValueError):
        confirm(manual_case, reason=reason)
    assert manual_case.db.get_contact(manual_case.contact.id) == manual_case.contact


@pytest.mark.parametrize("channel_type", ["email", "phone", "whatsapp", "unsupported"])
def test_confirmation_rejects_unknown_types_or_channels_not_owned_by_person(manual_case, channel_type):
    with pytest.raises(ValueError):
        confirm(manual_case, channel_type=channel_type)
    assert manual_case.db.get_contact(manual_case.contact.id) == manual_case.contact


def test_confirmation_requires_existing_channel_and_campaign_membership(manual_case, make_campaign):
    case = manual_case
    with pytest.raises(ValueError, match="existir"):
        confirm(case, channel_value="https://www.linkedin.com/in/another-synthetic-person")
    other = make_campaign()
    case.db.save_campaign(other)
    for campaign_id, contact_id in ((other.id, case.contact.id), (uuid4(), case.contact.id), (case.campaign.id, uuid4())):
        with pytest.raises(ValueError, match="no pertenece"):
            confirm_alternative_channel(case.db, campaign_id, contact_id, case.channel.type,
                                        case.channel.value, reason="Comprobación sintética.", confirmed=True)
    assert case.db.get_contact(case.contact.id) == case.contact


def test_invalid_alternative_channel_cannot_lose_negative_state(manual_case):
    case = manual_case
    invalid = case.channel.model_copy(update={"normalized_status": ChannelStatus.INVALID, "provider_status": "invalid"})
    saved = case.db.save_contact(case.contact.model_copy(update={"channels": [invalid, case.contact.channels[1]]}))
    with pytest.raises(ValueError, match="negativa"):
        confirm(case)
    assert case.db.get_contact(case.contact.id) == saved


@pytest.mark.parametrize("changes", [
    {"identity_status": IdentityStatus.PENDING}, {"identity_status": IdentityStatus.CONTRADICTED},
    {"identity_status": IdentityStatus.PENDING, "name_complete": False},
    {"current_employment": False}, {"current_employment": None}, {"relevant_function": False},
    {"title": "Marketing Director"},
])
def test_manual_access_cannot_replace_professional_identity_or_employment(manual_case, changes):
    case = manual_case
    saved = case.db.save_contact(case.contact.model_copy(update=changes))
    result = confirm(case)
    updated = case.db.get_contact(case.contact.id)
    assert updated.model_dump(exclude={"channels"}) == saved.model_dump(exclude={"channels"})
    assert updated.channels[0].manual_confirmed_at is not None
    assert result.business_status not in ("ready_alternative", "ready_preferred")


@pytest.mark.parametrize("age", ["stale", "future"])
def test_stale_or_future_employment_does_not_block_channel_notes(manual_case, age):
    case = manual_case
    days = -(case.campaign.limits.freshness.employment_days + 1) if age == "stale" else 1
    source = case.source.model_copy(update={"id": uuid4(), "published_at": utc_now() + timedelta(days=days)})
    saved = case.db.save_contact(case.contact.model_copy(update={"employment_evidence_ids": [source.id]}), evidence=[source])
    result = confirm(case)
    updated = case.db.get_contact(case.contact.id)
    assert updated.employment_evidence_ids == saved.employment_evidence_ids
    assert updated.channels[0].manual_confirmed_at is not None
    assert result.business_status not in ("ready_alternative", "ready_preferred")


@pytest.mark.parametrize("contradictory", [False, True])
def test_channel_sources_with_future_date_or_contradiction_block_confirmation(manual_case, contradictory):
    case = manual_case
    changes = {"contradiction_ids": [case.source.id]} if contradictory else {"retrieved_at": utc_now() + timedelta(days=1)}
    source = case.source.model_copy(update={"id": uuid4()} | changes)
    channel = case.channel.model_copy(update={"evidence_ids": [source.id]})
    saved = case.db.save_contact(case.contact.model_copy(update={"channels": [channel, case.contact.channels[1]]}), evidence=[source])
    before = case.db.list_evidence(case.company.id)
    with pytest.raises(ValueError, match="contradictoria"):
        confirm(case)
    assert case.db.get_contact(case.contact.id) == saved and case.db.list_evidence(case.company.id) == before


def test_confirmation_rolls_back_contact_and_evidence_when_checkpoint_fails(manual_case, monkeypatch):
    case = manual_case
    before = case.db.list_evidence(case.company.id)

    def failed_checkpoint(run):
        assert case.db.get_contact(case.contact.id).channels[0].manual_confirmed_at is not None
        assert len(case.db.list_evidence(case.company.id)) == len(before) + 1
        raise RuntimeError("Fallo sintético después de guardar contacto y evidencia.")

    monkeypatch.setattr(case.db, "save_run_item", failed_checkpoint)
    with pytest.raises(RuntimeError, match="Fallo sintético"):
        confirm(case)
    assert case.db.get_contact(case.contact.id) == case.contact
    assert case.db.list_evidence(case.company.id) == before
    assert case.db.get_run_item(case.campaign.id, case.company.id) == case.run


def test_confirmation_expires_without_refreshing_employment(manual_case):
    case = manual_case
    confirm(case)
    contact = case.db.get_contact(case.contact.id)
    evidence = case.db.list_evidence(case.company.id)
    expired = contact.channels[0].manual_confirmed_at + timedelta(days=case.campaign.limits.cache.contact_days + 1)
    assert not channel_is_usable(contact.channels[0], contact, evidence, case.campaign.limits, expired, case.company)
    assert derive_readiness(case.assessment, [contact], evidence, case.campaign.limits, expired, case.company) != "ready_alternative"


def test_other_ready_contact_keeps_preferred_status(manual_case):
    case = manual_case
    provider = case.source.model_copy(update={
        "id": uuid4(), "excerpt": f"{case.contact.name}, CTO de {case.company.name}, correo profesional preferred-synthetic@example.com."})
    preferred = Channel(contact_id=case.contact.id, type="email", value="preferred-synthetic@example.com",
                        evidence_ids=[provider.id], published_evidence_ids=[provider.id], retrieved_at=provider.retrieved_at,
                        professional=True, direct=True, normalized_status="published_professional")
    case.db.save_contact(case.contact.model_copy(update={"channels": case.contact.channels + [preferred]}), evidence=[provider])
    assert confirm(case).business_status == "ready_preferred"


def test_campaign_without_assessment_saves_notes_without_changing_status(manual_case, make_campaign):
    case = manual_case
    other_campaign = make_campaign()
    case.db.save_campaign(other_campaign)
    previous = case.db.save_run_item(RunItem(campaign_id=other_campaign.id, company_id=case.company.id))
    result = confirm_alternative_channel(case.db, other_campaign.id, case.contact.id, case.channel.type,
                                         case.channel.value, reason="Confirmación sintética.", confirmed=True)
    assert result.business_status == previous.business_status
    assert case.db.get_contact(case.contact.id).channels[0].manual_confirmed_at is not None
    assert case.db.get_run_item(case.campaign.id, case.company.id) == case.run


@pytest.mark.parametrize("channel_type,value,extra", [
    ("email", "comprobacion-sintetica@example.com", {"normalized_status": "verified", "verified_at": utc_now()}),
    ("phone", "+573001234567", {"phone_country": "CO"}),
    ("whatsapp", "+573001234567", {}),
])
def test_preferred_confirmation_preserves_provider_status_and_verification_dates(manual_case, channel_type, value, extra):
    case = manual_case
    provider = case.source.model_copy(update={
        "id": uuid4(), "source_type": "provider", "provider": "apollo",
        "external_reference": "apollo_v1:comprobacion-sintetica#enrichment",
        "claim": f"Canal profesional sintético de {case.contact.name}: {value}.",
    })
    channel = Channel(contact_id=case.contact.id, type=channel_type, value=value,
                      evidence_ids=[provider.id], retrieved_at=provider.retrieved_at,
                      provider_status="Estado sintético del proveedor", professional=True, direct=True, **extra)
    previous = case.db.save_contact(case.contact.model_copy(update={"channels": [channel, case.contact.channels[1]]}),
                                    evidence=[provider])
    usable = channel_is_usable(channel, previous, case.db.list_evidence(case.company.id),
                               case.campaign.limits, utc_now(), case.company)
    confirm(case, channel_type=channel_type, channel_value=value)
    updated = case.db.get_contact(case.contact.id).channels[0]
    assert updated.normalized_status == channel.normalized_status
    assert updated.provider_status == channel.provider_status
    assert updated.retrieved_at == channel.retrieved_at and updated.verified_at == channel.verified_at
    assert updated.professional == channel.professional and updated.direct == channel.direct
    assert updated.manual_confirmed_at is not None and updated.manual_confirmation_reason
    assert channel_is_usable(updated, case.db.get_contact(case.contact.id), case.db.list_evidence(case.company.id),
                              case.campaign.limits, utc_now(), case.company) == usable
    assert case.db.list_usage(campaign_id=case.campaign.id) == []


def test_confirmation_does_not_erase_negative_email_verification(manual_case):
    case = manual_case
    invalid = case.contact.channels[1]
    before = case.db.list_evidence(case.company.id)
    with pytest.raises(ValueError, match="negativa"):
        confirm(case, channel_type=invalid.type, channel_value=invalid.value)
    assert case.db.get_contact(case.contact.id) == case.contact
    assert case.db.list_evidence(case.company.id) == before


def test_phone_notes_do_not_refresh_expired_provider_evidence(manual_case):
    case = manual_case
    old = utc_now() - timedelta(days=case.campaign.limits.cache.contact_days + 1)
    value = "+573001234567"
    provider = case.source.model_copy(update={
        "id": uuid4(), "source_type": "provider", "provider": "apollo", "retrieved_at": old,
        "external_reference": "apollo_v1:telefono-sintetico#enrichment",
        "claim": f"Teléfono profesional sintético de {case.contact.name}: {value}.",
    })
    phone = Channel(contact_id=case.contact.id, type="phone", value=value, phone_country="CO",
                    evidence_ids=[provider.id], retrieved_at=old, professional=True, direct=True)
    case.db.save_contact(case.contact.model_copy(update={"channels": [phone, case.contact.channels[1]]}),
                         evidence=[provider])
    result = confirm(case, channel_type=phone.type, channel_value=phone.value,
                     reason=f"Comprobación sintética de {case.contact.name}, teléfono {value}.")
    updated_contact = case.db.get_contact(case.contact.id)
    updated = updated_contact.channels[0]
    assert updated.manual_confirmed_at is not None
    assert set(phone.evidence_ids) < set(updated.evidence_ids) and updated.retrieved_at == old
    assert not channel_is_usable(updated, updated_contact, case.db.list_evidence(case.company.id),
                                  case.campaign.limits, utc_now(), case.company)
    assert result.business_status == "needs_channel_confirmation"


def test_later_evidence_contradicting_channel_blocks_confirmation(manual_case):
    case = manual_case
    contradicting = case.source.model_copy(update={"id": uuid4(), "contradiction_ids": [case.source.id]})
    case.db.save_evidence(contradicting)
    with pytest.raises(ValueError, match="contradictoria"):
        confirm(case)
    assert case.db.get_contact(case.contact.id) == case.contact


@pytest.mark.parametrize("confirmed_domain", [True, False])
def test_public_confirmation_rechecks_dynamic_exclusions_without_writes(manual_case, tmp_path, confirmed_domain):
    from prospecting.pipeline import confirm_alternative_channel as public_confirm

    case = manual_case
    exclusions = ExclusionList.model_validate({
        "version": "exclusiones-sinteticas-v1", "validation_status": "validated",
        "source_reference": "Lista sintética posterior a la investigación", "observed_at": utc_now(),
        "entries": [{"id": "entrada-sintetica", "name": case.company.name,
                     "domains": [case.company.domain if confirmed_domain else "otra-empresa.example"],
                     "scope": "entity", "reason": "current_customer", "source_reference": "Exclusión sintética"}],
    })
    path = tmp_path / "exclusiones-sinteticas.json"
    path.write_text(exclusions.model_dump_json(), encoding="utf-8")
    before = case.db.list_evidence(case.company.id)
    with pytest.raises(ValueError, match="exclusión"):
        public_confirm(case.path, case.campaign.id, case.contact.id, case.channel.type, case.channel.value,
                       reason="Comprobación sintética.", confirmed=True, exclusions_path=path)
    assert case.db.get_contact(case.contact.id) == case.contact
    assert case.db.get_run_item(case.campaign.id, case.company.id) == case.run
    assert case.db.list_evidence(case.company.id) == before
