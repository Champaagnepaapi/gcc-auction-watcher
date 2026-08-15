"""Bounded, opt-in PokemonPriceTracker observer for V4.

Shadow contract:
- safe-off unless V4_PPT_SHADOW_ENABLED=true;
- GET-only PPT calls with hard request/credit/daily floors;
- English cards only until another language is empirically proven;
- exact TCGdex macro identity + existing deterministic V4 microvariant gate;
- PPT eBay data is SOLD_AGGREGATED, never item-level SOLD;
- current V4 opportunities are returned unchanged and no notification is sent.
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

import requests

from v4_ppt_shadow_model import (
    BASE_REQUIRED_DISCOUNT_PCT,
    EVIDENCE_CLASS,
    UPSTREAM_CLASS,
    DailyGradePoint,
    GradedAggregate,
    ShadowInput,
    analyze_shadow,
)

PPT_URL = "https://www.pokemonpricetracker.com/api/v2/cards"
STATE_KEY = "v4_ppt_shadow"
SCHEMA = 1


@dataclass(frozen=True)
class PptMacroIdentity:
    card_id: str
    name: str
    set_name: str
    number: str


@dataclass(frozen=True)
class PptMacroMatch:
    status: str
    row: Mapping[str, object] | None = None
    proof: str = ""


@dataclass
class PptRequestBudget:
    max_http_calls: int = 12
    credit_cap: int = 60
    daily_remaining_floor: int = 15_000
    interval_seconds: float = 1.10
    http_calls: int = 0
    credits: int = 0
    daily_remaining: int | None = None
    blocked_reason: str = ""
    _last_call: float | None = None

    def can_call(self) -> bool:
        if self.blocked_reason:
            return False
        if self.http_calls >= self.max_http_calls:
            self.blocked_reason = "HTTP_CALL_CAP"
        elif self.credits >= self.credit_cap:
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
        if self.credits > self.credit_cap:
            self.blocked_reason = "CREDIT_CAP_EXCEEDED"
        elif remaining <= self.daily_remaining_floor:
            self.blocked_reason = "DAILY_REMAINING_SAFETY_FLOOR"


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _num(value: object) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "", str(value or "").split("/", 1)[0]).casefold()
    if token.isdigit():
        return str(int(token))
    match = re.fullmatch(r"([a-z]+)0*(\d+)", token)
    return f"{match.group(1)}{int(match.group(2))}" if match else token


def _grade(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "").strip()
    return str(int(number)) if number.is_integer() else str(number).rstrip("0").rstrip(".")


def _grade_key(grader: object, grade: object) -> str:
    return f"{_norm(grader).replace(' ', '')}{_grade(grade).replace('.', '_')}"


def _positive(value: object) -> float | None:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and number > 0 else None


def _header_int(headers: Mapping[str, object], name: str) -> int | None:
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


def match_macro_identity(identity: PptMacroIdentity, rows: Sequence[Mapping[str, object]]) -> PptMacroMatch:
    exact = [row for row in rows if _norm(row.get("externalCatalogId")) == _norm(identity.card_id)]
    if len(exact) == 1:
        return PptMacroMatch("EXACT", exact[0], "EXTERNAL_CATALOG_ID")
    if len(exact) > 1:
        return PptMacroMatch("AMBIGUOUS", None, "EXTERNAL_CATALOG_ID")
    fallback = [
        row for row in rows
        if _num(row.get("cardNumber") or row.get("number")) == _num(identity.number)
        and _norm(row.get("setName") or row.get("set_name")).endswith(_norm(identity.set_name))
    ]
    if len(fallback) == 1:
        return PptMacroMatch("EXACT", fallback[0], "SET_NUMBER")
    if len(fallback) > 1:
        return PptMacroMatch("AMBIGUOUS", None, "SET_NUMBER")
    return PptMacroMatch("UNRESOLVED")


def _aggregate(row: Mapping[str, object], grader: str, grade: object) -> GradedAggregate | None:
    ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
    sales = ebay.get("salesByGrade") if isinstance(ebay.get("salesByGrade"), Mapping) else {}
    bucket = sales.get(_grade_key(grader, grade))
    if not isinstance(bucket, Mapping):
        return None
    smart = bucket.get("smartMarketPrice") if isinstance(bucket.get("smartMarketPrice"), Mapping) else {}
    try:
        count = int(bucket.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    return GradedAggregate(
        grader=grader.strip().upper(), grade=_grade(grade), sales_count=max(0, count),
        average_price_usd=_positive(bucket.get("averagePrice")),
        median_price_usd=_positive(bucket.get("medianPrice")),
        smart_market_price_usd=_positive(smart.get("price")),
        last_sale_date=str(bucket.get("lastSaleDate")) if bucket.get("lastSaleDate") else None,
        market_trend=str(bucket.get("marketTrend")) if bucket.get("marketTrend") else None,
    )


def _history(row: Mapping[str, object], grader: str, grade: object) -> list[DailyGradePoint]:
    ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
    histories = ebay.get("priceHistory") if isinstance(ebay.get("priceHistory"), Mapping) else {}
    days = histories.get(_grade_key(grader, grade))
    if not isinstance(days, Mapping):
        return []
    output = []
    for when, payload in sorted(days.items()):
        if not isinstance(payload, Mapping):
            continue
        try:
            count = int(payload.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        output.append(DailyGradePoint(str(when), max(0, count), _positive(payload.get("average")), _positive(payload.get("totalValue"))))
    return output


def _request(session: requests.Session, key: str, budget: PptRequestBudget, params: Mapping[str, object], timeout: float) -> tuple[int | None, object | None]:
    if not budget.can_call():
        return None, None
    budget.wait()
    try:
        response = session.get(PPT_URL, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}, params=dict(params), timeout=timeout)
    except requests.RequestException as error:
        budget.blocked_reason = f"REQUEST_ERROR:{type(error).__name__}"
        return None, None
    budget.record(getattr(response, "headers", {}) or {})
    try:
        return int(response.status_code), response.json()
    except ValueError:
        return int(response.status_code), None


def fetch_snapshot(identity: PptMacroIdentity, grader: str, grade: object, key: str, budget: PptRequestBudget, session: requests.Session, timeout: float) -> tuple[str, GradedAggregate | None, list[DailyGradePoint], str]:
    matched = None
    proof = ""
    attempts = (
        {"search": identity.name, "setName": identity.set_name, "limit": 5},
        {"search": f"{identity.name} {_num(identity.number)}", "setName": identity.set_name, "limit": 5},
        {"search": identity.name, "limit": 10},
    )
    for params in attempts:
        status, payload = _request(session, key, budget, params, timeout)
        if status is None:
            return "PENDING_BUDGET", None, [], budget.blocked_reason
        if status == 429:
            budget.blocked_reason = "RATE_LIMIT"
            return "RATE_LIMIT", None, [], "HTTP 429"
        if status != 200:
            return "PROVIDER_ERROR", None, [], f"HTTP {status}"
        match = match_macro_identity(identity, _rows(payload))
        if match.status == "AMBIGUOUS":
            return "AMBIGUOUS", None, [], match.proof
        if match.status == "EXACT":
            matched, proof = match.row, match.proof
            break
    if not isinstance(matched, Mapping):
        return "CLEAN_NO_MATCH", None, [], "NO_MACRO_MATCH"
    tcgplayer_id = matched.get("tcgPlayerId") or matched.get("tcgplayerId")
    if not tcgplayer_id:
        return "CLEAN_INSUFFICIENT", None, [], "TCGPLAYER_ID_MISSING"
    status, payload = _request(session, key, budget, {
        "tcgPlayerId": str(tcgplayer_id), "includeHistory": "true", "includeEbay": "true",
        "includeCardmarket": "false", "days": 180, "maxDataPoints": 180,
    }, timeout)
    if status is None:
        return "PENDING_BUDGET", None, [], budget.blocked_reason
    if status == 429:
        return "RATE_LIMIT", None, [], "HTTP 429"
    if status != 200:
        return "PROVIDER_ERROR", None, [], f"HTTP {status}"
    deep = match_macro_identity(identity, _rows(payload))
    if deep.status != "EXACT" or deep.row is None:
        return deep.status, None, [], "DEEP_IDENTITY_NOT_EXACT"
    aggregate = _aggregate(deep.row, grader, grade)
    if aggregate is None:
        return "CLEAN_NO_MATCH", None, [], f"GRADE_BUCKET_MISSING:{_grade_key(grader, grade)}"
    return "MATCHED", aggregate, _history(deep.row, grader, grade), proof


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


def _enabled() -> bool:
    return os.getenv("V4_PPT_SHADOW_ENABLED", "false").strip().casefold() in {"1", "true", "yes"}


def _root(state: dict) -> dict[str, Any]:
    root = state.get(STATE_KEY)
    if not isinstance(root, dict) or root.get("schema_version") != SCHEMA:
        root = {"schema_version": SCHEMA, "cache": {}, "records": {}}
        state[STATE_KEY] = root
    root.setdefault("cache", {})
    root.setdefault("records", {})
    return root


def _aware(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _cache(root: Mapping[str, Any], key: str, now: datetime, ttl: int) -> dict[str, Any] | None:
    item = root.get("cache", {}).get(key) if isinstance(root.get("cache"), Mapping) else None
    if not isinstance(item, Mapping) or not isinstance(item.get("metrics"), Mapping):
        return None
    fetched = _aware(item.get("fetched_at"))
    if fetched is None or now - fetched > timedelta(hours=ttl):
        return None
    return dict(item["metrics"])


def _gcc_exact_count(candidate: Any) -> int:
    import watcher
    target_grader = str(candidate.lot.grader or "").strip().upper()
    target_grade = watcher._target_grade(candidate.lot)
    count = 0
    for sale in getattr(candidate.gcc, "sales", []) or []:
        try:
            same_grade = target_grade is not None and float(getattr(sale, "grade", None)) == float(target_grade)
        except (TypeError, ValueError):
            same_grade = False
        if getattr(sale, "exact_card", True) is not False and str(getattr(sale, "grader", "") or "").strip().upper() == target_grader and same_grade:
            count += 1
    return count


def _record(root: dict[str, Any], identity_key: str, record: Mapping[str, Any]) -> None:
    records = root["records"]
    records[identity_key] = dict(record)
    maximum = _env_int("V4_PPT_SHADOW_MAX_STATE_RECORDS", 250, 10)
    if len(records) > maximum:
        ordered = sorted(records.items(), key=lambda pair: str(pair[1].get("observed_at") or ""))
        for old_key, _ in ordered[: len(records) - maximum]:
            records.pop(old_key, None)


def collect_ppt_shadow(candidates: Sequence[Any], opportunities: Sequence[Any], state: dict, now: datetime, *, session: requests.Session | None = None) -> dict[str, int]:
    import watcher
    import v4_canonical_multimarket as canonical_market

    summary = {"eligible": 0, "matched": 0, "strong": 0, "cache_hits": 0, "blocked_language": 0, "blocked_variant": 0, "rescue_candidates": 0, "revalue_candidates": 0}
    key = os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip()
    if not key:
        return summary
    root = _root(state)
    budget = PptRequestBudget(
        max_http_calls=_env_int("V4_PPT_SHADOW_MAX_HTTP_CALLS_PER_RUN", 12),
        credit_cap=_env_int("V4_PPT_SHADOW_CREDIT_CAP_PER_RUN", 60),
        daily_remaining_floor=_env_int("V4_PPT_SHADOW_DAILY_REMAINING_FLOOR", 15000),
        interval_seconds=_env_float("V4_PPT_SHADOW_REQUEST_INTERVAL_SECONDS", 1.10),
    )
    timeout = _env_float("V4_PPT_SHADOW_TIMEOUT_SECONDS", 20.0, 1.0)
    ttl = _env_int("V4_PPT_SHADOW_CACHE_TTL_HOURS", 6, 1)
    session = session or requests.Session()
    opportunity_by_key = {watcher.external_commercial_identity_key(op.lot): op for op in opportunities}
    usd_per_eur = canonical_market._usd_per_eur()
    if usd_per_eur is None:
        root["last_error"] = "FX_UNAVAILABLE"
        return summary

    for candidate in candidates:
        if not budget.can_call():
            break
        lot = candidate.lot
        canonical = canonical_market._canonical_from_lot(lot)
        if canonical.status != "EXACT":
            continue
        if str(canonical.language_code or "").strip().casefold() != "en":
            summary["blocked_language"] += 1
            continue
        _, variant_ok = canonical_market._raw_variant_choice(lot, canonical)
        if not variant_ok:
            summary["blocked_variant"] += 1
            continue
        grade = watcher._target_grade(lot)
        grader = str(lot.grader or "").strip().upper()
        if grade is None or not grader or lot.current_price is None:
            continue
        identity_key = watcher.external_commercial_identity_key(lot)
        opportunity = opportunity_by_key.get(identity_key)
        estimate = getattr(opportunity, "estimate", None) if opportunity is not None else getattr(candidate.gcc, "estimate", None)
        current = {
            "path": getattr(opportunity, "valuation_path", None),
            "fair_value_eur": getattr(estimate, "central", None),
            "discount_pct": getattr(opportunity, "discount_pct", None),
            "gcc_branch": getattr(candidate.gcc, "branch", None),
            "gcc_strength": getattr(candidate.gcc, "strength", None),
            "gcc_exact_sold_count": _gcc_exact_count(candidate),
            "already_opportunity": opportunity is not None,
        }
        summary["eligible"] += 1
        metrics = _cache(root, identity_key, now, ttl)
        if metrics is not None:
            summary["cache_hits"] += 1
        else:
            status, aggregate, history, proof = fetch_snapshot(
                PptMacroIdentity(canonical.card_id, canonical.name, canonical.set_name, canonical.full_number or canonical.local_id),
                grader, grade, key, budget, session, timeout,
            )
            if status != "MATCHED" or aggregate is None:
                _record(root, identity_key, {"observed_at": now.isoformat(), "status": status, "reason": proof, "current_v4": current, "evidence_class": EVIDENCE_CLASS, "upstream_class": UPSTREAM_CLASS})
                continue
            summary["matched"] += 1
            metrics = asdict(analyze_shadow(
                ShadowInput(True, True, grader, _grade(grade), float(lot.current_price), usd_per_eur, current["gcc_exact_sold_count"]),
                aggregate, history, today=now.date(),
            ))
            metrics["match_proof"] = proof
            root["cache"][identity_key] = {"fetched_at": now.isoformat(), "metrics": metrics}

        metrics = dict(metrics)
        fair = _positive(metrics.get("fair_value_eur"))
        if fair is not None:
            discount = (fair - float(lot.current_price)) / fair * 100.0
            metrics["discount_to_external_pct"] = discount
            metrics["baseline_30pct_signal"] = bool(metrics.get("evidence_strength") == "STRONG" and discount >= BASE_REQUIRED_DISCOUNT_PCT)
            metrics["kinetic_shadow_signal"] = bool(metrics.get("evidence_strength") == "STRONG" and discount >= float(metrics.get("shadow_required_discount_pct") or BASE_REQUIRED_DISCOUNT_PCT))
        if metrics.get("evidence_strength") == "STRONG":
            summary["strong"] += 1
        if metrics.get("evidence_strength") == "STRONG" and metrics.get("kinetic_shadow_signal"):
            if current["gcc_branch"] != "SUPPORTED":
                effect = "PPT_EXTERNAL_RESCUE_CANDIDATE"
                summary["rescue_candidates"] += 1
            elif not current["already_opportunity"]:
                effect = "PPT_REVALUE_CANDIDATE"
                summary["revalue_candidates"] += 1
            else:
                effect = "PPT_SUPPORTS_OR_REPRICES_CURRENT_OPPORTUNITY"
        else:
            effect = "NO_SHADOW_SIGNAL"
        _record(root, identity_key, {
            "observed_at": now.isoformat(), "status": "MATCHED", "card_id": canonical.card_id,
            "card": canonical.name, "set": canonical.set_name, "number": canonical.full_number,
            "grader": grader, "grade": _grade(grade), "gcc_price_eur": lot.current_price,
            "current_v4": current, "ppt_shadow": metrics, "shadow_effect": effect,
            "production_economic_use": False, "notification_use": False,
        })

    root["last_run"] = {"observed_at": now.isoformat(), "summary": summary, "http_calls": budget.http_calls, "credits": budget.credits, "daily_remaining": budget.daily_remaining, "blocked_reason": budget.blocked_reason, "production_economic_use": False}
    return summary


_ORIGINAL = None


def install_v4_ppt_shadow() -> None:
    global _ORIGINAL
    import watcher
    if getattr(watcher, "_v4_ppt_shadow_installed", False):
        return
    if not _enabled():
        watcher.log("PPT shadow: safe-off (V4_PPT_SHADOW_ENABLED=false)")
        return
    if not os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip():
        watcher.log("PPT shadow: safe-off (POKEMONPRICETRACKER_API_KEY missing)")
        return
    _ORIGINAL = watcher.process_external_market_candidates

    def wrapped(page, candidates, state, budgets, run_diagnostics, now, *args, **kwargs):
        opportunities = _ORIGINAL(page, candidates, state, budgets, run_diagnostics, now, *args, **kwargs)
        try:
            summary = collect_ppt_shadow(candidates, opportunities, state, now)
            watcher.log(
                "PPT shadow: "
                f"eligible {summary['eligible']} | matched {summary['matched']} | strong {summary['strong']} | "
                f"blocked-language {summary['blocked_language']} | blocked-variant {summary['blocked_variant']} | "
                f"cache {summary['cache_hits']} | rescue-hypothesis {summary['rescue_candidates']} | "
                f"revalue-hypothesis {summary['revalue_candidates']} | economic-use=false"
            )
        except Exception as error:
            watcher.log(f"PPT shadow failed open: {type(error).__name__}")
        return opportunities

    watcher.process_external_market_candidates = wrapped
    watcher._v4_ppt_shadow_installed = True
    watcher.log("PPT shadow: enabled (English-only, SOLD_AGGREGATED, no FV/max/notification changes)")
