from __future__ import annotations

from datetime import datetime, timezone
import re
import unicodedata
from typing import Any, Mapping, Optional
from v4_raw_consensus import MULTILINGUAL_DIMENSION_PATTERNS, parse_multilingual_commercial_dimensions

from v4_global_market_core import (
    ACTIVE_AUCTION,
    AUCTION_SNAPSHOT_LE5,
    FINISHED_UNPROVEN,
    FIXED_ASK,
    CommercialIdentity,
    PriceObservation,
)


def _parse_time(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _language(value: object) -> str:
    text = str(value or "").strip().casefold()
    return {"japanese": "ja", "english": "en", "french": "fr"}.get(text, text)


def _grader(code: object) -> str:
    return {"P": "PSA"}.get(str(code or "").strip().upper(), str(code or "").strip().upper())


def _grade(value: object) -> str:
    text = str(value or "").strip()
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _identity(row: Mapping[str, Any]) -> CommercialIdentity:
    attributes = " ".join(
        str(row.get(key) or "").strip()
        for key in ("attribute", "attribute2", "attribute3")
        if str(row.get(key) or "").strip()
    )
    set_name = str(row.get("variety") or row.get("variety_short") or "").strip()
    # Cardova repeats a catalog leaf under an explicit product/language/era
    # prefix. Remove only this syntax, and only when BOTH provider fields agree.
    wrapped = re.fullmatch(r"Pokemon TCG:\s*(Japanese|English)\s+(?:(?:XY|Sun & Moon|Sword & Shield|Scarlet & Violet|Black & White)\s+)?(.+)", set_name, re.I)
    if wrapped:
        short = str(row.get("variety_short") or "").strip()
        norm = lambda text: unicodedata.normalize("NFKC", text).casefold().strip()
        if _language(wrapped[1]) != _language(row.get("language")) or (short and norm(short) != norm(wrapped[2])):
            set_name = ""
        elif short:
            set_name = short
    dims = parse_multilingual_commercial_dimensions(attributes)
    edition = {"first_edition": "First Edition", "unlimited": "Unlimited"}.get(dims.get("edition"), "")
    finish = {"reverse": "Reverse", "holo": "Holo", "non_holo": "Non Holo"}.get(dims.get("finish"), "")
    # Preserve all remaining claims (FA, Shiny, Glossy, Green Back, etc.) for
    # downstream gates. An unrecognized attribute never disappears.
    variant = attributes
    if "__conflict__" not in dims.values():
        for dimension in ("edition", "finish"):
            for pattern in MULTILINGUAL_DIMENSION_PATTERNS[dimension].values():
                variant = re.sub(pattern, " ", variant, flags=re.I)
        variant = " ".join(variant.split())
    return CommercialIdentity(
        name=str(row.get("player") or "").strip(),
        set_name=set_name,
        number=str(row.get("card_number") or "").strip(),
        language=_language(row.get("language")),
        grader=_grader(row.get("authentication_company_code")),
        grade=_grade(row.get("grade")),
        finish=finish,
        edition=edition,
        variant=variant,
    )


def _identity_proven(identity: CommercialIdentity) -> bool:
    dims = parse_multilingual_commercial_dimensions(" ".join((identity.edition, identity.finish, identity.variant)))
    return identity.complete_for_exact_market and identity.language in {"en", "ja"} and "__conflict__" not in dims.values()


def parse_fixed_payload(
    payload: Mapping[str, Any],
    *,
    observed_at: datetime,
    buyer_fee_rate: float = 0.0,
    logistics_jpy: float = 0.0,
) -> list[PriceObservation]:
    observations: list[PriceObservation] = []
    rows = payload.get("list")
    if not isinstance(rows, list):
        return observations
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        if int(raw.get("listing_type") or 0) != 4:
            continue
        quantity = raw.get("set_quantity")
        if quantity not in {None, 1, "1"}:
            continue
        try:
            price = float(raw.get("asking_price") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        identity = _identity(raw)
        note = str(raw.get("remark") or "").strip()
        observations.append(
            PriceObservation(
                source="cardova",
                identity=identity,
                evidence_type=FIXED_ASK,
                price=price,
                currency="JPY",
                observed_at=observed_at,
                identity_proven=_identity_proven(identity),
                buyer_fee_rate=buyer_fee_rate,
                logistics_cost=logistics_jpy,
                note=note,
                source_id=str(raw.get("ulid") or "").strip(),
            )
        )
    return observations


def parse_auction_payload(
    payload: Mapping[str, Any],
    *,
    observed_at: datetime,
    buyer_premium_rate: Optional[float],
    logistics_jpy: float = 0.0,
    le5_minutes: float = 5.0,
) -> list[PriceObservation]:
    observations: list[PriceObservation] = []
    rows = payload.get("list")
    if not isinstance(rows, list):
        return observations
    now = observed_at.astimezone(timezone.utc)
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        if int(raw.get("listing_type") or 0) != 1:
            continue
        identity = _identity(raw)
        end_at = _parse_time(raw.get("end_date")) or _parse_time(raw.get("scheduled_end_date"))
        finished = int(raw.get("finished") or 0) == 1
        if finished:
            evidence_type = FINISHED_UNPROVEN
        elif end_at is not None:
            remaining = (end_at - now).total_seconds() / 60.0
            evidence_type = AUCTION_SNAPSHOT_LE5 if 0 <= remaining <= le5_minutes else ACTIVE_AUCTION
        else:
            evidence_type = ACTIVE_AUCTION
        raw_price = raw.get("bid_price") if raw.get("bid_price") is not None else raw.get("start_price")
        try:
            price = float(raw_price or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        note_parts = [str(raw.get("remark") or "").strip()]
        if raw.get("bid_price") is None:
            note_parts.append("no current bid; start price only")
        observations.append(
            PriceObservation(
                source="cardova",
                identity=identity,
                evidence_type=evidence_type,
                price=price,
                currency="JPY",
                observed_at=observed_at,
                identity_proven=_identity_proven(identity),
                end_at=end_at,
                buyer_fee_rate=buyer_premium_rate,
                logistics_cost=logistics_jpy,
                note="; ".join(part for part in note_parts if part),
                source_id=str(raw.get("ulid") or "").strip(),
            )
        )
    return observations
