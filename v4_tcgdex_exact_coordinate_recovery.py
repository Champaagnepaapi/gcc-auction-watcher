from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Mapping, Optional

import watcher
import v4_canonical_multimarket as canonical


# Source: tcgdex/cards-database commit af33c9ac882e2acfadffaf19e8083aa976d12983.
# This registry is intentionally tiny and exact. It only bridges GCC coordinates
# that are already proven enough to name one TCGdex set/localId deterministically.
_SOURCE_COMMIT = "af33c9ac882e2acfadffaf19e8083aa976d12983"


@dataclass(frozen=True)
class ExactCoordinateRecovery:
    language_code: str
    listing_set: str
    listing_number: str
    listing_name: str
    year: int
    tcgdex_set_id: str
    tcgdex_local_id: str
    tcgdex_official_count: int
    provenance: str


def _norm_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _norm_number(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lstrip("#")).upper()


def _key(
    language_code: str,
    listing_set: str,
    listing_number: str,
    listing_name: str,
    year: int,
) -> tuple[str, str, str, str, int]:
    return (
        str(language_code or "").strip().lower(),
        _norm_text(listing_set),
        _norm_number(listing_number),
        _norm_text(listing_name),
        int(year),
    )


_RECORDS = (
    ExactCoordinateRecovery(
        "ja",
        "Ruler of the Black Flame",
        "109/108",
        "Gloom",
        2023,
        "SV3",
        "109",
        108,
        "TCGdex SV3 / GCC exact coordinate bridge",
    ),
    ExactCoordinateRecovery(
        "ja",
        "VMAX Climax",
        "212/184",
        "Oranguru",
        2021,
        "S8b",
        "212",
        184,
        "TCGdex S8b / GCC exact coordinate bridge",
    ),
    ExactCoordinateRecovery(
        "ja",
        "Night Wanderer",
        "066/064",
        "Houndoom",
        2024,
        "SV6a",
        "066",
        64,
        "TCGdex SV6a / GCC exact coordinate bridge",
    ),
    ExactCoordinateRecovery(
        "ja",
        "Heat Wave Arena",
        "070/063",
        "Ethan's Typhlosion",
        2025,
        "SV9a",
        "070",
        63,
        "TCGdex SV9a / GCC exact coordinate bridge",
    ),
    ExactCoordinateRecovery(
        "ja",
        "Battle Partners",
        "102/100",
        "Articuno",
        2025,
        "SV9",
        "102",
        100,
        "TCGdex SV9 / GCC exact coordinate bridge",
    ),
    ExactCoordinateRecovery(
        "ja",
        "Legendary Shine Collection",
        "012/027",
        "Hoopa Ex",
        2015,
        "CP2",
        "012",
        27,
        "TCGdex CP2 / GCC exact coordinate bridge",
    ),
    ExactCoordinateRecovery(
        "ja",
        "151",
        "185/165",
        "Charizard Ex",
        2023,
        "SV2a",
        "185",
        165,
        "TCGdex SV2a / GCC exact coordinate bridge",
    ),
    ExactCoordinateRecovery(
        "ja",
        "Shiny Treasure ex",
        "254/190",
        "Kadabra",
        2023,
        "SV4a",
        "254",
        190,
        "TCGdex SV4a / GCC exact coordinate bridge",
    ),
    ExactCoordinateRecovery(
        "fr",
        "Tempête Argentée",
        "TG10/TG30",
        "Queulorior",
        2022,
        "swsh12tg",
        "TG10",
        30,
        "TCGdex Silver Tempest Trainer Gallery exact namespace bridge",
    ),
    ExactCoordinateRecovery(
        "fr",
        "Célébrations",
        "8/82",
        "Léviator Obscur Holo",
        2021,
        "cel25cc",
        "CC005",
        25,
        "TCGdex Celebrations Classic Collection exact reprint bridge",
    ),
)

_RECORDS_BY_KEY = {
    _key(
        record.language_code,
        record.listing_set,
        record.listing_number,
        record.listing_name,
        record.year,
    ): record
    for record in _RECORDS
}

_RECOVERY_CACHE: dict[tuple[str, str, str, str, int], canonical.CanonicalCard] = {}
_RECOVERY_NEGATIVE_CACHE: set[tuple[str, str, str, str, int]] = set()
_ORIGINAL_RESOLVER = None
_ORIGINAL_CLEAR_CACHE = None


def _record_for_lot(lot: watcher.Lot) -> tuple[Optional[ExactCoordinateRecovery], tuple[str, str, str, str, int]]:
    identity = watcher.extract_card_identity(lot)
    language_code = canonical._language_code(lot)
    listing_set = str(lot.card_set or identity.get("series") or "").strip()
    listing_number = str(lot.card_number or identity.get("ref") or "").strip()
    listing_name = str(identity.get("core") or "").strip()
    year_value = lot.year if lot.year is not None else identity.get("year")
    try:
        year = int(year_value)
    except (TypeError, ValueError):
        year = 0
    key = _key(language_code, listing_set, listing_number, listing_name, year)
    return _RECORDS_BY_KEY.get(key), key


def _set_count_matches(set_payload: Mapping[str, Any], expected: int) -> bool:
    counts = set_payload.get("cardCount")
    if not isinstance(counts, Mapping):
        return False
    observed = {str(value).strip() for value in (counts.get("official"), counts.get("total")) if value is not None}
    return str(int(expected)) in {str(int(value)) if value.isdigit() else value for value in observed}


def _local_id_matches(observed: Any, expected: str) -> bool:
    left = _norm_number(observed)
    right = _norm_number(expected)
    if left == right:
        return True
    if left.isdigit() and right.isdigit():
        return int(left) == int(right)
    return False


def _transient_status(status: int) -> bool:
    return status in {0, 408, 425, 429} or status >= 500


def _canonical_from_exact_coordinate(
    lot: watcher.Lot,
    record: ExactCoordinateRecovery,
    card: Mapping[str, Any],
) -> Optional[canonical.CanonicalCard]:
    card_id = str(card.get("id") or "").strip()
    local_id = str(card.get("localId") or "").strip()
    set_payload = card.get("set")
    if not card_id or not local_id or not isinstance(set_payload, Mapping):
        return None
    set_id = str(set_payload.get("id") or "").strip()
    set_name = str(set_payload.get("name") or "").strip()
    if set_id != record.tcgdex_set_id:
        return None
    if not _local_id_matches(local_id, record.tcgdex_local_id):
        return None
    if not _set_count_matches(set_payload, record.tcgdex_official_count):
        return None

    identity = watcher.extract_card_identity(lot)
    full_number = str(lot.card_number or identity.get("ref") or "").strip()
    return canonical.CanonicalCard(
        status="EXACT",
        card_id=card_id,
        set_id=set_id,
        set_name=set_name,
        local_id=local_id,
        full_number=full_number,
        name=str(card.get("name") or "").strip(),
        language_code=record.language_code,
        pricing=card.get("pricing") if isinstance(card.get("pricing"), Mapping) else {},
        variants=card.get("variants") if isinstance(card.get("variants"), Mapping) else {},
        reason=(
            f"TCGDEX_EXACT_COORDINATE_RECOVERY:{record.provenance}; "
            f"registry_source={_SOURCE_COMMIT}"
        ),
        unique_name_number=True,
    )


def _fetch_exact_coordinate(
    lot: watcher.Lot,
    record: ExactCoordinateRecovery,
) -> canonical.CanonicalCard | None:
    status, payload, _ = canonical._json_get(
        f"{canonical.TCGDEX_BASE_URL}/{record.language_code}/sets/"
        f"{record.tcgdex_set_id}/{record.tcgdex_local_id}",
        timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
    )
    if status != 200:
        if _transient_status(status):
            return canonical.CanonicalCard(
                "ERROR",
                reason=f"TCGdex exact-coordinate recovery transient HTTP {status}",
            )
        return None
    card = canonical._extract_single_payload(payload)
    if not isinstance(card, Mapping):
        return canonical.CanonicalCard(
            "ERROR",
            reason="TCGdex exact-coordinate recovery invalid payload",
        )
    return _canonical_from_exact_coordinate(lot, record, card)


def _reclassify_original_no_match(result: canonical.CanonicalCard) -> None:
    diagnostics = canonical._DIAGNOSTICS
    if diagnostics.tcgdex_no_match > 0:
        diagnostics.tcgdex_no_match -= 1
    if result.status == "EXACT":
        diagnostics.tcgdex_exact += 1
    elif result.status == "ERROR":
        diagnostics.tcgdex_error += 1


def _resolve_with_exact_coordinate_recovery(lot: watcher.Lot) -> canonical.CanonicalCard:
    assert _ORIGINAL_RESOLVER is not None
    record, key = _record_for_lot(lot)
    if record is None:
        return _ORIGINAL_RESOLVER(lot)

    cached = _RECOVERY_CACHE.get(key)
    if cached is not None:
        canonical._DIAGNOSTICS.tcgdex_exact += 1
        return cached
    if key in _RECOVERY_NEGATIVE_CACHE:
        return _ORIGINAL_RESOLVER(lot)

    original = _ORIGINAL_RESOLVER(lot)
    if original.status != "NO_MATCH":
        return original

    recovered = _fetch_exact_coordinate(lot, record)
    if recovered is None:
        _RECOVERY_NEGATIVE_CACHE.add(key)
        return original
    if recovered.status in {"EXACT", "ERROR"}:
        _reclassify_original_no_match(recovered)
    if recovered.status == "EXACT":
        _RECOVERY_CACHE[key] = recovered
    return recovered


def _clear_all_tcgdex_caches() -> None:
    _RECOVERY_CACHE.clear()
    _RECOVERY_NEGATIVE_CACHE.clear()
    assert _ORIGINAL_CLEAR_CACHE is not None
    _ORIGINAL_CLEAR_CACHE()


def install_v4_tcgdex_exact_coordinate_recovery() -> None:
    """Install a bounded post-NO_MATCH exact-coordinate bridge.

    This does not make TCGdex fuzzy. A recovery exists only for one reviewed
    language + GCC set + printed number + GCC name + year tuple, and the live
    TCGdex response must still prove the exact target set/localId/card count.
    """

    global _ORIGINAL_RESOLVER, _ORIGINAL_CLEAR_CACHE
    current = canonical.resolve_tcgdex_card
    if getattr(current, "_v4_exact_coordinate_recovery", False):
        return
    _ORIGINAL_RESOLVER = current
    _ORIGINAL_CLEAR_CACHE = canonical.clear_tcgdex_cache
    _resolve_with_exact_coordinate_recovery._v4_exact_coordinate_recovery = True  # type: ignore[attr-defined]
    canonical.resolve_tcgdex_card = _resolve_with_exact_coordinate_recovery
    canonical.clear_tcgdex_cache = _clear_all_tcgdex_caches
