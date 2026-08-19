"""Strict PokemonPriceTracker confirmation for the V4 Global Multi-Vault lane.

Adapted from the validated Japan Edge PPT shadow (#105/#107). This module is
read-only and returns aggregate eBay graded evidence only. It never turns an
aggregate into an item-level SOLD and never performs a commercial action.

The provider mapping is deliberately tiny and source-reviewed. Unmapped sets
fail closed before network access. PPT and PokeTrace/eBay belong to the same
EBAY_GRADED_AGGREGATE correlation family.
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median
from typing import Mapping, Optional, Sequence

import requests

from ecb_fx import ECBCurrencyConverter
from v4_global_market_core import CommercialIdentity, EBAY_GRADED_AGGREGATE

PPT_URL = "https://www.pokemonpricetracker.com/api/v2/cards"
PROVIDER = "PokemonPriceTracker"

# Live-proven by the bounded Japan Edge PPT diagnostic: Japanese Pokemon Card
# 151 is exposed as provider setId=23599. No other set is guessed.
REVIEWED_JP_SET_IDS = {
    "151": "23599",
    "pokemon card 151": "23599",
}

SENSITIVE_TERMS = (
    "master ball",
    "masterball",
    "poke ball",
    "pokeball",
    "reverse",
    "reverse holo",
    "1st edition",
    "first edition",
    "shadowless",
    "stamp",
    "stamped",
    "error",
    "incorrect texture",
)


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _collector(value: object) -> str:
    raw = str(value or "").strip().lstrip("#").split("/", 1)[0]
    token = re.sub(r"[^A-Za-z0-9]+", "", raw).casefold()
    if token.isdigit():
        return str(int(token))
    match = re.fullmatch(r"([a-z]+)0*(\d+)", token)
    return f"{match.group(1)}{int(match.group(2))}" if match else token


def _positive(value: object) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _header_int(headers: Mapping[str, object], name: str) -> Optional[int]:
    for key, value in headers.items():
        if str(key).casefold() != name.casefold():
            continue
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None
    return None


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


def _grade_key(identity: CommercialIdentity) -> str:
    grader = _norm(identity.grader).replace(" ", "")
    try:
        value = float(str(identity.grade).strip())
        grade = str(int(value)) if value.is_integer() else f"{value:g}"
    except (TypeError, ValueError):
        grade = str(identity.grade or "").strip()
    return f"{grader}{grade.replace('.', '_')}"


def _sensitive_claims(identity: CommercialIdentity) -> tuple[str, ...]:
    blob = _norm(" ".join((identity.edition, identity.finish, identity.variant)))
    found: list[str] = []
    for raw in SENSITIVE_TERMS:
        claim = _norm(raw)
        if claim and claim in blob and claim not in found:
            found.append(claim)
    return tuple(found)


def _provider_blob(row: Mapping[str, object]) -> str:
    return _norm(
        " ".join(
            str(row.get(key) or "")
            for key in ("name", "printing", "variant", "rarity", "description")
        )
    )


def reviewed_set_id(identity: CommercialIdentity) -> Optional[str]:
    if _norm(identity.language) not in {"ja", "jp", "japanese", "japonais"}:
        return None
    return REVIEWED_JP_SET_IDS.get(_norm(identity.set_name))


def _match(identity: CommercialIdentity, rows: Sequence[Mapping[str, object]], set_id: str):
    expected_id = _norm(set_id)
    expected_number = _collector(identity.number)
    candidates: list[Mapping[str, object]] = []
    for row in rows:
        declared_language = row.get("language")
        if declared_language not in (None, "") and _norm(declared_language) not in {
            "ja", "jp", "japanese", "japonais", "japan",
        }:
            continue
        if _norm(row.get("setId") or row.get("set_id")) != expected_id:
            continue
        if _collector(row.get("cardNumber") or row.get("number")) != expected_number:
            continue
        candidates.append(row)
    if len(candidates) != 1:
        return "AMBIGUOUS" if len(candidates) > 1 else "CLEAN_NO_MATCH", None
    row = candidates[0]
    provider_blob = _provider_blob(row)
    for claim in _sensitive_claims(identity):
        if claim not in provider_blob:
            return "MICROVARIANT_UNPROVEN", None
    return "EXACT", row


@dataclass
class PptBudget:
    max_http_calls: int = 8
    max_credits: int = 40
    daily_remaining_floor: int = 15_000
    interval_seconds: float = 1.10
    http_calls: int = 0
    credits: int = 0
    daily_remaining: Optional[int] = None
    blocked_reason: str = ""
    _last_call: Optional[float] = None

    def can_call(self) -> bool:
        if self.blocked_reason:
            return False
        if self.http_calls >= self.max_http_calls:
            self.blocked_reason = "HTTP_CALL_CAP"
        elif self.credits >= self.max_credits:
            self.blocked_reason = "CREDIT_CAP"
        elif (
            self.daily_remaining is not None
            and self.daily_remaining <= self.daily_remaining_floor
        ):
            self.blocked_reason = "DAILY_REMAINING_SAFETY_FLOOR"
        return not self.blocked_reason

    def wait(self) -> None:
        if self._last_call is None or self.interval_seconds <= 0:
            return
        delay = self.interval_seconds - (time.monotonic() - self._last_call)
        if delay > 0:
            time.sleep(delay)

    def record(self, headers: Mapping[str, object]) -> None:
        self.http_calls += 1
        self._last_call = time.monotonic()
        consumed = _header_int(headers, "X-Api-Calls-Consumed")
        remaining = _header_int(headers, "X-Ratelimit-Daily-Remaining")
        if consumed is None:
            self.blocked_reason = "CREDIT_HEADER_REQUIRED"
            return
        if remaining is None:
            self.blocked_reason = "DAILY_REMAINING_HEADER_REQUIRED"
            return
        self.credits += consumed
        self.daily_remaining = remaining
        if self.credits > self.max_credits:
            self.blocked_reason = "CREDIT_CAP_EXCEEDED"
        elif remaining <= self.daily_remaining_floor:
            self.blocked_reason = "DAILY_REMAINING_SAFETY_FLOOR"


@dataclass(frozen=True)
class PptSnapshot:
    status: str
    fair_eur: Optional[float] = None
    sales_count: int = 0
    last_sale_at: Optional[datetime] = None
    evidence_class: str = "SOLD_AGGREGATED"
    correlation_group: str = EBAY_GRADED_AGGREGATE
    match_proof: str = ""
    note: str = ""


def _request(
    session: requests.Session,
    api_key: str,
    budget: PptBudget,
    params: Mapping[str, object],
    timeout: float,
):
    if not budget.can_call():
        return None, None
    budget.wait()
    try:
        response = session.get(
            PPT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            params=dict(params),
            timeout=timeout,
        )
    except requests.RequestException as error:
        budget.blocked_reason = f"REQUEST_ERROR:{type(error).__name__}"
        return None, None
    budget.record(getattr(response, "headers", {}) or {})
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return int(response.status_code), payload


def _parse_last_sale(value: object) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_snapshot(
    identity: CommercialIdentity,
    *,
    api_key: str,
    budget: PptBudget,
    session: requests.Session,
    fx: ECBCurrencyConverter,
    timeout: float = 15.0,
    now: Optional[datetime] = None,
) -> PptSnapshot:
    observed_at = now or datetime.now(timezone.utc)
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return PptSnapshot("BLOCKED_IDENTITY", note="incomplete/non-actionable identity")
    if _norm(identity.language) not in {"ja", "jp", "japanese", "japonais"}:
        return PptSnapshot("BLOCKED_LANGUAGE", note="PPT exact mapping currently Japanese only")
    if _norm(identity.grader) != "psa" or str(identity.grade).strip() not in {"10", "10.0"}:
        return PptSnapshot("BLOCKED_GRADE", note="reviewed PPT mapping requires PSA 10")
    set_id = reviewed_set_id(identity)
    if not set_id:
        return PptSnapshot("CATALOG_SET_ID_UNMAPPED", note="no reviewed PPT setId; no network")
    if not api_key:
        return PptSnapshot("PROVIDER_DISABLED", note="PPT key unavailable")

    matched = None
    for search in (_collector(identity.number), identity.name):
        status, payload = _request(
            session,
            api_key,
            budget,
            {
                "language": "japanese",
                "setId": set_id,
                "search": search,
                "limit": 5,
            },
            timeout,
        )
        if status is None:
            return PptSnapshot("PENDING_BUDGET", note=budget.blocked_reason)
        if status == 429:
            budget.blocked_reason = "RATE_LIMIT"
            return PptSnapshot("RATE_LIMIT", note="HTTP 429")
        if status != 200:
            return PptSnapshot("PROVIDER_ERROR", note=f"HTTP {status}")
        match_status, row = _match(identity, _rows(payload), set_id)
        if match_status in {"AMBIGUOUS", "MICROVARIANT_UNPROVEN"}:
            return PptSnapshot(match_status, match_proof=match_status, note=match_status)
        if match_status == "EXACT":
            matched = row
            break
    if matched is None:
        return PptSnapshot("CLEAN_NO_MATCH", note="exact reviewed setId+collector not found")

    tcgplayer_id = matched.get("tcgPlayerId") or matched.get("tcgplayerId")
    if not tcgplayer_id:
        return PptSnapshot("CLEAN_INSUFFICIENT", note="TCGPLAYER_ID_MISSING")
    status, payload = _request(
        session,
        api_key,
        budget,
        {
            "language": "japanese",
            "tcgPlayerId": str(tcgplayer_id),
            "includeHistory": "true",
            "includeEbay": "true",
            "includeCardmarket": "false",
            "days": 180,
            "maxDataPoints": 180,
        },
        timeout,
    )
    if status is None:
        return PptSnapshot("PENDING_BUDGET", note=budget.blocked_reason)
    if status == 429:
        budget.blocked_reason = "RATE_LIMIT"
        return PptSnapshot("RATE_LIMIT", note="HTTP 429")
    if status != 200:
        return PptSnapshot("PROVIDER_ERROR", note=f"HTTP {status}")
    deep_status, row = _match(identity, _rows(payload), set_id)
    if deep_status != "EXACT" or row is None:
        return PptSnapshot(deep_status, match_proof=deep_status, note="deep identity not exact")

    ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
    grades = ebay.get("salesByGrade") if isinstance(ebay.get("salesByGrade"), Mapping) else {}
    bucket = grades.get(_grade_key(identity))
    if not isinstance(bucket, Mapping):
        return PptSnapshot("CLEAN_NO_MATCH", note="exact grade bucket missing")
    try:
        count = max(0, int(bucket.get("count") or 0))
    except (TypeError, ValueError):
        count = 0
    smart = bucket.get("smartMarketPrice") if isinstance(bucket.get("smartMarketPrice"), Mapping) else {}
    centers = [
        value
        for value in (
            _positive(bucket.get("medianPrice")),
            _positive(smart.get("price")),
            _positive(bucket.get("averagePrice")),
        )
        if value is not None
    ]
    if count <= 0 or not centers:
        return PptSnapshot("CLEAN_INSUFFICIENT", sales_count=count, note="aggregate center/count missing")
    fair_usd = float(median(centers))
    converted = fx.convert(Decimal(str(fair_usd)), "USD", "EUR", observed_at.date())
    if converted is None or converted <= 0:
        return PptSnapshot("FX_UNAVAILABLE", sales_count=count, note="USD/EUR unavailable")
    return PptSnapshot(
        "MATCHED",
        fair_eur=round(float(converted), 2),
        sales_count=count,
        last_sale_at=_parse_last_sale(bucket.get("lastSaleDate")),
        match_proof="JP_QUERY_SCOPE_PROVIDER_SET_ID_NUMBER_AND_VARIANT",
        note="PPT Japanese eBay graded aggregate; ASK/current auction never used",
    )
