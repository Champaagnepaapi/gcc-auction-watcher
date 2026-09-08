"""Bounded public PriceCharting retrieval recovery without relaxing identity.

The public PriceCharting search endpoint can return absolute/localized game links
or redirect an exact query directly to a product page. This layer broadens
retrieval shapes, parses the provider's dedicated Full Price Guide section, and
uses one respectful retry on HTTP 429. A PriceCharting value remains GUIDE
evidence, never an item-level SOLD.

Numeric-denominator cards may use PriceCharting product pages whose own identity
surface exposes only the printed numerator (for example ``Magneton #112`` while
TCGdex proves ``112/106``). Such pages are accepted only when the provider H1,
set/language and numerator all score exact and the provider identity surface does
not expose a conflicting full coordinate. Promo denominators remain strict: the
full code (for example ``242/SV-P``) must be explicitly present.
"""
from __future__ import annotations

import html
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
    raw = html.unescape(str(value or "").strip())
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

    canonical = _canonical_product_url(raw)
    if canonical and canonical not in candidates:
        body = pc._html_text(raw)
        candidates[canonical] = {
            "id": canonical,
            "product-name": body[:8000],
            "console-name": f"{urlsplit(canonical).path.replace('/', ' ').replace('-', ' ')} {body[:16000]}",
        }
    return tuple(candidates.values())


def _price_guide_section(body: str) -> str:
    text = str(body or "")
    marker = re.search(r"(?is)(?:Full\s+Price\s+Guide|Guide\s+Complet\s+des\s+Prix)\s*:", text)
    if marker is None:
        return ""
    tail = text[marker.end() :]
    end = re.search(
        r"(?is)(?:All\s+prices\s+are\s+the\s+current\s+market\s+price|"
        r"Les\s+prix\s+de\s+.+?\s+sont\s+actualis[eé]s|\n\s*Graded\s+Population\s+Report\b)",
        tail,
    )
    return (tail[: end.start()] if end is not None else tail)[:20000]


def _structured_public_guide_value(body: str, price_key: str) -> Optional[float]:
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
            rf"(?is)(?:^|\n)\s*{label}\s*(?:\||:)?\s*\$\s*([0-9][0-9,]*(?:\.\d{{1,2}})?)",
            section,
        )
        if not match:
            return None
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None
    assert _ORIGINAL_GUIDE_VALUE is not None
    return _ORIGINAL_GUIDE_VALUE(body, price_key)


def _full_number_parts(value: object) -> tuple[str, str]:
    raw = str(value or "").strip().lstrip("#")
    if "/" not in raw:
        return raw.lstrip("0") or "0", ""
    left, right = raw.split("/", 1)
    return left.strip().lstrip("0") or "0", right.strip().casefold()


def _candidate_has_number_conflict(lot: watcher.Lot, candidate: Mapping[str, object]) -> bool:
    expected = str(lot.card_number or watcher.extract_card_identity(lot).get("ref") or "").strip()
    expected_left, expected_right = _full_number_parts(expected)
    if not expected_left or not expected_right:
        return False
    text = " ".join(
        (str(candidate.get("product-name") or ""), str(candidate.get("console-name") or ""), str(candidate.get("id") or ""))
    )
    full_tokens = re.findall(r"(?i)#?\s*0*(\d{1,4})\s*/\s*([A-Za-z0-9][A-Za-z0-9.-]*)", text)
    same_numerator = [
        (left.lstrip("0") or "0", right.casefold())
        for left, right in full_tokens
        if (left.lstrip("0") or "0") == expected_left
    ]
    if same_numerator and not any(right == expected_right for _, right in same_numerator):
        return True
    if not expected_right.isdigit():
        compact_expected = re.sub(r"[^a-z0-9]", "", expected.casefold())
        compact_text = re.sub(r"[^a-z0-9]", "", text.casefold())
        return compact_expected not in compact_text
    return False


def _safe_candidates(lot: watcher.Lot, candidates: Sequence[Mapping[str, object]]) -> tuple[Mapping[str, object], ...]:
    return tuple(candidate for candidate in candidates if not _candidate_has_number_conflict(lot, candidate))


def _request_public_with_one_429_retry(self: pc.PriceChartingProvider, path_or_url: str, parameters: Mapping[str, str]) -> str:
    try:
        return self._request_public(path_or_url, parameters)
    except RuntimeError as error:
        if "HTTP 429" not in str(error):
            raise
        time.sleep(max(2.0, float(self.config.public_request_interval_seconds)))
        return self._request_public(path_or_url, parameters)


def _numerator_query(lot: watcher.Lot) -> str:
    identity = watcher.extract_card_identity(lot)
    core = str(identity.get("core") or lot.title or "").strip()
    number = str(lot.card_number or identity.get("ref") or "").strip().lstrip("#")
    numerator = number.split("/", 1)[0].strip() if number else ""
    set_name = str(lot.card_set or identity.get("series") or "").strip()
    return " ".join(part for part in (core, numerator, set_name) if part).strip()


def _recovery_query(lot: watcher.Lot) -> str:
    identity = watcher.extract_card_identity(lot)
    core = str(identity.get("core") or lot.title or "").strip()
    full_number = str(lot.card_number or identity.get("ref") or "").strip().lstrip("#")
    _left, right = _full_number_parts(full_number)
    if right and not right.isdigit():
        return " ".join(part for part in (core, full_number, "Pokemon Japanese Promo") if part).strip()
    return _numerator_query(lot)


def _slug(value: object) -> str:
    return "-".join(pc._normalize(value).split())


def _direct_product_url(lot: watcher.Lot) -> str:
    """Build one provider-convention candidate; page proof is still mandatory."""
    identity = watcher.extract_card_identity(lot)
    name = str(identity.get("core") or lot.title or "").strip()
    set_name = str(lot.card_set or identity.get("series") or "").strip()
    full_number = str(lot.card_number or identity.get("ref") or "").strip().lstrip("#")
    left, right = _full_number_parts(full_number)
    if not name or not set_name or not left or not right:
        return ""
    if not right.isdigit():
        set_slug = "pokemon-japanese-promo"
        number_slug = f"{left}{right}"
    else:
        set_slug = f"pokemon-japanese-{_slug(set_name)}"
        number_slug = left
    product_slug = f"{_slug(name)}-{_slug(number_slug)}"
    if not set_slug or not product_slug:
        return ""
    return f"{pc.PRICECHARTING_BASE_URL}/game/{set_slug}/{product_slug}"


def _product_identity_text(raw_html: str, body: str) -> str:
    """Keep identity fields only; historical sold titles must not create conflicts."""
    parts: list[str] = []
    h1 = re.search(r"(?is)<h1\b[^>]*>(.*?)</h1>", raw_html or "")
    if h1:
        parts.append(pc._html_text(h1.group(1)).strip())
    number = re.search(r"(?is)(?:Card\s+Number|Num[eé]ro\s+de\s+carte)\s*:\s*(#?\s*[A-Za-z0-9./-]+)", body or "")
    if number:
        parts.append(f"Card Number: {number.group(1).strip()}")
    return " ".join(part for part in parts if part)[:2000]


def _lookup_public_with_numerator_recovery(
    self: pc.PriceChartingProvider,
    lot: watcher.Lot,
    price_key: str,
    exact_grade_bucket: bool,
) -> pc.PriceChartingLookup:
    query = self._query(lot)
    if not query:
        return pc.PriceChartingLookup("CLEAN_NO_MATCH", note="identité PriceCharting insuffisante")
    try:
        search_html = _request_public_with_one_429_retry(self, "/search-products", {"type": "prices", "q": query})
    except RuntimeError as error:
        return pc.PriceChartingLookup("PROVIDER_ERROR", note=str(error))

    candidates = _safe_candidates(lot, pc._public_search_candidates(search_html))
    selected = self._select_candidate(lot, candidates)
    full_number = str(lot.card_number or watcher.extract_card_identity(lot).get("ref") or "")
    recovered_by_search = False
    if isinstance(selected, pc.PriceChartingLookup) and selected.status == "CLEAN_NO_MATCH":
        retry_query = _recovery_query(lot)
        if retry_query and "/" in full_number:
            try:
                retry_html = _request_public_with_one_429_retry(self, "/search-products", {"type": "prices", "q": retry_query})
            except RuntimeError as error:
                return pc.PriceChartingLookup("PROVIDER_ERROR", note=str(error))
            retry_selected = self._select_candidate(lot, _safe_candidates(lot, pc._public_search_candidates(retry_html)))
            if isinstance(retry_selected, pc.PriceChartingLookup):
                if retry_selected.status == "AMBIGUOUS":
                    return retry_selected
            else:
                selected = retry_selected
                recovered_by_search = True

    direct_recovery = False
    if isinstance(selected, pc.PriceChartingLookup):
        if selected.status != "CLEAN_NO_MATCH":
            return selected
        product_url = _direct_product_url(lot)
        if not product_url:
            return selected
        direct_recovery = True
    else:
        product_url = selected.product_id

    try:
        product_html = _request_public_with_one_429_retry(self, product_url, {})
    except RuntimeError as error:
        if direct_recovery and "HTTP 404" in str(error):
            return selected if isinstance(selected, pc.PriceChartingLookup) else pc.PriceChartingLookup("CLEAN_NO_MATCH")
        return pc.PriceChartingLookup("PROVIDER_ERROR", product_id=product_url, note=str(error))

    body = pc._html_text(product_html)
    identity_text = _product_identity_text(product_html, body)
    pseudo_detail = {
        "id": product_url,
        "product-name": identity_text,
        "console-name": f"{urlsplit(product_url).path.replace('/', ' ').replace('-', ' ')} {identity_text}",
    }
    if _candidate_has_number_conflict(lot, pseudo_detail):
        return pc.PriceChartingLookup("CLEAN_NO_MATCH", product_id=product_url, note="coordonnée imprimée PriceCharting en conflit")
    detail_match = pc._score_candidate(lot, pseudo_detail)
    if detail_match.score < self.config.minimum_match_score:
        return pc.PriceChartingLookup("CLEAN_NO_MATCH", product_id=product_url, note="identité page publique PriceCharting non prouvée")
    value = pc._public_guide_value(body, price_key)
    if value is None or value <= 0:
        return pc.PriceChartingLookup("CLEAN_INSUFFICIENT", product_id=product_url, note=f"guide public {price_key} absent")

    bucket = "PSA 10" if exact_grade_bucket else "grade générique"
    recovery_note = ""
    if recovered_by_search:
        recovery_note = "; récupération de recherche bornée"
    elif direct_recovery:
        recovery_note = "; récupération URL fournisseur bornée + page revalidée"
    return pc.PriceChartingLookup(
        "MATCHED",
        product_id=product_url,
        value_usd=value,
        exact_grade_bucket=exact_grade_bucket,
        note=(f"PriceCharting public price guide {bucket}{recovery_note}; guide calculé depuis l'historique PriceCharting, pas une vente item-level"),
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
