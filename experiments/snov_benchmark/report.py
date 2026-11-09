"""Métricas experimentales reproducibles; ninguna consulta ni categoría productiva de listo."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlsplit

from prospecting.contacts import complete_name, fold_words, mentions, professional_email
from prospecting.sources import within_domain

from .contracts import BenchmarkCapture, BenchmarkManifest, manifest_digest


def _name(person):
    return " ".join(value.strip() for value in (person.first_name, person.last_name) if value and value.strip())


def _fresh(value, days, observed_at):
    return value is not None and observed_at - timedelta(days=days) <= value <= observed_at


def _role_matches(title, aliases):
    if not title:
        return False
    observed = " ".join(re.sub(r"\b(?:regional|global)\b", "", fold_words(title)).split())
    scope = r"(?:latam|latin america|latinoamerica|colombia|mexico|worldwide|and|y|de|para|for|in|en|co|mx)"
    return any(re.fullmatch(re.escape(fold_words(alias)) + r"(?:\s+" + scope + r")*", observed)
               for alias in aliases)


def _employment(person, company, days, observed_at):
    name = _name(person)
    if not complete_name(name) or "*" in name:
        return False, "incomplete_name"
    if person.domain != company.domain:
        return False, "entity_mismatch"
    nominal = [fact for fact in company.evidence if fold_words(fact.full_name) == fold_words(name)
               and fact.domain == company.domain and fact.observed_at <= observed_at
               and within_domain(urlsplit(str(fact.source_url)).hostname or "", company.domain)
               and mentions(fact.excerpt, name)]
    if any(fact.status == "ended" for fact in nominal):
        return False, "employment_ended"
    same_role = [fact for fact in nominal if person.title and
                 _role_matches(person.title, [fact.title]) and _role_matches(fact.title, [person.title])
                 and mentions(fact.excerpt, fact.title)]
    if any(fact.status == "ambiguous" for fact in same_role):
        return False, "ambiguous_source"
    if any(fact.status == "current" and fact.published_at is not None
           and fact.published_at <= fact.observed_at
           and _fresh(fact.published_at, days, observed_at) for fact in same_role):
        return True, "corporate_evidence"
    return False, "dated_corporate_evidence_required"


def _distinct(candidates):
    groups, by_key = [], {}
    for person in candidates:
        name = _name(person)
        keys = [("id", person.id)]
        if complete_name(name) and "*" not in name:
            keys.append(("name", person.domain, fold_words(name)))
        if person.email:
            keys.append(("email", person.email.casefold()))
        matched = {by_key[key] for key in keys if key in by_key}
        index = min(matched) if matched else len(groups)
        if not matched:
            groups.append([])
        for other in matched - {index}:
            groups[index].extend(groups[other])
            groups[other] = []
            by_key = {key: index if value == other else value for key, value in by_key.items()}
        groups[index].append(person)
        by_key.update({key: index for key in keys})
    return [group for group in groups if group]


def _sum_known(rows, field):
    try:
        values = [Decimal(str(row[field])) for row in rows if row.get(field) is not None]
        if any(not value.is_finite() or value < 0 for value in values):
            raise ValueError("El consumo y la latencia deben ser finitos y no negativos.")
        return None if len(values) != len(rows) else sum(values, Decimal("0"))
    except InvalidOperation as error:
        raise ValueError("El consumo y la latencia deben ser números decimales.") from error


def _ratio(numerator, denominator):
    return None if not denominator else numerator / denominator


def _money(value):
    return None if value is None else str(value)


def _company_metrics(manifest, company, capture):
    groups = _distinct(capture.candidates)
    counts = dict(found=len(groups), enriched=0, full_names=0, relevant=0, employment_evidenced=0,
                  professional_valid_email=0, usable_channel=0, useful_contacts=0, identity_conflicts=0)
    functions, persons = set(), []
    for group in groups:
        person = max(group, key=lambda row: (row.enriched, row.retrieved_at))
        names = {fold_words(_name(row)) for row in group if complete_name(_name(row)) and "*" not in _name(row)}
        domains = {row.domain for row in group if row.domain}
        emails = {row.email.casefold() for row in group if row.email}
        role_sets = {tuple(family for family, titles in company.role_families.items() if _role_matches(row.title, titles))
                     for row in group if row.title}
        conflict = len(names) > 1 or len(domains) > 1 or len(emails) > 1 or len(role_sets) > 1
        name = _name(person)
        complete = bool(person.first_name and person.last_name and complete_name(name) and "*" not in name)
        entity = person.domain == company.domain and not conflict
        matched = [family for family, titles in company.role_families.items() if _role_matches(person.title, titles)]
        relevant = bool(entity and matched)
        employment, employment_reason = _employment(person, company, manifest.contact_days, capture.observed_at)
        if conflict:
            employment, employment_reason = False, "identity_conflict"
        valid_email = bool(entity and person.email and person.email_status == "valid"
                           and re.fullmatch(r'[^@\s<>(),;:"]+@[^@\s]+\.[^@\s]+', person.email)
                           and professional_email(person.email, company.domain))
        usable = bool(complete and valid_email and
                      _fresh(person.email_verified_at, manifest.contact_days, capture.observed_at))
        useful = bool(person.enriched and complete and relevant and employment and usable)
        counts["enriched"] += person.enriched
        counts["full_names"] += complete
        counts["relevant"] += relevant
        counts["employment_evidenced"] += employment
        counts["professional_valid_email"] += valid_email
        counts["usable_channel"] += usable
        counts["useful_contacts"] += useful
        counts["identity_conflicts"] += conflict
        if relevant:
            functions.update(matched)
        persons.append({"person_id": person.id, "full_name": complete, "relevant": relevant,
                        "functions": matched if relevant else [], "employment_evidenced": employment,
                        "employment_reason": employment_reason, "professional_valid_email": valid_email,
                        "usable_channel": usable, "useful": useful, "identity_conflict": conflict})
    requests = capture.requests
    cost = _sum_known(requests, "final_cost_usd")
    credits = _sum_known(requests, "credits")
    latency = _sum_known(requests, "elapsed_seconds")
    return {"company_id": str(company.company_id), "provider": capture.provider,
            "country": company.country, "segment": company.segment, "status": capture.status,
            **counts, "duplicates": len(capture.candidates) - len(groups),
            "functions": sorted(functions), "functions_count": len(functions),
            "requests": len(requests), "failed_requests": sum(row.get("outcome") == "failed" for row in requests),
            "unknown_requests": sum(row.get("outcome") == "unknown" for row in requests),
            "errors": len(capture.errors), "elapsed_seconds": None if latency is None else float(latency),
            "credits": _money(credits), "final_cost_usd": _money(cost),
            "cost_per_useful_contact_usd": _money(None if cost is None or not counts["useful_contacts"]
                                                   else cost / counts["useful_contacts"]),
            "denominators": {"found": len(groups), "enriched": counts["enriched"], "requests": len(requests)},
            "people": persons}


def report_capture(manifest, captures):
    """Contrasta ambos brazos con la muestra congelada, sin suplir capturas ni fechas ausentes."""
    manifest = BenchmarkManifest.model_validate(manifest)
    captures = [BenchmarkCapture.model_validate(item) for item in captures]
    digest = manifest_digest(manifest)
    companies = {company.company_id: company for company in manifest.companies}
    pairs = set()
    for capture in captures:
        pair = (capture.company_id, capture.provider)
        if (capture.benchmark_id != manifest.benchmark_id or capture.manifest_sha256 != digest
                or capture.origin != manifest.origin or capture.company_id not in companies):
            raise ValueError("La captura no pertenece al manifiesto y origen de esta comparación.")
        if pair in pairs:
            raise ValueError("Solo se admite una captura por empresa y proveedor.")
        pairs.add(pair)
    rows = [_company_metrics(manifest, companies[item.company_id], item) for item in captures]
    providers = {}
    count_keys = ("found", "enriched", "full_names", "relevant", "employment_evidenced",
                  "professional_valid_email", "usable_channel", "useful_contacts", "duplicates", "requests",
                  "failed_requests", "unknown_requests", "errors", "identity_conflicts")
    for provider in ("apollo", "snov"):
        selected = [row for row in rows if row["provider"] == provider]
        totals = {key: sum(row[key] for row in selected) for key in count_keys}
        cost, credits = (_sum_known(selected, field) for field in ("final_cost_usd", "credits"))
        latency = _sum_known(selected, "elapsed_seconds")
        complete = len(selected) == len(companies) and all(row["status"] == "completed" for row in selected)
        functions = sorted({family for row in selected for family in row["functions"]})
        providers[provider] = {**totals, "companies_planned": len(companies), "companies_captured": len(selected),
            "companies_completed": sum(row["status"] == "completed" for row in selected),
            "coverage_complete": complete, "functions": functions, "functions_count": len(functions),
            "functions_per_company": _ratio(sum(row["functions_count"] for row in selected), len(selected)),
            "elapsed_seconds": None if latency is None else float(latency),
            "credits": _money(credits), "final_cost_usd": _money(cost),
            "cost_per_useful_contact_usd": _money(None if cost is None or not totals["useful_contacts"]
                                                   else cost / totals["useful_contacts"]),
            "enrichment_rate": _ratio(totals["enriched"], totals["found"]),
            "employment_evidence_rate": _ratio(totals["employment_evidenced"], totals["found"]),
            "usable_channel_rate": _ratio(totals["usable_channel"], totals["found"]),
            "useful_contact_rate": _ratio(totals["useful_contacts"], totals["found"]),
            "error_rate": _ratio(totals["failed_requests"], totals["requests"]),
            "denominators": {"companies": len(companies), "captured_companies": len(selected),
                             "found": totals["found"], "enriched": totals["enriched"], "requests": totals["requests"]}}
    return {"schema_version": "snov_benchmark_report_v1", "benchmark_id": str(manifest.benchmark_id),
            "origin": manifest.origin, "manifest_sha256": digest,
            "source_reference": manifest.source_reference, "config_versions": manifest.config_versions,
            "comparison_complete": all(item["coverage_complete"] for item in providers.values()),
            "missing_captures": [{"company_id": str(company_id), "provider": provider}
                                 for company_id in companies for provider in ("apollo", "snov")
                                 if (company_id, provider) not in pairs],
            "providers": providers, "companies": rows}
