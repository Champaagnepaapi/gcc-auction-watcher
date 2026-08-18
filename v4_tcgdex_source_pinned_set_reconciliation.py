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


def _recover_from_immutable_source(
    lot: watcher.Lot,
    *,
    alias: generalized.ExactSetAlias,
    language_code: str,
    listing_set: str,
    listing_name: str,
) -> canonical.CanonicalCard | None:
    """Prove the aliased set/localId directly from the immutable TCGdex source.

    The live REST projection is known to occasionally expose a stale/wrong set
    namespace.  When that happens, the already-reviewed exact GCC set alias plus
    printed denominator selects one TCGdex set.  We then require the immutable
    cards-database file for the exact localId to import that same set.  The
    existing source-finish parser provides the source-path/set-import proof and
    finish flags from the same pinned file; no provider market field participates.
    """

    # Lazy import avoids the intentional installer cycle: source-pinned finish
    # installs this set-reconciliation layer before wrapping it.
    from v4_tcgdex_source_pinned_finish import source_pinned_finish_proof

    identity = watcher.extract_card_identity(lot)
    reference = str(lot.card_number or identity.get("ref") or "").strip()
    if not reference or not listing_name:
        return None

    for local_id in generalized._reference_candidates(reference):
        if not generalized._same_local_id(local_id, reference):
            continue
        candidate = canonical.CanonicalCard(
            status="EXACT",
            card_id=f"{alias.tcgdex_set_id}-{local_id}",
            set_id=alias.tcgdex_set_id,
            set_name=listing_set,
            local_id=local_id,
            full_number=reference,
            name=listing_name,
            language_code=language_code,
            pricing={},
            variants={},
            reason="TCGDEX_SOURCE_PINNED_SET_COORDINATE",
            unique_name_number=False,
        )
        proof = source_pinned_finish_proof(candidate)
        if proof is None:
            continue

        finishes = set(proof.finishes)
        variants = {
            key: key in finishes
            for key in ("normal", "holo", "reverse")
        }
        watcher.log(
            "TCGdex source set correction: "
            f"{listing_name} #{reference} | "
            f"set={alias.tcgdex_set_id} | source={proof.source_path} | "
            f"pin={proof.source_commit[:12]}"
        )
        return replace(
            candidate,
            variants=variants,
            reason="TCGDEX_SOURCE_PINNED_SET_RECONCILED",
        )
    return None


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

    # Preserve the existing fast path: if the target live REST coordinate is
    # healthy, use its full canonical payload.  The immutable source path below
    # exists specifically for the observed class where REST itself is the stale
    # projection and therefore cannot prove the corrected namespace.
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
        recovered = _recover_from_immutable_source(
            lot,
            alias=alias,
            language_code=language_code,
            listing_set=listing_set,
            listing_name=listing_name,
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
    language and printed denominator must select one reviewed Japanese alias.
    The target set + localId is then proven either by the exact live TCGdex
    coordinate or, when that REST projection is itself stale, by the immutable
    pinned cards-database file importing the same exact set. Provider market data
    never participates. If neither proof is available, the conflict blocks.
    """

    global _ORIGINAL_RESOLVER
    current = canonical.resolve_tcgdex_card
    if getattr(current, "_v4_tcgdex_source_pinned_set_reconciliation", False):
        return
    _ORIGINAL_RESOLVER = current
    _resolve_with_source_pinned_set_reconciliation._v4_tcgdex_source_pinned_set_reconciliation = True  # type: ignore[attr-defined]
    canonical.resolve_tcgdex_card = _resolve_with_source_pinned_set_reconciliation
