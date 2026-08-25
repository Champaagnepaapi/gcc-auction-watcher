"""Recover one vintage Magi card from exact name + printed Pokédex marker.

This fallback is deliberately narrow and fail-closed. It runs only after the
normal Magi path has proved that the Japanese set name is absent. A candidate is
eligible only when the title exposes the classic ``LV.xx`` + ``No.xxx`` pattern
and one leading Japanese card name after the PSA10 marker.

TCGdex must then prove that exact Japanese name is globally unique, the detailed
card reproduces the same id/localId/name, its ``dexId`` contains the printed
``No.`` value, and its set exposes a numeric official card count. The collector
coordinate is derived only from that revalidated TCGdex detail.

No fuzzy matching, translation, event alias, rarity inference or per-card
exception is used. Multiple same-name cards remain AMBIGUOUS. The existing
scan-scoped recovery resolver/budget is reused unchanged.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping
from urllib.parse import quote

import japan_edge_hunter as japan
import v4_global_marketplace_magi_japanese_native_identity as japanese_native
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_recovery_budget as recovery_budget
from v4_global_market_core import CommercialIdentity
import v4_global_retrieval_hardening_v3 as retrieval_v3


_EXPECTED_REASON = "japanese_set_name_unproven"
_LV_RE = re.compile(r"\bLV\.?\s*(\d{1,3})(?!\d)", re.IGNORECASE)
_NO_RE = re.compile(r"\bNO\.?\s*(\d{1,4})(?!\d)", re.IGNORECASE)
_LEADING_JP_RE = re.compile(r"^[ぁ-んァ-ヶ一-龯々ー・]{2,}")
_LEFT_TRIM_RE = re.compile(r"^[\s\[\]【】()（）<>〈〉:：・/_-]+")
_GENERIC_PREFIXES = ("ポケモンカードゲーム", "ポケモンカード")
_ORIGINAL_RESOLVER = None
_INSTALLED = False


def _same_text(left: object, right: object) -> bool:
    return unicodedata.normalize("NFKC", str(left or "")).strip() == unicodedata.normalize(
        "NFKC", str(right or "")
    ).strip()


def _vintage_markers(title: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", japan.current_text(title))
    levels = {match.group(1) for match in _LV_RE.finditer(normalized)}
    dex_numbers = {match.group(1) for match in _NO_RE.finditer(normalized)}
    if len(levels) != 1 or len(dex_numbers) != 1:
        return "", "vintage_lv_no_markers_unproven"
    return next(iter(dex_numbers)), "vintage_lv_no_markers_exact"


def _leading_exact_japanese_name(title: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", japan.current_text(title))
    psa = retrieval_v3.PSA10_RE.search(normalized)
    if psa is None:
        return "", "psa10_unproven"
    tail = normalized[psa.end() :]
    tail = _LEFT_TRIM_RE.sub("", tail)
    changed = True
    while changed:
        changed = False
        for prefix in _GENERIC_PREFIXES:
            if tail.startswith(prefix):
                tail = tail[len(prefix) :]
                tail = _LEFT_TRIM_RE.sub("", tail)
                changed = True
                break
    match = _LEADING_JP_RE.match(tail)
    if match is None:
        return "", "vintage_exact_name_unproven"
    name = match.group(0).strip()
    if name in _GENERIC_PREFIXES:
        return "", "vintage_exact_name_unproven"
    return name, "vintage_exact_name_in_title"


def _dex_ids(card: Mapping[str, Any]) -> set[str]:
    raw = card.get("dexId")
    values = raw if isinstance(raw, list) else [raw]
    output: set[str] = set()
    for value in values:
        try:
            output.add(str(int(str(value).strip())))
        except (TypeError, ValueError):
            continue
    return output


def _unique_exact_name_proof(
    *,
    resolver: retrieval_v3.TCGdexJapaneseProofResolver,
    exact_name: str,
    dex_number: str,
) -> tuple[retrieval_v3.JapaneseCatalogProof | None, str]:
    status, payload = resolver._get("cards", params={"name": f"eq:{exact_name}"})
    if status == 0:
        return None, "TCGDEX_BUDGET_EXHAUSTED"
    if status != 200:
        return None, f"TCGDEX_CARD_SEARCH_HTTP_{status}"

    briefs: dict[str, Mapping[str, Any]] = {}
    for row in resolver._list_payload(payload):
        card_id = str(row.get("id") or "").strip()
        local_id = str(row.get("localId") or "").strip()
        name = str(row.get("name") or "").strip()
        if not card_id or not local_id or not _same_text(name, exact_name):
            continue
        briefs[card_id] = row
    if not briefs:
        return None, "TCGDEX_EXACT_NAME_NOT_FOUND"
    if len(briefs) != 1:
        return None, "TCGDEX_GLOBAL_EXACT_NAME_AMBIGUOUS"

    card_id, brief = next(iter(briefs.items()))
    status, detail_payload = resolver._get(f"cards/{quote(card_id, safe='')}")
    if status == 0:
        return None, "TCGDEX_BUDGET_EXHAUSTED"
    if status != 200:
        return None, f"TCGDEX_CARD_DETAIL_HTTP_{status}"
    card = resolver._detail_payload(detail_payload)
    if not isinstance(card, Mapping):
        return None, "TCGDEX_CARD_DETAIL_INVALID_PAYLOAD"

    detail_id = str(card.get("id") or "").strip()
    local_id = str(card.get("localId") or "").strip()
    name_ja = str(card.get("name") or "").strip()
    card_set = card.get("set")
    if not isinstance(card_set, Mapping):
        return None, "TCGDEX_CARD_DETAIL_SET_MISSING"
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
        return None, "TCGDEX_CARD_DETAIL_CONFLICT"
    if str(int(dex_number)) not in _dex_ids(card):
        return None, "TCGDEX_PRINTED_DEX_NUMBER_CONFLICT"

    return retrieval_v3.JapaneseCatalogProof(
        status="EXACT",
        reason="TCGDEX_JA_GLOBAL_EXACT_NAME_UNIQUE_WITH_DEX",
        card_id=card_id,
        set_id=set_id,
        name_ja=name_ja,
        set_name_ja=set_name,
        local_id=local_id,
        official_count=official_count,
    ), "TCGDEX_JA_GLOBAL_EXACT_NAME_UNIQUE_WITH_DEX"


def _status_for_reason(reason: str) -> str:
    lowered = str(reason or "").casefold()
    if "budget" in lowered or "http_-1" in lowered or re.search(r"http_(?:408|425|429|5\d\d)", lowered):
        return "ERROR"
    if "ambiguous" in lowered or "conflict" in lowered:
        return "AMBIGUOUS"
    return "NO_MATCH"


def recover_vintage_name_unique_card_resolution(
    ask: japan.Ask,
    original: native.MagiNativeResolution,
    *,
    resolver: retrieval_v3.TCGdexJapaneseProofResolver,
) -> native.MagiNativeResolution:
    if original.status != "NO_MATCH" or original.reason != _EXPECTED_REASON:
        return original

    title = japan.current_text(ask.title)
    dex_number, _marker_reason = _vintage_markers(title)
    if not dex_number:
        return original
    exact_name, _name_reason = _leading_exact_japanese_name(title)
    if not exact_name:
        return original

    proof, proof_reason = _unique_exact_name_proof(
        resolver=resolver,
        exact_name=exact_name,
        dex_number=dex_number,
    )
    if proof is None:
        return native.MagiNativeResolution(
            _status_for_reason(proof_reason),
            f"target_catalog_unproven:{proof_reason}",
        )

    if not proof.local_id or not proof.official_count:
        return native.MagiNativeResolution(
            "NO_MATCH", "tcgdex_derived_coordinate_incomplete", card_id=proof.card_id, set_id=proof.set_id
        )
    full_number = f"{proof.local_id}/{proof.official_count}"
    set_label = japanese_native._resolver_set_label(proof, full_number=full_number)
    if not set_label:
        return native.MagiNativeResolution(
            "AMBIGUOUS", "tcgdex_native_set_label_ambiguous", card_id=proof.card_id, set_id=proof.set_id
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
            "NO_MATCH", "commercial_identity_incomplete", card_id=proof.card_id, set_id=proof.set_id
        )
    return native.MagiNativeResolution(
        "EXACT",
        "MAGI_NATIVE_TCGDEX_JA_GLOBAL_EXACT_NAME_UNIQUE_WITH_PRINTED_DEX",
        identity=identity,
        card_id=proof.card_id,
        set_id=proof.set_id,
    )


def _resolve_with_vintage_name_unique_card(ask, **kwargs):
    assert _ORIGINAL_RESOLVER is not None
    original = _ORIGINAL_RESOLVER(ask, **kwargs)
    resolver = recovery_budget.active_recovery_resolver(kwargs["resolver"])
    return recover_vintage_name_unique_card_resolution(
        ask,
        original,
        resolver=resolver,
    )


def install_global_marketplace_magi_vintage_name_unique_card() -> None:
    global _ORIGINAL_RESOLVER, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = native.resolve_magi_native_identity
    native.resolve_magi_native_identity = _resolve_with_vintage_name_unique_card
    _INSTALLED = True
