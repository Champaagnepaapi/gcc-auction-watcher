"""Cross-language PokemonPriceTracker shadow bridge for V4.

Important semantics:
- a French physical card is never re-labeled as an English physical card;
- TCGdex same-card-id EN metadata is retrieval-only identity bridging;
- PPT EN graded eBay aggregates remain an EN market anchor;
- FR fair value is produced only when an empirical FR/EN basis is calibrated
  from exact GCC FR SOLD of the same card + grader + grade against dated PPT EN
  history;
- without that calibration, the EN anchor is informative only and cannot create
  an EXTERNAL_RESCUE/revalue hypothesis;
- production opportunities are returned unchanged and no notification is sent.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Mapping, Sequence

import requests

import v4_ppt_shadow_provider as ppt_base
from v4_ppt_shadow_model import (
    BASE_REQUIRED_DISCOUNT_PCT,
    DailyGradePoint,
    ShadowInput,
    analyze_shadow,
)

STATE_KEY = "v4_ppt_shadow"
SCHEMA = 2

RELATION_EXACT_LANGUAGE = "EXACT_LANGUAGE"
RELATION_CROSS_LANGUAGE_EN = "CROSS_LANGUAGE_EN_ANCHOR"

MIN_LANGUAGE_BASIS_PAIRS = 3
MIN_LANGUAGE_BASIS_DISTINCT_DAYS = 2
MIN_LANGUAGE_BASIS_RECENT_90D = 1
MAX_LANGUAGE_BASIS_RELATIVE_MAD = 0.25
LANGUAGE_PAIR_MAX_DAY_GAP = 7
CROSS_LANGUAGE_SAFETY_PP = 10.0


@dataclass(frozen=True)
class PptMarketIdentity:
    status: str
    identity: ppt_base.PptMacroIdentity | None
    listing_language: str
    provider_language: str
    market_relation: str
    proof: str


@dataclass(frozen=True)
class LanguageBasis:
    status: str
    ratio_fr_per_en: float | None
    pair_count: int
    distinct_sale_days: int
    recent_pairs_90d: int
    latest_pair_age_days: int | None
    relative_mad: float | None
    pair_day_gap_max: int
    fx_method: str = "CURRENT_USD_PER_EUR_FOR_HISTORICAL_PAIR_NORMALIZATION"


class _EnglishPptSession:
    """Force PPT English explicitly; the provider defaults to English today."""

    def __init__(self, inner: requests.Session):
        self.inner = inner

    def get(self, url: str, *args: Any, **kwargs: Any):
        params = dict(kwargs.pop("params", {}) or {})
        params.setdefault("language", "english")
        return self.inner.get(url, *args, params=params, **kwargs)


def _positive(value: object) -> float | None:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and number > 0 else None


def _parse_day(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _grade_text(value: object) -> str:
    return ppt_base._grade(value)


def _same_grade(left: object, right: object) -> bool:
    return _grade_text(left) == _grade_text(right)


def _same_local_id(left: object, right: object) -> bool:
    return ppt_base._num(left) == ppt_base._num(right)


def _root(state: dict[str, Any]) -> dict[str, Any]:
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


def _cache(
    root: Mapping[str, Any], identity_key: str, now: datetime, ttl_hours: int
) -> tuple[dict[str, Any], list[DailyGradePoint]] | None:
    cache = root.get("cache") if isinstance(root.get("cache"), Mapping) else {}
    item = cache.get(identity_key) if isinstance(cache, Mapping) else None
    if not isinstance(item, Mapping):
        return None
    fetched = _aware(item.get("fetched_at"))
    if fetched is None or now - fetched > timedelta(hours=ttl_hours):
        return None
    provider_metrics = item.get("provider_metrics")
    raw_history = item.get("history")
    if not isinstance(provider_metrics, Mapping) or not isinstance(raw_history, Sequence):
        return None
    history: list[DailyGradePoint] = []
    for point in raw_history:
        if not isinstance(point, Mapping):
            continue
        history.append(
            DailyGradePoint(
                date=str(point.get("date") or ""),
                count=int(point.get("count") or 0),
                average_price_usd=_positive(point.get("average_price_usd")),
                total_value_usd=_positive(point.get("total_value_usd")),
            )
        )
    return dict(provider_metrics), history


def _record(root: dict[str, Any], identity_key: str, record: Mapping[str, Any]) -> None:
    records = root["records"]
    records[identity_key] = dict(record)
    maximum = ppt_base._env_int("V4_PPT_SHADOW_MAX_STATE_RECORDS", 250, 10)
    if len(records) <= maximum:
        return
    ordered = sorted(
        records.items(), key=lambda pair: str(pair[1].get("observed_at") or "")
    )
    for old_key, _ in ordered[: len(records) - maximum]:
        records.pop(old_key, None)


def resolve_ppt_market_identity(canonical: Any, canonical_market: Any) -> PptMarketIdentity:
    language = str(getattr(canonical, "language_code", "") or "").strip().casefold()
    if language == "en":
        return PptMarketIdentity(
            status="EXACT",
            identity=ppt_base.PptMacroIdentity(
                canonical.card_id,
                canonical.name,
                canonical.set_name,
                canonical.full_number or canonical.local_id,
            ),
            listing_language="en",
            provider_language="en",
            market_relation=RELATION_EXACT_LANGUAGE,
            proof="TCGDEX_LISTING_EN_EXACT",
        )

    if language != "fr":
        return PptMarketIdentity(
            status="UNSUPPORTED_LANGUAGE",
            identity=None,
            listing_language=language,
            provider_language="",
            market_relation="UNAVAILABLE",
            proof="PPT_SHADOW_CURRENTLY_SUPPORTS_EN_EXACT_AND_FR_TO_EN_BRIDGE",
        )

    try:
        status, english = canonical_market._fetch_tcgdex_card_detail(
            "en", canonical.card_id
        )
    except Exception as error:
        return PptMarketIdentity(
            status="BRIDGE_ERROR",
            identity=None,
            listing_language="fr",
            provider_language="en",
            market_relation=RELATION_CROSS_LANGUAGE_EN,
            proof=f"TCGDEX_EN_DETAIL_ERROR:{type(error).__name__}",
        )

    if status != 200 or not isinstance(english, Mapping):
        return PptMarketIdentity(
            status="BRIDGE_UNRESOLVED",
            identity=None,
            listing_language="fr",
            provider_language="en",
            market_relation=RELATION_CROSS_LANGUAGE_EN,
            proof=f"TCGDEX_EN_DETAIL_HTTP_{status}",
        )

    english_id = str(english.get("id") or "").strip()
    english_local_id = str(english.get("localId") or "").strip()
    english_set = english.get("set") if isinstance(english.get("set"), Mapping) else {}
    english_set_id = str(english_set.get("id") or "").strip()
    english_set_name = str(english_set.get("name") or "").strip()
    english_name = str(english.get("name") or "").strip()

    if english_id != str(canonical.card_id or "").strip():
        return PptMarketIdentity(
            "BRIDGE_CONFLICT", None, "fr", "en", RELATION_CROSS_LANGUAGE_EN,
            "TCGDEX_CARD_ID_CHANGED_ACROSS_LANGUAGE",
        )
    if getattr(canonical, "set_id", "") and english_set_id != str(canonical.set_id).strip():
        return PptMarketIdentity(
            "BRIDGE_CONFLICT", None, "fr", "en", RELATION_CROSS_LANGUAGE_EN,
            "TCGDEX_SET_ID_CHANGED_ACROSS_LANGUAGE",
        )
    if not _same_local_id(english_local_id, getattr(canonical, "local_id", "")):
        return PptMarketIdentity(
            "BRIDGE_CONFLICT", None, "fr", "en", RELATION_CROSS_LANGUAGE_EN,
            "TCGDEX_LOCAL_ID_CHANGED_ACROSS_LANGUAGE",
        )
    if not all((english_name, english_set_name, english_local_id)):
        return PptMarketIdentity(
            "BRIDGE_INCOMPLETE", None, "fr", "en", RELATION_CROSS_LANGUAGE_EN,
            "TCGDEX_EN_ALIAS_INCOMPLETE",
        )

    official = ""
    counts = english_set.get("cardCount") if isinstance(english_set.get("cardCount"), Mapping) else {}
    if isinstance(counts, Mapping) and counts.get("official") is not None:
        official = str(counts.get("official")).strip()
    english_number = (
        f"{english_local_id}/{official}"
        if official
        else str(getattr(canonical, "full_number", "") or english_local_id)
    )

    return PptMarketIdentity(
        status="EXACT_BRIDGE",
        identity=ppt_base.PptMacroIdentity(
            canonical.card_id,
            english_name,
            english_set_name,
            english_number,
        ),
        listing_language="fr",
        provider_language="en",
        market_relation=RELATION_CROSS_LANGUAGE_EN,
        proof="TCGDEX_SAME_CARD_ID_SET_ID_LOCAL_ID_FR_TO_EN",
    )


def _exact_gcc_sales(candidate: Any, grader: str, grade: object) -> list[Any]:
    output: list[Any] = []
    for sale in getattr(candidate.gcc, "sales", []) or []:
        if getattr(sale, "exact_card", True) is False:
            continue
        if str(getattr(sale, "source", "gcc") or "gcc").strip().casefold() != "gcc":
            continue
        if str(getattr(sale, "grader", "") or "").strip().upper() != grader.strip().upper():
            continue
        if not _same_grade(getattr(sale, "grade", None), grade):
            continue
        if _positive(getattr(sale, "price", None)) is None:
            continue
        if _parse_day(getattr(sale, "sold_at", None)) is None:
            continue
        output.append(sale)
    return output


def _history_candidates(history: Sequence[DailyGradePoint]) -> list[tuple[DailyGradePoint, date]]:
    output: list[tuple[DailyGradePoint, date]] = []
    for point in history:
        day = _parse_day(point.date)
        if day is None or point.count <= 0 or _positive(point.average_price_usd) is None:
            continue
        output.append((point, day))
    return output


def estimate_fr_en_language_basis(
    candidate: Any,
    history: Sequence[DailyGradePoint],
    *,
    grader: str,
    grade: object,
    usd_per_eur: float,
    today: date,
) -> LanguageBasis:
    if usd_per_eur <= 0:
        return LanguageBasis("FX_UNAVAILABLE", None, 0, 0, 0, None, None, 0)

    points = _history_candidates(history)
    ratios: list[float] = []
    sale_days: list[date] = []
    pair_gaps: list[int] = []

    for sale in _exact_gcc_sales(candidate, grader, grade):
        sold_day = _parse_day(getattr(sale, "sold_at", None))
        if sold_day is None or not points:
            continue
        nearest_point, nearest_day = min(
            points, key=lambda item: abs((item[1] - sold_day).days)
        )
        gap = abs((nearest_day - sold_day).days)
        if gap > LANGUAGE_PAIR_MAX_DAY_GAP:
            continue
        en_usd = _positive(nearest_point.average_price_usd)
        fr_eur = _positive(getattr(sale, "price", None))
        if en_usd is None or fr_eur is None:
            continue
        en_eur = en_usd / usd_per_eur
        if en_eur <= 0:
            continue
        ratio = fr_eur / en_eur
        if ratio <= 0:
            continue
        ratios.append(ratio)
        sale_days.append(sold_day)
        pair_gaps.append(gap)

    if not ratios:
        return LanguageBasis("NO_EXACT_FR_EN_PAIRS", None, 0, 0, 0, None, None, 0)

    center = float(median(ratios))
    relative_mad = (
        float(median(abs(value - center) for value in ratios)) / center
        if center > 0
        else None
    )
    distinct_days = len(set(sale_days))
    ages = [(today - day).days for day in sale_days if today >= day]
    recent_pairs = sum(1 for age in ages if age <= 90)
    latest_age = min(ages) if ages else None

    if len(ratios) < MIN_LANGUAGE_BASIS_PAIRS:
        status = "INSUFFICIENT_PAIRS"
    elif distinct_days < MIN_LANGUAGE_BASIS_DISTINCT_DAYS:
        status = "INSUFFICIENT_TEMPORAL_SPREAD"
    elif recent_pairs < MIN_LANGUAGE_BASIS_RECENT_90D:
        status = "STALE_BASIS"
    elif relative_mad is None or relative_mad > MAX_LANGUAGE_BASIS_RELATIVE_MAD:
        status = "DISPERSED_BASIS"
    else:
        status = "CALIBRATED"

    return LanguageBasis(
        status=status,
        ratio_fr_per_en=center,
        pair_count=len(ratios),
        distinct_sale_days=distinct_days,
        recent_pairs_90d=recent_pairs,
        latest_pair_age_days=latest_age,
        relative_mad=relative_mad,
        pair_day_gap_max=max(pair_gaps) if pair_gaps else 0,
    )


def _apply_language_relation(
    metrics: Mapping[str, Any],
    *,
    relation: PptMarketIdentity,
    candidate: Any,
    history: Sequence[DailyGradePoint],
    grader: str,
    grade: object,
    usd_per_eur: float,
    now: datetime,
) -> tuple[dict[str, Any], bool]:
    output = dict(metrics)
    anchor_fair_eur = _positive(output.get("fair_value_eur"))
    anchor_fair_usd = _positive(output.get("fair_value_usd"))
    anchor_strength = str(output.get("evidence_strength") or "UNAVAILABLE")
    gcc_price = _positive(getattr(candidate.lot, "current_price", None))

    output.update(
        {
            "listing_language": relation.listing_language,
            "provider_market_language": relation.provider_language,
            "market_relation": relation.market_relation,
            "market_relation_proof": relation.proof,
            "exact_language_comparable": relation.market_relation == RELATION_EXACT_LANGUAGE,
            "ppt_anchor_evidence_strength": anchor_strength,
            "anchor_fair_value_eur": anchor_fair_eur,
            "anchor_fair_value_usd": anchor_fair_usd,
            "anchor_discount_pct_unadjusted": (
                (anchor_fair_eur - gcc_price) / anchor_fair_eur * 100.0
                if anchor_fair_eur and gcc_price is not None
                else None
            ),
            "language_basis_status": "NOT_REQUIRED",
            "language_basis_ratio_fr_per_en": None,
            "language_basis_pairs": 0,
            "language_basis_distinct_days": 0,
            "language_basis_recent_pairs_90d": 0,
            "language_basis_latest_pair_age_days": None,
            "language_basis_relative_mad": None,
            "language_basis_pair_day_gap_max": 0,
            "language_basis_fx_method": None,
            "cross_language_safety_pp": 0.0,
            "economic_eligible_in_shadow": anchor_strength == "STRONG",
        }
    )

    if relation.market_relation == RELATION_EXACT_LANGUAGE:
        return output, anchor_strength == "STRONG"

    basis = estimate_fr_en_language_basis(
        candidate,
        history,
        grader=grader,
        grade=grade,
        usd_per_eur=usd_per_eur,
        today=now.date(),
    )
    output.update(
        {
            "language_basis_status": basis.status,
            "language_basis_ratio_fr_per_en": basis.ratio_fr_per_en,
            "language_basis_pairs": basis.pair_count,
            "language_basis_distinct_days": basis.distinct_sale_days,
            "language_basis_recent_pairs_90d": basis.recent_pairs_90d,
            "language_basis_latest_pair_age_days": basis.latest_pair_age_days,
            "language_basis_relative_mad": basis.relative_mad,
            "language_basis_pair_day_gap_max": basis.pair_day_gap_max,
            "language_basis_fx_method": basis.fx_method,
            "cross_language_safety_pp": CROSS_LANGUAGE_SAFETY_PP,
            "fair_value_usd": None,
            "fair_value_eur": None,
            "discount_to_external_pct": None,
            "baseline_30pct_signal": False,
            "kinetic_shadow_signal": False,
            "economic_eligible_in_shadow": False,
        }
    )

    if (
        basis.status != "CALIBRATED"
        or basis.ratio_fr_per_en is None
        or anchor_fair_eur is None
        or gcc_price is None
    ):
        return output, False

    adjusted_fair = anchor_fair_eur * basis.ratio_fr_per_en
    discount = (adjusted_fair - gcc_price) / adjusted_fair * 100.0
    base_required = float(
        output.get("shadow_required_discount_pct") or BASE_REQUIRED_DISCOUNT_PCT
    )
    required = max(
        BASE_REQUIRED_DISCOUNT_PCT,
        min(50.0, base_required + CROSS_LANGUAGE_SAFETY_PP),
    )
    actionable = anchor_strength == "STRONG"
    output.update(
        {
            "fair_value_eur": adjusted_fair,
            "discount_to_external_pct": discount,
            "shadow_required_discount_pct": required,
            "baseline_30pct_signal": bool(actionable and discount >= max(BASE_REQUIRED_DISCOUNT_PCT, required)),
            "kinetic_shadow_signal": bool(actionable and discount >= required),
            "economic_eligible_in_shadow": actionable,
            "valuation_evidence_strength": "CALIBRATED_CROSS_LANGUAGE" if actionable else "WEAK_CROSS_LANGUAGE",
        }
    )
    return output, actionable


def _gcc_exact_count(candidate: Any, grader: str, grade: object) -> int:
    return len(_exact_gcc_sales(candidate, grader, grade))


def collect_ppt_shadow_cross_language(
    candidates: Sequence[Any],
    opportunities: Sequence[Any],
    state: dict[str, Any],
    now: datetime,
    *,
    session: requests.Session | None = None,
) -> dict[str, int]:
    import watcher
    import v4_canonical_multimarket as canonical_market

    summary = {
        "eligible": 0,
        "matched": 0,
        "strong": 0,
        "exact_language": 0,
        "cross_language_anchor": 0,
        "cross_language_calibrated": 0,
        "anchor_only": 0,
        "bridge_failed": 0,
        "cache_hits": 0,
        "blocked_language": 0,
        "blocked_variant": 0,
        "rescue_candidates": 0,
        "revalue_candidates": 0,
    }
    api_key = os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip()
    if not api_key:
        return summary

    root = _root(state)
    budget = ppt_base.PptRequestBudget(
        max_http_calls=ppt_base._env_int("V4_PPT_SHADOW_MAX_HTTP_CALLS_PER_RUN", 12),
        credit_cap=ppt_base._env_int("V4_PPT_SHADOW_CREDIT_CAP_PER_RUN", 60),
        daily_remaining_floor=ppt_base._env_int("V4_PPT_SHADOW_DAILY_REMAINING_FLOOR", 15000),
        interval_seconds=ppt_base._env_float("V4_PPT_SHADOW_REQUEST_INTERVAL_SECONDS", 1.10),
    )
    timeout = ppt_base._env_float("V4_PPT_SHADOW_TIMEOUT_SECONDS", 20.0, 1.0)
    ttl = ppt_base._env_int("V4_PPT_SHADOW_CACHE_TTL_HOURS", 6, 1)
    raw_session = session or requests.Session()
    ppt_session = _EnglishPptSession(raw_session)
    opportunity_by_key = {
        watcher.external_commercial_identity_key(op.lot): op for op in opportunities
    }
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

        _, variant_ok = canonical_market._raw_variant_choice(lot, canonical)
        if not variant_ok:
            summary["blocked_variant"] += 1
            continue

        market_identity = resolve_ppt_market_identity(canonical, canonical_market)
        if market_identity.status == "UNSUPPORTED_LANGUAGE":
            summary["blocked_language"] += 1
            continue
        if market_identity.identity is None:
            summary["bridge_failed"] += 1
            identity_key = watcher.external_commercial_identity_key(lot)
            _record(
                root,
                identity_key,
                {
                    "observed_at": now.isoformat(),
                    "status": market_identity.status,
                    "reason": market_identity.proof,
                    "card_id": canonical.card_id,
                    "listing_language": market_identity.listing_language,
                    "provider_market_language": market_identity.provider_language,
                    "market_relation": market_identity.market_relation,
                    "production_economic_use": False,
                    "notification_use": False,
                },
            )
            continue

        grade = watcher._target_grade(lot)
        grader = str(lot.grader or "").strip().upper()
        if grade is None or not grader or lot.current_price is None:
            continue

        identity_key = watcher.external_commercial_identity_key(lot)
        opportunity = opportunity_by_key.get(identity_key)
        estimate = (
            getattr(opportunity, "estimate", None)
            if opportunity is not None
            else getattr(candidate.gcc, "estimate", None)
        )
        current = {
            "path": getattr(opportunity, "valuation_path", None),
            "fair_value_eur": getattr(estimate, "central", None),
            "discount_pct": getattr(opportunity, "discount_pct", None),
            "gcc_branch": getattr(candidate.gcc, "branch", None),
            "gcc_strength": getattr(candidate.gcc, "strength", None),
            "gcc_exact_sold_count": _gcc_exact_count(candidate, grader, grade),
            "already_opportunity": opportunity is not None,
        }
        summary["eligible"] += 1
        if market_identity.market_relation == RELATION_EXACT_LANGUAGE:
            summary["exact_language"] += 1
        else:
            summary["cross_language_anchor"] += 1

        cached = _cache(root, identity_key, now, ttl)
        if cached is not None:
            summary["cache_hits"] += 1
            provider_metrics, history = cached
        else:
            status, aggregate, history, proof = ppt_base.fetch_snapshot(
                market_identity.identity,
                grader,
                grade,
                api_key,
                budget,
                ppt_session,
                timeout,
            )
            if status != "MATCHED" or aggregate is None:
                _record(
                    root,
                    identity_key,
                    {
                        "observed_at": now.isoformat(),
                        "status": status,
                        "reason": proof,
                        "card_id": canonical.card_id,
                        "card": canonical.name,
                        "set": canonical.set_name,
                        "number": canonical.full_number,
                        "grader": grader,
                        "grade": _grade_text(grade),
                        "gcc_price_eur": lot.current_price,
                        "current_v4": current,
                        "listing_language": market_identity.listing_language,
                        "provider_market_language": market_identity.provider_language,
                        "market_relation": market_identity.market_relation,
                        "market_relation_proof": market_identity.proof,
                        "evidence_class": "SOLD_AGGREGATED",
                        "upstream_class": "EBAY_SOLD_AGGREGATED_VIA_PPT",
                        "production_economic_use": False,
                        "notification_use": False,
                    },
                )
                continue

            summary["matched"] += 1
            provider_metrics = asdict(
                analyze_shadow(
                    ShadowInput(
                        True,
                        True,
                        grader,
                        _grade_text(grade),
                        float(lot.current_price),
                        usd_per_eur,
                        current["gcc_exact_sold_count"],
                    ),
                    aggregate,
                    history,
                    today=now.date(),
                )
            )
            provider_metrics["match_proof"] = proof
            root["cache"][identity_key] = {
                "fetched_at": now.isoformat(),
                "provider_metrics": provider_metrics,
                "history": [asdict(point) for point in history],
            }

        metrics, shadow_economic_eligible = _apply_language_relation(
            provider_metrics,
            relation=market_identity,
            candidate=candidate,
            history=history,
            grader=grader,
            grade=grade,
            usd_per_eur=usd_per_eur,
            now=now,
        )
        if metrics.get("ppt_anchor_evidence_strength") == "STRONG":
            summary["strong"] += 1

        if market_identity.market_relation == RELATION_CROSS_LANGUAGE_EN:
            if metrics.get("language_basis_status") == "CALIBRATED":
                summary["cross_language_calibrated"] += 1
            else:
                summary["anchor_only"] += 1

        signal = bool(
            shadow_economic_eligible and metrics.get("kinetic_shadow_signal")
        )
        if signal:
            if market_identity.market_relation == RELATION_CROSS_LANGUAGE_EN:
                prefix = "PPT_CROSS_LANGUAGE_CALIBRATED"
            else:
                prefix = "PPT"
            if current["gcc_branch"] != "SUPPORTED":
                effect = f"{prefix}_EXTERNAL_RESCUE_CANDIDATE"
                summary["rescue_candidates"] += 1
            elif not current["already_opportunity"]:
                effect = f"{prefix}_REVALUE_CANDIDATE"
                summary["revalue_candidates"] += 1
            else:
                effect = f"{prefix}_SUPPORTS_OR_REPRICES_CURRENT_OPPORTUNITY"
        elif market_identity.market_relation == RELATION_CROSS_LANGUAGE_EN:
            effect = "PPT_CROSS_LANGUAGE_ANCHOR_ONLY"
        else:
            effect = "NO_SHADOW_SIGNAL"

        _record(
            root,
            identity_key,
            {
                "observed_at": now.isoformat(),
                "status": "MATCHED",
                "card_id": canonical.card_id,
                "card": canonical.name,
                "set": canonical.set_name,
                "number": canonical.full_number,
                "grader": grader,
                "grade": _grade_text(grade),
                "gcc_price_eur": lot.current_price,
                "listing_language": market_identity.listing_language,
                "provider_market_language": market_identity.provider_language,
                "market_relation": market_identity.market_relation,
                "market_relation_proof": market_identity.proof,
                "ppt_lookup_name": market_identity.identity.name,
                "ppt_lookup_set": market_identity.identity.set_name,
                "current_v4": current,
                "ppt_shadow": metrics,
                "shadow_effect": effect,
                "production_economic_use": False,
                "notification_use": False,
            },
        )

    root["last_run"] = {
        "observed_at": now.isoformat(),
        "summary": summary,
        "http_calls": budget.http_calls,
        "credits": budget.credits,
        "daily_remaining": budget.daily_remaining,
        "blocked_reason": budget.blocked_reason,
        "production_economic_use": False,
        "notification_use": False,
    }
    return summary


_ORIGINAL = None


def install_v4_ppt_shadow_language_bridge() -> None:
    global _ORIGINAL
    import watcher

    if getattr(watcher, "_v4_ppt_shadow_installed", False):
        return
    if not ppt_base._enabled():
        watcher.log("PPT shadow: safe-off (V4_PPT_SHADOW_ENABLED=false)")
        return
    if not os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip():
        watcher.log("PPT shadow: safe-off (POKEMONPRICETRACKER_API_KEY missing)")
        return

    _ORIGINAL = watcher.process_external_market_candidates

    def wrapped(page, candidates, state, budgets, run_diagnostics, now, *args, **kwargs):
        opportunities = _ORIGINAL(
            page, candidates, state, budgets, run_diagnostics, now, *args, **kwargs
        )
        try:
            summary = collect_ppt_shadow_cross_language(
                candidates, opportunities, state, now
            )
            watcher.log(
                "PPT shadow: "
                f"eligible {summary['eligible']} | matched {summary['matched']} | "
                f"PPT-anchor-strong {summary['strong']} | exact-language {summary['exact_language']} | "
                f"FR->EN-anchor {summary['cross_language_anchor']} | "
                f"FR->EN-calibrated {summary['cross_language_calibrated']} | "
                f"anchor-only {summary['anchor_only']} | bridge-failed {summary['bridge_failed']} | "
                f"blocked-language {summary['blocked_language']} | blocked-variant {summary['blocked_variant']} | "
                f"cache {summary['cache_hits']} | rescue-hypothesis {summary['rescue_candidates']} | "
                f"revalue-hypothesis {summary['revalue_candidates']} | economic-use=false"
            )
        except Exception as error:
            watcher.log(f"PPT shadow failed open: {type(error).__name__}")
        return opportunities

    watcher.process_external_market_candidates = wrapped
    watcher._v4_ppt_shadow_installed = True
    watcher.log(
        "PPT shadow: enabled (EN exact + deterministic FR->EN market anchor; "
        "FR valuation only after empirical same-card FR/EN calibration; "
        "SOLD_AGGREGATED; no FV/max/notification production changes)"
    )
