"""Recover measured Magi Classic promo coordinates without inventing identity.

Some Magi listings print ``(CLL) ... CLL007/032`` or ``(CLK) ... CLK003/032``.
The generic collector parser sees the fraction but cannot derive a set code.
This wrapper accepts only the measured CLL/CLK forms when the same prefix is
independently echoed as a standalone provider token. It then emits numeric
localId + exact provider prefix so the existing TCGdex resolver must still prove
the card. Missing TCGdex catalogue support remains NO_MATCH.
"""
from __future__ import annotations

import re
import unicodedata

import japan_edge_hunter as japan
import v4_global_marketplace_magi_detail_coordinate as detail
import v4_global_marketplace_magi_native_identity as native


_SUPPORTED_PREFIXES = frozenset({"CLL", "CLK"})
_PREFIXED_LOCAL_RE = re.compile(r"^([A-Z]{3})(\d{2,4})$", re.I)
_ORIGINAL_PREFLIGHT = None
_INSTALLED = False


def _prefixed_coordinate(text: str) -> tuple[str, str, str]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).upper()
    coordinates: set[tuple[str, str]] = set()
    for match in japan.CARD_RE.finditer(normalized):
        local_raw, denominator = match.group(1), match.group(2)
        local_match = _PREFIXED_LOCAL_RE.fullmatch(local_raw)
        if local_match is None or not denominator.isdigit():
            continue
        prefix = local_match.group(1).upper()
        if prefix not in _SUPPORTED_PREFIXES:
            continue
        # The prefix must also appear independently from the prefixed fraction,
        # e.g. ``(CLL)``. The prefix embedded inside ``CLL007`` is insufficient.
        standalone = re.compile(
            rf"(?<![A-Z0-9]){re.escape(prefix)}(?![A-Z0-9])",
            re.I,
        )
        scrubbed = normalized[: match.start()] + " " + normalized[match.end() :]
        if standalone.search(scrubbed) is None:
            continue
        local = str(int(local_match.group(2)))
        denom = str(int(denominator))
        coordinates.add((f"{local}/{denom}", prefix))
    if not coordinates:
        return "", "", "set_code_unproven"
    if len(coordinates) != 1:
        return "", "", "collector_number_ambiguous"
    full_number, set_code = next(iter(coordinates))
    return full_number, set_code, "magi_native_prefixed_promo_coordinate_parsed"


def _preflight_with_prefixed_promo(ask: japan.Ask) -> tuple[str, str, str]:
    assert _ORIGINAL_PREFLIGHT is not None
    original = _ORIGINAL_PREFLIGHT(ask)
    if original[2] != "set_code_unproven":
        return original
    evidence = detail._current_product_evidence(ask)
    return _prefixed_coordinate(evidence)


def install_global_marketplace_magi_prefixed_promo_coordinate() -> None:
    global _ORIGINAL_PREFLIGHT, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_PREFLIGHT = native._preflight
    native._preflight = _preflight_with_prefixed_promo
    _INSTALLED = True
