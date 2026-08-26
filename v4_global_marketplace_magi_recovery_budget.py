"""Dedicated bounded TCGdex budget for Magi recovery-only identity paths.

The native exact-coordinate lane owns its existing Japanese resolver budget.
Fallbacks for provider-missing set/number evidence must not starve that lane, so
this module gives recovery paths a separate resolver for the duration of one
Magi scan. The recovery resolver caches safe set-list queries, clean set-card
coordinate reads, exact parameterized card searches and clean card-detail reads,
and exposes aggregate request-class diagnostics. No listing data is emitted and
every identity gate remains unchanged.

The final eight requests of the fixed recovery budget are reserved for exact
card-search/card-detail proof. Broader set discovery/coordinate scans fail closed
once that reserve is reached; the total ceiling remains unchanged.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Mapping, Optional

import v4_global_marketplace_magi_native_identity as native
import v4_global_retrieval_hardening_v3 as retrieval_v3


_MAX_RECOVERY_REQUESTS = 36
_CARD_IDENTITY_RESERVE_REQUESTS = 8
_CARD_IDENTITY_PRIORITY_CLASSES = frozenset({"card_search", "card_detail"})
_ACTIVE_RECOVERY_RESOLVER: Optional[retrieval_v3.TCGdexJapaneseProofResolver] = None
_ORIGINAL_SCAN = None
_INSTALLED = False


def _request_class(path: str, params: Optional[Mapping[str, str]] = None) -> str:
    normalized = str(path or "").strip().lstrip("/")
    if normalized == "sets":
        return "sets_filtered" if params else "sets_catalog"
    if normalized.startswith("sets/"):
        parts = [part for part in normalized.split("/") if part]
        return "set_detail" if len(parts) == 2 else "set_coordinate"
    if normalized == "cards":
        return "card_search"
    if normalized.startswith("cards/"):
        return "card_detail"
    return "other"


def _compact_counts(values: Mapping[str, int]) -> str:
    return ",".join(f"{key}:{int(values[key])}" for key in sorted(values) if int(values[key]) > 0) or "none"


class CachedRecoveryResolver(retrieval_v3.TCGdexJapaneseProofResolver):
    """Cache deterministic recovery reads and expose aggregate diagnostics."""

    def __init__(self, *, max_requests: int = _MAX_RECOVERY_REQUESTS):
        super().__init__(max_requests=max_requests)
        self._set_list_cache: dict[tuple[tuple[str, str], ...], object] = {}
        self._coordinate_cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[int, object]] = {}
        self._card_search_cache: dict[tuple[tuple[str, str], ...], object] = {}
        self._card_detail_cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[int, object]] = {}
        self.request_breakdown: Counter[str] = Counter()
        self.cache_hits: Counter[str] = Counter()
        self.reserved_breakdown: Counter[str] = Counter()
        self.exhausted_breakdown: Counter[str] = Counter()
        # Tiny unit-test budgets should keep their historical semantics. The
        # production 36-request budget reserves eight requests, matching four
        # strict exact card-search + card-detail proof pairs already observed in
        # the proven 31/96 Magi production baseline.
        self._card_identity_reserve = min(
            _CARD_IDENTITY_RESERVE_REQUESTS,
            max(0, int(max_requests) - 2),
        )

    def _get(self, path: str, *, params: Optional[Mapping[str, str]] = None):
        normalized_path = str(path or "").strip().lstrip("/")
        request_class = _request_class(normalized_path, params)
        params_key = tuple(sorted((str(k), str(v)) for k, v in (params or {}).items()))
        if normalized_path == "sets" and params_key in self._set_list_cache:
            self.cache_hits[request_class] += 1
            return 200, self._set_list_cache[params_key]
        # Only parameterized card searches are cached. This keeps the cache
        # bounded to explicit recovery queries (for example exact name=eq:...)
        # and avoids accidentally retaining an unfiltered cards catalog.
        if normalized_path == "cards" and params_key and params_key in self._card_search_cache:
            self.cache_hits[request_class] += 1
            return 200, self._card_search_cache[params_key]

        parts = [part for part in normalized_path.split("/") if part]
        coordinate_key = (normalized_path, params_key)
        is_set_coordinate = len(parts) >= 3 and parts[0] == "sets"
        is_card_detail = len(parts) == 2 and parts[0] == "cards"
        if is_set_coordinate and coordinate_key in self._coordinate_cache:
            self.cache_hits[request_class] += 1
            return self._coordinate_cache[coordinate_key]
        if is_card_detail and coordinate_key in self._card_detail_cache:
            self.cache_hits[request_class] += 1
            return self._card_detail_cache[coordinate_key]

        # Preserve the production reserve for the strongest bounded recovery
        # class: exact parameterized card search followed by exact card-detail
        # revalidation. Broader set scans simply fail closed at the reserve
        # boundary; they never borrow from or increase the 36-call cap.
        reserve_floor = max(0, self.max_requests - self._card_identity_reserve)
        if (
            self._card_identity_reserve
            and request_class not in _CARD_IDENTITY_PRIORITY_CLASSES
            and self.requests_used >= reserve_floor
        ):
            self.reserved_breakdown[request_class] += 1
            return 0, {"error": "budget_reserved_for_card_identity"}

        before = self.requests_used
        status, payload = super()._get(path, params=params)
        if self.requests_used > before:
            self.request_breakdown[request_class] += self.requests_used - before
        elif status == 0:
            self.exhausted_breakdown[request_class] += 1

        if normalized_path == "sets" and status == 200:
            self._set_list_cache[params_key] = payload
        if normalized_path == "cards" and params_key and status == 200:
            self._card_search_cache[params_key] = payload
        # Clean 200/404 exact-coordinate and exact-card-detail answers are
        # deterministic for this one scan and safe to reuse. Never cache
        # transport/rate-limit/server failures or budget exhaustion because
        # they must remain retryable/fail-closed.
        if is_set_coordinate and status in {200, 404}:
            self._coordinate_cache[coordinate_key] = (status, payload)
        if is_card_detail and status in {200, 404}:
            self._card_detail_cache[coordinate_key] = (status, payload)
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
        suffixes = [
            f"tcgdex_recovery_requests={recovery.requests_used}",
            f"tcgdex_recovery_card_identity_reserve={recovery._card_identity_reserve}",
        ]
        breakdown = getattr(recovery, "request_breakdown", {})
        cache_hits = getattr(recovery, "cache_hits", {})
        reserved = getattr(recovery, "reserved_breakdown", {})
        exhausted = getattr(recovery, "exhausted_breakdown", {})
        if breakdown:
            suffixes.append(f"tcgdex_recovery_breakdown={_compact_counts(breakdown)}")
        if cache_hits:
            suffixes.append(f"tcgdex_recovery_cache_hits={_compact_counts(cache_hits)}")
        if reserved:
            suffixes.append(f"tcgdex_recovery_reserved={_compact_counts(reserved)}")
        if exhausted:
            suffixes.append(f"tcgdex_recovery_exhausted={_compact_counts(exhausted)}")
        suffix = "; ".join(suffixes)
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
