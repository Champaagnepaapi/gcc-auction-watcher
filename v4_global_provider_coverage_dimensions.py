"""One-shot read-only extension of the Global provider coverage diagnostic.

Adds only parsed commercial-dimension evidence to sanitized PokeTrace candidate
output. It does not change provider matching, valuation, notification or state.
"""
from __future__ import annotations

from typing import Any, Mapping

import watcher
import v4_global_provider_coverage_diagnostic as diagnostic
import v4_multimarket_safety as safety


_ORIGINAL_SANITIZER = diagnostic.sanitize_poketrace_candidate


def sanitize_with_dimensions(lot, canonical, candidate: Mapping[str, Any]) -> dict[str, Any]:
    payload = _ORIGINAL_SANITIZER(lot, canonical, candidate)
    payload["expected_dimensions"] = dict(sorted(watcher.expected_commercial_dimensions(lot).items()))
    payload["observed_dimensions"] = {
        key: sorted(values)
        for key, values in sorted(safety._candidate_sensitive_dimensions(candidate).items())
    }
    return payload


def main() -> int:
    diagnostic.sanitize_poketrace_candidate = sanitize_with_dimensions
    return diagnostic.main()


if __name__ == "__main__":
    raise SystemExit(main())
