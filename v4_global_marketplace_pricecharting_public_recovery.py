"""Bounded public PriceCharting retrieval recovery without relaxing identity.

The public PriceCharting search endpoint can return absolute/localized game links
or redirect an exact query directly to a product page. This layer broadens
retrieval shapes, parses the provider's dedicated Full Price Guide section, and
uses one respectful retry on HTTP 429. A PriceCharting value remains GUIDE
evidence, never an item-level SOLD.

The recovery may use PriceCharting as the only valuation guide when no stronger
SOLD-derived source is available, but PriceCharting must prove its own product
identity. TCGdex is not a prerequisite for a PriceCharting GUIDE match.
"""
from __future__ import annotations

import re
import time
from typing import Mapping, Optional, Sequence
from urllib.parse import urljoin, urlsplit

import watcher
import v4_pricecharting_valuation as pc


_INSTALLED = False
_ORIGINAL_PUBLIC_CANDIDATES = None
_ORIGINAL_LOOKUP_PUBLIC = None
_ORIGINAL_GUIDE_VALUE = None


def _pricecharting_game_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    url = urljoin(pc.PRICECHARTING_BASE_URL, raw)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "pricecharting.com",
        "www.pricecharting.com",
    }:
        return ""
    path = parsed.path or ""
    if not re.search(r"/(?:[a-z]{2}/)?game/", path, re.IGNORECASE):
        return ""
    return url


def _canonical_product_url(raw: str) -> str:
    for tag in re.findall(r"(?is)<link\b[^>]*>", raw or ""):
        if not re.search(
            r"\brel\s*=\s*[\"'][^\"']*\bcanonical\b[^\"']*[\"']",
            tag,
            re.I,
        ):
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
    # PriceCharting directly to a product page. The canonical /game/ URL is an
    # explicit provider locator; final identity scoring still decides acceptance.
    canonical = _canonical_product_url(raw)
    if canonical and canonical not in candidates:
        body = pc._html_text(raw)
        candidates[canonical] = {
            "id": canonical,
            # Current PriceCharting pages put Card Number/Details below menu and
            # comparison content. Keep enough bounded text for deterministic
            # name/set/number/language scoring without parsing arbitrary size.
            "product-name": body[:8000],
            "console-name": (
                f"{urlsplit(canonical).path.replace('/', ' ').replace('-', ' ')} "
                f"{body[:16000]}"
            ),
        }

    return tuple(candidates.values())


def _price_guide_section(body: str) -> str:
    """Return only the provider's dedicated Full Price Guide block when present."""
    text = str(body or "")
    marker = re.search(
        r"(?is)(?:Full\s+Price\s+Guide|Guide\s+Complet\s+des\s+Prix)\s*:",
        text,
    )
    if marker is None:
        return ""
    tail = text[marker.end() :]
    end = re.search(
        r"(?is)(?:All\s+prices\s+are\s+the\s+current\s+market\s+price|"
        r"Les\s+prix\s+de\s+.+?\s+sont\s+actualis[eé]s|"
        r"\n\s*Graded\s+Population\s+Report\b)",
        tail,
    )
    section = tail[: end.start()] if end is not None else tail
    return section[:20000]


def _structured_public_guide_value(body: str, price_key: str) -> Optional[float]:
    """Read the requested grade from Full Price Guide, never the compare-table row."""
    labels = {
        "manual-only-price": r"PSA\s*10",
        "graded-price": r"Grade\s*9(?!\.5)",
        "new-price": r"Grade\s*8(?!\.5)",
    }
    label = labels.get(price_key)
    if not label:
        return None

    section = _price_guide_section(body)
    if section:
        match = re.search(
            rf"(?is)(?:^|\n)\s*{label}\s*(?:\||:)?\s*\$\s*"
            r"([0-9][0-9,]*(?:\.\d{1,2})?)",
            section,
        )
        if not match:
            return None
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None

    # Backward-compatible fallback for small/simple fixtures or provider pages
    # that genuinely lack a dedicated Full Price Guide heading.
    assert _ORIGINAL_GUIDE_VALUE is not None
    return _ORIGINAL_GUIDE_VALUE(body, price_key)


def _full_number_parts(value: object) -> tuple[str, str]:
    raw = str(value or "").strip().lstrip("#")
    if "/" not in raw:
        return raw.lstrip("0") or "0", ""
    left, right = raw.split("/", 1)
    return left.strip().lstrip("0") or "0", right.strip().casefold()


def _candidate_has_number_conflict(
    lot: watcher.Lot,
    candidate: Mapping[str, object],
) -> bool:
    """Reject explicit denominator/promo-code conflicts before fuzzy scoring."""
    expected = str(
        lot.card_number or watcher.extract_card_identity(lot).get("ref") or ""
    ).strip()
    expected_left, expected_right = _full_number_parts(expected)
    if not expected_left or not expected_right:
        return False

    text = " ".join(
        (
            str(candidate.get("product-name") or ""),
            str(candidate.get("console-name") or ""),
            str(candidate.get("id") or ""),
        )
    )
    full_tokens = re.findall(
        r"(?i)#?\s*0*(\d{1,4})\s*/\s*([A-Za-z0-9][A-Za-z0-9.-]*)",
        text,
    )
    same_numerator = [
        (left.lstrip("0") or "0", right.casefold())
        for left, right in full_tokens
        if (left.lstrip("0") or "0") == expected_left
    ]
    if same_numerator and not any(right == expected_right for _, right in same_numerator):
        return True

    # Promo coordinates are set-code-bearing printed numbers. If the provider
    # candidate does not expose the exact full coordinate, numerator-only is not
    # enough (e.g. 291/SV-P must never match 291/SM-P).
    if not expected_right.isdigit():
        compact_expected = re.sub(r"[^a-z0-9]", "", expected.casefold())
        compact_text = re.sub(r"[^a-z0-9]", "", text.casefold())
        return compact_expected not in compact_text
    return False


def _safe_candidates(
    lot: watcher.Lot,
    candidates: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        candidate
        for candidate in candidates
        if not _candidate_has_number_conflict(lot, candidate)
    )


def _request_public_with_one_429_retry(
    self: pc.PriceChartingProvider,
    path_or_url: str,
    parameters: Mapping[str, str],
) -> str:
    try:
        return self._request_public(path_or_url, parameters)
    except RuntimeError as error:
        if "HTTP 429" not in str(error):
            raise
        # Respect provider throttling: one bounded retry only, after a real wait.
        time.sleep(max(2.0, float(self.config.public_request_interval_seconds)))
        return self._request_public(path_or_url, parameters)


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
    """Public lookup with exact provider-page proof and one numerator retry."""
    query = self._query(lot)
    if not query:
        return pc.PriceChartingLookup(
            "CLEAN_NO_MATCH", note="identité PriceCharting insuffisante"
        )

    try:
        search_html = _request_public_with_one_429_retry(
            self,
            "/search-products",
            {"type": "prices", "q": query},
        )
    except RuntimeError as error:
        return pc.PriceChartingLookup("PROVIDER_ERROR", note=str(error))

    candidates = _safe_candidates(lot, pc._public_search_candidates(search_html))
    selected = self._select_candidate(lot, candidates)

    full_number = str(
        lot.card_number or watcher.extract_card_identity(lot).get("ref") or ""
    )
    recovered_by_numerator = False
    if isinstance(selected, pc.PriceChartingLookup) and selected.status == "CLEAN_NO_MATCH":
        retry_query = _numerator_query(lot)
        if retry_query and "/" in full_number:
            try:
                retry_html = _request_public_with_one_429_retry(
                    self,
                    "/search-products",
                    {"type": "prices", "q": retry_query},
                )
            except RuntimeError as error:
                return pc.PriceChartingLookup("PROVIDER_ERROR", note=str(error))
            retry_candidates = _safe_candidates(
                lot, pc._public_search_candidates(retry_html)
            )
            retry_selected = self._select_candidate(lot, retry_candidates)
            if isinstance(retry_selected, pc.PriceChartingLookup):
                # Ambiguity is stronger information than the initial no-match.
                if retry_selected.status == "AMBIGUOUS":
                    return retry_selected
            else:
                selected = retry_selected
                recovered_by_numerator = True

    if isinstance(selected, pc.PriceChartingLookup):
        return selected

    product_url = selected.product_id
    try:
        product_html = _request_public_with_one_429_retry(self, product_url, {})
    except RuntimeError as error:
        return pc.PriceChartingLookup(
            "PROVIDER_ERROR", product_id=product_url, note=str(error)
        )

    body = pc._html_text(product_html)
    pseudo_detail = {
        "id": product_url,
        "product-name": body[:8000],
        "console-name": f"{product_url} {body[:16000]}",
    }
    if _candidate_has_number_conflict(lot, pseudo_detail):
        return pc.PriceChartingLookup(
            "CLEAN_NO_MATCH",
            product_id=product_url,
            note="coordonnée imprimée PriceCharting en conflit",
        )

    detail_match = pc._score_candidate(lot, pseudo_detail)
    if detail_match.score < self.config.minimum_match_score:
        return pc.PriceChartingLookup(
            "CLEAN_NO_MATCH",
            product_id=product_url,
            note="identité page publique PriceCharting non prouvée",
        )

    value = pc._public_guide_value(body, price_key)
    if value is None or value <= 0:
        return pc.PriceChartingLookup(
            "CLEAN_INSUFFICIENT",
            product_id=product_url,
            note=f"guide public {price_key} absent",
        )

    bucket = "PSA 10" if exact_grade_bucket else "grade générique"
    recovery_note = (
        "; récupération de recherche bornée par numerator"
        if recovered_by_numerator
        else ""
    )
    return pc.PriceChartingLookup(
        "MATCHED",
        product_id=product_url,
        value_usd=value,
        exact_grade_bucket=exact_grade_bucket,
        note=(
            f"PriceCharting public price guide {bucket}{recovery_note}; "
            "guide calculé depuis l'historique PriceCharting, pas une vente item-level"
        ),
    )


def install_global_marketplace_pricecharting_public_recovery() -> None:
    global _INSTALLED
    global _ORIGINAL_PUBLIC_CANDIDATES, _ORIGINAL_LOOKUP_PUBLIC, _ORIGINAL_GUIDE_VALUE
    if _INSTALLED:
        return
    _ORIGINAL_PUBLIC_CANDIDATES = pc._public_search_candidates
    _ORIGINAL_LOOKUP_PUBLIC = pc.PriceChartingProvider._lookup_public
    _ORIGINAL_GUIDE_VALUE = pc._public_guide_value
    pc._public_search_candidates = _expanded_public_search_candidates
    pc._public_guide_value = _structured_public_guide_value
    pc.PriceChartingProvider._lookup_public = _lookup_public_with_numerator_recovery
    _INSTALLED = True
