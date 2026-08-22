"""Fanatics Japanese cross-locale TCGdex recovery for the Global lane.

Fanatics often renders Japanese cards with romanized/English card names while
TCGdex's `ja` projection exposes Japanese names. This module does not translate
or fuzzy-match. It proves the provider name against TCGdex's Indonesian
projection (which shares the same immutable card IDs/set coordinates), then
requires the identical card ID/coordinate to exist in the Japanese projection.

The fallback runs only after the normal exact resolver fails, only for explicit
Japanese Fanatics titles, and stays bounded/fail-closed.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Callable, Mapping, Optional
from urllib.parse import quote

import v4_canonical_multimarket as multimarket
import v4_global_fanatics_native_identity as v1
import v4_global_marketplace_fanatics_native_v2 as v2
import v4_global_marketplace_fanatics_native_v3 as v3
import v4_tcgdex_generalized_coordinate_recovery as generalized
from v4_global_market_core import CommercialIdentity


_SET_CODE_RE = re.compile(
    r"^(?:[A-Za-z]{1,5}\d+[A-Za-z0-9-]*|[A-Za-z]{1,5}-P)$",
    re.IGNORECASE,
)
_MAX_ALIAS_NAMES = 4
_CROSS_LOCALE_NAME_LANGUAGE = "id"
_ORIGINAL_RESOLVER = None


def _set_payload(card: Mapping[str, Any]) -> Mapping[str, Any]:
    value = card.get("set")
    return value if isinstance(value, Mapping) else {}


def _card_coordinate_ok(
    card: Mapping[str, Any],
    *,
    set_id: str = "",
    local_id: str,
) -> bool:
    card_id = str(card.get("id") or "").strip()
    observed_local = str(card.get("localId") or "").strip()
    set_payload = _set_payload(card)
    observed_set = str(set_payload.get("id") or "").strip()
    if not card_id or not observed_local or not observed_set:
        return False
    if set_id and observed_set.casefold() != set_id.casefold():
        return False
    return generalized._same_local_id(observed_local, local_id)


def _fetch_set_localid(
    language: str,
    set_id: str,
    local_id: str,
    *,
    json_get: Callable[..., tuple[int, object, Mapping[str, str]]],
) -> tuple[Optional[Mapping[str, Any]], str]:
    for candidate in generalized._reference_candidates(local_id):
        try:
            status, payload, _ = json_get(
                f"{multimarket.TCGDEX_BASE_URL}/{language}/sets/"
                f"{quote(set_id, safe='')}/{quote(candidate, safe='')}",
                timeout=multimarket.TCGDEX_TIMEOUT_SECONDS,
            )
        except Exception as error:
            return None, f"tcgdex_cross_locale_{type(error).__name__.casefold()}"
        if status == 404:
            continue
        if status != 200:
            if generalized._transient_status(status):
                return None, f"tcgdex_cross_locale_transient_http_{status}"
            return None, f"tcgdex_cross_locale_http_{status}"
        card = multimarket._extract_single_payload(payload)
        if not isinstance(card, Mapping):
            return None, "tcgdex_cross_locale_invalid_payload"
        if not _card_coordinate_ok(card, set_id=set_id, local_id=local_id):
            return None, "tcgdex_cross_locale_coordinate_conflict"
        return card, "ok"
    return None, "not_found"


def _search_unique_alias(
    name: str,
    local_id: str,
    *,
    json_get: Callable[..., tuple[int, object, Mapping[str, str]]],
) -> tuple[Optional[Mapping[str, Any]], str]:
    briefs_by_id: dict[str, Mapping[str, Any]] = {}
    for candidate in generalized._reference_candidates(local_id):
        try:
            status, payload, _ = json_get(
                f"{multimarket.TCGDEX_BASE_URL}/{_CROSS_LOCALE_NAME_LANGUAGE}/cards",
                params={"name": f"eq:{name}", "localId": f"eq:{candidate}"},
                timeout=multimarket.TCGDEX_TIMEOUT_SECONDS,
            )
        except Exception as error:
            return None, f"tcgdex_cross_locale_{type(error).__name__.casefold()}"
        if status != 200:
            if generalized._transient_status(status):
                return None, f"tcgdex_cross_locale_transient_http_{status}"
            return None, f"tcgdex_cross_locale_http_{status}"
        for brief in multimarket._extract_list_payload(payload):
            card_id = str(brief.get("id") or "").strip()
            if card_id:
                briefs_by_id[card_id] = brief
    if not briefs_by_id:
        return None, "not_found"
    if len(briefs_by_id) != 1:
        return None, "ambiguous"

    card_id = next(iter(briefs_by_id))
    try:
        status, payload, _ = json_get(
            f"{multimarket.TCGDEX_BASE_URL}/{_CROSS_LOCALE_NAME_LANGUAGE}/cards/"
            f"{quote(card_id, safe='')}",
            timeout=multimarket.TCGDEX_TIMEOUT_SECONDS,
        )
    except Exception as error:
        return None, f"tcgdex_cross_locale_{type(error).__name__.casefold()}"
    if status != 200:
        if generalized._transient_status(status):
            return None, f"tcgdex_cross_locale_transient_http_{status}"
        return None, f"tcgdex_cross_locale_http_{status}"
    card = multimarket._extract_single_payload(payload)
    if not isinstance(card, Mapping):
        return None, "tcgdex_cross_locale_invalid_payload"
    if not _card_coordinate_ok(card, local_id=local_id):
        return None, "tcgdex_cross_locale_coordinate_conflict"
    if v1._norm(card.get("name")) != v1._norm(name):
        return None, "tcgdex_cross_locale_name_conflict"
    return card, "ok"


def _fetch_japanese_same_card(
    alias_card: Mapping[str, Any],
    *,
    local_id: str,
    json_get: Callable[..., tuple[int, object, Mapping[str, str]]],
) -> tuple[Optional[Mapping[str, Any]], str]:
    card_id = str(alias_card.get("id") or "").strip()
    set_id = str(_set_payload(alias_card).get("id") or "").strip()
    if not card_id or not set_id:
        return None, "tcgdex_cross_locale_coordinate_unproven"
    try:
        status, payload, _ = json_get(
            f"{multimarket.TCGDEX_BASE_URL}/ja/cards/{quote(card_id, safe='')}",
            timeout=multimarket.TCGDEX_TIMEOUT_SECONDS,
        )
    except Exception as error:
        return None, f"tcgdex_cross_locale_{type(error).__name__.casefold()}"
    if status != 200:
        if generalized._transient_status(status):
            return None, f"tcgdex_cross_locale_transient_http_{status}"
        return None, f"tcgdex_cross_locale_http_{status}"
    card = multimarket._extract_single_payload(payload)
    if not isinstance(card, Mapping):
        return None, "tcgdex_cross_locale_invalid_payload"
    if str(card.get("id") or "").strip() != card_id:
        return None, "tcgdex_cross_locale_card_id_conflict"
    if not _card_coordinate_ok(card, set_id=set_id, local_id=local_id):
        return None, "tcgdex_cross_locale_coordinate_conflict"
    return card, "ok"


def _full_number(alias_card: Mapping[str, Any], local_id: str) -> str:
    normalized_local = v1._norm_local(local_id)
    counts = _set_payload(alias_card).get("cardCount")
    if isinstance(counts, Mapping):
        official = counts.get("official")
        if official is not None and str(official).strip():
            return f"{normalized_local}/{v1._norm_local(official)}"
    return normalized_local


def _identity_from_cross_locale(
    coordinate: v1.FanaticsNativeCoordinate,
    alias_card: Mapping[str, Any],
    japanese_card: Mapping[str, Any],
    *,
    title: str,
    proof_text: str,
    reason: str,
) -> tuple[Optional[CommercialIdentity], str]:
    if coordinate.language_code != "ja":
        return None, "tcgdex_cross_locale_language_not_japanese"
    if v1._norm(alias_card.get("name")) != v1._norm(coordinate.name):
        return None, "tcgdex_cross_locale_name_conflict"
    if str(alias_card.get("id") or "").strip() != str(japanese_card.get("id") or "").strip():
        return None, "tcgdex_cross_locale_card_id_conflict"

    full_number = _full_number(alias_card, coordinate.local_id)
    exposed = v2._exposed_collector_numbers(f"{title}\n{proof_text}")
    if exposed and v1._norm_full_number(full_number) not in exposed:
        return None, "conflicting_full_fraction"

    set_name = str(_set_payload(alias_card).get("name") or "").strip()
    if not set_name:
        set_name = coordinate.set_name
    identity = CommercialIdentity(
        name=coordinate.name,
        set_name=set_name,
        number=full_number,
        language="ja",
        grader="PSA",
        grade=coordinate.grade,
        edition=coordinate.edition,
        finish=coordinate.finish,
        variant=coordinate.variant,
    )
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return None, "commercial_identity_incomplete"
    return identity, reason


def resolve_fanatics_cross_locale_identity(
    title: str,
    *,
    proof_text: str = "",
    json_get: Optional[Callable[..., tuple[int, object, Mapping[str, str]]]] = None,
) -> v1.FanaticsNativeResolution:
    """Recover explicit Japanese Fanatics titles without translating card names."""
    json_get = json_get or multimarket._json_get
    candidates, parse_reason = v3._flexible_candidates(title)
    candidates = [candidate for candidate in candidates if candidate.language_code == "ja"]
    if not candidates:
        return v1.FanaticsNativeResolution("NO_MATCH", parse_reason)

    exact: dict[str, tuple[CommercialIdentity, v1.FanaticsNativeCoordinate, str]] = {}
    errors: Counter[str] = Counter()

    # Fast deterministic path: provider exposes the exact TCGdex-style set code.
    for coordinate in candidates:
        set_id = coordinate.set_name.strip()
        if not _SET_CODE_RE.fullmatch(set_id):
            continue
        alias_card, alias_status = _fetch_set_localid(
            _CROSS_LOCALE_NAME_LANGUAGE,
            set_id,
            coordinate.local_id,
            json_get=json_get,
        )
        if alias_card is None:
            if alias_status not in {"not_found"}:
                errors[alias_status] += 1
            continue
        if v1._norm(alias_card.get("name")) != v1._norm(coordinate.name):
            continue
        japanese_card, ja_status = _fetch_japanese_same_card(
            alias_card,
            local_id=coordinate.local_id,
            json_get=json_get,
        )
        if japanese_card is None:
            if ja_status not in {"not_found"}:
                errors[ja_status] += 1
            continue
        identity, reason = _identity_from_cross_locale(
            coordinate,
            alias_card,
            japanese_card,
            title=title,
            proof_text=proof_text,
            reason="FANATICS_TCGDEX_CROSS_LOCALE_SET_LOCALID_EXACT",
        )
        if identity is not None:
            exact[identity.strict_key] = (identity, coordinate, reason)

    # Generic fallback: exact Indonesian alias + localId must be globally unique,
    # then the identical card ID/coordinate must exist in Japanese TCGdex.
    if not exact:
        seen_names: set[str] = set()
        checked = 0
        for coordinate in candidates:
            name_key = v1._norm(coordinate.name)
            if not name_key or name_key in seen_names:
                continue
            seen_names.add(name_key)
            checked += 1
            if checked > _MAX_ALIAS_NAMES:
                break
            alias_card, alias_status = _search_unique_alias(
                coordinate.name,
                coordinate.local_id,
                json_get=json_get,
            )
            if alias_card is None:
                if alias_status == "ambiguous":
                    errors["tcgdex_cross_locale_alias_ambiguous"] += 1
                elif alias_status != "not_found":
                    errors[alias_status] += 1
                continue
            japanese_card, ja_status = _fetch_japanese_same_card(
                alias_card,
                local_id=coordinate.local_id,
                json_get=json_get,
            )
            if japanese_card is None:
                if ja_status != "not_found":
                    errors[ja_status] += 1
                continue
            identity, reason = _identity_from_cross_locale(
                coordinate,
                alias_card,
                japanese_card,
                title=title,
                proof_text=proof_text,
                reason="FANATICS_TCGDEX_CROSS_LOCALE_UNIQUE_NAME_LOCALID",
            )
            if identity is not None:
                exact[identity.strict_key] = (identity, coordinate, reason)

    if len(exact) > 1:
        return v1.FanaticsNativeResolution(
            "AMBIGUOUS", "multiple_exact_tcgdex_cross_locale_candidates"
        )
    if len(exact) == 1:
        identity, coordinate, reason = next(iter(exact.values()))
        return v1.FanaticsNativeResolution(
            "EXACT", reason, coordinate=coordinate, identity=identity
        )
    if errors:
        return v1.FanaticsNativeResolution(
            "ERROR", errors.most_common(1)[0][0], coordinate=candidates[0]
        )
    return v1.FanaticsNativeResolution(
        "NO_MATCH", "tcgdex_cross_locale_no_exact", coordinate=candidates[0]
    )


def resolve_fanatics_native_identity_with_cross_locale(
    title: str,
    *,
    proof_text: str = "",
    resolver: Callable[[Any], multimarket.CanonicalCard] = multimarket.resolve_tcgdex_card,
) -> v1.FanaticsNativeResolution:
    assert _ORIGINAL_RESOLVER is not None
    original = _ORIGINAL_RESOLVER(title, proof_text=proof_text, resolver=resolver)
    if original.status not in {"NO_MATCH", "AMBIGUOUS"}:
        return original
    recovered = resolve_fanatics_cross_locale_identity(title, proof_text=proof_text)
    if recovered.status == "EXACT":
        return recovered
    if recovered.status == "ERROR":
        return recovered
    return original


def install_global_marketplace_fanatics_cross_locale() -> None:
    global _ORIGINAL_RESOLVER
    current = v3.resolve_fanatics_native_identity_v3
    if getattr(current, "_fanatics_cross_locale_installed", False):
        v3.install_global_marketplace_fanatics_native_v3()
        return
    _ORIGINAL_RESOLVER = current
    resolve_fanatics_native_identity_with_cross_locale._fanatics_cross_locale_installed = True  # type: ignore[attr-defined]
    v3.resolve_fanatics_native_identity_v3 = resolve_fanatics_native_identity_with_cross_locale
    v3.install_global_marketplace_fanatics_native_v3()
