from __future__ import annotations

import base64
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple
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
RAW_CONDITION_ID = "4000"
GRADED_CONDITION_IDS = frozenset({"2750"})


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


def _append_aspect(
    aspects: Dict[str, Tuple[str, ...]], name: object, raw_values: object
) -> None:
    clean_name = str(name or "").strip()
    if not clean_name:
        return
    if isinstance(raw_values, (list, tuple)):
        values = tuple(str(value).strip() for value in raw_values if str(value).strip())
    elif raw_values is None:
        values = ()
    else:
        values = (str(raw_values).strip(),)
    if values:
        aspects[clean_name] = tuple(
            dict.fromkeys(aspects.get(clean_name, ()) + values)
        )


def _aspects(payload: Mapping[str, object]) -> Dict[str, Tuple[str, ...]]:
    """Fusionne les aspects structures Search/getItem et Product en memoire."""

    aspects: Dict[str, Tuple[str, ...]] = {}
    for raw_aspect in payload.get("localizedAspects", []) or []:
        if not isinstance(raw_aspect, Mapping):
            continue
        raw_values = raw_aspect.get("value")
        if raw_values is None:
            raw_values = raw_aspect.get("values")
        _append_aspect(aspects, raw_aspect.get("name"), raw_values)

    product = payload.get("product")
    if isinstance(product, Mapping):
        for group in product.get("aspectGroups", []) or []:
            if not isinstance(group, Mapping):
                continue
            for raw_aspect in group.get("aspects", []) or []:
                if not isinstance(raw_aspect, Mapping):
                    continue
                values = raw_aspect.get("localizedValues")
                if values is None:
                    values = raw_aspect.get("values")
                _append_aspect(
                    aspects,
                    raw_aspect.get("localizedName") or raw_aspect.get("name"),
                    values,
                )
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


def grading_status_from_ebay_data(
    condition_id: Optional[str], aspects: Mapping[str, Tuple[str, ...]]
) -> StructuredGradingStatus:
    """Combine les champs eBay structures sans utiliser le titre.

    eBay definit 4000 comme non grade et 2750 comme grade pour la categorie
    de cartes concernee. Un conflit avec les aspects reste ambigu et est donc
    rejete de maniere prudente.
    """

    aspect_status = structured_grading_status(aspects)
    if condition_id == RAW_CONDITION_ID:
        if aspect_status is StructuredGradingStatus.GRADED:
            return StructuredGradingStatus.UNKNOWN
        return StructuredGradingStatus.RAW
    if condition_id in GRADED_CONDITION_IDS:
        if aspect_status is StructuredGradingStatus.RAW:
            return StructuredGradingStatus.UNKNOWN
        return StructuredGradingStatus.GRADED
    return aspect_status


IDENTITY_ALIASES = {
    "game": ("Game", "Jeu", "Franchise", "Spiel", "Gioco", "Juego"),
    "set": (
        "Set",
        "Set Name",
        "Card Set",
        "Series",
        "Serie",
        "Série",
        "Extension",
        "Nom du set",
        "Nom de l'extension",
        "Erweiterung",
        "Kartenset",
        "Espansione",
        "Nome del set",
        "Conjunto",
        "Colección",
        "Expansion",
        "Expansión",
    ),
    "card_number": (
        "Card Number",
        "Card No.",
        "Collector Number",
        "Numero de carte",
        "Numéro de carte",
        "N° de carte",
        "Nº de carte",
        "Kartennummer",
        "Nummer der Karte",
        "Numero della carta",
        "Numero carta",
        "Número de carta",
        "N.º de carta",
    ),
    "year": (
        "Year Manufactured",
        "Year",
        "Annee de fabrication",
        "Année",
        "Herstellungsjahr",
        "Anno di fabbricazione",
        "Año de fabricación",
        "Año",
    ),
    "language": ("Language", "Langue", "Sprache", "Lingua", "Idioma"),
    "variant": (
        "Parallel/Variety",
        "Variante",
        "Parallelita/Varieta",
        "Features",
        "Caracteristiques",
        "Caractéristiques",
        "Merkmale",
        "Besonderheiten",
        "Características",
    ),
    "rarity": (
        "Rarity",
        "Rareté",
        "Rarite",
        "Seltenheit",
        "Rarità",
        "Rarita",
        "Rareza",
    ),
    "finish": (
        "Finish",
        "Finition",
        "Holo",
        "Holographic",
        "Reverse Holo",
        "Holographique",
        "Oberfläche",
        "Oberflache",
        "Finitura",
        "Acabado",
    ),
    "edition": ("Edition", "Édition", "Edizione", "Ausgabe", "Edición"),
    "illustrator": (
        "Illustrator",
        "Illustrateur",
        "Illustratore",
        "Ilustrador",
    ),
}

DIRECT_CARD_NAME_ALIASES = (
    "Card Name",
    "Name of Card",
    "Nom de la carte",
    "Nom de carte",
    "Pokémon",
    "Pokemon",
    "Pokémon Name",
    "Pokemon Name",
    "Nom du Pokémon",
    "Kartenname",
    "Nome carta",
    "Nome della carta",
    "Nombre de la carta",
)
CHARACTER_CARD_NAME_ALIASES = (
    "Character",
    "Personnage",
    "Personaggio",
    "Charakter",
    "Personaje",
)
CONTEXTUAL_CARD_NAME_ALIASES = (
    "Card",
    "Carte",
    "Subject",
    "Sujet",
    "Motiv",
    "Soggetto",
)

CARD_NAME_SOURCE_LOCALIZED = "localizedAspects"
CARD_NAME_SOURCE_TITLE = "title fallback"
CARD_NAME_SOURCE_SET_NUMBER = "set+number"

IDENTITY_SCORE_WEIGHTS = {
    "card_name": 30,
    "set": 20,
    "card_number": 20,
    "language": 10,
    "year": 10,
    "variant": 10,
}


@dataclass(frozen=True)
class CardNameLookupResult:
    card_name: Optional[str]
    ambiguous: bool = False


class SetNumberCardNameResolver(Protocol):
    """Future resolution exacte, sans imposer de fournisseur externe."""

    def resolve(
        self,
        set_name: str,
        card_number: str,
        language: Optional[str],
        year: Optional[int],
        variant: Optional[str],
    ) -> CardNameLookupResult:
        ...


class NullSetNumberCardNameResolver:
    def resolve(
        self,
        set_name: str,
        card_number: str,
        language: Optional[str],
        year: Optional[int],
        variant: Optional[str],
    ) -> CardNameLookupResult:
        return CardNameLookupResult(None)


@dataclass(frozen=True)
class IdentityResolution:
    identity: CardIdentity
    score: int
    score_components: Tuple[str, ...]
    card_name_source: Optional[str]


@dataclass(frozen=True)
class IdentityAspectAudit:
    unmapped_name_like_label: bool = False
    unmapped_number_like_label: bool = False


def identity_aspect_audit(payload: Mapping[str, object]) -> IdentityAspectAudit:
    """Count potentially useful labels without logging labels or values.

    This is diagnostic-only. Unknown labels are never promoted to identity
    fields, so a future taxonomy alias still needs an explicit offline test.
    """

    aspects = _aspects(payload)
    recognized_name_labels = {
        _normalize(value)
        for value in (
            *DIRECT_CARD_NAME_ALIASES,
            *CHARACTER_CARD_NAME_ALIASES,
            *CONTEXTUAL_CARD_NAME_ALIASES,
        )
    }
    recognized_number_labels = {
        _normalize(value) for value in IDENTITY_ALIASES["card_number"]
    }
    unmapped_name = False
    unmapped_number = False
    for label in aspects:
        normalized = _normalize(label)
        tokens = set(normalized.split())
        if normalized not in recognized_name_labels and (
            tokens
            & {
                "name",
                "nom",
                "nome",
                "nombre",
                "character",
                "personnage",
                "personaggio",
                "personaje",
                "charakter",
                "pokemon",
            }
        ):
            unmapped_name = True
        if normalized not in recognized_number_labels and (
            tokens
            & {
                "number",
                "numero",
                "nummer",
                "collector",
            }
        ) and (
            tokens & {"card", "carte", "carta", "karte", "collector"}
        ):
            unmapped_number = True
    return IdentityAspectAudit(unmapped_name, unmapped_number)


def _single_card_name(
    aspects: Mapping[str, Tuple[str, ...]], aliases: Sequence[str]
) -> Tuple[Optional[str], bool]:
    values = tuple(
        dict.fromkeys(value for value in _matching_values(aspects, aliases) if value)
    )
    if len(values) == 1:
        return values[0], False
    return None, len(values) > 1


def _card_name_from_aspects(
    aspects: Mapping[str, Tuple[str, ...]],
    set_name: Optional[str],
    card_number: Optional[str],
) -> Tuple[Optional[str], Tuple[str, ...]]:
    direct, direct_ambiguous = _single_card_name(aspects, DIRECT_CARD_NAME_ALIASES)
    if direct_ambiguous:
        return None, ("card_name: plusieurs noms directs",)
    if direct:
        return direct, ()

    character, character_ambiguous = _single_card_name(
        aspects, CHARACTER_CARD_NAME_ALIASES
    )
    if character and re.search(r"[,;|]", character):
        character = None
        character_ambiguous = True
    if character_ambiguous:
        return None, ("card_name: plusieurs personnages",)
    if character:
        return character, ()

    contextual, contextual_ambiguous = _single_card_name(
        aspects, CONTEXTUAL_CARD_NAME_ALIASES
    )
    if contextual_ambiguous:
        return None, ("card_name: plusieurs sujets",)
    generic_values = {
        "card",
        "carte",
        "single card",
        "individual card",
        "trading card",
        "pokemon card",
        "collectible card",
        "collectible",
    }
    if (
        contextual
        and _normalize(contextual) not in generic_values
        and set_name
        and card_number
    ):
        return contextual, ()
    return None, ()


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

    card_name, card_name_ambiguities = _card_name_from_aspects(
        aspects, extracted["set"], extracted["card_number"]
    )
    ambiguities.extend(card_name_ambiguities)

    return CardIdentity(
        game=extracted["game"],
        card_name=card_name,
        set=extracted["set"],
        card_number=extracted["card_number"],
        year=year,
        language=extracted["language"],
        variant=extracted["variant"],
        rarity=extracted["rarity"],
        finish=extracted["finish"],
        edition=extracted["edition"],
        illustrator=extracted["illustrator"],
        ambiguities=tuple(ambiguities),
    )


_TITLE_LABELS = {
    "set": ("set", "series", "serie", "série", "extension", "erweiterung"),
    "card_number": (
        "card number",
        "numero de carte",
        "numéro de carte",
        "kartennummer",
        "numero della carta",
    ),
    "language": ("language", "langue", "sprache", "lingua"),
    "variant": ("variant", "variante", "parallel/variety"),
}


def _labelled_title_value(title: str, labels: Sequence[str]) -> Optional[str]:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:^|[|;,])\s*(?:{label_pattern})\s*[:=]\s*([^|;,]{{1,80}})",
        title,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _title_fallbacks(title: str) -> Dict[str, object]:
    """Extrait seulement des signaux explicites ou des motifs tres bornes."""

    values: Dict[str, object] = {}
    normalized = _normalize(title)
    if "pokemon" in normalized:
        values["game"] = "Pokémon TCG"
    for field_name, labels in _TITLE_LABELS.items():
        value = _labelled_title_value(title, labels)
        if value:
            values[field_name] = value

    if "card_number" not in values:
        number_match = re.search(
            (
                r"(?<![A-Za-z0-9])"
                r"([A-Z]{0,6}\d{1,4}[A-Z]?/"
                r"(?:[A-Z]{0,6}\d{1,4}[A-Z]?|[A-Z]{1,6}(?:-[A-Z])?))"
                r"(?![A-Za-z0-9])"
            ),
            title,
            flags=re.IGNORECASE,
        )
        if number_match:
            values["card_number"] = number_match.group(1)
    year_match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", title)
    if year_match:
        values["year"] = int(year_match.group(1))

    language_names = {
        "english": "English",
        "anglais": "English",
        "french": "French",
        "francais": "French",
        "franzosisch": "French",
        "german": "German",
        "allemand": "German",
        "deutsch": "German",
        "italian": "Italian",
        "italien": "Italian",
        "italiano": "Italian",
        "japanese": "Japanese",
        "japonais": "Japanese",
        "japanisch": "Japanese",
    }
    if "language" not in values:
        for signal, canonical in language_names.items():
            if re.search(rf"\b{re.escape(signal)}\b", normalized):
                values["language"] = canonical
                break
    return values


def _safe_title_card_name(
    title: str, structured: CardIdentity
) -> Tuple[Optional[str], bool]:
    """Retourne un nom verbatim seulement si les aspects verrouillent l'identite."""

    if not structured.set or not structured.card_number:
        return None, False
    if not (structured.language or structured.year or structured.variant):
        return None, False

    labelled = _labelled_title_value(
        title,
        (
            "card name",
            "nom de la carte",
            "character",
            "personnage",
            "kartenname",
            "nome carta",
        ),
    )
    if labelled:
        if re.search(r"[,;]|\s(?:and|et|und|e)\s", labelled, flags=re.IGNORECASE):
            return None, True
        return labelled, False

    number_match = re.search(
        re.escape(structured.card_number), title, flags=re.IGNORECASE
    )
    if not number_match:
        return None, False
    candidate = title[: number_match.start()]
    removable = (
        structured.set,
        structured.language,
        str(structured.year) if structured.year else None,
        structured.variant,
        "Pokémon TCG",
        "Pokemon TCG",
        "Pokémon",
        "Pokemon",
        "Trading Card Game",
        "JCC",
        "TCG",
    )
    for value in removable:
        if value:
            candidate = re.sub(re.escape(value), " ", candidate, flags=re.IGNORECASE)
    candidate = re.sub(
        r"\b(?:card|carte|single|raw|ungraded|holo|reverse|rare|mint|nm)\b",
        " ",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = " ".join(candidate.strip(" -–—:|[](){}").split())
    if not candidate:
        return None, False
    unsafe = (
        len(candidate) > 60
        or not 1 <= len(candidate.split()) <= 4
        or bool(
            re.search(
                r"[,;/+&]|\b(?:lot|bundle|collection|mystery|proxy|custom)\b",
                candidate,
                re.IGNORECASE,
            )
        )
        or not any(character.isalpha() for character in candidate)
    )
    return (None, True) if unsafe else (candidate, False)


def _identity_score(identity: CardIdentity) -> Tuple[int, Tuple[str, ...]]:
    values = {
        "card_name": identity.card_name,
        "set": identity.set,
        "card_number": identity.card_number,
        "language": identity.language,
        "year": identity.year,
        "variant": identity.variant,
    }
    components = tuple(
        f"{field_name}:+{IDENTITY_SCORE_WEIGHTS[field_name]}"
        for field_name, value in values.items()
        if value is not None and value != ""
    )
    score = sum(
        IDENTITY_SCORE_WEIGHTS[field_name]
        for field_name, value in values.items()
        if value is not None and value != ""
    )
    if identity.ambiguities:
        score = max(0, score - 25)
        components += ("ambiguity:-25",)
    return score, components


def resolve_card_identity(
    payload: Mapping[str, object],
    aspects: Optional[Mapping[str, Tuple[str, ...]]] = None,
    set_number_resolver: Optional[SetNumberCardNameResolver] = None,
) -> IdentityResolution:
    structured = card_identity_from_aspects(
        aspects if aspects is not None else _aspects(payload)
    )
    product = payload.get("product")
    product_title = product.get("title") if isinstance(product, Mapping) else None
    titles = tuple(
        dict.fromkeys(
            str(value).strip()
            for value in (product_title, payload.get("title"))
            if value and str(value).strip()
        )
    )
    fallback: Dict[str, object] = {}
    for title in titles:
        for name, value in _title_fallbacks(title).items():
            fallback.setdefault(name, value)
    fields = {
        "game": structured.game,
        "card_name": structured.card_name,
        "set": structured.set,
        "card_number": structured.card_number,
        "year": structured.year,
        "language": structured.language,
        "variant": structured.variant,
        "rarity": structured.rarity,
        "finish": structured.finish,
        "edition": structured.edition,
        "illustrator": structured.illustrator,
    }
    for name, value in fallback.items():
        if name in fields and name != "card_name" and fields[name] is None:
            fields[name] = value

    card_name_source = (
        CARD_NAME_SOURCE_LOCALIZED if structured.card_name is not None else None
    )
    ambiguities = list(structured.ambiguities)
    resolver = set_number_resolver or NullSetNumberCardNameResolver()
    if fields["card_name"] is None and fields["set"] and fields["card_number"]:
        lookup = resolver.resolve(
            str(fields["set"]),
            str(fields["card_number"]),
            str(fields["language"]) if fields["language"] else None,
            int(fields["year"]) if fields["year"] is not None else None,
            str(fields["variant"]) if fields["variant"] else None,
        )
        if lookup.ambiguous:
            ambiguities.append("card_name: resolution set+number ambigue")
        elif lookup.card_name and lookup.card_name.strip():
            fields["card_name"] = lookup.card_name.strip()
            card_name_source = CARD_NAME_SOURCE_SET_NUMBER

    if fields["card_name"] is None:
        title_names = []
        title_ambiguous = False
        for title in titles:
            title_name, ambiguous = _safe_title_card_name(title, structured)
            title_ambiguous = title_ambiguous or ambiguous
            if title_name:
                title_names.append(title_name)
        distinct_title_names = tuple(dict.fromkeys(title_names))
        if title_ambiguous or len(distinct_title_names) > 1:
            ambiguities.append("card_name: title fallback ambigu")
        elif len(distinct_title_names) == 1:
            fields["card_name"] = distinct_title_names[0]
            card_name_source = CARD_NAME_SOURCE_TITLE

    identity = CardIdentity(**fields, ambiguities=tuple(dict.fromkeys(ambiguities)))
    score, components = _identity_score(identity)
    return IdentityResolution(identity, score, components, card_name_source)


def card_identity_from_ebay_payload(
    payload: Mapping[str, object], aspects: Optional[Mapping[str, Tuple[str, ...]]] = None
) -> CardIdentity:
    return resolve_card_identity(payload, aspects).identity


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
    condition_id = (
        str(payload["conditionId"]) if payload.get("conditionId") is not None else None
    )
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
        condition_id=condition_id,
        grading_status=grading_status_from_ebay_data(condition_id, aspects),
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
        identity=card_identity_from_ebay_payload(payload, aspects),
    )
