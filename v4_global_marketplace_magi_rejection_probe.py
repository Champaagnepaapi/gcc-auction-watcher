"""Bounded PR-only diagnostics for final Magi identity rejections.

The probe is inert unless ``GLOBAL_MAGI_REJECTION_DIAGNOSTICS=true``. It wraps
the final Magi native resolver after all exact recovery layers and prints only
public Magi item URL/title, final rejection reason, and already-resolved public
TCGdex card/set IDs when present. No payload body, credentials, cookies,
provider responses or market values are logged.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field

import japan_edge_hunter as japan
import v4_global_marketplace_magi_native_identity as native


_ENABLED = os.getenv("GLOBAL_MAGI_REJECTION_DIAGNOSTICS", "false").strip().lower() in {
    "1", "true", "yes"
}
_MAX_TOTAL = max(0, int(os.getenv("GLOBAL_MAGI_REJECTION_DIAGNOSTICS_MAX_TOTAL", "30")))
_MAX_PER_REASON = max(1, int(os.getenv("GLOBAL_MAGI_REJECTION_DIAGNOSTICS_MAX_PER_REASON", "4")))
_ITEM_URL_RE = re.compile(r"^https://magi\.camp/items/\d+(?:[/?#].*)?$", re.I)
_PUBLIC_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_COUNTS: Counter[str] = Counter()
_TOTAL = 0
_ORIGINAL_RESOLVER = None
_INSTALLED = False

# Artifact diagnostics, independent of the optional console rejection probe.
# This is a storage bound, never a retrieval or identity budget.
_MANIFEST_MAX_ROWS = 200
_REQUEST_CLASSES = ("sets_filtered", "sets_catalog", "set_detail", "set_coordinate",
                    "card_search", "card_detail", "other")


@dataclass(frozen=True)
class MagiScanStatus(native.ScanStatus):
    manifest: dict = field(default_factory=dict)


def budget_snapshot(resolver, alias_budget) -> dict[str, int]:
    """Read scan-owned counters only; do not resolve, fetch, or warm caches."""
    import v4_global_marketplace_magi_recovery_budget as budget

    recovery = budget._ACTIVE_RECOVERY_RESOLVER
    counters = {
        "native_ja": resolver.requests_used,
        "latin_alias": alias_budget.requests_used,
        "recovery": getattr(recovery, "requests_used", 0),
        "recovery_broad": getattr(recovery, "_nonpriority_requests_used", 0),
    }
    for attribute, label in (("request_breakdown", "requests"), ("cache_hits", "cache_hits"),
                             ("reserved_breakdown", "reserved"), ("exhausted_breakdown", "exhausted")):
        counts = getattr(recovery, attribute, {})
        for category in _REQUEST_CLASSES:
            counters[f"{label}.{category}"] = int(counts.get(category, 0))
    return counters


class MagiManifest:
    def __init__(self, candidates: int):
        self.candidates = candidates
        self.rows: list[dict] = []
        self.seen = 0

    def record(self, ask, status, reason, before, after, resolution=None):
        self.seen += 1
        if len(self.rows) >= _MANIFEST_MAX_ROWS:
            return
        # Strip query/fragment data even on otherwise valid public item URLs.
        match = re.fullmatch(r"https://magi\.camp/items/(\d+)(?:[/?#].*)?", str(ask.url), re.I)
        item_id = match.group(1) if match else ""
        coordinate = {}
        if resolution is not None:
            for key in ("card_id", "set_id"):
                value = _safe_public_id(getattr(resolution, key, ""))
                if value:
                    coordinate[key] = value
        # Coordinates on a rejection describe the catalog evidence, not an
        # assertion that the provider's identity matched it.
        self.rows.append({
            "ordinal": self.seen,
            "item_id": item_id,
            "url": f"https://magi.camp/items/{item_id}" if item_id else "",
            "status": status if status in {"EXACT", "NO_MATCH", "ERROR", "NOT_EVALUATED"} else "ERROR",
            "reason": str(reason)[:180] if re.fullmatch(r"[A-Za-z0-9_+:. -]{1,180}", str(reason)) else "identity_unproven",
            "coordinate": coordinate,
            "budget_delta": {key: after[key] - before.get(key, 0) for key in sorted(after)
                             if after[key] != before.get(key, 0)},
        })

    def payload(self):
        return {"schema_version": 1, "candidates": self.candidates,
                "rows": self.rows, "truncated": max(0, self.seen - len(self.rows))}


def clear_magi_rejection_probe_state() -> None:
    global _TOTAL
    _COUNTS.clear()
    _TOTAL = 0


def _safe_title(value: object) -> str:
    text = " ".join(str(value or "").split())
    return text[:240]


def _safe_url(value: object) -> str:
    text = str(value or "").strip()
    return text if _ITEM_URL_RE.fullmatch(text) else ""


def _safe_public_id(value: object) -> str:
    text = str(value or "").strip()
    return text if _PUBLIC_ID_RE.fullmatch(text) else ""


def _record(ask: japan.Ask, result: native.MagiNativeResolution) -> None:
    global _TOTAL
    if not _ENABLED or _TOTAL >= _MAX_TOTAL:
        return
    if result.status == "EXACT" and result.identity is not None:
        return
    reason = " ".join(str(result.reason or result.status or "identity_unproven").split())[:180]
    if _COUNTS[reason] >= _MAX_PER_REASON:
        return
    url = _safe_url(ask.url)
    title = _safe_title(ask.title)
    if not url:
        return
    card_id = _safe_public_id(result.card_id)
    set_id = _safe_public_id(result.set_id)
    coordinate = ""
    if card_id or set_id:
        coordinate = f" | tcgdex_card_id={card_id or '-'} | tcgdex_set_id={set_id or '-'}"
    _COUNTS[reason] += 1
    _TOTAL += 1
    print(
        f"[MAGI_REJECT] reason={reason}{coordinate} | url={url} | title={title}",
        flush=True,
    )


def _resolve_with_probe(ask, **kwargs):
    assert _ORIGINAL_RESOLVER is not None
    result = _ORIGINAL_RESOLVER(ask, **kwargs)
    _record(ask, result)
    return result


def install_global_marketplace_magi_rejection_probe() -> None:
    global _ORIGINAL_RESOLVER, _INSTALLED
    if _INSTALLED or not _ENABLED:
        return
    _ORIGINAL_RESOLVER = native.resolve_magi_native_identity
    native.resolve_magi_native_identity = _resolve_with_probe
    _INSTALLED = True
