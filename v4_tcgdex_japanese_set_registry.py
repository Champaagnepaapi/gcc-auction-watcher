from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional


REGISTRY_VERSION = "2026-08-16.1"


@dataclass(frozen=True)
class JapaneseSetRegistryEntry:
    target_names: tuple[str, ...]
    set_id: str
    expected_denominator: str
    ja_set_name: str
    provenance_url: str
    provenance_merge_sha: str
    provenance_label: str


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^0-9a-z]+", " ", text)
    return " ".join(text.split())


def _number_denominator(number: object) -> str:
    raw = unicodedata.normalize("NFKC", str(number or "")).upper().replace(" ", "")
    if "/" not in raw:
        return ""
    return raw.split("/", 1)[1].lstrip("0") or "0"


def _same_denominator(left: str, right: str) -> bool:
    a = unicodedata.normalize("NFKC", str(left or "")).upper().strip().lstrip("0") or "0"
    b = unicodedata.normalize("NFKC", str(right or "")).upper().strip().lstrip("0") or "0"
    if a.isdigit() and b.isdigit():
        return int(a) == int(b)
    return a == b


# Tiny, versioned, auditable registry. Every mapping below comes from a merged
# TCGdex cards-database PR that explicitly names the Japanese set ID and the
# corresponding English set label. No fuzzy matching or inferred translation is
# allowed when resolving entries.
JAPANESE_SET_REGISTRY: tuple[JapaneseSetRegistryEntry, ...] = (
    JapaneseSetRegistryEntry(
        target_names=("151", "Pokemon Card 151", "Pokémon Card 151"),
        set_id="SV2a",
        expected_denominator="165",
        ja_set_name="ポケモンカード151",
        provenance_url="https://github.com/tcgdex/cards-database/pull/1773",
        provenance_merge_sha="a50280dd388c60ca0685af5d0fb26b71e9095a1c",
        provenance_label="TCGdex PR #1773: SV2a ポケモンカード151 (Pokémon Card 151)",
    ),
    JapaneseSetRegistryEntry(
        target_names=("Raging Surf",),
        set_id="SV3a",
        expected_denominator="62",
        ja_set_name="レイジングサーフ",
        provenance_url="https://github.com/tcgdex/cards-database/pull/1863",
        provenance_merge_sha="ec63c8d2c47ebc8b09c8fe2e182d38fb5afa2b68",
        provenance_label="TCGdex PR #1863: SV3a レイジングサーフ (Raging Surf)",
    ),
    JapaneseSetRegistryEntry(
        target_names=("Night Wanderer",),
        set_id="SV6a",
        expected_denominator="64",
        ja_set_name="ナイトワンダラー",
        provenance_url="https://github.com/tcgdex/cards-database/pull/1870",
        provenance_merge_sha="f6106611def98e543c24c6cb5e2102d9fd85d102",
        provenance_label="TCGdex PR #1870: SV6a ナイトワンダラー (Night Wanderer)",
    ),
    JapaneseSetRegistryEntry(
        target_names=("Mega Dream Ex", "Mega Dream ex"),
        set_id="M2a",
        expected_denominator="193",
        ja_set_name="MEGAドリームex",
        provenance_url="https://github.com/tcgdex/cards-database/pull/1735",
        provenance_merge_sha="209bcf5904f6f360d1220831fe740a5c0d9f2429",
        provenance_label="TCGdex PR #1735: M2a MEGAドリームex (Mega Dream ex)",
    ),
    JapaneseSetRegistryEntry(
        target_names=("M-P Promotional", "M-P Promotional cards", "Mega Promotional Cards"),
        set_id="M-P",
        expected_denominator="M-P",
        ja_set_name="メガ プロモカード",
        provenance_url="https://github.com/tcgdex/cards-database/pull/1740",
        provenance_merge_sha="8ce0eb29d54fe1fdb54e8d32cb6f5b4ce95c29db",
        provenance_label="TCGdex PR #1740: M-P メガ プロモカード (Mega Promotional Cards)",
    ),
)


def resolve_japanese_set(target_set_name: object, card_number: object) -> tuple[Optional[JapaneseSetRegistryEntry], str]:
    key = _norm(target_set_name)
    if not key:
        return None, "REGISTRY_TARGET_SET_MISSING"

    matches = [entry for entry in JAPANESE_SET_REGISTRY if key in {_norm(alias) for alias in entry.target_names}]
    if not matches:
        return None, "REGISTRY_TARGET_SET_UNMAPPED"
    if len(matches) != 1:
        return None, "REGISTRY_TARGET_SET_AMBIGUOUS"

    entry = matches[0]
    denominator = _number_denominator(card_number)
    if not denominator:
        return None, "REGISTRY_TARGET_DENOMINATOR_MISSING"
    if not _same_denominator(denominator, entry.expected_denominator):
        return None, "REGISTRY_TARGET_DENOMINATOR_CONFLICT"
    return entry, "REGISTRY_EXACT_SET_MAPPING"
