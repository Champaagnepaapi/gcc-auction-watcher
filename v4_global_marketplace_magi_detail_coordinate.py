"""Deterministic Magi detail-evidence coordinate recovery.

The Magi detail fetch already keeps the current product body. Some public Magi
listings omit the collector fraction or bracketed set code from ``page.title()``
while exposing an exact coordinate such as ``SV8a 209/187`` in the current
product detail. This layer allows that explicit product evidence to feed the
existing Magi-native TCGdex proof without guessing or fuzzy matching.
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
_ADJACENT_SET_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9.-])([A-Za-z][A-Za-z0-9.-]{1,12})[ \t]*(?:[\[{(][ \t]*)?$"
)
_PREFIXED_LOCAL_RE = re.compile(r"^([A-Z]{2,6})(\d{1,4})/(\d+)$", re.I)
_NON_SET_PREFIXES = {
    "AR",
    "SAR",
    "SR",
    "RR",
    "RRR",
    "UR",
    "HR",
    "CSR",
    "CHR",
    "TR",
}


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


def _adjacent_set_codes(text: str, full_number: str) -> set[str]:
    """Return set-id shaped tokens immediately preceding the proven fraction.

    Magi commonly renders ``... SAR SV8a 209/187 ...`` without brackets. Only
    the token immediately adjacent to the *same already-proven full fraction*
    may participate. A rarity token such as ``SAR`` is rejected by the existing
    strict set-id grammar, and a set-looking token elsewhere on the page is not
    considered.
    """
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    output: set[str] = set()
    for match in japan.CARD_RE.finditer(normalized.upper()):
        if japan.number(match.group(0)) != full_number:
            continue
        prefix = normalized[max(0, match.start() - 32) : match.start()]
        token_match = _ADJACENT_SET_TOKEN_RE.search(prefix)
        if token_match is None:
            continue
        candidate = token_match.group(1).strip()
        if native._SET_ID_RE.fullmatch(candidate):
            output.add(candidate)
    return output


def _set_code_from_evidence(text: str, full_number: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    bracket_codes = {
        match.group(1).strip()
        for match in retrieval_v3.MAGI_SET_CODE_RE.finditer(normalized)
        if match.group(1).strip()
    }
    adjacent_codes = _adjacent_set_codes(normalized, full_number)
    explicit_codes = bracket_codes | adjacent_codes
    if len(explicit_codes) > 1:
        return "", "set_code_ambiguous"
    if len(explicit_codes) == 1:
        code = next(iter(explicit_codes))
        reason = "explicit_set_code_detail" if code in bracket_codes else "adjacent_set_code_detail"
        return code, reason

    if "/" in full_number:
        denominator = full_number.split("/", 1)[1]
        if not denominator.isdigit() and native._SET_ID_RE.fullmatch(denominator):
            return denominator, "intrinsic_promo_set_code"
    return "", "set_code_unproven"


def _prefixed_local_coordinate(text: str, full_number: str) -> tuple[str, str, str]:
    """Split provider notation like ``CLK003/032`` only with independent prefix proof.

    Some Magi Classic listings fuse a letter-only set namespace into the printed
    localId while also exposing the same namespace as a standalone label, e.g.
    ``(CLK) PROMO CLK003/032``.  The standalone repetition is mandatory so an
    arbitrary alphanumeric localId cannot manufacture a set. Known rarity tokens
    are explicitly excluded. Downstream TCGdex set/localId/denominator/name proof
    remains mandatory.
    """
    match = _PREFIXED_LOCAL_RE.fullmatch(str(full_number or "").upper())
    if match is None:
        return "", "", "prefixed_local_unproven"
    prefix, local, denominator = match.groups()
    prefix = prefix.upper()
    if prefix in _NON_SET_PREFIXES:
        return "", "", "prefixed_local_rarity_token"

    normalized = unicodedata.normalize("NFKC", str(text or "")).upper()
    standalone = re.compile(rf"(?<![A-Z0-9]){re.escape(prefix)}(?![A-Z0-9])")
    if standalone.search(normalized) is None:
        return "", "", "prefixed_local_set_label_unproven"

    canonical = japan.number(f"{local}/{denominator}")
    if not canonical:
        return "", "", "prefixed_local_number_unproven"
    return canonical, prefix, "prefixed_local_set_code_detail"


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
    if not set_code and set_reason == "set_code_unproven":
        canonical_number, prefixed_set, _ = _prefixed_local_coordinate(evidence, full_number)
        if canonical_number and prefixed_set:
            full_number, set_code = canonical_number, prefixed_set
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
