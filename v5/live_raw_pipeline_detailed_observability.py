"""V5 live diagnostic entrypoint with passive per-record identity observability.

Import order is intentional: ``live_raw_pipeline_uniqueness`` first installs the
current deterministic uniqueness resolver. This module then replaces only the
constructed resolver/visual classes with subclasses that call the canonical V5
logic unchanged and collect bounded diagnostics around it.
"""

from __future__ import annotations

import sys

from . import live_raw_pipeline_uniqueness as _uniqueness_entrypoint  # noqa: F401
from . import live_raw_pipeline_catalog as catalog_pipeline
from .detailed_identity_observability import (
    DetailedDeterministicUniquenessHybridPokemonCardResolver,
    DetailedLocalVisualIdentityResolver,
    DetailedPokeTraceIdentityResolver,
    render_detailed_record,
)


_BasePipelineDiagnostic = catalog_pipeline.CatalogAwareLiveRawPipelineDiagnostic


class DetailedCatalogAwareLiveRawPipelineDiagnostic(_BasePipelineDiagnostic):
    """Print richer diagnostics after the unchanged pipeline has finished."""

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
        return summary


# Patch only constructor symbols used by catalog_pipeline.main(). Matching,
# thresholds, microvariant gates, market valuation and purchase safety remain in
# the existing V5 implementation.
catalog_pipeline.PokeTraceIdentityResolver = DetailedPokeTraceIdentityResolver
catalog_pipeline.HybridPokemonCardResolver = (
    DetailedDeterministicUniquenessHybridPokemonCardResolver
)
catalog_pipeline.LocalVisualIdentityResolver = DetailedLocalVisualIdentityResolver
catalog_pipeline.CatalogAwareLiveRawPipelineDiagnostic = (
    DetailedCatalogAwareLiveRawPipelineDiagnostic
)


def main() -> int:
    return catalog_pipeline.main()


if __name__ == "__main__":
    sys.exit(main())
