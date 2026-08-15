from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping, Sequence


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _collector_numerator(value: object) -> str:
    compact = re.sub(r"\s+", "", str(value or "")).lstrip("#")
    token = re.sub(r"[^A-Za-z0-9]+", "", compact.split("/", 1)[0]).casefold()
    if token.isdigit():
        return str(int(token))
    match = re.fullmatch(r"([a-z]+)0*(\d+)", token)
    return f"{match.group(1)}{int(match.group(2))}" if match else token


def _set_compatible(expected: object, actual: object) -> bool:
    left, right = _norm(expected), _norm(actual)
    return bool(left and right and (left == right or right.endswith(left)))


@dataclass(frozen=True)
class CanonicalPptIdentity:
    tcgdex_id: str
    name: str
    set_name: str
    number: str
    language: str = "en"


@dataclass(frozen=True)
class PptMacroMatch:
    status: str
    candidate_count: int
    row: Mapping[str, object] | None = None
    proof: str = ""


def match_macro_identity(
    canonical: CanonicalPptIdentity,
    rows: Sequence[Mapping[str, object]],
) -> PptMacroMatch:
    """Match PPT rows without trusting descriptor-rich provider display names.

    Preferred proof is PPT `externalCatalogId`, which historical payloads show
    mirroring the canonical Pokemon catalog id (for example `swsh7-215`). The
    fallback is exact set + collector number. Provider names may contain labels
    such as `(Alternate Art Secret)` and are retrieval metadata, not identity
    proof. Microvariant proof remains separate.
    """
    by_external = [
        row for row in rows
        if _norm(row.get("externalCatalogId")) == _norm(canonical.tcgdex_id)
    ]
    if len(by_external) == 1:
        return PptMacroMatch("EXACT", 1, by_external[0], "EXTERNAL_CATALOG_ID")
    if len(by_external) > 1:
        return PptMacroMatch("AMBIGUOUS", len(by_external), proof="EXTERNAL_CATALOG_ID")

    by_set_number = [
        row for row in rows
        if _collector_numerator(row.get("cardNumber") or row.get("number"))
        == _collector_numerator(canonical.number)
        and _set_compatible(canonical.set_name, row.get("setName") or row.get("set_name"))
    ]
    if len(by_set_number) == 1:
        return PptMacroMatch("EXACT", 1, by_set_number[0], "SET_NUMBER")
    if len(by_set_number) > 1:
        return PptMacroMatch("AMBIGUOUS", len(by_set_number), proof="SET_NUMBER")
    return PptMacroMatch("UNRESOLVED", 0)


def raw_usd(row: Mapping[str, object]) -> float | None:
    prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
    for key in ("market", "low"):
        try:
            value = prices.get(key)
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            pass
    return None


def cardmarket_eur(row: Mapping[str, object]) -> float | None:
    cm = row.get("cardmarketPrices") if isinstance(row.get("cardmarketPrices"), Mapping) else {}
    for key in ("marketEur", "trendEur", "lowEur"):
        try:
            value = cm.get(key)
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            pass
    return None


def _grade_key(grader: str, grade: str | float | int) -> str:
    g = _norm(grader).replace(" ", "")
    numeric = str(grade).strip().replace(".", "_")
    return f"{g}{numeric}"


@dataclass(frozen=True)
class PptGradedAggregate:
    grade_key: str
    sales_count: int
    average_price_usd: float | None
    median_price_usd: float | None
    smart_market_price_usd: float | None
    smart_market_confidence: str | None
    last_sale_date: str | None
    market_trend: str | None


def graded_aggregate(
    row: Mapping[str, object], *, grader: str, grade: str | float | int
) -> PptGradedAggregate | None:
    ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
    sales = ebay.get("salesByGrade") if isinstance(ebay.get("salesByGrade"), Mapping) else {}
    key = _grade_key(grader, grade)
    bucket = sales.get(key)
    if not isinstance(bucket, Mapping):
        return None

    def number(name: str) -> float | None:
        try:
            value = bucket.get(name)
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    try:
        count = int(bucket.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    smart = bucket.get("smartMarketPrice") if isinstance(bucket.get("smartMarketPrice"), Mapping) else {}
    try:
        smart_price = float(smart.get("price")) if smart.get("price") is not None else None
    except (TypeError, ValueError):
        smart_price = None
    return PptGradedAggregate(
        grade_key=key,
        sales_count=count,
        average_price_usd=number("averagePrice"),
        median_price_usd=number("medianPrice"),
        smart_market_price_usd=smart_price,
        smart_market_confidence=str(smart.get("confidence")) if smart.get("confidence") else None,
        last_sale_date=str(bucket.get("lastSaleDate")) if bucket.get("lastSaleDate") else None,
        market_trend=str(bucket.get("marketTrend")) if bucket.get("marketTrend") else None,
    )


@dataclass(frozen=True)
class PptDailyGradeAggregate:
    date: str
    grade_key: str
    count: int
    average_price_usd: float | None
    total_value_usd: float | None


def daily_grade_history(
    row: Mapping[str, object], *, grader: str, grade: str | float | int
) -> list[PptDailyGradeAggregate]:
    ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
    histories = ebay.get("priceHistory") if isinstance(ebay.get("priceHistory"), Mapping) else {}
    key = _grade_key(grader, grade)
    days = histories.get(key)
    if not isinstance(days, Mapping):
        return []
    out: list[PptDailyGradeAggregate] = []
    for date, payload in sorted(days.items()):
        if not isinstance(payload, Mapping):
            continue
        try:
            count = int(payload.get("count") or 0)
        except (TypeError, ValueError):
            count = 0

        def f(field: str) -> float | None:
            try:
                value = payload.get(field)
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        out.append(PptDailyGradeAggregate(str(date), key, count, f("average"), f("totalValue")))
    return out


def total_ebay_sales(row: Mapping[str, object]) -> int | None:
    """Global provider-detected eBay count; never a PSA10 count."""
    ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
    try:
        return int(ebay.get("totalSales")) if ebay.get("totalSales") is not None else None
    except (TypeError, ValueError):
        return None
