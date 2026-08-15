from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Sequence


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _number_parts(value: object) -> tuple[str, str]:
    compact = re.sub(r"\s+", "", str(value or "")).lstrip("#")
    if not compact:
        return "", ""
    numerator, _, denominator = compact.partition("/")

    def canonical(part: str) -> str:
        token = re.sub(r"[^A-Za-z0-9]+", "", part).casefold()
        if token.isdigit():
            return str(int(token))
        match = re.fullmatch(r"([a-z]+)0*(\d+)", token)
        if match:
            return f"{match.group(1)}{int(match.group(2))}"
        return token

    return canonical(numerator), canonical(denominator)


def _language(value: object) -> str:
    token = _norm(value)
    aliases = {
        "english": "en", "anglais": "en", "en": "en",
        "french": "fr", "francais": "fr", "fr": "fr",
        "japanese": "ja", "japonais": "ja", "jp": "ja", "ja": "ja",
    }
    return aliases.get(token, token)


@dataclass(frozen=True)
class CatalogCard:
    catalog_id: str
    name: str
    set_name: str
    number: str
    language: str
    denominator: str = ""
    snapshot_version: str = ""


@dataclass(frozen=True)
class IdentityClues:
    name: str | None = None
    set_name: str | None = None
    number: str | None = None
    language: str | None = None

    def supplied_fields(self) -> tuple[str, ...]:
        return tuple(
            field
            for field, value in (
                ("name", self.name),
                ("set_name", self.set_name),
                ("number", self.number),
                ("language", self.language),
            )
            if value not in (None, "")
        )


@dataclass(frozen=True)
class CardinalityResult:
    status: ResolutionStatus
    candidate_count: int
    snapshot_version: str
    supplied_fields: tuple[str, ...]
    inferred_fields: tuple[str, ...] = ()
    card: CatalogCard | None = None
    candidate_ids: tuple[str, ...] = ()


class CatalogCardinalityIndex:
    """Exact local catalog cardinality resolver.

    Every supplied clue is an exact constraint. No fuzzy matching, substring
    similarity or guessed translation is used as identity proof. Exactly one
    compatible row resolves macro identity; zero remains unresolved; more than
    one remains ambiguous.

    Language remains a commercial identity dimension and localized rows are not
    silently collapsed. Microvariants (edition/finish/stamp/etc.) are outside
    this macro resolver and must still pass a separate deterministic gate.
    """

    def __init__(self, rows: Sequence[CatalogCard], *, snapshot_version: str) -> None:
        self.rows = tuple(rows)
        self.snapshot_version = snapshot_version
        self._name: dict[str, set[int]] = {}
        self._set: dict[str, set[int]] = {}
        self._num: dict[str, set[int]] = {}
        self._den: dict[str, set[int]] = {}
        self._lang: dict[str, set[int]] = {}
        for i, row in enumerate(self.rows):
            self._add(self._name, _norm(row.name), i)
            self._add(self._set, _norm(row.set_name), i)
            numerator, denominator = _number_parts(row.number)
            if not denominator and row.denominator:
                _, denominator = _number_parts(f"0/{row.denominator}")
            self._add(self._num, numerator, i)
            if denominator:
                self._add(self._den, denominator, i)
            self._add(self._lang, _language(row.language), i)

    @staticmethod
    def _add(index: dict[str, set[int]], key: str, position: int) -> None:
        if key:
            index.setdefault(key, set()).add(position)

    def resolve(self, clues: IdentityClues) -> CardinalityResult:
        supplied = clues.supplied_fields()
        if not supplied:
            return CardinalityResult(
                ResolutionStatus.UNRESOLVED, 0, self.snapshot_version, supplied
            )

        constraints: list[set[int]] = []
        if clues.name:
            constraints.append(set(self._name.get(_norm(clues.name), set())))
        if clues.set_name:
            constraints.append(set(self._set.get(_norm(clues.set_name), set())))
        if clues.language:
            constraints.append(set(self._lang.get(_language(clues.language), set())))
        if clues.number:
            numerator, denominator = _number_parts(clues.number)
            constraints.append(set(self._num.get(numerator, set())))
            if denominator:
                constraints.append(set(self._den.get(denominator, set())))

        if not constraints or any(not constraint for constraint in constraints):
            return CardinalityResult(
                ResolutionStatus.UNRESOLVED, 0, self.snapshot_version, supplied
            )

        candidate_positions = set.intersection(*constraints)
        candidate_ids = tuple(sorted(self.rows[i].catalog_id for i in candidate_positions))
        if len(candidate_positions) == 0:
            status = ResolutionStatus.UNRESOLVED
        elif len(candidate_positions) > 1:
            status = ResolutionStatus.AMBIGUOUS
        else:
            status = ResolutionStatus.RESOLVED

        if status is not ResolutionStatus.RESOLVED:
            return CardinalityResult(
                status,
                len(candidate_positions),
                self.snapshot_version,
                supplied,
                candidate_ids=candidate_ids,
            )

        position = next(iter(candidate_positions))
        card = self.rows[position]
        inferred = tuple(
            field
            for field in ("name", "set_name", "number", "language")
            if field not in supplied
        )
        return CardinalityResult(
            status,
            1,
            self.snapshot_version,
            supplied,
            inferred,
            card,
            candidate_ids,
        )


def cards_from_mappings(
    rows: Iterable[Mapping[str, object]], *, snapshot_version: str
) -> list[CatalogCard]:
    """Adapter for a local TCGdex/Robot-KB snapshot representation."""
    out: list[CatalogCard] = []
    for row in rows:
        catalog_id = str(row.get("catalog_id") or row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        set_name = str(row.get("set_name") or row.get("setName") or "").strip()
        number = str(row.get("number") or row.get("localId") or "").strip()
        language = str(row.get("language") or "").strip()
        denominator = str(row.get("denominator") or "").strip()
        if not all((catalog_id, name, set_name, number, language)):
            continue
        out.append(
            CatalogCard(
                catalog_id=catalog_id,
                name=name,
                set_name=set_name,
                number=number,
                language=language,
                denominator=denominator,
                snapshot_version=snapshot_version,
            )
        )
    return out
