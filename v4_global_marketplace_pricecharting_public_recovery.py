"""Bounded public PriceCharting retrieval recovery without relaxing identity.

The public PriceCharting search endpoint can return absolute/localized game links
or redirect an exact query directly to a product page.  The legacy parser only
accepted relative ``/game/...`` anchors, which made valid products look like
clean no-matches.  This layer broadens retrieval shapes only; the existing
name/set/number/language scoring, ambiguity margin and grade-value parsing remain
the authority.

If the exact full-number search still has no match, one additional bounded search
uses only the printed numerator.  Final candidate scoring is unchanged, so the
fallback cannot turn a fuzzy/ambiguous result into an exact valuation.  A
PriceCharting value remains GUIDE evidence, never an item-level SOLD.
"""
from __future__ import annotations

import re
from typing import Mapping, Optional
from urllib.parse import urljoin, urlsplit

import watcher
import v4_pricecharting_valuation as pc


_INSTALLED = False
_ORIGINAL_PUBLIC_CANDIDATES = None
_ORIGINAL_LOOKUP_PUBLIC = None


def _pricecharting_game_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    url = urljoin(pc.PRICECHARTING_BASE_URL, raw)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"pricecharting.com", "www.pricecharting.com"}:
        return ""
    path = parsed.path or ""
    if not re.search(r"/(?:[a-z]{2}/)?game/", path, re.IGNORECASE):
        return ""
    return url


def _canonical_product_url(raw: str) -> str:
    for tag in re.findall(r"(?is)<link\b[^>]*>", raw or ""):
        if not re.search(r"\brel\s*=\s*[\"'][^\"']*\bcanonical\b[^\"']*[\"']", tag, re.I):
            continue
        match = re.search(r"\bhref\s*=\s*[\"']([^\"']+)[\"']", tag, re.I)
        if match:
            url = _pricecharting_game_url(match.group(1))
            if url:
                return url
    return ""


def _expanded_public_search_candidates(raw: str) -> tuple[Mapping[str, object], ...]:
    assert _ORIGINAL_PUBLIC_CANDIDATES is not None
    candidates: dict[str, Mapping[str, object]] = {
        str(item.get("id") or ""): item
        for item in _ORIGINAL_PUBLIC_CANDIDATES(raw)
        if str(item.get("id") or "")
    }

    anchor_pattern = re.compile(
        r"(?is)<a\b[^>]*href=[\"'](?P<href>[^\"']*(?:/[a-z]{2})?/game/[^\"']+)[\"'][^>]*>"
        r"(?P<label>.*?)</a>"
    )
    for match in anchor_pattern.finditer(raw or ""):
        url = _pricecharting_game_url(match.group("href"))
        label = pc._html_text(match.group("label")).strip()
        if not url or not pc._normalize(label):
            continue
        candidates.setdefault(
            url,
            {
                "id": url,
                "product-name": label,
                "console-name": urlsplit(url).path.replace("/", " ").replace("-", " "),
            },
        )
        if len(candidates) >= 40:
            break

    # A sufficiently specific /search-products request may be redirected by
    # PriceCharting directly to a product page.  The canonical /game/ URL is an
    # explicit provider locator; final identity scoring still decides acceptance.
    canonical = _canonical_product_url(raw)
    if canonical and canonical not in candidates:
        body = pc._html_text(raw)
        candidates[canonical] = {
            "id": canonical,
            "product-name": body[:1600],
            "console-name": f"{urlsplit(canonical).path.replace('/', ' ').replace('-', ' ')} {body[:7000]}",
        }

    return tuple(candidates.values())


def _numerator_query(lot: watcher.Lot) -> str:
    identity = watcher.extract_card_identity(lot)
    core = str(identity.get("core") or lot.title or "").strip()
    number = str(lot.card_number or identity.get("ref") or "").strip().lstrip("#")
    numerator = number.split("/", 1)[0].strip() if number else ""
    set_name = str(lot.card_set or identity.get("series") or "").strip()
    return " ".join(part for part in (core, numerator, set_name) if part).strip()


def _lookup_public_with_numerator_recovery(
    self: pc.PriceChartingProvider,
    lot: watcher.Lot,
    price_key: str,
    exact_grade_bucket: bool,
) -> pc.PriceChartingLookup:
    """Match the wrapped method's positional call contract exactly.

    ``PriceChartingProvider.lookup`` calls ``_lookup_public(lot, price_key,
    exact_grade_bucket)`` positionally.  Keeping this wrapper positional avoids
    turning a transport-recovery layer into a runtime TypeError.
    """
    assert _ORIGINAL_LOOKUP_PUBLIC is not None
    first = _ORIGINAL_LOOKUP_PUBLIC(
        self,
        lot,
        price_key,
        exact_grade_bucket,
    )
    if first.status != "CLEAN_NO_MATCH":
        return first

    full_number = str(lot.card_number or watcher.extract_card_identity(lot).get("ref") or "")
    query = _numerator_query(lot)
    if not query or "/" not in full_number:
        return first

    try:
        search_html = self._request_public(
            "/search-products",
            {"type": "prices", "q": query},
        )
    except RuntimeError as error:
        return pc.PriceChartingLookup("PROVIDER_ERROR", note=str(error))

    selected = self._select_candidate(lot, pc._public_search_candidates(search_html))
    if isinstance(selected, pc.PriceChartingLookup):
        # Never weaken ambiguity/no-match semantics just because a second query
        # was attempted.
        return selected if selected.status == "AMBIGUOUS" else first

    product_url = selected.product_id
    try:
        product_html = self._request_public(product_url, {})
    except RuntimeError as error:
        return pc.PriceChartingLookup("PROVIDER_ERROR", product_id=product_url, note=str(error))

    body = pc._html_text(product_html)
    pseudo_detail = {
        "id": product_url,
        "product-name": body[:1600],
        "console-name": f"{product_url} {body[:7000]}",
    }
    detail_match = pc._score_candidate(lot, pseudo_detail)
    if detail_match.score < self.config.minimum_match_score:
        return first

    value = pc._public_guide_value(body, price_key)
    if value is None or value <= 0:
        return pc.PriceChartingLookup(
            "CLEAN_INSUFFICIENT",
            product_id=product_url,
            note=f"guide public {price_key} absent après récupération numerator",
        )
    bucket = "PSA 10" if exact_grade_bucket else "grade générique"
    return pc.PriceChartingLookup(
        "MATCHED",
        product_id=product_url,
        value_usd=value,
        exact_grade_bucket=exact_grade_bucket,
        note=(
            f"PriceCharting public price guide {bucket}; récupération de recherche bornée par numerator; "
            "guide calculé depuis l'historique PriceCharting, pas une vente item-level"
        ),
    )


def install_global_marketplace_pricecharting_public_recovery() -> None:
    global _INSTALLED, _ORIGINAL_PUBLIC_CANDIDATES, _ORIGINAL_LOOKUP_PUBLIC
    if _INSTALLED:
        return
    _ORIGINAL_PUBLIC_CANDIDATES = pc._public_search_candidates
    _ORIGINAL_LOOKUP_PUBLIC = pc.PriceChartingProvider._lookup_public
    pc._public_search_candidates = _expanded_public_search_candidates
    pc.PriceChartingProvider._lookup_public = _lookup_public_with_numerator_recovery
    _INSTALLED = True
