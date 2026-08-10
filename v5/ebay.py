from __future__ import annotations

import base64
import os
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

import requests

from .models import (
    CardIdentity,
    EbayListing,
    SellerInfo,
    StructuredGradingStatus,
    decimal_from,
)


PRODUCTION_IDENTITY_BASE = "https://api.ebay.com/identity/v1/oauth2"
PRODUCTION_BROWSE_BASE = "https://api.ebay.com/buy/browse/v1"
SANDBOX_IDENTITY_BASE = "https://api.sandbox.ebay.com/identity/v1/oauth2"
SANDBOX_BROWSE_BASE = "https://api.sandbox.ebay.com/buy/browse/v1"
OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayConfigurationError(ValueError):
    pass


class EbayApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class EbayBrowseConfig:
    client_id: str
    client_secret: str
    marketplace_id: str
    category_id: str
    raw_aspect_name: str
    raw_aspect_value: str
    delivery_country: Optional[str] = None
    delivery_postal_code: Optional[str] = None
    content_language: Optional[str] = None
    environment: str = "production"
    timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> "EbayBrowseConfig":
        required = {
            "client_id": os.getenv("EBAY_CLIENT_ID", "").strip(),
            "client_secret": os.getenv("EBAY_CLIENT_SECRET", "").strip(),
            "category_id": os.getenv("EBAY_V5_CATEGORY_ID", "").strip(),
            "raw_aspect_name": os.getenv("EBAY_V5_RAW_ASPECT_NAME", "").strip(),
            "raw_aspect_value": os.getenv("EBAY_V5_RAW_ASPECT_VALUE", "").strip(),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise EbayConfigurationError(
                "Variables eBay V5 manquantes: " + ", ".join(sorted(missing))
            )
        environment = os.getenv("EBAY_V5_ENVIRONMENT", "production").strip().lower()
        if environment not in {"production", "sandbox"}:
            raise EbayConfigurationError("EBAY_V5_ENVIRONMENT doit valoir production ou sandbox")
        return cls(
            marketplace_id=os.getenv("EBAY_V5_MARKETPLACE_ID", "EBAY_FR").strip(),
            delivery_country=os.getenv("EBAY_V5_DELIVERY_COUNTRY", "").strip() or None,
            delivery_postal_code=os.getenv("EBAY_V5_DELIVERY_POSTAL_CODE", "").strip() or None,
            content_language=os.getenv("EBAY_V5_CONTENT_LANGUAGE", "").strip() or None,
            environment=environment,
            timeout_seconds=float(os.getenv("EBAY_V5_TIMEOUT_SECONDS", "15")),
            **required,
        )

    @property
    def identity_base(self) -> str:
        if self.environment == "sandbox":
            return SANDBOX_IDENTITY_BASE
        return PRODUCTION_IDENTITY_BASE

    @property
    def browse_base(self) -> str:
        if self.environment == "sandbox":
            return SANDBOX_BROWSE_BASE
        return PRODUCTION_BROWSE_BASE


class EbayBrowseClient:
    """Connecteur read-only vers l'API Browse officielle eBay.

    Il ne contient aucune operation Order, bid, checkout ou achat. Le filtre
    RAW repose sur un aspect de categorie configure, puis chaque detail est
    revalide avec ``localizedAspects``.
    """

    def __init__(
        self,
        config: EbayBrowseConfig,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self._access_token: Optional[str] = None

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        credentials = f"{self.config.client_id}:{self.config.client_secret}".encode("utf-8")
        authorization = base64.b64encode(credentials).decode("ascii")
        response = self.session.post(
            f"{self.config.identity_base}/token",
            headers={
                "Authorization": f"Basic {authorization}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": OAUTH_SCOPE},
            timeout=self.config.timeout_seconds,
        )
        self._raise_for_status(response, "authentification eBay")
        token = response.json().get("access_token")
        if not token:
            raise EbayApiError("La reponse OAuth eBay ne contient aucun access_token")
        self._access_token = str(token)
        return self._access_token

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "X-EBAY-C-MARKETPLACE-ID": self.config.marketplace_id,
            "Accept": "application/json",
        }
        if self.config.content_language:
            headers["Accept-Language"] = self.config.content_language
        context = []
        if self.config.delivery_country:
            context.append(f"country={self.config.delivery_country}")
        if self.config.delivery_postal_code:
            context.append(f"zip={self.config.delivery_postal_code}")
        if context:
            headers["X-EBAY-C-ENDUSERCTX"] = "contextualLocation=" + quote(
                ",".join(context), safe=""
            )
        return headers

    @staticmethod
    def _raise_for_status(response: requests.Response, operation: str) -> None:
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(response, "status_code", "inconnu")
            raise EbayApiError(f"Echec {operation} (HTTP {status})") from exc

    def search_raw_pokemon_cards(
        self,
        query: str = "Pokemon card",
        limit: int = 50,
        offset: int = 0,
    ) -> List[EbayListing]:
        if not 1 <= limit <= 200:
            raise ValueError("La limite Browse eBay doit etre comprise entre 1 et 200")
        filters = []
        if self.config.delivery_country:
            filters.append(f"deliveryCountry:{self.config.delivery_country}")
        params = {
            "q": query,
            "category_ids": self.config.category_id,
            "aspect_filter": (
                f"categoryId:{self.config.category_id},"
                f"{self.config.raw_aspect_name}:{{{self.config.raw_aspect_value}}}"
            ),
            "fieldgroups": "EXTENDED",
            "limit": str(limit),
            "offset": str(offset),
        }
        if filters:
            params["filter"] = ",".join(filters)
        response = self.session.get(
            f"{self.config.browse_base}/item_summary/search",
            headers=self._headers(),
            params=params,
            timeout=self.config.timeout_seconds,
        )
        self._raise_for_status(response, "recherche Browse")

        listings = []
        for summary in response.json().get("itemSummaries", []):
            item_id = summary.get("itemId")
            if not item_id:
                continue
            detail = self.get_item_payload(str(item_id))
            listing = parse_ebay_item(detail)
            if listing.grading_status is StructuredGradingStatus.RAW:
                listings.append(listing)
        return listings

    def get_item_payload(self, item_id: str) -> Mapping[str, object]:
        response = self.session.get(
            f"{self.config.browse_base}/item/{item_id}",
            headers=self._headers(),
            timeout=self.config.timeout_seconds,
        )
        self._raise_for_status(response, f"lecture de l'article {item_id}")
        return response.json()


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    return " ".join(
        "".join(character for character in text if not unicodedata.combining(character))
        .casefold()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )


def _aspects(payload: Mapping[str, object]) -> Dict[str, Tuple[str, ...]]:
    aspects: Dict[str, Tuple[str, ...]] = {}
    for raw_aspect in payload.get("localizedAspects", []) or []:
        if not isinstance(raw_aspect, Mapping):
            continue
        name = str(raw_aspect.get("name", "")).strip()
        if not name:
            continue
        raw_values = raw_aspect.get("value")
        if raw_values is None:
            raw_values = raw_aspect.get("values")
        if isinstance(raw_values, (list, tuple)):
            values = tuple(str(value).strip() for value in raw_values if str(value).strip())
        elif raw_values is None:
            values = ()
        else:
            values = (str(raw_values).strip(),)
        if values:
            aspects[name] = tuple(dict.fromkeys(aspects.get(name, ()) + values))
    return aspects


def _matching_values(
    aspects: Mapping[str, Tuple[str, ...]], aliases: Iterable[str]
) -> Tuple[str, ...]:
    normalized_aliases = {_normalize(alias) for alias in aliases}
    values = []
    for name, aspect_values in aspects.items():
        if _normalize(name) in normalized_aliases:
            values.extend(aspect_values)
    return tuple(dict.fromkeys(values))


def structured_grading_status(
    aspects: Mapping[str, Tuple[str, ...]]
) -> StructuredGradingStatus:
    signals = []
    for name, values in aspects.items():
        normalized_name = _normalize(name)
        normalized_values = {_normalize(value) for value in values}
        if normalized_name in {"graded", "gradee", "carte gradee"}:
            if normalized_values & {"no", "non", "false", "ungraded", "non gradee"}:
                signals.append(StructuredGradingStatus.RAW)
            elif normalized_values & {"yes", "oui", "true", "graded", "gradee"}:
                signals.append(StructuredGradingStatus.GRADED)
        elif normalized_name in {
            "professional grader",
            "grading company",
            "service de gradation professionnelle",
            "organisme de certification",
        }:
            raw_values = {
                "not professionally graded",
                "ungraded",
                "none",
                "aucun",
                "non gradee",
                "non applicable",
            }
            if normalized_values & raw_values:
                signals.append(StructuredGradingStatus.RAW)
            elif normalized_values:
                signals.append(StructuredGradingStatus.GRADED)
        elif normalized_name in {
            "certification number",
            "numero de certification",
            "certification",
        }:
            ignored = {"", "none", "aucun", "not applicable", "n/a", "sans objet"}
            if normalized_values - ignored:
                signals.append(StructuredGradingStatus.GRADED)
    unique = set(signals)
    if unique == {StructuredGradingStatus.RAW}:
        return StructuredGradingStatus.RAW
    if unique == {StructuredGradingStatus.GRADED}:
        return StructuredGradingStatus.GRADED
    return StructuredGradingStatus.UNKNOWN


IDENTITY_ALIASES = {
    "game": ("Game", "Jeu", "Franchise"),
    "card_name": ("Card Name", "Nom de la carte", "Character", "Personnage"),
    "set": ("Set", "Card Set", "Series", "Serie", "Série", "Extension"),
    "card_number": ("Card Number", "Numero de carte", "Numéro de carte"),
    "year": ("Year Manufactured", "Year", "Annee de fabrication", "Année"),
    "language": ("Language", "Langue"),
    "variant": (
        "Parallel/Variety",
        "Variante",
        "Finish",
        "Finition",
        "Features",
        "Caracteristiques",
        "Caractéristiques",
    ),
}


def card_identity_from_aspects(
    aspects: Mapping[str, Tuple[str, ...]]
) -> CardIdentity:
    extracted: Dict[str, Optional[str]] = {}
    ambiguities = []
    for field_name, aliases in IDENTITY_ALIASES.items():
        values = _matching_values(aspects, aliases)
        distinct = tuple(dict.fromkeys(value for value in values if value))
        if len(distinct) > 1:
            ambiguities.append(f"{field_name}: valeurs contradictoires ({', '.join(distinct)})")
        extracted[field_name] = distinct[0] if len(distinct) == 1 else None

    year = None
    if extracted["year"]:
        try:
            year = int(str(extracted["year"]).strip())
            if year < 1996 or year > datetime.now().year + 1:
                ambiguities.append(f"year: valeur invalide ({year})")
                year = None
        except ValueError:
            ambiguities.append(f"year: valeur illisible ({extracted['year']})")

    return CardIdentity(
        game=extracted["game"],
        card_name=extracted["card_name"],
        set=extracted["set"],
        card_number=extracted["card_number"],
        year=year,
        language=extracted["language"],
        variant=extracted["variant"],
        ambiguities=tuple(ambiguities),
    )


def _amount(payload: object) -> Optional[object]:
    if isinstance(payload, Mapping):
        return payload.get("value")
    return None


def _currency(payload: object) -> Optional[str]:
    if isinstance(payload, Mapping) and payload.get("currency"):
        return str(payload["currency"])
    return None


def _shipping_price(payload: Mapping[str, object]) -> Optional[object]:
    prices = []
    for option in payload.get("shippingOptions", []) or []:
        if not isinstance(option, Mapping):
            continue
        for key in ("shippingCost", "baseDeliveryCost"):
            amount = _amount(option.get(key))
            if amount is not None:
                prices.append(decimal_from(amount))
    return min(prices) if prices else None


def _parse_datetime(value: object) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_ebay_item(payload: Mapping[str, object]) -> EbayListing:
    aspects = _aspects(payload)
    buying_options = tuple(str(value) for value in payload.get("buyingOptions", []) or [])
    price_payload = payload.get("price")
    if "AUCTION" in buying_options and payload.get("currentBidPrice"):
        price_payload = payload.get("currentBidPrice")
    amount = _amount(price_payload)
    currency = _currency(price_payload)
    if amount is None or not currency:
        raise EbayApiError("Article eBay sans prix/devise structure")

    categories = payload.get("categories", []) or []
    category_id = payload.get("categoryId")
    category_name = payload.get("categoryPath")
    if isinstance(categories, list) and categories:
        leaf = categories[-1]
        if isinstance(leaf, Mapping):
            category_id = category_id or leaf.get("categoryId")
            category_name = category_name or leaf.get("categoryName")

    seller_payload = payload.get("seller") or {}
    if not isinstance(seller_payload, Mapping):
        seller_payload = {}
    image_payload = payload.get("image") or {}
    if not isinstance(image_payload, Mapping):
        image_payload = {}
    additional_images = []
    for image in payload.get("additionalImages", []) or []:
        if isinstance(image, Mapping) and image.get("imageUrl"):
            additional_images.append(str(image["imageUrl"]))

    return EbayListing(
        item_id=str(payload.get("itemId", "")),
        title=str(payload.get("title", "")),
        url=str(payload.get("itemWebUrl", "")),
        price=decimal_from(amount),
        currency=currency,
        shipping_price=_shipping_price(payload),
        buying_options=buying_options,
        end_time=_parse_datetime(payload.get("itemEndDate")),
        bid_count=(int(payload["bidCount"]) if payload.get("bidCount") is not None else None),
        condition=(str(payload["condition"]) if payload.get("condition") else None),
        grading_status=structured_grading_status(aspects),
        seller=SellerInfo(
            username=(str(seller_payload["username"]) if seller_payload.get("username") else None),
            feedback_percentage=(
                str(seller_payload["feedbackPercentage"])
                if seller_payload.get("feedbackPercentage") is not None
                else None
            ),
            feedback_score=(
                int(seller_payload["feedbackScore"])
                if seller_payload.get("feedbackScore") is not None
                else None
            ),
        ),
        primary_image_url=(
            str(image_payload["imageUrl"]) if image_payload.get("imageUrl") else None
        ),
        additional_image_urls=tuple(dict.fromkeys(additional_images)),
        category_id=(str(category_id) if category_id else None),
        category_name=(str(category_name) if category_name else None),
        aspects=aspects,
        identity=card_identity_from_aspects(aspects),
    )
