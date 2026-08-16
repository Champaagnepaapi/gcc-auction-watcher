from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one replacement target, found {count}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Exact curated catalogues are a distinct, explicit proof source.
replace_once(
    "v5/microvariants.py",
    '''MICROVARIANT_APPLICABLE = "MICROVARIANT_APPLICABLE"\nMICROVARIANT_NOT_APPLICABLE = "MICROVARIANT_NOT_APPLICABLE"\nMICROVARIANT_APPLICABILITY_UNKNOWN = "MICROVARIANT_APPLICABILITY_UNKNOWN"\n\nFIRST_EDITION_CONFIRMED = "FIRST_EDITION_CONFIRMED"\n''',
    '''MICROVARIANT_APPLICABLE = "MICROVARIANT_APPLICABLE"\nMICROVARIANT_NOT_APPLICABLE = "MICROVARIANT_NOT_APPLICABLE"\nMICROVARIANT_APPLICABILITY_UNKNOWN = "MICROVARIANT_APPLICABILITY_UNKNOWN"\nCURATED_EXACT_CATALOG_SOURCE = "CURATED_EXACT_CATALOG"\nTRUSTED_EXACT_CATALOG_SOURCES = frozenset({\n    "TCGDEX_EXACT",\n    CURATED_EXACT_CATALOG_SOURCE,\n})\n\nFIRST_EDITION_CONFIRMED = "FIRST_EDITION_CONFIRMED"\n''',
)
replace_once(
    "v5/microvariants.py",
    '''        has_catalog_proof = (\n            applicability.source == "TCGDEX_EXACT"\n            and applicability.status in {MICROVARIANT_APPLICABLE, MICROVARIANT_NOT_APPLICABLE}\n        )\n''',
    '''        has_catalog_proof = (\n            applicability.source in TRUSTED_EXACT_CATALOG_SOURCES\n            and applicability.status in {MICROVARIANT_APPLICABLE, MICROVARIANT_NOT_APPLICABLE}\n        )\n''',
)


# 2) A curated entry may clear only the explicitly resolved game ambiguity.
replace_once(
    "v5/catalog_gap_registry.py",
    '''        resolved = replace(\n            identity,\n            game="Pokémon TCG",\n            set=entry.canonical_set,\n            card_number=entry.card_number,\n            year=identity.year or entry.year,\n            ambiguities=_remove_resolved_game_ambiguity(identity),\n        )\n''',
    '''        remaining_ambiguities = _remove_resolved_game_ambiguity(identity)\n        if remaining_ambiguities:\n            continue\n        resolved = replace(\n            identity,\n            game="Pokémon TCG",\n            set=entry.canonical_set,\n            card_number=entry.card_number,\n            year=identity.year or entry.year,\n            ambiguities=remaining_ambiguities,\n        )\n''',
)


# 3) Reject the digital Pokémon TCG Pocket game before physical-card identity work.
replace_once(
    "v5/ebay.py",
    '''    return False\n\n\n_TITLE_LABELS = {\n''',
    '''    return False\n\n\n_DIGITAL_TCG_POCKET_TITLE_PATTERN = re.compile(\n    r"\\bpok[eé]mon\\s+tcg\\s+pocket\\b", re.IGNORECASE\n)\n_DIGITAL_TCG_POCKET_TITLE_MARKERS = (\n    re.compile(r"\\baccount\\b", re.IGNORECASE),\n    re.compile(r"\\bhourglass(?:es)?\\b", re.IGNORECASE),\n    re.compile(r"\\binstant\\b", re.IGNORECASE),\n    re.compile(r"\\bfast\\b", re.IGNORECASE),\n    re.compile(r"\\btrade|trading\\b", re.IGNORECASE),\n)\n\n\ndef is_non_physical_pokemon_listing(\n    payload: Mapping[str, object],\n    aspects: Optional[Mapping[str, Sequence[str]]] = None,\n) -> bool:\n    """Reject deterministic digital Pokémon TCG Pocket listings.\n\n    The project is physical single-card only.  We require an explicit Pocket\n    game/set signal or the exact product name plus a digital-delivery marker;\n    a generic word such as ``pocket`` alone is never sufficient.\n    """\n\n    title = str(payload.get("title") or "").strip()\n    asp = aspects if aspects is not None else _aspects(payload)\n    game_values = _matching_values(asp, IDENTITY_ALIASES["game"])\n    set_values = _matching_values(asp, IDENTITY_ALIASES["set"])\n\n    if any(_normalize(value) == "pokemon tcg pocket" for value in game_values):\n        return True\n    if (\n        _DIGITAL_TCG_POCKET_TITLE_PATTERN.search(title)\n        and any(_normalize(value) in {"tcg pocket", "shining revelry"} for value in set_values)\n    ):\n        return True\n    if _DIGITAL_TCG_POCKET_TITLE_PATTERN.search(title) and any(\n        pattern.search(title) for pattern in _DIGITAL_TCG_POCKET_TITLE_MARKERS\n    ):\n        return True\n    return False\n\n\n_TITLE_LABELS = {\n''',
)


# 4) Wire the digital reject into the live V5 path before catalogue work.
replace_once(
    "v5/live_raw_pipeline_catalog.py",
    '''    identity_aspect_audit,\n    is_bundle_or_multi_card_listing,\n    parse_ebay_item,\n''',
    '''    identity_aspect_audit,\n    is_bundle_or_multi_card_listing,\n    is_non_physical_pokemon_listing,\n    parse_ebay_item,\n''',
)
replace_once(
    "v5/live_raw_pipeline_catalog.py",
    '''        if is_bundle_or_multi_card_listing(record.enriched):\n            _progress(\n                f"identity record {self._identity_records_seen}: early bundle/multi-card reject"\n            )\n            return None, False\n\n        initial = resolve_card_identity(\n''',
    '''        if is_non_physical_pokemon_listing(record.enriched):\n            _progress(\n                f"identity record {self._identity_records_seen}: early non-physical/digital reject"\n            )\n            return None, False\n\n        if is_bundle_or_multi_card_listing(record.enriched):\n            _progress(\n                f"identity record {self._identity_records_seen}: early bundle/multi-card reject"\n            )\n            return None, False\n\n        initial = resolve_card_identity(\n''',
)


# 5) Wire the exact curated gap after a clean TCGdex no-match, before provider fallbacks.
replace_once(
    "v5/card_identity_catalog.py",
    '''from .ebay import CardNameLookupResult, SetNumberCardNameResolver\n''',
    '''from .catalog_gap_registry import resolve_curated_catalog_gap\nfrom .ebay import CardNameLookupResult, SetNumberCardNameResolver\n''',
)
replace_once(
    "v5/card_identity_catalog.py",
    '''from .microvariants import (\n    MicrovariantApplicability,\n    tcgdex_microvariant_applicability,\n)\n''',
    '''from .microvariants import (\n    CURATED_EXACT_CATALOG_SOURCE,\n    MicrovariantApplicability,\n    tcgdex_microvariant_applicability,\n)\n''',
)
replace_once(
    "v5/card_identity_catalog.py",
    '''    alias_identity_calls_avoided_by_tcgdex_exact: int = 0\n    post_macro_applicability_attempts: int = 0\n''',
    '''    alias_identity_calls_avoided_by_tcgdex_exact: int = 0\n    curated_exact_gap_hits: int = 0\n    post_macro_applicability_attempts: int = 0\n''',
)
replace_once(
    "v5/card_identity_catalog.py",
    '''            self._identity_cache[key] = tcgdex\n            return tcgdex\n\n        poketrace = None\n''',
    '''            self._identity_cache[key] = tcgdex\n            return tcgdex\n\n        if not tcgdex.ambiguous:\n            curated = resolve_curated_catalog_gap(identity)\n            if curated is not None:\n                result = CatalogIdentityResult(\n                    identity=curated.identity,\n                    source=CURATED_EXACT_CATALOG_SOURCE,\n                    matched=True,\n                    ambiguous=False,\n                    blocking=False,\n                    microvariant_applicability=curated.applicability,\n                )\n                self.counters.curated_exact_gap_hits += 1\n                self._identity_cache[key] = result\n                return result\n\n        poketrace = None\n''',
)
replace_once(
    "v5/card_identity_catalog.py",
    '''            f"TCGdex hits: {counters.tcgdex_hits}",\n            f"Pokémon TCG API requests: {counters.pokemon_tcg_requests}",\n''',
    '''            f"TCGdex hits: {counters.tcgdex_hits}",\n            f"curated exact catalog-gap hits: {counters.curated_exact_gap_hits}",\n            f"Pokémon TCG API requests: {counters.pokemon_tcg_requests}",\n''',
)

print("patched V5 digital Pocket rejection + exact curated catalogue gap")
