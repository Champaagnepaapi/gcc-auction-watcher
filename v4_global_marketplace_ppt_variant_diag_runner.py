"""Read-only PR diagnostic bootstrap for final PPT material-gate outcomes.

This file is never used by production workflows. It replaces only the already
installed detailed-variant matcher with an observing wrapper, then runs the
normal marketplace-first Global bootstrap unchanged.
"""
from __future__ import annotations

import os

os.environ.setdefault("GLOBAL_PPT_VARIANT_DIAGNOSTICS", "true")

import v4_tcgdex_detailed_variants as detailed
import v4_global_marketplace_ppt_variant_diagnostics as diagnostics


_ORIGINAL_DETAILED_PPT_MATCH = detailed._ppt_match_with_detailed_variants


def _observed_detailed_match(identity, canonical_card, rows, *, provider_set_id: str = ""):
    diagnostics._ORIGINAL_MATCH = _ORIGINAL_DETAILED_PPT_MATCH
    return diagnostics._diagnostic_match(
        identity,
        canonical_card,
        rows,
        provider_set_id=provider_set_id,
    )


def main() -> int:
    # The normal installer will attach this function at the exact point where it
    # would have attached the production detailed matcher. No provider request,
    # identity decision or economic result is altered.
    detailed._ppt_match_with_detailed_variants = _observed_detailed_match
    import v4_global_marketplace_notify_resilient as runner

    return runner.main()


if __name__ == "__main__":
    raise SystemExit(main())
