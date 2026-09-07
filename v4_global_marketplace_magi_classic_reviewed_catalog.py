"""Reviewed catalog-gap recovery for Japanese Pokemon Card Game Classic on Magi.

TCGdex currently lacks the CLL/CLK/CLF deck-coordinate projection used by
Magi. This module does not fuzzy-match or translate at runtime. It carries a
small reviewed immutable coordinate table whose card name + Japanese product
version + model code were independently verified against public KREAM product
pages on 2026-09-07.

Only exact Magi single-card titles that state ``Pokemon Card Game Classic``, one
supported model coordinate, the matching Japanese Pokemon name and PSA 10 may
use this fallback. Unknown coordinates remain blocked. The listing remains a
FIXED ASK; this module provides identity only and never sale evidence.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

import japan_edge_hunter as japan
import v4_global_marketplace_magi_native_identity as native
import v4_global_retrieval_hardening_v3 as retrieval_v3
from v4_global_market_core import CommercialIdentity


@dataclass(frozen=True)
class ReviewedClassicCard:
    model_code: str
    name_en: str
    name_ja: str
    provenance_url: str


# Public independent evidence: exact KREAM Japanese-version product + model code.
# CLL013/032 and CLL014/032 are deliberately absent until an independent source
# proves them; Magi itself is not used to bootstrap its own canonical identity.
_REVIEWED = {
    row.model_code: row
    for row in (
        ReviewedClassicCard("CLL001/032", "Charmander", "ヒトカゲ", "https://kream.co.kr/products/695798"),
        ReviewedClassicCard("CLL003/032", "Charizard", "リザードン", "https://kream.co.kr/products/695800"),
        ReviewedClassicCard("CLL008/032", "Pikachu", "ピカチュウ", "https://kream.co.kr/products/695805"),
        ReviewedClassicCard("CLL009/032", "Raichu", "ライチュウ", "https://www.kream.co.kr/products/695806"),
        ReviewedClassicCard("CLK003/032", "Blastoise", "カメックス", "https://kream.co.kr/products/695833"),
        ReviewedClassicCard("CLK006/032", "Magikarp", "コイキング", "https://kream.co.kr/products/695836"),
        ReviewedClassicCard("CLK007/032", "Gyarados", "ギャラドス", "https://kream.co.kr/products/695837"),
        ReviewedClassicCard("CLK014/032", "Mewtwo", "ミュウツー", "https://kream.co.kr/products/695844"),
        ReviewedClassicCard("CLF001/032", "Bulbasaur", "フシギダネ", "https://kream.co.kr/products/676242"),
        ReviewedClassicCard("CLF002/032", "Ivysaur", "フシギソウ", "https://kream.co.kr/products/676243"),
        ReviewedClassicCard("CLF003/032", "Venusaur", "フシギバナ", "https://kream.co.kr/products/676244"),
        ReviewedClassicCard("CLF015/032", "Chansey", "ラッキー", "https://kream.co.kr/products/676256"),
    )
}

_CLASSIC_RE = re.compile(r"ポケモンカードゲーム\s*Classic", re.I)
_MODEL_RE = re.compile(r"(?<![A-Z0-9])(?P<deck>CLL|CLK|CLF)\s*0*(?P<local>\d{1,3})\s*/\s*0*(?P<denom>\d{1,3})(?![A-Z0-9])", re.I)
_ORIGINAL_RESOLVER = None
_INSTALLED = False


def _compact(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).replace(" ", "")


def _model_codes(text: str) -> set[str]:
    output: set[str] = set()
    for match in _MODEL_RE.finditer(unicodedata.normalize("NFKC", str(text or ""))):
        output.add(f"{match.group('deck').upper()}{int(match.group('local')):03d}/{int(match.group('denom')):03d}")
    return output


def resolve_reviewed_classic_identity(ask: japan.Ask) -> native.MagiNativeResolution:
    title = japan.current_text(ask.title)
    current = japan.current_text("\n".join(value for value in (ask.title, ask.text) if value))
    if not _CLASSIC_RE.search(unicodedata.normalize("NFKC", title)):
        return native.MagiNativeResolution("NO_MATCH", "not_reviewed_classic")
    if japan.has_any(title, japan.AUCTION):
        return native.MagiNativeResolution("NO_MATCH", "ongoing_auction")
    if japan.has_any(title, japan.MULTI):
        return native.MagiNativeResolution("NO_MATCH", "multi_item_listing")
    if not retrieval_v3.SINGLE_CARD_RE.search(unicodedata.normalize("NFKC", title)):
        return native.MagiNativeResolution("NO_MATCH", "single_quantity_unproven")
    if not retrieval_v3.PSA10_RE.search(unicodedata.normalize("NFKC", current)):
        return native.MagiNativeResolution("NO_MATCH", "psa10_unproven")
    if native._EXPLICIT_ENGLISH_RE.search(current):
        return native.MagiNativeResolution("NO_MATCH", "explicit_non_japanese_language")
    if native._SENSITIVE_RE.search(current):
        return native.MagiNativeResolution("NO_MATCH", "sensitive_variant_unproven")

    codes = _model_codes(current)
    if len(codes) != 1:
        return native.MagiNativeResolution(
            "AMBIGUOUS" if codes else "NO_MATCH",
            "reviewed_classic_coordinate_ambiguous" if codes else "reviewed_classic_coordinate_unproven",
        )
    model_code = next(iter(codes))
    reviewed = _REVIEWED.get(model_code)
    if reviewed is None:
        return native.MagiNativeResolution("NO_MATCH", "reviewed_classic_coordinate_absent")

    # Magi itself must independently expose the Japanese Pokemon name; the
    # reviewed table supplies coordinate authority, not permission to ignore a
    # contradictory listing title.
    if _compact(reviewed.name_ja) not in _compact(current):
        return native.MagiNativeResolution("NO_MATCH", "reviewed_classic_japanese_name_unproven")

    identity = CommercialIdentity(
        name=reviewed.name_en,
        set_name="Pokemon Card Game Classic",
        number=model_code,
        language="ja",
        grader="PSA",
        grade="10",
    )
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return native.MagiNativeResolution("NO_MATCH", "commercial_identity_incomplete")
    return native.MagiNativeResolution(
        "EXACT",
        "MAGI_REVIEWED_CLASSIC_COORDINATE_EXACT",
        identity=identity,
        card_id=f"reviewed-classic:{model_code}",
        set_id=model_code[:3],
    )


def _resolve_with_reviewed_classic(ask, **kwargs):
    assert _ORIGINAL_RESOLVER is not None
    reviewed = resolve_reviewed_classic_identity(ask)
    if reviewed.status == "EXACT":
        return reviewed
    # A title explicitly in Classic scope with an unknown/conflicting reviewed
    # coordinate stays blocked; do not spend TCGdex budget trying to reinterpret
    # the same catalog gap as a different set.
    if reviewed.reason != "not_reviewed_classic":
        return reviewed
    return _ORIGINAL_RESOLVER(ask, **kwargs)


def install_global_marketplace_magi_classic_reviewed_catalog() -> None:
    global _ORIGINAL_RESOLVER, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = native.resolve_magi_native_identity
    native.resolve_magi_native_identity = _resolve_with_reviewed_classic
    _INSTALLED = True
