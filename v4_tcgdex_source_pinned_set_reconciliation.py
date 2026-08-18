from __future__ import annotations

from dataclasses import replace

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_japanese_set_aliases as japanese_aliases


_ORIGINAL_RESOLVER = None


def _reconcilable_alias_for_lot(lot: watcher.Lot) -> generalized.ExactSetAlias | None:
    language_code, listing_set, reference, _, _, _ = generalized._lot_components(lot)
    key = generalized._alias_key(language_code, listing_set)
    allowed = {
        generalized._alias_key(alias.language_code, alias.listing_set): alias
        for alias in japanese_aliases._ALIASES
    }
    alias = allowed.get(key)
    if alias is None or not generalized._validate_reference_for_alias(reference, alias):
        return None
    return alias


def _reclassify_exact(result: canonical.CanonicalCard) -> None:
    diagnostics = canonical._DIAGNOSTICS
    if diagnostics.tcgdex_exact > 0:
        diagnostics.tcgdex_exact -= 1
    if result.status == "AMBIGUOUS":
        diagnostics.tcgdex_ambiguous += 1
    elif result.status == "ERROR":
        diagnostics.tcgdex_error += 1


def _reconcile_exact_source_pinned_set(
    lot: watcher.Lot,
    card: canonical.CanonicalCard,
) -> canonical.CanonicalCard:
    if card.status != "EXACT":
        return card

    alias = _reconcilable_alias_for_lot(lot)
    if alias is None or card.set_id == alias.tcgdex_set_id:
        return card

    language_code, listing_set, _, listing_name, _, _ = generalized._lot_components(lot)
    recovered = generalized._fetch_coordinate(
        lot,
        language_code=language_code,
        listing_set=listing_set,
        listing_name=listing_name,
        set_id=alias.tcgdex_set_id,
        expected_count=alias.tcgdex_official_count,
        allow_localized_name_mismatch=alias.allow_localized_name_mismatch,
    )
    if recovered is None:
        blocked = canonical.CanonicalCard(
            "AMBIGUOUS",
            reason=(
                "TCGdex source-pinned set alias conflicts with REST namespace "
                f"({card.set_id} != {alias.tcgdex_set_id})"
            ),
        )
        _reclassify_exact(blocked)
        return blocked
    if recovered.status != "EXACT":
        _reclassify_exact(recovered)
        return recovered

    return replace(
        recovered,
        reason="TCGDEX_SOURCE_PINNED_SET_RECONCILED",
    )


def _resolve_with_source_pinned_set_reconciliation(lot: watcher.Lot) -> canonical.CanonicalCard:
    assert _ORIGINAL_RESOLVER is not None
    return _reconcile_exact_source_pinned_set(lot, _ORIGINAL_RESOLVER(lot))


def install_v4_tcgdex_source_pinned_set_reconciliation() -> None:
    """Correct a conflicting REST set namespace only from reviewed source-pinned aliases.

    This post-identity layer is intentionally narrow: the exact GCC set label,
    language and printed denominator must select one reviewed Japanese alias,
    then exact set + localId must be proven again by TCGdex. Provider market data
    never participates. If the pinned coordinate cannot be proven, the conflict
    blocks instead of preserving the contradictory REST identity.
    """

    global _ORIGINAL_RESOLVER
    current = canonical.resolve_tcgdex_card
    if getattr(current, "_v4_tcgdex_source_pinned_set_reconciliation", False):
        return
    _ORIGINAL_RESOLVER = current
    _resolve_with_source_pinned_set_reconciliation._v4_tcgdex_source_pinned_set_reconciliation = True  # type: ignore[attr-defined]
    canonical.resolve_tcgdex_card = _resolve_with_source_pinned_set_reconciliation
