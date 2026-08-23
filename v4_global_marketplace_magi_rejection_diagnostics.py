"""Bounded public rejection examples for Magi PR validation.

Diagnostics only: this wrapper never changes a resolver result. It prints at
most three public listing examples per final resolution reason so PR live logs
can distinguish provider-data gaps from parser/catalog gaps without retaining
secrets or private session data.
"""
from __future__ import annotations

import json
from collections import Counter

import japan_edge_hunter as japan
import v4_global_marketplace_magi_detail_coordinate as detail_coordinate
import v4_global_marketplace_magi_native_identity as native


_MAX_EXAMPLES_PER_REASON = 3
_COUNTS: Counter[str] = Counter()
_ORIGINAL_RESOLVER = None
_INSTALLED = False


def _clean(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _resolve_with_bounded_diagnostics(ask, **kwargs):
    assert _ORIGINAL_RESOLVER is not None
    result = _ORIGINAL_RESOLVER(ask, **kwargs)
    reason = result.reason or result.status or "unknown"
    _COUNTS[reason] += 1
    if _COUNTS[reason] <= _MAX_EXAMPLES_PER_REASON:
        full_number, set_code, preflight_reason = native._preflight(ask)
        evidence = detail_coordinate._current_product_evidence(ask)
        payload = {
            "reason": reason,
            "status": result.status,
            "url": str(getattr(ask, "url", "") or ""),
            "title": _clean(getattr(ask, "title", ""), 260),
            "evidence": _clean(evidence, 420),
            "preflight_reason": preflight_reason,
            "full_number": full_number,
            "set_code": set_code,
            "card_id": result.card_id,
            "set_id": result.set_id,
        }
        print("[MAGI_REJECT_DIAG] " + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return result


def install_global_marketplace_magi_rejection_diagnostics() -> None:
    """Wrap the final Magi resolver for PR-live observability only."""
    global _ORIGINAL_RESOLVER, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = native.resolve_magi_native_identity
    native.resolve_magi_native_identity = _resolve_with_bounded_diagnostics
    _INSTALLED = True
