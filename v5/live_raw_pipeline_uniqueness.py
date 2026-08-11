from __future__ import annotations

import sys

from . import live_raw_pipeline_catalog as catalog_pipeline
from .card_identity_uniqueness import (
    DeterministicUniquenessHybridPokemonCardResolver,
    render_catalog_uniqueness_counters,
)


# Keep the established V5 pipeline untouched and replace only the resolver
# class constructed by its main() entrypoint. The subclass preserves the normal
# Hybrid path and adds exact two-of-three TCGdex uniqueness before fallbacks.
catalog_pipeline.HybridPokemonCardResolver = (
    DeterministicUniquenessHybridPokemonCardResolver
)


_original_render = catalog_pipeline.render_card_catalog_counters


def _render_with_uniqueness(resolver):
    base = _original_render(resolver)
    if isinstance(resolver, DeterministicUniquenessHybridPokemonCardResolver):
        return base + "\n" + render_catalog_uniqueness_counters(resolver)
    return base


catalog_pipeline.render_card_catalog_counters = _render_with_uniqueness


def main() -> int:
    return catalog_pipeline.main()


if __name__ == "__main__":
    sys.exit(main())
