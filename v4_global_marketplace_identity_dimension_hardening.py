"""Global-only semantic cleanup for GCC commercial dimensions.

GCC's public `collectible.attribute` field is not consistently a physical card
finish: modern rows can expose mechanics such as `V` or `Ex` there. Treating
those labels as holo/printing evidence creates false PokeTrace/PPT microvariant
conflicts. This wrapper keeps only values that the existing deterministic finish
parser recognizes; mechanics stay proved by the exact card name instead.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Optional

import v4_global_marketplace_discovery as discovery
import v4_raw_consensus as raw_consensus
from v4_global_market_core import CommercialIdentity


_ORIGINAL_GCC_IDENTITY = None
_INSTALLED = False


def gcc_identity_from_row_semantic(
    row: Mapping[str, Any],
) -> Optional[CommercialIdentity]:
    assert _ORIGINAL_GCC_IDENTITY is not None
    identity = _ORIGINAL_GCC_IDENTITY(row)
    if identity is None:
        return None

    raw_finish = str(identity.finish or "").strip()
    finish = raw_consensus.normalize_finish_str(raw_finish) or ""
    if finish == raw_finish:
        return identity
    return replace(identity, finish=finish)


def install_global_marketplace_identity_dimension_hardening() -> None:
    """Install after the existing marketplace hardening, idempotently."""

    global _ORIGINAL_GCC_IDENTITY, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_GCC_IDENTITY = discovery.gcc_identity_from_row
    discovery.gcc_identity_from_row = gcc_identity_from_row_semantic
    _INSTALLED = True
