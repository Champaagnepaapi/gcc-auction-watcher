"""Global-only recovery of reviewed TCGdex aliases from the immutable source pin.

The production V4 stack already uses exact set aliases and immutable source-file
proofs. At larger Global batches, some aliases can reach NO_MATCH/AMBIGUOUS before
the source fallback gets a chance (REST namespace gaps, catalogue uniqueness
collisions, or the historical 12-request source-proof budget). This wrapper does
not invent identity: it retries only reviewed aliases whose exact printed
reference validates, then requires the pinned card file to import that exact set.
"""
from __future__ import annotations

import os
from dataclasses import replace

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_japanese_set_aliases as japanese_aliases
import v4_tcgdex_source_pinned_finish as source_finish
import v4_tcgdex_source_pinned_set_reconciliation as reconciliation


_ORIGINAL_RESOLVER = None
_INSTALLED = False


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default)).strip()))
    except ValueError:
        return default


def _reviewed_alias(lot: watcher.Lot) -> generalized.ExactSetAlias | None:
    language_code, listing_set, reference, _, _, _ = generalized._lot_components(lot)
    allowed = {
        generalized._alias_key(alias.language_code, alias.listing_set): alias
        for alias in japanese_aliases._ALIASES
    }
    alias = allowed.get(generalized._alias_key(language_code, listing_set))
    if alias is None:
        return None
    if not generalized._validate_reference_for_alias(reference, alias):
        return None
    return alias


def _reclassify_recovered(original: canonical.CanonicalCard) -> None:
    diagnostics = canonical._DIAGNOSTICS
    if original.status == "NO_MATCH" and diagnostics.tcgdex_no_match > 0:
        diagnostics.tcgdex_no_match -= 1
    elif original.status == "AMBIGUOUS" and diagnostics.tcgdex_ambiguous > 0:
        diagnostics.tcgdex_ambiguous -= 1
    diagnostics.tcgdex_exact += 1


def recover_reviewed_source_alias(
    lot: watcher.Lot,
    original: canonical.CanonicalCard,
) -> canonical.CanonicalCard:
    """Recover only NO_MATCH/AMBIGUOUS results from exact pinned source proof."""

    if original.status not in {"NO_MATCH", "AMBIGUOUS"}:
        return original
    alias = _reviewed_alias(lot)
    if alias is None:
        return original

    language_code, listing_set, _, listing_name, _, _ = generalized._lot_components(lot)
    recovered = reconciliation._recover_from_immutable_source(
        lot,
        alias=alias,
        language_code=language_code,
        listing_set=listing_set,
        listing_name=listing_name,
    )
    if recovered is None or recovered.status != "EXACT":
        return original

    _reclassify_recovered(original)
    return replace(recovered, reason="TCGDEX_GLOBAL_SOURCE_ALIAS_RECOVERED")


def _resolve_with_global_source_alias(lot: watcher.Lot) -> canonical.CanonicalCard:
    assert _ORIGINAL_RESOLVER is not None
    return recover_reviewed_source_alias(lot, _ORIGINAL_RESOLVER(lot))


def install_global_marketplace_tcgdex_source_alias_recovery() -> None:
    """Install only inside the Global marketplace-first process."""

    global _ORIGINAL_RESOLVER, _INSTALLED
    if _INSTALLED:
        return

    global_source_cap = _env_int("GLOBAL_TCGDEX_SOURCE_MAX_REQUESTS_PER_RUN", 60)
    source_finish._SOURCE_MAX_REQUESTS_PER_RUN = max(
        source_finish._SOURCE_MAX_REQUESTS_PER_RUN,
        global_source_cap,
    )

    japanese_aliases.install_v4_tcgdex_japanese_set_aliases()
    _ORIGINAL_RESOLVER = canonical.resolve_tcgdex_card
    canonical.resolve_tcgdex_card = _resolve_with_global_source_alias
    _INSTALLED = True
