"""Exact Magi recovery for Japanese Pokemon Rumble cards.

Magi exposes these cards as ``乱戦！ポケモンスクランブル`` with a numeric
``local/016`` coordinate, while TCGdex's Japanese REST projection does not expose
the historical set. The immutable cards-database pin does expose the same
16-card product as ``ru1 / Pokemon Rumble`` in the non-Asian catalogue, plus the
repository's exact Japanese Pokemon-name translation table.

Recovery is set-level and deterministic, never card-specific:
- the final prior failure must be NO_SET_WITH_OFFICIAL_DENOMINATOR;
- current Magi product evidence must contain the exact Japanese Rumble label;
- the printed denominator must be 016;
- the pinned set file must prove id=ru1, name=Pokemon Rumble, official=16;
- the exact numbered card file must import that same set and expose one English
  card name;
- the pinned JP->EN translation table must map exactly one Japanese Pokemon name
  present in the Magi product evidence to that exact English card name.

No fuzzy matching, guessed translation, provider pricing, or per-card exception
is used. Missing/conflicting source evidence leaves the original rejection intact.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable, Optional

import japan_edge_hunter as japan
import v4_global_marketplace_magi_detail_coordinate as detail_coordinate
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_standard_source_proof as standard_source
from v4_global_market_core import CommercialIdentity


_RUMBLE_MARKER = unicodedata.normalize("NFKC", "乱戦！ポケモンスクランブル")
_SET_PATH = "data/Platinum/Pokémon Rumble.ts"
_CARD_PATH = "data/Platinum/Pokémon Rumble/{local}.ts"
_TRANSLATIONS_PATH = "scripts/utils-data/jp_card_translations.ts"
_EXPECTED_PRIOR_REASON = "target_catalog_unproven:TCGDEX_NO_SET_WITH_OFFICIAL_DENOMINATOR"
_ORIGINAL_RESOLVER = None
_INSTALLED = False


def _normalized(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or ""))


def _set_identity(text: str) -> tuple[str, str, str]:
    id_match = re.search(r"\bid\s*:\s*['\"]([^'\"]+)['\"]", text)
    name_match = re.search(
        r"\bname\s*:\s*\{.*?\ben\s*:\s*['\"]([^'\"]+)['\"]",
        text,
        re.DOTALL,
    )
    count_match = re.search(r"\bofficial\s*:\s*(\d+)", text)
    if id_match is None or name_match is None or count_match is None:
        return "", "", ""
    set_id = id_match.group(1).strip()
    set_name = name_match.group(1).strip()
    try:
        official = str(int(count_match.group(1)))
    except (TypeError, ValueError):
        return "", "", ""
    if set_id != "ru1" or set_name != "Pokémon Rumble" or official != "16":
        return "", "", ""
    return set_id, set_name, official


def _card_name_en(text: str) -> str:
    if re.search(
        r"^\s*import\s+Set\s+from\s+['\"]\.\./Pokémon Rumble['\"]\s*;?\s*$",
        text,
        re.MULTILINE,
    ) is None:
        return ""
    head = text.split("illustrator:", 1)[0]
    match = re.search(
        r"\bname\s*:\s*\{\s*en\s*:\s*['\"]([^'\"]+)['\"]",
        head,
        re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _jp_names_for_english(translation_text: str, english_name: str) -> tuple[str, ...]:
    # The pinned source map uses literal pairs: ['ヒードラン', 'Heatran'].
    # Restrict the lookup to the already-proved English card name so unrelated
    # Pokemon names elsewhere in the product title cannot participate.
    pattern = re.compile(
        rf"\[\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]{re.escape(english_name)}['\"]\s*\]"
    )
    return tuple(dict.fromkeys(match.group(1).strip() for match in pattern.finditer(translation_text)))


def source_pinned_rumble_identity(
    *,
    evidence: str,
    source_text_get: Callable[[str], Optional[str]] = standard_source._source_text,
) -> Optional[CommercialIdentity]:
    """Return one exact Japanese commercial identity or fail closed."""
    current = _normalized(japan.current_text(evidence))
    if _RUMBLE_MARKER not in current:
        return None

    full_number, _ = detail_coordinate._full_number_from_evidence(current)
    if not full_number or "/" not in full_number:
        return None
    local, denominator = full_number.split("/", 1)
    if not local.isdigit() or not denominator.isdigit() or int(denominator) != 16:
        return None
    local_int = int(local)
    if local_int < 1 or local_int > 16:
        return None

    set_text = source_text_get(_SET_PATH)
    if not set_text:
        return None
    set_id, set_name, official = _set_identity(set_text)
    if not set_id or official != "16":
        return None

    card_text = source_text_get(_CARD_PATH.format(local=local_int))
    if not card_text:
        return None
    card_name = _card_name_en(card_text)
    if not card_name:
        return None

    translations = source_text_get(_TRANSLATIONS_PATH)
    if not translations:
        return None
    jp_names = _jp_names_for_english(translations, card_name)
    matching_jp_names = tuple(name for name in jp_names if name and name in current)
    if len(matching_jp_names) != 1:
        return None

    identity = CommercialIdentity(
        name=card_name,
        set_name=set_name,
        number=f"{local_int}/16",
        language="ja",
        grader="PSA",
        grade="10",
    )
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return None
    return identity


def recover_rumble_resolution(
    ask: japan.Ask,
    original: native.MagiNativeResolution,
    *,
    source_text_get: Callable[[str], Optional[str]] = standard_source._source_text,
) -> native.MagiNativeResolution:
    if original.status != "NO_MATCH" or original.reason != _EXPECTED_PRIOR_REASON:
        return original
    evidence = detail_coordinate._current_product_evidence(ask)
    identity = source_pinned_rumble_identity(
        evidence=evidence,
        source_text_get=source_text_get,
    )
    if identity is None:
        return original
    local = identity.number.split("/", 1)[0]
    return native.MagiNativeResolution(
        "EXACT",
        "MAGI_NATIVE_TCGDEX_SOURCE_PINNED_POKEMON_RUMBLE_EXACT",
        identity=identity,
        card_id=f"ru1-{local}",
        set_id="ru1",
    )


def _resolve_with_rumble_source(ask, **kwargs):
    assert _ORIGINAL_RESOLVER is not None
    original = _ORIGINAL_RESOLVER(ask, **kwargs)
    return recover_rumble_resolution(ask, original)


def install_global_marketplace_magi_rumble_source_proof() -> None:
    global _ORIGINAL_RESOLVER, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = native.resolve_magi_native_identity
    native.resolve_magi_native_identity = _resolve_with_rumble_source
    _INSTALLED = True
