"""Passive PokemonPriceTracker identity shadow for V5 diagnostics.

This module is observation-only. It may show that PokemonPriceTracker could
recover a macro coordinate, but it never mutates CardIdentity, never changes
acceptance, and never proves edition/finish/microvariant.
"""

from __future__ import annotations

import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import requests

from .identity_observability import UnresolvedIdentityDiagnostic


BASE_URL = "https://www.pokemonpricetracker.com/api/v2/cards"


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _number(value: object) -> str:
    compact = re.sub(r"\s+", "", str(value or "")).lstrip("#")
    token = re.sub(r"[^A-Za-z0-9]+", "", compact.split("/", 1)[0]).casefold()
    if token.isdigit():
        return str(int(token))
    match = re.fullmatch(r"([a-z]+)0*(\d+)", token)
    return f"{match.group(1)}{int(match.group(2))}" if match else token


def _set_equal(expected: object, actual: object) -> bool:
    return bool(_norm(expected) and _norm(expected) == _norm(actual))


def _name_compatible(expected: object, actual: object) -> bool:
    """Retrieval-only compatibility; never an identity acceptance rule."""
    left, right = _norm(expected), _norm(actual)
    if not left or not right:
        return False
    return right == left or right.startswith(left + " ")


def _rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if isinstance(data, Mapping):
        return [data]
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
        return [row for row in data if isinstance(row, Mapping)]
    return []


def _header_int(headers: Mapping[str, object], wanted: str) -> int | None:
    for key, value in headers.items():
        if str(key).casefold() != wanted.casefold():
            continue
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None
    return None


@dataclass(frozen=True)
class PptShadowResult:
    record: int
    item_id: str
    status: str
    candidate_count: int
    recovered_set: str | None = None
    external_catalog_id: str | None = None
    proof_level: str = "OBSERVATION_ONLY"


@dataclass
class PptShadowCounters:
    records_seen: int = 0
    eligible: int = 0
    calls: int = 0
    credits: int = 0
    exact_set_number_observations: int = 0
    unique_name_number_set_recoverable: int = 0
    ambiguous: int = 0
    no_match: int = 0
    unavailable: int = 0
    budget_exhausted: int = 0
    skipped_coordinates: int = 0
    daily_remaining: int | None = None


@dataclass
class PokemonPriceTrackerIdentityShadow:
    enabled: bool
    api_key: str | None
    session: object = requests
    max_calls: int = 12
    max_credits: int = 120
    daily_remaining_floor: int = 1000
    interval_seconds: float = 0.20
    counters: PptShadowCounters = field(default_factory=PptShadowCounters)
    results: list[PptShadowResult] = field(default_factory=list)
    _last_call: float | None = None
    _blocked: bool = False

    @classmethod
    def from_env(cls) -> "PokemonPriceTrackerIdentityShadow":
        return cls(
            enabled=_truthy(os.getenv("V5_PPT_IDENTITY_SHADOW_ENABLED", "false")),
            api_key=os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip() or None,
            max_calls=max(0, min(20, int(os.getenv("V5_PPT_IDENTITY_SHADOW_MAX_CALLS", "12")))),
            max_credits=max(0, min(250, int(os.getenv("V5_PPT_IDENTITY_SHADOW_MAX_CREDITS", "120")))),
        )

    def _can_call(self) -> bool:
        if not self.enabled or not self.api_key or self._blocked:
            return False
        if self.counters.calls >= self.max_calls or self.counters.credits >= self.max_credits:
            self.counters.budget_exhausted += 1
            self._blocked = True
            return False
        if (
            self.counters.daily_remaining is not None
            and self.counters.daily_remaining <= self.daily_remaining_floor
        ):
            self.counters.budget_exhausted += 1
            self._blocked = True
            return False
        return True

    def _request(self, params: Mapping[str, object]) -> list[Mapping[str, object]] | None:
        if not self._can_call():
            return None
        if self._last_call is not None:
            wait = self.interval_seconds - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
        try:
            response = self.session.get(
                BASE_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                },
                params=dict(params),
                timeout=20,
            )
        except Exception:
            self.counters.unavailable += 1
            self._blocked = True
            return None
        self.counters.calls += 1
        self._last_call = time.monotonic()
        consumed = _header_int(response.headers, "X-Api-Calls-Consumed")
        remaining = _header_int(response.headers, "X-Ratelimit-Daily-Remaining")
        if consumed is None or remaining is None:
            self.counters.unavailable += 1
            self._blocked = True
            return None
        self.counters.credits += consumed
        self.counters.daily_remaining = remaining
        if self.counters.credits > self.max_credits:
            self.counters.budget_exhausted += 1
            self._blocked = True
        if getattr(response, "status_code", None) != 200:
            self.counters.unavailable += 1
            if getattr(response, "status_code", None) == 429:
                self._blocked = True
            return None
        try:
            return _rows(response.json())
        except Exception:
            self.counters.unavailable += 1
            self._blocked = True
            return None

    def observe_one(self, diag: UnresolvedIdentityDiagnostic) -> PptShadowResult | None:
        self.counters.records_seen += 1
        name = str(diag.card_name or "").strip()
        number = _number(diag.card_number)
        set_name = str(diag.set_name or "").strip()
        if not (name and number):
            self.counters.skipped_coordinates += 1
            return None
        if not self._can_call():
            return None
        self.counters.eligible += 1

        params: dict[str, object] = {
            "search": f"{name} {number}",
            "limit": 10,
        }
        if set_name:
            params["setName"] = set_name
        rows = self._request(params)
        if rows is None:
            return None

        number_rows = [
            row
            for row in rows
            if _number(row.get("cardNumber") or row.get("number")) == number
            and _name_compatible(name, row.get("name"))
        ]
        if set_name:
            exact = [
                row
                for row in number_rows
                if _set_equal(set_name, row.get("setName") or row.get("set_name"))
            ]
            if len(exact) == 1:
                row = exact[0]
                self.counters.exact_set_number_observations += 1
                result = PptShadowResult(
                    diag.record,
                    str(diag.item_id or "UNKNOWN"),
                    "EXACT_SET_NUMBER_SHADOW",
                    1,
                    str(row.get("setName") or row.get("set_name") or "") or None,
                    str(row.get("externalCatalogId") or "") or None,
                    "SHADOW_ONLY_NOT_ACCEPTANCE",
                )
            elif len(exact) > 1:
                self.counters.ambiguous += 1
                result = PptShadowResult(
                    diag.record,
                    str(diag.item_id or "UNKNOWN"),
                    "AMBIGUOUS",
                    len(exact),
                )
            else:
                self.counters.no_match += 1
                result = PptShadowResult(
                    diag.record,
                    str(diag.item_id or "UNKNOWN"),
                    "NO_MATCH",
                    0,
                )
        else:
            unique_sets = {
                _norm(row.get("setName") or row.get("set_name")): row
                for row in number_rows
                if _norm(row.get("setName") or row.get("set_name"))
            }
            if len(unique_sets) == 1 and len(number_rows) == 1:
                row = next(iter(unique_sets.values()))
                self.counters.unique_name_number_set_recoverable += 1
                result = PptShadowResult(
                    diag.record,
                    str(diag.item_id or "UNKNOWN"),
                    "UNIQUE_NAME_NUMBER_SET_SHADOW",
                    1,
                    str(row.get("setName") or row.get("set_name") or "") or None,
                    str(row.get("externalCatalogId") or "") or None,
                    "SHADOW_ONLY_SET_CANDIDATE_NOT_ACCEPTANCE",
                )
            elif number_rows:
                self.counters.ambiguous += 1
                result = PptShadowResult(
                    diag.record,
                    str(diag.item_id or "UNKNOWN"),
                    "AMBIGUOUS",
                    len(number_rows),
                )
            else:
                self.counters.no_match += 1
                result = PptShadowResult(
                    diag.record,
                    str(diag.item_id or "UNKNOWN"),
                    "NO_MATCH",
                    0,
                )
        self.results.append(result)
        return result

    def observe(self, diagnostics: Sequence[UnresolvedIdentityDiagnostic]) -> None:
        for diag in diagnostics:
            if not self._can_call() and self._blocked:
                break
            self.observe_one(diag)

    def render(self) -> str:
        c = self.counters
        lines = [
            "=== V5 POKEMONPRICETRACKER IDENTITY SHADOW ===",
            f"enabled: {str(bool(self.enabled and self.api_key)).lower()}",
            "changes identity acceptance: false",
            "changes microvariant gates: false",
            "provider candidate proves finish/edition: false",
            f"records seen: {c.records_seen}",
            f"eligible: {c.eligible}",
            f"HTTP calls: {c.calls}/{self.max_calls}",
            f"credits consumed: {c.credits}/{self.max_credits}",
            f"daily remaining: {c.daily_remaining}",
            f"exact set+number shadow observations: {c.exact_set_number_observations}",
            f"unique name+number set candidates: {c.unique_name_number_set_recoverable}",
            f"ambiguous: {c.ambiguous}",
            f"no-match: {c.no_match}",
            f"unavailable/error: {c.unavailable}",
            f"budget exhausted: {c.budget_exhausted}",
        ]
        for result in self.results:
            lines.append(
                "PPT_SHADOW "
                f"record={result.record} item_id={result.item_id} status={result.status} "
                f"candidates={result.candidate_count} recovered_set={result.recovered_set or 'UNKNOWN'} "
                f"external_catalog_id={result.external_catalog_id or 'UNKNOWN'} "
                f"proof={result.proof_level}"
            )
        return "\n".join(lines)
