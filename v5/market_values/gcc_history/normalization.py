from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Optional, Tuple

from .identity import canonicalize_collectible
from .models import CanonicalCollectible, GCCSale, Grader, SaleType


_GRADER_ALIASES = {
    "psa": Grader.PSA,
    "professional sports authenticator": Grader.PSA,
    "pca": Grader.PCA,
    "professional card authenticator": Grader.PCA,
    "bgs": Grader.BGS,
    "beckett": Grader.BGS,
    "beckett grading services": Grader.BGS,
    "cgc": Grader.CGC,
    "certified guaranty company": Grader.CGC,
    "sgc": Grader.SGC,
    "sportscard guaranty": Grader.SGC,
    "raw": Grader.RAW,
    "ungraded": Grader.RAW,
    "non graded": Grader.RAW,
    "not graded": Grader.RAW,
    "sans grade": Grader.RAW,
}

_SOLD_STATUSES = {"sold", "completed", "complete", "vendu", "closed sold"}
_SALE_TYPES = {
    "auction": SaleType.AUCTION,
    "enchere": SaleType.AUCTION,
    "fixed price": SaleType.FIXED_PRICE,
    "buy it now": SaleType.FIXED_PRICE,
    "accepted offer": SaleType.ACCEPTED_OFFER,
    "best offer accepted": SaleType.ACCEPTED_OFFER,
}


def normalize_grader(value: object) -> Grader:
    normalized = re.sub(r"\s+", " ", str(value or "").strip().casefold())
    if normalized in _GRADER_ALIASES:
        return _GRADER_ALIASES[normalized]
    for alias, grader in _GRADER_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return grader
    return Grader.UNKNOWN


def normalize_grade(
    value: object, grader: Grader
) -> Tuple[Optional[Decimal], Optional[str]]:
    if grader in {Grader.RAW, Grader.UNKNOWN}:
        return None, None if value is None else str(value).strip() or None
    raw = str(value or "").strip()
    if not raw:
        return None, None
    match = re.search(r"(?<!\d)(10(?:\.0)?|[1-9](?:\.\d)?)(?!\d)", raw)
    if not match:
        return None, raw.upper()
    grade = Decimal(match.group(1)).normalize()
    qualifier = (raw[: match.start()] + " " + raw[match.end() :]).upper()
    # Descriptive grade words and grader labels are not economic qualifiers.
    # Marks such as OC, MK, ST, PD or a BGS label designation remain intact.
    for descriptor in (
        "PROFESSIONAL SPORTS AUTHENTICATOR",
        "PROFESSIONAL CARD AUTHENTICATOR",
        "BECKETT GRADING SERVICES",
        "NEAR MINT-MINT",
        "NEAR MINT MINT",
        "GEM MINT",
        "NM-MT",
        "MINT",
        "PSA",
        "PCA",
        "BGS",
        "CGC",
        "SGC",
    ):
        qualifier = qualifier.replace(descriptor, " ")
    qualifier = re.sub(r"\s+", " ", qualifier).strip(" -/") or None
    return grade, qualifier


def _optional_bool(value: object) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized in {"true", "yes", "1", "oui"}:
        return True
    if normalized in {"false", "no", "0", "non"}:
        return False
    return None


def _parse_date(value: object) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class GCCSaleParser:
    """Normalize exported/offline sale records. This class performs no I/O."""

    def parse_record(self, record: Mapping[str, object]) -> Optional[GCCSale]:
        status = str(record.get("status") or "").strip().casefold()
        completed = _optional_bool(record.get("completed"))
        if status not in _SOLD_STATUSES and completed is not True:
            return None

        try:
            price = Decimal(str(record.get("price")))
        except (InvalidOperation, TypeError, ValueError):
            return None
        currency = str(record.get("currency") or "").strip().upper()
        if price < 0 or not re.fullmatch(r"[A-Z]{3}", currency):
            return None

        grader = normalize_grader(record.get("grader"))
        grade, qualifier = normalize_grade(record.get("grade"), grader)
        identity = canonicalize_collectible(
            CanonicalCollectible(
                card_name=_string(record.get("card_name")),
                set_name=_string(record.get("set_name")),
                card_number=_string(record.get("card_number")),
                language=_string(record.get("language")),
                variant=_string(record.get("variant")),
                first_edition=_optional_bool(record.get("first_edition")),
                finish=_string(record.get("finish")),
                promo=_optional_bool(record.get("promo")),
                stamped=_optional_bool(record.get("stamped")),
                special_print=_string(record.get("special_print")),
                year=_integer(record.get("year")),
                set_family=_string(record.get("set_family")),
                category=_string(record.get("category")) or "pokemon",
            )
        )
        sale_type_text = re.sub(
            r"\s+", " ", str(record.get("sale_type") or "").strip().casefold()
        )
        return GCCSale(
            source=_string(record.get("source")) or "GCC_HISTORY",
            identity=identity,
            grader=grader,
            grade=grade,
            grade_qualifier=qualifier,
            price=price,
            currency=currency,
            sale_date=_parse_date(record.get("sale_date")),
            sale_type=_SALE_TYPES.get(sale_type_text, SaleType.UNKNOWN),
            completed=True,
            listing_title=_string(record.get("listing_title")),
            source_id=_string(record.get("source_id")),
            source_url=_string(record.get("source_url")),
        )

    def parse_records(
        self, records: Iterable[Mapping[str, object]]
    ) -> Tuple[Tuple[GCCSale, ...], int]:
        parsed: list[GCCSale] = []
        invalid = 0
        for record in records:
            sale = self.parse_record(record)
            if sale is None:
                invalid += 1
            else:
                parsed.append(sale)
        return tuple(parsed), invalid


def _string(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _integer(value: object) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
