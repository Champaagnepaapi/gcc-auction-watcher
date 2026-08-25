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
