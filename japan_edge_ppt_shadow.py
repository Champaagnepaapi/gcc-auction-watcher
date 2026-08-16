"""PokemonPriceTracker Japanese graded-market shadow for Japan Edge.

Safety contract:
- Japanese physical cards only (`language=japanese` on every PPT request);
- exact macro identity = Japanese language + exact normalized set + collector number;
- sensitive microvariants remain fail-closed unless the provider row proves them;
- exact grader + grade bucket only (Japan Edge currently PSA 10);
- PPT eBay data is `SOLD_AGGREGATED`, never item-level SOLD;
- PPT and PokeTrace share the `EBAY_GRADED_AGGREGATE` correlation group and
  therefore never count as two independent markets;
- this module only enriches a report. It never changes Japan Edge decisions,
  sends notifications, writes state, purchases, bids, checks out or pays.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Optional, Sequence

import requests

import japan_edge_hunter as base
from ecb_fx import ECBCurrencyConverter

PPT_URL = "https://www.pokemonpricetracker.com/api/v2/cards"
EVIDENCE_CLASS = "SOLD_AGGREGATED"
CORRELATION_GROUP = "EBAY_GRADED_AGGREGATE"
PROVIDER = "PokemonPriceTracker"

SENSITIVE_VARIANT_TERMS = (
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
    text = re.sub(r"[^a-z0-9]+", " ", text.casefold())
    return " ".join(text.split())


def _collector(value: object) -> str:
    raw = str(value or "").strip().lstrip("#").split("/", 1)[0]
    token = re.sub(r"[^A-Za-z0-9]+", "", raw).casefold()
    if token.isdigit():
        return str(int(token))
    match = re.fullmatch(r"([a-z]+)0*(\d+)", token)
    return f"{match.group(1)}{int(match.group(2))}" if match else token


def _language_is_japanese(value: object) -> bool:
    return _norm(value) in {"japanese", "japan", "jp", "ja", "jpn"}


def _grade_key(grader: object, grade: object) -> str:
    grader_key = _norm(grader).replace(" ", "")
    try:
        number = float(str(grade).strip())
        grade_key = str(int(number)) if number.is_integer() else str(number).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        grade_key = str(grade or "").strip()
    return f"{grader_key}{grade_key.replace('.', '_')}"


def _positive(value: object) -> Optional[float]:
    try:
        result = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return result if result is not None and result > 0 else None


def _header_int(headers: Mapping[str, object], name: str) -> Optional[int]:
    for key, value in headers.items():
        if str(key).casefold() == name.casefold():
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


def _sensitive_claims(identity: base.Identity) -> tuple[str, ...]:
    blob = _norm(" ".join(x for x in (identity.edition, identity.attribute, identity.variety) if x))
    found = []
    for term in SENSITIVE_VARIANT_TERMS:
        normalized = _norm(term)
        if normalized and normalized in blob and normalized not in found:
            found.append(normalized)
    return tuple(found)


def _provider_identity_blob(row: Mapping[str, object]) -> str:
    values = [
        row.get("name"),
        row.get("printing"),
        row.get("variant"),
        row.get("rarity"),
        row.get("description"),
    ]
    return _norm(" ".join(str(value or "") for value in values))


@dataclass(frozen=True)
class PptMatch:
    status: str
    row: Optional[Mapping[str, object]] = None
    reason: str = ""


def match_japanese_identity(identity: base.Identity, rows: Sequence[Mapping[str, object]]) -> PptMatch:
    """Deterministic provider-side macro proof for a Japanese card.

    Set + collector number are the macro identity. Sensitive finish/edition claims
    are checked separately and must be explicit in the provider row.
    """
    if not _language_is_japanese(identity.language):
        return PptMatch("BLOCKED_LANGUAGE", reason="PHYSICAL_CARD_NOT_JAPANESE")

    expected_set = _norm(identity.set_name)
    expected_number = _collector(identity.number)
    candidates: list[Mapping[str, object]] = []
    for row in rows:
        if not _language_is_japanese(row.get("language")):
            continue
        if _norm(row.get("setName") or row.get("set_name")) != expected_set:
            continue
        if _collector(row.get("cardNumber") or row.get("number")) != expected_number:
            continue
        candidates.append(row)

    if len(candidates) == 0:
        return PptMatch("CLEAN_NO_MATCH", reason="JP_SET_NUMBER_NOT_FOUND")
    if len(candidates) > 1:
        return PptMatch("AMBIGUOUS", reason="MULTIPLE_JP_SET_NUMBER_ROWS")

    row = candidates[0]
    provider_blob = _provider_identity_blob(row)
    for claim in _sensitive_claims(identity):
        if claim not in provider_blob:
            return PptMatch("MICROVARIANT_UNPROVEN", reason=f"MISSING_PROVIDER_CLAIM:{claim}")
    return PptMatch("EXACT", row=row, reason="JP_LANGUAGE_SET_NUMBER_AND_VARIANT")


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
        elif self.daily_remaining is not None and self.daily_remaining <= self.daily_remaining_floor:
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
class DailyPoint:
    date: str
    count: int
    average_usd: Optional[float]


@dataclass(frozen=True)
class PptJapaneseSnapshot:
    status: str
    evidence_class: str = EVIDENCE_CLASS
    correlation_group: str = CORRELATION_GROUP
    provider: str = PROVIDER
    language: str = "Japanese"
    grader: str = "PSA"
    grade: str = "10"
    fair_value_usd: Optional[float] = None
    fair_value_eur: Optional[float] = None
    median_price_usd: Optional[float] = None
    average_price_usd: Optional[float] = None
    smart_market_price_usd: Optional[float] = None
    sales_count: int = 0
    last_sale_date: Optional[str] = None
    momentum_30d_pct: Optional[float] = None
    momentum_90d_pct: Optional[float] = None
    momentum_180d_pct: Optional[float] = None
    sales_velocity_30d: Optional[float] = None
    sales_velocity_90d: Optional[float] = None
    sales_velocity_180d: Optional[float] = None
    match_proof: str = ""
    note: str = ""


def _aggregate(row: Mapping[str, object], grader: str, grade: str) -> dict[str, object] | None:
    ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
    sales = ebay.get("salesByGrade") if isinstance(ebay.get("salesByGrade"), Mapping) else {}
    bucket = sales.get(_grade_key(grader, grade))
    if not isinstance(bucket, Mapping):
        return None
    smart = bucket.get("smartMarketPrice") if isinstance(bucket.get("smartMarketPrice"), Mapping) else {}
    try:
        count = max(0, int(bucket.get("count") or 0))
    except (TypeError, ValueError):
        count = 0
    return {
        "count": count,
        "average": _positive(bucket.get("averagePrice")),
        "median": _positive(bucket.get("medianPrice")),
        "smart": _positive(smart.get("price")),
        "last_sale_date": str(bucket.get("lastSaleDate")) if bucket.get("lastSaleDate") else None,
    }


def _history(row: Mapping[str, object], grader: str, grade: str) -> list[DailyPoint]:
    ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
    histories = ebay.get("priceHistory") if isinstance(ebay.get("priceHistory"), Mapping) else {}
    days = histories.get(_grade_key(grader, grade))
    if not isinstance(days, Mapping):
        return []
    output: list[DailyPoint] = []
    for when, payload in sorted(days.items()):
        if not isinstance(payload, Mapping):
            continue
        try:
            count = max(0, int(payload.get("count") or 0))
        except (TypeError, ValueError):
            count = 0
        output.append(DailyPoint(str(when), count, _positive(payload.get("average"))))
    return output


def _date(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _weighted_center(points: Sequence[DailyPoint]) -> Optional[float]:
    total_weight = 0
    total_value = 0.0
    for point in points:
        if point.average_usd is None or point.count <= 0:
            continue
        total_weight += point.count
        total_value += point.average_usd * point.count
    return total_value / total_weight if total_weight > 0 else None


def _window_metrics(points: Sequence[DailyPoint], days: int, now: datetime) -> tuple[Optional[float], Optional[float]]:
    cutoff = now - timedelta(days=days)
    selected = [point for point in points if (_date(point.date) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    if not selected:
        return None, None
    velocity = sum(max(0, point.count) for point in selected) * 30.0 / float(days)
    midpoint = now - timedelta(days=days / 2)
    old = [point for point in selected if (_date(point.date) or now) < midpoint]
    new = [point for point in selected if (_date(point.date) or now) >= midpoint]
    old_center = _weighted_center(old)
    new_center = _weighted_center(new)
    momentum = None
    if old_center is not None and new_center is not None and old_center > 0:
        momentum = (new_center / old_center - 1.0) * 100.0
    return (round(momentum, 1) if momentum is not None else None, round(velocity, 2))


def _request(
    session: requests.Session,
    api_key: str,
    budget: PptBudget,
    params: Mapping[str, object],
    timeout: float,
) -> tuple[Optional[int], object | None]:
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
        return int(response.status_code), response.json()
    except ValueError:
        return int(response.status_code), None


def fetch_japanese_snapshot(
    identity: base.Identity,
    *,
    api_key: str,
    budget: PptBudget,
    session: requests.Session,
    fx: ECBCurrencyConverter,
    timeout: float = 15.0,
    now: Optional[datetime] = None,
) -> PptJapaneseSnapshot:
    observed_at = now or datetime.now(timezone.utc)
    if not _language_is_japanese(identity.language):
        return PptJapaneseSnapshot(status="BLOCKED_LANGUAGE", note="physical card is not Japanese")
    if _norm(identity.grader) != "psa" or str(identity.grade).strip() not in {"10", "10.0"}:
        return PptJapaneseSnapshot(status="BLOCKED_GRADE", grader=identity.grader, grade=identity.grade, note="Japan Edge PPT shadow currently requires exact PSA 10")

    search_params = {
        "language": "japanese",
        "search": identity.number,
        "setName": identity.set_name,
        "limit": 10,
    }
    status, payload = _request(session, api_key, budget, search_params, timeout)
    if status is None:
        return PptJapaneseSnapshot(status="PENDING_BUDGET", note=budget.blocked_reason)
    if status == 429:
        budget.blocked_reason = "RATE_LIMIT"
        return PptJapaneseSnapshot(status="RATE_LIMIT", note="HTTP 429")
    if status != 200:
        return PptJapaneseSnapshot(status="PROVIDER_ERROR", note=f"HTTP {status}")

    match = match_japanese_identity(identity, _rows(payload))
    if match.status != "EXACT" or match.row is None:
        return PptJapaneseSnapshot(status=match.status, match_proof=match.reason, note=match.reason)

    tcgplayer_id = match.row.get("tcgPlayerId") or match.row.get("tcgplayerId")
    if not tcgplayer_id:
        return PptJapaneseSnapshot(status="CLEAN_INSUFFICIENT", match_proof=match.reason, note="TCGPLAYER_ID_MISSING")

    deep_params = {
        "language": "japanese",
        "tcgPlayerId": str(tcgplayer_id),
        "includeHistory": "true",
        "includeEbay": "true",
        "days": 180,
        "maxDataPoints": 180,
    }
    status, payload = _request(session, api_key, budget, deep_params, timeout)
    if status is None:
        return PptJapaneseSnapshot(status="PENDING_BUDGET", match_proof=match.reason, note=budget.blocked_reason)
    if status == 429:
        budget.blocked_reason = "RATE_LIMIT"
        return PptJapaneseSnapshot(status="RATE_LIMIT", match_proof=match.reason, note="HTTP 429")
    if status != 200:
        return PptJapaneseSnapshot(status="PROVIDER_ERROR", match_proof=match.reason, note=f"HTTP {status}")

    deep_match = match_japanese_identity(identity, _rows(payload))
    if deep_match.status != "EXACT" or deep_match.row is None:
        return PptJapaneseSnapshot(status=deep_match.status, match_proof=deep_match.reason, note="DEEP_IDENTITY_NOT_EXACT")

    aggregate = _aggregate(deep_match.row, identity.grader, identity.grade)
    if aggregate is None:
        return PptJapaneseSnapshot(status="CLEAN_NO_MATCH", match_proof=deep_match.reason, note="PSA10_BUCKET_MISSING")

    centers = [value for value in (aggregate["median"], aggregate["smart"], aggregate["average"]) if isinstance(value, (int, float)) and value > 0]
    fair_usd = float(median(centers)) if centers else None
    fair_eur = None
    if fair_usd is not None:
        converted = fx.convert(Decimal(str(fair_usd)), "USD", "EUR", observed_at.date())
        if converted is not None and converted > 0:
            fair_eur = round(float(converted), 2)

    history = _history(deep_match.row, identity.grader, identity.grade)
    m30, v30 = _window_metrics(history, 30, observed_at)
    m90, v90 = _window_metrics(history, 90, observed_at)
    m180, v180 = _window_metrics(history, 180, observed_at)

    if fair_usd is not None and fair_eur is None:
        final_status = "FX_UNAVAILABLE"
    elif fair_eur is None or int(aggregate["count"]) <= 0:
        final_status = "CLEAN_INSUFFICIENT"
    else:
        final_status = "MATCHED"

    return PptJapaneseSnapshot(
        status=final_status,
        fair_value_usd=round(fair_usd, 2) if fair_usd is not None else None,
        fair_value_eur=fair_eur,
        median_price_usd=aggregate["median"],
        average_price_usd=aggregate["average"],
        smart_market_price_usd=aggregate["smart"],
        sales_count=int(aggregate["count"]),
        last_sale_date=aggregate["last_sale_date"],
        momentum_30d_pct=m30,
        momentum_90d_pct=m90,
        momentum_180d_pct=m180,
        sales_velocity_30d=v30,
        sales_velocity_90d=v90,
        sales_velocity_180d=v180,
        match_proof=deep_match.reason,
        note="PPT Japanese eBay graded aggregate; same upstream family as PokeTrace eBay aggregate",
    )


def _identity_from_row(row: Mapping[str, object]) -> Optional[base.Identity]:
    raw = row.get("identity")
    if not isinstance(raw, Mapping):
        return None
    try:
        return base.Identity(**dict(raw))
    except (TypeError, ValueError):
        return None


def _provider_consistency(ppt_eur: Optional[float], poketrace_eur: Optional[float]) -> tuple[str, Optional[float]]:
    if not ppt_eur or ppt_eur <= 0 or not poketrace_eur or poketrace_eur <= 0:
        return "NOT_COMPARABLE", None
    ratio = max(ppt_eur, poketrace_eur) / min(ppt_eur, poketrace_eur)
    if ratio <= 1.20:
        status = "CONSISTENT"
    elif ratio <= 1.35:
        status = "MATERIAL_DIFFERENCE"
    else:
        status = "PROVIDER_CONFLICT"
    return status, round(ratio, 3)


def enrich_report(
    report: Mapping[str, object],
    *,
    api_key: str,
    budget: PptBudget,
    session: requests.Session,
    fx: ECBCurrencyConverter,
    max_candidates: int,
    timeout: float = 15.0,
) -> dict[str, object]:
    output = dict(report)
    raw_rows = report.get("opportunities") if isinstance(report.get("opportunities"), Sequence) else []
    rows: list[dict[str, object]] = []
    attempted = 0
    matched = 0

    for raw_row in raw_rows:
        row = dict(raw_row) if isinstance(raw_row, Mapping) else {}
        identity = _identity_from_row(row)
        if identity is None or not _language_is_japanese(identity.language):
            row["ppt_japanese_shadow"] = asdict(PptJapaneseSnapshot(status="BLOCKED_IDENTITY", note="Japanese physical identity missing"))
            rows.append(row)
            continue

        if attempted >= max(0, max_candidates):
            row["ppt_japanese_shadow"] = asdict(PptJapaneseSnapshot(status="PENDING_BUDGET", note="candidate cap reached"))
            rows.append(row)
            continue

        attempted += 1
        snapshot = fetch_japanese_snapshot(
            identity,
            api_key=api_key,
            budget=budget,
            session=session,
            fx=fx,
            timeout=timeout,
        )
        if snapshot.status == "MATCHED":
            matched += 1

        external = row.get("external_reference") if isinstance(row.get("external_reference"), Mapping) else {}
        try:
            poketrace_fair = float(external.get("fair_eur")) if external.get("fair_eur") is not None else None
        except (TypeError, ValueError):
            poketrace_fair = None
        consistency, ratio = _provider_consistency(snapshot.fair_value_eur, poketrace_fair)
        shadow = asdict(snapshot)
        shadow.update(
            {
                "poketrace_provider_consistency": consistency,
                "ppt_vs_poketrace_center_ratio": ratio,
                "independent_market_increment": 0,
                "production_decision_use": False,
                "notification_use": False,
            }
        )
        row["ppt_japanese_shadow"] = shadow
        rows.append(row)

    output["opportunities"] = rows
    output["ppt_japanese_shadow"] = {
        "enabled": True,
        "provider": PROVIDER,
        "evidence_class": EVIDENCE_CLASS,
        "correlation_group": CORRELATION_GROUP,
        "language": "Japanese",
        "attempted": attempted,
        "matched": matched,
        "http_calls": budget.http_calls,
        "credits": budget.credits,
        "daily_remaining": budget.daily_remaining,
        "blocked_reason": budget.blocked_reason,
        "independent_market_increment": 0,
        "production_decision_use": False,
        "notification_use": False,
    }
    return output


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default)).strip()))
    except ValueError:
        return default


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default)).strip()))
    except ValueError:
        return default


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="japan_edge_report.json")
    parser.add_argument("--output", default="japan_edge_ppt_shadow_report.json")
    args = parser.parse_args()

    api_key = os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("POKEMONPRICETRACKER_API_KEY is required for an explicit Japan Edge PPT shadow run")

    report = json.loads(Path(args.input).read_text(encoding="utf-8"))
    budget = PptBudget(
        max_http_calls=_env_int("JAPAN_EDGE_PPT_MAX_HTTP_CALLS", 8, 1),
        max_credits=_env_int("JAPAN_EDGE_PPT_MAX_CREDITS", 40, 1),
        daily_remaining_floor=_env_int("JAPAN_EDGE_PPT_DAILY_REMAINING_FLOOR", 15_000, 0),
        interval_seconds=_env_float("JAPAN_EDGE_PPT_INTERVAL_SECONDS", 1.10, 0.0),
    )
    output = enrich_report(
        report,
        api_key=api_key,
        budget=budget,
        session=requests.Session(),
        fx=ECBCurrencyConverter(),
        max_candidates=_env_int("JAPAN_EDGE_PPT_MAX_CANDIDATES", 4, 0),
        timeout=_env_float("JAPAN_EDGE_PPT_TIMEOUT_SECONDS", 15.0, 1.0),
    )
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = output.get("ppt_japanese_shadow", {})
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
