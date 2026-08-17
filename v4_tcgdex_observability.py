from __future__ import annotations

from functools import wraps
from typing import Any

import watcher
import v4_canonical_multimarket as multimarket


_PRESERVED_FIELDS = (
    "tcgdex_attempted",
    "tcgdex_exact",
    "tcgdex_no_match",
    "tcgdex_ambiguous",
    "tcgdex_error",
    "psa_below_8_excluded",
    "psa_unsupported_grade_excluded",
)


def _snapshot_pre_external_diagnostics() -> dict[str, int]:
    diagnostics = multimarket._DIAGNOSTICS
    return {
        field: int(getattr(diagnostics, field, 0) or 0)
        for field in _PRESERVED_FIELDS
    }


def install_v4_tcgdex_observability() -> None:
    """Preserve catalog-stage diagnostics across the external-stage reset.

    The canonical V4 pipeline resolves TCGdex identity during item inspection,
    before ``process_external_market_candidates`` starts. That function resets
    ``MultiMarketDiagnostics`` for external-market counters, which previously
    erased the already-collected TCGdex and PSA-scope counters and produced
    misleading ``attempted 0`` logs.

    This wrapper changes diagnostics only. Matching, valuation, provider
    budgets, queue ordering and opportunity decisions are untouched.
    """

    original = watcher.process_external_market_candidates
    if getattr(original, "_v4_tcgdex_observability_installed", False):
        return

    @wraps(original)
    def wrapped(*args: Any, **kwargs: Any):
        preserved = _snapshot_pre_external_diagnostics()
        original_diagnostics_class = multimarket.MultiMarketDiagnostics

        class PreservingMultiMarketDiagnostics(original_diagnostics_class):
            def __init__(self, *diag_args: Any, **diag_kwargs: Any) -> None:
                super().__init__(*diag_args, **diag_kwargs)
                for field, value in preserved.items():
                    setattr(self, field, value)

        multimarket.MultiMarketDiagnostics = PreservingMultiMarketDiagnostics
        try:
            return original(*args, **kwargs)
        finally:
            multimarket.MultiMarketDiagnostics = original_diagnostics_class

    setattr(wrapped, "_v4_tcgdex_observability_installed", True)
    watcher.process_external_market_candidates = wrapped
