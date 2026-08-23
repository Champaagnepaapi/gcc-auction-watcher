"""Dedicated bounded TCGdex budget for Magi recovery-only identity paths.

The native exact-coordinate lane owns its existing Japanese resolver budget.
Fallbacks for provider-missing set/number evidence must not starve that lane, so
this module gives recovery paths a separate resolver for the duration of one
Magi scan.  The recovery resolver caches only successful top-level set-list
queries keyed by exact parameters; card-coordinate/detail calls remain normal
TCGdex requests and every identity gate remains unchanged.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Optional

import v4_global_marketplace_magi_native_identity as native
import v4_global_retrieval_hardening_v3 as retrieval_v3


_MAX_RECOVERY_REQUESTS = 36
_ACTIVE_RECOVERY_RESOLVER: Optional[retrieval_v3.TCGdexJapaneseProofResolver] = None
_ORIGINAL_SCAN = None
_INSTALLED = False


class CachedRecoveryResolver(retrieval_v3.TCGdexJapaneseProofResolver):
    """Cache only successful exact set-list queries inside one recovery scan."""

    def __init__(self, *, max_requests: int = _MAX_RECOVERY_REQUESTS):
        super().__init__(max_requests=max_requests)
        self._set_list_cache: dict[tuple[tuple[str, str], ...], object] = {}

    def _get(self, path: str, *, params: Optional[Mapping[str, str]] = None):
        normalized_path = str(path or "").strip().lstrip("/")
        cache_key = tuple(sorted((str(k), str(v)) for k, v in (params or {}).items()))
        if normalized_path == "sets" and cache_key in self._set_list_cache:
            return 200, self._set_list_cache[cache_key]

        status, payload = super()._get(path, params=params)
        if normalized_path == "sets" and status == 200:
            self._set_list_cache[cache_key] = payload
        return status, payload


def active_recovery_resolver(fallback):
    """Return the scan-scoped recovery resolver, or fallback for direct tests."""
    return _ACTIVE_RECOVERY_RESOLVER or fallback


def _scan_with_recovery_budget(*args, **kwargs):
    global _ACTIVE_RECOVERY_RESOLVER
    assert _ORIGINAL_SCAN is not None

    # Nested invocation should share the same bounded context rather than create
    # another independent budget.
    if _ACTIVE_RECOVERY_RESOLVER is not None:
        return _ORIGINAL_SCAN(*args, **kwargs)

    recovery = CachedRecoveryResolver(max_requests=_MAX_RECOVERY_REQUESTS)
    _ACTIVE_RECOVERY_RESOLVER = recovery
    try:
        rows, status = _ORIGINAL_SCAN(*args, **kwargs)
        detail = str(status.detail or "")
        suffix = f"tcgdex_recovery_requests={recovery.requests_used}"
        return rows, replace(status, detail=f"{detail}; {suffix}" if detail else suffix)
    finally:
        _ACTIVE_RECOVERY_RESOLVER = None
        recovery.close()


def install_global_marketplace_magi_recovery_budget() -> None:
    """Install a scan-scoped recovery budget without altering native gates."""
    global _ORIGINAL_SCAN, _INSTALLED
    if _INSTALLED:
        return

    # Lazy imports avoid import-order cycles with the native scanner module.
    import v4_global_marketplace_notify as marketplace
    import v4_global_marketplace_scan as scan

    _ORIGINAL_SCAN = native.scan_magi_native_inventory
    native.scan_magi_native_inventory = _scan_with_recovery_budget
    scan.scan_magi_inventory = _scan_with_recovery_budget
    marketplace.scan_magi_inventory = _scan_with_recovery_budget
    _INSTALLED = True
