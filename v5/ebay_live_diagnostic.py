"""Diagnostic eBay Production V5 sans persistance ni donnees listing-level.

Ce module ne contient aucune operation d'achat, d'enchere ou de checkout. Il
ne conserve que des compteurs agreges en memoire et ne journalise jamais les
credentials, l'Application Access Token ou les valeurs des annonces.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

import requests

from .ebay import (
    OAUTH_SCOPE,
    PRODUCTION_BROWSE_BASE,
    PRODUCTION_IDENTITY_BASE,
    EbayApiError,
    parse_ebay_item,
)
from .models import CostInputs, GradeImagePair
from .scanner import (
    MARKET_DATA_UNAVAILABLE,
    RawCardScanner,
    SafeguardConfig,
    ScanRequest,
)
from .valuation import MarketDataUnavailable


OAUTH_URL = f"{PRODUCTION_IDENTITY_BASE}/token"
SEARCH_URL = f"{PRODUCTION_BROWSE_BASE}/item_summary/search"
CATEGORY_ID = "183454"
RAW_CONDITION_ID = "4000"
RESULT_LIMIT = 20
MARKETPLACES = ("EBAY_US", "EBAY_CH")


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
    http_status: str = "NOT_CALLED"
    error_type: Optional[str] = None
    error_code: Optional[str] = None
    total_announced: int = 0
    results_received: int = 0
    raw_condition_4000: int = 0
    other_conditions: int = 0
    usable_identity: int = 0
    insufficient_identity: int = 0
    front_image_available: int = 0
    back_image_available: int = 0
    insufficient_images: int = 0
    cheap_filter_pass: int = 0
    cheap_filter_reject: int = 0
    market_values_missing: int = 0


@dataclass(frozen=True)
class LiveDiagnosticSummary:
    oauth: OAuthAggregate
    marketplaces: Tuple[MarketplaceAggregate, ...]


class EbayLiveDiagnostic:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        session: Optional[requests.Session] = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session or requests.Session()
        self._timeout_seconds = timeout_seconds

    def run(self) -> LiveDiagnosticSummary:
        token, oauth = self._application_token()
        if token is None:
            return LiveDiagnosticSummary(
                oauth=oauth,
                marketplaces=tuple(
                    MarketplaceAggregate(marketplace_id=value)
                    for value in MARKETPLACES
                ),
            )

        # Le token reste une variable en memoire et n'entre jamais dans le
        # resultat agregé ni dans le rendu des logs.
        marketplaces = tuple(
            self._browse_marketplace(marketplace_id, token)
            for marketplace_id in MARKETPLACES
        )
        return LiveDiagnosticSummary(oauth=oauth, marketplaces=marketplaces)

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

    def _browse_marketplace(
        self, marketplace_id: str, token: str
    ) -> MarketplaceAggregate:
        aggregate = MarketplaceAggregate(marketplace_id=marketplace_id)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
        }
        params = {
            "q": "Pokémon",
            "category_ids": CATEGORY_ID,
            "filter": f"conditionIds:{{{RAW_CONDITION_ID}}}",
            "fieldgroups": "EXTENDED",
            "limit": str(RESULT_LIMIT),
        }
        try:
            response = self._session.get(
                SEARCH_URL,
                headers=headers,
                params=params,
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            aggregate.http_status = "REQUEST_ERROR"
            aggregate.error_type = _technical_identifier(type(exc).__name__)
            return aggregate

        aggregate.http_status = str(response.status_code)
        payload = _safe_json(response)
        if response.status_code != 200:
            aggregate.error_type, aggregate.error_code = _error_metadata(payload)
            return aggregate
        if not isinstance(payload, Mapping):
            aggregate.error_type = "INVALID_JSON"
            return aggregate

        aggregate.total_announced = _safe_nonnegative_int(payload.get("total")) or 0
        summaries = payload.get("itemSummaries")
        if not isinstance(summaries, list):
            summaries = []
        summaries = summaries[:RESULT_LIMIT]
        aggregate.results_received = len(summaries)

        for summary in summaries:
            if not isinstance(summary, Mapping):
                aggregate.insufficient_identity += 1
                aggregate.insufficient_images += 1
                aggregate.cheap_filter_reject += 1
                continue
            detail = self._item_detail_in_memory(summary, headers)
            self._aggregate_item(detail, aggregate)
        return aggregate

    def _item_detail_in_memory(
        self, summary: Mapping[str, object], headers: Mapping[str, str]
    ) -> Mapping[str, object]:
        item_id = summary.get("itemId")
        if not isinstance(item_id, str) or not item_id:
            return summary
        url = f"{PRODUCTION_BROWSE_BASE}/item/{quote(item_id, safe='')}"
        try:
            response = self._session.get(
                url,
                headers=dict(headers),
                timeout=self._timeout_seconds,
            )
        except requests.RequestException:
            return summary
        if response.status_code != 200:
            return summary
        detail = _safe_json(response)
        if not isinstance(detail, Mapping):
            return summary
        # Fusion ephemere en memoire; aucune reponse n'est retournee au caller.
        return {**summary, **detail}

    @staticmethod
    def _aggregate_item(
        payload: Mapping[str, object], aggregate: MarketplaceAggregate
    ) -> None:
        condition_id = (
            str(payload["conditionId"])
            if payload.get("conditionId") is not None
            else None
        )
        if condition_id == RAW_CONDITION_ID:
            aggregate.raw_condition_4000 += 1
        else:
            aggregate.other_conditions += 1

        try:
            listing = parse_ebay_item(payload)
        except (EbayApiError, TypeError, ValueError, KeyError):
            aggregate.insufficient_identity += 1
            aggregate.insufficient_images += 1
            aggregate.cheap_filter_reject += 1
            return

        # Acces explicite aux champs demandes pour verifier le contrat du
        # parser. Aucune de ces valeurs ne quitte la memoire du processus.
        _ = (
            listing.condition_id,
            listing.condition,
            listing.price,
            listing.buying_options,
            listing.end_time,
            listing.image_urls,
            listing.category_id,
            listing.category_name,
            listing.aspects,
        )

        identity_usable = listing.identity.is_unambiguous_pokemon()
        if identity_usable:
            aggregate.usable_identity += 1
        else:
            aggregate.insufficient_identity += 1

        front_available = bool(listing.primary_image_url)
        if front_available:
            aggregate.front_image_available += 1

        # Browse fournit des images additionnelles sans role recto/verso.
        # Le diagnostic refuse donc d'appeler l'une d'elles "verso" sans
        # preuve semantique. back_image_available reste prudemment a zero.
        back_available = False
        if back_available:
            aggregate.back_image_available += 1
        if not front_available or not back_available:
            aggregate.insufficient_images += 1

        # Passage dans le vrai cheap filter V5 avec un MarketDataProvider
        # explicitement indisponible. Aucun cout absent n'est remplace par zero
        # et le provider visuel est un garde-fou qui echouerait s'il etait appele.
        scanner = RawCardScanner(
            _NeverGradeProvider(),  # type: ignore[arg-type]
            _MissingMarketDataProvider(),  # type: ignore[arg-type]
            safeguards=SafeguardConfig(maximum_paid_gradings_per_run=0),
        )
        cheap_result = scanner.cheap_filter(
            ScanRequest(
                listing=listing,
                image_pair=GradeImagePair(
                    front_url=listing.primary_image_url,
                    back_url=None,
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
        if cheap_result.eligible_for_visual_grading:
            aggregate.cheap_filter_pass += 1
        else:
            aggregate.cheap_filter_reject += 1
        if MARKET_DATA_UNAVAILABLE in cheap_result.reasons:
            aggregate.market_values_missing += 1


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


def render_live_summary(summary: LiveDiagnosticSummary) -> str:
    lines: List[str] = [
        "=== V5 EBAY LIVE SUMMARY ===",
        "",
        "OAuth:",
        f"HTTP status: {summary.oauth.http_status}",
        f"Application token: {'OK' if summary.oauth.token_obtained else 'FAIL'}",
        f"expires_in: {summary.oauth.expires_in if summary.oauth.expires_in is not None else 'N/A'}",
    ]
    for aggregate in summary.marketplaces:
        lines.extend(
            [
                "",
                f"{aggregate.marketplace_id}:",
                f"HTTP status: {aggregate.http_status}",
            ]
        )
        if aggregate.error_type:
            lines.append(f"error type: {aggregate.error_type}")
        if aggregate.error_code:
            lines.append(f"error code: {aggregate.error_code}")
        lines.extend(
            [
                f"total annoncé: {aggregate.total_announced}",
                f"résultats reçus: {aggregate.results_received}",
                f"raw conditionId=4000: {aggregate.raw_condition_4000}",
                f"autres conditions: {aggregate.other_conditions}",
                f"identité exploitable: {aggregate.usable_identity}",
                f"identité insuffisante: {aggregate.insufficient_identity}",
                f"front image disponible: {aggregate.front_image_available}",
                f"back image disponible: {aggregate.back_image_available}",
                f"images insuffisantes: {aggregate.insufficient_images}",
                f"cheap-filter pass: {aggregate.cheap_filter_pass}",
                f"cheap-filter reject: {aggregate.cheap_filter_reject}",
                f"market-values-missing: {aggregate.market_values_missing}",
            ]
        )
    lines.extend(
        [
            "",
            "CardGrader calls: 0",
            "Purchases: 0",
            "Bids: 0",
            "Checkout: 0",
            "Persisted eBay records: 0",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
    try:
        summary = EbayLiveDiagnostic(client_id, client_secret).run()
    except Exception:
        # Aucun traceback: il pourrait contenir une valeur listing-level issue
        # d'une bibliotheque tierce. Le statut reste purement technique.
        summary = LiveDiagnosticSummary(
            oauth=OAuthAggregate("INTERNAL_ERROR", False, None),
            marketplaces=tuple(
                MarketplaceAggregate(marketplace_id=value) for value in MARKETPLACES
            ),
        )
    print(render_live_summary(summary))
    us_summary = next(
        (value for value in summary.marketplaces if value.marketplace_id == "EBAY_US"),
        None,
    )
    return 0 if summary.oauth.token_obtained and us_summary and us_summary.http_status == "200" else 1


if __name__ == "__main__":
    sys.exit(main())
