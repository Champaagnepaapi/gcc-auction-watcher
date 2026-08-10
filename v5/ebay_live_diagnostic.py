"""Diagnostic eBay Production V5 enrichi, agrege et sans persistance.

Le module utilise exclusivement OAuth Application, Commerce Taxonomy et Buy
Browse en lecture seule. Les payloads, identifiants et images restent en
memoire; seul ``render_live_summary`` produit une sortie, exclusivement sous
forme de compteurs et de statuts techniques agreges.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote, urlparse

import requests

from .ebay import (
    OAUTH_SCOPE,
    PRODUCTION_BROWSE_BASE,
    PRODUCTION_IDENTITY_BASE,
    CARD_NAME_SOURCE_LOCALIZED,
    CARD_NAME_SOURCE_SET_NUMBER,
    CARD_NAME_SOURCE_TITLE,
    EbayApiError,
    NullSetNumberCardNameResolver,
    SetNumberCardNameResolver,
    parse_ebay_item,
    resolve_card_identity,
)
from .image_detection import (
    BACK_IMAGE_CANDIDATE,
    BACK_IMAGE_CONFIRMED,
    BACK_IMAGE_UNKNOWN,
    LocalPokemonBackDetector,
)
from .models import CardIdentity, CostInputs, GradeImagePair
from .scanner import MARKET_DATA_UNAVAILABLE, RawCardScanner, SafeguardConfig, ScanRequest
from .valuation import MarketDataUnavailable


OAUTH_URL = f"{PRODUCTION_IDENTITY_BASE}/token"
SEARCH_URL = f"{PRODUCTION_BROWSE_BASE}/item_summary/search"
TAXONOMY_BASE = "https://api.ebay.com/commerce/taxonomy/v1"
DEFAULT_CATEGORY_TREE_URL = f"{TAXONOMY_BASE}/get_default_category_tree_id"
CATEGORY_SUGGESTIONS_URL = f"{TAXONOMY_BASE}/category_tree/{{tree_id}}/get_category_suggestions"
RAW_CONDITION_ID = "4000"
RESULT_LIMIT = 20
MAX_VISUAL_IMAGES_PER_ITEM = 6
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MARKETPLACES = ("EBAY_US", "EBAY_CH")
CATEGORY_QUERY = "Pokémon CCG Individual Cards"


class _NeverGradeProvider:
    def assess(self, image_pair: object, identity: object) -> object:
        raise AssertionError("Le cheap filter ne doit jamais appeler CardGrader")


class _MissingMarketDataProvider:
    def values_for(self, identity: object) -> object:
        raise MarketDataUnavailable("MARKET_VALUES_MISSING")


@dataclass(frozen=True)
class OAuthAggregate:
    http_status: str
    token_obtained: bool
    expires_in: Optional[int]


@dataclass
class MarketplaceAggregate:
    marketplace_id: str
    taxonomy_http_status: str = "NOT_CALLED"
    taxonomy_ok: bool = False
    taxonomy_error_type: Optional[str] = None
    taxonomy_error_code: Optional[str] = None
    resolved_category_id: Optional[str] = field(default=None, repr=False)
    http_status: str = "NOT_CALLED"
    error_type: Optional[str] = None
    error_code: Optional[str] = None
    total_announced: int = 0
    results_received: int = 0
    get_item_calls: int = 0
    get_item_success: int = 0
    get_item_failure: int = 0
    empty_reason: str = "autre"


@dataclass
class IdentityAggregate:
    before_usable: int = 0
    before_insufficient: int = 0
    after_usable: int = 0
    after_insufficient: int = 0
    localized_aspects_available: int = 0
    product_data_available: int = 0
    game: int = 0
    card_name: int = 0
    set_name: int = 0
    card_number: int = 0
    year: int = 0
    language: int = 0
    variant: int = 0
    rarity: int = 0
    finish: int = 0
    edition: int = 0
    illustrator: int = 0
    missing_game: int = 0
    missing_card_name: int = 0
    missing_set: int = 0
    missing_card_number: int = 0
    missing_language: int = 0
    ambiguous: int = 0
    resolved_localized_aspects: int = 0
    resolved_title_fallback: int = 0
    resolved_set_number: int = 0
    score_total: int = 0


@dataclass
class ImageAggregate:
    search_primary: int = 0
    search_additional: int = 0
    get_item_primary: int = 0
    get_item_additional: int = 0
    total_images: int = 0
    back_confirmed: int = 0
    back_candidate: int = 0
    back_unknown: int = 0


@dataclass
class CheapFilterAggregate:
    passed: int = 0
    reject_identity: int = 0
    reject_images: int = 0
    market_values_missing: int = 0


@dataclass(frozen=True)
class LiveDiagnosticSummary:
    oauth: OAuthAggregate
    marketplaces: Tuple[MarketplaceAggregate, ...]
    duplicate_items: int = 0
    unique_items: int = 0
    same_category_id: bool = False
    identity: IdentityAggregate = field(default_factory=IdentityAggregate)
    images: ImageAggregate = field(default_factory=ImageAggregate)
    cheap_filter: CheapFilterAggregate = field(default_factory=CheapFilterAggregate)


@dataclass
class _DiscoveryRecord:
    marketplace_id: str
    summary: Mapping[str, object] = field(repr=False)
    item_id: Optional[str] = field(default=None, repr=False)
    detail: Mapping[str, object] = field(default_factory=dict, repr=False)
    enriched: Mapping[str, object] = field(default_factory=dict, repr=False)
    get_item_success: bool = False


class EbayLiveDiagnostic:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        session: Optional[requests.Session] = None,
        timeout_seconds: float = 20.0,
        set_number_resolver: Optional[SetNumberCardNameResolver] = None,
        back_detector: Optional[LocalPokemonBackDetector] = None,
        image_fetcher: Optional[Callable[[str], Optional[bytes]]] = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session or requests.Session()
        self._timeout_seconds = timeout_seconds
        self._set_number_resolver = (
            set_number_resolver or NullSetNumberCardNameResolver()
        )
        self._back_detector = back_detector or LocalPokemonBackDetector()
        self._image_fetcher = image_fetcher or self._fetch_image_in_memory

    def run(self) -> LiveDiagnosticSummary:
        token, oauth = self._application_token()
        if token is None:
            return LiveDiagnosticSummary(
                oauth=oauth,
                marketplaces=tuple(
                    MarketplaceAggregate(marketplace_id=value) for value in MARKETPLACES
                ),
            )

        aggregates: Dict[str, MarketplaceAggregate] = {}
        records: List[_DiscoveryRecord] = []
        for marketplace_id in MARKETPLACES:
            aggregate, discovered = self._discover_marketplace(marketplace_id, token)
            aggregates[marketplace_id] = aggregate
            records.extend(discovered)

        duplicates, unique_items = self._enrich_unique_items(records, aggregates, token)
        identity = IdentityAggregate()
        images = ImageAggregate()
        cheap_filter = CheapFilterAggregate()
        for record in records:
            self._aggregate_record(record, identity, images, cheap_filter)

        category_ids = [
            aggregate.resolved_category_id for aggregate in aggregates.values()
        ]
        same_category_id = bool(
            len(category_ids) == len(MARKETPLACES)
            and all(category_ids)
            and len(set(category_ids)) == 1
        )
        return LiveDiagnosticSummary(
            oauth=oauth,
            marketplaces=tuple(aggregates[value] for value in MARKETPLACES),
            duplicate_items=duplicates,
            unique_items=unique_items,
            same_category_id=same_category_id,
            identity=identity,
            images=images,
            cheap_filter=cheap_filter,
        )

    def _application_token(self) -> Tuple[Optional[str], OAuthAggregate]:
        if not self._client_id or not self._client_secret:
            return None, OAuthAggregate("NOT_CALLED", False, None)
        try:
            response = self._session.post(
                OAUTH_URL,
                auth=(self._client_id, self._client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials", "scope": OAUTH_SCOPE},
                timeout=self._timeout_seconds,
            )
        except requests.RequestException:
            return None, OAuthAggregate("REQUEST_ERROR", False, None)

        status = str(response.status_code)
        payload = _safe_json(response)
        if response.status_code != 200:
            return None, OAuthAggregate(status, False, None)
        token = payload.get("access_token") if isinstance(payload, Mapping) else None
        expires_in = _safe_nonnegative_int(
            payload.get("expires_in") if isinstance(payload, Mapping) else None
        )
        if not isinstance(token, str) or not token:
            return None, OAuthAggregate(status, False, expires_in)
        return token, OAuthAggregate(status, True, expires_in)

    @staticmethod
    def _headers(token: str, marketplace_id: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
        }

    def _resolve_category(
        self, marketplace_id: str, token: str, aggregate: MarketplaceAggregate
    ) -> Optional[str]:
        headers = self._headers(token, marketplace_id)
        try:
            tree_response = self._session.get(
                DEFAULT_CATEGORY_TREE_URL,
                headers=headers,
                params={"marketplace_id": marketplace_id},
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            aggregate.taxonomy_http_status = "REQUEST_ERROR"
            aggregate.taxonomy_error_type = _technical_identifier(type(exc).__name__)
            return None

        tree_payload = _safe_json(tree_response)
        aggregate.taxonomy_http_status = str(tree_response.status_code)
        if tree_response.status_code != 200 or not isinstance(tree_payload, Mapping):
            aggregate.taxonomy_error_type, aggregate.taxonomy_error_code = _error_metadata(
                tree_payload
            )
            return None
        tree_id = tree_payload.get("categoryTreeId")
        if not isinstance(tree_id, str) or not tree_id:
            aggregate.taxonomy_error_type = "CATEGORY_TREE_ID_MISSING"
            return None

        url = CATEGORY_SUGGESTIONS_URL.format(tree_id=quote(tree_id, safe=""))
        try:
            suggestion_response = self._session.get(
                url,
                headers=headers,
                params={"q": CATEGORY_QUERY},
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            aggregate.taxonomy_http_status += "/REQUEST_ERROR"
            aggregate.taxonomy_error_type = _technical_identifier(type(exc).__name__)
            return None

        suggestion_payload = _safe_json(suggestion_response)
        aggregate.taxonomy_http_status += f"/{suggestion_response.status_code}"
        if suggestion_response.status_code != 200 or not isinstance(
            suggestion_payload, Mapping
        ):
            aggregate.taxonomy_error_type, aggregate.taxonomy_error_code = _error_metadata(
                suggestion_payload
            )
            return None
        suggestions = suggestion_payload.get("categorySuggestions")
        if not isinstance(suggestions, list) or not suggestions:
            aggregate.taxonomy_error_type = "CATEGORY_SUGGESTIONS_EMPTY"
            return None
        first = suggestions[0]
        category = first.get("category") if isinstance(first, Mapping) else None
        category_id = category.get("categoryId") if isinstance(category, Mapping) else None
        if not isinstance(category_id, str) or not category_id:
            aggregate.taxonomy_error_type = "CATEGORY_ID_MISSING"
            return None
        aggregate.taxonomy_ok = True
        aggregate.resolved_category_id = category_id
        return category_id

    def _discover_marketplace(
        self, marketplace_id: str, token: str
    ) -> Tuple[MarketplaceAggregate, List[_DiscoveryRecord]]:
        aggregate = MarketplaceAggregate(marketplace_id=marketplace_id)
        category_id = self._resolve_category(marketplace_id, token, aggregate)
        params = {
            "q": "Pokémon",
            "filter": f"conditionIds:{{{RAW_CONDITION_ID}}}",
            "fieldgroups": "EXTENDED",
            "limit": str(RESULT_LIMIT),
        }
        if category_id:
            params["category_ids"] = category_id
        try:
            response = self._session.get(
                SEARCH_URL,
                headers=self._headers(token, marketplace_id),
                params=params,
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            aggregate.http_status = "REQUEST_ERROR"
            aggregate.error_type = _technical_identifier(type(exc).__name__)
            if marketplace_id == "EBAY_CH":
                aggregate.empty_reason = "API error"
            return aggregate, []

        aggregate.http_status = str(response.status_code)
        payload = _safe_json(response)
        if response.status_code != 200:
            aggregate.error_type, aggregate.error_code = _error_metadata(payload)
            if marketplace_id == "EBAY_CH":
                aggregate.empty_reason = (
                    "unsupported filter"
                    if _payload_mentions_filter(payload)
                    else "API error"
                )
            return aggregate, []
        if not isinstance(payload, Mapping):
            aggregate.error_type = "INVALID_JSON"
            if marketplace_id == "EBAY_CH":
                aggregate.empty_reason = "API error"
            return aggregate, []

        aggregate.total_announced = _safe_nonnegative_int(payload.get("total")) or 0
        summaries = payload.get("itemSummaries")
        if not isinstance(summaries, list):
            summaries = []
        records = []
        for summary in summaries[:RESULT_LIMIT]:
            if not isinstance(summary, Mapping):
                summary = {}
            item_id = summary.get("itemId")
            records.append(
                _DiscoveryRecord(
                    marketplace_id=marketplace_id,
                    summary=summary,
                    item_id=item_id if isinstance(item_id, str) and item_id else None,
                    enriched=summary,
                )
            )
        aggregate.results_received = len(records)
        if marketplace_id == "EBAY_CH":
            aggregate.empty_reason = (
                self._diagnose_empty_ch(token, category_id)
                if aggregate.results_received == 0
                else "autre"
            )
        return aggregate, records

    def _diagnose_empty_ch(self, token: str, category_id: Optional[str]) -> str:
        if not category_id:
            return "autre"
        combined = self._probe_search_total(
            token, {"q": "Pokémon", "category_ids": category_id, "limit": "1"}
        )
        if combined is None:
            return "API error"
        if combined > 0:
            return "no inventory"
        # Ces deux requetes sont uniquement des sondes agregées: la recherche
        # de decouverte conserve toujours la categorie resolue initialement.
        category_only = self._probe_search_total(
            token, {"category_ids": category_id, "limit": "1"}
        )
        query_only = self._probe_search_total(token, {"q": "Pokémon", "limit": "1"})
        if category_only is None or query_only is None:
            return "API error"
        if category_only > 0 and query_only > 0:
            return "query/category mismatch"
        return "no inventory"

    def _probe_search_total(
        self, token: str, params: Mapping[str, str]
    ) -> Optional[int]:
        try:
            response = self._session.get(
                SEARCH_URL,
                headers=self._headers(token, "EBAY_CH"),
                params=dict(params),
                timeout=self._timeout_seconds,
            )
        except requests.RequestException:
            return None
        payload = _safe_json(response)
        if response.status_code != 200 or not isinstance(payload, Mapping):
            return None
        return _safe_nonnegative_int(payload.get("total")) or 0

    def _enrich_unique_items(
        self,
        records: Sequence[_DiscoveryRecord],
        aggregates: Mapping[str, MarketplaceAggregate],
        token: str,
    ) -> Tuple[int, int]:
        first_by_id: Dict[str, _DiscoveryRecord] = {}
        duplicate_count = 0
        anonymous_count = 0
        for record in records:
            if record.item_id is None:
                anonymous_count += 1
                continue
            existing = first_by_id.get(record.item_id)
            if existing is None:
                first_by_id[record.item_id] = record
            elif existing.marketplace_id != record.marketplace_id:
                duplicate_count += 1

        detail_by_id: Dict[str, Tuple[bool, Mapping[str, object]]] = {}
        for item_id, owner in first_by_id.items():
            aggregate = aggregates[owner.marketplace_id]
            if aggregate.get_item_calls >= RESULT_LIMIT:
                detail_by_id[item_id] = (False, {})
                continue
            aggregate.get_item_calls += 1
            success, detail = self._get_item(item_id, owner.marketplace_id, token)
            detail_by_id[item_id] = (success, detail)

        for record in records:
            if record.item_id is None:
                record.enriched = record.summary
                continue
            success, detail = detail_by_id.get(record.item_id, (False, {}))
            record.get_item_success = success
            if success:
                record.detail = detail
                record.enriched = {**record.summary, **detail}
                aggregates[record.marketplace_id].get_item_success += 1
            else:
                record.enriched = record.summary
                aggregates[record.marketplace_id].get_item_failure += 1

        return duplicate_count, len(first_by_id) + anonymous_count

    def _get_item(
        self, item_id: str, marketplace_id: str, token: str
    ) -> Tuple[bool, Mapping[str, object]]:
        url = f"{PRODUCTION_BROWSE_BASE}/item/{quote(item_id, safe='')}"
        try:
            response = self._session.get(
                url,
                headers=self._headers(token, marketplace_id),
                params={"fieldgroups": "PRODUCT"},
                timeout=self._timeout_seconds,
            )
        except requests.RequestException:
            return False, {}
        if response.status_code != 200:
            return False, {}
        detail = _safe_json(response)
        return (True, detail) if isinstance(detail, Mapping) else (False, {})

    def _aggregate_record(
        self,
        record: _DiscoveryRecord,
        identity_aggregate: IdentityAggregate,
        images: ImageAggregate,
        cheap_filter: CheapFilterAggregate,
    ) -> None:
        before_resolution = resolve_card_identity(
            record.summary, set_number_resolver=self._set_number_resolver
        )
        after_resolution = resolve_card_identity(
            record.enriched, set_number_resolver=self._set_number_resolver
        )
        before_identity = before_resolution.identity
        after_identity = after_resolution.identity
        if before_identity.is_unambiguous_pokemon():
            identity_aggregate.before_usable += 1
        else:
            identity_aggregate.before_insufficient += 1
        if after_identity.is_unambiguous_pokemon():
            identity_aggregate.after_usable += 1
        else:
            identity_aggregate.after_insufficient += 1
        _aggregate_identity(after_identity, identity_aggregate)
        identity_aggregate.score_total += after_resolution.score
        if after_resolution.card_name_source == CARD_NAME_SOURCE_LOCALIZED:
            identity_aggregate.resolved_localized_aspects += 1
        elif after_resolution.card_name_source == CARD_NAME_SOURCE_TITLE:
            identity_aggregate.resolved_title_fallback += 1
        elif after_resolution.card_name_source == CARD_NAME_SOURCE_SET_NUMBER:
            identity_aggregate.resolved_set_number += 1

        if _has_localized_aspects(record.enriched):
            identity_aggregate.localized_aspects_available += 1
        if _has_product_data(record.enriched):
            identity_aggregate.product_data_available += 1

        images.search_primary += int(_primary_image_url(record.summary) is not None)
        images.search_additional += int(bool(_additional_images(record.summary)))
        images.get_item_primary += int(_primary_image_url(record.detail) is not None)
        images.get_item_additional += int(bool(_additional_images(record.detail)))
        images.total_images += len(_all_image_urls(record.detail))
        image_state, confirmed_back_url = self._back_image_state(record.enriched)
        if image_state == BACK_IMAGE_CONFIRMED:
            images.back_confirmed += 1
        elif image_state == BACK_IMAGE_CANDIDATE:
            images.back_candidate += 1
        else:
            images.back_unknown += 1

        condition_id = record.enriched.get("conditionId")
        raw = condition_id is not None and str(condition_id) == RAW_CONDITION_ID
        if not raw or not after_identity.is_unambiguous_pokemon():
            cheap_filter.reject_identity += 1
        if (
            raw
            and after_identity.is_unambiguous_pokemon()
            and image_state != BACK_IMAGE_CONFIRMED
        ):
            cheap_filter.reject_images += 1

        try:
            listing = parse_ebay_item(record.enriched)
        except (EbayApiError, TypeError, ValueError, KeyError):
            return
        scanner = RawCardScanner(
            _NeverGradeProvider(),  # type: ignore[arg-type]
            _MissingMarketDataProvider(),  # type: ignore[arg-type]
            safeguards=SafeguardConfig(maximum_paid_gradings_per_run=0),
        )
        result = scanner.cheap_filter(
            ScanRequest(
                listing=listing,
                image_pair=GradeImagePair(
                    front_url=listing.primary_image_url,
                    back_url=confirmed_back_url,
                ),
                costs=CostInputs(
                    purchase_price=listing.price,
                    shipping_to_buyer=listing.shipping_price,
                    buyer_fees=None,
                    grading_fee=None,
                    shipping_for_grading=None,
                    marketplace_selling_fee_rate=None,
                    other_costs=None,
                    currency=listing.currency,
                ),
            )
        )
        if result.eligible_for_visual_grading:
            cheap_filter.passed += 1
        if MARKET_DATA_UNAVAILABLE in result.reasons:
            cheap_filter.market_values_missing += 1

    def _back_image_state(
        self, payload: Mapping[str, object]
    ) -> Tuple[str, Optional[str]]:
        additions = _additional_images(payload)
        explicit_back_markers = {
            "back",
            "card back",
            "reverse",
            "verso",
            "ruckseite",
            "retro",
        }
        marker_keys = ("imageType", "type", "role", "label", "imageLabel")
        for image in additions:
            if any(
                _normalized_marker(image.get(key)) in explicit_back_markers
                for key in marker_keys
                if image.get(key) is not None
            ):
                image_url = image.get("imageUrl")
                return (
                    BACK_IMAGE_CONFIRMED,
                    str(image_url) if image_url else None,
                )

        for image in additions[:MAX_VISUAL_IMAGES_PER_ITEM]:
            image_url = image.get("imageUrl")
            if not image_url:
                continue
            image_bytes = self._image_fetcher(str(image_url))
            if image_bytes is None:
                continue
            assessment = self._back_detector.assess_bytes(image_bytes)
            if assessment.state == BACK_IMAGE_CONFIRMED:
                return BACK_IMAGE_CONFIRMED, str(image_url)
        if any(image.get("imageUrl") for image in additions):
            return BACK_IMAGE_CANDIDATE, None
        return BACK_IMAGE_UNKNOWN, None

    def _fetch_image_in_memory(self, image_url: str) -> Optional[bytes]:
        parsed = urlparse(image_url)
        hostname = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or not (
            hostname == "ebayimg.com" or hostname.endswith(".ebayimg.com")
        ):
            return None
        try:
            response = self._session.get(
                image_url,
                headers={"Accept": "image/*"},
                timeout=self._timeout_seconds,
                stream=True,
            )
        except requests.RequestException:
            return None
        try:
            if response.status_code != 200:
                return None
            raw_length = getattr(response, "headers", {}).get("Content-Length")
            if raw_length and int(raw_length) > MAX_IMAGE_BYTES:
                return None
            content = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                content.extend(chunk)
                if len(content) > MAX_IMAGE_BYTES:
                    return None
            return bytes(content) if content else None
        except (AttributeError, TypeError, ValueError):
            return None
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()


def _aggregate_identity(identity: CardIdentity, aggregate: IdentityAggregate) -> None:
    coverage = {
        "game": identity.game,
        "card_name": identity.card_name,
        "set_name": identity.set,
        "card_number": identity.card_number,
        "year": identity.year,
        "language": identity.language,
        "variant": identity.variant,
        "rarity": identity.rarity,
        "finish": identity.finish,
        "edition": identity.edition,
        "illustrator": identity.illustrator,
    }
    for field_name, value in coverage.items():
        if value is not None and value != "":
            setattr(aggregate, field_name, getattr(aggregate, field_name) + 1)
    missing = set(identity.missing_required_fields())
    aggregate.missing_game += int("game" in missing)
    aggregate.missing_card_name += int("card_name" in missing)
    aggregate.missing_set += int("set" in missing)
    aggregate.missing_card_number += int("card_number" in missing)
    aggregate.missing_language += int("language" in missing)
    aggregate.ambiguous += int(bool(identity.ambiguities))


def _has_localized_aspects(payload: Mapping[str, object]) -> bool:
    aspects = payload.get("localizedAspects")
    return isinstance(aspects, list) and any(isinstance(value, Mapping) for value in aspects)


def _has_product_data(payload: Mapping[str, object]) -> bool:
    product = payload.get("product")
    return isinstance(product, Mapping) and bool(product)


def _primary_image_url(payload: Mapping[str, object]) -> Optional[str]:
    image = payload.get("image")
    if isinstance(image, Mapping) and image.get("imageUrl"):
        return str(image["imageUrl"])
    return None


def _additional_images(payload: Mapping[str, object]) -> Tuple[Mapping[str, object], ...]:
    images = payload.get("additionalImages")
    if not isinstance(images, list):
        return ()
    return tuple(value for value in images if isinstance(value, Mapping))


def _all_image_urls(payload: Mapping[str, object]) -> Tuple[str, ...]:
    urls = []
    primary = _primary_image_url(payload)
    if primary:
        urls.append(primary)
    for image in _additional_images(payload):
        if image.get("imageUrl"):
            urls.append(str(image["imageUrl"]))
    return tuple(dict.fromkeys(urls))


def _normalized_marker(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join(
        "".join(character for character in text if not unicodedata.combining(character))
        .casefold()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )


def _safe_json(response: object) -> object:
    try:
        return response.json()  # type: ignore[attr-defined]
    except (TypeError, ValueError):
        return None


def _safe_nonnegative_int(value: object) -> Optional[int]:
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _technical_identifier(value: object) -> Optional[str]:
    if value is None:
        return None
    candidate = str(value)
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", candidate):
        return candidate
    return "REDACTED_IDENTIFIER"


def _error_metadata(payload: object) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(payload, Mapping):
        return "INVALID_OR_EMPTY_ERROR", None
    errors = payload.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], Mapping):
        first = errors[0]
        error_type = first.get("category") or first.get("domain")
        error_code = first.get("errorId") or first.get("code")
        return _technical_identifier(error_type), _technical_identifier(error_code)
    return (
        _technical_identifier(payload.get("type") or payload.get("error")),
        _technical_identifier(payload.get("code")),
    )


def _payload_mentions_filter(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return False
    for error in errors:
        if not isinstance(error, Mapping):
            continue
        technical_text = " ".join(
            str(error.get(key, ""))
            for key in ("domain", "category", "name", "message")
        ).casefold()
        if "filter" in technical_text or "conditionid" in technical_text:
            return True
    return False


def render_live_summary(summary: LiveDiagnosticSummary) -> str:
    aggregates = {value.marketplace_id: value for value in summary.marketplaces}
    ch = aggregates.get("EBAY_CH", MarketplaceAggregate("EBAY_CH"))
    lines: List[str] = [
        "=== V5 EBAY IDENTITY/BACK SUMMARY ===",
        "",
        f"OAuth: {'OK' if summary.oauth.token_obtained else 'FAIL'}",
        "",
        f"identity exploitable before: {summary.identity.before_usable}",
        f"identity exploitable after: {summary.identity.after_usable}",
        f"card_name coverage: {summary.identity.card_name}",
        f"resolved via localizedAspects: {summary.identity.resolved_localized_aspects}",
        f"resolved via title fallback: {summary.identity.resolved_title_fallback}",
        f"resolved via set+number: {summary.identity.resolved_set_number}",
        f"ambiguous: {summary.identity.ambiguous}",
        "",
        f"BACK_IMAGE_CONFIRMED: {summary.images.back_confirmed}",
        f"BACK_IMAGE_CANDIDATE: {summary.images.back_candidate}",
        f"BACK_IMAGE_UNKNOWN: {summary.images.back_unknown}",
        "",
        f"EBAY_CH reason: {ch.empty_reason}",
        "",
        "CardGrader calls: 0",
        "Purchases: 0",
        "Bids: 0",
        "Checkout: 0",
        "Persisted eBay records: 0",
    ]
    return "\n".join(lines)


def main() -> int:
    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
    try:
        summary = EbayLiveDiagnostic(client_id, client_secret).run()
    except Exception:
        # Aucun traceback: une bibliotheque tierce pourrait y inclure une
        # valeur listing-level. Le diagnostic reste agrege meme en erreur.
        summary = LiveDiagnosticSummary(
            oauth=OAuthAggregate("INTERNAL_ERROR", False, None),
            marketplaces=tuple(
                MarketplaceAggregate(marketplace_id=value) for value in MARKETPLACES
            ),
        )
    print(render_live_summary(summary))
    return 0 if summary.oauth.token_obtained else 1


if __name__ == "__main__":
    sys.exit(main())
