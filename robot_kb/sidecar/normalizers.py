"""Evidence-conservative normalization for shadow market observations."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from robot_kb.domain import InclusionState, ObservationType, SourceKind
from robot_kb.repository import PriceComponent

from .models import (
    IdentityClaim,
    NormalizationBatch,
    NormalizedObservation,
    RawSourceRecord,
)


_UNEQUIVOCAL_SOLD_STATUSES = frozenset({"SOLD"})
_AMBIGUOUS_COMPLETION_STATUSES = frozenset(
    {"COMPLETED", "SUCCESSFUL", "ENDED", "ENDED_SOLD", "ENDED_UNSOLD"}
)
_BUNDLE_RE = re.compile(
    r"\b(?:bundle|lot|set of|collection|complete(?:\s+\w+){0,3}\s+set|"
    r"pair|duo|trio|menu|"
    r"sealed|booster|display|box|pack|case|mystery|oripa|break|spot|"
    r"multi(?:ple)?)\b",
    re.IGNORECASE,
)
_MENU_RE = re.compile(
    r"\b(?:(?:pick|choose|select)\s+(?:one|a|your)|choose\s+your|au\s+choix|"
    r"choisissez\s+un(?:e)?\s+carte)\b",
    re.IGNORECASE,
)
_MULTIPLE_NAMES_RE = re.compile(
    r"\b[A-Za-zÀ-ÿ][\wÀ-ÿ'-]*(?:\s+[A-Za-zÀ-ÿ][\wÀ-ÿ'-]*){0,2}\s*"
    r"(?:&|\+|\band\b|\bet\b|\bor\b|\bou\b)\s*"
    r"[A-Za-zÀ-ÿ][\wÀ-ÿ'-]*",
    re.IGNORECASE,
)
_SLASH_ALTERNATIVE_RE = re.compile(
    r"\b[A-Za-zÀ-ÿ][\wÀ-ÿ'-]*(?:\s+[A-Za-zÀ-ÿ][\wÀ-ÿ'-]*){0,2}"
    r"\s*/\s*[A-Za-zÀ-ÿ][\wÀ-ÿ'-]*\b",
    re.IGNORECASE,
)
_MULTIPLICITY_RE = re.compile(
    r"\b(?:(?:[2-9]|[1-9]\d+)\s*[x×]|[x×]\s*(?:[2-9]|[1-9]\d+)|"
    r"two|three|four|five|six|seven|eight|nine|ten|deux|trois|quatre|"
    r"cinq|six|sept|huit|neuf|dix)\b",
    re.IGNORECASE,
)
_PLURAL_CARD_RE = re.compile(r"\b(?:cards|cartes)\b", re.IGNORECASE)
_CARD_TYPE_VALUES = frozenset(
    {
        "CARD",
        "CARDS",
        "GRADED_CARD",
        "POKEMON_CARD",
        "SINGLE_CARD",
        "SLAB",
        "TRADING_CARD",
    }
)
_POKEMON_CATEGORY_VALUES = frozenset(
    {"POKEMON", "POKEMON_CARD", "POKEMON_CARDS"}
)
_COMPATIBLE_CATEGORY_VALUES = _POKEMON_CATEGORY_VALUES | frozenset(
    {"CARD", "CARDS", "TCG", "TRADING_CARD", "TRADING_CARDS"}
)
_CARDINALITY_FIELDS = (
    "quantity",
    "cardinality",
    "cardCount",
    "cardsCount",
    "numberOfCards",
    "itemCount",
    "itemsCount",
)
_NEGATIVE_SCOPE_FLAGS = (
    "bundle",
    "collection",
    "containsMultipleCards",
    "isBundle",
    "isCollection",
    "isLot",
    "isMultiItem",
    "isMultiple",
    "isSealed",
    "lot",
    "multiple",
    "sealed",
    "sealedProduct",
)
_NEGATIVE_SCOPE_TOKENS = frozenset(
    {
        "BOOSTER",
        "BOX",
        "BREAK",
        "BUNDLE",
        "CASE",
        "COLLECTION",
        "DISPLAY",
        "LOT",
        "MENU",
        "MULTI_CARD",
        "MULTIPLE",
        "MYSTERY",
        "ORIPA",
        "PACK",
        "SEALED",
        "SEALED_PRODUCT",
        "SET",
        "SPOT",
    }
)
_SUPPORTED_CURRENCIES = frozenset({"EUR", "USD", "CHF"})


def _nonempty(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _first(*values: Any) -> Any:
    for value in values:
        if _nonempty(value):
            return value.strip() if isinstance(value, str) else value
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _aware_timestamp(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.isoformat(timespec="microseconds")
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return text


def _minor_from_cents(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        decimal = Decimal(str(value))
    except InvalidOperation:
        return None
    if not decimal.is_finite() or decimal < 0 or decimal != decimal.to_integral_value():
        return None
    return int(decimal)


def _minor_from_major(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not decimal.is_finite() or decimal < 0:
        return None
    return int((decimal * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _money(
    payload: Mapping[str, Any],
    *,
    cents_fields: Sequence[str],
    major_fields: Sequence[str],
) -> Optional[int]:
    for field in cents_fields:
        if field in payload:
            value = _minor_from_cents(payload.get(field))
            if value is not None:
                return value
    for field in major_fields:
        if field in payload:
            value = _minor_from_major(payload.get(field))
            if value is not None:
                return value
    return None


def _contract_currency(
    containers: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
    *,
    default: str,
) -> tuple[Optional[str], bool]:
    explicit = []
    for container in containers:
        for field in fields:
            if field not in container:
                continue
            value = container.get(field)
            if not isinstance(value, str):
                return None, True
            normalized = value.strip().upper()
            if normalized not in _SUPPORTED_CURRENCIES:
                return None, True
            explicit.append(normalized)
    if len(set(explicit)) > 1:
        return None, True
    return (explicit[0] if explicit else default), False


def _claim(field_name: str, value: Any, source_kind: SourceKind) -> Optional[IdentityClaim]:
    if not _nonempty(value):
        return None
    return IdentityClaim(field_name, value, source_kind)


def _claims(values: Iterable[Optional[IdentityClaim]]) -> Tuple[IdentityClaim, ...]:
    return tuple(value for value in values if value is not None)


def _explicit_final_price(payload: Mapping[str, Any]) -> tuple[Optional[int], str]:
    """Only fields whose names explicitly assert a consummated sale."""

    field_groups = (
        (
            ("acceptedOfferPriceInCents",),
            ("acceptedOfferPrice",),
            "ACCEPTED_OFFER",
        ),
        (
            ("soldPriceInCents",),
            ("soldPrice",),
            "ITEM_PRICE",
        ),
    )
    for cents, major, component_type in field_groups:
        value = _money(payload, cents_fields=cents, major_fields=major)
        if value is not None:
            return value, component_type
    return None, "ITEM_PRICE"


def _quantity(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 and value.is_integer() else None
    if isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        return int(value.strip())
    return None


def _structured_cardinality(
    payload: Mapping[str, Any],
    item: Mapping[str, Any],
    collectible: Mapping[str, Any],
) -> tuple[Optional[int], bool, bool, bool]:
    """Return value, proof-of-one, explicit non-one, and field absence."""

    values = []
    field_present = False
    for container, fields in (
        (payload, _CARDINALITY_FIELDS),
        (item, _CARDINALITY_FIELDS),
        (
            collectible,
            ("cardinality", "cardCount", "cardsCount", "numberOfCards"),
        ),
    ):
        for field in fields:
            if field not in container:
                continue
            field_present = True
            normalized = _quantity(container.get(field))
            if normalized is None:
                return None, False, False, False
            values.append(normalized)
    if not field_present:
        return None, False, False, True
    if len(set(values)) != 1:
        return None, False, bool(any(value != 1 for value in values)), False
    cardinality = values[0]
    return cardinality, cardinality == 1, cardinality != 1, False


def _scope_token(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    return re.sub(r"[^A-Z0-9]+", "_", value.strip().upper()).strip("_")


def _is_negative_scope_token(token: str) -> bool:
    return any(
        token == negative
        or token.startswith(f"{negative}_")
        or token.endswith(f"_{negative}")
        for negative in _NEGATIVE_SCOPE_TOKENS
    )


def _structured_type_is_individual_card(
    payload: Mapping[str, Any],
    item: Mapping[str, Any],
    collectible: Mapping[str, Any],
) -> tuple[bool, bool]:
    type_values = []
    for container, fields in (
        (payload, ("itemType", "productType")),
        (item, ("type", "itemType", "productType")),
        (collectible, ("type", "itemType", "productType")),
    ):
        for field in fields:
            if field not in container:
                continue
            token = _scope_token(container.get(field))
            if token is None:
                return False, False
            type_values.append(token)
    if not type_values:
        return False, False
    type_blocked = any(_is_negative_scope_token(token) for token in type_values)
    type_compatible = bool(
        not type_blocked
        and all(token in _CARD_TYPE_VALUES for token in type_values)
    )

    category_values = []
    for container in (payload, item, collectible):
        if "category" not in container:
            continue
        token = _scope_token(container.get("category"))
        if token is None:
            return False, type_blocked
        category_values.append(token)
    category_compatible = bool(
        category_values
        and any(token in _POKEMON_CATEGORY_VALUES for token in category_values)
        and all(token in _COMPATIBLE_CATEGORY_VALUES for token in category_values)
    )
    return type_compatible and category_compatible, type_blocked


def _structured_scope_is_negative(
    payload: Mapping[str, Any],
    item: Mapping[str, Any],
    collectible: Mapping[str, Any],
) -> bool:
    false_values = (False, 0, "", "0", "false", "no", "none", None)
    for container in (payload, item, collectible):
        if "isSingleCard" in container:
            value = container.get("isSingleCard")
            normalized = value.strip().casefold() if isinstance(value, str) else value
            if normalized not in (True, 1, "1", "true", "yes"):
                return True
        for field in _NEGATIVE_SCOPE_FLAGS:
            if field not in container:
                continue
            value = container.get(field)
            normalized = value.strip().casefold() if isinstance(value, str) else value
            if normalized not in false_values:
                return True
        for field in (
            "format",
            "itemScope",
            "listingScope",
            "listingType",
            "productFormat",
            "productKind",
            "scope",
        ):
            if field not in container:
                continue
            token = _scope_token(container.get(field))
            if token is not None and _is_negative_scope_token(token):
                return True
    return False


def _gcc_single_collectible_object(
    payload: Mapping[str, Any],
    item: Mapping[str, Any],
    collectible: Mapping[str, Any],
    source_native_record_id: str,
) -> bool:
    """Recognize GCC's singular graded-card inventory object contract.

    This is deliberately a conjunction of independent structured fields from
    the retained GCC payloads. A title, card metadata, or certificate alone is
    never sufficient.
    """

    def scalar_text(value: Any) -> Optional[str]:
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip()

    listing_id = scalar_text(payload.get("id"))
    item_id = scalar_text(item.get("id"))
    serial_number = scalar_text(item.get("serialNumber"))
    grader = scalar_text(item.get("gradingCompany"))
    grade = scalar_text(item.get("grade"))
    recto_image = scalar_text(item.get("rectoImageKey"))
    verso_image = scalar_text(item.get("versoImageKey"))
    singular_objects = bool(
        isinstance(payload.get("item"), Mapping)
        and isinstance(item.get("collectible"), Mapping)
    )
    competing_collection_shape = any(
        field in container
        for container, fields in (
            (payload, ("items", "collectibles", "components")),
            (item, ("items", "collectibles", "components")),
            (collectible, ("items", "collectibles", "components")),
        )
        for field in fields
    )
    return bool(
        singular_objects
        and not competing_collection_shape
        and listing_id == source_native_record_id
        and item_id is not None
        and item_id != listing_id
        and serial_number is not None
        and re.fullmatch(r"\d{8,9}", serial_number)
        and grader is not None
        and grade is not None
        and recto_image is not None
        and verso_image is not None
        and recto_image != verso_image
    )


def _single_card_scope(
    payload: Mapping[str, Any],
    item: Mapping[str, Any],
    collectible: Mapping[str, Any],
    title: Any,
    source_native_record_id: str,
) -> tuple[str, bool, Optional[int], Optional[str]]:
    """Require structured one-card proof; free text can only veto exactness."""

    text_values = (
        title,
        payload.get("body"),
        payload.get("description"),
        payload.get("listingText"),
        item.get("body"),
        item.get("description"),
        item.get("descriptionEn"),
        item.get("descriptionFr"),
        item.get("additionalInformation"),
    )
    evidence_text = "\n".join(
        str(value) for value in text_values if _nonempty(value)
    )
    (
        quantity,
        cardinality_is_one,
        explicit_non_one,
        generic_cardinality_absent,
    ) = _structured_cardinality(payload, item, collectible)
    type_is_card, type_is_blocked = _structured_type_is_individual_card(
        payload, item, collectible
    )
    negative_structured = bool(
        explicit_non_one
        or type_is_blocked
        or _structured_scope_is_negative(payload, item, collectible)
    )
    negative_text = bool(
        _BUNDLE_RE.search(evidence_text)
        or _MENU_RE.search(evidence_text)
        or _MULTIPLE_NAMES_RE.search(evidence_text)
        or _SLASH_ALTERNATIVE_RE.search(evidence_text)
        or _MULTIPLICITY_RE.search(evidence_text)
        or _PLURAL_CARD_RE.search(evidence_text)
    )
    if negative_structured or negative_text:
        return "BUNDLE_OR_MULTI", False, quantity, None
    gcc_single_collectible = bool(
        generic_cardinality_absent
        and type_is_card
        and _gcc_single_collectible_object(
            payload, item, collectible, source_native_record_id
        )
    )
    positive = bool(
        (cardinality_is_one or gcc_single_collectible)
        and type_is_card
        and isinstance(title, str)
        and bool(title.strip())
    )
    if positive:
        method = (
            "GENERIC_STRUCTURED_CARDINALITY"
            if cardinality_is_one
            else "GCC_SINGLE_COLLECTIBLE_OBJECT"
        )
        return "SINGLE_CARD", True, quantity, method
    return "AMBIGUOUS_ITEM_SCOPE", False, quantity, None


def _timestamp_value(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(candidate)


def normalize_gcc(record: RawSourceRecord) -> NormalizationBatch:
    """Normalize one GCC row without inferring a sale or print microvariant."""

    payload = record.payload
    item = _mapping(payload.get("item"))
    collectible = _mapping(item.get("collectible"))
    seller = _mapping(payload.get("seller"))

    status = str(_first(payload.get("status"), "UNKNOWN")).strip().upper()
    selling_type = str(_first(payload.get("sellingType"), "UNKNOWN")).strip().upper()
    if "AUCTION" in selling_type:
        mode = "AUCTION"
    elif selling_type in {"FIXED", "FIXED_PRICE", "BUY_NOW"}:
        mode = "FIXED_PRICE"
    else:
        mode = "UNKNOWN"

    title = _first(item.get("title"), payload.get("title"))
    item_scope, explicit_single, quantity, cardinality_evidence_method = (
        _single_card_scope(
            payload,
            item,
            collectible,
            title,
            record.source_native_record_id,
        )
    )

    language = _first(collectible.get("language"), item.get("language"))
    set_name = _first(collectible.get("set"), collectible.get("extension"))
    collector_number = _first(
        collectible.get("reference"), collectible.get("collectorNumber")
    )
    edition = _first(collectible.get("edition"), item.get("edition"))
    finish = _first(collectible.get("finish"), item.get("finish"))
    print_variant = _first(
        collectible.get("printVariant"), collectible.get("variant"), item.get("variant")
    )
    stamp = _first(collectible.get("stamp"), item.get("stamp"))
    shadow_treatment = _first(
        collectible.get("shadowTreatment"), item.get("shadowTreatment")
    )
    auction_end = _first(payload.get("endTime"), payload.get("auctionEndTime"))
    bid_count = _first(payload.get("bidsNumber"), payload.get("bidCount"))
    seller_id = _first(
        payload.get("sellerId"), seller.get("id"), seller.get("username")
    )
    certification_number = _first(
        item.get("serialNumber"),
        item.get("certificationNumber"),
        item.get("certificateNumber"),
        collectible.get("certificationNumber"),
    )
    listing_url = _first(
        payload.get("url"),
        payload.get("listingUrl"),
        f"https://gradedcardcenter.com/item/{record.source_native_record_id}",
    )
    claims = _claims(
        (
            _claim("listing_id", record.source_native_record_id, SourceKind.LISTING),
            _claim("listing_url", listing_url, SourceKind.LISTING),
            _claim("listing_status", status, SourceKind.LISTING),
            _claim("selling_mode", mode, SourceKind.LISTING),
            _claim("card_title_raw", title, SourceKind.LISTING),
            _claim("grader", item.get("gradingCompany"), SourceKind.LISTING),
            _claim("grade", item.get("grade"), SourceKind.LISTING),
            _claim("language", language, SourceKind.LISTING),
            _claim("set", set_name, SourceKind.LISTING),
            _claim("collector_number", collector_number, SourceKind.LISTING),
            _claim("edition", edition, SourceKind.LISTING),
            _claim("finish", finish, SourceKind.LISTING),
            _claim("print_variant", print_variant, SourceKind.LISTING),
            _claim("stamp", stamp, SourceKind.LISTING),
            _claim("shadow_treatment", shadow_treatment, SourceKind.LISTING),
            _claim("certification_number", certification_number, SourceKind.LISTING),
            _claim("auction_end_at", auction_end, SourceKind.LISTING),
            _claim("bid_count", bid_count, SourceKind.LISTING),
            _claim("seller_identifier", seller_id, SourceKind.LISTING),
            _claim("item_scope", item_scope, SourceKind.LISTING),
            _claim(
                "cardinality_evidence_method",
                cardinality_evidence_method,
                SourceKind.LISTING,
            ),
        )
    )

    dimension_values = {
        "language": language,
        "set": set_name,
        "collector_number": collector_number,
        "edition": edition,
        "finish": finish,
        "print_variant": print_variant,
        "stamp": stamp,
        "shadow_treatment": shadow_treatment,
    }
    unresolved = [
        field_name
        for field_name, value in dimension_values.items()
        if not _nonempty(value)
    ]
    if not explicit_single:
        unresolved.append("single_card_scope")

    observed_at = _aware_timestamp(record.retrieved_at)
    if observed_at is None:
        raise ValueError("GCC retrieved_at must be a timezone-aware timestamp")
    source_updated_raw = _first(payload.get("updatedAt"), payload.get("sourceUpdatedAt"))
    source_updated_at = _aware_timestamp(
        source_updated_raw
    )
    listing_started_at = _aware_timestamp(
        _first(payload.get("listedAt"), payload.get("startTime"), payload.get("createdAt"))
    )
    sale_occurred_at = _aware_timestamp(
        _first(payload.get("soldAt"), payload.get("saleOccurredAt"))
    )
    final_price_minor, final_component_type = _explicit_final_price(payload)
    currency, invalid_currency = _contract_currency(
        (payload, item),
        ("currency", "currencyCode"),
        default="EUR",
    )
    chronology_valid = bool(
        sale_occurred_at is not None
        and _timestamp_value(sale_occurred_at) <= _timestamp_value(observed_at)
        and (
            source_updated_raw is None
            or (
                source_updated_at is not None
                and _timestamp_value(sale_occurred_at)
                <= _timestamp_value(source_updated_at)
                <= _timestamp_value(observed_at)
            )
        )
    )
    genuine_sale = bool(
        status in _UNEQUIVOCAL_SOLD_STATUSES
        and final_price_minor is not None
        and currency is not None
        and chronology_valid
    )
    sale_candidate = bool(
        status in _UNEQUIVOCAL_SOLD_STATUSES
        or status in _AMBIGUOUS_COMPLETION_STATUSES
        or any(
            _nonempty(payload.get(field))
            for field in (
                "soldAt",
                "saleOccurredAt",
                "completedAt",
                "soldPriceInCents",
                "soldPrice",
                "finalPriceInCents",
                "finalPrice",
            )
        )
    )
    sale_candidates_rejected = int(sale_candidate and not genuine_sale)
    ambiguous_sale_records = int(
        sale_candidate and status in _AMBIGUOUS_COMPLETION_STATUSES
    )

    shipping_minor = _money(
        payload,
        cents_fields=("shippingInCents", "shippingPriceInCents"),
        major_fields=("shipping", "shippingPrice"),
    )
    current_price_minor = _money(
        payload,
        cents_fields=("priceInCents", "currentPriceInCents"),
        major_fields=("price", "currentPrice"),
    )
    money_fields = (
        "priceInCents",
        "currentPriceInCents",
        "price",
        "currentPrice",
        "shippingInCents",
        "shippingPriceInCents",
        "shipping",
        "shippingPrice",
        "soldPriceInCents",
        "soldPrice",
        "acceptedOfferPriceInCents",
        "acceptedOfferPrice",
    )
    monetary_facts_rejected = int(
        invalid_currency and any(field in payload for field in money_fields)
    )
    prices = []
    if genuine_sale:
        prices.append(
            PriceComponent(
                final_component_type,
                final_price_minor,
                currency,
                inclusion_state=InclusionState.UNKNOWN,
            )
        )
    else:
        if current_price_minor is not None and currency is not None:
            prices.append(
                PriceComponent(
                    "ITEM_PRICE",
                    current_price_minor,
                    currency,
                    inclusion_state=InclusionState.UNKNOWN,
                )
            )
    if shipping_minor is not None and currency is not None:
        prices.append(
            PriceComponent(
                "SHIPPING",
                shipping_minor,
                currency,
                inclusion_state=InclusionState.UNKNOWN,
            )
        )

    if genuine_sale:
        observation_type = ObservationType.SALE_TRANSACTION
        fact = {
            "listing_started_at": listing_started_at,
            "sale_occurred_at": sale_occurred_at,
            "transaction_status": "COMPLETED",
        }
        event_at = sale_occurred_at
        event_time_precision = "EXACT"
    else:
        observation_type = ObservationType.LISTING_SNAPSHOT
        fact = {
            "listing_started_at": listing_started_at,
            "snapshot_status": f"{status}:{mode}",
            "quantity": quantity,
        }
        event_at = None
        event_time_precision = "UNKNOWN"

    observations = (
        NormalizedObservation(
            observation_type=observation_type,
            source_native_record_id=record.source_native_record_id,
            observed_at=observed_at,
            fact=fact,
            source_updated_at=source_updated_at,
            event_at=event_at,
            event_time_precision=event_time_precision,
            prices=tuple(prices),
            identity_subject_type="GCC_LISTING_OBSERVATION",
            identity_subject_label=f"GCC listing {record.source_native_record_id}",
            identity_namespace="GCC_LISTING_ID",
            identity_identifier_value=record.source_native_record_id,
            unresolved_dimensions=tuple(sorted(set(unresolved))),
            claims=claims,
            exact_identity_eligible=explicit_single,
            genuine_sale_evidence=genuine_sale,
        ),
    )
    return NormalizationBatch(
        observations,
        sale_candidates_rejected=sale_candidates_rejected,
        ambiguous_sale_records=ambiguous_sale_records,
        monetary_facts_rejected=monetary_facts_rejected,
    )


_CARDMARKET_METRICS = {
    "avg": ("AVG", None),
    "low": ("LOW", None),
    "trend": ("TREND", None),
    "avg1": ("AVG_1D", 1),
    "avg7": ("AVG_7D", 7),
    "avg30": ("AVG_30D", 30),
}
_TCGPLAYER_METRICS = {
    "low": "LOW",
    "lowprice": "LOW",
    "mid": "MID",
    "midprice": "MID",
    "high": "HIGH",
    "highprice": "HIGH",
    "market": "MARKET",
    "marketprice": "MARKET",
    "directlow": "DIRECT_LOW",
    "directlowprice": "DIRECT_LOW",
}
_METADATA_KEYS = frozenset(
    {"unit", "currency", "updated", "updatedat", "language", "condition"}
)


def _clean_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _numeric_leaves(
    payload: Mapping[str, Any], path: Tuple[str, ...] = ()
) -> Iterable[tuple[Tuple[str, ...], Any]]:
    for key, value in payload.items():
        token = str(key)
        if _clean_token(token) in _METADATA_KEYS:
            continue
        current_path = path + (token,)
        if isinstance(value, Mapping):
            yield from _numeric_leaves(value, current_path)
        elif not isinstance(value, bool) and isinstance(value, (int, float, Decimal, str)):
            try:
                candidate = Decimal(str(value))
            except InvalidOperation:
                continue
            if candidate.is_finite():
                yield current_path, value


def _metric_definition(
    market: str, path: Tuple[str, ...]
) -> Optional[tuple[str, str, Optional[int]]]:
    if not path:
        return None
    leaf = _clean_token(path[-1])
    parent_segments = [_clean_token(part) for part in path[:-1] if _clean_token(part)]
    if market == "cardmarket":
        raw_leaf = str(path[-1])
        base_raw, separator, suffix = raw_leaf.partition("-")
        definition = _CARDMARKET_METRICS.get(_clean_token(base_raw).replace("_", ""))
        if definition is None:
            return None
        metric_label, window_days = definition
        segment_parts = parent_segments + ([_clean_token(suffix)] if separator else [])
    else:
        compact_leaf = leaf.replace("_", "")
        metric_label = _TCGPLAYER_METRICS.get(compact_leaf)
        if metric_label is None:
            return None
        window_days = None
        segment_parts = parent_segments
    segment = ".".join(part for part in segment_parts if part) or "generic"
    metric_name = f"{market.upper()}_{metric_label}:{segment.upper()}"
    return metric_name, segment, window_days


def _provider_timestamp(provider_payload: Mapping[str, Any]) -> Optional[str]:
    return _aware_timestamp(
        _first(
            provider_payload.get("updatedAt"),
            provider_payload.get("updated"),
            provider_payload.get("sourceUpdatedAt"),
        )
    )


def _provider_currency(
    provider_payload: Mapping[str, Any], market: str
) -> tuple[Optional[str], bool]:
    # These defaults are limited to the exact provider contracts represented by
    # TCGdex's Cardmarket (EUR) and TCGplayer (USD) pricing containers.
    return _contract_currency(
        (provider_payload,),
        ("unit", "currency"),
        default="EUR" if market == "cardmarket" else "USD",
    )


def _tcgdex_claims(
    payload: Mapping[str, Any], market: str, segment: str
) -> Tuple[IdentityClaim, ...]:
    set_payload = _mapping(payload.get("set"))
    values = [
        _claim("tcgdex_card_id", payload.get("id"), SourceKind.PROVIDER),
        _claim("card_title_raw", payload.get("name"), SourceKind.PROVIDER),
        _claim("collector_number", payload.get("localId"), SourceKind.PROVIDER),
        _claim("set_id", set_payload.get("id"), SourceKind.PROVIDER),
        _claim("set", set_payload.get("name"), SourceKind.PROVIDER),
        _claim("language", payload.get("language"), SourceKind.PROVIDER),
        _claim("upstream_market", market, SourceKind.PROVIDER),
    ]
    if segment != "generic":
        # A pricing-bucket label is retained as evidence but never promoted to
        # finish/edition/print-variant truth.
        values.append(_claim("market_segment", segment, SourceKind.PROVIDER))
    return _claims(values)


def normalize_tcgdex(record: RawSourceRecord) -> NormalizationBatch:
    """Flatten embedded Cardmarket/TCGplayer prices into provider metrics."""

    payload = record.payload
    pricing = payload.get("pricing")
    if not isinstance(pricing, Mapping):
        return NormalizationBatch((), rejected_record=True)
    card_id = payload.get("id")
    if not isinstance(card_id, str) or not card_id.strip():
        return NormalizationBatch((), rejected_record=True)
    observed_at = _aware_timestamp(record.retrieved_at)
    if observed_at is None:
        raise ValueError("TCGdex retrieved_at must be a timezone-aware timestamp")

    normalized = []
    metric_alias_conflicts = 0
    monetary_facts_rejected = 0
    for market, market_name in (
        ("cardmarket", "Cardmarket"),
        ("tcgplayer", "TCGplayer"),
    ):
        provider_payload = pricing.get(market)
        if not isinstance(provider_payload, Mapping):
            continue
        currency, invalid_currency = _provider_currency(provider_payload, market)
        source_updated_at = _provider_timestamp(provider_payload)
        candidates: dict[
            tuple[str, str, Optional[int]], list[tuple[Tuple[str, ...], int]]
        ] = {}
        for path, value in _numeric_leaves(provider_payload):
            definition = _metric_definition(market, path)
            if definition is None:
                continue
            metric_name, segment, window_days = definition
            metric_value_minor = _minor_from_major(value)
            if metric_value_minor is None:
                continue
            candidates.setdefault(
                (metric_name, segment, window_days), []
            ).append((path, metric_value_minor))

        if invalid_currency:
            monetary_facts_rejected += len(candidates)
            continue

        for (metric_name, segment, window_days), aliases in sorted(
            candidates.items()
        ):
            distinct_values = {value for _, value in aliases}
            if len(distinct_values) != 1:
                metric_alias_conflicts += 1
                continue
            path, metric_value_minor = min(
                aliases, key=lambda candidate: "/".join(candidate[0]).casefold()
            )
            window_started_at = None
            window_ended_at = None
            if window_days is not None and source_updated_at is not None:
                candidate = (
                    source_updated_at[:-1] + "+00:00"
                    if source_updated_at.endswith("Z")
                    else source_updated_at
                )
                updated = datetime.fromisoformat(candidate)
                window_started_at = (updated - timedelta(days=window_days)).isoformat(
                    timespec="microseconds"
                )
                window_ended_at = source_updated_at

            identifier_value = f"{card_id.strip()}:{market}:{segment}"
            normalized.append(
                NormalizedObservation(
                    observation_type=ObservationType.PROVIDER_METRIC_OBSERVATION,
                    source_native_record_id=(
                        f"{card_id.strip()}:{market}:{'/'.join(path)}"
                    ),
                    observed_at=observed_at,
                    source_updated_at=source_updated_at,
                    event_at=source_updated_at,
                    event_time_precision=(
                        "EXACT" if source_updated_at is not None else "UNKNOWN"
                    ),
                    fact={
                        "metric_name": metric_name,
                        "metric_value_minor": metric_value_minor,
                        "currency": currency,
                        "window_started_at": window_started_at,
                        "window_ended_at": window_ended_at,
                        "sample_size": None,
                    },
                    upstream_market_code=market,
                    upstream_market_name=market_name,
                    identity_subject_type="TCGDEX_MARKET_SEGMENT",
                    identity_subject_label=(
                        f"TCGdex {card_id.strip()} {market} {segment}"
                    ),
                    identity_namespace="TCGDEX_MARKET_SEGMENT",
                    identity_identifier_value=identifier_value,
                    unresolved_dimensions=(
                        "edition",
                        "exact_print_variant",
                        "finish",
                        "shadow_treatment",
                        "stamp",
                    ),
                    claims=_tcgdex_claims(payload, market, segment),
                )
            )
    return NormalizationBatch(
        tuple(normalized),
        metric_alias_conflicts=metric_alias_conflicts,
        monetary_facts_rejected=monetary_facts_rejected,
    )
