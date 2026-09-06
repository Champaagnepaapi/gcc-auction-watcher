from __future__ import annotations

import os
import re
import time
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping, Optional, Sequence

import requests

import watcher


PRICECHARTING_BASE_URL = "https://www.pricecharting.com"
PRICECHARTING_SOURCE = "pricecharting"
_INSTALL_MARKER = "_v4_pricecharting_source_roles_installed"


@dataclass(frozen=True)
class PriceChartingConfig:
    enabled: bool = True
    token: Optional[str] = field(default=None, repr=False)
    timeout_seconds: float = 10.0
    max_cards_per_run: int = 8
    minimum_match_score: Decimal = Decimal("0.72")
    minimum_match_margin: Decimal = Decimal("0.08")
    minimum_request_interval_seconds: float = 1.05

    @classmethod
    def from_env(cls) -> "PriceChartingConfig":
        return cls(
            enabled=os.getenv("PRICECHARTING_ENABLED", "true").strip().casefold()
            == "true",
            token=os.getenv("PRICECHARTING_TOKEN", "").strip() or None,
            timeout_seconds=max(
                1.0, float(os.getenv("PRICECHARTING_TIMEOUT_SECONDS", "10"))
            ),
            max_cards_per_run=max(
                0, int(os.getenv("PRICECHARTING_MAX_CARDS_PER_RUN", "8"))
            ),
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
    explanation: tuple[str, ...]


@dataclass(frozen=True)
class PriceChartingLookup:
    status: str
    product_id: str = ""
    value_usd: Optional[float] = None
    exact_grade_bucket: bool = False
    note: str = ""


class PriceChartingProvider:
    """Bounded read-only PriceCharting Prices API adapter for V4.

    This is a port of the already-reviewed V5 provider shape, kept physically
    separate from V5. The official Prices API returns current guide values, not
    historic item-level SOLD rows. V4 therefore never labels these values SOLD.

    PriceCharting documents `manual-only-price` for cards as PSA 10. Its grade-9
    and grade-8 buckets are generic across grading companies, so only the PSA 10
    bucket can become automatic V4 fair-value evidence. Other buckets remain
    weak/context-only.
    """

    def __init__(
        self,
        config: Optional[PriceChartingConfig] = None,
        session=None,
    ) -> None:
        self.config = config or PriceChartingConfig.from_env()
        self.session = session or requests.Session()
        self.cards_attempted = 0
        self._last_request_started: Optional[float] = None

    def lookup(self, lot: watcher.Lot) -> PriceChartingLookup:
        if not self.config.enabled:
            return PriceChartingLookup("DISABLED", note="PriceCharting désactivé")
        if not self.config.token:
            return PriceChartingLookup(
                "UNAVAILABLE", note="PriceCharting token absent"
            )
        if self.cards_attempted >= self.config.max_cards_per_run:
            return PriceChartingLookup(
                "PENDING_BUDGET", note="budget PriceCharting épuisé"
            )

        price_key, exact_grade_bucket = _price_key_for_lot(lot)
        if not price_key:
            return PriceChartingLookup(
                "CLEAN_INSUFFICIENT",
                note="grade non mappable sans mélange de grader/grade",
            )

        self.cards_attempted += 1
        identity = watcher.extract_card_identity(lot)
        query = " ".join(
            part
            for part in (
                str(identity.get("core") or lot.title or "").strip(),
                str(lot.card_number or identity.get("ref") or "").strip(),
                str(lot.card_set or identity.get("series") or "").strip(),
            )
            if part
        )
        if not query:
            return PriceChartingLookup(
                "CLEAN_NO_MATCH", note="identité PriceCharting insuffisante"
            )

        try:
            search = self._request("/api/products", {"q": query})
        except RuntimeError as error:
            return PriceChartingLookup("PROVIDER_ERROR", note=str(error))

        raw_candidates = search.get("products")
        candidates = (
            tuple(item for item in raw_candidates if isinstance(item, Mapping))
            if isinstance(raw_candidates, Sequence)
            and not isinstance(raw_candidates, (str, bytes))
            else ()
        )
        matches = tuple(
            sorted(
                (_score_candidate(lot, item) for item in candidates),
                key=lambda item: item.score,
                reverse=True,
            )
        )
        if not matches or matches[0].score < self.config.minimum_match_score:
            return PriceChartingLookup(
                "CLEAN_NO_MATCH",
                note="aucun produit PriceCharting assez exact",
            )
        if len(matches) > 1 and (
            matches[0].score - matches[1].score < self.config.minimum_match_margin
        ):
            return PriceChartingLookup(
                "AMBIGUOUS", note="résultats PriceCharting ambigus"
            )

        selected = matches[0]
        try:
            product = self._request("/api/product", {"id": selected.product_id})
        except RuntimeError as error:
            return PriceChartingLookup("PROVIDER_ERROR", note=str(error))
        if str(product.get("id") or "") != selected.product_id:
            return PriceChartingLookup(
                "CLEAN_NO_MATCH", note="product id PriceCharting incohérent"
            )
        detail_match = _score_candidate(lot, product)
        if detail_match.score < self.config.minimum_match_score:
            return PriceChartingLookup(
                "CLEAN_NO_MATCH", note="identité détail PriceCharting non prouvée"
            )

        value = _pennies(product, price_key)
        if value is None or value <= 0:
            return PriceChartingLookup(
                "CLEAN_INSUFFICIENT",
                product_id=selected.product_id,
                note=f"guide {price_key} absent",
            )
        bucket = "PSA 10" if exact_grade_bucket else "grade générique"
        return PriceChartingLookup(
            "MATCHED",
            product_id=selected.product_id,
            value_usd=value,
            exact_grade_bucket=exact_grade_bucket,
            note=(
                f"PriceCharting Prices API {bucket}; guide courant dérivé du marché, "
                "pas une vente item-level"
            ),
        )

    def _request(self, path: str, parameters: Mapping[str, str]) -> Mapping[str, object]:
        self._respect_rate_limit()
        safe_parameters = dict(parameters)
        safe_parameters["t"] = self.config.token or ""
        try:
            response = self.session.get(
                f"{PRICECHARTING_BASE_URL}{path}",
                params=safe_parameters,
                timeout=self.config.timeout_seconds,
            )
        except Exception:
            raise RuntimeError("PriceCharting réseau indisponible") from None
        status_code = getattr(response, "status_code", None)
        if status_code != 200:
            raise RuntimeError(f"PriceCharting HTTP {status_code}")
        try:
            payload = response.json()
        except Exception:
            raise RuntimeError("PriceCharting JSON invalide") from None
        if not isinstance(payload, Mapping) or payload.get("status") != "success":
            raise RuntimeError("PriceCharting réponse en erreur")
        return payload

    def _respect_rate_limit(self) -> None:
        now = time.monotonic()
        if self._last_request_started is not None:
            elapsed = now - self._last_request_started
            remaining = self.config.minimum_request_interval_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)
                now = time.monotonic()
        self._last_request_started = now


def _normalize(value: object) -> str:
    plain = unicodedata.normalize("NFKD", str(value or ""))
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", plain.casefold()).strip()


def _compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", _normalize(value))


def _contains_words(needle: object, haystack: str) -> bool:
    words = tuple(_normalize(needle).split())
    return bool(words) and all(word in haystack.split() for word in words)


def _number_matches(reference: str, candidate_text: str) -> bool:
    full = _compact(reference)
    compact_candidate = _compact(candidate_text)
    if full and full in compact_candidate:
        return True
    numerator = _compact(reference.split("/", 1)[0])
    return bool(
        numerator
        and re.search(rf"#\s*0*{re.escape(numerator)}\b", candidate_text, re.I)
    )


def _score_candidate(lot: watcher.Lot, candidate: Mapping[str, object]) -> CandidateMatch:
    identity = watcher.extract_card_identity(lot)
    product_id = str(candidate.get("id") or "")
    product_name_raw = str(candidate.get("product-name") or "")
    product_name = _normalize(product_name_raw)
    console_name = _normalize(candidate.get("console-name") or "")
    combined = f"{product_name} {console_name}".strip()
    expected_name = str(identity.get("core") or lot.title or "").strip()
    expected_set = str(lot.card_set or identity.get("series") or "").strip()
    expected_number = str(lot.card_number or identity.get("ref") or "").strip()
    expected_language = _normalize(lot.language or identity.get("language") or "")

    score = Decimal("0")
    possible = Decimal("0")
    explanation: list[str] = []
    checks = (
        ("name", expected_name, Decimal("40"), _contains_words(expected_name, product_name)),
        ("set", expected_set, Decimal("20"), _contains_words(expected_set, combined)),
        (
            "number",
            expected_number,
            Decimal("30"),
            _number_matches(expected_number, product_name_raw) if expected_number else False,
        ),
    )
    for label, expected, weight, matched in checks:
        if not expected:
            continue
        possible += weight
        if matched:
            score += weight
        explanation.append(f"{label}:{'match' if matched else 'no_match'}")

    if expected_language:
        aliases = {
            "japanese": ("japanese", "japonais"),
            "japonais": ("japanese", "japonais"),
            "french": ("french", "francais"),
            "francais": ("french", "francais"),
            "german": ("german", "deutsch"),
            "english": ("english",),
            "anglais": ("english",),
        }.get(expected_language, (expected_language,))
        foreign_markers = (
            "japanese", "japonais", "french", "francais", "german", "deutsch",
            "italian", "spanish", "korean", "chinese",
        )
        if any(alias in combined for alias in aliases):
            possible += Decimal("10")
            score += Decimal("10")
            explanation.append("language:match")
        elif expected_language not in {"english", "anglais"} or any(
            marker in combined for marker in foreign_markers
        ):
            possible += Decimal("10")
            explanation.append("language:no_match")
        else:
            explanation.append("language:unverified")

    normalized = score / possible if possible else Decimal("0")
    if not product_id:
        normalized = Decimal("0")
        explanation.append("product_id:missing")
    return CandidateMatch(product_id, normalized, tuple(explanation))


def _pennies(payload: Mapping[str, object], key: str) -> Optional[float]:
    raw = payload.get(key)
    if raw in {None, ""}:
        return None
    try:
        pennies = Decimal(str(raw))
    except InvalidOperation:
        return None
    if pennies <= 0:
        return None
    return float(pennies / Decimal("100"))


def _price_key_for_lot(lot: watcher.Lot) -> tuple[str, bool]:
    try:
        grade = float(lot.grade) if lot.grade is not None else None
    except (TypeError, ValueError):
        return "", False
    grader = str(lot.grader or "").strip().upper()
    if grader == "PSA" and grade == 10.0:
        return "manual-only-price", True
    if grade == 9.0:
        return "graded-price", False
    if grade in {8.0, 8.5}:
        return "new-price", False
    return "", False


def _evidence_from_lookup(
    lot: watcher.Lot,
    lookup: PriceChartingLookup,
    *,
    now: datetime,
) -> watcher.ExternalMarketEvidence:
    key = watcher.external_commercial_identity_key(lot)
    if lookup.status == "PENDING_BUDGET":
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_PENDING,
            source=PRICECHARTING_SOURCE,
            note=lookup.note,
            fetched_at=now,
        )
    if lookup.status in {"PROVIDER_ERROR", "UNAVAILABLE", "DISABLED"}:
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
            source=PRICECHARTING_SOURCE,
            note=lookup.note,
            fetched_at=now,
        )
    if lookup.status in {"CLEAN_NO_MATCH", "AMBIGUOUS"}:
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_CLEAN_NO_MATCH,
            source=PRICECHARTING_SOURCE,
            note=lookup.note,
            fetched_at=now,
        )
    if lookup.value_usd is None or lookup.value_usd <= 0:
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_CLEAN_INSUFFICIENT,
            watcher.EVIDENCE_WEAK,
            PRICECHARTING_SOURCE,
            note=lookup.note,
            fetched_at=now,
        )

    usd_per_eur = watcher.get_psa_apr_usd_per_eur()
    if usd_per_eur is None or usd_per_eur <= 0:
        return watcher.ExternalMarketEvidence(
            key,
            watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
            source=PRICECHARTING_SOURCE,
            note="PriceCharting USD/EUR indisponible",
            fetched_at=now,
        )
    central = float(lookup.value_usd) / float(usd_per_eur)
    exact = bool(lookup.exact_grade_bucket)
    threshold = max(float(watcher.MIN_DISCOUNT), 40.0 if exact else 50.0)
    estimate = watcher.MarketEstimate(
        low=central,
        central=central,
        high=central,
        kept_comparables=[],
        rejected_outliers=[],
        recent_90_count=0,
        dated_count=0,
        liquidity="non mesurée",
        dispersion="guide ponctuel",
        confidence="moyenne" if exact else "faible",
        adaptive_discount_pct=threshold,
        rationale=(
            "PriceCharting official Prices API: guide courant PSA 10 exact; "
            "aucune vente item-level fabriquée"
            if exact
            else "PriceCharting guide générique de grade; contexte uniquement"
        ),
        source_counts={"pricecharting_guide": 1},
        exact_grade_count=0,
        same_grader_count=0,
        source_consistent=True,
        grade_arbitrage=False,
    )
    return watcher.ExternalMarketEvidence(
        key,
        watcher.EXTERNAL_MATCHED,
        watcher.EVIDENCE_STRONG if exact else watcher.EVIDENCE_WEAK,
        PRICECHARTING_SOURCE,
        estimate=estimate,
        comparables=[],
        note=(f"{lookup.note}; product_id={lookup.product_id}" if lookup.product_id else lookup.note),
        fetched_at=now,
    )


_PROVIDER: Optional[PriceChartingProvider] = None


def pricecharting_evidence_for_lot(
    lot: watcher.Lot,
    *,
    now: Optional[datetime] = None,
    provider: Optional[PriceChartingProvider] = None,
) -> watcher.ExternalMarketEvidence:
    global _PROVIDER
    if provider is None:
        if _PROVIDER is None:
            _PROVIDER = PriceChartingProvider()
        provider = _PROVIDER
    effective_now = now or datetime.now(timezone.utc)
    return _evidence_from_lookup(lot, provider.lookup(lot), now=effective_now)


def install_v4_pricecharting_valuation_source_roles() -> None:
    """Keep opportunity marketplaces separate from V4 fair-value providers.

    PokeTrace is evaluated before this fallback by the canonical multimarket
    layer. Here PSA APR remains the first exact fallback. Direct eBay SOLD scraping
    is deliberately disabled for economic valuation: eBay is reserved for a
    future active-listing opportunity scanner. PriceCharting then supplies a
    bounded valuation fallback. Only its documented PSA 10 bucket can become
    automatic strong evidence; generic grade buckets remain weak.
    """

    current = watcher.fetch_external_market_evidence
    if getattr(current, _INSTALL_MARKER, False):
        return

    def source_role_fetch(page, candidate, budgets, diagnostics, now):
        previous_ebay = watcher.EBAY_ENABLED
        watcher.EBAY_ENABLED = False
        try:
            apr_or_unavailable = current(
                page, candidate, budgets, diagnostics, now
            )
        finally:
            watcher.EBAY_ENABLED = previous_ebay

        if (
            apr_or_unavailable.source == "psa"
            and apr_or_unavailable.status == watcher.EXTERNAL_MATCHED
            and apr_or_unavailable.strength == watcher.EVIDENCE_STRONG
            and apr_or_unavailable.estimate is not None
        ):
            return apr_or_unavailable

        pc = pricecharting_evidence_for_lot(candidate.lot, now=now)
        if (
            pc.status == watcher.EXTERNAL_MATCHED
            and pc.strength == watcher.EVIDENCE_STRONG
            and pc.estimate is not None
        ):
            if apr_or_unavailable.note:
                pc = replace(
                    pc,
                    note=f"{pc.note}; APR: {apr_or_unavailable.note}",
                )
            return pc

        if pc.status in {
            watcher.EXTERNAL_PENDING,
            *watcher.EXTERNAL_RETRY_STATUSES,
        }:
            return replace(
                apr_or_unavailable,
                note=(
                    f"{apr_or_unavailable.note}; PriceCharting: {pc.note}; "
                    "eBay direct réservé au scan d'offres, pas à la fair value"
                ).strip("; "),
            )
        return replace(
            pc,
            note=(
                f"{pc.note}; APR: {apr_or_unavailable.note}; "
                "eBay direct réservé au scan d'offres, pas à la fair value"
            ).strip("; "),
        )

    setattr(source_role_fetch, _INSTALL_MARKER, True)
    setattr(source_role_fetch, "_wrapped_fetch", current)
    watcher.fetch_external_market_evidence = source_role_fetch
    watcher.log(
        "Valuation source roles: PokeTrace -> PSA APR -> PriceCharting; "
        "direct eBay SOLD removed from fair-value authority"
    )
