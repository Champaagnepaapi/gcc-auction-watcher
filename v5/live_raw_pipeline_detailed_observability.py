"""V5 live diagnostic with detailed identity observability and emergency fallback.

Import order is intentional: ``live_raw_pipeline_uniqueness`` first installs the
current deterministic uniqueness resolver. This module then keeps those safety
gates, keeps routine PokeTrace identity retrieval disabled, and permits a
separate bounded PokeTrace identity lane only after a genuine TCGdex technical
outage and an unresolved normal catalogue chain.

PokemonPriceTracker is optionally queried *after* all live decisions as a
shadow-only diagnostic. Its output cannot mutate identity, microvariant gates,
or valuation.
"""

from __future__ import annotations

import sys

from . import live_raw_pipeline_uniqueness as _uniqueness_entrypoint  # noqa: F401
from . import live_raw_pipeline_catalog as catalog_pipeline
from .detailed_identity_observability import render_detailed_record
from .emergency_identity_fallback import (
    EmergencyFallbackDetailedPokemonCardResolver,
    render_emergency_identity_policy,
)
from .poketrace_market_only_identity import (
    MarketOnlyPokeTraceIdentityResolver,
    MarketOnlyPokeTraceVisualIdentityResolver,
    render_market_only_identity_counters,
)
from .pokemonpricetracker_identity_shadow import PokemonPriceTrackerIdentityShadow


_BasePipelineDiagnostic = catalog_pipeline.CatalogAwareLiveRawPipelineDiagnostic


class DetailedCatalogAwareLiveRawPipelineDiagnostic(_BasePipelineDiagnostic):
    """Print richer diagnostics after the current deterministic pipeline."""

    def run(self):
        summary = super().run()
        print("=== V5 DETAILED PER-RECORD IDENTITY OBSERVABILITY ===")
        if not self.unresolved_diagnostics:
            print("unresolved/variant-blocked records: 0")
        else:
            print(
                "unresolved/variant-blocked records: "
                f"{len(self.unresolved_diagnostics)}"
            )
            for simple in self.unresolved_diagnostics:
                print(
                    render_detailed_record(
                        simple,
                        self.card_catalog_resolver,
                        self.visual_identity,
                    )
                )
        print("observability changes acceptance/valuation: false")
        if isinstance(
            self.card_catalog_resolver,
            EmergencyFallbackDetailedPokemonCardResolver,
        ):
            print(render_emergency_identity_policy(self.card_catalog_resolver))

        # This is deliberately last: every acceptance/valuation decision has
        # already been made. PPT can only report what it might have found.
        ppt_shadow = PokemonPriceTrackerIdentityShadow.from_env()
        ppt_shadow.observe(tuple(self.unresolved_diagnostics))
        print(ppt_shadow.render())
        return summary


# Routine PokeTrace identity remains a no-op. The catalogue resolver owns the
# separate emergency lane and enables it only from per-record TCGdex technical
# health evidence. Microvariant gates, market valuation and purchase safety are
# otherwise unchanged.
catalog_pipeline.PokeTraceIdentityResolver = MarketOnlyPokeTraceIdentityResolver
catalog_pipeline.HybridPokemonCardResolver = (
    EmergencyFallbackDetailedPokemonCardResolver
)
catalog_pipeline.LocalVisualIdentityResolver = (
    MarketOnlyPokeTraceVisualIdentityResolver
)
catalog_pipeline.render_poketrace_identity_counters = (
    render_market_only_identity_counters
)
catalog_pipeline.CatalogAwareLiveRawPipelineDiagnostic = (
    DetailedCatalogAwareLiveRawPipelineDiagnostic
)


def main() -> int:
    return catalog_pipeline.main()


if __name__ == "__main__":
    sys.exit(main())
