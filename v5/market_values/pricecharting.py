from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, Optional, Protocol, Sequence, Tuple

try:
    import requests
except ModuleNotFoundError:  # Les tests hors ligne injectent leur session.
    requests = None  # type: ignore[assignment]

from ..models import CardIdentity
from .models import MarketValues, normalize_identity_text


PRICECHARTING_BASE_URL = "https://www.pricecharting.com"
PRICECHARTING_AMBIGUOUS = "PRICECHARTING_AMBIGUOUS"
PRICECHARTING_NO_MATCH = "PRICECHARTING_NO_MATCH"
PRICECHARTING_DISABLED = "PRICECHARTING_DISABLED"
PRICECHARTING_MATCHED = "PRICECHARTING_MATCHED"
PRICECHARTING_ERROR = "PRICECHARTING_ERROR"


class PriceChartingError(RuntimeError):
    pass


class HttpSession(Protocol):
    def get(self, url: str, **kwargs: object) -> object:
        ...


@dataclass(frozen=True)
class PriceChartingConfig:
    enabled: bool = False
    token: Optional[str] = field(default=None, repr=False)
    timeout_seconds: float = 15.0
    minimum_match_score: Decimal = Decimal("0.72")
    minimum_match_margin: Decimal = Decimal("0.08")
    minimum_request_interval_seconds: float = 1.0

    @classmethod
    def from_env(cls) -> "PriceChartingConfig":
        return cls(
            enabled=os.getenv("PRICECHARTING_ENABLED", "false").strip().casefold()
            == "true",
            token=os.getenv("PRICECHARTING_TOKEN", "").strip() or None,
            timeout_seconds=float(os.getenv("PRICECHARTING_TIMEOUT_SECONDS", "15")),
            minimum_match_score=Decimal(
                os.getenv("PRICECHARTING_MIN_MATCH_SCORE", "0.72")
            ),
            minimum_match_margin=Decimal(
                os.getenv("PRICECHARTING_MIN_MATCH_MARGIN", "0.08")
            ),
        )


@dataclass(frozen=True)
class CandidateMatch:
    product_id: str
    score: Decimal
    explanation: Tuple[str, ...]


@dataclass(frozen=True)
class PriceChartingResult:
    status: str
    values: Optional[MarketValues]
    candidates_seen: int
    match_explanation: Tuple[str, ...] = ()


class PriceChartingProvider:
    """Fournisseur officiel PriceCharting, desactive par defaut.

    Le token n'apparait dans aucun message, ``repr`` ou exception genere par
    cette classe. Les tests utilisent une session injectee et aucune requete
    reelle n'est necessaire.
    """

    def __init__(
        self,
        config: Optional[PriceChartingConfig] = None,
        session: Optional[HttpSession] = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config or PriceChartingConfig.from_env()
        if session is not None:
            self.session = session
        elif requests is not None:
            self.session = requests.Session()
        else:
            raise PriceChartingError(
                "Le client HTTP PriceCharting n'est pas installe"
            )
        self.monotonic = monotonic
        self.sleeper = sleeper
        self._last_request_started: Optional[float] = None
        self.live_calls = 0

    def values_for(self, identity: CardIdentity) -> PriceChartingResult:
        if not self.config.enabled:
            return PriceChartingResult(PRICECHARTING_DISABLED, None, 0)
        if not self.config.token:
            raise PriceChartingError("PRICECHARTING_TOKEN absent")

        search = self._request(
            "/api/products", {"q": _search_query(identity)}
        )
        raw_candidates = search.get("products")
        candidates = (
            tuple(item for item in raw_candidates if isinstance(item, Mapping))
            if isinstance(raw_candidates, Sequence) and not isinstance(raw_candidates, str)
            else ()
        )
        matches = tuple(
            sorted(
                (_score_candidate(identity, candidate) for candidate in candidates),
                key=lambda item: item.score,
                reverse=True,
            )
        )
        if not matches or matches[0].score < self.config.minimum_match_score:
            return PriceChartingResult(
                PRICECHARTING_NO_MATCH,
                None,
                len(candidates),
                matches[0].explanation if matches else (),
            )
        if len(matches) > 1 and (
            matches[0].score - matches[1].score < self.config.minimum_match_margin
        ):
            return PriceChartingResult(
                PRICECHARTING_AMBIGUOUS,
                None,
                len(candidates),
                ("top_match_margin_insufficient",),
            )

        selected = matches[0]
        product = self._request("/api/product", {"id": selected.product_id})
        if str(product.get("id", "")) != selected.product_id:
            return PriceChartingResult(
                PRICECHARTING_NO_MATCH,
                None,
                len(candidates),
                ("product_id_mismatch",),
            )
        detailed_match = _score_candidate(identity, product)
        if detailed_match.score < self.config.minimum_match_score:
            return PriceChartingResult(
                PRICECHARTING_NO_MATCH,
                None,
                len(candidates),
                ("product_detail_identity_mismatch",) + detailed_match.explanation,
            )
        values = market_values_from_product(
            product,
            identity=identity,
            match_confidence=detailed_match.score,
            explanation=detailed_match.explanation,
        )
        return PriceChartingResult(
            PRICECHARTING_MATCHED,
            values,
            len(candidates),
            detailed_match.explanation,
        )

    def _request(self, path: str, parameters: Mapping[str, str]) -> Mapping[str, object]:
        self._respect_rate_limit()
        safe_parameters = dict(parameters)
        safe_parameters["t"] = self.config.token or ""
        try:
            self.live_calls += 1
            response = self.session.get(
                f"{PRICECHARTING_BASE_URL}{path}",
                params=safe_parameters,
                timeout=self.config.timeout_seconds,
            )
        except Exception:
            raise PriceChartingError("Echec reseau PriceCharting") from None
        status_code = getattr(response, "status_code", None)
        if status_code != 200:
            raise PriceChartingError(f"Echec PriceCharting (HTTP {status_code})")
        try:
            payload = response.json()
        except Exception:
            raise PriceChartingError("Reponse JSON PriceCharting invalide") from None
        if not isinstance(payload, Mapping) or payload.get("status") != "success":
            raise PriceChartingError("Reponse PriceCharting en erreur")
        return payload

    def _respect_rate_limit(self) -> None:
        now = self.monotonic()
        if self._last_request_started is not None:
            elapsed = now - self._last_request_started
            remaining = self.config.minimum_request_interval_seconds - elapsed
            if remaining > 0:
                self.sleeper(remaining)
                now = self.monotonic()
        self._last_request_started = now


def _search_query(identity: CardIdentity) -> str:
    fields = (identity.card_name, identity.card_number, identity.set)
    return " ".join(str(value).strip() for value in fields if value)


def _compact_number(value: object) -> str:
    return re.sub(r"[^0-9a-z]", "", normalize_identity_text(value))


def _candidate_number_matches(card_number: str, candidate_text: str) -> bool:
    full = _compact_number(card_number)
    compact_candidate = _compact_number(candidate_text)
    if full and full in compact_candidate:
        return True
    numerator = _compact_number(card_number.split("/", 1)[0])
    if not numerator:
        return False
    return bool(re.search(rf"#\s*0*{re.escape(numerator)}\b", candidate_text))


def _contains_words(needle: object, haystack: str) -> bool:
    words = tuple(normalize_identity_text(needle).split())
    return bool(words) and all(word in haystack.split() for word in words)


def _score_candidate(
    identity: CardIdentity, candidate: Mapping[str, object]
) -> CandidateMatch:
    product_id = str(candidate.get("id", ""))
    product_name = normalize_identity_text(candidate.get("product-name", ""))
    console_name = normalize_identity_text(candidate.get("console-name", ""))
    combined = f"{product_name} {console_name}".strip()
    score = Decimal("0")
    possible = Decimal("0")
    explanation = []

    checks = (
        ("card_name", identity.card_name, Decimal("40"), _contains_words(identity.card_name, product_name)),
        ("set", identity.set, Decimal("20"), _contains_words(identity.set, combined)),
        (
            "card_number",
            identity.card_number,
            Decimal("30"),
            _candidate_number_matches(identity.card_number or "", str(candidate.get("product-name", ""))),
        ),
    )
    for label, expected, weight, matched in checks:
        if not expected:
            continue
        possible += weight
        if matched:
            score += weight
            explanation.append(f"{label}:match")
        else:
            explanation.append(f"{label}:no_match")

    release_date = str(candidate.get("release-date", ""))
    if identity.year and release_date:
        possible += Decimal("5")
        matched = release_date.startswith(str(identity.year))
        if matched:
            score += Decimal("5")
        explanation.append(f"year:{'match' if matched else 'no_match'}")
    normalized_language = normalize_identity_text(identity.language)
    if normalized_language:
        foreign_markers = {
            "japanese",
            "japonais",
            "french",
            "francais",
            "german",
            "deutsch",
            "italian",
            "spanish",
            "korean",
            "chinese",
        }
        if normalized_language in combined:
            possible += Decimal("5")
            score += Decimal("5")
            explanation.append("language:match")
        elif normalized_language not in {"english", "anglais"} or any(
            marker in combined for marker in foreign_markers
        ):
            possible += Decimal("5")
            explanation.append("language:no_match")
        else:
            explanation.append("language:unverified")

    if identity.variant:
        possible += Decimal("5")
        if _contains_words(identity.variant, combined):
            score += Decimal("5")
            explanation.append("variant:match")
        else:
            explanation.append("variant:no_match")

    normalized_score = score / possible if possible else Decimal("0")
    if not product_id:
        normalized_score = Decimal("0")
        explanation.append("product_id:missing")
    return CandidateMatch(product_id, normalized_score, tuple(explanation))


def _pennies(payload: Mapping[str, object], key: str) -> Optional[Decimal]:
    raw = payload.get(key)
    if raw is None or raw == "":
        return None
    try:
        pennies = Decimal(str(raw))
    except InvalidOperation:
        return None
    if pennies < 0:
        return None
    return pennies / Decimal("100")


def market_values_from_product(
    payload: Mapping[str, object],
    identity: CardIdentity,
    match_confidence: Decimal,
    explanation: Tuple[str, ...] = (),
) -> MarketValues:
    """Mappe exactement les quatre cles cartes documentees par PriceCharting."""

    return MarketValues(
        source="PriceCharting official Prices API",
        currency="USD",
        ungraded_value=_pennies(payload, "loose-price"),
        grade8_generic_value=_pennies(payload, "new-price"),
        grade9_generic_value=_pennies(payload, "graded-price"),
        psa10_value=_pennies(payload, "manual-only-price"),
        matched_identity=identity,
        match_confidence=match_confidence,
        matched_product_id=str(payload.get("id", "")) or None,
        fetched_at=datetime.now(timezone.utc),
        freshness=None,
        notes=explanation,
        limitations=(
            "GRADE8_GENERIC is not PSA8",
            "GRADE9_GENERIC is not PSA9",
            "Current guide values; no historic sales returned by this endpoint",
        ),
    )
