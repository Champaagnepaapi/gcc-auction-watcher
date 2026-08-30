#!/usr/bin/env python3
"""Bounded reviewed Cardova front-image proof for Japanese Basic rarity symbols.

The manifest contains only exact Cardova SOLD rows whose public front scan was
manually reviewed on 2026-08-30. A visible printed rarity symbol (star or circle)
positively excludes the Japanese Basic No Rarity Symbol printing. This module
never infers ordinary printing from missing Cardova text and never stores images;
it binds the review to the exact Cardova source id, certificate, image filename
and SHA-256 of the reviewed public front scan.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


REVIEWED_RARITY_SYMBOL_EVIDENCE: dict[str, dict[str, str]] = {
    "01KZ5VB9KH7573R44RMZSQ6AW8": {
        "card": "Venusaur", "cert": "159075586", "set": "PMCG1", "local_id": "011",
        "grade": "9", "finish": "holo", "image_a": "38591b47-a343-4bf7-a9fd-348c91e5f418.jpg",
        "image_sha256": "f9e5b3f3b1968347b27dc0e483c4169b21fde13ae07990b9db0378c4f74734a7", "symbol": "star",
    },
    "01KZBQKT91D6G8A5G9F74XDT5Z": {
        "card": "Charizard", "cert": "156329834", "set": "PMCG1", "local_id": "021",
        "grade": "8", "finish": "holo", "image_a": "bba91134-c3a8-4857-8e1f-bd8651f7c9df.jpg",
        "image_sha256": "520fd1de64f9aec8c5d39ea1f642d9cfa1d97fb340be178e542a1214687a2c61", "symbol": "star",
    },
    "01KZN2ZR90M6JRE644RG0JY2W7": {
        "card": "Blastoise", "cert": "159624088", "set": "PMCG1", "local_id": "032",
        "grade": "10", "finish": "holo", "image_a": "1061957f-fa7e-4d03-8e7f-7de21c8d5cef.jpg",
        "image_sha256": "5ad21799e139abeceb4b4cb8bd0a42d989d064cb5ea234d2b6693eb2a802dd81", "symbol": "star",
    },
    "01KZ5VBZQ1GH40GGBS2KS4CQ9E": {
        "card": "Blastoise", "cert": "139588954", "set": "PMCG1", "local_id": "032",
        "grade": "8", "finish": "holo", "image_a": "00c26cd6-f8de-4433-b2c7-2d42115e27ff.jpg",
        "image_sha256": "dd09ae4a1ac4153941157b1bbc855e5a57528c67402d05845c067dc4c04d0da4", "symbol": "star",
    },
    "01KZAGTV1REJ84RN4NBP09NH93": {
        "card": "Weedle", "cert": "144210949", "set": "PMCG1", "local_id": "004",
        "grade": "9", "finish": "normal", "image_a": "8733deee-c0db-46f0-8451-0dad8b725ff5.jpg",
        "image_sha256": "c99846a0d12918878cf74120297ef9671bd49f7dcbcdae5176e08256737d2a3b", "symbol": "circle",
    },
    "01KZATHECDMYMZHNS1R16776KA": {
        "card": "Pikachu", "cert": "157088348", "set": "PMCG1", "local_id": "035",
        "grade": "9", "finish": "normal", "image_a": "66369259-b08c-49ff-af66-d61707e0c631.jpg",
        "image_sha256": "bcd192185fcefb99a8358a25a5ee1f18aa217a3ae6ce369cb12ed66870f399fd", "symbol": "circle",
    },
    "01KZMP7CM0F9H2193FCGX6JKAX": {
        "card": "Nidoking", "cert": "152978253", "set": "PMCG1", "local_id": "013",
        "grade": "8", "finish": "holo", "image_a": "e5d03760-deda-41a2-9280-d9ed3f00c6c9.jpg",
        "image_sha256": "716ab3621f45dfdcc1fda605fd087c50b246f117bef5c89ef7125b053cbc16dc", "symbol": "star",
    },
    "01KZBQKT89DJ5NV2GM9HKM9VGG": {
        "card": "Ninetales", "cert": "159108831", "set": "PMCG1", "local_id": "022",
        "grade": "8", "finish": "holo", "image_a": "da7ce664-5b55-4f37-8994-dfd6b5c76641.jpg",
        "image_sha256": "20dee0f63121774e2dd476c1b23868843d54efa9d99347cb44a15e2ad40766c9", "symbol": "star",
    },
    "01KZ5VDXFD6DFRYSEV43TCYQN6": {
        "card": "Poliwag", "cert": "139813616", "set": "PMCG1", "local_id": "024",
        "grade": "9", "finish": "normal", "image_a": "f9a0ae59-30fd-4cd7-83f2-81693113098a.jpg",
        "image_sha256": "50360658e203d9e4dfe68df818e4b5d137557910d04d4e0ed8126e43fa2fb8bc", "symbol": "circle",
    },
    "01M04FJ11ZW31RGAM1F5CRDWE4": {
        "card": "Zapdos", "cert": "166138355", "set": "PMCG1", "local_id": "042",
        "grade": "10", "finish": "holo", "image_a": "36a3d8fe-a31b-428b-a5ae-9efc38c03bb7.jpg",
        "image_sha256": "f99bda7d691063af013d9c0dd37624b15042306e3f88b71e0467571c6fdc8cf8", "symbol": "star",
    },
}

REVIEW_DATE = "2026-08-30"
PROOF_REASON = "NO_RARITY_EXCLUDED_REVIEWED_VISIBLE_RARITY_SYMBOL"


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _row_matches(row: Mapping[str, Any], evidence: Mapping[str, str]) -> bool:
    return bool(
        row.get("macro_identity_exact") is True
        and row.get("finish_exact") is True
        and _norm(row.get("card_name_provider_claim") or row.get("card_name")) == evidence["card"]
        and _norm(row.get("tcgdex_set_id")) == evidence["set"]
        and _norm(row.get("tcgdex_local_id")) == evidence["local_id"]
        and _norm(row.get("grade")) == evidence["grade"]
        and _norm(row.get("finish")).casefold() == evidence["finish"]
    )


def apply_reviewed_front_image_proof(
    row: Mapping[str, Any], *, certificate_number: str, image_a: str, image_sha256: str
) -> tuple[Optional[dict[str, Any]], str]:
    source_id = _norm(row.get("source_native_record_id"))
    evidence = REVIEWED_RARITY_SYMBOL_EVIDENCE.get(source_id)
    if evidence is None:
        return None, "NO_REVIEWED_RARITY_SYMBOL_EVIDENCE"
    if not _row_matches(row, evidence):
        return None, "REVIEWED_RARITY_SYMBOL_ROW_CONFLICT"
    if _norm(certificate_number) != evidence["cert"]:
        return None, "REVIEWED_RARITY_SYMBOL_CERT_CONFLICT"
    if _norm(image_a) != evidence["image_a"]:
        return None, "REVIEWED_RARITY_SYMBOL_IMAGE_NAME_CONFLICT"
    if _norm(image_sha256).casefold() != evidence["image_sha256"]:
        return None, "REVIEWED_RARITY_SYMBOL_IMAGE_HASH_CONFLICT"
    if row.get("printing_exact") is True:
        return None, "REVIEWED_RARITY_SYMBOL_PRINTING_ALREADY_EXACT"

    out = dict(row)
    out.update(
        {
            "reviewed_rarity_symbol_visible_exact": True,
            "reviewed_rarity_symbol_kind": evidence["symbol"],
            "reviewed_rarity_symbol_date": REVIEW_DATE,
            "reviewed_cardova_certificate_number": evidence["cert"],
            "reviewed_cardova_front_image_a": evidence["image_a"],
            "reviewed_cardova_front_image_sha256": evidence["image_sha256"],
            "no_rarity_symbol_excluded_exact": True,
            "no_rarity_symbol_exclusion_reason": PROOF_REASON,
            # A visible rarity symbol excludes No Rarity but does not invent a
            # synthetic provider printing value such as "standard".
            "printing_exact": False,
            "printing": "",
            "microvariant_exact": False,
            "exact_identity_link_candidate": False,
            "exact_card_sale_evidence_ready": False,
            "sale_transaction_ready": False,
            "robot_kb_write": False,
            "v4_economic_use": False,
        }
    )
    return out, PROOF_REASON


def has_exact_no_rarity_exclusion(row: Mapping[str, Any]) -> bool:
    source_id = _norm(row.get("source_native_record_id"))
    evidence = REVIEWED_RARITY_SYMBOL_EVIDENCE.get(source_id)
    if evidence is None or not _row_matches(row, evidence):
        return False
    return bool(
        row.get("reviewed_rarity_symbol_visible_exact") is True
        and row.get("no_rarity_symbol_excluded_exact") is True
        and _norm(row.get("no_rarity_symbol_exclusion_reason")) == PROOF_REASON
        and _norm(row.get("reviewed_rarity_symbol_kind")) == evidence["symbol"]
        and _norm(row.get("reviewed_cardova_certificate_number")) == evidence["cert"]
        and _norm(row.get("reviewed_cardova_front_image_a")) == evidence["image_a"]
        and _norm(row.get("reviewed_cardova_front_image_sha256")).casefold() == evidence["image_sha256"]
        and row.get("printing_exact") is not True
    )


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "REVIEWED_CARDOVA_FRONT_IMAGE_RARITY_SYMBOL_PROOF",
        "manifest_entries": len(REVIEWED_RARITY_SYMBOL_EVIDENCE),
        "positive_visible_symbol_required": True,
        "absence_of_provider_text_proves_standard": False,
        "synthetic_standard_printing_value_created": False,
        "images_stored_in_repo": False,
        "canonical_link_written": False,
        "robot_kb_write": False,
        "sale_transaction_ready": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }
