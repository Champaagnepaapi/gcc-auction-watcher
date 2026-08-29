#!/usr/bin/env python3
"""Manual-only Robot KB canonical identity bootstrap from GCC + exact TCGdex.

This tool exists because the durable P3 schema intentionally does not invent
canonical cards while ingesting observations.  It is deliberately narrow:

- one explicit GCC listing per invocation;
- GCC identity comes from retained Robot KB raw payloads, not free-form input;
- all retained GCC identities for that listing must agree;
- TCGdex resolution reuses the already-proven V4 exact resolver;
- phase 1 accepts only EN/JA single Pokemon cards with one unambiguous
  normal/holo/reverse finish in TCGdex;
- premium/sensitive microvariant markers and unsupported structured variant
  fields fail closed;
- validate is the default operational path and writes nothing;
- write creates only canonical identity rows + PROVEN GCC/TCGdex identifier
  links; it never creates a market observation or SALE_TRANSACTION;
- no V4 economic use and no commercial transaction behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_GCC_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_SENSITIVE_TITLE_RE = re.compile(
    r"\b(?:first\s+edition|1st\s+edition|shadowless|master\s*ball|"
    r"poke\s*ball|cosmos|galaxy|cracked\s*ice|stamped?|promo\s+stamp)\b",
    re.I,
)
_ALLOWED_CARD_TYPES = frozenset(
    {"CARD", "CARDS", "GRADED_CARD", "POKEMON_CARD", "SINGLE_CARD", "SLAB"}
)
_LANGUAGE_CODES = {
    "EN": "en",
    "ENGLISH": "en",
    "ANGLAIS": "en",
    "JA": "ja",
    "JP": "ja",
    "JAPANESE": "ja",
    "JAPONAIS": "ja",
}
_FINISH_MAP = {
    "normal": "NON_HOLO",
    "holo": "HOLO",
    "reverse": "REVERSE_HOLO",
}
_KNOWN_VARIANT_KEYS = frozenset({"normal", "holo", "reverse", "firstedition"})


class CanonicalizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GccIdentity:
    listing_id: str
    gcc_url: str
    title: str
    card_set: str
    collector_number: str
    language_code: str
    grader: str
    grade: str
    year: Optional[int]
    structured_finish: str = ""
    structured_variant: str = ""
    structured_stamp: str = ""
    structured_edition: str = ""
    structured_shadow_treatment: str = ""

    @property
    def signature(self) -> tuple[object, ...]:
        return (
            _norm(self.title),
            _norm(self.card_set),
            _norm_number(self.collector_number),
            self.language_code,
            _norm(self.grader),
            _norm(self.grade),
            self.year,
            _norm(self.structured_finish),
            _norm(self.structured_variant),
            _norm(self.structured_stamp),
            _norm(self.structured_edition),
            _norm(self.structured_shadow_treatment),
        )


@dataclass(frozen=True)
class CanonicalPlan:
    tcgdex_card_id: str
    tcgdex_set_id: str
    tcgdex_set_name: str
    tcgdex_name: str
    language_code: str
    collector_number: str
    finish: str
    edition_stamp: str = ""
    resolver_reason: str = ""

    @property
    def profile_assignments(self) -> Mapping[str, str]:
        values = {"finish": self.finish}
        if self.edition_stamp:
            values["edition_stamp"] = self.edition_stamp
        return values

    @property
    def canonical_set_key(self) -> str:
        # Language is intentionally part of phase-1 set identity.  Robot KB has
        # no populated cross-language catalog yet, so merging language set
        # namespaces would be a stronger claim than the available evidence.
        return f"tcgdex:{self.language_code}:{self.tcgdex_set_id}"


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _norm_number(value: object) -> str:
    raw = str(value or "").strip().upper().replace(" ", "").lstrip("#")
    if "/" not in raw:
        return str(int(raw)) if raw.isdigit() else raw
    left, right = raw.split("/", 1)
    if left.isdigit():
        left = str(int(left))
    if right.isdigit():
        right = str(int(right))
    return f"{left}/{right}"


def _language_code(value: object) -> str:
    return _LANGUAGE_CODES.get(str(value or "").strip().upper(), "")


def gcc_listing_id(value: str) -> str:
    raw = value.strip()
    if _GCC_ID_RE.fullmatch(raw):
        return raw.lower()
    try:
        parsed = urlparse(raw)
    except ValueError as exc:
        raise CanonicalizationError("invalid GCC listing identifier") from exc
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in {
        "gradedcardcenter.com",
        "www.gradedcardcenter.com",
    }:
        raise CanonicalizationError("GCC listing must be a canonical HTTPS GCC URL or UUID")
    match = re.fullmatch(r"/item/([0-9a-f-]{36})/?", parsed.path, re.I)
    if match is None or _GCC_ID_RE.fullmatch(match.group(1)) is None:
        raise CanonicalizationError("GCC URL does not contain a canonical listing UUID")
    return match.group(1).lower()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (Mapping, list, tuple, set)):
            rendered = str(value).strip()
            if rendered:
                return rendered
    return ""


def _year(value: object) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if 1900 <= value <= 2100 else None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}", text):
        parsed = int(text)
        return parsed if 1900 <= parsed <= 2100 else None
    return None


def identity_from_gcc_payload(listing_id: str, payload: Mapping[str, Any]) -> GccIdentity:
    item = _mapping(payload.get("item"))
    collectible = _mapping(item.get("collectible"))
    if not item or not collectible:
        raise CanonicalizationError("retained GCC payload lacks singular item/collectible structure")

    category = _norm(collectible.get("category"))
    if category not in {"pokemon", "pokemon card", "pokemon cards"}:
        raise CanonicalizationError("GCC retained object is not explicitly Pokemon")
    item_type = re.sub(r"[^A-Z0-9]+", "_", _text(collectible.get("type"), item.get("type")).upper()).strip("_")
    if item_type not in _ALLOWED_CARD_TYPES:
        raise CanonicalizationError("GCC retained object is not explicitly an individual card")

    title = _text(item.get("title"), payload.get("title"))
    card_set = _text(collectible.get("set"), collectible.get("extension"))
    collector_number = _text(collectible.get("reference"), collectible.get("collectorNumber"))
    language_code = _language_code(_text(collectible.get("language"), item.get("language")))
    grader = _text(item.get("gradingCompany"))
    grade = _text(item.get("grade"))
    if not all((title, card_set, collector_number, language_code, grader, grade)):
        raise CanonicalizationError(
            "GCC retained identity requires title/set/collector-number/language/grader/grade"
        )

    return GccIdentity(
        listing_id=listing_id,
        gcc_url=f"https://gradedcardcenter.com/item/{listing_id}",
        title=title,
        card_set=card_set,
        collector_number=collector_number,
        language_code=language_code,
        grader=grader,
        grade=grade,
        year=_year(collectible.get("yearOfDistribution")),
        structured_finish=_text(collectible.get("finish"), item.get("finish")),
        structured_variant=_text(
            collectible.get("printVariant"), collectible.get("variant"), item.get("variant")
        ),
        structured_stamp=_text(collectible.get("stamp"), item.get("stamp")),
        structured_edition=_text(collectible.get("edition"), item.get("edition")),
        structured_shadow_treatment=_text(
            collectible.get("shadowTreatment"), item.get("shadowTreatment")
        ),
    )


def _gcc_source_record_ids(kb: Any, listing_id: str) -> list[str]:
    rows = kb.connection.execute(
        """
        SELECT record.id
        FROM external_identifier AS identifier
        JOIN external_object AS object ON object.id = identifier.external_object_id
        JOIN source_system AS source ON source.id = object.source_system_id
        JOIN source_record AS record ON record.external_object_id = object.id
        WHERE source.code = 'gcc'
          AND identifier.namespace = 'GCC_LISTING_ID'
          AND identifier.identifier_value = ?
        ORDER BY record.retrieved_at, record.id
        """,
        (listing_id,),
    ).fetchall()
    return [str(row["id"]) for row in rows]


def load_gcc_identity(kb: Any, listing_id: str) -> GccIdentity:
    record_ids = _gcc_source_record_ids(kb, listing_id)
    if not record_ids:
        raise CanonicalizationError("GCC listing is not present in Robot KB retained history")
    identities = []
    for record_id in record_ids:
        payload = kb.raw_source_payload(record_id)
        if not isinstance(payload, Mapping):
            raise CanonicalizationError("retained GCC source payload is not a JSON object")
        identities.append(identity_from_gcc_payload(listing_id, payload))
    signatures = {identity.signature for identity in identities}
    if len(signatures) != 1:
        raise CanonicalizationError("retained GCC identity changed or conflicts across history")
    return identities[-1]


def _lot_for_v4_resolver(identity: GccIdentity) -> Any:
    import watcher

    return watcher.Lot(
        url=identity.gcc_url,
        title=identity.title,
        current_price=None,
        source_type="ROBOT_KB_CANONICALIZE",
        grader=identity.grader,
        grade=identity.grade,
        card_set=identity.card_set,
        card_number=identity.collector_number,
        language="Japanese" if identity.language_code == "ja" else "English",
        year=identity.year,
    )


def resolve_tcgdex_exact(identity: GccIdentity) -> Any:
    # Reuse the proven V4 resolver instead of implementing a second matcher.
    import v4_canonical_multimarket as canonical_multimarket

    result = canonical_multimarket.resolve_tcgdex_card(_lot_for_v4_resolver(identity))
    if getattr(result, "status", "") != "EXACT":
        raise CanonicalizationError(
            f"TCGdex exact resolution failed: {getattr(result, 'status', '') or 'UNKNOWN'}"
        )
    return result


def _structured_finish_code(value: str) -> str:
    key = _norm(value)
    if not key:
        return ""
    aliases = {
        "holo": "HOLO",
        "holographic": "HOLO",
        "reverse": "REVERSE_HOLO",
        "reverse holo": "REVERSE_HOLO",
        "reverse holographic": "REVERSE_HOLO",
        "normal": "NON_HOLO",
        "non holo": "NON_HOLO",
        "non holographic": "NON_HOLO",
    }
    return aliases.get(key, "UNSUPPORTED")


def canonical_plan(identity: GccIdentity, resolved: Any) -> CanonicalPlan:
    card_id = _text(getattr(resolved, "card_id", ""))
    set_id = _text(getattr(resolved, "set_id", ""))
    set_name = _text(getattr(resolved, "set_name", ""))
    name = _text(getattr(resolved, "name", ""))
    language_code = _text(getattr(resolved, "language_code", "")).casefold()
    full_number = _norm_number(getattr(resolved, "full_number", ""))
    if not all((card_id, set_id, set_name, name, language_code, full_number)):
        raise CanonicalizationError("TCGdex exact result lacks canonical identity fields")
    if language_code != identity.language_code:
        raise CanonicalizationError("TCGdex language conflicts with retained GCC identity")
    if full_number != _norm_number(identity.collector_number):
        raise CanonicalizationError("TCGdex full collector number conflicts with retained GCC identity")

    if _SENSITIVE_TITLE_RE.search(identity.title):
        raise CanonicalizationError("sensitive microvariant marker requires a richer proof path")
    for label, value in (
        ("variant", identity.structured_variant),
        ("stamp", identity.structured_stamp),
        ("edition", identity.structured_edition),
        ("shadow treatment", identity.structured_shadow_treatment),
    ):
        if value:
            raise CanonicalizationError(f"structured GCC {label} is not supported by phase-1 bootstrap")

    variants = getattr(resolved, "variants", None)
    if not isinstance(variants, Mapping):
        raise CanonicalizationError("TCGdex variants are missing; exact finish is unproven")
    normalized_variants = {_norm(key).replace(" ", ""): value for key, value in variants.items()}
    unknown_true = [
        key
        for key, value in normalized_variants.items()
        if key not in _KNOWN_VARIANT_KEYS and value is True
    ]
    if unknown_true:
        raise CanonicalizationError("TCGdex exposes an unsupported active variant axis")
    finish_flags = {}
    for source_key in _FINISH_MAP:
        value = normalized_variants.get(source_key)
        if not isinstance(value, bool):
            raise CanonicalizationError("TCGdex normal/holo/reverse flags must be explicit booleans")
        finish_flags[source_key] = value
    active_finishes = [key for key, enabled in finish_flags.items() if enabled]
    if len(active_finishes) != 1:
        raise CanonicalizationError("TCGdex finish is ambiguous or absent")
    finish = _FINISH_MAP[active_finishes[0]]

    structured_finish = _structured_finish_code(identity.structured_finish)
    if structured_finish == "UNSUPPORTED":
        raise CanonicalizationError("structured GCC finish is unsupported")
    if structured_finish and structured_finish != finish:
        raise CanonicalizationError("structured GCC finish conflicts with TCGdex")

    edition_stamp = ""
    first_edition = normalized_variants.get("firstedition")
    if first_edition is not None and not isinstance(first_edition, bool):
        raise CanonicalizationError("TCGdex firstEdition flag must be boolean when present")
    if first_edition is True:
        edition_stamp = "FIRST_EDITION"
    # False never becomes NO_FIRST_EDITION_STAMP: absence of First Edition is
    # explicitly not a proof of Unlimited/no-stamp in this project.

    return CanonicalPlan(
        tcgdex_card_id=card_id,
        tcgdex_set_id=set_id,
        tcgdex_set_name=set_name,
        tcgdex_name=name,
        language_code=language_code,
        collector_number=full_number,
        finish=finish,
        edition_stamp=edition_stamp,
        resolver_reason=_text(getattr(resolved, "reason", "")),
    )


def _identifier_id(kb: Any, *, source_code: str, namespace: str, value: str) -> str:
    rows = kb.connection.execute(
        """
        SELECT identifier.id
        FROM external_identifier AS identifier
        JOIN external_object AS object ON object.id = identifier.external_object_id
        JOIN source_system AS source ON source.id = object.source_system_id
        WHERE source.code = ?
          AND identifier.namespace = ?
          AND identifier.identifier_value = ?
        ORDER BY identifier.id
        """,
        (source_code, namespace, value),
    ).fetchall()
    if len(rows) != 1:
        raise CanonicalizationError(
            f"expected exactly one {source_code}:{namespace} identifier; got {len(rows)}"
        )
    return str(rows[0]["id"])


def _guard_existing_links(kb: Any, identifier_id: str, expected_card_id: Optional[str] = None) -> Optional[str]:
    rows = kb.connection.execute(
        """
        SELECT resolution_state, canonical_card_id
        FROM identifier_link
        WHERE external_identifier_id = ?
        ORDER BY created_at, id
        """,
        (identifier_id,),
    ).fetchall()
    if not rows:
        return None
    proven = {row["canonical_card_id"] for row in rows if row["resolution_state"] == "PROVEN"}
    if len(proven) > 1:
        raise CanonicalizationError("identifier has contradictory PROVEN canonical links")
    if proven:
        card_id = str(next(iter(proven)))
        if expected_card_id is not None and card_id != expected_card_id:
            raise CanonicalizationError("identifier is already PROVEN to a different canonical card")
        return card_id
    raise CanonicalizationError("identifier already has a non-PROVEN resolution history")


def persist_plan(kb: Any, identity: GccIdentity, plan: CanonicalPlan) -> Mapping[str, Any]:
    from robot_kb.domain import ResolutionState

    gcc_identifier_id = _identifier_id(
        kb,
        source_code="gcc",
        namespace="GCC_LISTING_ID",
        value=identity.listing_id,
    )
    existing_gcc_card = _guard_existing_links(kb, gcc_identifier_id)

    with kb._transaction():
        set_id = kb.create_canonical_set(
            plan.canonical_set_key,
            plan.tcgdex_set_name,
        )
        family_id = kb.create_card_family(
            set_id,
            plan.collector_number,
            plan.tcgdex_name,
        )
        localized_id = kb.create_localized_card(
            family_id,
            plan.language_code,
            plan.tcgdex_name,
            localized_set_name=plan.tcgdex_set_name,
        )
        profile_id = kb.create_variant_profile(
            plan.profile_assignments,
            label=f"TCGdex exact {plan.tcgdex_card_id}",
        )
        kb.allow_variant_profile(family_id, profile_id)
        card_id = kb.create_canonical_card(localized_id, profile_id)

        if existing_gcc_card is not None and existing_gcc_card != card_id:
            raise CanonicalizationError("existing GCC PROVEN link conflicts with exact TCGdex plan")

        tcgdex_source_id = kb.create_source_system(
            "tcgdex_catalog",
            "TCGdex exact catalog identity",
            "CATALOG",
        )
        tcgdex_object_id = kb.create_external_object(
            tcgdex_source_id,
            "CATALOG_CARD",
            plan.tcgdex_card_id,
        )
        tcgdex_identifier_id = kb.add_external_identifier(
            tcgdex_object_id,
            "TCGDEX_CARD_ID",
            plan.tcgdex_card_id,
        )
        existing_tcgdex_card = _guard_existing_links(
            kb,
            tcgdex_identifier_id,
            expected_card_id=card_id,
        )
        if existing_tcgdex_card is None:
            kb.link_identifier(
                tcgdex_identifier_id,
                ResolutionState.PROVEN,
                canonical_card_id=card_id,
            )
        if existing_gcc_card is None:
            kb.link_identifier(
                gcc_identifier_id,
                ResolutionState.PROVEN,
                canonical_card_id=card_id,
            )

    return {
        "canonical_card_id": card_id,
        "canonical_set_id": set_id,
        "card_family_id": family_id,
        "localized_card_id": localized_id,
        "variant_profile_id": profile_id,
        "gcc_link_already_proven": existing_gcc_card is not None,
        "tcgdex_link_already_proven": existing_tcgdex_card is not None,
    }


def safe_summary(*, mode: str, listing_id: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "gcc_listing_id": listing_id,
        "gcc_identity_consistent": False,
        "tcgdex_exact": False,
        "microvariant_proven": False,
        "canonical_card_resolved": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate or manually persist one exact GCC -> TCGdex canonical identity"
    )
    parser.add_argument("mode", choices=("validate", "write"))
    parser.add_argument("--gcc-listing", required=True, help="GCC item UUID or canonical item URL")
    args = parser.parse_args(argv)

    try:
        listing_id = gcc_listing_id(args.gcc_listing)
    except CanonicalizationError as exc:
        print(json.dumps({"mode": args.mode, "error": str(exc), "robot_kb_write": False}, sort_keys=True))
        return 2

    summary = safe_summary(mode=args.mode, listing_id=listing_id)
    database = os.getenv("ROBOT_KB_DATABASE_URL", "").strip()
    if not database:
        summary["error"] = "ROBOT_KB_DATABASE_URL is required"
        print(json.dumps(summary, sort_keys=True))
        return 2

    try:
        from robot_kb.repository import KnowledgeBase

        with KnowledgeBase.open(database) as kb:
            identity = load_gcc_identity(kb, listing_id)
            summary["gcc_identity_consistent"] = True
            summary["gcc_identity"] = asdict(identity)
            resolved = resolve_tcgdex_exact(identity)
            summary["tcgdex_exact"] = True
            plan = canonical_plan(identity, resolved)
            summary["microvariant_proven"] = True
            summary["plan"] = asdict(plan)
            if args.mode == "write":
                persisted = persist_plan(kb, identity, plan)
                summary.update(persisted)
                summary["robot_kb_write"] = True
                summary["canonical_card_resolved"] = True
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except CanonicalizationError as exc:
        summary["error"] = str(exc)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as exc:
        # Do not echo environment variables or retained raw payloads on failure.
        summary["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
