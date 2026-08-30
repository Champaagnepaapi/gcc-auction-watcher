#!/usr/bin/env python3
"""Read-only wrapper that closes Japanese Basic ordinary variants from reviewed visible rarity symbols.

The base legacy closure remains authoritative. This wrapper only handles the one
remaining bounded ambiguity class: exactly two otherwise-identical compatible
pinned-source variants where one is ordinary (no printing dimension) and one is
``printing=no_rarity_symbol``. A separately reviewed Cardova front scan with a
visible rarity symbol positively excludes the No Rarity variant.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

import robot_kb_cardova_legacy_microvariant_closure_probe as base
import robot_kb_cardova_reviewed_rarity_symbol_proof as rarity_proof


def _promote_ordinary(
    row: Mapping[str, Any], dimensions: Mapping[str, str]
) -> dict[str, Any]:
    out = dict(row)
    commercial = dict(out.get("commercial_axes_proven") or {})
    for key, value in dimensions.items():
        commercial[key] = value

    edition = dimensions.get("edition", "")
    special_finish = dimensions.get("special_finish", "")
    shadow = dimensions.get("shadow", "")

    out.update(
        {
            "pinned_source_variant_exact": True,
            "pinned_source_variant_dimensions": dict(dimensions),
            "pinned_source_variant_opaque": [],
            "pinned_source_variant_reason": "UNIQUE_ORDINARY_VARIANT_AFTER_VISIBLE_RARITY_SYMBOL_PROOF",
            "printing_applicability_exact": True,
            "printing_applicability_reason": "NO_RARITY_EXCLUDED_BY_REVIEWED_VISIBLE_RARITY_SYMBOL",
            "edition_applicability_exact": True,
            "edition_applicability_reason": (
                "PINNED_SOURCE_VARIANT_EXPLICIT"
                if edition
                else "NOT_APPLICABLE_IN_PINNED_SOURCE_VARIANT"
            ),
            "special_finish_applicability_exact": True,
            "special_finish_applicability_reason": (
                "PINNED_SOURCE_VARIANT_EXPLICIT"
                if special_finish
                else "NOT_APPLICABLE_IN_PINNED_SOURCE_VARIANT"
            ),
            "variant_applicability_exact": True,
            "variant_applicability_reason": "UNIQUE_ORDINARY_VARIANT_AFTER_VISIBLE_RARITY_SYMBOL_PROOF",
            "edition_exact": bool(edition),
            "edition": edition,
            "special_finish_exact": bool(special_finish),
            "special_finish": special_finish,
            "shadow_exact": bool(shadow),
            "shadow": shadow,
            # The positive image evidence excludes No Rarity. It does not invent
            # a provider/source value called "standard" when TCGdex represents
            # the ordinary variant by absence of a printing dimension.
            "printing_exact": False,
            "printing": "",
            "commercial_axes_proven": commercial,
            "remaining_unproven_axes": [],
            "microvariant_exact": True,
            "microvariant_reason": "UNIQUE_ORDINARY_VARIANT_AFTER_VISIBLE_RARITY_SYMBOL_PROOF",
            "exact_identity_link_candidate": True,
            "canonical_link_written": False,
            "exact_card_sale_evidence_ready": False,
            "sale_transaction_ready": False,
            "robot_kb_write": False,
            "v4_economic_use": False,
        }
    )
    return out


def close_record(
    row: Mapping[str, Any], *, source_fetcher: Callable[[str], str]
) -> tuple[Optional[dict[str, Any]], str]:
    closed, reason = base.close_record(row, source_fetcher=source_fetcher)
    if closed is not None or reason != "PINNED_SOURCE_VARIANT_AMBIGUOUS":
        return closed, reason

    if not rarity_proof.has_exact_no_rarity_exclusion(row):
        return None, reason

    expected, expected_reason = base._expected_dimensions(row)
    if expected is None:
        return None, expected_reason

    path = base._norm(row.get("pinned_source_path"))
    set_id = base._norm(row.get("tcgdex_set_id"))
    try:
        source_text = source_fetcher(path)
    except Exception:
        source_text = ""
    entries, parse_reason = base._source_variant_entries(source_text, set_id=set_id)
    if not entries:
        return None, parse_reason

    signatures: list[tuple[tuple[tuple[str, str], ...], tuple[str, ...]]] = []
    for entry in entries:
        dims, opaque = base._signature(entry)
        if any(dims.get(key) != value for key, value in expected.items()):
            continue
        signature = (tuple(sorted(dims.items())), opaque)
        if signature not in signatures:
            signatures.append(signature)

    # This proof path is deliberately limited to the observed Basic shape:
    # exactly two compatible variants, identical except for explicit No Rarity.
    if len(signatures) != 2:
        return None, "RARITY_SYMBOL_PROOF_SOURCE_SHAPE_CONFLICT"

    ordinary = []
    no_rarity = []
    for dimension_items, opaque in signatures:
        if opaque:
            return None, "RARITY_SYMBOL_PROOF_SOURCE_OPAQUE"
        dims = dict(dimension_items)
        if dims.get("printing") == "no_rarity_symbol":
            no_rarity.append(dims)
        elif "printing" not in dims:
            ordinary.append(dims)
        else:
            return None, "RARITY_SYMBOL_PROOF_OTHER_PRINTING_CONFLICT"

    if len(ordinary) != 1 or len(no_rarity) != 1:
        return None, "RARITY_SYMBOL_PROOF_SOURCE_SHAPE_CONFLICT"

    ordinary_dims = ordinary[0]
    no_rarity_dims = dict(no_rarity[0])
    no_rarity_dims.pop("printing", None)
    if ordinary_dims != no_rarity_dims:
        return None, "RARITY_SYMBOL_PROOF_VARIANTS_DIFFER_BEYOND_PRINTING"

    out = _promote_ordinary(row, ordinary_dims)
    return out, "MICROVARIANT_EXACT_VISIBLE_RARITY_SYMBOL_EXCLUDES_NO_RARITY"


def safe_summary() -> dict[str, Any]:
    safety = dict(rarity_proof.safe_summary())
    safety.update(
        {
            "mode": "READ_ONLY_CARDOVA_RARITY_SYMBOL_MICROVARIANT_CLOSURE",
            "base_legacy_closure_reused": True,
            "only_two_variant_ordinary_vs_no_rarity_shape": True,
            "exact_identity_link_candidate_only": True,
            "canonical_link_written": False,
            "robot_kb_write": False,
            "sale_transaction_ready": False,
            "v4_economic_use": False,
            "automatic_purchase": False,
            "automatic_bid": False,
            "automatic_checkout": False,
            "automatic_payment": False,
        }
    )
    return safety
