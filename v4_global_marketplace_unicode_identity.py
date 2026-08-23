"""Global-only Unicode identity normalization for exact Japanese card identities.

The shared market core intentionally predates native Japanese commercial names
and its normalizer keeps only ASCII a-z/0-9. That makes an otherwise exact
TCGdex Japanese identity appear incomplete. This installer is deliberately
Global-only and preserves the existing normalization byte-for-byte for every
non-Japanese/CJK input. Only identities containing Japanese/CJK script use the
Unicode path.
"""
from __future__ import annotations

import re
import unicodedata

import v4_global_market_core as market_core


_ORIGINAL_NORM = market_core._norm
_JAPANESE_OR_CJK_RE = re.compile(
    r"[\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff]"
)
_INSTALLED = False


def _unicode_identity_norm(value: object) -> str:
    """Preserve exact Japanese/CJK letters without changing the Latin contract."""
    original = _ORIGINAL_NORM(value)
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()

    # Keep the historical V4/Global result exactly for Latin and every other
    # non-Japanese/CJK input. This prevents queue/signature churn outside the
    # new Japanese-native identity lane.
    if _JAPANESE_OR_CJK_RE.search(text) is None:
        return original

    # NFKC keeps Japanese voiced kana composed (for example ポ and ド), unlike
    # the former NFKD attempt which split dakuten and corrupted exact names.
    normalized = "".join(ch if ch.isalnum() else " " for ch in text)
    return re.sub(r"\s+", " ", normalized).strip()


def install_global_marketplace_unicode_identity() -> None:
    """Install Unicode-safe identity normalization only in the Global process."""
    global _INSTALLED
    if _INSTALLED:
        return
    market_core._norm = _unicode_identity_norm
    _INSTALLED = True
