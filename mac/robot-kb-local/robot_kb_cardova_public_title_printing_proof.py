#!/usr/bin/env python3
"""Pure read-only proof parser for Cardova public auction page titles."""

from __future__ import annotations

from typing import Any, Mapping, Optional
from urllib.parse import urlparse

CARDOVA_HOST = "www.cardova.co.jp"
CARDOVA_PATH_PREFIX = "/en/auction/card/"
NO_RARITY_PHRASE = "No Rarity Original Print"


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _safe_url(url: object, source_id: str) -> bool:
    parsed = urlparse(_norm(url))
    return bool(
        parsed.scheme == "https"
        and parsed.hostname == CARDOVA_HOST
        and parsed.path == f"{CARDOVA_PATH_PREFIX}{source_id}"
        and not parsed.query
        and not parsed.fragment
    )


def prove_title(
    row: Mapping[str, Any], *, page_url: str, page_title: str
) -> tuple[Optional[dict[str, Any]], str]:
    source_id = _norm(row.get("source_native_record_id"))
    if not source_id or not _safe_url(page_url, source_id):
        return None, "CARDOVA_PUBLIC_URL_CONFLICT"
    if _norm(row.get("tcgdex_set_id")) != "PMCG1":
        return None, "NOT_JAPANESE_BASIC_PMGC1"
    if row.get("macro_identity_exact") is not True or row.get("finish_exact") is not True:
        return None, "MACRO_OR_FINISH_NOT_EXACT"
    if row.get("printing_exact") is True:
        return dict(row), "PRINTING_ALREADY_EXACT"

    title = _norm(page_title)
    suffix = " - Cardova Japan"
    if not title.endswith(suffix):
        return None, "CARDOVA_PUBLIC_TITLE_SUFFIX_CONFLICT"
    body = title[: -len(suffix)]

    name = _norm(row.get("card_name_provider_claim") or row.get("card_name"))
    grade = _norm(row.get("grade"))
    finish = _norm(row.get("finish"))
    if not name or not grade or finish not in {"holo", "non_holo"}:
        return None, "ROW_IDENTITY_FIELDS_MISSING"
    prefix = f"1996 {name} PSA {grade}" + (" Holo" if finish == "holo" else "")
    if body != prefix and not body.startswith(prefix + " "):
        return None, "CARDOVA_PUBLIC_TITLE_IDENTITY_CONFLICT"

    remainder = body[len(prefix):].strip()
    if not remainder.startswith(NO_RARITY_PHRASE):
        return None, "CARDOVA_PUBLIC_TITLE_NO_PRINTING_PROOF"

    material_tail = remainder[len(NO_RARITY_PHRASE):].strip()
    if material_tail:
        out = dict(row)
        out.update(
            {
                "cardova_public_title": title,
                "cardova_public_url": page_url,
                "cardova_public_no_rarity_claim_exact": True,
                "cardova_public_material_tail": material_tail,
                "printing_exact": False,
                "microvariant_exact": False,
                "exact_identity_link_candidate": False,
                "sale_transaction_ready": False,
                "v4_economic_use": False,
            }
        )
        return out, "CARDOVA_PUBLIC_TITLE_MATERIAL_TAIL_UNRESOLVED"

    out = dict(row)
    axes = dict(out.get("commercial_axes_proven") or {})
    axes["printing"] = "no_rarity_symbol"
    out.update(
        {
            "cardova_public_title": title,
            "cardova_public_url": page_url,
            "cardova_public_no_rarity_claim_exact": True,
            "cardova_public_material_tail": "",
            "printing_exact": True,
            "printing": "no_rarity_symbol",
            "printing_proof_reason": "PRINTING_EXACT_CARDOVA_PUBLIC_TITLE_NO_RARITY",
            "no_rarity_is_first_edition": False,
            "commercial_axes_proven": axes,
            "microvariant_exact": False,
            "exact_identity_link_candidate": False,
            "exact_card_sale_evidence_ready": False,
            "sale_transaction_ready": False,
            "v4_economic_use": False,
        }
    )
    return out, "PRINTING_EXACT_CARDOVA_PUBLIC_TITLE_NO_RARITY"


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_PUBLIC_TITLE_PRINTING_PROOF",
        "absence_proves_standard_printing": False,
        "material_tail_blocks_plain_no_rarity": True,
        "no_rarity_is_first_edition": False,
        "canonical_link_written": False,
        "robot_kb_write": False,
        "sale_transaction_ready": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }
