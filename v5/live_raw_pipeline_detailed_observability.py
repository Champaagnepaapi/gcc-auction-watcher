"""V5 live diagnostic entrypoint with detailed identity observability.

Import order is intentional: ``live_raw_pipeline_uniqueness`` first installs the
current deterministic uniqueness resolver. This module then keeps that resolver
and its safety gates, adds passive observability, and applies the V5 live policy
that PokeTrace is market/pricing only rather than an identity source.
"""

from __future__ import annotations

import sys

from . import live_raw_pipeline_uniqueness as _uniqueness_entrypoint  # noqa: F401
from . import live_raw_pipeline_catalog as catalog_pipeline
from .detailed_identity_observability import (
    DetailedDeterministicUniquenessHybridPokemonCardResolver,
    render_detailed_record,
)
from .poketrace_market_only_identity import (
    MarketOnlyPokeTraceIdentityResolver,
    MarketOnlyPokeTraceVisualIdentityResolver,
    render_market_only_identity_counters,
    render_poketrace_market_only_policy,
)


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
        identity_resolver = getattr(
            self.card_catalog_resolver, "poketrace_identity", None
        )
        if isinstance(identity_resolver, MarketOnlyPokeTraceIdentityResolver):
            print(
                render_poketrace_market_only_policy(
                    identity_resolver,
                    self.visual_identity,
                )
            )
        return summary


# Patch only constructor symbols used by catalog_pipeline.main(). The catalogue
# resolver, deterministic uniqueness and microvariant gates stay unchanged.
# PokeTrace identity/visual search is deliberately replaced by market-only
# no-ops; the PokeTrace market provider itself is not disabled or modified.
catalog_pipeline.PokeTraceIdentityResolver = MarketOnlyPokeTraceIdentityResolver
catalog_pipeline.HybridPokemonCardResolver = (
    DetailedDeterministicUniquenessHybridPokemonCardResolver
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
