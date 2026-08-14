"""Isolated, read-only market observation sidecar.

Importing this package performs no I/O and has no connection to V4 entrypoints.
"""

from .collectors import (
    GCCMarketplaceCollector,
    SourceCollectionError,
    TCGdexCollector,
    load_gcc_fixture,
    load_tcgdex_fixture,
)
from .models import (
    CollectionResult,
    IdentityClaim,
    NormalizedObservation,
    RawSourceRecord,
    ShadowDiagnostics,
)
from .normalizers import normalize_gcc, normalize_tcgdex
from .persistence import ShadowKnowledgePersistence
from .runner import ShadowSidecar

__all__ = [
    "CollectionResult",
    "GCCMarketplaceCollector",
    "IdentityClaim",
    "NormalizedObservation",
    "RawSourceRecord",
    "ShadowDiagnostics",
    "ShadowKnowledgePersistence",
    "ShadowSidecar",
    "SourceCollectionError",
    "TCGdexCollector",
    "load_gcc_fixture",
    "load_tcgdex_fixture",
    "normalize_gcc",
    "normalize_tcgdex",
]
