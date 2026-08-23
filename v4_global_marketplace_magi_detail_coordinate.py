"""Deterministic Magi detail-evidence coordinate recovery.

The Magi detail fetch already keeps the current product body. Some public Magi
listings omit the collector fraction or set code from ``page.title()`` while
exposing it on the current product detail. This layer allows that explicit
product evidence to feed the existing Magi-native TCGdex proof without guessing
or fuzzy matching.
"""
from __future__ import annotations

import re
import unicodedata

import japan_edge_hunter as japan
import v4_global_marketplace_magi_native_identity as native
import v4_global_retrieval_hardening_v3 as retrieval_v3


_EXPLICIT_JAPANESE_ENGLISH_RE = re.compile(r"英語(?:版)?", re.I)
_MAGI_FOOTER_BOUNDARY_RE = re.compile(
    r"\n(?:絞り込み|カテゴリで絞り込む|magiについて)\s*(?:\n|$)",
    re.I,
)


def _current_product_evidence(ask: japan.Ask) -> str:
    """Keep current-listing evidence and exclude Magi navigation/footer chrome.

    Magi's footer contains a permanent ``magi（英語版）`` link. That is a site
    navigation label, not card-language evidence. Product description text above
    the footer remains authoritative, so a real ``英語版`` claim still blocks.
    """
    evidence = japan.current_text("\n".join(value for value in (ask.title, ask.text) if value))
    return _MAGI_FOOTER_BOUNDARY_RE.split(evidence, maxsplit=1)[0]


def _full_number_from_evidence(text: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).upper()
    tokens = {
        japan.number(match.group(0))
        for match in japan.CARD_RE.finditer(normalized)
        if japan.number(match.group(0))
    }
    if not tokens:
        return "", "collector_number_unproven"
    if len(tokens) != 1:
        return "", "collector_number_ambiguous"
    return next(iter(tokens)), "full_collector_number_exact_detail"


def _set_code_from_evidence(text: str, full_number: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    codes = {
        match.group(1).strip()
        for match in retrieval_v3.MAGI_SET_CODE_RE.finditer(normalized)
        if match.group(1).strip()
    }
    if len(codes) > 1:
        return "", "set_code_ambiguous"
    if len(codes) == 1:
        return next(iter(codes)), "explicit_set_code_detail"

    if "/" in full_number:
        denominator = full_number.split("/", 1)[1]
        if not denominator.isdigit() and native._SET_ID_RE.fullmatch(denominator):
            return denominator, "intrinsic_promo_set_code"
    return "", "set_code_unproven"


def preflight_with_detail_coordinate(ask: japan.Ask) -> tuple[str, str, str]:
    title = japan.current_text(ask.title)
    evidence = _current_product_evidence(ask)

    if japan.has_any(title, japan.AUCTION):
        return "", "", "ongoing_auction"
    if japan.has_any(title, japan.MULTI):
        return "", "", "multi_item_listing"
    if not retrieval_v3.SINGLE_CARD_RE.search(unicodedata.normalize("NFKC", title)):
        return "", "", "single_quantity_unproven"
    if not retrieval_v3.PSA10_RE.search(unicodedata.normalize("NFKC", title)):
        return "", "", "psa10_unproven"

    # Latin EN/ENG claims are title-scoped. Japanese 英語/英語版 remains blocking
    # anywhere in the bounded current-product evidence, but footer navigation is
    # excluded before this check.
    if native._EXPLICIT_ENGLISH_RE.search(title) or _EXPLICIT_JAPANESE_ENGLISH_RE.search(evidence):
        return "", "", "explicit_non_japanese_language"
    # Material variant claims in the current product evidence stay blocking.
    if native._SENSITIVE_RE.search(evidence):
        return "", "", "sensitive_variant_unproven"

    full_number, number_reason = _full_number_from_evidence(evidence)
    if not full_number:
        return "", "", number_reason
    set_code, set_reason = _set_code_from_evidence(evidence, full_number)
    if not set_code:
        return "", "", set_reason
    return full_number, set_code, "magi_native_detail_coordinate_parsed"


_INSTALLED = False


def install_global_marketplace_magi_detail_coordinate() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    # The native resolver intentionally looks up this helper at call time. Only
    # explicit current-product coordinate evidence changes; every downstream
    # TCGdex/name/set/localId/denominator/microvariant gate remains unchanged.
    native._preflight = preflight_with_detail_coordinate
    _INSTALLED = True
