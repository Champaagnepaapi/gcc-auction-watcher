from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from email.header import Header
from pathlib import Path
from statistics import median
from typing import Optional
from urllib.parse import quote_plus, urljoin

import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv()

BASE = "https://gradedcardcenter.com"
FIXED_PRICE_URL = 'https://gradedcardcenter.com/filtres?sellingTypes=%5B%22FIXED_PRICE%22%5D'

MIN_PRICE = 10.0
MAX_PRICE = float(os.getenv("MAX_PRICE_EUR", "100"))
MIN_DISCOUNT = float(os.getenv("MIN_DISCOUNT_PCT", "30"))
MAX_AUCTION_MINUTES = int(os.getenv("MAX_AUCTION_MINUTES", "60"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()

# eBay public "Sold / Completed" search (no Developer API needed)
EBAY_ENABLED = os.getenv("EBAY_ENABLED", "true").lower() == "true"
EBAY_BASE = "https://www.ebay.fr"
EBAY_MIN_COMPS = int(os.getenv("EBAY_MIN_COMPS", "2"))
EBAY_MAX_RESULTS = int(os.getenv("EBAY_MAX_RESULTS", "20"))
EBAY_MAX_QUERIES_PER_CARD = int(
    os.getenv("EBAY_MAX_QUERIES_PER_CARD", os.getenv("EBAY_MAX_QUERIES", "2"))
)
EBAY_MAX_CARDS_PER_RUN = int(os.getenv("EBAY_MAX_CARDS_PER_RUN", "2"))
EBAY_PAGE_WAIT_MS = int(os.getenv("EBAY_PAGE_WAIT_MS", "700"))
EBAY_NAV_TIMEOUT = int(os.getenv("EBAY_NAV_TIMEOUT", "6000"))

# PSA Auction Prices Realized public search (PSA-graded cards only)
PSA_APR_ENABLED = os.getenv("PSA_APR_ENABLED", "true").lower() == "true"
PSA_APR_BASE = "https://www.psacard.com"
PSA_APR_SEARCH_URL = f"{PSA_APR_BASE}/auctionprices"
PSA_APR_MIN_COMPS = int(os.getenv("PSA_APR_MIN_COMPS", "2"))
PSA_APR_MAX_CARDS_PER_RUN = int(os.getenv("PSA_APR_MAX_CARDS_PER_RUN", "2"))
PSA_APR_MAX_RESULTS = int(os.getenv("PSA_APR_MAX_RESULTS", "20"))
PSA_APR_NAV_TIMEOUT = int(os.getenv("PSA_APR_NAV_TIMEOUT", "6000"))
PSA_APR_USD_PER_EUR_FALLBACK = os.getenv(
    "PSA_APR_USD_PER_EUR_FALLBACK", ""
).strip()
ECB_DAILY_RATES_URL = (
    "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
)
PSA_APR_MATCH_MIN_SCORE = 75
MIN_EMPIRICAL_GRADER_RATIO_SALES = int(
    os.getenv("MIN_EMPIRICAL_GRADER_RATIO_SALES", "10")
)

NAV_TIMEOUT = 15000
TEXT_TIMEOUT = 3000
MAX_SCAN_SECONDS = 300
MAX_AUCTION_CANDIDATES = 120
MAX_FIXED_CANDIDATES = 120

MONEY_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:['’\s]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*€",
    re.I,
)
EBAY_MONEY_RE = re.compile(
    r"(?<!\d)(\d[\d\s\u00a0.,']*)\s*(?:EUR|€)\b",
    re.I,
)
HREF_ITEM_RE = re.compile(r"/item/[0-9a-f-]{20,}", re.I)

SEALED_KEYWORDS = (
    "booster", "pack", "display", "box", "coffret", "blister", "bundle",
    "elite trainer", "etb", "deck", "tin", "case", "scellé", "sealed",
    "collection box", "trainer box", "tripack", "3-pack", "duopack",
)

GRADERS = ("PSA", "PCA", "CGC", "BGS", "BECKETT", "CCC", "CA", "PG")
VALID_COMPARABLE_SOURCES = frozenset({"gcc", "ebay", "psa"})
LOGGED_INVALID_GRADES: set[str] = set()


@dataclass
class Lot:
    url: str
    title: str
    current_price: Optional[float]
    source_type: str
    sale_name: str = ""
    end_text: str = ""
    minutes_to_end: Optional[int] = None
    body: str = ""
    grader: str = ""
    grade: Optional[str] = None
    listing_text: str = ""
    page_title_raw: str = ""


@dataclass
class ComparableSale:
    """Format commun aux ventes GCC, eBay et aux futures sources (PSA APR)."""

    price: float
    source: str = "gcc"
    grader: str = ""
    grade: Optional[float] = None
    sold_at: Optional[datetime] = None
    context: str = ""
    exact_card: bool = True
    match_score: int = 100


# Alias conservé pour les intégrations qui importeraient encore l'ancien nom.
HistoricalSale = ComparableSale


@dataclass(frozen=True)
class EmpiricalGraderRatio:
    """Ratio futur mesuré: valeur grader cible / valeur grader source."""

    source_grader: str
    target_grader: str
    grade: float
    target_per_source_ratio: float
    sample_size: int
    sources: tuple[str, ...]
    measured_at: datetime


@dataclass
class ComparableSelection:
    primary: list[ComparableSale]
    lower_bounds: list[ComparableSale]
    upper_bounds: list[ComparableSale]
    secondary: list[ComparableSale]
    rationale: str
    grade_arbitrage: bool = False
    arbitrage_reference_grade: Optional[float] = None
    arbitrage_reference_value: Optional[float] = None
    depends_on_other_graders: bool = False


@dataclass
class MarketEstimate:
    low: float
    central: float
    high: float
    kept_comparables: list[ComparableSale]
    rejected_outliers: list[ComparableSale]
    recent_90_count: int
    dated_count: int
    liquidity: str
    dispersion: str
    confidence: str
    adaptive_discount_pct: float
    rationale: str
    source_counts: dict[str, int]
    exact_grade_count: int
    same_grader_count: int
    source_consistent: Optional[bool] = None
    grade_arbitrage: bool = False
    arbitrage_reference_grade: Optional[float] = None
    arbitrage_reference_value: Optional[float] = None


@dataclass
class Opportunity:
    lot: Lot
    estimate: MarketEstimate
    discount_pct: float
    max_recommended: float
    gcc_comparables: list[ComparableSale]
    ebay_comparables: list[ComparableSale]
    ebay_note: str = ""
    psa_apr_comparables: list[ComparableSale] = field(default_factory=list)
    psa_apr_estimate: Optional[MarketEstimate] = None
    psa_apr_note: str = ""
    psa_apr_population: Optional[int] = None
    psa_apr_pop_higher: Optional[int] = None
    psa_apr_most_recent_price: Optional[float] = None

    @property
    def estimated_market(self) -> float:
        return self.estimate.central

    @property
    def confidence(self) -> str:
        return self.estimate.confidence

    @property
    def rationale(self) -> str:
        return self.estimate.rationale

    @property
    def grade_arbitrage(self) -> bool:
        return self.estimate.grade_arbitrage


@dataclass
class NotificationDecision:
    should_notify: bool
    final_alert: bool = False
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PsaAprCandidate:
    url: str
    text: str


@dataclass
class PsaAprData:
    sales: list[ComparableSale]
    population: Optional[int] = None
    pop_higher: Optional[int] = None
    most_recent_price: Optional[float] = None
    matched_url: str = ""
    match_score: int = 0
    note: str = ""


@dataclass
class PsaAprValidationResult:
    opportunity: Optional[Opportunity]
    sufficient: bool


@dataclass
class ValidationBudgets:
    psa_apr_cards: int = 0
    ebay_cards: int = 0


REJECTION_GRADER_GRADE = "grader_grade_unreadable"
REJECTION_SPECIAL_QUALIFIER = "special_qualifier_excluded"
REJECTION_EMPTY_HISTORY = "empty_history"
REJECTION_INSUFFICIENT_COMPARABLES = "insufficient_comparables"
REJECTION_INSUFFICIENT_IDENTITY = "insufficient_identity"
REJECTION_INSUFFICIENT_DISCOUNT = "insufficient_discount"
REJECTION_FIXED_ABOVE_MAX = "fixed_above_prudent_max"
REJECTION_OTHER = "other"


@dataclass
class GccComparableDiagnostics:
    raw_count: int = 0
    identity_count: int = 0
    same_grader_count: int = 0
    exact_grade_count: int = 0
    lower_grade_count: int = 0
    higher_grade_count: int = 0
    nearest_neighbor_count: int = 0
    inter_grader_candidates: int = 0
    normalized_count: int = 0
    invalid_grader_count: int = 0
    invalid_grade_count: int = 0
    insufficient_identity_count: int = 0
    ratio_rejected_count: int = 0
    outlier_count: int = 0
    kept_count: int = 0
    dated_count: int = 0
    under_30_days_count: int = 0
    days_30_to_90_count: int = 0
    over_90_days_count: int = 0
    grade_arbitrage: bool = False


GRADE_UNREADABLE_GRADER_ABSENT = "grader absent"
GRADE_UNREADABLE_GRADE_ABSENT = "grader reconnu mais grade absent"
GRADE_UNREADABLE_GRADE_INVALID = "grade présent mais invalide"
GRADE_UNREADABLE_CONFLICT = "conflit entre plusieurs valeurs"
GRADE_UNREADABLE_AMBIGUOUS = "parsing ambigu"
GRADE_UNREADABLE_OTHER = "autre"
GRADE_SPECIAL_QUALIFIER = "qualifier spécial exclu"


@dataclass(frozen=True)
class GradeUnreadableDiagnostic:
    title: str
    url: str
    price: Optional[float]
    source_type: str
    extracted_grader: str
    extracted_grade: Optional[str]
    page_title_raw: str
    grading_block_raw: str
    label_contexts: tuple[tuple[str, str], ...]
    raw_excerpt: str
    reason: str
    observed_graders: tuple[str, ...] = ()
    observed_grades: tuple[str, ...] = ()
    special_qualifier: str = ""


@dataclass
class RunDiagnostics:
    fixed_candidates: int = 0
    auction_candidates_ending_soon: int = 0
    live_auction_urls: set[str] = field(default_factory=set)
    ending_soon_sale_urls: set[str] = field(default_factory=set)
    cards_in_ending_sales: set[str] = field(default_factory=set)
    valuation_outcomes: dict[str, str] = field(default_factory=dict)
    valuation_sources: dict[str, str] = field(default_factory=dict)
    external_rejections: set[str] = field(default_factory=set)
    unreadable_grade_lots: dict[str, GradeUnreadableDiagnostic] = field(
        default_factory=dict
    )
    special_qualifier_lots: dict[str, GradeUnreadableDiagnostic] = field(
        default_factory=dict
    )
    final_opportunities: int = 0

    def record_live_sales(self, urls: list[str]) -> None:
        self.live_auction_urls.update(urls)

    def record_ending_sale(self, url: str, lots: list[Lot]) -> None:
        self.ending_soon_sale_urls.add(url)
        self.cards_in_ending_sales.update(lot.url for lot in lots)

    def record_valuation(self, lot: Lot, rejection: str = "") -> None:
        key = lot.url or f"{lot.source_type}:{lot.title}"
        if key in self.valuation_outcomes:
            return
        self.valuation_outcomes[key] = rejection
        self.valuation_sources[key] = lot.source_type

    def record_external_rejection(self, lot: Lot) -> None:
        self.external_rejections.add(lot.url or f"{lot.source_type}:{lot.title}")

    def record_unreadable_grade(
        self, lot: Lot, diagnostic: GradeUnreadableDiagnostic
    ) -> None:
        key = lot.url or f"{lot.source_type}:{lot.title}"
        self.unreadable_grade_lots.setdefault(key, diagnostic)

    def record_special_qualifier(
        self, lot: Lot, diagnostic: GradeUnreadableDiagnostic
    ) -> None:
        key = lot.url or f"{lot.source_type}:{lot.title}"
        self.special_qualifier_lots.setdefault(key, diagnostic)

    @property
    def lots_analyzed(self) -> int:
        return len(self.valuation_outcomes)

    @property
    def auction_lots_analyzed(self) -> int:
        return sum(source == "auction" for source in self.valuation_sources.values())

    @property
    def gcc_opportunities(self) -> int:
        return sum(not rejection for rejection in self.valuation_outcomes.values())

    def rejection_count(self, reason: str) -> int:
        return sum(value == reason for value in self.valuation_outcomes.values())

    @property
    def rejected_total(self) -> int:
        return sum(bool(value) for value in self.valuation_outcomes.values())

    @property
    def is_coherent(self) -> bool:
        return self.lots_analyzed == self.rejected_total + self.gcc_opportunities


_PSA_APR_RATE_LOOKUP_DONE = False
_PSA_APR_USD_PER_EUR: Optional[float] = None


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_state() -> dict:
    state = None
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            log(f"État illisible ({STATE_FILE}), nouvel état initialisé")

    # Compatibilité avec les anciens state.json: leurs champs sont conservés et
    # les nouvelles sections sont ajoutées sans migration destructive.
    if not isinstance(state, dict):
        state = {}
    if not isinstance(state.get("notified"), dict):
        state["notified"] = {}
    if not isinstance(state.get("seen"), dict):
        state["seen"] = {}
    state["schema_version"] = 2
    return state


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalize_money(raw: str) -> float:
    clean = (
        raw.replace("'", "")
        .replace("’", "")
        .replace("\u00a0", "")
        .replace(" ", "")
        .replace(",", ".")
    )
    return float(clean)


def parse_money(text: str) -> Optional[float]:
    vals = []
    for m in MONEY_RE.findall(text or ""):
        try:
            vals.append(normalize_money(m))
        except ValueError:
            pass
    return vals[0] if vals else None


def parse_ecb_usd_per_eur(xml_text: str) -> Optional[float]:
    """Lit le taux ECB coté comme nombre de dollars pour un euro."""
    try:
        root = ET.fromstring(xml_text or "")
    except ET.ParseError:
        return None
    for element in root.iter():
        if element.attrib.get("currency", "").upper() != "USD":
            continue
        try:
            rate = float(element.attrib.get("rate", ""))
        except (TypeError, ValueError):
            return None
        return rate if rate > 0 else None
    return None


def _configured_usd_per_eur_fallback() -> Optional[float]:
    try:
        rate = float(PSA_APR_USD_PER_EUR_FALLBACK.replace(",", "."))
    except (AttributeError, TypeError, ValueError):
        return None
    return rate if rate > 0 else None


def get_psa_apr_usd_per_eur(http_get=None) -> Optional[float]:
    """Récupère le taux ECB une seule fois par processus/run, puis le met en cache."""
    global _PSA_APR_RATE_LOOKUP_DONE, _PSA_APR_USD_PER_EUR
    if _PSA_APR_RATE_LOOKUP_DONE:
        return _PSA_APR_USD_PER_EUR

    _PSA_APR_RATE_LOOKUP_DONE = True
    try:
        getter = http_get or getattr(requests, "get", None)
        if getter is None:
            raise RuntimeError("client HTTP indisponible")
        response = getter(
            ECB_DAILY_RATES_URL,
            timeout=max(1.0, min(6.0, PSA_APR_NAV_TIMEOUT / 1000)),
        )
        response.raise_for_status()
        _PSA_APR_USD_PER_EUR = parse_ecb_usd_per_eur(response.text)
    except Exception:
        _PSA_APR_USD_PER_EUR = None

    if _PSA_APR_USD_PER_EUR is None:
        _PSA_APR_USD_PER_EUR = _configured_usd_per_eur_fallback()
    if _PSA_APR_USD_PER_EUR is None:
        log("PSA APR: conversion USD/EUR indisponible -> validation APR ignorée")
    return _PSA_APR_USD_PER_EUR


def usd_to_eur(price_usd: float, usd_per_eur: float) -> float:
    if price_usd <= 0 or usd_per_eur <= 0:
        raise ValueError("prix USD et taux USD/EUR doivent être positifs")
    return round(price_usd / usd_per_eur, 2)


def parse_psa_apr_usd(raw: str) -> Optional[float]:
    match = re.search(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", raw or "")
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


MONTH_NUMBERS = {
    "janvier": 1, "january": 1, "jan": 1,
    "fevrier": 2, "february": 2, "feb": 2,
    "mars": 3, "march": 3, "mar": 3,
    "avril": 4, "april": 4, "apr": 4,
    "mai": 5, "may": 5,
    "juin": 6, "june": 6, "jun": 6,
    "juillet": 7, "july": 7, "jul": 7,
    "aout": 8, "august": 8, "aug": 8,
    "septembre": 9, "september": 9, "sept": 9, "sep": 9,
    "octobre": 10, "october": 10, "oct": 10,
    "novembre": 11, "november": 11, "nov": 11,
    "decembre": 12, "december": 12, "dec": 12,
}


def _plain_text(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def parse_sale_date(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """Extrait les formats de date courants observés chez GCC/eBay."""
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    plain = _plain_text(text)

    relative_patterns = (
        (r"(?:il y a\s*)?(\d+)\s*(?:jours?|days?)(?:\s*ago)?", 1),
        (r"(?:il y a\s*)?(\d+)\s*(?:semaines?|weeks?)(?:\s*ago)?", 7),
        (r"(?:il y a\s*)?(\d+)\s*(?:mois|months?)(?:\s*ago)?", 30),
        (r"(?:il y a\s*)?(\d+)\s*(?:ans?|years?)(?:\s*ago)?", 365),
    )
    for pattern, multiplier in relative_patterns:
        match = re.search(pattern, plain, re.I)
        if match:
            return reference - timedelta(days=int(match.group(1)) * multiplier)

    numeric_patterns = (
        (r"\b(20\d{2}|19\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", "ymd"),
        (r"\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2}|19\d{2})\b", "dmy"),
    )
    for pattern, order in numeric_patterns:
        match = re.search(pattern, plain)
        if not match:
            continue
        parts = [int(value) for value in match.groups()]
        year, month, day = parts if order == "ymd" else (parts[2], parts[1], parts[0])
        try:
            result = datetime(year, month, day, tzinfo=timezone.utc)
            return result if result <= reference + timedelta(days=1) else None
        except ValueError:
            continue

    month_names = "|".join(sorted(MONTH_NUMBERS, key=len, reverse=True))
    patterns = (
        rf"\b(\d{{1,2}})\s+({month_names})\s+(20\d{{2}}|19\d{{2}})\b",
        rf"\b({month_names})\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(20\d{{2}}|19\d{{2}})\b",
    )
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, plain, re.I)
        if not match:
            continue
        if index == 0:
            day, month_name, year = match.groups()
        else:
            month_name, day, year = match.groups()
        try:
            result = datetime(
                int(year), MONTH_NUMBERS[month_name.lower()], int(day), tzinfo=timezone.utc
            )
            return result if result <= reference + timedelta(days=1) else None
        except (KeyError, ValueError):
            continue

    return None


def sale_age_days(sale: ComparableSale, now: Optional[datetime] = None) -> Optional[float]:
    if sale.sold_at is None:
        return None
    reference = now or datetime.now(timezone.utc)
    sold_at = sale.sold_at
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    if sold_at.tzinfo is None:
        sold_at = sold_at.replace(tzinfo=timezone.utc)
    return max(0.0, (reference - sold_at).total_seconds() / 86400)


def recency_weight(sold_at: Optional[datetime], now: Optional[datetime] = None) -> float:
    """Pondération progressive: 1,00 (<30j), 0,70 (90j), 0,40 (180j), 0,20 (365j)."""
    if sold_at is None:
        return 0.45
    age = sale_age_days(ComparableSale(price=1, sold_at=sold_at), now)
    if age is None or age <= 30:
        return 1.0
    if age <= 90:
        return 1.0 - (age - 30) * (0.30 / 60)
    if age <= 180:
        return 0.70 - (age - 90) * (0.30 / 90)
    if age <= 365:
        return 0.40 - (age - 180) * (0.20 / 185)
    return max(0.10, 0.20 * 365 / age)


def percentile(values: list[float], quantile: float) -> float:
    vals = sorted(values)
    if not vals:
        raise ValueError("percentile requires at least one value")
    if len(vals) == 1:
        return vals[0]
    position = max(0.0, min(1.0, quantile)) * (len(vals) - 1)
    lower = int(position)
    upper = min(lower + 1, len(vals) - 1)
    fraction = position - lower
    return vals[lower] + fraction * (vals[upper] - vals[lower])


def filter_price_outliers(
    comparables: list[ComparableSale],
) -> tuple[list[ComparableSale], list[ComparableSale]]:
    """Filtre MAD (puis IQR si MAD nul), robuste dès quatre comparables."""
    valid = [sale for sale in comparables if sale.price > 0]
    if len(valid) < 4:
        return valid, []

    prices = [sale.price for sale in valid]
    med = median(prices)
    deviations = [abs(price - med) for price in prices]
    mad = median(deviations)

    if mad > 0:
        kept = [
            sale for sale in valid
            if 0.6745 * abs(sale.price - med) / mad <= 3.5
        ]
    else:
        q1 = percentile(prices, 0.25)
        q3 = percentile(prices, 0.75)
        iqr = q3 - q1
        if iqr <= 0:
            kept = [sale for sale in valid if 0.5 * med <= sale.price <= 2.0 * med]
        else:
            kept = [sale for sale in valid if q1 - 1.5 * iqr <= sale.price <= q3 + 1.5 * iqr]

    # Ne jamais fabriquer une estimation sur moins de trois points à cause du filtre.
    if len(kept) < 3:
        return valid, []
    kept_ids = {id(sale) for sale in kept}
    return kept, [sale for sale in valid if id(sale) not in kept_ids]


def weighted_quantile(values_and_weights: list[tuple[float, float]], quantile: float) -> float:
    pairs = sorted((value, max(weight, 0.001)) for value, weight in values_and_weights)
    if not pairs:
        raise ValueError("weighted_quantile requires at least one value")
    if len(pairs) == 1:
        return pairs[0][0]
    total = sum(weight for _, weight in pairs)
    positions = []
    cumulative = 0.0
    for _, weight in pairs:
        cumulative += weight
        positions.append((cumulative - weight / 2) / total)
    target = max(0.0, min(1.0, quantile))
    if target <= positions[0]:
        return pairs[0][0]
    if target >= positions[-1]:
        return pairs[-1][0]
    for index in range(1, len(pairs)):
        if positions[index] >= target:
            left_pos, right_pos = positions[index - 1], positions[index]
            fraction = (target - left_pos) / (right_pos - left_pos)
            return pairs[index - 1][0] + fraction * (pairs[index][0] - pairs[index - 1][0])
    return pairs[-1][0]


def listing_is_pokemon_card(blob: str) -> bool:
    text = blob or ""
    lower = text.lower()

    # GCC expose la catégorie sur les cartes de listing: "Pokemon • French • ..."
    if not re.search(r"\bPok[ée]mon\b", text, re.I):
        return False

    # Écarte les produits scellés/accessoires.
    if any(word in lower for word in SEALED_KEYWORDS):
        return False

    return True


def sanitize_card_title(candidate: str) -> str:
    """Retourne un vrai titre potentiel, jamais une ligne Pop/métadonnée."""
    title = re.sub(r"\s+", " ", candidate or "").strip(" -–—|:")
    title = re.sub(
        r"^Pop(?:ulation)?\s*:?[ #]*(?:\d+)\s*[-–—|:]\s*",
        "",
        title,
        flags=re.I,
    ).strip()
    if not title or len(title) > 180:
        return ""
    if title.upper() in {
        "LIVE", "ENDED", "SOON", "AUCTION", "ENCHÈRE", "POKEMON", "POKÉMON",
        "DÉTAILS", "DETAILS", "DESCRIPTION", "INFORMATIONS", "SALES HISTORY",
        "HISTORIQUE DES VENTES",
    }:
        return ""
    if re.fullmatch(r"Pop(?:ulation)?\s*:?[ #]*\d+", title, re.I):
        return ""
    if "€" in title or (
        re.fullmatch(r"#?[A-Z0-9-]+(?:/[A-Z0-9-]+)?", title, re.I)
        and re.search(r"\d", title)
    ):
        return ""
    if re.fullmatch(
        r"(?:PSA|PCA|CGC|BGS|BECKETT|CCC|CA|PG)\s*(?:GRADE\s*)?\d{1,3}(?:[.,]\d{1,2})?\+?",
        title,
        re.I,
    ):
        return ""
    if re.match(
        r"^(?:Pop(?:ulation)?|Grade|Note|Grader|Gradation|Langue|Language|"
        r"S[ée]rie|Set|Extension|Ann[ée]e|Year|R[ée]f[ée]rence|Reference|"
        r"Certification|Cert(?:ificat)?|Prix|Price|Cat[ée]gorie|Category)\s*:?\b",
        title,
        re.I,
    ):
        return ""
    if re.match(r"^Pok[ée]mon\b", title, re.I) and re.search(
        r"[•|].*\b(?:French|Fran[çc]ais|English|Anglais|Japanese|Japonais)\b",
        title,
        re.I,
    ):
        return ""
    if not re.search(r"[A-Za-zÀ-ÿ]{2,}", title):
        return ""
    return title


def extract_card_title(
    page_heading: str = "",
    existing_title: str = "",
    listing_text: str = "",
    body: str = "",
) -> str:
    """Privilégie les labels de nom puis les titres GCC et le bloc de listing."""
    explicit_text = f"{body[:8000]}\n{listing_text[:3000]}"
    for pattern in (
        r"(?:Nom de la carte|Nom de l'article|Nom du collectible|Card name|"
        r"Item name|Collectible name|Nom|Titre|Title)\s*:\s*([^\n\r]{2,180})",
        r"(?:Collectible)\s*:\s*([^\n\r]{2,180})",
    ):
        match = re.search(pattern, explicit_text, re.I)
        if match:
            title = sanitize_card_title(match.group(1))
            if title:
                return title

    candidates = [existing_title, page_heading]
    candidates.extend((listing_text or "").splitlines())
    for candidate in candidates:
        title = sanitize_card_title(candidate)
        if title:
            return title
    return ""


def collect_live_auction_urls(page) -> list[str]:
    log("Ouverture accueil GCC...")
    page.goto(BASE, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    page.wait_for_timeout(1500)

    links = page.locator("a[href]")
    urls = set()

    for i in range(links.count()):
        try:
            a = links.nth(i)
            href = a.get_attribute("href") or ""
            txt = (a.inner_text(timeout=500) or "").strip()

            if "/auction/" in href and ("LIVE" in txt.upper() or "AUCTION" in href.upper()):
                if href.startswith("/"):
                    href = BASE + href
                if href.startswith(BASE):
                    urls.add(href.split("?")[0])
        except Exception:
            continue

    return sorted(urls)


def parse_sale_countdown_minutes(body: str) -> Optional[int]:
    # Sur une page de vente GCC, le compte à rebours global apparaît près du haut.
    head = body or ""
    values = {}

    patterns = {
        "days": r"(\d+)\s*(?:JOURS?|DAYS?)",
        "hours": r"(\d+)\s*(?:HEURES?|HOURS?|HRS?)",
        "minutes": r"(\d+)\s*(?:MINUTES?|MINS?)",
        "seconds": r"(\d+)\s*(?:SEC(?:ONDES?)?|SECONDS?)",
    }

    for key, pattern in patterns.items():
        m = re.search(pattern, head, re.I)
        if m:
            values[key] = int(m.group(1))

    if not values:
        return None

    return (
        values.get("days", 0) * 1440
        + values.get("hours", 0) * 60
        + values.get("minutes", 0)
        + (1 if values.get("seconds", 0) > 0 else 0)
    )


def collect_lots_from_listing(
    page,
    url: str,
    source_type: str,
    run_diagnostics: Optional[RunDiagnostics] = None,
) -> list[Lot]:
    log(f"Ouverture listing {source_type}: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    page.wait_for_timeout(1200)

    # Pour une vente aux enchères, si la vente globale finit dans >1h,
    # inutile de parcourir ses lots maintenant.
    sale_ends_soon = False
    if source_type == "auction":
        try:
            body_top = page.locator("body").inner_text(timeout=TEXT_TIMEOUT)
            sale_minutes = parse_sale_countdown_minutes(body_top)
            if sale_minutes is not None and sale_minutes > MAX_AUCTION_MINUTES:
                log(f"Vente ignorée: fin dans ~{sale_minutes} min")
                return []
            sale_ends_soon = (
                sale_minutes is not None and sale_minutes <= MAX_AUCTION_MINUTES
            )
        except Exception:
            pass

    last_height = 0
    stable = 0

    for _ in range(45):
        page.mouse.wheel(0, 2600)
        page.wait_for_timeout(120)
        try:
            h = page.evaluate("document.body.scrollHeight")
        except Exception:
            break

        if h == last_height:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
            last_height = h

    try:
        sale_name = page.locator("h1").first.inner_text(timeout=1000).strip()
    except Exception:
        sale_name = ""

    anchors = page.locator('a[href*="/item/"]')
    lots: dict[str, Lot] = {}

    for i in range(anchors.count()):
        try:
            a = anchors.nth(i)
            href = a.get_attribute("href") or ""
            if not HREF_ITEM_RE.search(href):
                continue

            item_url = BASE + href if href.startswith("/") else href
            item_url = item_url.split("?")[0]

            text = (a.inner_text(timeout=500) or "").strip()
            candidate_texts = [text]

            el = a
            for _ in range(4):
                try:
                    el = el.locator("xpath=..")
                    t = (el.inner_text(timeout=500) or "").strip()
                    if t:
                        candidate_texts.append(t)
                except Exception:
                    break

            blob = min(
                (t for t in candidate_texts if "€" in t),
                key=len,
                default=max(candidate_texts, key=len, default=""),
            )

            if not listing_is_pokemon_card(blob):
                continue

            price = parse_money(blob)
            if price is None or price < MIN_PRICE or price > MAX_PRICE:
                continue

            title = extract_card_title(
                existing_title="",
                listing_text=f"{text}\n{blob}",
            )

            lot = Lot(
                url=item_url,
                title=title,
                current_price=price,
                source_type=source_type,
                sale_name=sale_name,
                listing_text=blob,
            )

            if source_type == "auction":
                lot.minutes_to_end, lot.end_text = parse_listing_countdown_minutes(blob)

            lots[item_url] = lot
        except Exception:
            continue

    collected = list(lots.values())
    if run_diagnostics is not None and source_type == "auction" and sale_ends_soon:
        run_diagnostics.record_ending_sale(url, collected)
    return collected


def validate_grade_value(raw: str, grader: str = "", log_invalid: bool = True) -> Optional[str]:
    cleaned = (raw or "").strip().replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if value <= 0 or value > 10:
        if log_invalid:
            label = f"{grader} {raw}".strip()
            if label not in LOGGED_INVALID_GRADES:
                LOGGED_INVALID_GRADES.add(label)
                log(f"grade invalide ignoré: {label}")
        return None
    return f"{value:g}"


def format_grade_label(grader: str, grade: Optional[str]) -> str:
    return " ".join(part for part in (grader, grade or "") if part)


def parse_grader_grade(text: str) -> tuple[str, Optional[str]]:
    """Extrait un grade explicite/compact avant l'historique, toujours dans ]0, 10]."""
    current = re.split(
        r"Historique des ventes|Sales history",
        text or "",
        maxsplit=1,
        flags=re.I,
    )[0][:5000]
    lines = [line.strip() for line in current.splitlines() if line.strip()]
    grader_group = "|".join(re.escape(grader) for grader in GRADERS)
    number = r"-?\d{1,3}(?:[.,]\d{1,2})?"

    detected_match = re.search(rf"\b({grader_group})\b", current, re.I)
    detected_grader = detected_match.group(1).upper() if detected_match else ""
    invalid_seen = set()

    def validated(raw: str, grader: str) -> Optional[str]:
        key = (grader.upper(), raw.replace(",", "."))
        result = validate_grade_value(raw, grader, log_invalid=key not in invalid_seen)
        if result is None:
            invalid_seen.add(key)
        return result

    # Priorité aux lignes portant réellement un label Grade/Note. Le grader
    # peut être sur la même ligne ou dans les deux lignes structurées précédentes.
    explicit_re = re.compile(
        rf"\b(?:Grade|Note)\s*:?\s*(?:({grader_group})\s*)?({number})\b",
        re.I,
    )
    for index, line in enumerate(lines):
        match = explicit_re.search(line)
        if not match:
            continue
        nearby = " ".join(lines[max(0, index - 2): index + 3])
        grader_match = re.search(rf"\b({grader_group})\b", nearby, re.I)
        grader = (match.group(1) or (grader_match.group(1) if grader_match else "")).upper()
        grade = validated(match.group(2), grader)
        if grade is not None:
            return grader, grade

    # GCC peut rendre les champs d'un bloc "Gradation" sur des lignes séparées.
    # On accepte alors une valeur numérique isolée juste après le grader, mais
    # uniquement si le contexte du bloc est explicitement celui de la gradation.
    grader_only_re = re.compile(
        rf"^(?:Grader|Soci[ée]t[ée](?: de gradation)?)?\s*:?[ ]*({grader_group})$",
        re.I,
    )
    for index, line in enumerate(lines):
        grader_match = grader_only_re.fullmatch(line)
        if not grader_match:
            continue
        block_context = " ".join(lines[max(0, index - 4): index + 1])
        if not re.search(r"\b(?:Gradation|Grading|Grade|Note)\b", block_context, re.I):
            continue
        for following in lines[index + 1: index + 3]:
            if re.search(r"\bPop(?:ulation)?\b", following, re.I):
                break
            number_match = re.fullmatch(rf"({number})\+?", following)
            if not number_match:
                continue
            grader = grader_match.group(1).upper()
            grade = validated(number_match.group(1), grader)
            if grade is not None:
                return grader, grade
            break

    # Format compact de titre, par exemple "PSA 10 Dracaufeu" ou "BGS 9.5".
    # Les lignes Population/Certification/Référence sont exclues avant lecture.
    compact_re = re.compile(
        rf"\b({grader_group})\s*(?:GRADE\s*)?[:#]?\s*({number})\b",
        re.I,
    )
    ambiguous_prefix = re.compile(
        r"^\s*(?:Pop(?:ulation)?|Certification|Cert(?:ificat)?|Serial|Référence|"
        r"Reference|Année|Year|Prix|Price)\b",
        re.I,
    )
    for line in lines:
        if ambiguous_prefix.search(line):
            continue
        match = compact_re.search(line)
        if not match:
            continue
        grader = match.group(1).upper()
        grade = validated(match.group(2), grader)
        if grade is not None:
            return grader, grade

    return detected_grader, None


_GRADE_DIAGNOSTIC_SENSITIVE_RE = re.compile(
    r"\b(?:authorization|bearer|cookie|set-cookie|token|mot de passe|password|"
    r"session(?:[_ -]?id)?|api[_ -]?key|secret)\b",
    re.I,
)
_GRADE_DIAGNOSTIC_EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I
)
_GRADE_DIAGNOSTIC_GRADERS = tuple(dict.fromkeys((*GRADERS, "SGC")))
_PCA_AUTHENTIC_QUALIFIER = "PCA A / Authentique"
_SPECIAL_GRADE_QUALIFIERS = (
    (
        "OC / Off Center",
        r"(?:OC|OFF[ -]?CENT(?:ER|RE)(?:ED)?|HORS[ -]?CENTRAGE)"
        r"(?:\s*\(\s*OC\s*\))?",
    ),
    ("Miscut", r"(?:MC|MIS[ -]?CUT)(?:\s*\(\s*MC\s*\))?"),
    ("Error", r"(?:ERROR|ERREUR)"),
    ("Staining", r"(?:ST|STAIN(?:ING)?)"),
    ("Print Defect", r"(?:PD|PRINT[ -]?DEFECT)"),
    ("Out of Focus", r"(?:OF|OUT[ -]?OF[ -]?FOCUS)"),
    ("Marks", r"(?:MK|MARKS?)"),
    (
        "Authentic / Altered",
        r"(?:AUTHENTIC(?:[ -]?ALTERED)?|ALTERED|TRIMMED|RECOLORED|"
        r"MINIMUM[ -]?SIZE|EVIDENCE[ -]?OF[ -]?TRIMMING)",
    ),
)


def _safe_grade_diagnostic_text(raw: str, limit: int = 260) -> str:
    """Nettoie une ligne visible sans jamais reproduire un secret d'authentification."""
    text = re.sub(r"\s+", " ", raw or "").strip()
    if not text:
        return ""
    if _GRADE_DIAGNOSTIC_SENSITIVE_RE.search(text):
        return "[information d'authentification masquée]"
    text = _GRADE_DIAGNOSTIC_EMAIL_RE.sub("[email masqué]", text)
    if len(text) > limit:
        return f"{text[:limit - 1].rstrip()}…"
    return text


def _grade_diagnostic_full_text(lot: Lot) -> str:
    return "\n".join(
        value
        for value in (
            lot.page_title_raw,
            lot.title,
            lot.listing_text,
            lot.body,
        )
        if value
    )[:32000]


def _grade_diagnostic_current_text(lot: Lot) -> str:
    raw = _grade_diagnostic_full_text(lot)
    return re.split(
        r"Historique des ventes|Sales history",
        raw,
        maxsplit=1,
        flags=re.I,
    )[0][:16000]


def _extract_grading_block_raw(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    candidates = []
    for index, line in enumerate(lines):
        is_grading_heading = re.search(r"\b(?:Gradation|Grading)\b", line, re.I)
        is_grade_label = re.search(
            r"\b(?:Soci[ée]t[ée]\s+de\s+gradation|Grader|Grade|Note)\s*:?",
            line,
            re.I,
        )
        if not is_grading_heading and not is_grade_label:
            continue
        nearby = " ".join(lines[max(0, index - 2):index + 3])
        score = 1
        if re.search(r"\bArticle\b", nearby, re.I):
            score += 4
        if re.search(r"\bD[ée]tails?\b", nearby, re.I):
            score += 4
        if is_grade_label:
            score += 3
        candidates.append((score, index))
    if not candidates:
        return ""
    _, heading_index = max(candidates, key=lambda item: (item[0], -item[1]))
    start = max(0, heading_index - 2)
    selected = []
    for line in lines[start:start + 24]:
        if selected and re.search(
            r"Historique des ventes|Sales history|Articles? similaires?",
            line,
            re.I,
        ):
            break
        clean = _safe_grade_diagnostic_text(line)
        if clean:
            selected.append(clean)
    return "\n".join(selected)


def _grade_label_context(text: str, pattern: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    matches = []
    label_re = re.compile(pattern, re.I)
    for index, line in enumerate(lines):
        if not label_re.search(line):
            continue
        context = [line]
        suffix = label_re.sub("", line, count=1).strip(" :–—-")
        if not suffix and index + 1 < len(lines):
            context.append(lines[index + 1])
        clean = _safe_grade_diagnostic_text(" | ".join(context))
        if clean and clean not in matches:
            matches.append(clean)
        if len(matches) == 3:
            break
    return " || ".join(matches)


def _grade_raw_excerpt(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    keyword_re = re.compile(
        r"\b(?:PSA|PCA|CCC|BGS|CGC|SGC|Grade|Note|Gradation|Grading|"
        r"Off[ -]?Center|Miscut|Error|Staining|Print[ -]?Defect|"
        r"Out[ -]?of[ -]?Focus|Authentic|Authentique|Altered)\b",
        re.I,
    )
    selected = []
    selected_indexes = set()
    for index, line in enumerate(lines):
        if not keyword_re.search(line):
            continue
        for nearby in range(max(0, index - 1), min(len(lines), index + 2)):
            if nearby in selected_indexes:
                continue
            clean = _safe_grade_diagnostic_text(lines[nearby])
            if clean:
                selected.append(clean)
                selected_indexes.add(nearby)
            if len(selected) == 18:
                return "\n".join(selected)
    return "\n".join(selected)


def _match_special_grade_qualifier(raw: str, grader: str = "") -> str:
    value = re.sub(r"\s+", " ", raw or "").strip(" :–—-+")
    if not value:
        return ""
    if re.fullmatch(r"AUTHENTIQUE", value, re.I) or (
        (grader or "").upper() == "PCA" and re.fullmatch(r"A", value, re.I)
    ):
        return _PCA_AUTHENTIC_QUALIFIER
    for label, pattern in _SPECIAL_GRADE_QUALIFIERS:
        if re.fullmatch(
            rf"(?:{pattern})(?:\s+(?:QUALIFIER|QUALIFICATIF))?",
            value,
            re.I,
        ):
            return label
    return ""


def _find_special_grade_qualifier(
    lot: Lot, parser_text: str, grading_block: str
) -> str:
    """Reconnaît seulement un qualifier explicitement placé comme valeur de grade."""
    context_grader = (lot.grader or "").upper()
    if not context_grader:
        grader_match = re.search(
            r"\b(?:Soci[ée]t[ée]\s+de\s+gradation|Grader)\s*:?\s*"
            r"(PSA|PCA|CCC|BGS|CGC|SGC|CA|PG)\b",
            parser_text,
            re.I,
        )
        if grader_match:
            context_grader = grader_match.group(1).upper()
    if lot.grade is not None:
        matched = _match_special_grade_qualifier(
            str(lot.grade), context_grader
        )
        if matched:
            return matched

    grader_group = "|".join(
        re.escape(grader) for grader in _GRADE_DIAGNOSTIC_GRADERS
    )
    lines = [
        line.strip()
        for line in f"{parser_text}\n{grading_block}".splitlines()
        if line.strip()
    ]
    value_label_re = re.compile(
        r"\b(?:Grade|Note|Qualifier|Qualificatif)\s*:?\s*(.*)$",
        re.I,
    )
    for index, line in enumerate(lines):
        label_match = value_label_re.search(line)
        if label_match:
            candidate = label_match.group(1).strip()
            if not candidate and index + 1 < len(lines):
                candidate = lines[index + 1]
            candidate = re.sub(
                rf"^(?:{grader_group})\s*", "", candidate, flags=re.I
            )
            matched = _match_special_grade_qualifier(
                candidate, context_grader
            )
            if matched:
                return matched

        if re.search(
            r"\bPCA\b\s*(?:GRADE\s*|NOTE\s*)?[:#]?\s*A\b",
            line,
            re.I,
        ):
            return _PCA_AUTHENTIC_QUALIFIER

        for qualifier_label, qualifier_pattern in _SPECIAL_GRADE_QUALIFIERS:
            if re.search(
                rf"\b(?:{grader_group})\b\s*(?:GRADE\s*)?[:#]?\s*"
                rf"(?:{qualifier_pattern})\b",
                line,
                re.I,
            ):
                return qualifier_label

        nearby = " ".join(lines[max(0, index - 3):index])
        nearby_grader = (
            "PCA" if re.search(r"\bPCA\b", nearby, re.I) else context_grader
        )
        matched = _match_special_grade_qualifier(line, nearby_grader)
        if not matched:
            continue
        if re.search(
            rf"\b(?:{grader_group}|Grade|Note|Gradation|Grading|"
            r"Qualifier|Qualificatif)\b",
            nearby,
            re.I,
        ):
            return matched
    return ""


def _grade_diagnostic_observations(
    lot: Lot, text: str, grading_block: str
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[float, ...], bool]:
    grader_group = "|".join(
        re.escape(grader) for grader in _GRADE_DIAGNOSTIC_GRADERS
    )
    number = r"-?\d{1,3}(?:[.,]\d{1,2})?"
    graders = []
    raw_grades = []
    numeric_grades = []
    nonnumeric_current_grade = False

    def add_grader(raw: str) -> None:
        grader = (raw or "").upper()
        if grader and grader not in graders:
            graders.append(grader)

    def add_grade(raw: str) -> None:
        nonlocal nonnumeric_current_grade
        cleaned = (raw or "").strip().replace(",", ".")
        if not cleaned:
            return
        if cleaned not in raw_grades:
            raw_grades.append(cleaned)
        try:
            value = float(cleaned)
        except ValueError:
            nonnumeric_current_grade = True
            return
        if value not in numeric_grades:
            numeric_grades.append(value)

    if lot.grader.upper() in _GRADE_DIAGNOSTIC_GRADERS:
        add_grader(lot.grader)
    if lot.grade is not None:
        add_grade(str(lot.grade))

    for match in re.finditer(
        rf"\b(?:Soci[ée]t[ée]\s+de\s+gradation|Grader)\s*:?\s*"
        rf"({grader_group})\b",
        text,
        re.I,
    ):
        add_grader(match.group(1))

    explicit_re = re.compile(
        rf"\b(?:Grade|Note)\s*:?\s*(?:({grader_group})\s*)?({number})\b",
        re.I,
    )
    for match in explicit_re.finditer(text):
        if match.group(1):
            add_grader(match.group(1))
        add_grade(match.group(2))

    compact_re = re.compile(
        rf"\b({grader_group})\s*(?:GRADE\s*)?[:#]?\s*({number})\b",
        re.I,
    )
    for line in text.splitlines():
        if re.match(
            r"^\s*(?:Pop(?:ulation)?|Certification|Cert(?:ificat)?|Serial|"
            r"R[ée]f[ée]rence|Reference|Ann[ée]e|Year|Prix|Price)\b",
            line,
            re.I,
        ):
            continue
        for match in compact_re.finditer(line):
            add_grader(match.group(1))
            add_grade(match.group(2))

    block_lines = [
        line.strip() for line in (grading_block or "").splitlines() if line.strip()
    ]
    for index, line in enumerate(block_lines):
        for match in re.finditer(rf"\b({grader_group})\b", line, re.I):
            add_grader(match.group(1))
        number_match = re.fullmatch(rf"({number})\+?", line)
        if not number_match:
            continue
        previous = block_lines[index - 1] if index else ""
        if re.search(
            r"\b(?:Pop(?:ulation)?|Certification|Cert(?:ificat)?|Serial|"
            r"R[ée]f[ée]rence|Reference|Ann[ée]e|Year|Prix|Price)\b",
            previous,
            re.I,
        ):
            continue
        add_grade(number_match.group(1))

    if not graders:
        detected = re.search(rf"\b({grader_group})\b", text, re.I)
        if detected:
            add_grader(detected.group(1))

    return (
        tuple(graders),
        tuple(raw_grades),
        tuple(numeric_grades),
        nonnumeric_current_grade,
    )


def diagnose_unreadable_grade(lot: Lot) -> GradeUnreadableDiagnostic:
    """Décrit un échec de lecture sans intervenir dans le parseur ou la valeur."""
    full_text = _grade_diagnostic_full_text(lot)
    parser_text = _grade_diagnostic_current_text(lot)
    grading_block = _extract_grading_block_raw(full_text)
    special_qualifier = _find_special_grade_qualifier(
        lot, parser_text, grading_block
    )
    graders, raw_grades, numeric_grades, nonnumeric_grade = (
        _grade_diagnostic_observations(lot, parser_text, grading_block)
    )
    current_grader = (lot.grader or "").upper()
    known_current_grader = current_grader in GRADERS
    distinct_numeric = set(numeric_grades)
    invalid_numeric = [value for value in numeric_grades if value <= 0 or value > 10]
    valid_numeric = [value for value in numeric_grades if 0 < value <= 10]

    if special_qualifier:
        reason = GRADE_SPECIAL_QUALIFIER
    elif not current_grader:
        if len(graders) > 1:
            reason = GRADE_UNREADABLE_CONFLICT
        elif graders:
            reason = GRADE_UNREADABLE_AMBIGUOUS
        else:
            reason = GRADE_UNREADABLE_GRADER_ABSENT
    elif not known_current_grader:
        reason = GRADE_UNREADABLE_OTHER
    elif len(graders) > 1 or len(distinct_numeric) > 1:
        reason = GRADE_UNREADABLE_CONFLICT
    elif nonnumeric_grade or (invalid_numeric and not valid_numeric):
        reason = GRADE_UNREADABLE_GRADE_INVALID
    elif lot.grade is None and not raw_grades:
        reason = GRADE_UNREADABLE_GRADE_ABSENT
    elif lot.grade is None and valid_numeric:
        reason = GRADE_UNREADABLE_AMBIGUOUS
    elif lot.grade is not None and _target_grade(lot) is None:
        reason = GRADE_UNREADABLE_GRADE_INVALID
    else:
        reason = GRADE_UNREADABLE_OTHER

    label_specs = (
        ("Société de gradation", r"\bSoci[ée]t[ée]\s+de\s+gradation\s*:?\s*"),
        ("Grader", r"\bGrader\s*:?\s*"),
        ("Grade", r"\bGrade\s*:?\s*"),
        ("Note", r"\bNote\s*:?\s*"),
        (
            "Certification / numéro de série",
            r"\b(?:Certification|Cert(?:ificat|ificate)?(?:\s+Number)?|PSA\s+Cert|"
            r"Num[ée]ro\s+de\s+(?:certification|s[ée]rie)|Serial(?:\s+Number)?)\s*:?\s*",
        ),
    )
    label_contexts = tuple(
        (label, _grade_label_context(full_text, pattern) or "<absent>")
        for label, pattern in label_specs
    )
    safe_url = (lot.url or "<absent>").split("?", 1)[0].split("#", 1)[0]
    return GradeUnreadableDiagnostic(
        title=_safe_grade_diagnostic_text(lot.title) or "<absent>",
        url=safe_url,
        price=lot.current_price,
        source_type=lot.source_type or "<absent>",
        extracted_grader=_safe_grade_diagnostic_text(lot.grader) or "<absent>",
        extracted_grade=(
            _safe_grade_diagnostic_text(str(lot.grade))
            if lot.grade is not None else None
        ),
        page_title_raw=(
            _safe_grade_diagnostic_text(lot.page_title_raw) or "<absent>"
        ),
        grading_block_raw=grading_block or "<absent>",
        label_contexts=label_contexts,
        raw_excerpt=_grade_raw_excerpt(full_text) or "<absent>",
        reason=reason,
        observed_graders=graders,
        observed_grades=raw_grades,
        special_qualifier=special_qualifier,
    )


def format_unreadable_grade_diagnostic(
    diagnostic: GradeUnreadableDiagnostic,
) -> str:
    price = (
        f"{diagnostic.price:.2f} €"
        if diagnostic.price is not None else "<illisible>"
    )
    special_qualifier = diagnostic.reason == GRADE_SPECIAL_QUALIFIER
    lines = [
        (
            "=== DIAG QUALIFIER SPÉCIAL EXCLU ==="
            if special_qualifier else "=== DIAG GRADE ILLISIBLE ==="
        ),
        f"Titre: {diagnostic.title}",
        f"URL: {diagnostic.url}",
        f"Prix: {price}",
        f"Type: {diagnostic.source_type}",
        "",
        f"grader brut actuellement extrait: {diagnostic.extracted_grader}",
        (
            "grade brut actuellement extrait: "
            f"{diagnostic.extracted_grade or '<absent>'}"
        ),
        "",
        f"Titre brut de la page: {diagnostic.page_title_raw}",
        "Bloc de grading brut:",
    ]
    lines.extend(
        f"  {line}" for line in diagnostic.grading_block_raw.splitlines()
    )
    lines.append("Texte autour des labels:")
    lines.extend(
        f"- {label}: {context}"
        for label, context in diagnostic.label_contexts
    )
    lines.append("Extrait brut pertinent de la fiche:")
    lines.extend(f"  {line}" for line in diagnostic.raw_excerpt.splitlines())
    observed_graders = ", ".join(diagnostic.observed_graders) or "<aucun>"
    observed_grades = ", ".join(diagnostic.observed_grades) or "<aucun>"
    lines.extend(
        (
            f"Candidats observés: graders {observed_graders} | "
            f"grades {observed_grades}",
            *(
                (f"Qualifier spécial: {diagnostic.special_qualifier}",)
                if special_qualifier else ()
            ),
            f"Motif: {diagnostic.reason}",
        )
    )
    return "\n".join(lines)


def log_unreadable_grade_diagnostic(
    diagnostic: GradeUnreadableDiagnostic,
) -> None:
    for line in format_unreadable_grade_diagnostic(diagnostic).splitlines():
        log(line) if line else print(flush=True)


def parse_item_countdown_minutes(body: str) -> tuple[Optional[int], str]:
    head = body or ""
    values = {}

    patterns = {
        "days": r"(\d+)\s*(?:JOURS?|DAYS?)",
        "hours": r"(\d+)\s*(?:HEURES?|HOURS?|HRS?)",
        "minutes": r"(\d+)\s*(?:MINUTES?|MINS?)",
        "seconds": r"(\d+)\s*(?:SEC(?:ONDES?)?|SECONDS?)",
    }

    for key, pattern in patterns.items():
        m = re.search(pattern, head, re.I)
        if m:
            values[key] = int(m.group(1))

    if not values:
        return None, ""

    total = (
        values.get("days", 0) * 1440
        + values.get("hours", 0) * 60
        + values.get("minutes", 0)
        + (1 if values.get("seconds", 0) > 0 else 0)
    )

    label = (
        f"{values.get('days', 0)}j "
        f"{values.get('hours', 0)}h "
        f"{values.get('minutes', 0)}m "
        f"{values.get('seconds', 0)}s"
    )
    return total, label



def parse_listing_countdown_minutes(text: str) -> tuple[Optional[int], str]:
    """
    Lit le temps restant directement dans le bloc de carte du listing.

    IMPORTANT:
    - ne retourne JAMAIS 0 minute si aucun timer explicite n'est trouvé;
    - accepte les formats avec unités (jours/heures/minutes/sec);
    - accepte HH:MM:SS;
    - sinon retourne (None, "") pour forcer le fallback fiche.
    """
    raw = text or ""

    # Format explicite avec unités. On exige au moins UNE unité réellement présente.
    days_m = re.search(r"(?<!\d)(\d+)\s*(?:JOURS?|DAYS?)\b", raw, re.I)
    hours_m = re.search(r"(?<!\d)(\d+)\s*(?:HEURES?|HOURS?|HRS?)\b", raw, re.I)
    mins_m = re.search(r"(?<!\d)(\d+)\s*(?:MINUTES?|MINS?)\b", raw, re.I)
    secs_m = re.search(r"(?<!\d)(\d+)\s*(?:SEC(?:ONDES?)?|SECONDS?)\b", raw, re.I)

    if any((days_m, hours_m, mins_m, secs_m)):
        d = int(days_m.group(1)) if days_m else 0
        h = int(hours_m.group(1)) if hours_m else 0
        m = int(mins_m.group(1)) if mins_m else 0
        s = int(secs_m.group(1)) if secs_m else 0

        total = d * 1440 + h * 60 + m + (1 if s > 0 else 0)
        label = f"{d}j {h}h {m}m {s}s"
        return total, label

    # Format condensé HH:MM:SS
    for match in re.finditer(r"(?<!\d)(\d{1,2}):(\d{2}):(\d{2})(?!\d)", raw):
        h, m, s = map(int, match.groups())
        if 0 <= m < 60 and 0 <= s < 60:
            total = h * 60 + m + (1 if s > 0 else 0)
            return total, match.group(0)

    # Rien de lisible => fallback fiche.
    return None, ""


def inspect_item(page, lot: Lot) -> Lot:
    try:
        page.goto(lot.url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        page.wait_for_timeout(650)

        body = page.locator("body").inner_text(timeout=TEXT_TIMEOUT)
        lot.body = body

        page_heading = ""
        try:
            page_heading = page.locator("h1").first.inner_text(timeout=800).strip()
        except Exception:
            pass
        lot.page_title_raw = page_heading

        lot.title = extract_card_title(
            page_heading=page_heading,
            existing_title=lot.title,
            listing_text=lot.listing_text,
            body=body,
        )

        current_section = re.split(
            r"Historique des ventes|Sales history",
            body,
            maxsplit=1,
            flags=re.I,
        )[0]
        page_price = parse_money(current_section)
        if page_price is not None:
            lot.current_price = page_price

        lot.grader, lot.grade = parse_grader_grade(f"{lot.title}\n{body}")

        if lot.source_type == "auction":
            lot.minutes_to_end, lot.end_text = parse_item_countdown_minutes(body)

        return lot

    except PlaywrightTimeoutError:
        log(f"Timeout fiche: {lot.url}")
        return lot
    except Exception as e:
        log(f"Erreur fiche {type(e).__name__}: {lot.url}")
        return lot


def is_valid_pokemon_card(
    lot: Lot, run_diagnostics: Optional[RunDiagnostics] = None
) -> bool:
    body = lot.body or ""
    lower = body.lower()

    clean_title = sanitize_card_title(lot.title)
    if not clean_title:
        log(f"Lot ignoré: nom de carte insuffisamment identifié ({lot.url})")
        if run_diagnostics is not None:
            run_diagnostics.record_valuation(
                lot, REJECTION_INSUFFICIENT_IDENTITY
            )
        return False
    lot.title = clean_title

    if not re.search(r"(Catégorie|Category)\s*:?\s*Pok[ée]mon\b", body, re.I):
        if run_diagnostics is not None:
            run_diagnostics.record_valuation(lot, REJECTION_OTHER)
        return False

    if any(word in lower for word in SEALED_KEYWORDS):
        if run_diagnostics is not None:
            run_diagnostics.record_valuation(lot, REJECTION_OTHER)
        return False

    # On veut une carte, pas un produit scellé. La présence d'un bloc de gradation
    # ou d'une référence de carte est un signal positif.
    if re.search(r"Article\s+Gradation\s+Détails", body, re.I):
        return True

    if re.search(r"(Réf[ée]rence|Reference)\s*:?\s*#?\s*[A-Z0-9]+(?:/[A-Z0-9]+)+", body, re.I):
        return True

    if run_diagnostics is not None:
        run_diagnostics.record_valuation(lot, REJECTION_OTHER)
    return False


def extract_historical_sales(lot: Lot) -> list[HistoricalSale]:
    body = lot.body or ""

    m = re.search(r"(Historique des ventes|Sales history)(.*)", body, re.I | re.S)
    if not m:
        return []

    section = m.group(2)[:16000]

    if re.search(r"Connectez-vous.*historique|log in.*history", section, re.I | re.S):
        return []

    sales: list[HistoricalSale] = []

    for price_match in MONEY_RE.finditer(section):
        try:
            price = normalize_money(price_match.group(1))
        except ValueError:
            continue

        if not 1 <= price <= 50000:
            continue

        start = max(0, price_match.start() - 380)
        end = min(len(section), price_match.end() + 380)
        context = section[start:end]

        grader, grade_text = parse_grader_grade(context)
        grade = float(grade_text) if grade_text is not None else None

        sales.append(
            ComparableSale(
                price=price,
                source="gcc",
                grader=grader,
                grade=grade,
                sold_at=parse_sale_date(context),
                context=context.replace("\n", " ")[:300],
                exact_card=True,
                match_score=100,
            )
        )

    # Déduplication approximative d'éventuelles répétitions DOM.
    deduped: list[HistoricalSale] = []
    seen = set()
    for s in sales:
        sold_day = s.sold_at.date().isoformat() if s.sold_at else ""
        key = (round(s.price, 2), s.grader, s.grade, sold_day)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)

    return deduped[:40]



def normalize_ebay_eur(raw: str) -> float:
    """
    Convertit des formats eBay FR du type:
    1 299,00 / 1.299,00 / 1299.00 / 69,43
    en float EUR.
    """
    s = (
        (raw or "")
        .replace("\u00a0", "")
        .replace(" ", "")
        .replace("'", "")
        .strip()
    )

    if "," in s and "." in s:
        # Format européen probable: 1.299,00
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        tail = s.rsplit(",", 1)[-1]
        if len(tail) in (1, 2):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        tail = s.rsplit(".", 1)[-1]
        if len(tail) == 3 and s.count(".") >= 1:
            s = s.replace(".", "")

    return float(s)


def extract_card_identity(lot: Lot) -> dict:
    """
    Extrait les éléments d'identité de la carte depuis la fiche GCC:
    nom, référence, année, langue et série/set.
    """
    title = lot.title or ""
    body = lot.body or ""

    core = title
    if lot.grader and lot.grade:
        core = re.sub(
            rf"^\s*{re.escape(lot.grader)}\s*{re.escape(lot.grade)}\+?\s*",
            "",
            core,
            flags=re.I,
        )
    core = re.sub(
        r"^\s*(?:PSA|PCA|CGC|BGS|BECKETT|CCC|CA|PG)\s*\d+(?:[.,]\d)?\+?\s*",
        "",
        core,
        flags=re.I,
    )
    core = re.sub(r"\s+", " ", core).strip()

    ref = ""
    ref_patterns = (
        r"(?:Réf[ée]rence|Reference|Num[ée]ro|Number)\s*:?\s*#?\s*([A-Z0-9-]{1,10}(?:/[A-Z0-9-]{1,10})?)",
        r"#\s*([A-Z0-9-]{1,10}(?:/[A-Z0-9-]{1,10})?)",
        r"\b([A-Z0-9-]{1,10}/[A-Z0-9-]{1,10})\b",
    )
    for pattern in ref_patterns:
        match = re.search(pattern, f"{title}\n{body}", re.I)
        if match:
            ref = match.group(1).upper()
            break

    year = ""
    ym = re.search(
        r"(?:Année|Year)\s*:?\s*(19\d{2}|20\d{2})\b",
        body,
        re.I,
    ) or re.search(r"\b(19\d{2}|20\d{2})\b", f"{title}\n{body}")
    if ym:
        year = ym.group(1)

    language = ""
    language_map = {
        "French": ("French", "Français", "Francais"),
        "Japanese": ("Japanese", "Japonais"),
        "English": ("English", "Anglais"),
        "German": ("German", "Allemand"),
        "Spanish": ("Spanish", "Espagnol"),
        "Italian": ("Italian", "Italien"),
    }
    for canonical, variants in language_map.items():
        identity_text = f"{title}\n{lot.listing_text}\n{body}"
        if any(re.search(rf"\b{re.escape(v)}\b", identity_text, re.I) for v in variants):
            language = canonical
            break

    # Série/set: plusieurs libellés possibles selon la fiche GCC.
    series = ""
    series_patterns = [
        r"(?:Série|Serie|Set|Extension)\s*:?\s*([^\n\r]{2,80})",
        r"(?:Collection)\s*:?\s*([^\n\r]{2,80})",
    ]
    for pattern in series_patterns:
        sm = re.search(pattern, body, re.I)
        if sm:
            candidate = sm.group(1).strip()
            candidate = re.split(
                r"\s{2,}|(?:Langue|Language|Année|Year|Référence|Reference|Grade|Gradation|Catégorie|Category)\s*:?",
                candidate,
                maxsplit=1,
                flags=re.I,
            )[0].strip(" -:|")
            if candidate and len(candidate) >= 2:
                series = candidate
                break

    return {
        "core": core,
        "ref": ref,
        "year": year,
        "language": language,
        "series": series,
    }


def extract_psa_apr_identity(text: str) -> dict:
    """Extrait l'identité visible d'un résultat ou d'une fiche publique APR."""
    blob = text or ""
    lines = [re.sub(r"\s+", " ", line).strip(" |") for line in blob.splitlines()]
    lines = [line for line in lines if line]

    ref = ""
    for pattern in (
        r"#\s*([A-Z0-9-]{1,10}(?:/[A-Z0-9-]{1,10})?)",
        r"(?:No\.?|Number|Card Number)\s*:?[ #]*([A-Z0-9-]{1,10}(?:/[A-Z0-9-]{1,10})?)",
        r"\b([A-Z0-9-]{1,10}/[A-Z0-9-]{1,10})\b",
    ):
        match = re.search(pattern, blob, re.I)
        if match:
            ref = match.group(1).upper()
            break

    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", blob)
    year = year_match.group(1) if year_match else ""

    language = ""
    for canonical, variants in {
        "French": ("French", "Français", "Francais"),
        "Japanese": ("Japanese", "Japonais"),
        "English": ("English", "Anglais"),
        "German": ("German", "Allemand"),
        "Spanish": ("Spanish", "Espagnol"),
        "Italian": ("Italian", "Italien"),
    }.items():
        if any(re.search(rf"\b{re.escape(term)}\b", blob, re.I) for term in variants):
            language = canonical
            break

    series = ""
    for line in lines:
        if re.search(r"\b(?:19\d{2}|20\d{2})\b", line) and re.search(
            r"Pok[ée]mon", line, re.I
        ):
            series = line
            break

    core = ""
    explicit = re.search(
        r"(?:Subject|Card Name|Item Name)\s*:\s*([^\n\r|]{2,160})",
        blob,
        re.I,
    )
    if explicit:
        core = explicit.group(1).strip()
    elif series and series in lines:
        series_index = lines.index(series)
        for line in lines[series_index + 1:]:
            if re.fullmatch(
                r"(?:No\.?|Number|Card Number)\s*:?[ #]*[A-Z0-9/-]+",
                line,
                re.I,
            ):
                continue
            if re.search(
                r"Auction Prices|Total (?:Auction )?Sales|Population|Pop Higher|"
                r"Most Recent|Average Price|Search PSA|View Set",
                line,
                re.I,
            ):
                continue
            core = re.sub(r"\s+#\s*[A-Z0-9/-]+\s*$", "", line, flags=re.I).strip()
            if core:
                break

    return {
        "core": core,
        "ref": ref,
        "year": year,
        "language": language,
        "series": series,
    }


def _reference_parts(reference: str) -> tuple[str, str]:
    compact = re.sub(r"[^A-Z0-9/]", "", (reference or "").upper())
    numerator, separator, denominator = compact.partition("/")
    numerator = numerator.lstrip("0") or ("0" if numerator else "")
    denominator = denominator.lstrip("0") or ("0" if separator and denominator else "")
    return numerator, denominator


def card_references_match(target: str, candidate: str) -> bool:
    target_number, target_total = _reference_parts(target)
    candidate_number, candidate_total = _reference_parts(candidate)
    if not target_number or not candidate_number or target_number != candidate_number:
        return False
    return not (target_total and candidate_total and target_total != candidate_total)


def _identity_tokens(text: str) -> list[str]:
    stop = {
        "pokemon", "pokémon", "the", "and", "les", "des", "une", "card",
        "full", "art", "holo", "reverse", "psa", "auction", "prices",
    }
    return [
        token.lower()
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9'-]{3,}", text or "")
        if token.lower() not in stop
    ]


def psa_apr_identity_is_sufficient(lot: Lot) -> bool:
    identity = extract_card_identity(lot)
    if identity["ref"]:
        return bool(identity["core"] or identity["year"] or identity["series"])
    return bool(identity["core"] and identity["year"] and identity["series"])


def psa_apr_match_score(lot: Lot, candidate_text: str) -> tuple[int, str]:
    """Score strict: référence prioritaire, puis année/série/nom/langue."""
    target = extract_card_identity(lot)
    candidate = extract_psa_apr_identity(candidate_text)
    plain = _plain_text(candidate_text)
    reasons: list[str] = []
    score = 0

    if any(keyword in plain for keyword in SEALED_KEYWORDS):
        return 0, "produit scellé/accessoire"

    if target["ref"]:
        if not candidate["ref"]:
            return 0, "référence APR absente"
        if not card_references_match(target["ref"], candidate["ref"]):
            return 0, "mauvaise référence"
        score += 65
        reasons.append("référence exacte")

    year_matches = False
    if target["year"]:
        if candidate["year"] and candidate["year"] != target["year"]:
            return 0, "mauvaise année"
        if target["year"] in candidate_text:
            score += 12 if target["ref"] else 25
            year_matches = True
            reasons.append("année")

    series_tokens = _identity_tokens(target["series"])
    series_hits = sum(1 for token in series_tokens[:6] if token in plain)
    if series_hits:
        score += min(20 if target["ref"] else 30, series_hits * 6)
        reasons.append(f"série({series_hits})")

    name_tokens = _identity_tokens(target["core"])
    name_hits = sum(1 for token in name_tokens[:5] if token in plain)
    if name_hits:
        score += min(20 if target["ref"] else 30, name_hits * 10)
        reasons.append(f"nom({name_hits})")

    if target["language"]:
        if candidate["language"] and candidate["language"] != target["language"]:
            return 0, "mauvaise langue"
        if candidate["language"] == target["language"]:
            score += 5
            reasons.append("langue")

    if not target["ref"] and not (year_matches and series_hits and name_hits):
        return 0, "identité sans référence insuffisante"
    if target["ref"] and not (year_matches or series_hits or name_hits):
        return 0, "référence seule sans confirmation"
    return score, ", ".join(reasons)


def choose_psa_apr_candidate(
    lot: Lot, candidates: list[PsaAprCandidate]
) -> tuple[Optional[PsaAprCandidate], int, str]:
    unique: dict[str, PsaAprCandidate] = {}
    for candidate in candidates:
        if candidate.url and candidate.url not in unique:
            unique[candidate.url] = candidate

    ranked = []
    for candidate in unique.values():
        score, reason = psa_apr_match_score(lot, candidate.text)
        if score >= PSA_APR_MATCH_MIN_SCORE:
            ranked.append((score, candidate.url, candidate, reason))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if not ranked:
        return None, 0, "aucune correspondance assez forte"
    best = ranked[0]
    if len(ranked) > 1 and ranked[1][0] >= best[0] - 5:
        return None, best[0], "résultats APR ambigus"
    return best[2], best[0], best[3]


def psa_apr_search_query(lot: Lot) -> str:
    identity = extract_card_identity(lot)
    parts = [
        "Pokemon", identity["ref"], identity["year"], identity["series"],
        identity["core"], identity["language"],
    ]
    return re.sub(r"\s+", " ", " ".join(part for part in parts if part)).strip()


def psa_apr_card_validation_allowed(
    lot: Lot,
    cards_already_validated: int,
    max_cards: Optional[int] = None,
) -> bool:
    limit = PSA_APR_MAX_CARDS_PER_RUN if max_cards is None else max_cards
    return bool(
        PSA_APR_ENABLED
        and cards_already_validated < max(0, limit)
        and (lot.grader or "").upper() == "PSA"
        and _target_grade(lot) is not None
        and psa_apr_identity_is_sufficient(lot)
    )


def _split_psa_apr_row(row: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", field).strip()
        for field in re.split(r"[\n\t|]+", row or "")
        if field.strip()
    ]


def _parse_psa_apr_sale_row(
    row: str,
    usd_per_eur: float,
    now: Optional[datetime] = None,
) -> Optional[tuple[ComparableSale, str, str]]:
    fields = _split_psa_apr_row(row)
    date_index = next(
        (index for index, field in enumerate(fields) if parse_sale_date(field, now)),
        None,
    )
    price_index = next(
        (index for index, field in reversed(list(enumerate(fields))) if "$" in field),
        None,
    )
    if date_index is None or price_index is None:
        return None

    sold_at = parse_sale_date(fields[date_index], now)
    price_usd = parse_psa_apr_usd(fields[price_index])
    if sold_at is None or price_usd is None:
        return None

    grade = None
    for field in reversed(fields[:price_index]):
        match = re.fullmatch(r"(?:PSA\s*)?(10|[1-9](?:\.5)?)", field, re.I)
        if match:
            candidate_grade = float(match.group(1))
            if 0 < candidate_grade <= 10:
                grade = candidate_grade
                break
    if grade is None:
        return None

    between = fields[date_index + 1:price_index]
    auction_house = between[0] if between else "inconnue"
    sale_type = between[1] if len(between) > 1 else ""
    cert = next((field for field in between if re.fullmatch(r"\d{6,}", field)), "")
    if "·" in auction_house and not sale_type:
        auction_house, _, sale_type = auction_house.partition("·")
    context_parts = ["PSA APR", auction_house, sale_type]
    if cert:
        context_parts.append(f"cert {cert}")
    sale = ComparableSale(
        price=usd_to_eur(price_usd, usd_per_eur),
        source="psa",
        grader="PSA",
        grade=grade,
        sold_at=sold_at,
        context=" | ".join(part for part in context_parts if part)[:300],
        exact_card=True,
        match_score=100,
    )
    return sale, cert, auction_house.strip().lower()


def parse_psa_apr_sales(
    rows: list[str],
    usd_per_eur: float,
    now: Optional[datetime] = None,
) -> list[ComparableSale]:
    sales: list[ComparableSale] = []
    seen = set()
    for row in rows:
        parsed = _parse_psa_apr_sale_row(row, usd_per_eur, now)
        if parsed is None:
            continue
        sale, cert, auction_house = parsed
        key = (
            cert,
            sale.sold_at.date().isoformat() if sale.sold_at else "",
            round(sale.price, 2),
            sale.grade,
            auction_house,
        )
        if key in seen:
            continue
        seen.add(key)
        sales.append(sale)
        if len(sales) >= PSA_APR_MAX_RESULTS:
            break
    return sales


def parse_psa_apr_grade_metadata(
    rows: list[str], target_grade: float, usd_per_eur: float
) -> tuple[Optional[int], Optional[int], Optional[float]]:
    target_label = f"{target_grade:g}"
    for row in rows:
        fields = _split_psa_apr_row(row)
        if not fields or not re.fullmatch(
            rf"PSA\s*{re.escape(target_label)}", fields[0], re.I
        ):
            continue
        if len(fields) < 4:
            continue
        most_recent_usd = parse_psa_apr_usd(fields[1])
        numeric_tail = []
        for field in fields[2:]:
            if re.fullmatch(r"[\d,]+", field):
                numeric_tail.append(int(field.replace(",", "")))
        population = numeric_tail[-2] if len(numeric_tail) >= 2 else None
        pop_higher = numeric_tail[-1] if numeric_tail else None
        most_recent = (
            usd_to_eur(most_recent_usd, usd_per_eur)
            if most_recent_usd is not None
            else None
        )
        return population, pop_higher, most_recent
    return None, None, None


def parse_psa_apr_page(
    rows: list[str],
    target_grade: float,
    usd_per_eur: float,
    now: Optional[datetime] = None,
) -> PsaAprData:
    population, pop_higher, most_recent = parse_psa_apr_grade_metadata(
        rows, target_grade, usd_per_eur
    )
    return PsaAprData(
        sales=parse_psa_apr_sales(rows, usd_per_eur, now),
        population=population,
        pop_higher=pop_higher,
        most_recent_price=most_recent,
    )


def scrape_psa_apr(
    page,
    lot: Lot,
    usd_per_eur: Optional[float] = None,
    now: Optional[datetime] = None,
) -> PsaAprData:
    """Recherche APR publique; toute erreur/ambiguïté provoque un fast-fail."""
    if (
        not PSA_APR_ENABLED
        or (lot.grader or "").upper() != "PSA"
        or _target_grade(lot) is None
        or not psa_apr_identity_is_sufficient(lot)
    ):
        return PsaAprData([], note="APR non applicable")

    rate = usd_per_eur if usd_per_eur is not None else get_psa_apr_usd_per_eur()
    if rate is None:
        return PsaAprData([], note="conversion USD/EUR indisponible")

    query = psa_apr_search_query(lot)
    log(f"APR recherche: {query}")
    try:
        page.goto(
            PSA_APR_SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=PSA_APR_NAV_TIMEOUT,
        )
        search = page.locator(
            'input[name="q"], input[placeholder*="Search PSA-Graded Items"]'
        ).first
        if search.count() == 0:
            return PsaAprData([], note="formulaire APR indisponible")
        search.fill(query, timeout=min(PSA_APR_NAV_TIMEOUT, 2500))
        submit = page.locator(
            '[role="search"] button[aria-label="Search"], '
            'button:has-text("Search")'
        ).first
        if submit.count() == 0:
            return PsaAprData([], note="recherche APR indisponible")
        submit.click(timeout=min(PSA_APR_NAV_TIMEOUT, 2500))
        page.wait_for_timeout(700)
        body = page.locator("body").inner_text(timeout=min(PSA_APR_NAV_TIMEOUT, 2500))
    except Exception as error:
        log(f"APR: {type(error).__name__} -> abandon APR pour cette carte")
        return PsaAprData([], note=f"APR indisponible ({type(error).__name__})")

    lower_body = body.lower()
    if any(
        marker in lower_body
        for marker in (
            "captcha", "access denied", "verify you are human",
            "pardon our interruption", "too many requests",
        )
    ):
        log("APR: refus/anti-bot détecté -> abandon APR pour cette carte")
        return PsaAprData([], note="APR refusé ou anti-bot")

    current_url = page.url
    detail_candidate = None
    detail_score = 0
    detail_reason = ""
    if "auction results" in lower_body and current_url.rstrip("/") != PSA_APR_SEARCH_URL:
        detail_score, detail_reason = psa_apr_match_score(lot, body)
        if detail_score >= PSA_APR_MATCH_MIN_SCORE:
            detail_candidate = PsaAprCandidate(current_url, body)

    if detail_candidate is None:
        candidates: list[PsaAprCandidate] = []
        links = page.locator('a[href*="/auctionprices/"]')
        for index in range(min(links.count(), 120)):
            link = links.nth(index)
            try:
                href = link.get_attribute("href") or ""
                text = (link.inner_text(timeout=400) or "").strip()
            except Exception:
                continue
            url = urljoin(PSA_APR_BASE, href)
            if not text or url.rstrip("/") == PSA_APR_SEARCH_URL:
                continue
            candidates.append(PsaAprCandidate(url, f"{text}\n{url}"))
        detail_candidate, detail_score, detail_reason = choose_psa_apr_candidate(
            lot, candidates
        )

    if detail_candidate is None:
        log(f"APR correspondance: rejetée ({detail_reason})")
        return PsaAprData([], note=detail_reason)

    log(
        f"APR correspondance: score {detail_score} ({detail_reason}) | "
        f"{detail_candidate.url}"
    )
    try:
        if page.url != detail_candidate.url:
            page.goto(
                detail_candidate.url,
                wait_until="domcontentloaded",
                timeout=PSA_APR_NAV_TIMEOUT,
            )
        detail_body = page.locator("body").inner_text(
            timeout=min(PSA_APR_NAV_TIMEOUT, 2500)
        )
        verified_score, verified_reason = psa_apr_match_score(lot, detail_body)
        if verified_score < PSA_APR_MATCH_MIN_SCORE:
            log(f"APR correspondance: fiche rejetée ({verified_reason})")
            return PsaAprData([], note="fiche APR non confirmée")
        table_rows = page.locator("tr")
        rows = [
            table_rows.nth(index).inner_text(timeout=500)
            for index in range(min(table_rows.count(), 250))
        ]
    except Exception as error:
        log(f"APR: {type(error).__name__} sur la fiche -> abandon APR")
        return PsaAprData([], note=f"fiche APR indisponible ({type(error).__name__})")

    target_grade = _target_grade(lot)
    data = parse_psa_apr_page(rows, target_grade, rate, now)
    data.matched_url = detail_candidate.url
    data.match_score = verified_score
    exact_count = sum(sale.grade == target_grade for sale in data.sales)
    log(f"APR ventes exactes PSA {target_grade:g}: {exact_count}")
    log(
        f"APR population: {data.population if data.population is not None else '?'} | "
        f"higher {data.pop_higher if data.pop_higher is not None else '?'}"
    )
    return data


def ebay_queries_for_lot(lot: Lot) -> list[str]:
    """
    Génère plusieurs recherches, de la plus stricte à la plus large.
    Point clé: si GCC fournit un numéro/référence, on peut retrouver la même carte
    même lorsque le nom eBay est en anglais (Otaquin -> Oshawott, etc.).
    """
    ident = extract_card_identity(lot)
    core = ident["core"]
    ref = ident["ref"]
    year = ident["year"]
    language = ident["language"]
    series = ident["series"]

    queries = []

    def add(parts):
        q = " ".join(str(p).strip() for p in parts if p and str(p).strip())
        q = re.sub(r"\s+", " ", q).strip()
        if q and q not in queries:
            queries.append(q)

    # 1. Nom GCC + référence + grader + grade.
    add(["Pokemon", core, series, ref, lot.grader, lot.grade])

    # 2. Référence + année + grader + grade:
    #    indépendant du nom français/anglais du Pokémon.
    if ref:
        add(["Pokemon", series, ref, year, lot.grader, lot.grade])

    # 3. Référence + grade sans imposer la société de grading.
    if ref:
        add(["Pokemon", series, ref, year, lot.grade])

    # 4. Nom + grader/grade, utile si la référence n'est pas visible dans l'annonce eBay.
    add(["Pokemon", core, series, lot.grader, lot.grade])

    # 5. Recherche plus large, dernier recours.
    if ref:
        add(["Pokemon", series, ref, year])
    else:
        add(["Pokemon", core, series, year, language])

    return queries


def ebay_queries_within_budget(
    lot: Lot, max_queries: Optional[int] = None
) -> list[str]:
    limit = EBAY_MAX_QUERIES_PER_CARD if max_queries is None else max_queries
    return ebay_queries_for_lot(lot)[:max(0, limit)]


def ebay_card_validation_allowed(
    cards_already_validated: int, max_cards: Optional[int] = None
) -> bool:
    limit = EBAY_MAX_CARDS_PER_RUN if max_cards is None else max_cards
    return EBAY_ENABLED and cards_already_validated < max(0, limit)


def ebay_result_match_score(lot: Lot, title: str) -> tuple[int, str]:
    """
    Score de matching eBay.
    La référence de carte est le signal le plus fort et permet de ne pas dépendre
    du nom français du Pokémon.

    Retour:
      score >= 70 : comparable fort
      50-69       : comparable acceptable si grade/grader cohérent
      < 50        : rejeté
    """
    ident = extract_card_identity(lot)
    raw_title = title or ""
    t = raw_title.lower()
    compact = re.sub(r"\s+", "", t)

    if "pokemon" not in t and "pokémon" not in t:
        return 0, "pas Pokemon"

    if any(word in t for word in SEALED_KEYWORDS):
        return 0, "produit scellé/accessoire"

    score = 0
    reasons = []

    # Référence exacte = très forte identité de carte.
    ref = ident["ref"]
    ref_matched = False
    if ref:
        ref_forms = {
            ref.lower().replace(" ", ""),
            ref.lower().replace("#", "").replace(" ", ""),
        }
        for rf in ref_forms:
            if rf and rf in compact.replace("#", ""):
                ref_matched = True
                score += 60
                reasons.append("référence")
                break

    # Année.
    if ident["year"] and ident["year"] in t:
        score += 8
        reasons.append("année")

    # Série / set.
    series = (ident.get("series") or "").strip()
    if series:
        series_tokens = [
            tok.lower()
            for tok in re.findall(r"[A-Za-zÀ-ÿ0-9'-]{3,}", series)
            if tok.lower() not in {"pokemon", "pokémon", "the", "de", "du", "des", "set"}
        ]
        series_hits = sum(1 for tok in series_tokens[:5] if tok in t)
        if series_hits:
            score += min(18, 6 * series_hits)
            reasons.append(f"série({series_hits})")

    # Nom: utile mais non obligatoire si la référence correspond.
    stop = {
        "ex", "gx", "v", "vmax", "vstar", "pokemon", "pokémon",
        "the", "de", "du", "des", "la", "le", "les", "and", "et",
        "psa", "pca", "cgc", "bgs", "ccc",
    }
    tokens = [
        x.lower()
        for x in re.findall(r"[A-Za-zÀ-ÿ0-9'-]{3,}", ident["core"])
        if x.lower() not in stop
    ]
    name_hits = sum(1 for tok in tokens[:5] if tok in t)
    if name_hits:
        score += min(20, 8 * name_hits)
        reasons.append(f"nom({name_hits})")

    # Si pas de référence, le nom devient obligatoire.
    if not ref_matched and name_hits == 0:
        return 0, "ni référence ni nom"

    # Grade/grader de l'annonce.
    result_grader, result_grade_text = parse_grader_grade(raw_title)
    result_grade = None
    if result_grade_text:
        try:
            result_grade = float(result_grade_text)
        except ValueError:
            pass

    try:
        target_grade = float(lot.grade) if lot.grade else None
    except ValueError:
        target_grade = None

    if target_grade is not None and result_grade is not None:
        diff = abs(result_grade - target_grade)
        if diff == 0:
            score += 20
            reasons.append("grade exact")
        elif diff <= 1:
            score += 8
            reasons.append("grade voisin")
        else:
            score -= 15
            reasons.append("grade éloigné")
    elif target_grade is not None:
        score -= 10
        reasons.append("grade eBay absent")

    if lot.grader and result_grader:
        if result_grader == lot.grader:
            score += 10
            reasons.append("grader exact")
        else:
            # Autorisé: on veut justement comparer PSA/PCA/CGC/etc.
            score += 2
            reasons.append(f"autre grader {result_grader}")

    # Langue explicite contradictoire: pénalité, pas rejet automatique si ref exacte.
    lang = ident["language"].lower()
    language_terms = {
        "french": {"french", "français", "francais"},
        "japanese": {"japanese", "japonais"},
        "english": {"english", "anglais"},
        "german": {"german", "allemand"},
        "spanish": {"spanish", "espagnol"},
        "italian": {"italian", "italien"},
    }
    all_terms = set().union(*language_terms.values())
    present = {x for x in all_terms if x in t}
    if lang and present:
        expected = language_terms.get(lang, {lang})
        if present & expected:
            score += 8
            reasons.append("langue")
        else:
            score -= 25
            reasons.append("langue différente")

    return score, ", ".join(reasons)


def robust_median_prices(prices: list[float]) -> list[float]:
    """
    Écarte uniquement les outliers extrêmes lorsqu'il y a assez de données.
    On reste volontairement conservateur.
    """
    comparables = [ComparableSale(price=price) for price in prices if price > 0]
    kept, _ = filter_price_outliers(comparables)
    return sorted(sale.price for sale in kept)


def scrape_ebay_sold(page, lot: Lot) -> list[HistoricalSale]:
    """
    Recherche publique eBay Sold/Completed sans API Developer.

    V3.3 FAST-FAIL:
    - budget de requêtes indépendant pour chaque carte;
    - budget séparé de cartes validées pendant le run;
    - timeout navigation court;
    - abandon immédiat si la page eBay renvoie 0 résultat visible;
    - abandon immédiat après timeout/anti-bot;
    - ne ralentit plus le scan GCC de plusieurs minutes.
    """
    if not EBAY_ENABLED:
        return []

    collected: list[HistoricalSale] = []
    seen = set()

    queries = ebay_queries_within_budget(lot)
    log(f"eBay: {len(queries)} requête(s) max pour {lot.title}")

    for q_index, query in enumerate(queries, start=1):
        url = (
            f"{EBAY_BASE}/sch/i.html"
            f"?_nkw={quote_plus(query)}"
            f"&LH_Sold=1&LH_Complete=1&_ipg=120&_sop=13"
        )

        log(f"eBay q{q_index}: {query}")

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=EBAY_NAV_TIMEOUT)
            page.wait_for_timeout(EBAY_PAGE_WAIT_MS)
            body = page.locator("body").inner_text(timeout=min(TEXT_TIMEOUT, 2500))
        except Exception as e:
            log(f"eBay q{q_index}: {type(e).__name__} -> abandon eBay pour cette carte")
            return []

        lower_body = body.lower()
        if (
            "pardon our interruption" in lower_body
            or "vérifiez votre identité" in lower_body
            or "verify your identity" in lower_body
            or "captcha" in lower_body
        ):
            log("eBay: anti-bot/captcha détecté -> abandon eBay pour cette carte")
            return []

        cards = page.locator("li.s-item")
        raw_count = min(cards.count(), 120)

        # Si eBay ne fournit même aucun item structuré, inutile d'insister.
        if raw_count == 0:
            log(f"eBay q{q_index}: 0 résultat visible -> abandon eBay pour cette carte")
            return []

        matched_this_query = 0

        for i in range(raw_count):
            try:
                txt = (cards.nth(i).inner_text(timeout=600) or "").strip()
            except Exception:
                continue

            if not txt:
                continue

            low = txt.lower()
            if "best offer accepted" in low or "meilleure offre acceptée" in low:
                continue

            lines = [x.strip() for x in txt.splitlines() if x.strip()]
            title = lines[0] if lines else ""
            if title.lower() in {"shop on ebay", "explorer sur ebay"} and len(lines) > 1:
                title = lines[1]

            score, reason = ebay_result_match_score(lot, title)
            if score < 50:
                continue

            pm = EBAY_MONEY_RE.search(txt)
            if not pm:
                continue

            try:
                price = normalize_ebay_eur(pm.group(1))
            except Exception:
                continue

            if not 1 <= price <= 50000:
                continue

            grader, grade_text = parse_grader_grade(title)
            grade = None
            if grade_text:
                try:
                    grade = float(grade_text)
                except ValueError:
                    pass

            if lot.grade and grade is None:
                continue

            key = (
                re.sub(r"\s+", " ", title.lower()),
                round(price, 2),
                grader,
                grade,
            )
            if key in seen:
                continue
            seen.add(key)

            collected.append(
                ComparableSale(
                    price=price,
                    source="ebay",
                    grader=grader,
                    grade=grade,
                    sold_at=parse_sale_date(txt),
                    context=f"eBay SOLD score={score} ({reason}) | {title}"[:300],
                    exact_card=score >= 70,
                    match_score=score,
                )
            )
            matched_this_query += 1

            if len(collected) >= EBAY_MAX_RESULTS:
                break

        log(
            f"eBay q{q_index}: {raw_count} résultats visibles, "
            f"{matched_this_query} nouveau(x) comparable(s), total={len(collected)}"
        )

        # Si on a assez de comparables, on s'arrête.
        if len(collected) >= 3:
            break

        # Si la première requête a des résultats mais zéro comparable, on tente une seule requête plus large.
        # Après la deuxième, on s'arrête quoi qu'il arrive.

    return collected[:EBAY_MAX_RESULTS]


def _target_grade(lot: Lot) -> Optional[float]:
    try:
        grade = float(lot.grade) if lot.grade is not None else None
    except (TypeError, ValueError):
        return None
    return grade if grade is not None and 0 < grade <= 10 else None


def empirical_price_for_target_grader(
    sale: ComparableSale,
    target_grader: str,
    target_grade: float,
    ratios: list[EmpiricalGraderRatio],
) -> Optional[float]:
    """Normalise seulement avec un ratio fourni et suffisamment documenté."""
    if sale.grade != target_grade:
        return None
    if sale.grader == target_grader and sale.grade == target_grade:
        return sale.price
    eligible = [
        ratio for ratio in ratios
        if ratio.source_grader == sale.grader
        and ratio.target_grader == target_grader
        and ratio.grade == target_grade
        and ratio.sample_size >= MIN_EMPIRICAL_GRADER_RATIO_SALES
        and ratio.target_per_source_ratio > 0
        and bool(ratio.sources)
        and all(source in VALID_COMPARABLE_SOURCES for source in ratio.sources)
    ]
    if not eligible:
        return None
    evidence = max(eligible, key=lambda ratio: (ratio.sample_size, ratio.measured_at))
    return sale.price * evidence.target_per_source_ratio


def normalize_comparables_for_target_grader(
    sales: list[ComparableSale],
    target_grader: str,
    target_grade: float,
    ratios: list[EmpiricalGraderRatio],
) -> list[ComparableSale]:
    """Convertit les autres graders uniquement via des ratios empiriques admissibles."""
    normalized = []
    for sale in sales:
        price = empirical_price_for_target_grader(
            sale, target_grader, target_grade, ratios
        )
        if price is None or sale.grader == target_grader:
            continue
        normalized.append(
            ComparableSale(
                price=price,
                source=sale.source,
                grader=target_grader,
                grade=target_grade,
                sold_at=sale.sold_at,
                context=(
                    f"normalisé empiriquement {sale.grader}→{target_grader} | "
                    f"{sale.context}"
                )[:300],
                exact_card=sale.exact_card,
                match_score=sale.match_score,
            )
        )
    return normalized


def _same_target_grader(lot: Lot, sale: ComparableSale) -> bool:
    if not lot.grader:
        return True
    return bool(sale.grader) and sale.grader.upper() == lot.grader.upper()


def _nearest_grade_group(
    sales: list[ComparableSale], target_grade: float, lower: bool
) -> list[ComparableSale]:
    candidates = [
        sale for sale in sales
        if sale.grade is not None
        and (sale.grade < target_grade if lower else sale.grade > target_grade)
    ]
    if not candidates:
        return []
    nearest_grade = (
        max(sale.grade for sale in candidates if sale.grade is not None)
        if lower
        else min(sale.grade for sale in candidates if sale.grade is not None)
    )
    return [sale for sale in candidates if sale.grade == nearest_grade]


def _select_pricing_comparables(
    lot: Lot,
    sales: list[ComparableSale],
    grader_ratios: Optional[list[EmpiricalGraderRatio]] = None,
) -> ComparableSelection:
    valid = [sale for sale in sales if sale.price > 0]
    exact_card = [sale for sale in valid if sale.exact_card]
    # Une identité de carte seulement probable reste un signal secondaire:
    # elle ne peut créer ni valeur achetable ni arbitrage de grade.
    identity_candidates = exact_card
    target_grade = _target_grade(lot)
    if not lot.grader or target_grade is None:
        return ComparableSelection(
            primary=[],
            lower_bounds=[],
            upper_bounds=[],
            secondary=valid,
            rationale="",
        )

    graded = [sale for sale in identity_candidates if sale.grade is not None]
    same_grader = [sale for sale in graded if _same_target_grader(lot, sale)]
    other_graders = [sale for sale in graded if sale not in same_grader]
    same_exact = [sale for sale in same_grader if sale.grade == target_grade]
    other_exact = [sale for sale in other_graders if sale.grade == target_grade]
    same_lower = _nearest_grade_group(same_grader, target_grade, lower=True)
    same_higher = _nearest_grade_group(same_grader, target_grade, lower=False)

    # Une seule vraie vente même grader/même grade suffit à devenir la référence.
    # Le volume d'autres graders reste secondaire et ne peut pas déplacer sa médiane.
    if same_exact:
        secondary = [sale for sale in valid if sale not in same_exact + same_lower + same_higher]
        return ComparableSelection(
            primary=same_exact,
            lower_bounds=same_lower,
            upper_bounds=same_higher,
            secondary=secondary,
            rationale=(
                f"{len(same_exact)} même grader/grade (signal principal); "
                f"{len(same_lower) + len(same_higher)} grade(s) voisin(s) même grader; "
                f"{len(other_exact)} autre(s) grader(s) au grade exact en validation"
            ),
        )

    # Sans grade exact, le grade inférieur du même grader peut démontrer un
    # arbitrage conservateur, mais seulement si le prix courant ne le dépasse pas.
    if same_lower:
        robust_lower, _ = filter_price_outliers(same_lower)
        lower_market = median(sale.price for sale in robust_lower)
        if lot.current_price is not None and lot.current_price <= lower_market:
            lower_grade = same_lower[0].grade
            secondary = [sale for sale in valid if sale not in same_lower + same_higher]
            return ComparableSelection(
                primary=same_lower,
                lower_bounds=[],
                upper_bounds=same_higher,
                secondary=secondary,
                rationale=(
                    f"grade arbitrage: cible {target_grade:g} à {lot.current_price:.2f} € "
                    f"<= marché robuste grade {lower_grade:g} même grader ({lower_market:.2f} €); "
                    f"{len(other_exact)} autre(s) grader(s) au grade exact en validation"
                ),
                grade_arbitrage=True,
                arbitrage_reference_grade=lower_grade,
                arbitrage_reference_value=lower_market,
            )

    # Les autres graders ne deviennent exploitables qu'après une normalisation
    # empirique suffisamment documentée. Sans ratio, ils restent secondaires.
    if other_exact:
        normalized = normalize_comparables_for_target_grader(
            other_exact, lot.grader, target_grade, grader_ratios or []
        )
        if normalized:
            return ComparableSelection(
                primary=normalized,
                lower_bounds=[],
                upper_bounds=[],
                secondary=valid,
                rationale=(
                    f"aucune vente {lot.grader or 'grader cible'} au grade exact; "
                    f"{len(normalized)} vente(s) normalisée(s) par ratio(s) empirique(s)"
                ),
                depends_on_other_graders=True,
            )

    return ComparableSelection([], [], [], valid, "")


def diagnose_gcc_comparables(
    lot: Lot,
    sales: list[ComparableSale],
    estimate: Optional[MarketEstimate] = None,
    now: Optional[datetime] = None,
    grader_ratios: Optional[list[EmpiricalGraderRatio]] = None,
) -> GccComparableDiagnostics:
    """Observe les étapes GCC existantes sans participer à la valorisation."""
    valid = [sale for sale in sales if sale.price > 0]
    identity = [sale for sale in valid if sale.exact_card]
    graded = [sale for sale in identity if sale.grade is not None]
    target_grade = _target_grade(lot)
    same_grader = [
        sale for sale in graded
        if lot.grader and _same_target_grader(lot, sale)
    ]
    exact_grade = [
        sale for sale in same_grader
        if target_grade is not None and sale.grade == target_grade
    ]
    lower_grade = [
        sale for sale in same_grader
        if target_grade is not None and sale.grade < target_grade
    ]
    higher_grade = [
        sale for sale in same_grader
        if target_grade is not None and sale.grade > target_grade
    ]
    nearest_lower = (
        _nearest_grade_group(same_grader, target_grade, lower=True)
        if target_grade is not None else []
    )
    nearest_higher = (
        _nearest_grade_group(same_grader, target_grade, lower=False)
        if target_grade is not None else []
    )
    known_graders = {grader.upper() for grader in GRADERS}
    invalid_grader = [
        sale for sale in identity
        if not sale.grader or sale.grader.upper() not in known_graders
    ]
    other_exact = [
        sale for sale in graded
        if target_grade is not None
        and sale.grade == target_grade
        and sale not in same_grader
        and sale not in invalid_grader
    ]
    normalized = (
        normalize_comparables_for_target_grader(
            other_exact, lot.grader, target_grade, grader_ratios or []
        )
        if lot.grader and target_grade is not None else []
    )
    kept = estimate.kept_comparables if estimate is not None else []
    ages = [sale_age_days(sale, now) for sale in kept if sale.sold_at is not None]

    selection = _select_pricing_comparables(lot, sales, grader_ratios)
    return GccComparableDiagnostics(
        raw_count=len(sales),
        identity_count=len(identity),
        same_grader_count=len(same_grader),
        exact_grade_count=len(exact_grade),
        lower_grade_count=len(lower_grade),
        higher_grade_count=len(higher_grade),
        nearest_neighbor_count=len(nearest_lower) + len(nearest_higher),
        inter_grader_candidates=len(other_exact),
        normalized_count=len(normalized),
        invalid_grader_count=len(invalid_grader),
        invalid_grade_count=len(identity) - len(graded),
        insufficient_identity_count=len(valid) - len(identity),
        ratio_rejected_count=max(0, len(other_exact) - len(normalized)),
        outlier_count=(
            len(estimate.rejected_outliers) if estimate is not None else 0
        ),
        kept_count=len(kept),
        dated_count=len(ages),
        under_30_days_count=sum(age is not None and age < 30 for age in ages),
        days_30_to_90_count=sum(
            age is not None and 30 <= age <= 90 for age in ages
        ),
        over_90_days_count=sum(age is not None and age > 90 for age in ages),
        grade_arbitrage=selection.grade_arbitrage,
    )


def format_gcc_comparable_diagnostics(
    lot: Lot, diagnostics: GccComparableDiagnostics
) -> str:
    card_name = extract_card_identity(lot)["core"] or lot.title or "lot inconnu"
    return "\n".join(
        (
            f"DIAG GCC {card_name}: brut {diagnostics.raw_count} → "
            f"identité {diagnostics.identity_count} → "
            f"même grader {diagnostics.same_grader_count} → "
            f"grade exact {diagnostics.exact_grade_count}",
            f"grades inf/sup {diagnostics.lower_grade_count}/"
            f"{diagnostics.higher_grade_count} → "
            f"voisins {diagnostics.nearest_neighbor_count} → "
            f"inter-graders {diagnostics.inter_grader_candidates} → "
            f"normalisés {diagnostics.normalized_count} → "
            f"outliers {diagnostics.outlier_count} → retenus {diagnostics.kept_count}",
            f"Rejets: grader {diagnostics.invalid_grader_count} | "
            f"grade {diagnostics.invalid_grade_count} | "
            f"identité {diagnostics.insufficient_identity_count} | "
            f"ratio inter-grader {diagnostics.ratio_rejected_count}",
            f"Dates retenues: connues {diagnostics.dated_count} | "
            f"<30j {diagnostics.under_30_days_count} | "
            f"30–90j {diagnostics.days_30_to_90_count} | "
            f">90j {diagnostics.over_90_days_count}",
        )
    )


def log_gcc_comparable_diagnostics(
    lot: Lot, diagnostics: GccComparableDiagnostics
) -> None:
    for line in format_gcc_comparable_diagnostics(lot, diagnostics).splitlines():
        log(line)


def _comparable_weight(lot: Lot, sale: ComparableSale, now: Optional[datetime]) -> float:
    weight = recency_weight(sale.sold_at, now)
    if not sale.exact_card:
        weight *= 0.70
    target_grade = _target_grade(lot)
    if target_grade is not None and sale.grade is not None and sale.grade != target_grade:
        weight *= 0.65
    if sale.source == "ebay":
        weight *= 0.90
    weight *= max(0.60, min(1.0, sale.match_score / 100))
    return max(0.05, weight)


def price_dispersion(comparables: list[ComparableSale]) -> str:
    prices = [sale.price for sale in comparables if sale.price > 0]
    if len(prices) < 2:
        return "non mesurable"
    center = median(prices)
    if center <= 0:
        return "élevée"
    robust_spread = (percentile(prices, 0.75) - percentile(prices, 0.25)) / center
    if robust_spread <= 0.15:
        return "faible"
    if robust_spread <= 0.35:
        return "moyenne"
    return "élevée"


def assess_liquidity(
    comparables: list[ComparableSale], now: Optional[datetime] = None
) -> tuple[str, int, int]:
    ages = [sale_age_days(sale, now) for sale in comparables]
    dated_ages = [age for age in ages if age is not None]
    recent_90 = sum(age <= 90 for age in dated_ages)
    recent_180 = sum(age <= 180 for age in dated_ages)
    count = len(comparables)
    if count >= 5 and recent_90 >= 3:
        liquidity = "élevée"
    elif (count >= 3 and recent_180 >= 2) or (count >= 5 and recent_90 >= 1):
        liquidity = "moyenne"
    else:
        liquidity = "faible"
    return liquidity, recent_90, len(dated_ages)


def _source_consistency(comparables: list[ComparableSale]) -> Optional[bool]:
    grouped: dict[str, list[float]] = {}
    for sale in comparables:
        grouped.setdefault(sale.source, []).append(sale.price)
    medians = [median(prices) for prices in grouped.values() if len(prices) >= 2]
    if len(medians) < 2:
        return None
    return max(medians) / min(medians) <= 1.35


def adaptive_discount_threshold(
    count: int,
    dispersion: str,
    liquidity: str,
    recent_90_count: int,
    dated_count: int,
    exact_grade_count: int,
    source_consistent: Optional[bool] = None,
    depends_on_other_graders: bool = False,
) -> float:
    """Seuil documenté: ~40% (<=2), ~35% (3–4), 30% (>=5), puis prudence qualité."""
    if count <= 2:
        threshold = 40.0
    elif count <= 4:
        threshold = 35.0
    else:
        threshold = 30.0

    if dispersion == "élevée":
        threshold += 5.0
    if liquidity == "faible":
        threshold += 2.0
    if dated_count and recent_90_count == 0:
        threshold += 3.0
    elif dated_count >= 2 and recent_90_count / dated_count < 0.5:
        threshold += 2.0
    if count and exact_grade_count / count < 0.5:
        threshold += 2.0
    if source_consistent is False:
        threshold += 3.0
    if depends_on_other_graders:
        threshold += 5.0
    return max(MIN_DISCOUNT, min(45.0, threshold))


def determine_confidence(
    count: int,
    exact_card_count: int,
    exact_grade_count: int,
    same_grader_count: int,
    recent_90_count: int,
    dated_count: int,
    dispersion: str,
    liquidity: str,
    source_consistent: Optional[bool],
    depends_on_other_graders: bool = False,
) -> str:
    """Classement par règles explicites, sans faux score numérique sur 100."""
    exact_card_ratio = exact_card_count / count if count else 0.0
    exact_grade_ratio = exact_grade_count / count if count else 0.0
    recent_ratio = recent_90_count / dated_count if dated_count else 0.0
    coherent_sources = source_consistent is not False

    if depends_on_other_graders:
        return "faible"

    if (
        count >= 5
        and exact_card_ratio >= 0.80
        and exact_grade_ratio >= 0.60
        and same_grader_count >= 2
        and dated_count >= 3
        and recent_ratio >= 0.50
        and dispersion != "élevée"
        and liquidity == "élevée"
        and coherent_sources
    ):
        return "élevée"
    if (
        count >= 3
        and exact_card_ratio >= 0.65
        and exact_grade_ratio >= 0.50
        and same_grader_count >= 1
        and dispersion != "élevée"
        and liquidity != "faible"
        and coherent_sources
    ):
        return "moyenne"
    return "faible"


def build_market_estimate(
    lot: Lot,
    sales: list[ComparableSale],
    now: Optional[datetime] = None,
    grader_ratios: Optional[list[EmpiricalGraderRatio]] = None,
) -> Optional[MarketEstimate]:
    if not lot.grader or _target_grade(lot) is None:
        return None
    selection = _select_pricing_comparables(lot, sales, grader_ratios)
    if not selection.primary:
        return None
    primary_kept, rejected = filter_price_outliers(selection.primary)
    if not primary_kept:
        return None

    primary_prices = [
        (sale.price, _comparable_weight(lot, sale, now)) for sale in primary_kept
    ]
    low = weighted_quantile(primary_prices, 0.25)
    central = weighted_quantile(primary_prices, 0.50)
    high = weighted_quantile(primary_prices, 0.75)

    lower_kept, lower_rejected = filter_price_outliers(selection.lower_bounds)
    upper_kept, upper_rejected = filter_price_outliers(selection.upper_bounds)
    rejected.extend(lower_rejected + upper_rejected)
    if lower_kept:
        lower_prices = [
            (sale.price, _comparable_weight(lot, sale, now)) for sale in lower_kept
        ]
        low = min(low, weighted_quantile(lower_prices, 0.50))
    if upper_kept:
        upper_prices = [
            (sale.price, _comparable_weight(lot, sale, now)) for sale in upper_kept
        ]
        high = max(high, weighted_quantile(upper_prices, 0.50))
    low, high = min(low, central), max(high, central)

    kept = primary_kept + lower_kept + upper_kept
    liquidity, recent_90_count, dated_count = assess_liquidity(kept, now)
    dispersion = price_dispersion(kept)
    target_grade = _target_grade(lot)
    exact_grade_count = sum(
        target_grade is None or sale.grade == target_grade for sale in kept
    )
    same_grader_count = sum(
        bool(lot.grader) and sale.grader == lot.grader for sale in kept
    )
    exact_card_count = sum(sale.exact_card for sale in kept)
    source_consistent = _source_consistency(kept)
    threshold = adaptive_discount_threshold(
        len(kept), dispersion, liquidity, recent_90_count, dated_count,
        exact_grade_count, source_consistent, selection.depends_on_other_graders,
    )
    confidence = determine_confidence(
        len(kept), exact_card_count, exact_grade_count, same_grader_count,
        recent_90_count, dated_count, dispersion, liquidity, source_consistent,
        selection.depends_on_other_graders,
    )
    if selection.grade_arbitrage:
        confidence = "faible"
    source_counts: dict[str, int] = {}
    for sale in kept:
        source_counts[sale.source] = source_counts.get(sale.source, 0) + 1

    return MarketEstimate(
        low=low,
        central=central,
        high=high,
        kept_comparables=kept,
        rejected_outliers=rejected,
        recent_90_count=recent_90_count,
        dated_count=dated_count,
        liquidity=liquidity,
        dispersion=dispersion,
        confidence=confidence,
        adaptive_discount_pct=threshold,
        rationale=selection.rationale,
        source_counts=source_counts,
        exact_grade_count=exact_grade_count,
        same_grader_count=same_grader_count,
        source_consistent=source_consistent,
        grade_arbitrage=selection.grade_arbitrage,
        arbitrage_reference_grade=selection.arbitrage_reference_grade,
        arbitrage_reference_value=selection.arbitrage_reference_value,
    )


def estimate_cross_grader_market(
    lot: Lot,
    sales: list[ComparableSale],
    grader_ratios: Optional[list[EmpiricalGraderRatio]] = None,
) -> tuple[Optional[float], str, str]:
    """Wrapper compatible autour du nouveau moteur à fourchette."""
    estimate = build_market_estimate(lot, sales, grader_ratios=grader_ratios)
    if estimate is None:
        return None, "faible", ""
    return estimate.central, estimate.confidence, estimate.rationale


def _opportunity_from_estimate(
    lot: Lot,
    estimate: MarketEstimate,
    gcc_sales: list[ComparableSale],
    ebay_sales: Optional[list[ComparableSale]] = None,
    ebay_note: str = "",
    psa_apr_sales: Optional[list[ComparableSale]] = None,
    psa_apr_estimate: Optional[MarketEstimate] = None,
    psa_apr_note: str = "",
    psa_apr_population: Optional[int] = None,
    psa_apr_pop_higher: Optional[int] = None,
    psa_apr_most_recent_price: Optional[float] = None,
) -> Opportunity:
    discount = (estimate.central - lot.current_price) / estimate.central * 100
    if estimate.grade_arbitrage:
        # La borne basse du grade inférieur est déjà la référence prudente:
        # aucune décote artificielle supplémentaire n'est appliquée.
        max_recommended = estimate.low
    else:
        max_recommended = estimate.low * (1 - estimate.adaptive_discount_pct / 100)
    return Opportunity(
        lot=lot,
        estimate=estimate,
        discount_pct=discount,
        max_recommended=max(0.0, max_recommended),
        gcc_comparables=gcc_sales,
        ebay_comparables=ebay_sales or [],
        ebay_note=ebay_note,
        psa_apr_comparables=psa_apr_sales or [],
        psa_apr_estimate=psa_apr_estimate,
        psa_apr_note=psa_apr_note,
        psa_apr_population=psa_apr_population,
        psa_apr_pop_higher=psa_apr_pop_higher,
        psa_apr_most_recent_price=psa_apr_most_recent_price,
    )


def opportunity_rejection_reason(op: Opportunity) -> str:
    if op.estimate.grade_arbitrage:
        if op.lot.current_price > op.max_recommended:
            return (
                f"grade arbitrage {op.lot.current_price:.2f} € > borne prudente "
                f"du grade inférieur {op.max_recommended:.2f} €"
            )
        return ""
    if op.discount_pct < op.estimate.adaptive_discount_pct:
        return (
            f"décote {op.discount_pct:.1f}% < seuil adaptatif "
            f"{op.estimate.adaptive_discount_pct:.1f}%"
        )
    # Une enchère ne peut que monter: prix fixes et enchères doivent donc être
    # sous la même limite prudente dès le moment de l'alerte.
    if op.lot.current_price > op.max_recommended:
        mode = "enchère" if op.lot.source_type == "auction" else "prix fixe"
        return (
            f"{mode} {op.lot.current_price:.2f} € > prix max prudent "
            f"{op.max_recommended:.2f} €"
        )
    return ""


def _estimate_failure_diagnostic(
    diagnostics: GccComparableDiagnostics,
) -> tuple[str, str]:
    if diagnostics.raw_count == 0:
        return "historique vide", REJECTION_EMPTY_HISTORY
    if diagnostics.identity_count == 0:
        return "identité carte insuffisante", REJECTION_INSUFFICIENT_IDENTITY
    if (
        diagnostics.exact_grade_count == 0
        and diagnostics.normalized_count == 0
        and not diagnostics.grade_arbitrage
    ):
        return (
            "aucun comparable exact/normalisable",
            REJECTION_INSUFFICIENT_COMPARABLES,
        )
    return (
        "comparables insuffisants ou grades non exploitables",
        REJECTION_INSUFFICIENT_COMPARABLES,
    )


def _opportunity_rejection_category(op: Opportunity, reason: str) -> str:
    if reason.startswith("décote "):
        return REJECTION_INSUFFICIENT_DISCOUNT
    if op.lot.source_type == "fixed" and "prix max prudent" in reason:
        return REJECTION_FIXED_ABOVE_MAX
    return REJECTION_OTHER


def _log_estimate(prefix: str, op: Opportunity) -> None:
    estimate = op.estimate
    mode = "grade arbitrage" if estimate.grade_arbitrage else "décote classique"
    log(
        f"{prefix} ({mode}): valeur {estimate.low:.2f}/{estimate.central:.2f}/{estimate.high:.2f} € | "
        f"comps {len(estimate.kept_comparables)} gardés, {len(estimate.rejected_outliers)} outlier(s) | "
        f"récents <90j {estimate.recent_90_count}/{estimate.dated_count} datés | "
        f"liquidité {estimate.liquidity} | dispersion {estimate.dispersion} | "
        f"seuil {estimate.adaptive_discount_pct:.0f}% | prix max {op.max_recommended:.2f} €"
    )


def _weaker_confidence(first: str, second: str) -> str:
    rank = {"faible": 0, "moyenne": 1, "élevée": 2}
    return first if rank.get(first, 0) <= rank.get(second, 0) else second


def _conservative_source_validation_estimate(
    gcc_estimate: MarketEstimate,
    validation_estimate: MarketEstimate,
    source_label: str,
) -> tuple[MarketEstimate, str]:
    gcc_market = gcc_estimate.central
    validation_market = validation_estimate.central
    ratio = validation_market / gcc_market if gcc_market > 0 else 1.0

    if 0.60 <= ratio <= 1.60:
        combined = replace(
            gcc_estimate,
            low=min(gcc_estimate.low, validation_estimate.low),
            central=min(gcc_estimate.central, validation_estimate.central),
            high=min(gcc_estimate.high, validation_estimate.high),
            confidence=_weaker_confidence(
                gcc_estimate.confidence, validation_estimate.confidence
            ),
            adaptive_discount_pct=max(
                gcc_estimate.adaptive_discount_pct,
                validation_estimate.adaptive_discount_pct,
            ),
            source_consistent=True,
            rationale=(
                f"{gcc_estimate.rationale}; {source_label} cohérent, "
                "borne source par source la plus prudente"
            ),
        )
        combined.low = min(combined.low, combined.central)
        combined.high = max(combined.high, combined.central)
        note = (
            f"{source_label} cohérent ({validation_market:.2f} € vs "
            f"GCC {gcc_market:.2f} €), valeurs prudentes retenues"
        )
        return combined, note

    chosen = validation_estimate if validation_market < gcc_market else gcc_estimate
    combined = replace(
        chosen,
        confidence="faible",
        source_consistent=False,
        adaptive_discount_pct=min(
            45.0, max(MIN_DISCOUNT, chosen.adaptive_discount_pct + 3)
        ),
        rationale=(
            f"{chosen.rationale}; {source_label} divergent, "
            "source la plus prudente retenue"
        ),
    )
    note = (
        f"{source_label} divergent ({validation_market:.2f} € vs "
        f"GCC {gcc_market:.2f} €): source la plus prudente retenue"
    )
    return combined, note


def validate_with_psa_apr(
    page,
    op: Opportunity,
    grader_ratios: Optional[list[EmpiricalGraderRatio]] = None,
    usd_per_eur: Optional[float] = None,
    now: Optional[datetime] = None,
) -> PsaAprValidationResult:
    """Valide l'estimation GCC avec une estimation APR indépendante."""
    try:
        data = scrape_psa_apr(page, op.lot, usd_per_eur, now)
    except Exception as error:
        log(f"APR: {type(error).__name__} -> validation ignorée")
        op.psa_apr_note = f"PSA APR indisponible ({type(error).__name__})"
        return PsaAprValidationResult(op, False)

    op.psa_apr_comparables = data.sales
    op.psa_apr_population = data.population
    op.psa_apr_pop_higher = data.pop_higher
    op.psa_apr_most_recent_price = data.most_recent_price
    target_grade = _target_grade(op.lot)
    exact_sales = [sale for sale in data.sales if sale.grade == target_grade]
    if len(exact_sales) < PSA_APR_MIN_COMPS:
        op.psa_apr_note = (
            f"PSA APR: {len(exact_sales)} vente(s) PSA {target_grade:g}, insuffisant"
            if exact_sales
            else f"PSA APR: indisponible / 0 vente ({data.note or 'aucun résultat fiable'})"
        )
        log(f"APR validation insuffisante: {len(exact_sales)} vente(s) exacte(s)")
        return PsaAprValidationResult(op, False)

    apr_estimate = build_market_estimate(
        op.lot, data.sales, now=now, grader_ratios=grader_ratios
    )
    if apr_estimate is None:
        op.psa_apr_note = (
            f"PSA APR: {len(exact_sales)} vente(s), estimation non fiable"
        )
        log("APR validation insuffisante: estimation non fiable")
        return PsaAprValidationResult(op, False)

    op.psa_apr_estimate = apr_estimate
    log(
        f"APR estimation: {apr_estimate.low:.2f}/"
        f"{apr_estimate.central:.2f}/{apr_estimate.high:.2f} €"
    )
    combined_estimate, note = _conservative_source_validation_estimate(
        op.estimate, apr_estimate, "PSA APR"
    )
    combined_op = _opportunity_from_estimate(
        op.lot,
        combined_estimate,
        op.gcc_comparables,
        op.ebay_comparables,
        op.ebay_note,
        data.sales,
        apr_estimate,
        note,
        data.population,
        data.pop_higher,
        data.most_recent_price,
    )
    _log_estimate("Estimation après PSA APR", combined_op)
    rejection = opportunity_rejection_reason(combined_op)
    if rejection:
        log(f"APR validation rejetée: {op.lot.title} | {rejection}")
        return PsaAprValidationResult(None, True)
    log("APR validation retenue")
    return PsaAprValidationResult(combined_op, True)


def validate_with_ebay(
    page,
    op: Opportunity,
    grader_ratios: Optional[list[EmpiricalGraderRatio]] = None,
) -> Optional[Opportunity]:
    """Combine le format commun; en cas de divergence, garde la source la plus prudente."""
    ebay_sales = scrape_ebay_sold(page, op.lot)
    op.ebay_comparables = ebay_sales
    if len(ebay_sales) < EBAY_MIN_COMPS:
        op.ebay_note = f"eBay: {len(ebay_sales)} comparable(s), insuffisant"
        return op

    ebay_estimate = build_market_estimate(
        op.lot, ebay_sales, grader_ratios=grader_ratios
    )
    if ebay_estimate is None:
        op.ebay_note = f"eBay: {len(ebay_sales)} comparable(s), estimation non fiable"
        return op

    gcc_market = op.estimate.central
    ebay_market = ebay_estimate.central
    ratio = ebay_market / gcc_market if gcc_market > 0 else 1.0
    if 0.60 <= ratio <= 1.60:
        combined_estimate = build_market_estimate(
            op.lot,
            op.gcc_comparables + ebay_sales,
            grader_ratios=grader_ratios,
        )
        if combined_estimate is None:
            return op
        note = (
            f"eBay {len(ebay_sales)} ventes, médiane pondérée {ebay_market:.2f} € "
            f"({ebay_estimate.confidence})"
        )
    else:
        combined_estimate = ebay_estimate if ebay_market < gcc_market else op.estimate
        combined_estimate.source_consistent = False
        combined_estimate.confidence = "faible"
        combined_estimate.adaptive_discount_pct = min(
            45.0, max(MIN_DISCOUNT, combined_estimate.adaptive_discount_pct + 3)
        )
        note = (
            f"eBay divergent ({ebay_market:.2f} € vs GCC {gcc_market:.2f} €): "
            "source la plus prudente retenue"
        )

    combined_op = _opportunity_from_estimate(
        op.lot,
        combined_estimate,
        op.gcc_comparables,
        ebay_sales,
        note,
        op.psa_apr_comparables,
        op.psa_apr_estimate,
        op.psa_apr_note,
        op.psa_apr_population,
        op.psa_apr_pop_higher,
        op.psa_apr_most_recent_price,
    )
    _log_estimate("Estimation après eBay", combined_op)
    rejection = opportunity_rejection_reason(combined_op)
    if rejection:
        log(f"Rejet eBay: {op.lot.title} | {rejection}")
        return None
    return combined_op


def validate_secondary_sources(
    page,
    op: Opportunity,
    budgets: ValidationBudgets,
    grader_ratios: Optional[list[EmpiricalGraderRatio]] = None,
    apr_validator=None,
    ebay_validator=None,
) -> Optional[Opportunity]:
    """Route PSA vers APR puis eBay en fallback; les autres graders gardent eBay."""
    apr_validation = apr_validator or validate_with_psa_apr
    ebay_validation = ebay_validator or validate_with_ebay
    validated: Optional[Opportunity] = op

    if psa_apr_card_validation_allowed(op.lot, budgets.psa_apr_cards):
        budgets.psa_apr_cards += 1
        card_name = extract_card_identity(op.lot)["core"] or op.lot.title
        log(
            f"[APR {budgets.psa_apr_cards}/{PSA_APR_MAX_CARDS_PER_RUN}] "
            f"{format_grade_label(op.lot.grader, op.lot.grade)} {card_name}"
        )
        try:
            apr_result = apr_validation(page, op, grader_ratios=grader_ratios)
        except Exception as error:
            log(f"APR: {type(error).__name__} -> fallback eBay")
            apr_result = PsaAprValidationResult(op, False)
        if apr_result.sufficient:
            return apr_result.opportunity
        validated = apr_result.opportunity or op
        log("APR: aucun résultat fiable -> fallback eBay")

    if validated is not None and ebay_card_validation_allowed(budgets.ebay_cards):
        budgets.ebay_cards += 1
        log(
            f"[eBay carte {budgets.ebay_cards}/{EBAY_MAX_CARDS_PER_RUN}] "
            f"{validated.lot.title} | GCC {validated.estimated_market:.2f} €"
        )
        try:
            return ebay_validation(page, validated, grader_ratios=grader_ratios)
        except Exception as error:
            log(f"eBay: {type(error).__name__} -> validation ignorée")
            return validated
    return validated


def estimate_with_grade(
    lot: Lot,
    sales: list[ComparableSale],
    now: Optional[datetime] = None,
    grader_ratios: Optional[list[EmpiricalGraderRatio]] = None,
    run_diagnostics: Optional[RunDiagnostics] = None,
) -> Optional[Opportunity]:
    if not lot.grader or _target_grade(lot) is None:
        grade_diagnostic = diagnose_unreadable_grade(lot)
        special_qualifier = grade_diagnostic.reason == GRADE_SPECIAL_QUALIFIER
        log_unreadable_grade_diagnostic(grade_diagnostic)
        diagnostics = diagnose_gcc_comparables(
            lot, sales, now=now, grader_ratios=grader_ratios
        )
        log_gcc_comparable_diagnostics(lot, diagnostics)
        rejection_message = (
            "qualifier spécial exclu"
            if special_qualifier else "grader/grade cible non lisible"
        )
        log(f"Rejet valeur: {lot.title} | {rejection_message}")
        if run_diagnostics is not None:
            if special_qualifier:
                run_diagnostics.record_special_qualifier(lot, grade_diagnostic)
                run_diagnostics.record_valuation(
                    lot, REJECTION_SPECIAL_QUALIFIER
                )
            else:
                run_diagnostics.record_unreadable_grade(lot, grade_diagnostic)
                run_diagnostics.record_valuation(lot, REJECTION_GRADER_GRADE)
        return None
    if lot.current_price is None or lot.current_price < MIN_PRICE or lot.current_price > MAX_PRICE:
        diagnostics = diagnose_gcc_comparables(
            lot, sales, now=now, grader_ratios=grader_ratios
        )
        log_gcc_comparable_diagnostics(lot, diagnostics)
        if run_diagnostics is not None:
            run_diagnostics.record_valuation(lot, REJECTION_OTHER)
        return None
    estimate = build_market_estimate(lot, sales, now, grader_ratios)
    diagnostics = diagnose_gcc_comparables(
        lot, sales, estimate, now, grader_ratios
    )
    log_gcc_comparable_diagnostics(lot, diagnostics)
    if estimate is None or estimate.central <= 0:
        reason, category = _estimate_failure_diagnostic(diagnostics)
        log(f"Rejet valeur: {lot.title} | {reason}")
        if run_diagnostics is not None:
            run_diagnostics.record_valuation(lot, category)
        return None

    op = _opportunity_from_estimate(lot, estimate, sales)
    _log_estimate("Estimation GCC", op)
    rejection = opportunity_rejection_reason(op)
    if rejection:
        log(f"Rejet opportunité: {lot.title} | {rejection}")
        if run_diagnostics is not None:
            run_diagnostics.record_valuation(
                lot, _opportunity_rejection_category(op, rejection)
            )
        return None
    if run_diagnostics is not None:
        run_diagnostics.record_valuation(lot)
    log(
        f"Opportunité retenue ({lot.source_type}): {lot.title} | "
        f"décote {op.discount_pct:.1f}% | prix max {op.max_recommended:.2f} €"
    )
    return op


def notification_decision(
    op: Opportunity, previous: Optional[dict]
) -> NotificationDecision:
    """Décide les renotifications; accepte aussi les entrées state.json V1."""
    is_auction = op.lot.source_type == "auction"
    under_max = op.lot.current_price <= op.max_recommended
    final_eligible = (
        is_auction
        and op.lot.minutes_to_end is not None
        and op.lot.minutes_to_end <= 5
        and under_max
    )

    if not isinstance(previous, dict):
        return NotificationDecision(
            should_notify=True,
            final_alert=final_eligible,
            reasons=("nouvelle opportunité",),
        )

    reasons = []
    try:
        previous_price = float(previous.get("price"))
        if previous_price > 0 and op.lot.current_price <= previous_price * 0.90:
            reasons.append("prix en baisse d'au moins 10%")
    except (TypeError, ValueError):
        pass

    try:
        previous_discount = float(previous.get("discount_pct", 0))
        if op.discount_pct >= previous_discount + 5:
            reasons.append("décote améliorée d'au moins 5 points")
    except (TypeError, ValueError):
        pass

    final_alert = final_eligible and not bool(previous.get("final_alert_sent", False))
    if final_alert:
        reasons.append("toujours sous le prix max dans les 5 dernières minutes")
    elif is_auction and op.lot.minutes_to_end is not None and op.lot.minutes_to_end <= 15:
        try:
            previous_minutes = float(previous.get("minutes_to_end"))
        except (TypeError, ValueError):
            previous_minutes = None
        crossed_15 = previous_minutes is None or previous_minutes > 15
        if crossed_15 and not bool(previous.get("alert_15m_sent", False)):
            reasons.append("passage sous 15 minutes")

    return NotificationDecision(bool(reasons), final_alert, tuple(reasons))


def updated_notification_state(
    op: Opportunity,
    previous: Optional[dict],
    decision: NotificationDecision,
    notified_at: str,
) -> dict:
    old = previous if isinstance(previous, dict) else {}
    minutes = op.lot.minutes_to_end
    return {
        "discount_pct": op.discount_pct,
        "price": op.lot.current_price,
        "notified_at": notified_at,
        "minutes_to_end": minutes,
        "max_recommended": op.max_recommended,
        "adaptive_discount_pct": op.estimate.adaptive_discount_pct,
        "grade_arbitrage": op.estimate.grade_arbitrage,
        "alert_15m_sent": bool(old.get("alert_15m_sent"))
        or bool(op.lot.source_type == "auction" and minutes is not None and minutes <= 15),
        "final_alert_sent": bool(old.get("final_alert_sent")) or decision.final_alert,
        "last_reasons": list(decision.reasons),
    }


def _language_in_french(language: str) -> str:
    return {
        "French": "Français",
        "Japanese": "Japonais",
        "English": "Anglais",
        "German": "Allemand",
        "Spanish": "Espagnol",
        "Italian": "Italien",
    }.get(language, language or "Inconnue")


def _exact_count(lot: Lot, sales: list[ComparableSale]) -> int:
    target_grade = _target_grade(lot)
    return sum(
        sale.exact_card and (target_grade is None or sale.grade == target_grade)
        for sale in sales
    )


def notify(op: Opportunity, decision: NotificationDecision) -> None:
    if decision.final_alert:
        title = "GCC AUCTION — DERNIÈRES 5 MIN — SOUS PRIX MAX"
    elif op.estimate.grade_arbitrage and op.lot.source_type == "auction":
        title = "GCC AUCTION — ARBITRAGE GRADE"
    elif op.estimate.grade_arbitrage:
        title = "GCC PRIX FIXE — ARBITRAGE GRADE"
    elif op.lot.source_type == "auction":
        title = "GCC AUCTION — FORTE OPPORTUNITÉ"
    else:
        title = "GCC PRIX FIXE — FORTE OPPORTUNITÉ"

    ident = extract_card_identity(op.lot)
    card_name = ident["core"] or op.lot.title
    reference = ""
    if ident["ref"] and ident["ref"].lower() not in card_name.lower().replace(" ", ""):
        reference = f" #{ident['ref']}"
    identity_line = " · ".join(
        part for part in (
            ident.get("series") or "Série inconnue",
            ident.get("year") or "Année inconnue",
        )
    )
    grade_line = format_grade_label(op.lot.grader, op.lot.grade) or "Grade inconnu"
    estimate = op.estimate
    gcc_count = _exact_count(op.lot, op.gcc_comparables)
    ebay_count = _exact_count(op.lot, op.ebay_comparables)
    if op.ebay_comparables:
        ebay_status = (
            f"{ebay_count} vente(s) exacte(s) / {len(op.ebay_comparables)} comparable(s)"
        )
    else:
        ebay_status = "indisponible / 0 vente"
    ebay_detail = f"Détail eBay : {op.ebay_note}\n" if op.ebay_note else ""
    apr_count = _exact_count(op.lot, op.psa_apr_comparables)
    target_grade = _target_grade(op.lot)
    target_label = f"PSA {target_grade:g}" if target_grade is not None else "PSA"
    exact_apr_sales = [
        sale for sale in op.psa_apr_comparables
        if sale.exact_card and sale.grade == target_grade
    ]
    if op.psa_apr_estimate is not None and apr_count >= PSA_APR_MIN_COMPS:
        apr_estimate = op.psa_apr_estimate
        apr_lines = (
            f"PSA APR : {apr_count} vente(s) {target_label}\n"
            f"APR valeur : {apr_estimate.low:.2f}–{apr_estimate.high:.2f} €\n"
            f"APR centrale : {apr_estimate.central:.2f} €\n"
        )
    elif apr_count:
        apr_lines = f"PSA APR : {apr_count} vente(s) {target_label}, insuffisant\n"
    else:
        apr_lines = "PSA APR : indisponible / 0 vente\n"

    dated_apr_sales = [sale for sale in exact_apr_sales if sale.sold_at is not None]
    if dated_apr_sales:
        latest_apr_sale = max(dated_apr_sales, key=lambda sale: sale.sold_at)
        apr_lines += (
            f"Dernière vente APR : {latest_apr_sale.price:.2f} € — "
            f"{latest_apr_sale.sold_at.strftime('%d.%m.%Y')}\n"
        )
    if op.psa_apr_population is not None:
        apr_lines += f"Population {target_label} : {op.psa_apr_population}\n"
    if op.psa_apr_pop_higher is not None:
        apr_lines += f"Pop Higher : {op.psa_apr_pop_higher}\n"
    if op.psa_apr_most_recent_price is not None:
        apr_lines += (
            f"Most Recent Price PSA : {op.psa_apr_most_recent_price:.2f} €\n"
        )
    if op.psa_apr_note:
        apr_lines += f"Détail APR : {op.psa_apr_note}\n"
    recent_line = (
        f"{estimate.recent_90_count}/{len(estimate.kept_comparables)} < 90 jours"
    )
    if estimate.dated_count < len(estimate.kept_comparables):
        recent_line += f" ({len(estimate.kept_comparables) - estimate.dated_count} date(s) inconnue(s))"

    if estimate.grade_arbitrage:
        reference_grade = estimate.arbitrage_reference_grade
        reference_label = (
            f"{op.lot.grader} {reference_grade:g}"
            if reference_grade is not None
            else "grade inférieur"
        )
        reference_value = (
            f"{estimate.arbitrage_reference_value:.2f} €"
            if estimate.arbitrage_reference_value is not None
            else "inconnue"
        )
        valuation_lines = (
            f"Type d'opportunité : ARBITRAGE GRADE\n"
            f"Référence de marché : {reference_label}\n"
            f"Valeur robuste de référence : {reference_value}\n"
            f"Fourchette du grade inférieur : {estimate.low:.2f}–{estimate.high:.2f} €\n"
            f"Valeur exacte du grade cible : non estimée\n"
            f"Prix max conseillé : {op.max_recommended:.2f} €\n"
            f"Décote classique : non applicable\n\n"
        )
    else:
        valuation_lines = (
            f"Valeur estimée : {estimate.low:.2f}–{estimate.high:.2f} €\n"
            f"Estimation centrale : {estimate.central:.2f} €\n"
            f"Prix max conseillé : {op.max_recommended:.2f} €\n"
            f"Décote actuelle : {op.discount_pct:.1f}%\n"
            f"Seuil adaptatif : {estimate.adaptive_discount_pct:.0f}%\n\n"
        )

    timing_lines = ""
    if op.lot.source_type == "auction":
        minutes = op.lot.minutes_to_end
        timing = f"{minutes} min" if minutes is not None else (op.lot.end_text or "inconnue")
        max_status = "SOUS" if op.lot.current_price <= op.max_recommended else "AU-DESSUS DU"
        timing_lines = f"Statut enchère : {max_status} prix max conseillé\nFin : {timing}\n"

    reason_line = ", ".join(decision.reasons)
    msg = (
        f"{title}\n\n"
        f"{card_name}{reference}\n"
        f"{identity_line}\n"
        f"Langue : {_language_in_french(ident.get('language', ''))}\n"
        f"{grade_line}\n\n"
        f"Prix actuel : {op.lot.current_price:.2f} €\n"
        f"{valuation_lines}"
        f"GCC : {gcc_count} vente(s) exacte(s)\n"
        f"eBay : {ebay_status}\n"
        f"{ebay_detail}"
        f"{apr_lines}\n"
        f"Ventes récentes : {recent_line}\n"
        f"Liquidité : {estimate.liquidity}\n"
        f"Dispersion : {estimate.dispersion}\n"
        f"Confiance : {estimate.confidence}\n"
        f"Méthode : {estimate.rationale}\n"
        f"Raison alerte : {reason_line}\n\n"
        f"{timing_lines}"
        f"{op.lot.url}"
    )

    log(f"*** NOTIFICATION: {reason_line} ***")
    print(msg, flush=True)

    if NTFY_TOPIC:
        try:
            requests.post(
                f"{NTFY_SERVER}/{NTFY_TOPIC}",
                data=msg.encode("utf-8"),
                headers={
                    # RFC 2047 garde les titres Unicode (dont le tiret cadratin)
                    # compatibles avec l'encodage latin-1 des en-têtes HTTP.
                    "Title": Header(title, "utf-8").encode(),
                    "Priority": "5" if decision.final_alert else "4",
                    "Tags": "rotating_light,moneybag" if decision.final_alert else "moneybag,card_index",
                },
                timeout=10,
            ).raise_for_status()
            log("Notification ntfy envoyée")
        except Exception as e:
            log(f"Notification ntfy échouée: {e}")


def format_run_diagnostics(diagnostics: RunDiagnostics) -> str:
    lines = [
        "=== DIAGNOSTIC RUN ===",
        f"Prix fixes candidats: {diagnostics.fixed_candidates}",
        (
            f"Enchères candidates <={MAX_AUCTION_MINUTES} min: "
            f"{diagnostics.auction_candidates_ending_soon}"
        ),
        f"Lots analysés: {diagnostics.lots_analyzed}",
        "",
        "Rejetés:",
        (
            "- grader/grade illisible: "
            f"{diagnostics.rejection_count(REJECTION_GRADER_GRADE)}"
        ),
        (
            "- qualifier spécial exclu: "
            f"{diagnostics.rejection_count(REJECTION_SPECIAL_QUALIFIER)}"
        ),
        (
            "- historique vide: "
            f"{diagnostics.rejection_count(REJECTION_EMPTY_HISTORY)}"
        ),
        (
            "- comparables insuffisants: "
            f"{diagnostics.rejection_count(REJECTION_INSUFFICIENT_COMPARABLES)}"
        ),
        (
            "- identité insuffisante: "
            f"{diagnostics.rejection_count(REJECTION_INSUFFICIENT_IDENTITY)}"
        ),
        (
            "- décote insuffisante: "
            f"{diagnostics.rejection_count(REJECTION_INSUFFICIENT_DISCOUNT)}"
        ),
        (
            "- prix fixe > prix max prudent: "
            f"{diagnostics.rejection_count(REJECTION_FIXED_ABOVE_MAX)}"
        ),
        f"- autres motifs: {diagnostics.rejection_count(REJECTION_OTHER)}",
        "",
        f"Opportunités GCC: {diagnostics.gcc_opportunities}",
        f"Rejetées validation externe: {len(diagnostics.external_rejections)}",
        f"Opportunités finales: {diagnostics.final_opportunities}",
        "",
        f"Ventes live GCC: {len(diagnostics.live_auction_urls)}",
        (
            f"Ventes terminant <={MAX_AUCTION_MINUTES} min: "
            f"{len(diagnostics.ending_soon_sale_urls)}"
        ),
        (
            f"Cartes Pokémon {MIN_PRICE:.0f}–{MAX_PRICE:.0f} € dans ces ventes: "
            f"{len(diagnostics.cards_in_ending_sales)}"
        ),
        f"Lots réellement analysés: {diagnostics.auction_lots_analyzed}",
        "",
        (
            "Nombre de lots grade illisible: "
            f"{len(diagnostics.unreadable_grade_lots)}"
        ),
    ]
    lines.extend(
        f"- {item.url} | {item.title} | motif: {item.reason}"
        for item in diagnostics.unreadable_grade_lots.values()
    )
    lines.extend(
        (
            "",
            "Nombre de lots qualifier spécial exclu: "
            f"{len(diagnostics.special_qualifier_lots)}",
        )
    )
    lines.extend(
        f"- {item.url} | {item.title} | qualifier: {item.special_qualifier}"
        for item in diagnostics.special_qualifier_lots.values()
    )
    return "\n".join(lines)


def log_run_diagnostics(diagnostics: RunDiagnostics) -> None:
    for line in format_run_diagnostics(diagnostics).splitlines():
        log(line) if line else print(flush=True)


def main() -> int:
    started = time.monotonic()
    state = load_state()
    run_now = datetime.now(timezone.utc)
    now = run_now.isoformat()
    run_diagnostics = RunDiagnostics()

    log("=== GCC Watcher V4 (valorisation robuste + alertes intelligentes) démarré ===")
    log("Ordre: prix fixes d'abord, puis enchères")
    log(
        f"Filtres enchères: Pokémon -> carte -> prix -> temps <= {MAX_AUCTION_MINUTES} min "
        "-> valeur/décote"
    )
    log(f"Prix: {MIN_PRICE:.0f} à {MAX_PRICE:.0f} €")
    log(f"Décote plancher: {MIN_DISCOUNT:.0f}% (seuil adaptatif selon qualité)")
    log(
        "Valorisation: médiane pondérée par récence + MAD/IQR + "
        "validation PSA APR, fallback eBay public"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        session_file = Path("gcc_session.json")
        if session_file.exists():
            log("Session GCC trouvée — démarrage authentifié")
            context = browser.new_context(
                locale="fr-FR",
                timezone_id="Europe/Zurich",
                storage_state=str(session_file),
            )
        else:
            log("ATTENTION: aucune session GCC trouvée")
            context = browser.new_context(
                locale="fr-FR",
                timezone_id="Europe/Zurich",
            )

        page = context.new_page()
        page.set_default_timeout(TEXT_TIMEOUT)
        page.set_default_navigation_timeout(NAV_TIMEOUT)

        opportunities: list[Opportunity] = []

        try:
            # ============================================================
            # A) PRIX FIXES EN PREMIER
            # ============================================================
            log("=== Scan prix fixes ===")
            fixed_list = collect_lots_from_listing(page, FIXED_PRICE_URL, "fixed")
            fixed_list = sorted(
                fixed_list,
                key=lambda x: x.current_price if x.current_price is not None else 999999,
            )[:MAX_FIXED_CANDIDATES]
            run_diagnostics.fixed_candidates = len(fixed_list)

            log(f"Prix fixes candidats {MIN_PRICE:.0f}-{MAX_PRICE:.0f} €: {len(fixed_list)}")

            fixed_inspected = 0
            for lot in fixed_list:
                fixed_inspected += 1
                lot = inspect_item(page, lot)

                if not is_valid_pokemon_card(lot, run_diagnostics):
                    continue

                if lot.current_price is None:
                    log(f"[fixe {fixed_inspected}] Ignoré: prix non lisible")
                    run_diagnostics.record_valuation(lot, REJECTION_OTHER)
                    continue

                if lot.current_price < MIN_PRICE or lot.current_price > MAX_PRICE:
                    log(
                        f"[fixe {fixed_inspected}] Ignoré: prix {lot.current_price:.2f} € "
                        f"hors tranche {MIN_PRICE:.0f}-{MAX_PRICE:.0f} €"
                    )
                    run_diagnostics.record_valuation(lot, REJECTION_OTHER)
                    continue

                history = extract_historical_sales(lot)
                log(
                    f"[fixe {fixed_inspected}] {lot.current_price:.2f} € | "
                    f"{format_grade_label(lot.grader, lot.grade) or 'grade inconnu'} | "
                    f"historique: {len(history)} ventes"
                )

                state["seen"][lot.url] = {
                    "price": lot.current_price,
                    "seen_at": now,
                    "title": lot.title,
                    "source_type": lot.source_type,
                    "grade": format_grade_label(lot.grader, lot.grade),
                    "minutes_to_end": lot.minutes_to_end,
                }

                op = estimate_with_grade(
                    lot, history, run_now, run_diagnostics=run_diagnostics
                )
                if op:
                    opportunities.append(op)

            # ============================================================
            # B) ENCHÈRES
            # 1. Récupération des cartes depuis les listings
            # 2. Temps lu DIRECTEMENT sur le listing
            # 3. Fallback fiche individuelle seulement si timer illisible
            # 4. La limite MAX_AUCTION_CANDIDATES vient APRES le temps
            # ============================================================
            log("=== Scan enchères ===")
            auction_candidates: dict[str, Lot] = {}
            sales = collect_live_auction_urls(page)
            run_diagnostics.record_live_sales(sales)
            log(f"Ventes live détectées: {len(sales)}")

            for sale in sales:
                try:
                    lots = collect_lots_from_listing(
                        page, sale, "auction", run_diagnostics
                    )
                    for lot in lots:
                        auction_candidates.setdefault(lot.url, lot)
                except PlaywrightTimeoutError:
                    log(f"Timeout vente: {sale}")

            raw_auction_list = list(auction_candidates.values())
            log(f"Enchères Pokémon/prix avant filtre temps: {len(raw_auction_list)}")

            ending_soon: list[Lot] = []
            fallback_needed: list[Lot] = []

            # Préfiltre ultra-rapide à partir du texte du listing.
            for idx, lot in enumerate(raw_auction_list, start=1):
                if lot.minutes_to_end is None:
                    fallback_needed.append(lot)
                    log(
                        f"[préfiltre {idx}] timer absent/illisible -> fallback fiche"
                    )
                    continue

                action = "GARDÉ" if lot.minutes_to_end <= MAX_AUCTION_MINUTES else "IGNORÉ"
                log(
                    f"[préfiltre {idx}] temps lu = \"{lot.end_text}\" "
                    f"-> {lot.minutes_to_end} min -> {action}"
                )

                if lot.minutes_to_end <= MAX_AUCTION_MINUTES:
                    ending_soon.append(lot)

            log(
                f"Timer lisible sur listing: "
                f"{len(raw_auction_list) - len(fallback_needed)}/{len(raw_auction_list)}"
            )
            log(f"Fallback fiches nécessaire: {len(fallback_needed)}")

            # Fallback seulement pour les cartes dont le timer n'était pas lisible sur le listing.
            for idx, lot in enumerate(fallback_needed, start=1):
                lot = inspect_item(page, lot)

                if not is_valid_pokemon_card(lot):
                    continue

                if lot.current_price is None:
                    continue

                if lot.current_price < MIN_PRICE or lot.current_price > MAX_PRICE:
                    continue

                if lot.minutes_to_end is None:
                    log(f"[fallback {idx}] temps non lisible -> IGNORÉ")
                    continue

                action = "GARDÉ" if lot.minutes_to_end <= MAX_AUCTION_MINUTES else "IGNORÉ"
                log(
                    f"[fallback {idx}] temps lu = \"{lot.end_text}\" "
                    f"-> {lot.minutes_to_end} min -> {action}"
                )

                if lot.minutes_to_end <= MAX_AUCTION_MINUTES:
                    ending_soon.append(lot)

            # Déduplication
            dedup = {}
            for lot in ending_soon:
                dedup[lot.url] = lot
            ending_soon = list(dedup.values())
            run_diagnostics.auction_candidates_ending_soon = len(ending_soon)

            ending_soon.sort(
                key=lambda x: (
                    x.minutes_to_end if x.minutes_to_end is not None else 999999,
                    x.current_price if x.current_price is not None else 999999,
                )
            )

            log(
                f"Enchères réellement <= {MAX_AUCTION_MINUTES} min "
                f"et {MIN_PRICE:.0f}-{MAX_PRICE:.0f} €: {len(ending_soon)}"
            )

            # Limite seulement APRES le filtre temps.
            auction_list = ending_soon[:MAX_AUCTION_CANDIDATES]
            if len(ending_soon) > MAX_AUCTION_CANDIDATES:
                log(
                    f"Analyse de valeur limitée aux {MAX_AUCTION_CANDIDATES} "
                    "enchères qui finissent le plus tôt."
                )

            # ============================================================
            # C) HISTORIQUE + GRADE + DÉCOTE SEULEMENT SUR LES <= 60 MIN
            # ============================================================
            auction_inspected = 0
            for lot in auction_list:
                auction_inspected += 1

                # Si le lot n'a pas été ouvert pendant le fallback, on l'ouvre maintenant
                # uniquement parce qu'il a déjà passé le filtre temps.
                if not lot.body:
                    lot = inspect_item(page, lot)

                if not is_valid_pokemon_card(lot, run_diagnostics):
                    continue

                if lot.current_price is None:
                    run_diagnostics.record_valuation(lot, REJECTION_OTHER)
                    continue

                if lot.current_price < MIN_PRICE or lot.current_price > MAX_PRICE:
                    run_diagnostics.record_valuation(lot, REJECTION_OTHER)
                    continue

                # Double sécurité.
                if lot.minutes_to_end is None or lot.minutes_to_end > MAX_AUCTION_MINUTES:
                    run_diagnostics.record_valuation(lot, REJECTION_OTHER)
                    continue

                history = extract_historical_sales(lot)

                log(
                    f"[enchère {auction_inspected}] {lot.current_price:.2f} € | "
                    f"fin {lot.end_text} | "
                    f"{format_grade_label(lot.grader, lot.grade) or 'grade inconnu'} | "
                    f"historique: {len(history)} ventes"
                )

                state["seen"][lot.url] = {
                    "price": lot.current_price,
                    "seen_at": now,
                    "title": lot.title,
                    "source_type": lot.source_type,
                    "grade": format_grade_label(lot.grader, lot.grade),
                    "minutes_to_end": lot.minutes_to_end,
                }

                op = estimate_with_grade(
                    lot, history, run_now, run_diagnostics=run_diagnostics
                )
                if op:
                    opportunities.append(op)

            # ============================================================
            # D) VALIDATION PSA APR, FALLBACK eBay SOLD + NOTIFICATIONS
            # ============================================================
            log(f"Opportunités GCC avant validations: {len(opportunities)}")

            validation_page = context.new_page()
            validation_page.set_default_timeout(TEXT_TIMEOUT)
            validation_page.set_default_navigation_timeout(NAV_TIMEOUT)

            final_opportunities: list[Opportunity] = []
            validation_budgets = ValidationBudgets()

            for op in sorted(opportunities, key=lambda x: x.discount_pct, reverse=True):
                validated = validate_secondary_sources(
                    validation_page, op, validation_budgets
                )

                if validated is not None:
                    final_opportunities.append(validated)
                else:
                    run_diagnostics.record_external_rejection(op.lot)

            try:
                validation_page.close()
            except Exception:
                pass

            for op in sorted(final_opportunities, key=lambda x: x.discount_pct, reverse=True):
                key = op.lot.url
                prev = state["notified"].get(key)
                decision = notification_decision(op, prev)
                if decision.should_notify:
                    notify(op, decision)
                    state["notified"][key] = updated_notification_state(
                        op, prev, decision, now
                    )
                else:
                    log(f"Pas de renotification: {op.lot.title} | aucun changement important")

            save_state(state)
            run_diagnostics.final_opportunities = len(final_opportunities)
            log(f"Opportunités finales après validations: {len(final_opportunities)}")

        finally:
            log_run_diagnostics(run_diagnostics)
            browser.close()

    log(f"=== Scan terminé en {time.monotonic() - started:.1f}s ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
