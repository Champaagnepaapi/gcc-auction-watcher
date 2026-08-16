"""Strict global SOLD context for Japan Edge.

Adds independent PSA APR and direct eBay SOLD checks to the V3 PokeTrace/eBay
aggregate. Every direct comparable must prove Japanese + PSA 10 + exact card.
Marketplace inventory remains ASK-only. No transaction actions exist here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from statistics import median

from playwright.sync_api import sync_playwright

import japan_edge_hunter as base
import japan_edge_hunter_v3 as v3
import v4_canonical_multimarket as multimarket
import watcher


_ORIGINAL_POKETRACE_REFERENCE = v3.fetch_external_reference
_JAPANESE_RE = re.compile(r"\b(?:japanese|japonais|japan)\b", re.I)


@dataclass(frozen=True)
class ProviderCenter:
    source: str
    central_eur: float
    sold_count: int
    note: str = ""


def _exact_japanese_psa10_sale(sale: watcher.ComparableSale, *, require_provenance: bool) -> bool:
    if not sale.exact_card or sale.price <= 0:
        return False
    if (sale.grader or "").strip().upper() != "PSA" or sale.grade != 10:
        return False
    if require_provenance:
        return "language:japanese" in set(sale.proven_commercial_dimensions or ())
    return bool(_JAPANESE_RE.search(sale.context or "")) and sale.match_score >= 70


def _center_from_sales(
    lot: watcher.Lot,
    sales: list[watcher.ComparableSale],
    now: datetime,
    source: str,
) -> ProviderCenter | None:
    if len(sales) < 2:
        return None
    estimate = watcher.build_market_estimate(lot, sales, now)
    if estimate is None or estimate.central <= 0 or estimate.exact_grade_count < 2:
        return None
    return ProviderCenter(
        source=source,
        central_eur=round(float(estimate.central), 2),
        sold_count=int(estimate.exact_grade_count),
        note=estimate.rationale,
    )


def _direct_web_centers(op: base.Opportunity, now: datetime) -> list[ProviderCenter]:
    lot = v3._lot_for_external(op)
    centers: list[ProviderCenter] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            apr = watcher.scrape_psa_apr(page, lot, now=now)
            apr_sales = [
                sale
                for sale in apr.sales
                if _exact_japanese_psa10_sale(sale, require_provenance=True)
            ]
            apr_center = _center_from_sales(lot, apr_sales, now, "PSA APR")
            if apr_center is not None:
                centers.append(apr_center)

            ebay = watcher.scrape_ebay_sold(page, lot, with_status=True)
            ebay_sales = [
                sale
                for sale in getattr(ebay, "sales", [])
                if _exact_japanese_psa10_sale(sale, require_provenance=False)
            ]
            ebay_center = _center_from_sales(lot, ebay_sales, now, "eBay direct SOLD")
            if ebay_center is not None:
                centers.append(ebay_center)
        finally:
            browser.close()
    return centers


def fetch_full_market_reference(
    op: base.Opportunity,
    budget: multimarket.RequestBudget,
    now: datetime,
) -> v3.ExternalReference:
    """Return provider-family median without double-counting overlapping eBay data."""
    poketrace = _ORIGINAL_POKETRACE_REFERENCE(op, budget, now)
    direct_centers: list[ProviderCenter] = []
    try:
        direct_centers = _direct_web_centers(op, now)
    except Exception as error:
        direct_error = f"direct web {type(error).__name__}"
    else:
        direct_error = ""

    ebay_family_values: list[float] = []
    ebay_family_counts: list[int] = []
    ebay_notes: list[str] = []
    if poketrace.fair_eur is not None and poketrace.fair_eur > 0:
        ebay_family_values.append(float(poketrace.fair_eur))
        ebay_family_counts.append(int(poketrace.sold_count or 0))
        ebay_notes.append(f"PokeTrace={poketrace.fair_eur:.2f}")

    psa_centers: list[ProviderCenter] = []
    for center in direct_centers:
        if center.source == "eBay direct SOLD":
            ebay_family_values.append(center.central_eur)
            ebay_family_counts.append(center.sold_count)
            ebay_notes.append(f"direct={center.central_eur:.2f}")
        elif center.source == "PSA APR":
            psa_centers.append(center)

    provider_families: list[ProviderCenter] = []
    if ebay_family_values:
        provider_families.append(
            ProviderCenter(
                source="eBay SOLD family",
                central_eur=round(float(median(ebay_family_values)), 2),
                sold_count=max(ebay_family_counts or [0]),
                note=", ".join(ebay_notes),
            )
        )
    provider_families.extend(psa_centers)

    if not provider_families:
        notes = [poketrace.note or poketrace.status]
        if direct_error:
            notes.append(direct_error)
        return v3.ExternalReference(
            status="GLOBAL_EXACT_SOLD_UNAVAILABLE",
            evidence_strength="UNAVAILABLE",
            source="PokeTrace/eBay SOLD + PSA APR",
            note="; ".join(x for x in notes if x),
        )

    global_external = float(median([center.central_eur for center in provider_families]))
    source_label = " + ".join(center.source for center in provider_families)
    notes = "; ".join(
        f"{center.source} €{center.central_eur:.2f} ({center.sold_count} exact SOLD)"
        for center in provider_families
    )
    return v3.ExternalReference(
        status="EXACT_SOLD_CONFIRMED",
        fair_eur=round(global_external, 2),
        sold_count=sum(center.sold_count for center in provider_families),
        source=source_label,
        evidence_strength="STRONG",
        note=notes,
    )


def install() -> None:
    v3.fetch_external_reference = fetch_full_market_reference


def main() -> None:
    install()
    v3.main()


if __name__ == "__main__":
    main()
