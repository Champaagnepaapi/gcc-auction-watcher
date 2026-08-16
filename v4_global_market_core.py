from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Iterable, Mapping, Optional, Sequence

SUPPORTED_OPPORTUNITY_LANGUAGES = frozenset({"en", "ja"})

SOLD_EXACT = "SOLD_EXACT"
FIXED_ASK = "FIXED_ASK"
AUCTION_SNAPSHOT_LE5 = "AUCTION_SNAPSHOT_LE5"
ACTIVE_AUCTION = "ACTIVE_AUCTION"
FINISHED_UNPROVEN = "FINISHED_UNPROVEN"


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _norm_number(value: object) -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).upper().replace(" ", "").lstrip("#")
    if "/" not in raw:
        return raw
    left, right = raw.split("/", 1)
    if left.isdigit():
        left = str(int(left))
    if right.isdigit():
        right = str(int(right))
    return f"{left}/{right}"


def _norm_language(value: object) -> str:
    text = _norm(value)
    return {
        "en": "en",
        "english": "en",
        "anglais": "en",
        "ja": "ja",
        "jp": "ja",
        "japanese": "ja",
        "japonais": "ja",
        "fr": "fr",
        "french": "fr",
        "francais": "fr",
    }.get(text, text)


def _norm_grade(value: object) -> str:
    text = str(value or "").strip()
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class CommercialIdentity:
    name: str
    set_name: str
    number: str
    language: str
    grader: str
    grade: str
    edition: str = ""
    finish: str = ""
    variant: str = ""

    @property
    def strict_key(self) -> str:
        return "|".join(
            (
                _norm(self.name),
                _norm(self.set_name),
                _norm_number(self.number),
                _norm_language(self.language),
                _norm(self.grader).upper(),
                _norm_grade(self.grade),
                _norm(self.edition),
                _norm(self.finish),
                _norm(self.variant),
            )
        )

    @property
    def opportunity_language(self) -> bool:
        return _norm_language(self.language) in SUPPORTED_OPPORTUNITY_LANGUAGES

    @property
    def complete_for_exact_market(self) -> bool:
        return all(
            (
                _norm(self.name),
                _norm(self.set_name),
                _norm_number(self.number),
                _norm_language(self.language),
                _norm(self.grader),
                _norm_grade(self.grade),
            )
        )


@dataclass(frozen=True)
class PriceObservation:
    source: str
    identity: CommercialIdentity
    evidence_type: str
    price: float
    currency: str
    observed_at: datetime
    identity_proven: bool
    sold_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    buyer_fee_rate: Optional[float] = 0.0
    buyer_fee_flat: float = 0.0
    logistics_cost: float = 0.0
    time_adjustment_factor: Optional[float] = None
    note: str = ""
    source_id: str = ""

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError("price must be positive")
        if self.buyer_fee_rate is not None and self.buyer_fee_rate < 0:
            raise ValueError("buyer_fee_rate cannot be negative")
        if self.buyer_fee_flat < 0 or self.logistics_cost < 0:
            raise ValueError("fees cannot be negative")
        _as_utc(self.observed_at)
        if self.sold_at is not None:
            _as_utc(self.sold_at)
        if self.end_at is not None:
            _as_utc(self.end_at)

    @property
    def is_exact_sold(self) -> bool:
        return (
            self.evidence_type == SOLD_EXACT
            and self.identity_proven
            and self.sold_at is not None
            and self.identity.complete_for_exact_market
        )

    @property
    def is_offer(self) -> bool:
        return self.evidence_type in {FIXED_ASK, AUCTION_SNAPSHOT_LE5, ACTIVE_AUCTION}

    @property
    def is_actionable_offer(self) -> bool:
        return self.evidence_type in {FIXED_ASK, AUCTION_SNAPSHOT_LE5}


def to_eur(value: float, currency: str, currency_per_eur: Mapping[str, float]) -> Optional[float]:
    code = str(currency or "").strip().upper()
    if code == "EUR":
        return float(value)
    rate = currency_per_eur.get(code)
    if rate is None or rate <= 0:
        return None
    return float(value) / float(rate)


def all_in_eur(observation: PriceObservation, currency_per_eur: Mapping[str, float]) -> Optional[float]:
    if observation.buyer_fee_rate is None:
        return None
    total = (
        float(observation.price) * (1.0 + float(observation.buyer_fee_rate))
        + float(observation.buyer_fee_flat)
        + float(observation.logistics_cost)
    )
    return to_eur(total, observation.currency, currency_per_eur)


@dataclass(frozen=True)
class FairValue:
    identity: CommercialIdentity
    central_eur: float
    low_eur: float
    high_eur: float
    evidence_count: int
    recent_90_count: int
    method: str
    evidence_quality: str
    notification_safe: bool
    sources: tuple[str, ...]


def build_fair_value(
    identity: CommercialIdentity,
    evidence: Iterable[PriceObservation],
    *,
    now: datetime,
    currency_per_eur: Mapping[str, float],
    recent_days: int = 90,
    history_days: int = 365,
) -> Optional[FairValue]:
    now_utc = _as_utc(now)
    rows: list[tuple[PriceObservation, float, float]] = []
    for item in evidence:
        if item.identity.strict_key != identity.strict_key or not item.is_exact_sold:
            continue
        age_days = (now_utc - _as_utc(item.sold_at)).total_seconds() / 86400.0
        if age_days < 0 or age_days > history_days:
            continue
        eur = to_eur(item.price, item.currency, currency_per_eur)
        if eur is None or eur <= 0:
            continue
        rows.append((item, age_days, eur))

    if not rows:
        return None

    rows.sort(key=lambda row: row[1])
    recent = [row for row in rows if row[1] <= recent_days]
    if recent:
        basis = recent[:10]
        values = [row[2] for row in basis]
        count = len(basis)
        quality = "STRONG" if count >= 2 else "MODERATE"
        return FairValue(
            identity=identity,
            central_eur=round(float(median(values)), 2),
            low_eur=round(min(values), 2),
            high_eur=round(max(values), 2),
            evidence_count=count,
            recent_90_count=count,
            method="RECENT_EXACT_SOLD_MEDIAN",
            evidence_quality=quality,
            notification_safe=count >= 2,
            sources=tuple(dict.fromkeys(row[0].source for row in basis)),
        )

    adjusted: list[tuple[PriceObservation, float]] = []
    for item, _age_days, eur in rows[:10]:
        factor = item.time_adjustment_factor
        if factor is None or not (0.5 <= factor <= 2.0):
            continue
        adjusted.append((item, eur * factor))
    if len(adjusted) < 3:
        return None

    values = [value for _item, value in adjusted]
    return FairValue(
        identity=identity,
        central_eur=round(float(median(values)), 2),
        low_eur=round(min(values), 2),
        high_eur=round(max(values), 2),
        evidence_count=len(values),
        recent_90_count=0,
        method="TIME_ADJUSTED_EXACT_SOLD_MEDIAN",
        evidence_quality="MODERATE",
        notification_safe=True,
        sources=tuple(dict.fromkeys(item.source for item, _value in adjusted)),
    )


@dataclass(frozen=True)
class OfferAnalysis:
    observation: PriceObservation
    all_in_eur: Optional[float]
    discount_to_fair_pct: Optional[float]
    rank: Optional[int]
    gap_to_best_pct: Optional[float]
    notify_eligible: bool
    reason: str


@dataclass(frozen=True)
class MarketCompetition:
    fair_value: FairValue
    offers: tuple[OfferAnalysis, ...]
    best_source: str = ""
    best_all_in_eur: Optional[float] = None


def compare_market_offers(
    fair_value: FairValue,
    offers: Sequence[PriceObservation],
    *,
    currency_per_eur: Mapping[str, float],
    min_discount_pct: float = 30.0,
) -> MarketCompetition:
    staged: list[tuple[PriceObservation, Optional[float], Optional[float], str]] = []
    for item in offers:
        if item.identity.strict_key != fair_value.identity.strict_key:
            continue
        if not item.identity_proven or not item.identity.complete_for_exact_market:
            staged.append((item, None, None, "IDENTITY_UNPROVEN"))
            continue
        if not item.identity.opportunity_language:
            staged.append((item, None, None, "LANGUAGE_NOT_ACTIONABLE"))
            continue
        landed = all_in_eur(item, currency_per_eur)
        if landed is None:
            staged.append((item, None, None, "ALL_IN_UNPROVEN"))
            continue
        discount = (fair_value.central_eur - landed) / fair_value.central_eur * 100.0
        if item.evidence_type == ACTIVE_AUCTION:
            reason = "ACTIVE_AUCTION_WEAK_SIGNAL"
        elif item.evidence_type == FIXED_ASK:
            reason = "FIXED_ASK"
        elif item.evidence_type == AUCTION_SNAPSHOT_LE5:
            reason = "AUCTION_SNAPSHOT_LE5"
        else:
            reason = "NOT_AN_ACTIONABLE_OFFER"
        staged.append((item, landed, discount, reason))

    ranked_rows = sorted(
        [row for row in staged if row[1] is not None],
        key=lambda row: (float(row[1]), row[0].source, row[0].source_id),
    )
    ranks = {id(row[0]): index + 1 for index, row in enumerate(ranked_rows)}
    best = float(ranked_rows[0][1]) if ranked_rows else None

    output: list[OfferAnalysis] = []
    for item, landed, discount, reason in staged:
        rank = ranks.get(id(item)) if landed is not None else None
        gap = ((float(landed) - best) / best * 100.0) if landed is not None and best else None
        notify = bool(
            landed is not None
            and discount is not None
            and fair_value.notification_safe
            and item.is_actionable_offer
            and discount + 1e-9 >= min_discount_pct
        )
        output.append(
            OfferAnalysis(
                observation=item,
                all_in_eur=round(float(landed), 2) if landed is not None else None,
                discount_to_fair_pct=round(float(discount), 1) if discount is not None else None,
                rank=rank,
                gap_to_best_pct=round(float(gap), 1) if gap is not None else None,
                notify_eligible=notify,
                reason=reason,
            )
        )

    output.sort(key=lambda row: (row.rank is None, row.rank or 10**9, row.observation.source))
    best_source = ranked_rows[0][0].source if ranked_rows else ""
    return MarketCompetition(
        fair_value=fair_value,
        offers=tuple(output),
        best_source=best_source,
        best_all_in_eur=round(best, 2) if best is not None else None,
    )
