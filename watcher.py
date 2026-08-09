from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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
MIN_DISCOUNT = 30.0
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
EBAY_MAX_QUERIES = int(os.getenv("EBAY_MAX_QUERIES", "2"))
EBAY_PAGE_WAIT_MS = int(os.getenv("EBAY_PAGE_WAIT_MS", "700"))
EBAY_NAV_TIMEOUT = int(os.getenv("EBAY_NAV_TIMEOUT", "6000"))

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
class HistoricalSale:
    price: float
    grader: str
    grade: Optional[float]
    context: str


@dataclass
class Opportunity:
    lot: Lot
    estimated_market: float
    discount_pct: float
    exact_grade_comps: list[float]
    lower_grade_comps: list[HistoricalSale]
    higher_grade_comps: list[HistoricalSale]
    confidence: str
    rationale: str
    gcc_estimated_market: Optional[float] = None
    ebay_estimated_market: Optional[float] = None
    ebay_comps: int = 0
    ebay_note: str = ""


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"notified": {}, "seen": {}}


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
            HistoricalSale(
                price=price,
                grader=grader,
                grade=grade,
                context=context.replace("\n", " ")[:300],
            )
        )

    # Déduplication approximative d'éventuelles répétitions DOM.
    deduped: list[HistoricalSale] = []
    seen = set()
    for s in sales:
        key = (round(s.price, 2), s.grader, s.grade)
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
    Extrait quelques éléments stables de la fiche GCC pour construire une recherche
    eBay plus précise: nom, référence, année, langue.
    """
    title = lot.title or ""
    body = lot.body or ""

    # Enlève le grader + grade en tête du titre.
    core = title
    if lot.grader and lot.grade:
        core = re.sub(
            rf"^\s*{re.escape(lot.grader)}\s*{re.escape(lot.grade)}\+?\s*",
            "",
            core,
            flags=re.I,
        )
    core = re.sub(r"^\s*(?:PSA|PCA|CGC|BGS|BECKETT|CCC|CA|PG)\s*\d+(?:[.,]\d)?\+?\s*", "", core, flags=re.I)
    core = re.sub(r"\s+", " ", core).strip()

    ref = ""
    # Cherche d'abord une référence type #108/100 ou #176.
    m = re.search(r"#\s*([A-Z0-9]{1,6}(?:/[A-Z0-9]{1,6})?)", body, re.I)
    if m:
        ref = m.group(1)

    year = ""
    ym = re.search(r"\b(19\d{2}|20\d{2})\b", body)
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
        if any(re.search(rf"\b{re.escape(v)}\b", body, re.I) for v in variants):
            language = canonical
            break

    return {
        "core": core,
        "ref": ref,
        "year": year,
        "language": language,
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

    queries = []

    def add(parts):
        q = " ".join(str(p).strip() for p in parts if p and str(p).strip())
        q = re.sub(r"\s+", " ", q).strip()
        if q and q not in queries:
            queries.append(q)

    # 1. Nom GCC + référence + grader + grade.
    add(["Pokemon", core, ref, lot.grader, lot.grade])

    # 2. Référence + année + grader + grade:
    #    indépendant du nom français/anglais du Pokémon.
    if ref:
        add(["Pokemon", ref, year, lot.grader, lot.grade])

    # 3. Référence + grade sans imposer la société de grading.
    if ref:
        add(["Pokemon", ref, year, lot.grade])

    # 4. Nom + grader/grade, utile si la référence n'est pas visible dans l'annonce eBay.
    add(["Pokemon", core, lot.grader, lot.grade])

    # 5. Recherche plus large, dernier recours.
    if ref:
        add(["Pokemon", ref, year])
    else:
        add(["Pokemon", core, year, language])

    return queries


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
    vals = sorted(p for p in prices if p > 0)
    if len(vals) < 5:
        return vals

    med = median(vals)
    if med <= 0:
        return vals

    # Conserve les ventes entre 40% et 250% de la médiane initiale.
    filtered = [p for p in vals if 0.40 * med <= p <= 2.50 * med]
    return filtered if len(filtered) >= 3 else vals


def scrape_ebay_sold(page, lot: Lot) -> list[HistoricalSale]:
    """
    Recherche publique eBay Sold/Completed sans API Developer.

    V3.3 FAST-FAIL:
    - 2 requêtes maximum;
    - timeout navigation court;
    - abandon immédiat si la page eBay renvoie 0 résultat visible;
    - abandon immédiat après timeout/anti-bot;
    - ne ralentit plus le scan GCC de plusieurs minutes.
    """
    if not EBAY_ENABLED:
        return []

    collected: list[HistoricalSale] = []
    seen = set()

    queries = ebay_queries_for_lot(lot)[:EBAY_MAX_QUERIES]
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
                HistoricalSale(
                    price=price,
                    grader=grader,
                    grade=grade,
                    context=f"eBay SOLD score={score} ({reason}) | {title}"[:300],
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


def estimate_cross_grader_market(lot: Lot, sales: list[HistoricalSale]) -> tuple[Optional[float], str, str]:
    """
    Estimation par grade + grader utilisable pour GCC et eBay.
    Renvoie (estimation, confiance, explication).
    """
    if not sales:
        return None, "faible", ""

    try:
        current_grade = float(lot.grade) if lot.grade else None
    except ValueError:
        current_grade = None

    if current_grade is None:
        prices = [s.price for s in sales if s.price > 0]
        if len(prices) < 2:
            return None, "faible", ""
        return median(prices), ("élevée" if len(prices) >= 5 else "moyenne"), f"{len(prices)} ventes comparables"

    graded = [s for s in sales if s.grade is not None and s.price > 0]
    if not graded:
        return None, "faible", ""

    same_exact = [
        s for s in graded
        if s.grade == current_grade and lot.grader and s.grader == lot.grader
    ]
    other_exact = [
        s for s in graded
        if s.grade == current_grade and (not lot.grader or s.grader != lot.grader)
    ]

    same_lower = [
        s for s in graded
        if s.grade < current_grade and lot.grader and s.grader == lot.grader
    ]
    other_lower = [
        s for s in graded
        if s.grade < current_grade and (not lot.grader or s.grader != lot.grader)
    ]

    same_higher = [
        s for s in graded
        if s.grade > current_grade and lot.grader and s.grader == lot.grader
    ]
    other_higher = [
        s for s in graded
        if s.grade > current_grade and (not lot.grader or s.grader != lot.grader)
    ]

    # 1) Même grader + même grade.
    if len(same_exact) >= 2:
        base = median(robust_median_prices([s.price for s in same_exact]))
        if other_exact:
            cross = median(robust_median_prices([s.price for s in other_exact]))
            return (
                0.80 * base + 0.20 * cross,
                "élevée" if len(same_exact) >= 5 else "moyenne",
                f"{len(same_exact)} même grader/grade + {len(other_exact)} autre(s) grader(s) même grade",
            )
        return (
            base,
            "élevée" if len(same_exact) >= 5 else "moyenne",
            f"{len(same_exact)} ventes même grader au grade exact",
        )

    # 2) Même grade, autres graders compris.
    exact_all = same_exact + other_exact
    if len(exact_all) >= 2:
        weighted = []
        for s in same_exact:
            weighted.extend([s.price] * 3)
        for s in other_exact:
            weighted.extend([s.price] * 2)
        return (
            median(robust_median_prices(weighted)),
            "moyenne" if same_exact else "faible",
            f"{len(same_exact)} même grader + {len(other_exact)} autre(s) grader(s), grade exact",
        )

    # 3) Bornes de grades voisins, toutes sociétés.
    lower = same_lower + other_lower
    higher = same_higher + other_higher

    lower_bound = max((s.price for s in lower), default=None)
    higher_bound = min((s.price for s in higher), default=None)

    if lower_bound is not None and lot.current_price is not None and lot.current_price <= lower_bound:
        return (
            lower_bound,
            "moyenne" if same_lower else "faible",
            f"borne basse via grade inférieur ({len(lower)} vente(s))",
        )

    if lower_bound is not None and higher_bound is not None and higher_bound >= lower_bound:
        nearest_lower = max(lower, key=lambda s: s.grade or -999)
        nearest_higher = min(higher, key=lambda s: s.grade or 999)
        gl = nearest_lower.grade or current_grade
        gh = nearest_higher.grade or current_grade

        if gh > gl:
            fraction = (current_grade - gl) / (gh - gl)
            interpolated = nearest_lower.price + fraction * (nearest_higher.price - nearest_lower.price)
            market = max(lower_bound, min(interpolated, higher_bound))
        else:
            market = lower_bound

        same_company_neighbor = (
            nearest_lower.grader == lot.grader
            or nearest_higher.grader == lot.grader
        )
        return (
            market,
            "moyenne" if same_company_neighbor else "faible",
            f"interpolation grades {gl:g}→{gh:g}, graders {nearest_lower.grader or '?'}→{nearest_higher.grader or '?'}",
        )

    return None, "faible", ""


def validate_with_ebay(page, op: Opportunity) -> Optional[Opportunity]:
    """
    eBay sert de validation externe des vraies ventes GCC.
    Pour limiter les faux positifs:
    - eBay peut confirmer ou réduire l'estimation GCC;
    - si eBay est très divergent, on retient l'estimation la plus prudente;
    - si eBay n'est pas exploitable, on conserve GCC seul.
    """
    op.gcc_estimated_market = op.estimated_market

    ebay_sales = scrape_ebay_sold(page, op.lot)
    if len(ebay_sales) < EBAY_MIN_COMPS:
        op.ebay_note = f"eBay: {len(ebay_sales)} comparable(s), insuffisant"
        return op

    ebay_market, ebay_conf, ebay_reason = estimate_cross_grader_market(op.lot, ebay_sales)
    if ebay_market is None or ebay_market <= 0:
        op.ebay_note = f"eBay: {len(ebay_sales)} comparable(s), estimation non fiable"
        return op

    op.ebay_estimated_market = ebay_market
    op.ebay_comps = len(ebay_sales)

    gcc_market = op.gcc_estimated_market or op.estimated_market
    ratio = ebay_market / gcc_market if gcc_market > 0 else 1.0

    # Si les deux marchés sont raisonnablement proches: blend 65/35.
    # En cas de forte divergence: estimation la plus prudente.
    if 0.60 <= ratio <= 1.60:
        combined = 0.65 * gcc_market + 0.35 * ebay_market
        op.ebay_note = (
            f"eBay {len(ebay_sales)} ventes, {ebay_market:.2f} € "
            f"({ebay_conf}; {ebay_reason})"
        )
    else:
        combined = min(gcc_market, ebay_market)
        op.ebay_note = (
            f"eBay divergent ({ebay_market:.2f} € vs GCC {gcc_market:.2f} €): "
            f"estimation prudente retenue"
        )

    op.estimated_market = combined
    op.discount_pct = (combined - op.lot.current_price) / combined * 100

    # Si eBay fait tomber l'affaire sous 30%, on ne notifie plus.
    if op.discount_pct < MIN_DISCOUNT:
        log(
            f"eBay veto: {op.lot.title} | GCC {gcc_market:.2f} € | "
            f"eBay {ebay_market:.2f} € | combinée {combined:.2f} € | "
            f"décote {op.discount_pct:.1f}%"
        )
        return None

    return op


def estimate_with_grade(lot: Lot, sales: list[HistoricalSale]) -> Optional[Opportunity]:
    if lot.current_price is None or lot.current_price < MIN_PRICE or lot.current_price > MAX_PRICE:
        return None

    market, confidence, rationale = estimate_cross_grader_market(lot, sales)
    if market is None or market <= 0:
        return None

    discount = (market - lot.current_price) / market * 100
    if discount < MIN_DISCOUNT:
        return None

    try:
        current_grade = float(lot.grade) if lot.grade else None
    except ValueError:
        current_grade = None

    graded = [s for s in sales if s.grade is not None]
    exact = [
        s.price for s in graded
        if current_grade is not None and s.grade == current_grade
    ]
    lower = [
        s for s in graded
        if current_grade is not None and s.grade is not None and s.grade < current_grade
    ]
    higher = [
        s for s in graded
        if current_grade is not None and s.grade is not None and s.grade > current_grade
    ]

    return Opportunity(
        lot=lot,
        estimated_market=market,
        discount_pct=discount,
        exact_grade_comps=exact,
        lower_grade_comps=lower,
        higher_grade_comps=higher,
        confidence=confidence,
        rationale=rationale,
        gcc_estimated_market=market,
    )


def notify(op: Opportunity) -> None:
    mode = "ENCHÈRE" if op.lot.source_type == "auction" else "PRIX FIXE"

    if op.lot.source_type == "auction":
        title = f"GCC AUCTION: {op.discount_pct:.0f}% sous estimation"
    else:
        title = f"GCC PRIX FIXE: {op.discount_pct:.0f}% sous estimation"

    grade_line = ""
    if op.lot.grade:
        grade_line = f"Grade: {op.lot.grader} {op.lot.grade}\n".strip() + "\n"

    ident = extract_card_identity(op.lot)
    year_line = f"Année: {ident['year']}\n" if ident["year"] else ""

    timing_line = ""
    if op.lot.source_type == "auction":
        timing_line = f"Fin: {op.lot.end_text}\n"

    gcc_market = op.gcc_estimated_market or op.estimated_market

    ebay_lines = ""
    if op.ebay_estimated_market is not None:
        ebay_lines = (
            f"Estimation eBay vendus: {op.ebay_estimated_market:.2f} € "
            f"({op.ebay_comps} comps)\n"
            f"Estimation combinée: {op.estimated_market:.2f} €\n"
        )
    elif op.ebay_note:
        ebay_lines = f"{op.ebay_note}\n"

    msg = (
        f"{op.lot.title}\n"
        f"Type: {mode}\n"
        f"{grade_line}"
        f"{year_line}"
        f"Prix: {op.lot.current_price:.2f} €\n"
        f"Estimation GCC: {gcc_market:.2f} €\n"
        f"{ebay_lines}"
        f"Décote finale: {op.discount_pct:.1f}% | confiance {op.confidence}\n"
        f"Pourquoi GCC: {op.rationale}\n"
        f"{timing_line}"
        f"{op.lot.url}"
    )

    log("*** OPPORTUNITÉ ***")
    print(msg, flush=True)

    if NTFY_TOPIC:
        try:
            requests.post(
                f"{NTFY_SERVER}/{NTFY_TOPIC}",
                data=msg.encode("utf-8"),
                headers={
                    "Title": title,
                    "Priority": "4",
                    "Tags": "moneybag,card_index",
                },
                timeout=10,
            ).raise_for_status()
            log("Notification ntfy envoyée")
        except Exception as e:
            log(f"Notification ntfy échouée: {e}")


def main() -> int:
    started = time.monotonic()
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()

    log("=== GCC Watcher V3.3 FINAL (timer fix + eBay fast-fail) démarré ===")
    log("Ordre: prix fixes d'abord, puis enchères")
    log("Filtres enchères: Pokémon -> carte -> prix -> temps <= 60 min -> valeur/décote")
    log(f"Prix: {MIN_PRICE:.0f} à {MAX_PRICE:.0f} €")
    log(f"Décote minimale: {MIN_DISCOUNT:.0f}%")
    log("Valorisation: GCC inter-graders + validation eBay Sold publique")

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
                }

                op = estimate_with_grade(lot, history)
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
                }

                op = estimate_with_grade(lot, history)
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
            ebay_queries = 0

            for op in sorted(opportunities, key=lambda x: x.discount_pct, reverse=True):
                validated = op

                if EBAY_ENABLED and ebay_queries < EBAY_MAX_QUERIES:
                    ebay_queries += 1
                    log(
                        f"[eBay {ebay_queries}] {op.lot.title} | "
                        f"GCC {op.gcc_estimated_market or op.estimated_market:.2f} €"
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

                if not prev or op.discount_pct >= float(prev.get("discount_pct", 0)) + 5:
                    notify(op)
                    state["notified"][key] = {
                        "discount_pct": op.discount_pct,
                        "price": op.lot.current_price,
                        "notified_at": now,
                    }

            save_state(state)
            log(f"Opportunités GCC avant eBay: {len(opportunities)}")
            log(f"Opportunités finales après eBay: {len(final_opportunities)}")

        finally:
            browser.close()

    log(f"=== Scan terminé en {time.monotonic() - started:.1f}s ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
