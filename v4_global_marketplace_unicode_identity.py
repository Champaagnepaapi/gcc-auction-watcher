"""Global-only Unicode identity normalization for exact Japanese card identities.

The shared market core intentionally predates native Japanese commercial names
and its normalizer keeps only ASCII a-z/0-9. That makes an otherwise exact
TCGdex Japanese identity appear incomplete. This installer is deliberately
Global-only and preserves the existing normalization byte-for-byte for inputs
whose letters/numbers become ASCII after NFKD (including accented Latin text).
Only identities containing genuine non-ASCII letters/numbers use the Unicode
path.
"""
from __future__ import annotations

import re
import unicodedata

import v4_global_market_core as market_core


_ORIGINAL_NORM = market_core._norm
_INSTALLED = False


def _unicode_identity_norm(value: object) -> str:
    """Preserve Japanese letters/numbers without changing the Latin contract."""
    original = _ORIGINAL_NORM(value)
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()

    # Accented Latin text becomes ASCII after NFKD and must retain the exact
    # historical Global/V4 normalization result.
    if not any(ch.isalnum() and ord(ch) > 127 for ch in text):
        return original

    normalized = "".join(ch if ch.isalnum() else " " for ch in text)
    return re.sub(r"\s+", " ", normalized).strip()


def install_global_marketplace_unicode_identity() -> None:
    """Install Unicode-safe identity normalization only in the Global process."""
    global _INSTALLED
    if _INSTALLED:
        return
    market_core._norm = _unicode_identity_norm
    _INSTALLED = True
