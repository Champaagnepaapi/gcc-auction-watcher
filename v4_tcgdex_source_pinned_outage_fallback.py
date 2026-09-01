from __future__ import annotations

from dataclasses import replace

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_source_pinned_set_reconciliation as source_set


# Keep this fallback on exactly the same transient transport class already
# accepted by the proven TCGdex retry layer (#145/#216). A malformed payload,
# provider-auth/rate-limit response, ordinary NO_MATCH or ambiguity must never
# be converted into an exact identity by this wrapper.
_RETRYABLE_ERROR_MARKERS = (
    "connectionerror",
    "timeout",
    "http 502",
    "http 503",
    "http 504",
)

_ORIGINAL_RESOLVER = None


def _is_retryable_transport_error(card: canonical.CanonicalCard) -> bool:
    if card.status != "ERROR":
        return False
    reason = str(card.reason or "").casefold()
    return any(marker in reason for marker in _RETRYABLE_ERROR_MARKERS)


def _reclassify_error_as_exact() -> None:
    diagnostics = canonical._DIAGNOSTICS
    if diagnostics.tcgdex_error > 0:
        diagnostics.tcgdex_error -= 1
    diagnostics.tcgdex_exact += 1


def recover_source_pinned_outage(
    lot: watcher.Lot,
    original: canonical.CanonicalCard,
) -> canonical.CanonicalCard:
    """Recover only a reviewed Japanese set/localId during a TCGdex outage.

    The normal REST resolver always runs first. Recovery is attempted only after
    its proven retry/breaker stack returns a retryable transport ERROR. The lot
    must then select one of the already-reviewed Japanese set aliases and satisfy
    that alias' exact printed-number/denominator (or promo suffix) contract.

    Final proof reuses the existing immutable cards-database pin: the exact
    set/localId file must exist at that pin, import that exact set, and expose
    only recognized finish variants. Missing/malformed source or any unreviewed
    coordinate leaves the original ERROR untouched. This does not create a new
    alias, fuzzy/name-only resolver, clean NO_MATCH, or provider-market proof.
    """

    if not _is_retryable_transport_error(original):
        return original

    alias = source_set._reconcilable_alias_for_lot(lot)
    if alias is None:
        return original

    language_code, listing_set, _, listing_name, _, _ = generalized._lot_components(lot)
    if language_code != "ja" or not listing_name:
        return original

    recovered = source_set._recover_from_immutable_source(
        lot,
        alias=alias,
        language_code=language_code,
        listing_set=listing_set,
        listing_name=listing_name,
    )
    if recovered is None or recovered.status != "EXACT":
        return original

    _reclassify_error_as_exact()
    watcher.log(
        "TCGdex outage source recovery: "
        f"{listing_name} #{recovered.full_number} | set={recovered.set_id} | "
        "immutable reviewed alias proof"
    )
    return replace(recovered, reason="TCGDEX_SOURCE_PINNED_OUTAGE_RECOVERY")


def _resolve_with_source_pinned_outage_fallback(
    lot: watcher.Lot,
) -> canonical.CanonicalCard:
    assert _ORIGINAL_RESOLVER is not None
    return recover_source_pinned_outage(lot, _ORIGINAL_RESOLVER(lot))


def install_v4_tcgdex_source_pinned_outage_fallback() -> None:
    """Wrap the final V4 TCGdex resolver with a transport-outage-only fallback."""

    global _ORIGINAL_RESOLVER
    current = canonical.resolve_tcgdex_card
    if getattr(current, "_v4_tcgdex_source_pinned_outage_fallback", False):
        return
    _ORIGINAL_RESOLVER = current
    _resolve_with_source_pinned_outage_fallback._v4_tcgdex_source_pinned_outage_fallback = True  # type: ignore[attr-defined]
    canonical.resolve_tcgdex_card = _resolve_with_source_pinned_outage_fallback
