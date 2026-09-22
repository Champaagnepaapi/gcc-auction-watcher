from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit

from v4_global_market_core import CommercialIdentity, FIXED_ASK
from v4_global_marketplace_discovery import MarketplaceListing


COURTYARD_MARKETPLACE_URL = "https://courtyard.io/marketplace"
COURTYARD_MAX_DETAIL_PAGES = 30
COURTYARD_MAX_SCROLL_ROUNDS = 8
COURTYARD_ASSET_RE = re.compile(
    r"https?://(?:www\.)?(?:marketplace\.)?courtyard\.io/asset/[0-9a-f]{64}",
    re.I,
)
_SUPPORTED_GRADERS = frozenset({"PSA", "CGC", "BGS", "SGC", "AGS", "ISA"})
_LISTING_PRICE_KEYS = (
    "listingPriceUsd",
    "listing_price_usd",
    "listPriceUsd",
    "list_price_usd",
    "askPriceUsd",
    "ask_price_usd",
)
_ACTIVE_STATUSES = frozenset({"active", "listed", "for sale", "for_sale", "on sale", "on_sale"})


def _text(value: object) -> str:
    return str(value or "").strip()


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _text(value).casefold()).strip()


def _asset_url(value: object) -> str:
    match = COURTYARD_ASSET_RE.search(_text(value))
    if not match:
        return ""
    parsed = urlsplit(match.group(0))
    return urlunsplit(("https", "marketplace.courtyard.io", parsed.path, "", ""))


def asset_urls_from_values(values: Iterable[object]) -> list[str]:
    output: list[str] = []
    for value in values:
        url = _asset_url(value)
        if url and url not in output:
            output.append(url)
    return output


def _json_objects(script_texts: Sequence[str]) -> Iterable[Mapping[str, Any]]:
    def walk(value: object):
        if isinstance(value, Mapping):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for raw in script_texts:
        text = _text(raw)
        if not text or text[:1] not in "[{":
            continue
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        yield from walk(parsed)


def _direct_value(row: Mapping[str, Any], names: Sequence[str]) -> object:
    lowered = {str(key).casefold(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.casefold())
        if value not in (None, ""):
            return value
    return None


def _parse_price(value: object) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if 0 < number < 1_000_000 else None
    text = _text(value).replace(",", "")
    match = re.search(r"(?:USD\s*)?\$?\s*(\d+(?:\.\d{1,2})?)", text, re.I)
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None
    return number if 0 < number < 1_000_000 else None


def _language(value: object) -> str:
    return {
        "english": "en",
        "en": "en",
        "japanese": "ja",
        "ja": "ja",
        "jp": "ja",
    }.get(_norm(value), "")


def _grade(value: object) -> str:
    text = _text(value)
    match = re.fullmatch(
        r"(?:GEM\s*MINT\s*)?(10|9\.5|9|8\.5|8|7\.5|7|6\.5|6|5\.5|5|4\.5|4|3\.5|3|2\.5|2|1\.5|1)(?:\s*GEM\s*MINT)?",
        text,
        re.I,
    )
    if not match:
        try:
            number = float(text)
        except (TypeError, ValueError):
            return ""
        if number < 1 or number > 10 or number * 2 != int(number * 2):
            return ""
        return str(int(number)) if number.is_integer() else f"{number:g}"
    number = float(match.group(1))
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _identity_from_mapping(row: Mapping[str, Any]) -> Optional[CommercialIdentity]:
    game = _direct_value(row, ("game", "category", "franchise", "brand"))
    if game is not None and "pokemon" not in _norm(game):
        return None
    name = _text(_direct_value(row, ("cardName", "card_name", "collectibleName", "collectible_name")))
    set_name = _text(_direct_value(row, ("setName", "set_name", "cardSet", "card_set")))
    number = _text(
        _direct_value(row, ("cardNumber", "card_number", "collectorNumber", "collector_number"))
    ).lstrip("#")
    language = _language(_direct_value(row, ("language", "cardLanguage", "card_language")))
    grader = _text(_direct_value(row, ("grader", "gradingCompany", "grading_company"))).upper()
    grade = _grade(_direct_value(row, ("grade", "cardGrade", "card_grade")))
    if not (name and set_name and number and language and grader in _SUPPORTED_GRADERS and grade):
        return None
    edition = _text(_direct_value(row, ("edition", "printing")))
    finish = _text(_direct_value(row, ("finish", "foil", "surface")))
    variant = _text(_direct_value(row, ("variant", "rarity")))
    identity = CommercialIdentity(
        name, set_name, number, language, grader, grade, edition, finish, variant
    )
    return (
        identity
        if identity.complete_for_exact_market and identity.opportunity_language
        else None
    )


def _nested_identity(row: Mapping[str, Any]) -> Optional[CommercialIdentity]:
    candidates: list[CommercialIdentity] = []
    direct = _identity_from_mapping(row)
    if direct is not None:
        candidates.append(direct)
    for key in ("card", "collectible", "asset", "item", "product", "metadata"):
        value = _direct_value(row, (key,))
        if isinstance(value, Mapping):
            candidate = _identity_from_mapping(value)
            if candidate is not None:
                candidates.append(candidate)
    by_key = {candidate.strict_key: candidate for candidate in candidates}
    return next(iter(by_key.values())) if len(by_key) == 1 else None


def _active_listing_price(row: Mapping[str, Any]) -> Optional[float]:
    for key in _LISTING_PRICE_KEYS:
        value = _direct_value(row, (key,))
        price = _parse_price(value)
        if price is not None:
            return price
    status = _norm(_direct_value(row, ("listingStatus", "listing_status", "status")))
    listed = _direct_value(row, ("isListed", "is_listed", "listed"))
    active = listed is True or status in _ACTIVE_STATUSES
    if not active:
        return None
    currency = _norm(_direct_value(row, ("currency", "currencyCode", "currency_code")))
    if currency and currency not in {"usd", "us dollar", "us dollars"}:
        return None
    return _parse_price(_direct_value(row, ("price", "amount")))


def _label_value(body: str, labels: Sequence[str]) -> str:
    for label in labels:
        match = re.search(
            rf"(?:^|\n)\s*{label}\s*:?[ \t]*(?:\n[ \t]*)?([^\n]+)",
            body,
            re.I,
        )
        if match:
            return match.group(1).strip()
    return ""


def _body_identity(body: str) -> Optional[CommercialIdentity]:
    if "pokemon" not in _norm(body):
        return None
    row = {
        "cardName": _label_value(body, (r"Card\s*Name", r"Name")),
        "setName": _label_value(body, (r"Set(?:\s*Name)?",)),
        "cardNumber": _label_value(
            body, (r"Card\s*(?:Number|No\.?|#)", r"Collector\s*Number")
        ),
        "language": _label_value(body, (r"Language",)),
        "grader": _label_value(body, (r"Grader", r"Grading\s*Company")),
        "grade": _label_value(body, (r"Grade",)),
        "edition": _label_value(body, (r"Edition",)),
        "finish": _label_value(body, (r"Finish", r"Foil")),
        "variant": _label_value(body, (r"Variant", r"Rarity")),
        "game": "Pokemon",
    }
    return _identity_from_mapping(row)


def _body_listing_price(body: str) -> Optional[float]:
    if re.search(r"\bNot\s+listed\b", body, re.I):
        return None
    for pattern in (
        r"\bBuy\s+Now\b\s*:?[ \t]*(?:\n[ \t]*)?\$\s*([\d,]+(?:\.\d{1,2})?)",
        r"\bListed\s+(?:for|at)\b\s*:?[ \t]*(?:\n[ \t]*)?\$\s*([\d,]+(?:\.\d{1,2})?)",
        r"\bListing\s+Price\b\s*:?[ \t]*(?:\n[ \t]*)?\$\s*([\d,]+(?:\.\d{1,2})?)",
    ):
        match = re.search(pattern, body, re.I)
        if match:
            return _parse_price(match.group(1))
    return None


def parse_courtyard_asset_page(
    *,
    source_url: str,
    body: str,
    script_texts: Sequence[str],
    observed_at: datetime,
) -> Optional[MarketplaceListing]:
    """Parse one public Courtyard asset page conservatively.

    Courtyard's own FMV/market value is deliberately ignored: this adapter is
    opportunity-only. A listing is emitted only when the page proves a live ask,
    exact card identity, language, grader and grade. Buyer funding costs remain
    unknown until a concrete payment route is proven, so all-in stays unavailable.
    """
    source = _asset_url(source_url)
    if not source or re.search(r"\bNot\s+listed\b", body, re.I):
        return None

    candidates: dict[tuple[str, float], tuple[CommercialIdentity, float]] = {}
    for row in _json_objects(script_texts):
        price = _active_listing_price(row)
        if price is None:
            continue
        identity = _nested_identity(row)
        if identity is None:
            continue
        candidates[(identity.strict_key, price)] = (identity, price)

    body_price = _body_listing_price(body)
    body_identity = _body_identity(body) if body_price is not None else None
    if body_price is not None and body_identity is not None:
        candidates[(body_identity.strict_key, body_price)] = (body_identity, body_price)

    identity_keys = {key[0] for key in candidates}
    prices = {key[1] for key in candidates}
    if len(identity_keys) != 1 or len(prices) != 1:
        return None
    identity, price = next(iter(candidates.values()))
    source_id = source.rsplit("/", 1)[-1]
    return MarketplaceListing(
        market="courtyard",
        source_id=source_id,
        source_url=source,
        title=f"{identity.name} {identity.number} {identity.grader} {identity.grade}",
        identity=identity,
        evidence_type=FIXED_ASK,
        price=price,
        currency="USD",
        observed_at=observed_at,
        identity_proven=True,
        buyer_fee_rate=None,
        buyer_fee_flat=0.0,
        logistics_cost=0.0,
        note=(
            "Courtyard vaulted marketplace fixed ASK; marketplace itself has no valuation authority; "
            "buyer funding/payment all-in intentionally unproven; physical redemption shipping/tax excluded from vault route"
        ),
    )
