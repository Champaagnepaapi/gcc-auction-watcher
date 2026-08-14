from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from datetime import datetime
from typing import Any, Optional, Sequence

import watcher
import v4_canonical_multimarket as canonical_market
import v4_price_discovery as price_discovery


CATEGORY_SAME_GRADER_MARKET_DISCOUNT = "SAME_GRADER_MARKET_DISCOUNT"
SAME_GRADER_DISCOUNT_MIN_RATIO = 1.25

_ORIGINAL_LANGUAGE_CODE = canonical_market._language_code
_ORIGINAL_COLLECT_PRICE_DISCOVERY_LEAD = canonical_market._collect_price_discovery_lead
_ORIGINAL_EVALUATE_PRICE_DISCOVERY = price_discovery.evaluate_price_discovery
_ORIGINAL_MAYBE_NOTIFY_INCOMPLETE_COVERAGE = watcher.maybe_notify_incomplete_coverage
_INSTALLED = False


_LANGUAGE_ALIASES = {
    "fr": "fr",
    "fra": "fr",
    "fre": "fr",
    "fr fr": "fr",
    "french": "fr",
    "francais": "fr",
    "francaise": "fr",
    "en": "en",
    "eng": "en",
    "en gb": "en",
    "en us": "en",
    "english": "en",
    "anglais": "en",
    "ja": "ja",
    "jp": "ja",
    "jpn": "ja",
    "japanese": "ja",
    "japonais": "ja",
    "de": "de",
    "deu": "de",
    "ger": "de",
    "german": "de",
    "allemand": "de",
    "es": "es",
    "spa": "es",
    "spanish": "es",
    "espagnol": "es",
    "it": "it",
    "ita": "it",
    "italian": "it",
    "italien": "it",
    "pt": "pt",
    "por": "pt",
    "portuguese": "pt",
    "portugais": "pt",
    "ko": "ko",
    "kor": "ko",
    "korean": "ko",
    "coreen": "ko",
    "nl": "nl",
    "nld": "nl",
    "dut": "nl",
    "dutch": "nl",
    "neerlandais": "nl",
    "pl": "pl",
    "pol": "pl",
    "polish": "pl",
    "polonais": "pl",
    "ru": "ru",
    "rus": "ru",
    "russian": "ru",
    "russe": "ru",
    "id": "id",
    "ind": "id",
    "indonesian": "id",
    "indonesien": "id",
    "th": "th",
    "tha": "th",
    "thai": "th",
    "zh": "zh-tw",
    "zh tw": "zh-tw",
    "zho": "zh-tw",
    "chinese": "zh-tw",
    "chinois": "zh-tw",
}


def _plain(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def canonical_language_code(value: object) -> str:
    """Normalize human labels and common ISO aliases to one market language code."""
    plain = _plain(value)
    if not plain:
        return ""
    return _LANGUAGE_ALIASES.get(plain, plain)


def _patched_language_code(lot: watcher.Lot) -> str:
    identity = watcher.extract_card_identity(lot)
    value = lot.language or identity.get("language") or ""
    canonical = canonical_language_code(value)
    if canonical:
        return canonical
    return _ORIGINAL_LANGUAGE_CODE(lot)


def canonical_identity_complete(
    lot: watcher.Lot,
    canonical: canonical_market.CanonicalCard,
) -> bool:
    """Require a resolved card key before any Edge Hunter comp may be called exact."""
    number = canonical.full_number or canonical.local_id or lot.card_number
    language = canonical_language_code(
        canonical.language_code or lot.language or watcher.extract_card_identity(lot).get("language")
    )
    try:
        grade = float(lot.grade) if lot.grade is not None else None
    except (TypeError, ValueError):
        grade = None
    return bool(
        canonical.status == "EXACT"
        and canonical.card_id
        and canonical.set_id
        and canonical.set_name
        and canonical.name
        and number
        and language
        and (lot.grader or "").strip()
        and grade is not None
        and 0 < grade <= 10
    )


def _collect_price_discovery_lead_guarded(
    candidate: watcher.ValuationCandidate,
    canonical: canonical_market.CanonicalCard,
    raw: Optional[canonical_market.RawMarketSignal],
    poketrace: Optional[watcher.ExternalMarketEvidence] = None,
    fallback: Optional[watcher.ExternalMarketEvidence] = None,
    now: Optional[Any] = None,
) -> Optional[canonical_market.ManualReviewLead]:
    if not canonical_identity_complete(candidate.lot, canonical):
        watcher.log(
            "Edge Hunter fail-closed: IDENTITY_INCOMPLETE | "
            "EXACT_COMPS_UNVERIFIED | "
            f"{candidate.lot.url or candidate.lot.title}"
        )
        return None
    return _ORIGINAL_COLLECT_PRICE_DISCOVERY_LEAD(
        candidate,
        canonical,
        raw,
        poketrace,
        fallback,
        now,
    )


def _normalized_anchor(anchor: price_discovery.AdjacentAnchor) -> price_discovery.AdjacentAnchor:
    language = canonical_language_code(anchor.language)
    return replace(anchor, language=language or _plain(anchor.language))


def _same_grader_sold_anchors(
    signal: price_discovery.PriceDiscoverySignal,
    grader: str,
    grade: str,
) -> list[price_discovery.AdjacentAnchor]:
    norm_grader = (grader or "").strip().upper()
    target_grade = price_discovery._numeric_grade(grade)
    return [
        anchor
        for anchor in signal.credible_adjacent_anchors
        if not anchor.is_active_ask
        and anchor.price_type == "SOLD"
        and (anchor.grader or "").strip().upper() == norm_grader
        and price_discovery._numeric_grade(anchor.grade) == target_grade
        and anchor.price > 0
    ]


def evaluate_price_discovery_guarded(
    *,
    listing_identity: str,
    gcc_price: float,
    grader: str,
    grade: str,
    language: str = "fr",
    target_language: Optional[str] = None,
    exact_grader_sales: Sequence[Any] = (),
    recent_exact_sales: Sequence[Any] = (),
    adjacent_anchors: Sequence[price_discovery.AdjacentAnchor] = (),
    raw_consensus: Optional[Any] = None,
    crossgrade_probability: Optional[float] = None,
    temporal_adjustment: Optional[price_discovery.TemporalAdjustmentResult] = None,
    historical_target_sales: Sequence[Any] = (),
    historical_reference_sales: Sequence[Any] = (),
    now: Optional[datetime] = None,
) -> price_discovery.PriceDiscoverySignal:
    normalized_language = canonical_language_code(target_language or language) or "fr"
    normalized_anchors = tuple(_normalized_anchor(anchor) for anchor in adjacent_anchors)

    signal = _ORIGINAL_EVALUATE_PRICE_DISCOVERY(
        listing_identity=listing_identity,
        gcc_price=gcc_price,
        grader=grader,
        grade=grade,
        language=normalized_language,
        target_language=normalized_language,
        exact_grader_sales=exact_grader_sales,
        recent_exact_sales=recent_exact_sales,
        adjacent_anchors=normalized_anchors,
        raw_consensus=raw_consensus,
        crossgrade_probability=crossgrade_probability,
        temporal_adjustment=temporal_adjustment,
        historical_target_sales=historical_target_sales,
        historical_reference_sales=historical_reference_sales,
        now=now,
    )

    # A liquid PCA/BGS/CGC listing supported by same-grader, same-grade SOLD comps
    # is a same-grader market discount, not a cross-grader/secondary-grader spread.
    if signal.category != price_discovery.CATEGORY_SECONDARY_GRADER_DISCOUNT:
        return signal

    same_grader = _same_grader_sold_anchors(signal, grader, grade)
    evidence_points = sum(max(1, int(anchor.sale_count or 1)) for anchor in same_grader)
    if evidence_points < 2:
        return signal

    reference = price_discovery.compute_robust_reference_value(
        [anchor.price for anchor in same_grader]
    )
    if reference is None or reference <= 0 or gcc_price <= 0:
        return signal
    upside_ratio = reference / gcc_price
    if upside_ratio < SAME_GRADER_DISCOUNT_MIN_RATIO:
        return signal

    diagnostics = tuple(
        item
        for item in signal.diagnostics
        if item != price_discovery.CATEGORY_SECONDARY_GRADER_DISCOUNT
    ) + (
        CATEGORY_SAME_GRADER_MARKET_DISCOUNT,
        f"SAME_GRADER_EXACT_SOLD_EVIDENCE_{evidence_points}",
    )
    return replace(
        signal,
        category=CATEGORY_SAME_GRADER_MARKET_DISCOUNT,
        credible_high_reference=round(reference, 2),
        asymmetric_upside_ratio=round(upside_ratio, 2),
        main_thesis=(
            f"Same-grader {str(grader or '').strip().upper()} {grade} sold market "
            f"supports {reference:.2f} € vs GCC {gcc_price:.2f} € "
            f"({evidence_points} exact sold evidence point(s))"
        ),
        diagnostics=diagnostics,
    )


def format_technical_coverage_message(diagnostics: watcher.RunDiagnostics) -> str:
    fixed = diagnostics.fixed_coverage
    auction = diagnostics.auction_coverage
    fixed_economic = diagnostics.fixed_economic_coverage
    auction_economic = diagnostics.auction_economic_coverage
    queue = diagnostics.fixed_queue

    if (
        fixed.expected_total_scope == watcher.EXPECTED_TOTAL_SAME_QUERY
        and fixed.expected_total is not None
    ):
        fixed_discovery = (
            f"{fixed.unique_listings}/{fixed.expected_total} | {fixed.status}"
        )
    else:
        fixed_discovery = f"{fixed.unique_listings} listing(s) | {fixed.status}"

    auction_scope = getattr(
        diagnostics,
        "auction_discovery_scope_status",
        "TARGET_SCOPE_UNKNOWN",
    )
    lines = [
        "GCC SCAN COVERAGE — ACTION REQUIRED",
        f"Discovery fixed universe: {fixed_discovery}",
        (
            "Discovery auctions target scope: "
            f"{auction.unique_listings} listing(s) observed | {auction.status} | {auction_scope}"
        ),
    ]
    if (
        auction.expected_total is not None
        and auction.expected_total_scope != watcher.EXPECTED_TOTAL_SAME_QUERY
    ):
        lines.append(
            "GCC wider on-sale auction total (diagnostic only; not denominator): "
            f"{auction.expected_total}"
        )

    lines.extend(
        [
            (
                "Economic fixed (discovered valuation candidates): "
                f"{fixed_economic.attempted}/{fixed_economic.candidates} attempted | "
                f"{queue.status} | deferred by economic budget {fixed_economic.skipped_by_cap}"
            ),
            (
                "Economic auctions (discovered <=60m candidates): "
                f"{auction_economic.attempted}/{auction_economic.candidates} attempted | "
                f"{auction_economic.status} | deferred by economic budget "
                f"{auction_economic.skipped_by_cap}"
            ),
            (
                "Urgent fixed deferred: new "
                f"{queue.budget_skipped_count(watcher.QUEUE_P0_NEW)} | changed "
                f"{queue.budget_skipped_count(watcher.QUEUE_P1_CHANGED)}"
            ),
            (
                "Never-evaluated fixed backlog: "
                f"{queue.backlog_count(watcher.QUEUE_P2_NEVER_EVALUATED)}"
            ),
            f"State issue: {diagnostics.state_issue or 'NONE'}",
            f"DISCOVERY OVERALL: {diagnostics.discovery_coverage_status}",
            f"ECONOMIC OVERALL: {diagnostics.economic_coverage_status}",
            f"GLOBAL COVERAGE: {diagnostics.scan_coverage_status}",
            (
                "ECONOMIC RESULT TRUSTWORTHY: "
                f"{'YES' if diagnostics.economic_result_trustworthy else 'NO'}"
            ),
            "Discovery itself is not capped by valuation/provider budgets.",
        ]
    )
    return "\n".join(lines)


def maybe_notify_incomplete_coverage_guarded(
    diagnostics: watcher.RunDiagnostics,
    state: dict,
    now: datetime,
) -> bool:
    if not watcher._technical_alert_required(diagnostics) or not watcher.NTFY_TOPIC:
        return False

    signature = watcher._technical_coverage_signature(diagnostics)
    previous = state.setdefault("technical_alerts", {}).get("gcc_coverage", {})
    previous_at = watcher._parse_state_datetime(previous.get("sent_at"))
    if previous_at is not None:
        try:
            in_cooldown = (
                now - previous_at
            ).total_seconds() < watcher.GCC_TECH_ALERT_COOLDOWN_SECONDS
        except TypeError:
            in_cooldown = False
        if in_cooldown:
            qualifier = "identique " if previous.get("signature") == signature else ""
            watcher.log(
                f"Alerte technique couverture {qualifier}déjà envoyée récemment"
            )
            return False

    message = format_technical_coverage_message(diagnostics)
    try:
        watcher.requests.post(
            f"{watcher.NTFY_SERVER}/{watcher.NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": "GCC SCAN INCOMPLETE",
                "Priority": "4",
                "Tags": "warning,magnifying_glass_tilted_left",
            },
            timeout=10,
        ).raise_for_status()
        state["technical_alerts"]["gcc_coverage"] = {
            "signature": signature,
            "sent_at": now.isoformat(),
        }
        watcher.log("Alerte technique couverture ntfy envoyée")
        return True
    except Exception as error:
        watcher.log(
            f"Alerte technique couverture ntfy échouée: {type(error).__name__}"
        )
        return False


def install_v4_edge_hunter_safety() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Keep the canonical resolver and Edge Hunter on the same language vocabulary.
    canonical_market._LANGUAGE_CODES.update(
        {alias: code for alias, code in _LANGUAGE_ALIASES.items() if " " not in alias}
    )
    canonical_market._language_code = _patched_language_code

    # Price-discovery labels and weighting are patched without changing the core
    # production opportunity/arbitration pipeline.
    price_discovery.CATEGORY_SAME_GRADER_MARKET_DISCOUNT = (
        CATEGORY_SAME_GRADER_MARKET_DISCOUNT
    )
    price_discovery.evaluate_price_discovery = evaluate_price_discovery_guarded

    # Exact-comp semantics fail closed unless the canonical identity is complete.
    canonical_market._collect_price_discovery_lead = (
        _collect_price_discovery_lead_guarded
    )

    # Clarify coverage scope in phone alerts; discovery and economic budgets stay separate.
    watcher.maybe_notify_incomplete_coverage = maybe_notify_incomplete_coverage_guarded
    _INSTALLED = True
