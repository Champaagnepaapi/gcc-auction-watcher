from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any, Optional, Sequence

import japan_edge_hunter as japan
import v4_global_retrieval_hardening as v1
import v4_global_retrieval_hardening_v2 as v2
from v4_global_live_shadow import SourceStatus, _norm, _price_from_usd_text
from v4_market_comc_bridge import comc_fixed_offer
from v4_market_fanatics_bridge import fanatics_fixed_offer
from v4_market_magi_bridge import magi_fixed_ask_to_observation


SINGLE_CARD_RE = re.compile(r"(?<!\d)1\s*枚")
PSA10_RE = re.compile(r"\bPSA\s*(?:GEM\s*MT\s*)?10(?:\.0)?\b", re.I)
USD_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)")


def fanatics_title_identity_proof_v3(title: str, identity: japan.Identity) -> tuple[bool, str]:
    """Prove Fanatics identity from the canonical H1 only.

    Related/sales-history page text must never manufacture a conflicting collector
    number. If Fanatics only exposes a local id, exact set + Japanese + PSA10 +
    exact name/local id still remain mandatory.
    """
    normalized_title = unicodedata.normalize("NFKC", str(title or "")).splitlines()[0].strip()
    full_ok, full_reason = v1._full_fraction_status(normalized_title, identity)
    if not full_ok:
        return False, full_reason
    if not PSA10_RE.search(normalized_title):
        return False, "psa10_unproven"
    if not v1.JAPANESE_RE.search(normalized_title):
        return False, "language_unproven"
    ok, proof = v2._fanatics_set_middle(normalized_title, identity)
    if not ok:
        return False, proof
    if not v1._contains_sensitive_claims(normalized_title, identity):
        return False, "sensitive_variant_unproven"
    return True, "EXACT_FANATICS_H1_SET_LOCAL_ID_PROOF"


def collect_fanatics_v3(page: Any, seeds: Sequence[Any], *, observed_at, max_candidates: int = 8):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = v2.MarketTrace("fanatics")
    for seed in seeds:
        try:
            links, query_count = v2.fanatics_candidate_links_v2(page, seed, max_candidates, trace)
            searches += query_count
        except Exception as error:
            trace.reject(seed, f"search_error:{type(error).__name__}")
            return found, SourceStatus("fanatics", "ERROR", type(error).__name__, searches, candidates, exact), trace
        trace.retrieved(seed, len(links))
        for url in links:
            candidates += 1
            title = ""
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(650)
                title = page.locator("h1").first.inner_text(timeout=4000).strip()
                body = page.locator("body").inner_text(timeout=5000)
            except Exception:
                trace.reject(seed, "page_error", title=title, url=url)
                continue
            upper = body.upper()
            if "THIS ITEM IS NOT AVAILABLE" in upper or re.search(r"\bSOLD\s*:", upper):
                trace.reject(seed, "unavailable_or_sold", title=title, url=url)
                continue
            before_guide = re.split(r"Guide Price", body, maxsplit=1, flags=re.I)[0]
            price = _price_from_usd_text(before_guide)
            if price is None:
                trace.reject(seed, "price_unproven", title=title, url=url)
                continue
            ok, proof = fanatics_title_identity_proof_v3(title, seed.source_identity)
            if not ok:
                trace.reject(seed, proof, title=title, url=url)
                continue
            observation = fanatics_fixed_offer(
                identity=seed.identity,
                price_usd=price,
                observed_at=observed_at,
                source_id=url,
                identity_proven=True,
                buyer_fee_rate=0.0,
                note=f"Fanatics Buy Now ASK; {proof}; vault acquisition basis; tax/payment/shipping excluded",
            )
            found[seed.identity.strict_key].append((observation, url, title))
            exact += 1
            trace.exact(seed)
    return found, SourceStatus(
        "fanatics",
        "OK",
        "public Buy Now read-only; H1-scoped identity proof prevents related-card fraction pollution",
        searches,
        candidates,
        exact,
    ), trace


def magi_identity_check_v3(ask: japan.Ask, identity: japan.Identity) -> tuple[bool, str]:
    """Keep Japan Edge's exact gate but scope the quantity test to the product title.

    magi detail pages contain unrelated recommendation text with strings such as
    '2枚'. A title explicitly saying `1枚` proves the offer itself is one card; page
    chrome cannot turn that into a bundle.
    """
    title = japan.current_text(ask.title)
    text = japan.current_text("\n".join(x for x in (ask.title, ask.text) if x))
    if japan.has_any(title, japan.AUCTION):
        return False, "ongoing_auction"
    if japan.has_any(title, japan.MULTI):
        return False, "multi_item_listing"
    if not SINGLE_CARD_RE.search(unicodedata.normalize("NFKC", title)):
        return False, "single_quantity_unproven"
    if identity.number not in japan.number_tokens(text):
        return False, "collector_number_unproven"
    if not japan.PSA10_RE.search(unicodedata.normalize("NFKC", text)):
        return False, "psa10_unproven"
    if not japan.has_any(text, japan.JP):
        return False, "language_unproven"
    if not (japan.contains(text, identity.set_name) or japan.contains(text, identity.name)):
        return False, "card_or_set_unproven"
    edition = japan.norm(identity.edition)
    if edition and (identity.year <= 2003 or edition not in {"unlimited", "standard"}) and not japan.contains(text, edition):
        return False, "edition_unproven"
    for raw in (identity.attribute, identity.variety):
        normalized = japan.norm(raw)
        if normalized and any(
            value in normalized
            for value in (
                "1st edition",
                "first edition",
                "shadowless",
                "incorrect texture",
                "error",
                "stamp",
                "stamped",
                "reverse",
                "master ball",
                "pokeball",
            )
        ) and not japan.contains(text, normalized):
            return False, "microvariant_unproven"
    return True, "MAGI_SINGLE_TITLE_PLUS_EXISTING_EXACT_GATE"


def collect_magi_v3(page: Any, seeds: Sequence[Any], *, observed_at, max_candidates: int = 8):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = v2.MarketTrace("magi")
    for seed in seeds:
        try:
            asks, query_count = v2.magi_candidates_v2(page, seed, max_candidates, trace)
            searches += query_count
        except Exception as error:
            trace.reject(seed, f"search_error:{type(error).__name__}")
            return found, SourceStatus("magi", "ERROR", type(error).__name__, searches, candidates, exact), trace
        trace.retrieved(seed, len(asks))
        for ask in asks:
            candidates += 1
            try:
                detailed = v1.magi_detail_only(page, ask)
            except Exception:
                trace.reject(seed, "detail_error", title=ask.title, url=ask.url)
                continue
            ok, proof = magi_identity_check_v3(detailed, seed.source_identity)
            if not ok:
                trace.reject(seed, proof, title=detailed.title, url=detailed.url)
                continue
            observation = magi_fixed_ask_to_observation(
                identity=seed.identity,
                price_jpy=detailed.price_jpy,
                observed_at=observed_at,
                source_id=detailed.url,
                identity_proven=True,
                buyer_fee_rate=None,
                note=f"magi fixed ASK; {proof}; buyer/logistics all-in intentionally unproven in global shadow",
            )
            found[seed.identity.strict_key].append((observation, detailed.url, detailed.title))
            exact += 1
            trace.exact(seed)
    return found, SourceStatus(
        "magi",
        "OK",
        "public read-only; title-scoped single-card proof + existing exact identity checks",
        searches,
        candidates,
        exact,
    ), trace


def _comc_text_view_url(player_url: str) -> str:
    base = str(player_url or "").rstrip("/")
    return base if "%2CvText" in base or ",vText" in base else base + "%2Csn%2CvText"


def _contains_token(text: str, target: str) -> bool:
    haystack = _norm(text)
    needle = _norm(target)
    return bool(needle) and bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack, re.I))


def _full_number_field_matches(field: str, identity: japan.Identity) -> bool:
    return japan.number(field) == japan.number(identity.number)


def _intrinsic_set_code(identity: japan.Identity) -> bool:
    value = str(identity.number or "")
    if "/" not in value:
        return False
    denominator = value.split("/", 1)[1]
    return bool(re.search(r"[A-Za-z]", denominator))


def _comc_set_proven(set_field: str, number_field: str, identity: japan.Identity) -> bool:
    if _contains_token(set_field, identity.set_name):
        return True
    return _intrinsic_set_code(identity) and _full_number_field_matches(number_field, identity)


def _parse_usd_fields(fields: Sequence[str]) -> Optional[float]:
    for field in fields:
        match = USD_RE.search(field)
        if not match:
            continue
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if value > 0:
            return value
    return None


def comc_text_row_proof_v3(line: str, identity: japan.Identity) -> tuple[bool, str, Optional[float]]:
    normalized = unicodedata.normalize("NFKC", str(line or ""))
    fields = [field.strip() for field in normalized.split("|")]
    if len(fields) < 3:
        return False, "not_text_view_row", None
    set_field, number_field, description = fields[0], fields[1], fields[2]
    if "japanese" not in _norm(set_field):
        return False, "language_unproven", None
    target_local = v1.target_local_id(identity)
    if target_local is None:
        return False, "local_id_unavailable", None
    parsed_full = japan.number(number_field)
    if parsed_full:
        if parsed_full != japan.number(identity.number):
            return False, "conflicting_full_fraction", None
    else:
        number_digits = re.sub(r"^0+", "", re.sub(r"[^0-9A-Za-z-]", "", number_field)) or "0"
        if number_digits.casefold() != target_local.casefold():
            return False, "local_id_unproven", None
    if not _comc_set_proven(set_field, number_field, identity):
        return False, "set_unproven", None
    if not re.search(rf"(?<![A-Za-z0-9]){v1._source_name_pattern(identity.name)}(?![A-Za-z0-9])", description, re.I):
        return False, "card_name_unproven", None
    if not PSA10_RE.search(description):
        return False, "psa10_unproven", None
    if not v1._contains_sensitive_claims(f"{set_field}\n{description}", identity):
        return False, "sensitive_variant_unproven", None
    price = _parse_usd_fields(fields[3:])
    if price is None:
        return False, "price_unproven", None
    return True, "COMC_TEXT_VIEW_EXACT_ROW", price


def collect_comc_v3(page: Any, seeds: Sequence[Any], *, observed_at, max_candidates: int = 8):
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    trace = v2.MarketTrace("comc")
    for seed in seeds:
        player_url = v1._comc_player_url(page, seed.source_identity.name)
        if not player_url:
            trace.reject(seed, "player_url_unresolved")
            trace.query_pages.append({"identity": trace._label(seed), "player_url": "", "rows_seen": 0})
            searches += 1
            continue
        url = _comc_text_view_url(player_url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(800)
            body = page.locator("body").inner_text(timeout=5000)
            title = page.title()
            final_url = page.url
        except Exception as error:
            trace.reject(seed, f"page_error:{type(error).__name__}", url=url)
            searches += 1
            continue
        searches += 1
        rows = [line.strip() for line in body.splitlines() if "|" in line and line.strip()]
        reasons: Counter[str] = Counter()
        accepted: list[tuple[str, float]] = []
        for line in rows:
            ok, proof, price = comc_text_row_proof_v3(line, seed.source_identity)
            if not ok:
                reasons[proof] += 1
                continue
            assert price is not None
            accepted.append((line, price))
            if len(accepted) >= max_candidates:
                break
        trace.query_pages.append(
            {
                "identity": trace._label(seed),
                "player_url": player_url,
                "text_view_url": url,
                "final_url": str(final_url)[:500],
                "title": str(title)[:200],
                "rows_seen": len(rows),
                "candidate_rows": len(accepted),
                "row_reject_reasons": dict(reasons.most_common(8)),
            }
        )
        trace.retrieved(seed, len(accepted))
        if not accepted:
            trace.reject(seed, "search_no_actionable_psa10_candidate")
            continue
        for row_text, price in accepted:
            candidates += 1
            observation = comc_fixed_offer(
                identity=seed.identity,
                price_usd=price,
                observed_at=observed_at,
                source_id=url,
                identity_proven=True,
                buyer_fee_rate=None,
                note="COMC Buy Now ASK; exact text-view row binds set/language/localId/name/PSA10/price; buyer/logistics all-in unproven",
            )
            found[seed.identity.strict_key].append((observation, url, row_text[:500]))
            exact += 1
            trace.exact(seed)
    return found, SourceStatus(
        "comc",
        "OK",
        "public read-only; COMC text-view rows bind identity, grade and ask price",
        searches,
        candidates,
        exact,
    ), trace
