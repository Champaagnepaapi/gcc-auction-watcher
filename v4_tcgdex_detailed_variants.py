from __future__ import annotations

from dataclasses import dataclass, replace
import re
import sys
from typing import Any, Mapping, Sequence

import watcher
import v4_canonical_multimarket as canonical
import v4_raw_consensus as raw_consensus


# Stored inside CanonicalCard.variants so the existing CanonicalCard/lot handoff
# remains backward compatible.  These keys are internal provenance only; they
# are never provider pricing and never become graded fair value.
DETAILED_STATE_KEY = "__tcgdex_variants_detailed_state__"
DETAILED_ENTRIES_KEY = "__tcgdex_variants_detailed_entries__"
DETAILED_SCHEMA_KEY = "__tcgdex_variants_detailed_schema__"
DETAILED_SCHEMA_VERSION = 1

_ALLOWED_TYPES = frozenset({"normal", "holo", "reverse", "metal", "lenticular"})
_ALLOWED_SIZES = frozenset({"standard", "jumbo"})
_IGNORED_NON_IDENTITY_KEYS = frozenset({"pricing", "thirdParty", "third_party"})
_KNOWN_KEYS = frozenset(
    {
        "type",
        "size",
        "subtype",
        "stamp",
        "foil",
        "languages",
        *_IGNORED_NON_IDENTITY_KEYS,
    }
)
_FINISH_BY_TYPE = {
    "normal": "non_holo",
    "holo": "holo",
    "reverse": "reverse",
}
_SPECIAL_FINISH_BY_FOIL = {
    "pokeball": "poke_ball",
    "poke-ball": "poke_ball",
    "masterball": "master_ball",
    "master-ball": "master_ball",
    "cosmos": "cosmos",
    "galaxy": "galaxy",
    "cracked-ice": "cracked_ice",
    "crackedice": "cracked_ice",
}
_LANGUAGE_ALIASES = {
    "jp": "ja",
    "japanese": "ja",
    "english": "en",
    "french": "fr",
    "german": "de",
    "spanish": "es",
    "italian": "it",
    "portuguese": "pt",
    "korean": "ko",
    "chinese": "zh-tw",
}

_ORIGINAL_VALIDATE = canonical._validate_tcgdex_card
_ORIGINAL_CANDIDATE = None
_ORIGINAL_PPT_MATCH = None
_INSTALLED_VALIDATE = False
_INSTALLED_CANDIDATE = False
_INSTALLED_PPT = False
_LIVE_LOGGED = 0
_MAX_LIVE_LOGS = 5


@dataclass(frozen=True)
class DetailedVariantSignature:
    dimensions: tuple[tuple[str, str], ...]
    opaque: tuple[str, ...] = ()

    def dimension_map(self) -> dict[str, str]:
        return dict(self.dimensions)


@dataclass(frozen=True)
class DetailedVariantDecision:
    status: str
    compatible: bool
    selected: DetailedVariantSignature | None = None
    applicable_count: int = 0
    distinct_count: int = 0
    reason: str = ""


def _norm_token(value: object) -> str:
    return "-".join(
        token
        for token in re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split()
        if token
    )


def _normalize_language(value: object) -> str:
    token = _norm_token(value)
    return _LANGUAGE_ALIASES.get(token, token)


def _string_values(value: object, *, allow_many: bool) -> tuple[str, ...] | None:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        values = (value,)
    elif allow_many and isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if any(not isinstance(item, str) for item in value):
            return None
        values = tuple(value)
    else:
        return None
    cleaned = tuple(_norm_token(item) for item in values if _norm_token(item))
    return cleaned


def sanitize_variants_detailed(
    raw: object,
    *,
    language_code: str,
) -> tuple[str, tuple[Mapping[str, object], ...]]:
    """Validate TCGdex variants_detailed without consuming its pricing.

    Missing/empty data is neutral because TCGdex has documented catalogue gaps.
    A present malformed structure is fail-closed. Language-scoped variants are
    retained only for the already-proven exact canonical language.
    """

    if raw is None:
        return "ABSENT", ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return "MALFORMED", ()
    if not raw:
        return "EMPTY", ()

    language = _normalize_language(language_code)
    output: list[Mapping[str, object]] = []
    had_structural_entry = False
    for item in raw:
        if not isinstance(item, Mapping):
            return "MALFORMED", ()
        had_structural_entry = True
        variant_type = _norm_token(item.get("type"))
        if variant_type not in _ALLOWED_TYPES:
            return "MALFORMED", ()

        size = _norm_token(item.get("size")) or "standard"
        if size not in _ALLOWED_SIZES:
            return "MALFORMED", ()

        languages = _string_values(item.get("languages"), allow_many=True)
        if languages is None:
            return "MALFORMED", ()
        normalized_languages = tuple(_normalize_language(value) for value in languages)
        if normalized_languages and language not in normalized_languages:
            continue

        subtype = _string_values(item.get("subtype"), allow_many=True)
        stamp = _string_values(item.get("stamp"), allow_many=True)
        foil = _string_values(item.get("foil"), allow_many=True)
        if subtype is None or stamp is None or foil is None:
            return "MALFORMED", ()

        unknown_keys = tuple(
            sorted(str(key) for key in item.keys() if str(key) not in _KNOWN_KEYS)
        )
        # Deliberately do not copy pricing/thirdParty. They are RAW/provider
        # context and cannot become graded-slab valuation evidence here.
        output.append(
            {
                "type": variant_type,
                "size": size,
                "subtype": subtype,
                "stamp": stamp,
                "foil": foil,
                "languages": normalized_languages,
                "unknown_keys": unknown_keys,
            }
        )

    if had_structural_entry and not output:
        return "NO_LANGUAGE_VARIANT", ()
    return "USABLE", tuple(output)


def _assign_dimension(
    dimensions: dict[str, str],
    opaque: set[str],
    dimension: str,
    value: str,
) -> None:
    """Record one material dimension without last-write-wins ambiguity.

    A single TCGdex detailed entry can itself contain multiple subtype/stamp/foil
    tokens. If two of those tokens assert incompatible values for the same
    commercial axis, the entry is internally contradictory and must remain
    blocking. Repeating the same value is harmless.
    """

    existing = dimensions.get(dimension)
    if existing is None:
        dimensions[dimension] = value
        return
    if existing == value:
        return
    first, second = sorted((existing, value))
    opaque.add(f"conflict:{dimension}:{first}:{second}")


def _variant_signature(entry: Mapping[str, object]) -> DetailedVariantSignature:
    dimensions: dict[str, str] = {}
    opaque: set[str] = set()

    variant_type = str(entry.get("type") or "")
    if variant_type in _FINISH_BY_TYPE:
        _assign_dimension(dimensions, opaque, "finish", _FINISH_BY_TYPE[variant_type])
    elif variant_type:
        opaque.add(f"type:{variant_type}")

    size = str(entry.get("size") or "standard")
    if size != "standard":
        opaque.add(f"size:{size}")

    for subtype in entry.get("subtype") or ():
        token = str(subtype)
        if token == "shadowless":
            _assign_dimension(dimensions, opaque, "shadow", "shadowless")
        elif token == "unlimited":
            _assign_dimension(dimensions, opaque, "edition", "unlimited")
        else:
            parsed = raw_consensus.parse_multilingual_commercial_dimensions(
                token.replace("-", " ")
            )
            if parsed and all(value != "__conflict__" for value in parsed.values()):
                for key, value in parsed.items():
                    if key in watcher.SENSITIVE_COMMERCIAL_DIMENSIONS:
                        _assign_dimension(dimensions, opaque, key, value)
            else:
                opaque.add(f"subtype:{token}")

    for stamp in entry.get("stamp") or ():
        token = str(stamp)
        if token == "1st-edition":
            _assign_dimension(dimensions, opaque, "edition", "first_edition")
        else:
            # A generic "stamped" claim is not enough to identify a specific
            # stamp. Preserve the exact upstream token as an opaque material axis.
            opaque.add(f"stamp:{token}")

    for foil in entry.get("foil") or ():
        token = str(foil)
        special = _SPECIAL_FINISH_BY_FOIL.get(token)
        if special:
            _assign_dimension(dimensions, opaque, "special_finish", special)
        else:
            opaque.add(f"foil:{token}")

    for unknown in entry.get("unknown_keys") or ():
        opaque.add(f"field:{unknown}")

    return DetailedVariantSignature(
        dimensions=tuple(sorted(dimensions.items())),
        opaque=tuple(sorted(opaque)),
    )


def _detailed_payload(canonical_card: canonical.CanonicalCard) -> tuple[str, tuple[Mapping[str, object], ...]]:
    variants = canonical_card.variants if isinstance(canonical_card.variants, Mapping) else {}
    state = str(variants.get(DETAILED_STATE_KEY) or "ABSENT")
    entries = variants.get(DETAILED_ENTRIES_KEY) or ()
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        return "MALFORMED", ()
    normalized = tuple(item for item in entries if isinstance(item, Mapping))
    if len(normalized) != len(entries):
        return "MALFORMED", ()
    return state, normalized


def _legacy_finish_choices(canonical_card: canonical.CanonicalCard) -> set[str]:
    variants = canonical_card.variants if isinstance(canonical_card.variants, Mapping) else {}
    return {
        finish
        for finish, key in (("non_holo", "normal"), ("holo", "holo"), ("reverse", "reverse"))
        if variants.get(key) is True
    }


def _source_pinned_finish_choices(canonical_card: canonical.CanonicalCard) -> set[str]:
    if str(canonical_card.language_code or "").strip().casefold() not in {"ja", "jp"}:
        return set()
    # Import lazily: source-pinned finish imports canonical and the detailed
    # installer is intentionally layered after it at runtime.
    try:
        from v4_tcgdex_source_pinned_finish import source_pinned_finish_proof

        proof = source_pinned_finish_proof(canonical_card)
    except Exception:
        return set()
    if proof is None:
        return set()
    return {
        {"normal": "non_holo", "holo": "holo", "reverse": "reverse"}[finish]
        for finish in proof.finishes
        if finish in {"normal", "holo", "reverse"}
    }


def _expected_from_lot(lot: watcher.Lot) -> dict[str, str]:
    expected = dict(watcher.expected_commercial_dimensions(lot))
    return {
        key: str(value)
        for key, value in expected.items()
        if key in watcher.SENSITIVE_COMMERCIAL_DIMENSIONS and value not in (None, "")
    }


def _expected_from_global_identity(identity: object) -> dict[str, str]:
    expected: dict[str, str] = {}
    edition_raw = str(getattr(identity, "edition", "") or "")
    finish_raw = str(getattr(identity, "finish", "") or "")
    variant_raw = str(getattr(identity, "variant", "") or "")

    edition = raw_consensus.normalize_edition_str(edition_raw)
    finish = raw_consensus.normalize_finish_str(finish_raw)
    if edition:
        expected["edition"] = edition
    if finish:
        expected["finish"] = finish

    decomposed = raw_consensus.decompose_commercial_variant(variant_raw)
    for key in ("edition", "finish", "special_finish", "printing"):
        value = decomposed.get(key)
        if value:
            if key in expected and expected[key] != value:
                expected[key] = "__conflict__"
            else:
                expected[key] = value
    return expected


def detailed_variant_decision(
    canonical_card: canonical.CanonicalCard,
    expected: Mapping[str, str],
) -> DetailedVariantDecision:
    state, entries = _detailed_payload(canonical_card)
    if state in {"ABSENT", "EMPTY"}:
        return DetailedVariantDecision(state, True, reason="fallback legacy/source")
    if state == "MALFORMED":
        return DetailedVariantDecision(state, False, reason="variants_detailed malformed")
    if state == "NO_LANGUAGE_VARIANT":
        return DetailedVariantDecision(state, False, reason="no detailed variant for exact language")
    if state != "USABLE" or not entries:
        return DetailedVariantDecision(state, False, reason="unsupported detailed state")
    if any(value == "__conflict__" for value in expected.values()):
        return DetailedVariantDecision("LISTING_CONFLICT", False, reason="listing dimensions conflict")

    signatures = tuple(dict.fromkeys(_variant_signature(entry) for entry in entries))
    source_finishes = _source_pinned_finish_choices(canonical_card)
    legacy_finishes = _legacy_finish_choices(canonical_card)
    authoritative_finishes = source_finishes or legacy_finishes

    compatible: list[DetailedVariantSignature] = []
    for signature in signatures:
        dims = signature.dimension_map()
        finish = dims.get("finish")
        if finish and authoritative_finishes and finish not in authoritative_finishes:
            continue
        conflict = False
        for dimension, expected_value in expected.items():
            observed = dims.get(dimension)
            if observed and observed != expected_value:
                conflict = True
                break
        if not conflict:
            compatible.append(signature)

    distinct = tuple(dict.fromkeys(compatible))
    if not distinct:
        return DetailedVariantDecision(
            "CONFLICT",
            False,
            applicable_count=len(entries),
            distinct_count=0,
            reason="detailed variant conflicts with listing/source/legacy",
        )

    expected_finish = expected.get("finish")
    if source_finishes and len(source_finishes) > 1 and not expected_finish:
        return DetailedVariantDecision(
            "AMBIGUOUS",
            False,
            applicable_count=len(entries),
            distinct_count=max(len(distinct), len(source_finishes)),
            reason="source-pinned finish remains multi-variant",
        )
    if expected_finish and source_finishes and expected_finish not in source_finishes:
        return DetailedVariantDecision(
            "CONFLICT",
            False,
            applicable_count=len(entries),
            distinct_count=len(distinct),
            reason="listing finish conflicts with source-pinned catalogue",
        )

    if len(distinct) != 1:
        return DetailedVariantDecision(
            "AMBIGUOUS",
            False,
            applicable_count=len(entries),
            distinct_count=len(distinct),
            reason="multiple material detailed variants remain",
        )

    selected = distinct[0]
    if selected.opaque:
        return DetailedVariantDecision(
            "OPAQUE_MATERIAL_VARIANT",
            False,
            selected=selected,
            applicable_count=len(entries),
            distinct_count=1,
            reason="unsupported material detailed variant axis",
        )
    return DetailedVariantDecision(
        "EXACT",
        True,
        selected=selected,
        applicable_count=len(entries),
        distinct_count=1,
        reason="unique compatible detailed variant",
    )


def _effective_canonical(
    canonical_card: canonical.CanonicalCard,
    decision: DetailedVariantDecision,
) -> canonical.CanonicalCard:
    if decision.status != "EXACT" or decision.selected is None:
        return canonical_card
    dims = decision.selected.dimension_map()
    finish = dims.get("finish")
    if not finish:
        return canonical_card

    # Never narrow the immutable Japanese source proof. For other exact cards,
    # a present, unique, structurally valid variants_detailed entry may narrow
    # stale legacy normal/holo/reverse booleans for this provider decision only.
    if _source_pinned_finish_choices(canonical_card):
        return canonical_card
    variants = dict(canonical_card.variants) if isinstance(canonical_card.variants, Mapping) else {}
    for key, mapped in (("normal", "non_holo"), ("holo", "holo"), ("reverse", "reverse")):
        variants[key] = mapped == finish
    return replace(canonical_card, variants=variants)


def _validate_with_detailed_variants(
    lot: watcher.Lot,
    card: Mapping[str, Any],
    *,
    language_code: str,
    unique_name_number: bool,
    reason: str,
):
    global _LIVE_LOGGED
    result = _ORIGINAL_VALIDATE(
        lot,
        card,
        language_code=language_code,
        unique_name_number=unique_name_number,
        reason=reason,
    )
    if result is None or result.status != "EXACT" or "variants_detailed" not in card:
        return result

    state, entries = sanitize_variants_detailed(
        card.get("variants_detailed"), language_code=language_code
    )
    variants = dict(result.variants) if isinstance(result.variants, Mapping) else {}
    variants[DETAILED_SCHEMA_KEY] = DETAILED_SCHEMA_VERSION
    variants[DETAILED_STATE_KEY] = state
    variants[DETAILED_ENTRIES_KEY] = entries
    if _LIVE_LOGGED < _MAX_LIVE_LOGS:
        watcher.log(
            "TCGdex variants_detailed: "
            f"{result.card_id} | state={state} | applicable={len(entries)} | "
            f"language={language_code}"
        )
        _LIVE_LOGGED += 1
    return replace(result, variants=variants)


def _candidate_with_detailed_variants(
    lot: watcher.Lot,
    canonical_card: canonical.CanonicalCard,
    candidate: Mapping[str, Any],
) -> bool:
    assert _ORIGINAL_CANDIDATE is not None
    decision = detailed_variant_decision(canonical_card, _expected_from_lot(lot))
    if not decision.compatible:
        return False
    effective = _effective_canonical(canonical_card, decision)
    return bool(_ORIGINAL_CANDIDATE(lot, effective, candidate))


def _ppt_match_with_detailed_variants(identity, canonical_card, rows, *, provider_set_id: str = ""):
    assert _ORIGINAL_PPT_MATCH is not None
    decision = detailed_variant_decision(
        canonical_card, _expected_from_global_identity(identity)
    )
    if not decision.compatible:
        return "MICROVARIANT_UNPROVEN", None, f"TCGDEX_VARIANTS_DETAILED_{decision.status}"
    effective = _effective_canonical(canonical_card, decision)
    return _ORIGINAL_PPT_MATCH(
        identity, effective, rows, provider_set_id=provider_set_id
    )


def install_v4_tcgdex_detailed_variants() -> None:
    """Install detailed-variant proof over the existing exact TCGdex stack.

    This does not create a resolver. It decorates the already-exact card detail,
    then wraps the final provider gates. Missing detailed data preserves the
    existing legacy/source behavior; malformed/conflicting material detail fails
    closed. Global PPT is wrapped only when that module is already loaded.
    """

    global _INSTALLED_VALIDATE, _INSTALLED_CANDIDATE, _INSTALLED_PPT
    global _ORIGINAL_CANDIDATE, _ORIGINAL_PPT_MATCH

    if not _INSTALLED_VALIDATE:
        canonical._validate_tcgdex_card = _validate_with_detailed_variants
        _INSTALLED_VALIDATE = True

    current_candidate = canonical._candidate_exact_for_canonical
    if not getattr(current_candidate, "_v4_tcgdex_detailed_variants", False):
        _ORIGINAL_CANDIDATE = current_candidate
        _candidate_with_detailed_variants._v4_tcgdex_detailed_variants = True  # type: ignore[attr-defined]
        canonical._candidate_exact_for_canonical = _candidate_with_detailed_variants
        _INSTALLED_CANDIDATE = True

    ppt = sys.modules.get("v4_global_ppt_confirmation")
    if ppt is not None:
        current_ppt = getattr(ppt, "_match_canonical", None)
        if current_ppt is not None and not getattr(current_ppt, "_v4_tcgdex_detailed_variants", False):
            _ORIGINAL_PPT_MATCH = current_ppt
            _ppt_match_with_detailed_variants._v4_tcgdex_detailed_variants = True  # type: ignore[attr-defined]
            ppt._match_canonical = _ppt_match_with_detailed_variants
            _INSTALLED_PPT = True
