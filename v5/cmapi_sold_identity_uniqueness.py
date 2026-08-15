from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping

import requests


TCGDEX_BASE = "https://api.tcgdex.net/v2/en"
MAX_CANDIDATES = 12


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _tokens(value: object) -> tuple[str, ...]:
    return tuple(_norm(value).split())


def _number(value: object) -> str:
    raw = str(value or "").strip().lstrip("#").split("/", 1)[0]
    if re.fullmatch(r"0*\d+", raw):
        return str(int(raw))
    return raw.casefold()


def _title_has_number(title: object, number: object) -> bool:
    wanted = _number(number)
    if not wanted:
        return False
    return wanted in {_number(token) for token in re.findall(r"[A-Za-z]*\d+[A-Za-z]*", str(title or ""))}


def _title_has_all(title: object, phrase: object) -> bool:
    title_set = set(_tokens(title))
    needed = _tokens(phrase)
    return bool(needed) and all(token in title_set for token in needed)


def _base_card_name(value: object) -> str:
    tokens = list(_tokens(value))
    suffixes = {"v", "vmax", "vstar", "gx", "ex"}
    while tokens and tokens[-1] in suffixes:
        tokens.pop()
    return " ".join(tokens)


def is_signed_or_autographed(title: object) -> bool:
    text = _norm(title)
    if any(token in text.split() for token in ("signed", "autograph", "autographed")):
        return True
    return bool(re.search(r"\bauto\s*(?:grade\s*)?(?:10|9|8|7|6|5|4|3|2|1)\b", text))


@dataclass
class TCGdexSoldUniquenessResolver:
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()
        self._name_number_cache: dict[tuple[str, str, str], bool] = {}
        self._set_number_cache: dict[tuple[str, str, str], bool] = {}

    def _get_json(self, url: str, *, params: Mapping[str, object] | None = None) -> object | None:
        assert self.session is not None
        try:
            response = self.session.get(url, params=dict(params or {}), timeout=12)
            if response.status_code != 200:
                return None
            return response.json()
        except (requests.RequestException, ValueError):
            return None

    def name_number_unique(self, card: Mapping[str, object]) -> bool:
        name = str(card.get("name") or "").strip()
        set_name = str(card.get("set") or "").strip()
        number = _number(card.get("number"))
        key = (_norm(name), _norm(set_name), number)
        if key in self._name_number_cache:
            return self._name_number_cache[key]
        if not (name and set_name and number):
            self._name_number_cache[key] = False
            return False
        payload = self._get_json(
            f"{TCGDEX_BASE}/cards",
            params={
                "name": name,
                "localId": f"eq:{number}",
                "pagination:page": 1,
                "pagination:itemsPerPage": MAX_CANDIDATES + 1,
            },
        )
        rows = payload if isinstance(payload, list) else []
        exact = [
            row
            for row in rows
            if isinstance(row, Mapping)
            and _norm(row.get("name")) == _norm(name)
            and _number(row.get("localId")) == number
        ]
        if len(exact) != 1:
            self._name_number_cache[key] = False
            return False
        card_id = str(exact[0].get("id") or "").strip()
        detail = self._get_json(f"{TCGDEX_BASE}/cards/{card_id}") if card_id else None
        detail_set = detail.get("set") if isinstance(detail, Mapping) and isinstance(detail.get("set"), Mapping) else {}
        result = bool(
            isinstance(detail, Mapping)
            and _norm(detail.get("name")) == _norm(name)
            and _number(detail.get("localId")) == number
            and _norm(detail_set.get("name")) == _norm(set_name)
        )
        self._name_number_cache[key] = result
        return result

    def set_number_exact(self, card: Mapping[str, object]) -> bool:
        name = str(card.get("name") or "").strip()
        set_name = str(card.get("set") or "").strip()
        number = _number(card.get("number"))
        key = (_norm(name), _norm(set_name), number)
        if key in self._set_number_cache:
            return self._set_number_cache[key]
        if not (name and set_name and number):
            self._set_number_cache[key] = False
            return False
        payload = self._get_json(
            f"{TCGDEX_BASE}/sets",
            params={
                "name": set_name,
                "pagination:page": 1,
                "pagination:itemsPerPage": MAX_CANDIDATES + 1,
            },
        )
        rows = payload if isinstance(payload, list) else []
        exact_sets = [
            row for row in rows
            if isinstance(row, Mapping) and _norm(row.get("name")) == _norm(set_name)
        ]
        if len(exact_sets) != 1:
            self._set_number_cache[key] = False
            return False
        set_id = str(exact_sets[0].get("id") or "").strip()
        detail = self._get_json(f"{TCGDEX_BASE}/sets/{set_id}/{number}") if set_id else None
        detail_set = detail.get("set") if isinstance(detail, Mapping) and isinstance(detail.get("set"), Mapping) else {}
        result = bool(
            isinstance(detail, Mapping)
            and _norm(detail.get("name")) == _norm(name)
            and _number(detail.get("localId")) == number
            and _norm(detail_set.get("name")) == _norm(set_name)
        )
        self._set_number_cache[key] = result
        return result


def catalog_rescue_matches(
    card: Mapping[str, object],
    offer: Mapping[str, object],
    resolver: TCGdexSoldUniquenessResolver,
) -> bool:
    title = str(offer.get("title") or "")
    if not title or is_signed_or_autographed(title):
        return False
    if str(offer.get("company") or "").upper() != "PSA":
        return False
    if str(offer.get("grade") or "") not in {"10", "10.0"}:
        return False
    if not _title_has_number(title, card.get("number")):
        return False

    full_name_present = _title_has_all(title, card.get("name"))
    set_present = _title_has_all(title, card.get("set"))
    base_name = _base_card_name(card.get("name"))
    base_name_present = _title_has_all(title, base_name)

    # Exact set + collector number is a deterministic catalogue route. This can
    # recover an omitted V/VMAX/VSTAR suffix only when TCGdex confirms the exact
    # set+number resolves to the canonical card.
    if set_present and base_name_present and resolver.set_number_exact(card):
        return True

    # Exact full card name + number may recover an omitted set only if that pair
    # occurs exactly once in the English TCGdex catalogue and resolves back to
    # the canonical set. Numerator-only input is therefore still fail-closed on
    # any catalogue collision.
    if full_name_present and resolver.name_number_unique(card):
        return True

    return False
