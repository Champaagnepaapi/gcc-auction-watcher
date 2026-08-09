from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import Header
from pathlib import Path
from statistics import median
from typing import Optional
from urllib.parse import quote_plus

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
    grade: str = ""
    listing_text: str = ""


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


def collect_lots_from_listing(page, url: str, source_type: str) -> list[Lot]:
    log(f"Ouverture listing {source_type}: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    page.wait_for_timeout(1200)

    # Pour une vente aux enchères, si la vente globale finit dans >1h,
    # inutile de parcourir ses lots maintenant.
    if source_type == "auction":
        try:
            body_top = page.locator("body").inner_text(timeout=TEXT_TIMEOUT)
            sale_minutes = parse_sale_countdown_minutes(body_top)
            if sale_minutes is not None and sale_minutes > MAX_AUCTION_MINUTES:
                log(f"Vente ignorée: fin dans ~{sale_minutes} min")
                return []
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

            title = ""
            for line in blob.splitlines():
                s = line.strip()
                if not s or "€" in s or s.upper() in {"LIVE", "ENDED", "SOON"}:
                    continue
                if len(s) >= 4:
                    title = s
                    break

            if not title:
                title = text.splitlines()[0].strip() if text else item_url.rsplit("/", 1)[-1]

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

    return list(lots.values())


def parse_grader_grade(text: str) -> tuple[str, str]:
    head = (text or "")[:2500]

    for grader in GRADERS:
        m = re.search(
            rf"\b{re.escape(grader)}\s*(?:GRADE\s*)?(\d{{1,2}}(?:[.,]\d)?)\b",
            head,
            re.I,
        )
        if m:
            return grader.upper(), m.group(1).replace(",", ".")

    m = re.search(r"\b(?:Note|Grade)\s*:?\s*(\d{1,2}(?:[.,]\d)?)\b", head, re.I)
    if m:
        return "", m.group(1).replace(",", ".")

    return "", ""


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

        try:
            h1 = page.locator("h1").first.inner_text(timeout=800).strip()
            if h1:
                lot.title = h1
        except Exception:
            pass

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


def is_valid_pokemon_card(lot: Lot) -> bool:
    body = lot.body or ""
    lower = body.lower()

    if not re.search(r"(Catégorie|Category)\s*:?\s*Pok[ée]mon\b", body, re.I):
        return False

    if any(word in lower for word in SEALED_KEYWORDS):
        return False

    # On veut une carte, pas un produit scellé. La présence d'un bloc de gradation
    # ou d'une référence de carte est un signal positif.
    if re.search(r"Article\s+Gradation\s+Détails", body, re.I):
        return True

    if re.search(r"(Réf[ée]rence|Reference)\s*:?\s*#?\s*[A-Z0-9]+(?:/[A-Z0-9]+)+", body, re.I):
        return True

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

        grader = ""
        grade: Optional[float] = None

        for g in GRADERS:
            gm = re.search(
                rf"\b{re.escape(g)}\s*(?:GRADE\s*)?(\d{{1,2}}(?:[.,]\d)?)\b",
                context,
                re.I,
            )
            if gm:
                grader = g.upper()
                grade = float(gm.group(1).replace(",", "."))
                break

        if grade is None:
            gm = re.search(r"\b(?:Note|Grade)\s*:?\s*(\d{1,2}(?:[.,]\d)?)\b", context, re.I)
            if gm:
                grade = float(gm.group(1).replace(",", "."))

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
        return float(lot.grade) if lot.grade else None
    except ValueError:
        return None


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
    if target_grade is None:
        same_grader = [sale for sale in identity_candidates if _same_target_grader(lot, sale)]
        primary = same_grader if lot.grader else identity_candidates
        secondary = [sale for sale in valid if sale not in primary]
        return ComparableSelection(
            primary=primary if len(primary) >= 2 else [],
            lower_bounds=[],
            upper_bounds=[],
            secondary=secondary,
            rationale=f"{len(primary)} ventes comparables sans grade cible" if len(primary) >= 2 else "",
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
        op.lot, combined_estimate, op.gcc_comparables, ebay_sales, note
    )
    _log_estimate("Estimation après eBay", combined_op)
    rejection = opportunity_rejection_reason(combined_op)
    if rejection:
        log(f"Rejet eBay: {op.lot.title} | {rejection}")
        return None
    return combined_op


def estimate_with_grade(
    lot: Lot,
    sales: list[ComparableSale],
    now: Optional[datetime] = None,
    grader_ratios: Optional[list[EmpiricalGraderRatio]] = None,
) -> Optional[Opportunity]:
    if lot.current_price is None or lot.current_price < MIN_PRICE or lot.current_price > MAX_PRICE:
        return None
    estimate = build_market_estimate(lot, sales, now, grader_ratios)
    if estimate is None or estimate.central <= 0:
        log(f"Rejet valeur: {lot.title} | comparables insuffisants ou grades non exploitables")
        return None

    op = _opportunity_from_estimate(lot, estimate, sales)
    _log_estimate("Estimation GCC", op)
    rejection = opportunity_rejection_reason(op)
    if rejection:
        log(f"Rejet opportunité: {lot.title} | {rejection}")
        return None
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
    grade_line = f"{op.lot.grader} {op.lot.grade}".strip() or "Grade inconnu"
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
        f"PSA APR : indisponible / 0 vente\n\n"
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


def main() -> int:
    started = time.monotonic()
    state = load_state()
    run_now = datetime.now(timezone.utc)
    now = run_now.isoformat()

    log("=== GCC Watcher V4 (valorisation robuste + alertes intelligentes) démarré ===")
    log("Ordre: prix fixes d'abord, puis enchères")
    log(
        f"Filtres enchères: Pokémon -> carte -> prix -> temps <= {MAX_AUCTION_MINUTES} min "
        "-> valeur/décote"
    )
    log(f"Prix: {MIN_PRICE:.0f} à {MAX_PRICE:.0f} €")
    log(f"Décote plancher: {MIN_DISCOUNT:.0f}% (seuil adaptatif selon qualité)")
    log("Valorisation: médiane pondérée par récence + MAD/IQR + validation eBay publique")

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

            log(f"Prix fixes candidats {MIN_PRICE:.0f}-{MAX_PRICE:.0f} €: {len(fixed_list)}")

            fixed_inspected = 0
            for lot in fixed_list:
                fixed_inspected += 1
                lot = inspect_item(page, lot)

                if not is_valid_pokemon_card(lot):
                    continue

                if lot.current_price is None:
                    log(f"[fixe {fixed_inspected}] Ignoré: prix non lisible")
                    continue

                if lot.current_price < MIN_PRICE or lot.current_price > MAX_PRICE:
                    log(
                        f"[fixe {fixed_inspected}] Ignoré: prix {lot.current_price:.2f} € "
                        f"hors tranche {MIN_PRICE:.0f}-{MAX_PRICE:.0f} €"
                    )
                    continue

                history = extract_historical_sales(lot)
                log(
                    f"[fixe {fixed_inspected}] {lot.current_price:.2f} € | "
                    f"{lot.grader} {lot.grade} | historique: {len(history)} ventes"
                )

                state["seen"][lot.url] = {
                    "price": lot.current_price,
                    "seen_at": now,
                    "title": lot.title,
                    "source_type": lot.source_type,
                    "grade": f"{lot.grader} {lot.grade}".strip(),
                    "minutes_to_end": lot.minutes_to_end,
                }

                op = estimate_with_grade(lot, history, run_now)
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
            log(f"Ventes live détectées: {len(sales)}")

            for sale in sales:
                try:
                    lots = collect_lots_from_listing(page, sale, "auction")
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

                if not is_valid_pokemon_card(lot):
                    continue

                if lot.current_price is None:
                    continue

                if lot.current_price < MIN_PRICE or lot.current_price > MAX_PRICE:
                    continue

                # Double sécurité.
                if lot.minutes_to_end is None or lot.minutes_to_end > MAX_AUCTION_MINUTES:
                    continue

                history = extract_historical_sales(lot)

                log(
                    f"[enchère {auction_inspected}] {lot.current_price:.2f} € | "
                    f"fin {lot.end_text} | {lot.grader} {lot.grade} | "
                    f"historique: {len(history)} ventes"
                )

                state["seen"][lot.url] = {
                    "price": lot.current_price,
                    "seen_at": now,
                    "title": lot.title,
                    "source_type": lot.source_type,
                    "grade": f"{lot.grader} {lot.grade}".strip(),
                    "minutes_to_end": lot.minutes_to_end,
                }

                op = estimate_with_grade(lot, history, run_now)
                if op:
                    opportunities.append(op)

            # ============================================================
            # D) VALIDATION eBay SOLD + NOTIFICATIONS
            # ============================================================
            log(f"Opportunités GCC avant eBay: {len(opportunities)}")

            ebay_page = context.new_page()
            ebay_page.set_default_timeout(TEXT_TIMEOUT)
            ebay_page.set_default_navigation_timeout(NAV_TIMEOUT)

            final_opportunities: list[Opportunity] = []
            ebay_cards_validated = 0

            for op in sorted(opportunities, key=lambda x: x.discount_pct, reverse=True):
                validated = op

                if ebay_card_validation_allowed(ebay_cards_validated):
                    ebay_cards_validated += 1
                    log(
                        f"[eBay carte {ebay_cards_validated}/{EBAY_MAX_CARDS_PER_RUN}] "
                        f"{op.lot.title} | "
                        f"GCC {op.estimated_market:.2f} €"
                    )
                    validated = validate_with_ebay(ebay_page, op)

                if validated is not None:
                    final_opportunities.append(validated)

            try:
                ebay_page.close()
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
            log(f"Opportunités GCC avant eBay: {len(opportunities)}")
            log(f"Opportunités finales après eBay: {len(final_opportunities)}")

        finally:
            browser.close()

    log(f"=== Scan terminé en {time.monotonic() - started:.1f}s ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
