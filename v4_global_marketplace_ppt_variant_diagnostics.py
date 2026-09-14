"""PR-only diagnostics for PPT material/microvariant rejections.

The wrapper observes the already-returned PPT candidate rows. It performs no
network request, changes no match decision, and logs only bounded identity and
material fields needed to explain MICROVARIANT_UNPROVEN outcomes.
"""
from __future__ import annotations

import json
import os
from typing import Any, Mapping

import watcher
import v4_global_ppt_confirmation as ppt
import v4_multimarket_safety as safety
import v4_tcgdex_detailed_variants as detailed


_ORIGINAL_MATCH = None
_INSTALLED = False
_LOGGED = 0


def _enabled() -> bool:
    return os.getenv("GLOBAL_PPT_VARIANT_DIAGNOSTICS", "false").strip().lower() == "true"


def _max_logs() -> int:
    try:
        return max(0, min(20, int(os.getenv("GLOBAL_PPT_VARIANT_DIAGNOSTICS_MAX", "8"))))
    except ValueError:
        return 8


def _short(value: object, limit: int = 160) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _row_identity_material(row: Mapping[str, Any]) -> dict[str, object]:
    candidate = {
        "name": row.get("name"),
        "rarity": row.get("rarity"),
        "variant": " ".join(
            str(row.get(key) or "")
            for key in ("variant", "printing", "finish", "edition")
        ),
    }
    observed = safety._candidate_sensitive_dimensions(candidate)
    return {
        "name": _short(row.get("name")),
        "set_name": _short(row.get("setName") or row.get("set_name")),
        "number": _short(row.get("cardNumber") or row.get("number")),
        "language": _short(row.get("language")),
        "rarity": _short(row.get("rarity")),
        "variant": _short(row.get("variant")),
        "printing": _short(row.get("printing")),
        "finish": _short(row.get("finish")),
        "edition": _short(row.get("edition")),
        "external_catalog_id": _short(row.get("externalCatalogId")),
        "set_id": _short(row.get("setId") or row.get("set_id")),
        "sensitive_dimensions": {
            key: sorted(str(value) for value in values)
            for key, values in observed.items()
            if values
        },
    }


def _diagnostic_match(identity, canonical, rows, *, provider_set_id: str = ""):
    global _LOGGED
    assert _ORIGINAL_MATCH is not None
    result = _ORIGINAL_MATCH(
        identity,
        canonical,
        rows,
        provider_set_id=provider_set_id,
    )
    status = result[0] if isinstance(result, tuple) and result else ""
    if not _enabled() or status != "MICROVARIANT_UNPROVEN" or _LOGGED >= _max_logs():
        return result

    try:
        expected = detailed._expected_from_global_identity(identity)
        decision = detailed.detailed_variant_decision(canonical, expected)
        sanitized_rows = [
            _row_identity_material(row)
            for row in rows
            if isinstance(row, Mapping)
        ][:5]
        payload = {
            "canonical": {
                "card_id": _short(getattr(canonical, "card_id", "")),
                "set_id": _short(getattr(canonical, "set_id", "")),
                "set_name": _short(getattr(canonical, "set_name", "")),
                "number": _short(getattr(canonical, "full_number", "")),
                "language": _short(getattr(canonical, "language_code", "")),
            },
            "listing": {
                "name": _short(getattr(identity, "name", "")),
                "set_name": _short(getattr(identity, "set_name", "")),
                "number": _short(getattr(identity, "number", "")),
                "language": _short(getattr(identity, "language", "")),
                "grader": _short(getattr(identity, "grader", "")),
                "grade": _short(getattr(identity, "grade", "")),
                "edition": _short(getattr(identity, "edition", "")),
                "finish": _short(getattr(identity, "finish", "")),
                "variant": _short(getattr(identity, "variant", "")),
            },
            "expected_sensitive": expected,
            "detailed_decision": {
                "status": decision.status,
                "compatible": decision.compatible,
                "applicable_count": decision.applicable_count,
                "distinct_count": decision.distinct_count,
                "reason": decision.reason,
                "selected": (
                    decision.selected.dimension_map()
                    if decision.selected is not None
                    else {}
                ),
            },
            "provider_set_id": _short(provider_set_id),
            "rows": sanitized_rows,
        }
        watcher.log("[PPT_VARIANT_DIAG] " + json.dumps(payload, ensure_ascii=False, sort_keys=True))
        _LOGGED += 1
    except Exception as exc:
        watcher.log(f"[PPT_VARIANT_DIAG] diagnostic_error={type(exc).__name__}")
        _LOGGED += 1
    return result


def reset_ppt_variant_diagnostics() -> None:
    global _LOGGED
    _LOGGED = 0


def install_global_marketplace_ppt_variant_diagnostics() -> None:
    """Wrap the final PPT gate without changing requests or decisions."""
    global _ORIGINAL_MATCH, _INSTALLED
    if _INSTALLED or not _enabled():
        return
    current = ppt._match_canonical
    if getattr(current, "_v4_ppt_variant_diagnostics", False):
        _INSTALLED = True
        return
    _ORIGINAL_MATCH = current
    _diagnostic_match._v4_ppt_variant_diagnostics = True  # type: ignore[attr-defined]
    ppt._match_canonical = _diagnostic_match
    _INSTALLED = True
