"""Recover Magi cards whose number is absent but exact Japanese set+name is proven.

This path is deliberately narrower than a name search. It runs only after the
normal Magi preflight reached ``collector_number_unproven`` and requires one
explicit Japanese set name in the product title (for example
``[旧裏第2弾/ポケモンジャングル]``). TCGdex must resolve that exact set and exactly
one card name from that set may occur in the current product title. The full
coordinate is then copied from that exact TCGdex card; it is never guessed from
Magi text.

Name-only listings, multiple matching cards, missing catalogue counts, provider
errors, and any sensitive-variant rejection remain fail-closed.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping
from urllib.parse import quote

import japan_edge_hunter as japan
import v4_global_marketplace_magi_japanese_native_identity as japanese_native
import v4_global_marketplace_magi_native_identity as native
from v4_global_market_core import CommercialIdentity
import v4_global_retrieval_hardening_v3 as retrieval_v3


_JP_SCRIPT_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_SET_BRACKET_RE = re.compile(r"\[([^\]/]{1,50})/([^\]]{2,100})\]")
_ORIGINAL_RESOLVER = None
_INSTALLED = False


def _explicit_japanese_set_name(title: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", japan.current_text(title))
    names = {
        match.group(2).strip()
        for match in _SET_BRACKET_RE.finditer(normalized)
        if match.group(2).strip() and _JP_SCRIPT_RE.search(match.group(2))
    }
    if not names:
        return "", "japanese_set_name_unproven"
    if len(names) != 1:
        return "", "japanese_set_name_ambiguous"
    return next(iter(names)), "explicit_japanese_set_name"


def _set_official_count(set_detail: Mapping[str, Any]) -> str:
    counts = set_detail.get("cardCount")
    if not isinstance(counts, Mapping):
        return ""
    value = counts.get("official")
    try:
        return str(int(str(value).strip()))
    except (TypeError, ValueError):
        return ""


def _same_text(left: object, right: object) -> bool:
    return unicodedata.normalize("NFKC", str(left or "")).strip() == unicodedata.normalize(
        "NFKC", str(right or "")
    ).strip()


def _fetch_unique_card_in_exact_set(
    *,
    resolver: retrieval_v3.TCGdexJapaneseProofResolver,
    title: str,
    set_name: str,
) -> tuple[retrieval_v3.JapaneseCatalogProof | None, str]:
    status, payload = resolver._get(f"sets/{quote(set_name, safe='')}")
    if status == 0:
        return None, "TCGDEX_BUDGET_EXHAUSTED"
    if status == 404:
        return None, "TCGDEX_SET_NAME_NOT_FOUND"
    if status != 200:
        return None, f"TCGDEX_SET_NAME_HTTP_{status}"

    set_detail = resolver._detail_payload(payload)
    if not isinstance(set_detail, Mapping):
        return None, "TCGDEX_SET_NAME_INVALID_PAYLOAD"
    set_id = str(set_detail.get("id") or "").strip()
    catalog_set_name = str(set_detail.get("name") or "").strip()
    official_count = _set_official_count(set_detail)
    cards = set_detail.get("cards")
    if not set_id or not catalog_set_name or not official_count or not isinstance(cards, list):
        return None, "TCGDEX_SET_NAME_INCOMPLETE"
    if not _same_text(catalog_set_name, set_name):
        return None, "TCGDEX_SET_NAME_CONFLICT"

    matches: dict[str, Mapping[str, Any]] = {}
    for row in cards:
        if not isinstance(row, Mapping):
            continue
        card_id = str(row.get("id") or "").strip()
        local_id = str(row.get("localId") or "").strip()
        name = str(row.get("name") or "").strip()
        if not card_id or not local_id or len(name) < 2 or not _JP_SCRIPT_RE.search(name):
            continue
        if japanese_native.magi_hardening._jp_contains(title, name):
            matches[card_id] = row

    if not matches:
        return None, "TCGDEX_SET_NAME_CARD_NAME_NOT_FOUND"
    if len(matches) != 1:
        return None, "TCGDEX_SET_NAME_CARD_NAME_AMBIGUOUS"

    brief = next(iter(matches.values()))
    card_id = str(brief.get("id") or "").strip()
    status, detail_payload = resolver._get(f"cards/{quote(card_id, safe='')}")
    if status == 0:
        return None, "TCGDEX_BUDGET_EXHAUSTED"
    if status != 200:
        return None, f"TCGDEX_CARD_DETAIL_HTTP_{status}"
    card = resolver._detail_payload(detail_payload)
    if not isinstance(card, Mapping):
        return None, "TCGDEX_CARD_DETAIL_INVALID_PAYLOAD"

    local_id = str(card.get("localId") or "").strip()
    name_ja = str(card.get("name") or "").strip()
    card_set = card.get("set")
    if not isinstance(card_set, Mapping):
        return None, "TCGDEX_CARD_DETAIL_SET_MISSING"
    detail_set_id = str(card_set.get("id") or "").strip()
    detail_set_name = str(card_set.get("name") or "").strip()
    if (
        card_id != str(card.get("id") or "").strip()
        or not local_id
        or local_id != str(brief.get("localId") or "").strip()
        or not _same_text(name_ja, brief.get("name"))
        or detail_set_id != set_id
        or not _same_text(detail_set_name, set_name)
    ):
        return None, "TCGDEX_CARD_DETAIL_CONFLICT"

    return retrieval_v3.JapaneseCatalogProof(
        status="EXACT",
        reason="TCGDEX_JA_EXACT_SET_NAME_UNIQUE_CARD",
        card_id=card_id,
        set_id=set_id,
        name_ja=name_ja,
        set_name_ja=detail_set_name,
        local_id=local_id,
        official_count=official_count,
    ), "TCGDEX_JA_EXACT_SET_NAME_UNIQUE_CARD"


def recover_set_name_unique_card_resolution(
    ask: japan.Ask,
    original: native.MagiNativeResolution,
    *,
    resolver: retrieval_v3.TCGdexJapaneseProofResolver,
) -> native.MagiNativeResolution:
    if original.status != "NO_MATCH" or original.reason != "collector_number_unproven":
        return original

    title = japan.current_text(ask.title)
    set_name, set_reason = _explicit_japanese_set_name(title)
    if not set_name:
        return native.MagiNativeResolution("NO_MATCH", set_reason)

    proof, proof_reason = _fetch_unique_card_in_exact_set(
        resolver=resolver,
        title=title,
        set_name=set_name,
    )
    if proof is None:
        status = "ERROR" if "HTTP_-1" in proof_reason or "BUDGET" in proof_reason else (
            "AMBIGUOUS" if "AMBIGUOUS" in proof_reason else "NO_MATCH"
        )
        return native.MagiNativeResolution(status, f"target_catalog_unproven:{proof_reason}")

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
        "MAGI_NATIVE_TCGDEX_JA_EXACT_SET_NAME_UNIQUE_CARD_DERIVED_COORDINATE",
        identity=identity,
        card_id=proof.card_id,
        set_id=proof.set_id,
    )


def _resolve_with_set_name_unique_card(ask, **kwargs):
    assert _ORIGINAL_RESOLVER is not None
    original = _ORIGINAL_RESOLVER(ask, **kwargs)
    return recover_set_name_unique_card_resolution(
        ask,
        original,
        resolver=kwargs["resolver"],
    )


def install_global_marketplace_magi_set_name_unique_card() -> None:
    global _ORIGINAL_RESOLVER, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = native.resolve_magi_native_identity
    native.resolve_magi_native_identity = _resolve_with_set_name_unique_card
    _INSTALLED = True
