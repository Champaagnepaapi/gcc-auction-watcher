"""Recover exact Magi cards when reviewed rarity makes identity deterministic.

Two fail-closed lanes live here so rarity normalization stays centralized:

1. Existing exact-set lane: an exact Japanese set name is already proved, but
   multiple same-name cards exist inside that set. A reviewed rarity token may
   select exactly one revalidated card.
2. Missing-set lane: the listing has no provable set/collector coordinate, but
   an exact Japanese card-name token immediately precedes a reviewed rarity and
   that exact name+rarity resolves to exactly one card across TCGdex Japanese.

Reviewed provider normalization is deliberately narrow:
- standalone Magi ``R``  -> TCGdex ``Rare``;
- standalone Magi ``SR`` -> TCGdex ``Ultra Rare``;
- standalone Magi ``TR`` -> TCGdex ``Rare Holo``.

The TR mapping is accepted only through the same exact-name candidate search
and card-detail revalidation as the other reviewed rarities; it is not a
per-card alias. No fuzzy matching or translation is used. Provider errors,
missing official count, multiple candidates and all unreviewed rarity tokens
remain blocked.
"""
from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import quote

import japan_edge_hunter as japan
import v4_global_magi_registry_hardening as magi_hardening
import v4_global_marketplace_magi_japanese_native_identity as japanese_native
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_recovery_budget as recovery_budget
import v4_global_marketplace_magi_set_name_unique_card as set_unique
from v4_global_market_core import CommercialIdentity
import v4_global_retrieval_hardening_v3 as retrieval_v3


_EXPECTED_REASON = "target_catalog_unproven:TCGDEX_SET_NAME_CARD_NAME_AMBIGUOUS"
_EXPECTED_MISSING_SET_REASON = "japanese_set_name_unproven"
_RARITY_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(SAR|CSR|CHR|RRR|SR|AR|RR|UR|HR|TR|R)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_JP_NAME_AT_END_RE = re.compile(r"([ぁ-んァ-ヶ一-龯々ー・]+)\s*$")
_REVIEWED_RARITY_MAP = {
    "R": "Rare",
    "SR": "Ultra Rare",
    "TR": "Rare Holo",
}
_GENERIC_TITLE_LABELS = frozenset({"ポケモン", "ポケモンカード", "ポケモンカードゲーム"})
_MAX_GLOBAL_NAME_CANDIDATES = 8
_ORIGINAL_RESOLVER = None
_INSTALLED = False


def _provider_rarity(title: str) -> tuple[str, str]:
    matches = list(_RARITY_TOKEN_RE.finditer(str(title or "")))
    tokens = {match.group(1).upper() for match in matches}
    if len(tokens) != 1:
        return "", "magi_rarity_unproven" if not tokens else "magi_rarity_ambiguous"
    token = next(iter(tokens))
    rarity = _REVIEWED_RARITY_MAP.get(token, "")
    if not rarity:
        return "", "magi_rarity_mapping_unreviewed"
    return rarity, f"magi_rarity_exact:{token}"


def _exact_title_name_before_rarity(title: str) -> tuple[str, str]:
    """Return one exact Japanese token immediately before one reviewed rarity.

    This is intentionally a narrow retrieval key. It never becomes identity by
    itself; the TCGdex detail must return the exact same Japanese name and all
    material catalog coordinates before identity is emitted.
    """
    text = str(title or "")
    rarity_matches = list(_RARITY_TOKEN_RE.finditer(text))
    if len(rarity_matches) != 1:
        return "", "magi_name_rarity_position_ambiguous"
    rarity_match = rarity_matches[0]
    token = rarity_match.group(1).upper()
    if token not in _REVIEWED_RARITY_MAP:
        return "", "magi_rarity_mapping_unreviewed"
    name_match = _JP_NAME_AT_END_RE.search(text[: rarity_match.start()])
    if not name_match:
        return "", "magi_exact_name_before_rarity_unproven"
    name = name_match.group(1).strip()
    if not name or name in _GENERIC_TITLE_LABELS:
        return "", "magi_exact_name_before_rarity_unproven"
    return name, "magi_exact_name_before_rarity"


def _same_text(left: object, right: object) -> bool:
    return set_unique._same_text(left, right)


def _candidate_details_by_name_and_rarity(
    *,
    resolver: retrieval_v3.TCGdexJapaneseProofResolver,
    title: str,
    set_id: str,
    set_name: str,
    rarity: str,
) -> tuple[list[retrieval_v3.JapaneseCatalogProof], str]:
    status, payload = resolver._get(f"sets/{quote(set_id, safe='')}")
    if status == 0:
        return [], "TCGDEX_BUDGET_EXHAUSTED"
    if status != 200:
        return [], f"TCGDEX_SET_DETAIL_HTTP_{status}"
    set_detail = resolver._detail_payload(payload)
    if not isinstance(set_detail, Mapping):
        return [], "TCGDEX_SET_DETAIL_INVALID_PAYLOAD"

    catalog_set_id = str(set_detail.get("id") or "").strip()
    catalog_set_name = str(set_detail.get("name") or "").strip()
    official_count = set_unique._set_official_count(set_detail)
    cards = set_detail.get("cards")
    if (
        catalog_set_id.casefold() != set_id.casefold()
        or not _same_text(catalog_set_name, set_name)
        or not official_count
        or not isinstance(cards, list)
    ):
        return [], "TCGDEX_SET_DETAIL_CONFLICT"

    briefs: dict[str, Mapping[str, Any]] = {}
    for row in cards:
        if not isinstance(row, Mapping):
            continue
        card_id = str(row.get("id") or "").strip()
        local_id = str(row.get("localId") or "").strip()
        name = str(row.get("name") or "").strip()
        if not card_id or not local_id or not name:
            continue
        if magi_hardening._jp_contains(title, name):
            briefs[card_id] = row
    if len(briefs) < 2:
        return [], "TCGDEX_SAME_NAME_CANDIDATES_NOT_AMBIGUOUS"

    matching: list[retrieval_v3.JapaneseCatalogProof] = []
    for card_id, brief in briefs.items():
        status, detail_payload = resolver._get(f"cards/{quote(card_id, safe='')}")
        if status == 0:
            return [], "TCGDEX_BUDGET_EXHAUSTED"
        if status != 200:
            return [], f"TCGDEX_CARD_DETAIL_HTTP_{status}"
        card = resolver._detail_payload(detail_payload)
        if not isinstance(card, Mapping):
            return [], "TCGDEX_CARD_DETAIL_INVALID_PAYLOAD"

        detail_id = str(card.get("id") or "").strip()
        local_id = str(card.get("localId") or "").strip()
        name_ja = str(card.get("name") or "").strip()
        detail_rarity = str(card.get("rarity") or "").strip()
        card_set = card.get("set")
        if not isinstance(card_set, Mapping):
            return [], "TCGDEX_CARD_DETAIL_SET_MISSING"
        detail_set_id = str(card_set.get("id") or "").strip()
        detail_set_name = str(card_set.get("name") or "").strip()
        if (
            detail_id != card_id
            or local_id != str(brief.get("localId") or "").strip()
            or not _same_text(name_ja, brief.get("name"))
            or detail_set_id.casefold() != set_id.casefold()
            or not _same_text(detail_set_name, set_name)
        ):
            return [], "TCGDEX_CARD_DETAIL_CONFLICT"
        if detail_rarity != rarity:
            continue
        matching.append(
            retrieval_v3.JapaneseCatalogProof(
                status="EXACT",
                reason="TCGDEX_JA_EXACT_SET_NAME_RARITY_UNIQUE_CARD",
                card_id=card_id,
                set_id=detail_set_id,
                name_ja=name_ja,
                set_name_ja=detail_set_name,
                local_id=local_id,
                official_count=official_count,
            )
        )
    return matching, "TCGDEX_JA_EXACT_SET_NAME_RARITY_UNIQUE_CARD"


def _global_candidate_details_by_exact_name_and_rarity(
    *,
    resolver: retrieval_v3.TCGdexJapaneseProofResolver,
    exact_name: str,
    rarity: str,
) -> tuple[list[retrieval_v3.JapaneseCatalogProof], str]:
    """Globally revalidate one exact Japanese name + reviewed rarity.

    The API search is retrieval only. Every row is re-read through the exact
    card-detail endpoint and must reproduce ID/localId/name/set/official count
    plus rarity. This deliberately does not trust a missing-set Magi title to
    identify a set.
    """
    status, payload = resolver._get("cards", params={"name": f"eq:{exact_name}"})
    if status == 0:
        return [], "TCGDEX_BUDGET_EXHAUSTED"
    if status != 200:
        return [], f"TCGDEX_CARD_SEARCH_HTTP_{status}"
    rows = resolver._list_payload(payload)

    briefs: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        card_id = str(row.get("id") or "").strip()
        local_id = str(row.get("localId") or "").strip()
        name = str(row.get("name") or "").strip()
        if not card_id or not local_id or not name:
            continue
        if _same_text(name, exact_name):
            briefs[card_id] = row
    if not briefs:
        return [], "TCGDEX_EXACT_NAME_NOT_FOUND"
    if len(briefs) > _MAX_GLOBAL_NAME_CANDIDATES:
        return [], "TCGDEX_EXACT_NAME_TOO_MANY_CANDIDATES"

    matching: list[retrieval_v3.JapaneseCatalogProof] = []
    for card_id, brief in briefs.items():
        status, detail_payload = resolver._get(f"cards/{quote(card_id, safe='')}")
        if status == 0:
            return [], "TCGDEX_BUDGET_EXHAUSTED"
        if status != 200:
            return [], f"TCGDEX_CARD_DETAIL_HTTP_{status}"
        card = resolver._detail_payload(detail_payload)
        if not isinstance(card, Mapping):
            return [], "TCGDEX_CARD_DETAIL_INVALID_PAYLOAD"

        detail_id = str(card.get("id") or "").strip()
        local_id = str(card.get("localId") or "").strip()
        name_ja = str(card.get("name") or "").strip()
        detail_rarity = str(card.get("rarity") or "").strip()
        card_set = card.get("set")
        if not isinstance(card_set, Mapping):
            return [], "TCGDEX_CARD_DETAIL_SET_MISSING"
        set_id = str(card_set.get("id") or "").strip()
        set_name = str(card_set.get("name") or "").strip()
        official_count = retrieval_v3.TCGdexJapaneseProofResolver._official(card)
        if (
            detail_id != card_id
            or local_id != str(brief.get("localId") or "").strip()
            or not _same_text(name_ja, exact_name)
            or not set_id
            or not set_name
            or not official_count
        ):
            return [], "TCGDEX_CARD_DETAIL_CONFLICT"
        if detail_rarity != rarity:
            continue
        matching.append(
            retrieval_v3.JapaneseCatalogProof(
                status="EXACT",
                reason="TCGDEX_JA_EXACT_GLOBAL_NAME_RARITY_UNIQUE_CARD",
                card_id=card_id,
                set_id=set_id,
                name_ja=name_ja,
                set_name_ja=set_name,
                local_id=local_id,
                official_count=official_count,
            )
        )
    return matching, "TCGDEX_JA_EXACT_GLOBAL_NAME_RARITY_UNIQUE_CARD"


def _exact_resolution_from_proof(
    proof: retrieval_v3.JapaneseCatalogProof,
    *,
    rarity_reason: str,
    reason_prefix: str,
) -> native.MagiNativeResolution:
    if not proof.local_id or not proof.official_count:
        return native.MagiNativeResolution(
            "NO_MATCH",
            "tcgdex_derived_coordinate_incomplete",
            card_id=proof.card_id,
            set_id=proof.set_id,
        )
    full_number = f"{proof.local_id}/{proof.official_count}"
    set_label = japanese_native._resolver_set_label(proof, full_number=full_number)
    if not set_label:
        return native.MagiNativeResolution(
            "AMBIGUOUS",
            "tcgdex_native_set_label_ambiguous",
            card_id=proof.card_id,
            set_id=proof.set_id,
        )

    identity = CommercialIdentity(
        name=proof.name_ja,
        set_name=set_label,
        number=full_number,
        language="ja",
        grader="PSA",
        grade="10",
    )
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return native.MagiNativeResolution(
            "NO_MATCH",
            "commercial_identity_incomplete",
            card_id=proof.card_id,
            set_id=proof.set_id,
        )
    return native.MagiNativeResolution(
        "EXACT",
        f"{reason_prefix}+{rarity_reason}",
        identity=identity,
        card_id=proof.card_id,
        set_id=proof.set_id,
    )


def _recover_missing_set_global_name_rarity(
    ask: japan.Ask,
    original: native.MagiNativeResolution,
    *,
    resolver: retrieval_v3.TCGdexJapaneseProofResolver,
) -> native.MagiNativeResolution:
    if original.status != "NO_MATCH" or original.reason != _EXPECTED_MISSING_SET_REASON:
        return original

    title = japan.current_text(ask.title)
    rarity, rarity_reason = _provider_rarity(title)
    if not rarity:
        return original
    exact_name, _name_reason = _exact_title_name_before_rarity(title)
    if not exact_name:
        return original

    matches, proof_reason = _global_candidate_details_by_exact_name_and_rarity(
        resolver=resolver,
        exact_name=exact_name,
        rarity=rarity,
    )
    if len(matches) != 1:
        status = set_unique._resolution_status(proof_reason)
        if len(matches) > 1:
            status = "AMBIGUOUS"
            proof_reason = "TCGDEX_GLOBAL_NAME_RARITY_CARD_AMBIGUOUS"
        return native.MagiNativeResolution(status, f"target_catalog_unproven:{proof_reason}")

    return _exact_resolution_from_proof(
        matches[0],
        rarity_reason=rarity_reason,
        reason_prefix="MAGI_NATIVE_TCGDEX_JA_EXACT_GLOBAL_NAME_RARITY_UNIQUE_CARD",
    )


def recover_set_name_rarity_unique_card_resolution(
    ask: japan.Ask,
    original: native.MagiNativeResolution,
    *,
    resolver: retrieval_v3.TCGdexJapaneseProofResolver,
) -> native.MagiNativeResolution:
    missing_set = _recover_missing_set_global_name_rarity(
        ask,
        original,
        resolver=resolver,
    )
    if missing_set is not original:
        return missing_set

    if original.status != "AMBIGUOUS" or original.reason != _EXPECTED_REASON:
        return original

    title = japan.current_text(ask.title)
    rarity, rarity_reason = _provider_rarity(title)
    if not rarity:
        return native.MagiNativeResolution("AMBIGUOUS", rarity_reason)

    set_name, set_id, set_reason = set_unique._catalog_set_name_in_title(
        resolver=resolver,
        title=title,
    )
    if not set_name or not set_id:
        status = set_unique._resolution_status(set_reason)
        return native.MagiNativeResolution(status, set_reason)

    matches, proof_reason = _candidate_details_by_name_and_rarity(
        resolver=resolver,
        title=title,
        set_id=set_id,
        set_name=set_name,
        rarity=rarity,
    )
    if len(matches) != 1:
        status = set_unique._resolution_status(proof_reason)
        if len(matches) > 1:
            status = "AMBIGUOUS"
            proof_reason = "TCGDEX_SET_NAME_RARITY_CARD_AMBIGUOUS"
        return native.MagiNativeResolution(status, f"target_catalog_unproven:{proof_reason}")

    return _exact_resolution_from_proof(
        matches[0],
        rarity_reason=rarity_reason,
        reason_prefix="MAGI_NATIVE_TCGDEX_JA_EXACT_SET_NAME_RARITY_UNIQUE_CARD",
    )


def _resolve_with_set_name_rarity_unique_card(ask, **kwargs):
    assert _ORIGINAL_RESOLVER is not None
    original = _ORIGINAL_RESOLVER(ask, **kwargs)
    resolver = recovery_budget.active_recovery_resolver(kwargs["resolver"])
    return recover_set_name_rarity_unique_card_resolution(
        ask,
        original,
        resolver=resolver,
    )


def install_global_marketplace_magi_set_name_rarity_unique_card() -> None:
    global _ORIGINAL_RESOLVER, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = native.resolve_magi_native_identity
    native.resolve_magi_native_identity = _resolve_with_set_name_rarity_unique_card
    _INSTALLED = True
