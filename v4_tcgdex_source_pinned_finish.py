from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

import v4_canonical_multimarket as canonical


# Exact upstream source used by the existing V4 TCGdex recovery registries.
# A record here is allowed only when this immutable source proves the physical
# finish set for one exact TCGdex card and the live REST projection disagrees.
_SOURCE_COMMIT = "af33c9ac882e2acfadffaf19e8083aa976d12983"


@dataclass(frozen=True)
class SourcePinnedFinish:
    language_code: str
    card_id: str
    set_id: str
    local_id: str
    finishes: tuple[str, ...]
    source_path: str


_RECORDS = (
    SourcePinnedFinish(
        language_code="ja",
        card_id="S12a-174",
        set_id="S12a",
        local_id="174",
        finishes=("holo",),
        source_path="data-asia/S/S12a/174.ts",
    ),
)

_ALLOWED_FINISH_KEYS = frozenset({"normal", "holo", "reverse"})
_ORIGINAL_RESOLVER = None


def _same_local_id(first: object, second: object) -> bool:
    first_left, _ = canonical._canonical_number_parts(first)
    second_left, _ = canonical._canonical_number_parts(second)
    return bool(first_left and second_left and first_left == second_left)


def _record_for(card: canonical.CanonicalCard) -> SourcePinnedFinish | None:
    if card.status != "EXACT":
        return None
    for record in _RECORDS:
        if str(card.language_code or "").strip().casefold() != record.language_code.casefold():
            continue
        if str(card.card_id or "").strip() != record.card_id:
            continue
        if str(card.set_id or "").strip() != record.set_id:
            continue
        if not _same_local_id(card.local_id, record.local_id):
            continue
        return record
    return None


def apply_source_pinned_finish(card: canonical.CanonicalCard) -> canonical.CanonicalCard:
    """Correct only normal/holo/reverse for one exact, immutable catalog card.

    This is not provider inference. The override is keyed by the already-proven
    TCGdex language + card ID + set ID + localId and comes from an immutable
    cards-database source pin. Every non-finish flag from the REST response is
    preserved unchanged.
    """

    record = _record_for(card)
    if record is None:
        return card

    declared = set(record.finishes)
    if not declared or not declared.issubset(_ALLOWED_FINISH_KEYS):
        return card

    variants = dict(card.variants) if isinstance(card.variants, Mapping) else {}
    for key in _ALLOWED_FINISH_KEYS:
        variants[key] = key in declared
    return replace(card, variants=variants)


def _resolve_with_source_pinned_finish(lot) -> canonical.CanonicalCard:
    assert _ORIGINAL_RESOLVER is not None
    return apply_source_pinned_finish(_ORIGINAL_RESOLVER(lot))


def install_v4_tcgdex_source_pinned_finish() -> None:
    """Install a post-identity correction for proven TCGdex REST/source drift."""

    global _ORIGINAL_RESOLVER
    current = canonical.resolve_tcgdex_card
    if getattr(current, "_v4_tcgdex_source_pinned_finish", False):
        return
    _ORIGINAL_RESOLVER = current
    _resolve_with_source_pinned_finish._v4_tcgdex_source_pinned_finish = True  # type: ignore[attr-defined]
    canonical.resolve_tcgdex_card = _resolve_with_source_pinned_finish
