"""Cuentas objetivo declaradas al preparar la campaña; empresas y dominios exclusivamente sintéticos, sin red."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from core.forms import parse_target_accounts
from prospecting.discovery import is_target_account
from prospecting.identity import ExclusionEntry, ExclusionList
from prospecting.models import CampaignFilters, IdentityStatus, RunStage, TargetAccount
from prospecting.pipeline.discovery import resolve_company_identity, run_discovery


def accounts(*domains, **fields):
    return CampaignFilters(target_accounts=[TargetAccount(domain=domain, **fields) for domain in domains])


def test_form_lines_accept_a_pasted_url_and_optional_name_and_country():
    parsed = parse_target_accounts(
        "https://www.consumo-sintetico.example/promociones?x=1, Consumo Sintético, mx\n\n"
        "pagos-sinteticos.example\n")
    assert [(item.domain, item.name, item.countries) for item in parsed] == [
        ("consumo-sintetico.example", "Consumo Sintético", ["MX"]), ("pagos-sinteticos.example", None, [])]
    with pytest.raises(ValueError, match="línea 2"):
        parse_target_accounts("valida.example\nno es un dominio")


def test_campaign_rejects_repeated_domains_foreign_countries_and_more_accounts_than_companies(make_campaign):
    with pytest.raises(ValidationError):
        accounts("repetida.example", "repetida.example")
    with pytest.raises(ValidationError):
        make_campaign(filters=accounts("ajena.example", countries=["MX"]))  # La campaña sintética es de CO.
    with pytest.raises(ValidationError):
        make_campaign(filters=accounts("uno.example", "dos.example"), max_companies=1)


def test_target_accounts_become_companies_without_any_provider_call(database, make_campaign):
    campaign = database.save_campaign(make_campaign(
        filters=accounts("consumo-sintetico.example", name="Consumo Sintético"), max_companies=1))
    # Sin presupuesto ni cliente: cualquier intento de llamar a un proveedor fallaría.
    report = run_discovery(database, None, None, campaign.id, account_ref="sin-uso", authorization=None)
    assert report.queries == [] and report.stop_reason is None and len(report.selected_company_ids) == 1
    company = database.get_company(report.selected_company_ids[0])
    assert (company.name, company.domain, company.identity_status) == (
        "Consumo Sintético", "consumo-sintetico.example", IdentityStatus.PENDING)
    declared = database.list_evidence(company.id)
    assert len(declared) == 1 and is_target_account(declared[0]) and database.list_usage() == []
    # Repetir el descubrimiento no duplica la empresa.
    assert run_discovery(database, None, None, campaign.id, account_ref="sin-uso",
                         authorization=None).stop_reason == "already_discovered"
    assert len(database.list_run_items(campaign.id)) == 1


def test_declared_account_confirms_identity_country_and_segment_without_reading_a_page(database, make_campaign):
    campaign = database.save_campaign(make_campaign(
        countries=["CO", "MX"], segments=["cpg_loyalty"],
        filters=accounts("consumo-sintetico.example", name="Consumo Sintético", countries=["MX"]), max_companies=1))
    company_id = run_discovery(database, None, None, campaign.id, account_ref="sin-uso",
                               authorization=None).selected_company_ids[0]
    decision = resolve_company_identity(database, campaign.id, company_id).decision
    assert decision.status == "confirmed" and decision.stop_reason is None
    company = database.get_company(company_id)
    assert company.identity_status == IdentityStatus.CONFIRMED
    assert company.operating_countries == ["MX"] and company.segments == ["cpg_loyalty"]
    declared = database.list_evidence(company_id)[0].id
    assert company.provenance["operating_countries"] == [declared] and company.provenance["segments"] == [declared]
    assert database.get_run_item(campaign.id, company_id).stage == RunStage.IDENTITY_RESOLVED


def test_same_domain_in_a_later_campaign_reuses_the_confirmed_company(database, make_campaign):
    first = database.save_campaign(make_campaign(filters=accounts("consumo-sintetico.example"), max_companies=1))
    company_id = run_discovery(database, None, None, first.id, account_ref="sin-uso",
                               authorization=None).selected_company_ids[0]
    resolve_company_identity(database, first.id, company_id)
    second = database.save_campaign(make_campaign(filters=accounts("consumo-sintetico.example"), max_companies=1))
    report = run_discovery(database, None, None, second.id, account_ref="sin-uso", authorization=None)
    assert report.selected_company_ids == [company_id] and report.reused_company_ids == [company_id]
    assert resolve_company_identity(database, second.id, company_id).decision.status == "confirmed"


def test_excluded_target_account_takes_no_place(database, make_campaign):
    exclusions = ExclusionList(
        version="exclusiones-sinteticas", validation_status="validated", source_reference="Lista sintética de pruebas.",
        observed_at=datetime(2026, 10, 11, tzinfo=UTC), entries=[ExclusionEntry(
            id="cliente-sintetico", name="Cliente Sintético", domains=["cliente-sintetico.example"],
            scope="entity", reason="current_customer", source_reference="Lista sintética de pruebas.")])
    campaign = database.save_campaign(make_campaign(
        filters=accounts("cliente-sintetico.example", "consumo-sintetico.example"), max_companies=2))
    report = run_discovery(database, None, None, campaign.id, account_ref="sin-uso", authorization=None,
                           exclusions=exclusions)
    assert [item.host for item in report.excluded] == ["cliente-sintetico.example"]
    assert report.discarded == {"excluded_account": 1} and len(report.selected_company_ids) == 1
    assert database.get_company(report.selected_company_ids[0]).domain == "consumo-sintetico.example"
