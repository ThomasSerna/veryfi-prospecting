"""Consultas, lectura y selección de Tavily con respuestas exclusivamente sintéticas."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from prospecting.discovery import (
    NON_BUSINESS_DOMAINS, TEMPLATE_VERSION, PlannedQuery, TavilyExtractResponse,
    TavilySearchResponse, build_company, build_search_queries, classify_tavily_error,
    extract_credits, extract_request, group_candidates, infer_name, parse_extract,
    parse_search, search_request, select_candidates, validate_public_url,
)
from prospecting.models import CampaignLimits
from prospecting.providers import ProviderError


RETRIEVED_AT = datetime(2026, 10, 11, 12, tzinfo=UTC)


def limits(config, **discovery):
    values = config.defaults.model_dump(include=set(CampaignLimits.model_fields))
    values["discovery"].update(discovery)
    return values


def planned(country="CO", segment="fintech_software", profile="expense_reimbursement"):
    return PlannedQuery(
        country=country, segment=segment, profile_id=profile,
        template_version=TEMPLATE_VERSION, query=f"consulta sintética {country}",
    )


def search_response(*results, request_id="solicitud-sintetica"):
    return TavilySearchResponse.model_validate({
        "query": "consulta sintética", "answer": None, "images": [], "response_time": 0.1,
        "results": [
            {"url": url, "title": title, "content": "Resumen exclusivamente sintético.", "score": 0.5}
            for url, title in results
        ],
        "usage": {"credits": 1}, "request_id": request_id,
    })


def hits_for(query, index, *results):
    hits, _ = parse_search(query, index, search_response(*results), uuid4(), RETRIEVED_AT)
    return hits


def test_queries_cover_only_campaign_countries_and_segments(make_campaign):
    both = build_search_queries(make_campaign(countries=["CO", "MX"], segments=["fintech_software", "cpg_loyalty"]))
    assert len(both) == 8
    assert {(item.country, item.segment) for item in both} == {
        ("CO", "fintech_software"), ("CO", "cpg_loyalty"), ("MX", "fintech_software"), ("MX", "cpg_loyalty"),
    }
    assert len({item.query for item in both}) == 8
    single = build_search_queries(make_campaign(countries=["MX"], segments=["cpg_loyalty"]))
    assert {(item.country, item.segment) for item in single} == {("MX", "cpg_loyalty")}
    assert all("México" in item.query and item.template_version == TEMPLATE_VERSION for item in single)


def test_reduced_query_limit_truncates_round_robin(make_campaign, config):
    campaign = make_campaign(
        countries=["CO", "MX"], segments=["fintech_software", "cpg_loyalty"],
        limits=limits(config, web_queries=4),
    )
    queries = build_search_queries(campaign)
    assert len(queries) == 4
    assert {(item.country, item.segment) for item in queries} == {
        ("CO", "fintech_software"), ("CO", "cpg_loyalty"), ("MX", "fintech_software"), ("MX", "cpg_loyalty"),
    }
    one = make_campaign(limits=limits(config, web_queries=1))
    assert len(build_search_queries(one)) == 1


def test_keywords_are_appended_to_queries(make_campaign):
    campaign = make_campaign(filters={"keywords": ["tarjetas corporativas"]})
    assert all(item.query.endswith("tarjetas corporativas") for item in build_search_queries(campaign))


def test_search_payload_uses_country_basic_depth_and_exclusions(make_campaign):
    campaign = make_campaign(countries=["MX"])
    query = build_search_queries(campaign)[0]
    request = search_request(query, "cuenta-sintetica", campaign.limits.discovery)
    assert request.provider == "tavily" and request.operation == "search"
    assert request.payload["country"] == "mexico"
    assert request.payload["topic"] == "general"
    assert request.payload["search_depth"] == "basic"
    assert request.payload["max_results"] == 10
    assert request.payload["include_usage"] is True
    assert request.payload["include_raw_content"] is False
    assert "linkedin.com" in request.payload["exclude_domains"]
    assert len(request.payload["exclude_domains"]) <= 150


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/precios", "http://10.0.0.8/", "http://[::1]/", "http://169.254.169.254/latest",
    "https://8.8.8.8/", "http://localhost/admin", "https://impresora.local/", "https://intranet/",
    "file:///etc/passwd", "ftp://empresa-uno.example/", "javascript:alert(1)",
    "https://usuario:clave@empresa-uno.example/", "https://empresa-uno.example:8080/",
    "https://empresa uno.example/", "https://servicio.internal/", "", None, 42,
])
def test_unsafe_urls_are_rejected(url):
    assert validate_public_url(url) is None


@pytest.mark.parametrize("url", [
    "https://empresa-uno.example/producto", "http://www.empresa-dos.example", "https://app.empresa.example:443/a?b=c",
])
def test_public_urls_are_accepted(url):
    assert validate_public_url(url) == url


def test_parse_discards_unsafe_and_non_business_results():
    hits, discarded = parse_search(planned(), 0, search_response(
        ("https://www.empresa-uno.example/gastos", "Gastos | Empresa Uno"),
        ("https://www.linkedin.com/company/sintetica", "Perfil sintético"),
        ("https://es.wikipedia.org/wiki/Sintetico", "Artículo sintético"),
        ("http://10.0.0.8/interno", "Interno"),
        ("https://empresa-dos.example/", "Empresa Dos"),
    ), uuid4(), RETRIEVED_AT)
    assert [hit.host for hit in hits] == ["empresa-uno.example", "empresa-dos.example"]
    assert [hit.rank for hit in hits] == [1, 5]
    assert discarded == {"non_business_domain": 2, "unsafe_url": 1}
    assert all(not hit.host.endswith(tuple(NON_BUSINESS_DOMAINS)) for hit in hits)


def test_same_host_groups_but_subdomains_stay_separate():
    hits = hits_for(
        planned(), 0,
        ("https://www.empresa.example/a", "A | Empresa"),
        ("https://empresa.example/b", "B | Empresa"),
        ("https://promo.empresa.example/", "Promoción | Empresa"),
    )
    candidates, dropped = group_candidates(hits, 60)
    assert dropped == 0
    assert {item.host: len(item.hits) for item in candidates} == {"empresa.example": 2, "promo.empresa.example": 1}


def test_raw_limit_interleaves_queries_by_rank():
    first = hits_for(planned("CO"), 0, *[(f"https://co{index}.example/", "CO") for index in range(10)])
    second = hits_for(planned("MX"), 1, *[(f"https://mx{index}.example/", "MX") for index in range(10)])
    candidates, dropped = group_candidates(first + second, 6)
    assert dropped == 14
    assert [item.host for item in candidates] == [
        "co0.example", "mx0.example", "co1.example", "mx1.example", "co2.example", "mx2.example",
    ]


def test_selection_balances_combinations_and_reports_shortfalls(make_campaign):
    campaign = make_campaign(countries=["CO", "MX"], max_companies=8)
    co = hits_for(planned("CO"), 0, *[(f"https://co{index}.example/", "CO") for index in range(9)])
    mx = hits_for(planned("MX"), 1, ("https://mx0.example/", "MX"), ("https://mx1.example/", "MX"))
    candidates, _ = group_candidates(co + mx, 60)
    selected, report = select_candidates(candidates, campaign)
    assert len(selected) == 8
    assert sum(item.hits[0].query.country == "MX" for item in selected) == 2
    by_country = {item.country: item for item in report}
    assert by_country["MX"].insufficient is True and by_country["MX"].selected == 2
    assert by_country["CO"].insufficient is False and by_country["CO"].selected == 6


def test_selection_never_exceeds_max_companies_or_invents_rows(make_campaign):
    campaign = make_campaign(max_companies=3)
    candidates, _ = group_candidates(hits_for(planned(), 0, ("https://uno.example/", "Uno")), 60)
    selected, report = select_candidates(candidates, campaign)
    assert len(selected) == 1
    assert report[0].insufficient is True
    many, _ = group_candidates(hits_for(planned(), 0, *[(f"https://e{i}.example/", "E") for i in range(10)]), 60)
    assert len(select_candidates(many, campaign)[0]) == 3


def test_name_is_inferred_from_title_or_domain():
    assert infer_name("Gestión de gastos | Empresa Uno", "empresa-uno.example") == "Empresa Uno"
    assert infer_name("Promoción verano - Marca Sintética", "promo.marcasintetica.com.co") == "Marca Sintética"
    assert infer_name("Página sin nombre", "app.gastos-sinteticos.com.mx") == "Gastos Sinteticos"
    assert infer_name(None, "empresa.example") == "Empresa"


def test_company_keeps_provenance_and_unknown_country_segment(database, make_campaign):
    query = planned()
    hits = hits_for(query, 0, ("https://www.empresa-uno.example/gastos", "Gastos | Empresa Uno"))
    candidate = group_candidates(hits, 60)[0][0]
    company, evidence = build_company(candidate)
    assert company.domain == "empresa-uno.example"
    assert company.name == "Empresa Uno"
    assert company.identity_status == "pending"
    assert company.operating_countries is None and company.segments is None
    name_fact = next(item for item in evidence if item.id in company.provenance["name"])
    assert name_fact.kind == "inference"
    hit_fact = next(item for item in evidence if item.id in company.provenance["domain"])
    assert hit_fact.kind == "observed" and hit_fact.source_type == "secondary"
    assert hit_fact.provider == "tavily" and hit_fact.external_reference == "solicitud-sintetica#1"
    assert str(hit_fact.url) == "https://www.empresa-uno.example/gastos"
    assert hit_fact.retrieved_at == RETRIEVED_AT
    assert query.query in hit_fact.claim and "CO" in hit_fact.claim
    database.save_company(company, evidence=evidence)
    assert {item.id for item in database.list_evidence(company.id)} == {item.id for item in evidence}


def test_extract_request_is_bounded_and_counts_credits():
    request = extract_request(["https://empresa.example/"], "recibos", "cuenta-sintetica")
    assert request.operation == "extract"
    assert request.payload["extract_depth"] == "basic"
    assert request.payload["chunks_per_source"] == 3
    assert request.payload["timeout"] < 10
    assert [extract_credits(count) for count in (1, 5, 6, 10)] == [1, 1, 2, 2]


def test_parse_extract_marks_primary_and_ignores_failures_and_unrequested(make_company):
    company, _ = make_company(domain="empresa.example")
    requested = ["https://www.empresa.example/producto", "https://prensa.example/nota", "https://empresa.example/caida"]
    response = TavilyExtractResponse.model_validate({
        "results": [
            {"url": requested[0], "raw_content": "Sube tus recibos sintéticos. [...] " + "x" * 2000},
            {"url": requested[1], "raw_content": "Nota sintética sobre la empresa."},
            {"url": "https://no-solicitada.example/", "raw_content": "No pedida."},
        ],
        "failed_results": [{"url": requested[2], "error": "Fallo sintético"}],
        "usage": {"credits": 1}, "request_id": "extraccion-sintetica",
    })
    evidence, failures = parse_extract(company, requested, response, uuid4(), RETRIEVED_AT)
    by_url = {}
    for item in evidence:
        by_url.setdefault(str(item.url), []).append(item)
    assert set(by_url) == set(requested[:2])
    assert {item.source_type for item in by_url[requested[0]]} == {"primary"}
    assert {item.source_type for item in by_url[requested[1]]} == {"secondary"}
    assert all(len(item.excerpt) <= 800 and item.kind == "observed" for item in evidence)
    assert failures == [(requested[2], "Fallo sintético")]


@pytest.mark.parametrize(("kind", "status", "reason"), [
    ("http", 401, "permission_denied"), ("http", 432, "quota_exceeded"), ("http", 433, "quota_exceeded"),
    ("http", 429, "rate_limited"), ("http", 400, "invalid_input"), ("http", 422, "invalid_input"),
    ("http", 500, "provider_error"), ("timeout", None, "timeout"), ("json", None, "invalid_response"),
    ("schema", None, "invalid_response"), ("local", None, "local_error"),
])
def test_tavily_errors_have_specific_reasons(kind, status, reason):
    assert classify_tavily_error(ProviderError(kind, "Fallo sintético", http_status=status)) == reason
