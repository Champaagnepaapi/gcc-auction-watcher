#!/usr/bin/env python3
"""Read-only corroboration of Cardova JP promo variant evidence.

This phase joins two already-produced diagnostics by Cardova source-native id:

- exact macro identity from the official Pokemon Japan printed-coordinate probe;
- Cardova's public native ``attribute`` / ``attribute2`` / ``attribute3`` fields.

Provider attributes are evidence, never truth by themselves.  The only finish
corroboration implemented here is deliberately narrow: Cardova must say exactly
``Holo`` (with no additional material token) and the *same exact official card
detail page* must itself contain an official related-link label with the literal
Japanese term ``キラカード``.  ``Holo Shiny``, ``FA``, ``SR`` and any other
provider token remain material/opaque and blocking.

A structurally proven ``*-P`` official coordinate may establish the ``promo``
printing class, but this probe still leaves edition/special-finish/variant
applicability open.  Therefore it never declares a complete microvariant and
never creates a SALE_TRANSACTION or Robot KB write.
"""

from __future__ import annotations

import argparse
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlparse
import unicodedata


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_pokemon_jp_official_probe as official_probe  # noqa: E402


DEFAULT_MAX_RECORDS = 20
HARD_MAX_RECORDS = 50
OFFICIAL_HOST = "www.pokemon-card.com"


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _compact(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", "", text).strip()


def _provider_attribute_state(value: object) -> tuple[str, str, tuple[str, ...]]:
    """Return (state, proven_finish, opaque_tokens) without guessing semantics."""

    raw = _norm(value)
    if not raw:
        return "MISSING", "", ()
    plain = re.sub(r"[^a-z0-9]+", " ", raw.casefold()).strip()
    tokens = tuple(token for token in plain.split() if token)
    if tokens == ("holo",):
        return "EXPLICIT_HOLO_ONLY", "holo", ()
    if "holo" in tokens:
        opaque = tuple(token for token in tokens if token != "holo")
        return "EXPLICIT_HOLO_PLUS_MATERIAL", "holo", opaque
    return "OPAQUE_OR_NON_FINISH", "", tokens


class _AnchorTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._current_href: Optional[str] = None
        self._parts: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.casefold() != "a" or self._current_href is not None:
            return
        href = ""
        for key, value in attrs:
            if key.casefold() == "href":
                href = str(value or "")
                break
        self._current_href = href
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None and data:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._current_href is None:
            return
        self.anchors.append((_norm(" ".join(self._parts)), self._current_href))
        self._current_href = None
        self._parts = []


def _safe_related_href(href: object) -> bool:
    raw = str(href or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return parsed.scheme == "https" and parsed.hostname == OFFICIAL_HOST
    return raw.startswith("/") or raw.startswith("card-search/")


def official_holo_labels(html: str) -> tuple[str, ...]:
    parser = _AnchorTextParser()
    parser.feed(str(html or ""))
    labels: list[str] = []
    for text, href in parser.anchors:
        if not _safe_related_href(href):
            continue
        if "キラカード" not in _compact(text):
            continue
        if text not in labels:
            labels.append(text)
    return tuple(labels)


def _load_records(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or not isinstance(payload.get("records"), list):
        raise ValueError(f"{path} must contain records[]")
    records = payload["records"]
    if any(not isinstance(item, Mapping) for item in records):
        raise ValueError(f"{path} records[] must contain objects")
    return list(records)


def _same_identity(official: Mapping[str, Any], variant: Mapping[str, Any]) -> bool:
    for key in ("source_native_record_id", "certification_number", "collector_number"):
        if not _norm(official.get(key)) or _norm(official.get(key)) != _norm(variant.get(key)):
            return False
    return True


def reconcile_record(
    official: Mapping[str, Any],
    variant: Mapping[str, Any],
    *,
    detail_fetcher: Callable[[str], str],
) -> tuple[Optional[dict[str, Any]], str]:
    if not _same_identity(official, variant):
        return None, "INPUT_IDENTITY_CONFLICT"
    if _norm(official.get("macro_identity_status")) != "EXACT":
        return None, "OFFICIAL_MACRO_NOT_EXACT"
    if official.get("official_catalog_entry_unique") is not True:
        return None, "OFFICIAL_COORDINATE_NOT_UNIQUE"
    if variant.get("japanese_structured_promo_candidate") is not True:
        return None, "NOT_STRUCTURED_JP_PROMO"

    namespace = _norm(official.get("printed_namespace"))
    if not re.fullmatch(r"[A-Za-z0-9]+-P", namespace, flags=re.IGNORECASE):
        return None, "OFFICIAL_PROMO_NAMESPACE_UNPROVEN"

    attributes = tuple(
        _norm(variant.get(key))
        for key in ("provider_attribute", "provider_attribute2", "provider_attribute3")
        if _norm(variant.get(key))
    )
    combined = " ".join(attributes)
    provider_state, provider_finish, opaque_tokens = _provider_attribute_state(combined)

    card_id = _norm(official.get("official_card_id"))
    if not re.fullmatch(r"\d{1,10}", card_id):
        return None, "OFFICIAL_CARD_ID_INVALID"
    try:
        html = detail_fetcher(card_id)
    except official_probe.OfficialBoundError as error:
        return None, str(error)
    except official_probe.OfficialProviderError as error:
        return None, str(error)
    labels = official_holo_labels(html)
    official_holo = bool(labels)
    finish_corroborated = bool(
        provider_state == "EXPLICIT_HOLO_ONLY"
        and provider_finish == "holo"
        and official_holo
    )

    unresolved = ["edition_applicability", "special_finish_applicability", "variant_applicability"]
    if not finish_corroborated:
        unresolved.insert(0, "finish")
    if opaque_tokens:
        unresolved.append("provider_material_tokens")

    row = {
        "source_native_record_id": _norm(official.get("source_native_record_id")),
        "certification_number": _norm(official.get("certification_number")),
        "card_name": _norm(official.get("card_name")),
        "collector_number": _norm(official.get("collector_number")),
        "language": _norm(official.get("language")),
        "grader": _norm(official.get("grader")),
        "grade": _norm(official.get("grade")),
        "official_card_id": card_id,
        "official_detail_url": _norm(official.get("official_detail_url")),
        "official_macro_identity_status": "EXACT",
        "printing": "promo",
        "printing_provenance": "POKEMON_JP_OFFICIAL_PROMO_NAMESPACE",
        "provider_attributes": list(attributes),
        "provider_attribute_state": provider_state,
        "provider_finish_claim": provider_finish,
        "provider_opaque_material_tokens": list(opaque_tokens),
        "official_holo_labels": list(labels),
        "official_holo_explicit": official_holo,
        "finish_holo_corroborated": finish_corroborated,
        "commercial_axes_proven": {
            "printing": "promo",
            **({"finish": "holo"} if finish_corroborated else {}),
        },
        "remaining_unproven_axes": unresolved,
        "microvariant_status": "PARTIAL_EVIDENCE_ONLY",
        "microvariant_exact": False,
        "exact_card_sale_evidence_ready": False,
        "payment_completed_at_proven": False,
        "sale_transaction_ready": False,
    }
    if finish_corroborated:
        return row, "PARTIAL_OFFICIAL_PROVIDER_FINISH_CORROBORATED"
    if opaque_tokens:
        return row, "PARTIAL_PROVIDER_MATERIAL_TOKEN_UNCORROBORATED"
    if provider_finish:
        return row, "PARTIAL_PROVIDER_FINISH_UNCORROBORATED"
    return row, "PARTIAL_PROVIDER_ATTRIBUTE_UNMAPPED"


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_JP_PROMO_VARIANT_CORROBORATION",
        "provider_attribute_is_identity_proof_alone": False,
        "official_detail_exact_card_required": True,
        "official_holo_literal_required": "キラカード",
        "premium_variant_from_provider_alone": False,
        "fuzzy_matching": False,
        "translation_assumed": False,
        "microvariant_exact": False,
        "payment_completed_at_proven": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "sale_transaction_ready": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def run(
    official_records: Sequence[Mapping[str, Any]],
    variant_records: Sequence[Mapping[str, Any]],
    *,
    max_records: int,
    detail_fetcher: Callable[[str], str],
) -> Mapping[str, Any]:
    variant_by_id = {
        _norm(record.get("source_native_record_id")): record
        for record in variant_records
        if _norm(record.get("source_native_record_id"))
    }
    selected = list(official_records[:max_records])
    rows: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    finish_corroborated = 0
    promo_printing_proven = 0

    for official in selected:
        source_id = _norm(official.get("source_native_record_id"))
        variant = variant_by_id.get(source_id)
        if variant is None:
            blocked["VARIANT_SURFACE_ROW_MISSING"] += 1
            continue
        row, reason = reconcile_record(official, variant, detail_fetcher=detail_fetcher)
        if row is None:
            blocked[reason] += 1
            continue
        promo_printing_proven += 1
        if row.get("finish_holo_corroborated") is True:
            finish_corroborated += 1
        else:
            blocked[reason] += 1
        rows.append(row)

    return {
        "selected_official_records": len(selected),
        "joined_records": len(rows),
        "promo_printing_proven_count": promo_printing_proven,
        "finish_holo_corroborated_count": finish_corroborated,
        "exact_microvariant_count": 0,
        "blocked": dict(sorted(blocked.items())),
        "records": rows,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Corroborate Cardova JP promo variant evidence")
    parser.add_argument("--official-input", type=Path, required=True)
    parser.add_argument("--variant-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--delay-seconds", type=float, default=0.35)
    args = parser.parse_args(argv)
    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")

    summary = safe_summary()
    try:
        catalog = official_probe.OfficialPokemonJpCatalog(
            delay_seconds=args.delay_seconds,
            max_detail_requests=min(args.max_records, official_probe.MAX_DETAIL_REQUESTS),
        )
        summary.update(
            run(
                _load_records(args.official_input),
                _load_records(args.variant_input),
                max_records=args.max_records,
                detail_fetcher=catalog.detail_html,
            )
        )
        summary["official_detail_requests"] = catalog.detail_requests
        code = 0
    except Exception as error:
        summary["error"] = f"{type(error).__name__}: {error}"
        code = 1

    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
