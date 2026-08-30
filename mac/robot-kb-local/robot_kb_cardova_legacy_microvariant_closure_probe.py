#!/usr/bin/env python3
"""Read-only microvariant closure for bounded exact legacy Cardova SOLD rows.

This probe composes already-validated evidence only:

1. bounded exact Cardova macro identity;
2. exact finish from the immutable pinned TCGdex card source;
3. the reviewed five-coordinate No Rarity fallback when its exact provider claim
   is present;
4. the same immutable TCGdex source file's complete ``variants`` list.

It reuses V4's detailed-variant signature semantics for finish, edition, shadow,
stamp and special-foil dimensions. The only additional source token handled here
is TCGdex's legacy ``subtype: no-rarity``, mapped to the already-reviewed
``printing=no_rarity_symbol`` axis.

A row closes only when exactly one non-opaque pinned-source variant remains after
all positively proven dimensions are required. Absence of a provider claim never
selects a premium/material variant: e.g. a Basic card with both ordinary and
``no-rarity`` source variants stays ambiguous unless No Rarity was independently
proven. When one source variant is unique, absent edition/special-finish/printing
axes are recorded as not applicable *in that pinned source variant*; no value is
invented.

This is a read-only identity candidate probe. It never writes a canonical link,
Robot KB row, SALE_TRANSACTION, V4 economic input, notification or commerce
operation.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_legacy_macro_finish_probe as finish_probe  # noqa: E402
import robot_kb_cardova_no_rarity_reviewed_fallback as no_rarity  # noqa: E402
import v4_tcgdex_detailed_variants as detailed  # noqa: E402


SOURCE_COMMIT = finish_probe.SOURCE_COMMIT
DEFAULT_MAX_RECORDS = 500
HARD_MAX_RECORDS = 500
DEFAULT_MAX_GROUPS = 20
DEFAULT_MIN_DISTINCT_DEXIDS = 2
DEFAULT_TIMEOUT_SECONDS = 4.0

_NON_IDENTITY_FIELDS = frozenset({"thirdParty", "third_party", "pricing"})
_VARIANT_FIELDS = frozenset({"type", "size", "subtype", "stamp", "foil", "languages"})
_FINISH_EXPECTED = {"normal": "non_holo", "holo": "holo", "reverse": "reverse"}
_NO_RARITY_SUBTYPES = frozenset({"no-rarity", "no-rarity-symbol"})


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _token(value: object) -> str:
    return "-".join(
        token
        for token in re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split()
        if token
    )


def _split_top_level(text: str) -> tuple[str, ...]:
    """Split comma-separated TypeScript properties without entering nested values."""

    parts: list[str] = []
    start = 0
    quote = ""
    escaped = False
    curly = square = paren = 0
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == "{":
            curly += 1
        elif char == "}":
            curly -= 1
        elif char == "[":
            square += 1
        elif char == "]":
            square -= 1
        elif char == "(":
            paren += 1
        elif char == ")":
            paren -= 1
        elif char == "," and curly == 0 and square == 0 and paren == 0:
            part = text[start:index].strip()
            if part:
                parts.append(part)
            start = index + 1
        if min(curly, square, paren) < 0:
            return ()
    if quote or curly or square or paren:
        return ()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return tuple(parts)


def _variant_objects(block: str) -> tuple[str, ...]:
    objects: list[str] = []
    start: Optional[int] = None
    quote = ""
    escaped = False
    depth = 0
    for index, char in enumerate(block):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == "{":
            if depth == 0:
                start = index + 1
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return ()
            if depth == 0 and start is not None:
                objects.append(block[start:index])
                start = None
    if quote or depth != 0:
        return ()
    return tuple(objects)


def _quoted(value: str) -> Optional[str]:
    raw = value.strip()
    match = re.fullmatch(r"(['\"])(.*)\1", raw, flags=re.DOTALL)
    if match is None:
        return None
    inner = match.group(2)
    if "\\" in inner:
        # Escaped identity tokens are not needed for the legacy cohorts and are
        # safer to keep opaque than to implement a partial JS string decoder.
        return None
    return _token(inner)


def _string_values(value: str) -> Optional[tuple[str, ...]]:
    single = _quoted(value)
    if single is not None:
        return (single,) if single else ()
    raw = value.strip()
    if not (raw.startswith("[") and raw.endswith("]")):
        return None
    inner = raw[1:-1].strip()
    if not inner:
        return ()
    pieces = _split_top_level(inner)
    if not pieces:
        return None
    parsed: list[str] = []
    for piece in pieces:
        token = _quoted(piece)
        if token is None:
            return None
        if token:
            parsed.append(token)
    return tuple(parsed)


def _source_variant_entries(text: str, *, set_id: str) -> tuple[tuple[Mapping[str, object], ...], str]:
    if not text or len(text) > 250_000:
        return (), "PINNED_SOURCE_VARIANTS_UNAVAILABLE"
    set_import = re.compile(
        rf"^\s*import\s+Set\s+from\s+['\"]\.\./{re.escape(set_id)}['\"]\s*;?\s*$",
        flags=re.MULTILINE,
    )
    if set_import.search(text) is None:
        return (), "PINNED_SOURCE_SET_IMPORT_CONFLICT"

    block = finish_probe._extract_variants_block(text)
    if not block:
        return (), "PINNED_SOURCE_VARIANTS_UNAVAILABLE"
    objects = _variant_objects(block)
    if not objects:
        return (), "PINNED_SOURCE_VARIANTS_MALFORMED"

    entries: list[Mapping[str, object]] = []
    for object_text in objects:
        properties = _split_top_level(object_text)
        if not properties:
            return (), "PINNED_SOURCE_VARIANTS_MALFORMED"
        parsed: dict[str, object] = {
            "size": "standard",
            "subtype": (),
            "stamp": (),
            "foil": (),
            "languages": (),
            "unknown_keys": (),
        }
        unknown: list[str] = []
        for property_text in properties:
            match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$", property_text, flags=re.DOTALL)
            if match is None:
                return (), "PINNED_SOURCE_VARIANTS_MALFORMED"
            key, raw_value = match.group(1), match.group(2).strip()
            if key in _NON_IDENTITY_FIELDS:
                continue
            if key not in _VARIANT_FIELDS:
                unknown.append(key)
                continue
            values = _string_values(raw_value)
            if values is None:
                return (), "PINNED_SOURCE_VARIANTS_MALFORMED"
            if key in {"type", "size"}:
                if len(values) != 1:
                    return (), "PINNED_SOURCE_VARIANTS_MALFORMED"
                parsed[key] = values[0]
            else:
                parsed[key] = values
        if not parsed.get("type"):
            return (), "PINNED_SOURCE_VARIANTS_MALFORMED"
        parsed["unknown_keys"] = tuple(sorted(set(unknown)))

        languages = tuple(str(value) for value in parsed.get("languages") or ())
        if languages:
            normalized = {detailed._normalize_language(value) for value in languages}
            if "ja" not in normalized:
                continue
        entries.append(parsed)

    if not entries:
        return (), "PINNED_SOURCE_NO_JAPANESE_VARIANT"
    return tuple(entries), "PINNED_SOURCE_VARIANTS_PARSED"


def _signature(entry: Mapping[str, object]) -> tuple[dict[str, str], tuple[str, ...]]:
    """Reuse V4 detailed-variant semantics, adding only legacy no-rarity mapping."""

    base = detailed._variant_signature(entry)
    dimensions = base.dimension_map()
    opaque = set(base.opaque)

    for subtype in entry.get("subtype") or ():
        token = str(subtype)
        if token not in _NO_RARITY_SUBTYPES:
            continue
        opaque.discard(f"subtype:{token}")
        existing = dimensions.get("printing")
        if existing and existing != "no_rarity_symbol":
            opaque.add(f"conflict:printing:{existing}:no_rarity_symbol")
        else:
            dimensions["printing"] = "no_rarity_symbol"

    return dict(sorted(dimensions.items())), tuple(sorted(opaque))


def _expected_dimensions(row: Mapping[str, Any]) -> tuple[Optional[dict[str, str]], str]:
    finish = _norm(row.get("finish")).casefold()
    expected_finish = _FINISH_EXPECTED.get(finish)
    if row.get("finish_exact") is not True or not expected_finish:
        return None, "FINISH_NOT_EXACT"
    expected = {"finish": expected_finish}

    if row.get("printing_exact") is True:
        printing = _norm(row.get("printing")).casefold()
        if printing != "no_rarity_symbol":
            return None, "PRINTING_EXACT_VALUE_UNSUPPORTED"
        expected["printing"] = printing
    if row.get("edition_exact") is True:
        edition = _norm(row.get("edition")).casefold()
        if not edition:
            return None, "EDITION_EXACT_VALUE_MISSING"
        expected["edition"] = edition
    if row.get("special_finish_exact") is True:
        special = _norm(row.get("special_finish")).casefold()
        if not special:
            return None, "SPECIAL_FINISH_EXACT_VALUE_MISSING"
        expected["special_finish"] = special
    return expected, "EXPECTED_DIMENSIONS_READY"


def _provider_material_ok(row: Mapping[str, Any]) -> tuple[bool, str]:
    raw = row.get("provider_opaque_material_tokens")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return False, "PROVIDER_MATERIAL_SURFACE_MALFORMED"
    tokens = tuple(_norm(value).casefold() for value in raw if _norm(value))
    if not tokens:
        return True, "PROVIDER_MATERIAL_CLEAR"
    if (
        tokens == ("no rarity original print",)
        and row.get("printing_exact") is True
        and _norm(row.get("printing")).casefold() == "no_rarity_symbol"
        and row.get("provider_no_rarity_claim_exact") is True
    ):
        return True, "PROVIDER_NO_RARITY_ALREADY_CORROBORATED"
    return False, "PROVIDER_MATERIAL_TOKEN_UNRESOLVED"


def close_record(
    row: Mapping[str, Any], *, source_fetcher: Callable[[str], str]
) -> tuple[Optional[dict[str, Any]], str]:
    if row.get("macro_identity_exact") is not True:
        return None, "MACRO_IDENTITY_NOT_EXACT"
    if row.get("microvariant_exact") is not False:
        return None, "INPUT_MICROVARIANT_ALREADY_PROMOTED"
    if _norm(row.get("pinned_source_commit")) != SOURCE_COMMIT:
        return None, "PINNED_SOURCE_COMMIT_CONFLICT"
    if not finish_probe._source_coordinate_ok(row):
        return None, "PINNED_SOURCE_COORDINATE_CONFLICT"

    provider_ok, provider_reason = _provider_material_ok(row)
    if not provider_ok:
        return None, provider_reason
    expected, expected_reason = _expected_dimensions(row)
    if expected is None:
        return None, expected_reason

    path = _norm(row.get("pinned_source_path"))
    set_id = _norm(row.get("tcgdex_set_id"))
    try:
        source_text = source_fetcher(path)
    except Exception:
        source_text = ""
    entries, parse_reason = _source_variant_entries(source_text, set_id=set_id)
    if not entries:
        return None, parse_reason

    signatures: list[tuple[tuple[tuple[str, str], ...], tuple[str, ...]]] = []
    for entry in entries:
        dims, opaque = _signature(entry)
        # Positive evidence must be explicitly present in the source variant.
        # This is intentionally stricter than merely rejecting conflicts.
        if any(dims.get(key) != value for key, value in expected.items()):
            continue
        signature = (tuple(sorted(dims.items())), opaque)
        if signature not in signatures:
            signatures.append(signature)

    if not signatures:
        return None, "PINNED_SOURCE_VARIANT_CONFLICT"
    if len(signatures) != 1:
        return None, "PINNED_SOURCE_VARIANT_AMBIGUOUS"

    dimension_items, opaque = signatures[0]
    if opaque:
        return None, "PINNED_SOURCE_VARIANT_OPAQUE"
    dimensions = dict(dimension_items)

    out = dict(row)
    commercial = dict(out.get("commercial_axes_proven") or {})
    for key, value in dimensions.items():
        commercial[key] = value

    edition = dimensions.get("edition", "")
    special_finish = dimensions.get("special_finish", "")
    printing = dimensions.get("printing", "")
    shadow = dimensions.get("shadow", "")

    out.update(
        {
            "pinned_source_variant_exact": True,
            "pinned_source_variant_dimensions": dimensions,
            "pinned_source_variant_opaque": [],
            "pinned_source_variant_reason": "UNIQUE_COMPATIBLE_PINNED_SOURCE_VARIANT",
            "printing_applicability_exact": True,
            "printing_applicability_reason": (
                "PINNED_SOURCE_VARIANT_EXPLICIT"
                if printing
                else "NOT_APPLICABLE_IN_PINNED_SOURCE_VARIANT"
            ),
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
            "variant_applicability_reason": "UNIQUE_COMPATIBLE_PINNED_SOURCE_VARIANT",
            "edition_exact": bool(edition),
            "edition": edition,
            "special_finish_exact": bool(special_finish),
            "special_finish": special_finish,
            "shadow_exact": bool(shadow),
            "shadow": shadow,
            # Preserve a previously corroborated printing value. Otherwise an
            # explicit source printing becomes exact only because this row has a
            # unique compatible source variant.
            "printing_exact": bool(printing) or out.get("printing_exact") is True,
            "printing": printing or _norm(out.get("printing")),
            "commercial_axes_proven": commercial,
            "remaining_unproven_axes": [],
            "microvariant_exact": True,
            "microvariant_reason": "UNIQUE_COMPATIBLE_PINNED_SOURCE_VARIANT",
            "exact_identity_link_candidate": True,
            "canonical_link_written": False,
            "exact_card_sale_evidence_ready": False,
            "sale_transaction_ready": False,
            "robot_kb_write": False,
            "v4_economic_use": False,
        }
    )
    return out, "MICROVARIANT_EXACT_UNIQUE_PINNED_SOURCE_VARIANT"


def run_records(
    payload: Mapping[str, Any], *, source_fetcher: Callable[[str], str]
) -> Mapping[str, Any]:
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("input payload has no records list")

    records: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            blocked["INPUT_ROW_MALFORMED"] += 1
            continue
        closed, reason = close_record(raw, source_fetcher=source_fetcher)
        if closed is None:
            blocked[reason] += 1
            continue
        records.append(closed)
        reasons[reason] += 1

    return {
        "unresolved_sale_transactions_available": payload.get(
            "unresolved_sale_transactions_available", 0
        ),
        "selected_records": payload.get("selected_records", len(raw_records)),
        "macro_identity_exact_count": payload.get("macro_identity_exact_count", 0),
        "finish_exact_count": payload.get("finish_exact_count", 0),
        "printing_exact_input_count": payload.get("printing_exact_count", 0),
        "source_variant_exact_count": len(records),
        "microvariant_exact_count": len(records),
        "exact_identity_link_candidate_count": len(records),
        "canonical_links_written": 0,
        "reasons": dict(sorted(reasons.items())),
        "blocked": dict(sorted(blocked.items())),
        "records": records,
    }


def run_database(
    database_url: str,
    *,
    max_records: int,
    max_groups: int,
    min_distinct_dexids: int,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    # One cache is intentionally shared by finish and variant closure, so the
    # same immutable source file is not fetched twice in one diagnostic run.
    source = finish_probe._cached_network_fetcher(timeout_seconds)
    finish_payload = finish_probe.run_database(
        database_url,
        max_records=max_records,
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
        source_fetcher=source,
    )

    # Reuse only the already-reviewed manifest. Do not retry the live PSA surface
    # that is known to return 403 from this Mac.
    reviewed_input = dict(finish_payload)
    reviewed_input["blocked"] = {}
    reviewed = no_rarity.apply_reviewed_fallback(reviewed_input)

    out = dict(
        run_records(
            reviewed,
            source_fetcher=source,
        )
    )
    for key in (
        "database_scope",
        "database_host_class",
        "database_name",
        "database_port",
        "db_read_blocked",
        "macro_blocked",
    ):
        if key in finish_payload:
            out[key] = finish_payload[key]
    out.update(
        {
            "psa_live_refetch": False,
            "reviewed_no_rarity_manifest_entries": len(no_rarity.REVIEWED_NO_RARITY_EVIDENCE),
            "reviewed_no_rarity_rows_proven": reviewed.get(
                "reviewed_no_rarity_rows_proven", 0
            ),
        }
    )
    return out


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_LEGACY_MICROVARIANT_CLOSURE",
        "database_read_only_transaction": True,
        "source_commit": SOURCE_COMMIT,
        "v4_detailed_variant_semantics_reused": True,
        "psa_live_refetch": False,
        "reviewed_no_rarity_manifest_bounded": True,
        "absence_of_provider_claim_selects_material_variant": False,
        "canonical_link_written": False,
        "robot_kb_write": False,
        "sale_transaction_ready": False,
        "sale_transaction_stored": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Close legacy Cardova microvariants from immutable TCGdex source read-only"
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--max-groups", type=int, default=DEFAULT_MAX_GROUPS)
    parser.add_argument("--min-distinct-dexids", type=int, default=DEFAULT_MIN_DISTINCT_DEXIDS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)

    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")
    if not 1 <= args.max_groups <= 50:
        parser.error("--max-groups must be between 1 and 50")
    if not 2 <= args.min_distinct_dexids <= 20:
        parser.error("--min-distinct-dexids must be between 2 and 20")
    if not 0.5 <= args.timeout_seconds <= 10.0:
        parser.error("--timeout-seconds must be between 0.5 and 10")

    try:
        payload = dict(safe_summary())
        payload.update(
            run_database(
                _norm(args.database_url),
                max_records=args.max_records,
                max_groups=args.max_groups,
                min_distinct_dexids=args.min_distinct_dexids,
                timeout_seconds=args.timeout_seconds,
            )
        )
        payload["error"] = None
        code = 0
    except Exception as error:
        payload = dict(safe_summary())
        payload["error"] = f"{type(error).__name__}: {error}"
        code = 1

    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
