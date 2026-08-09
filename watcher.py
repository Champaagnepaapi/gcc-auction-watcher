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

import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv()

BASE = "https://gradedcardcenter.com"
FIXED_PRICE_URL = 'https://gradedcardcenter.com/filtres?sellingTypes=%5B%22FIXED_PRICE%22%5D'

MAX_PRICE = float(os.getenv("MAX_PRICE_EUR", "100"))
MIN_DISCOUNT = float(os.getenv("MIN_DISCOUNT_PCT", "20"))
MAX_AUCTION_MINUTES = int(os.getenv("MAX_AUCTION_MINUTES", "60"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()

NAV_TIMEOUT = 15000
TEXT_TIMEOUT = 3000
MAX_SCAN_SECONDS = 300
MAX_AUCTION_CANDIDATES = 120
MAX_FIXED_CANDIDATES = 120

MONEY_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:['’\s]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*€",
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


def parse_money(text: str) -> Optional[float]:
    vals = []
    for m in MONEY_RE.findall(text or ""):
        try:
            vals.append(float(m.replace(",", ".")))
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
    head = (body or "")[:4000]
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
            if price is None or price > MAX_PRICE:
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

            lots[item_url] = Lot(
                url=item_url,
                title=title,
                current_price=price,
                source_type=source_type,
                sale_name=sale_name,
            )
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
    head = (body or "")[:3500]
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
            price = float(price_match.group(1).replace(",", "."))
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


def estimate_with_grade(lot: Lot, sales: list[HistoricalSale]) -> Optional[Opportunity]:
    if lot.current_price is None or lot.current_price <= 0 or lot.current_price > MAX_PRICE:
        return None

    try:
        current_grade = float(lot.grade) if lot.grade else None
    except ValueError:
        current_grade = None

    # Si la carte est gradée, on refuse les comparables sans grade exploitable.
    if current_grade is not None:
        relevant = [
            s for s in sales
            if s.grade is not None
            and (not lot.grader or not s.grader or s.grader == lot.grader)
        ]
    else:
        relevant = sales

    if len(relevant) < 2:
        return None

    exact = [
        s.price for s in relevant
        if current_grade is not None and s.grade == current_grade
    ]

    lower = [
        s for s in relevant
        if current_grade is not None and s.grade is not None and s.grade < current_grade
    ]

    higher = [
        s for s in relevant
        if current_grade is not None and s.grade is not None and s.grade > current_grade
    ]

    rationale_parts = []

    if len(exact) >= 2:
        market = median(exact)
        rationale_parts.append(f"{len(exact)} ventes au grade exact")
        confidence = "élevée" if len(exact) >= 5 else "moyenne"
    elif current_grade is not None:
        # Estimation conservative par bornes ordinales.
        lower_prices = [s.price for s in lower]
        higher_prices = [s.price for s in higher]

        lower_bound = max(lower_prices) if lower_prices else None
        higher_bound = min(higher_prices) if higher_prices else None

        # Cas particulièrement intéressant:
        # le prix actuel d'un grade supérieur est <= à des ventes de grades inférieurs.
        if lower_bound is not None and lot.current_price <= lower_bound:
            market = lower_bound
            rationale_parts.append(
                f"prix actuel <= vente(s) de grade inférieur; borne basse {lower_bound:.2f} €"
            )
            confidence = "moyenne"
        elif lower_bound is not None and higher_bound is not None and higher_bound >= lower_bound:
            # Interpolation prudente entre la meilleure borne basse et haute.
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

            rationale_parts.append(
                f"estimé entre grades {nearest_lower.grade:g} et {nearest_higher.grade:g}"
            )
            confidence = "moyenne"
        else:
            # Pas assez de bornes fiables pour inventer une valeur.
            return None
    else:
        prices = [s.price for s in relevant]
        market = median(prices)
        rationale_parts.append(f"{len(prices)} ventes comparables")
        confidence = "moyenne" if len(prices) < 5 else "élevée"

    if market <= 0:
        return None

    discount = (market - lot.current_price) / market * 100
    if discount < MIN_DISCOUNT:
        return None

    return Opportunity(
        lot=lot,
        estimated_market=market,
        discount_pct=discount,
        exact_grade_comps=exact,
        lower_grade_comps=lower,
        higher_grade_comps=higher,
        confidence=confidence,
        rationale="; ".join(rationale_parts),
    )


def notify(op: Opportunity) -> None:
    mode = "ENCHÈRE" if op.lot.source_type == "auction" else "PRIX FIXE"
    title = f"GCC {mode}: {op.discount_pct:.0f}% sous estimation"

    grade_line = ""
    if op.lot.grade:
        grade_line = f"Grade: {op.lot.grader} {op.lot.grade}\n".strip() + "\n"

    timing_line = ""
    if op.lot.source_type == "auction":
        timing_line = f"Fin: {op.lot.end_text}\n"

    msg = (
        f"{op.lot.title}\n"
        f"Type: {mode}\n"
        f"{grade_line}"
        f"Prix: {op.lot.current_price:.2f} €\n"
        f"Estimation GCC: {op.estimated_market:.2f} €\n"
        f"Décote: {op.discount_pct:.1f}% | confiance {op.confidence}\n"
        f"Pourquoi: {op.rationale}\n"
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

    log("=== GCC Watcher V2 démarré ===")
    log("Filtres: Pokémon + carte individuelle")
    log(f"Prix max: {MAX_PRICE:.0f} €")
    log(f"Enchères: uniquement <= {MAX_AUCTION_MINUTES} min")
    log("Prix fixes: inclus")
    log("Valorisation: grade exact en priorité + bornes grades voisins")

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

        try:
            auction_candidates: dict[str, Lot] = {}
            sales = collect_live_auction_urls(page)
            log(f"Ventes live détectées: {len(sales)}")

            for sale in sales:
                if time.monotonic() - started > MAX_SCAN_SECONDS:
                    break

                try:
                    lots = collect_lots_from_listing(page, sale, "auction")
                    log(f"- {len(lots)} cartes Pokémon <= {MAX_PRICE:.0f} € à moins d'1h")
                    for lot in lots:
                        auction_candidates.setdefault(lot.url, lot)
                except PlaywrightTimeoutError:
                    log(f"Timeout vente: {sale}")

            auction_list = sorted(
                auction_candidates.values(),
                key=lambda x: x.current_price if x.current_price is not None else 999999,
            )[:MAX_AUCTION_CANDIDATES]

            fixed_list = collect_lots_from_listing(page, FIXED_PRICE_URL, "fixed")
            fixed_list = sorted(
                fixed_list,
                key=lambda x: x.current_price if x.current_price is not None else 999999,
            )[:MAX_FIXED_CANDIDATES]

            log(f"Cartes enchères à inspecter: {len(auction_list)}")
            log(f"Cartes prix fixes à inspecter: {len(fixed_list)}")

            opportunities: list[Opportunity] = []
            inspected = 0

            for lot in auction_list + fixed_list:
                if time.monotonic() - started > MAX_SCAN_SECONDS:
                    log("Durée maximale du scan atteinte.")
                    break

                inspected += 1
                lot = inspect_item(page, lot)

                if lot.current_price is None or lot.current_price <= 0:
                    log(f"[{inspected}] Ignoré: prix actuel non lisible")
                    continue
                if lot.current_price > MAX_PRICE:
                    log(
                        f"[{inspected}] Ignoré: prix actuel {lot.current_price:.2f} € "
                        f"> budget {MAX_PRICE:.2f} €"
                    )
                    continue

                if not is_valid_pokemon_card(lot):
                    log(f"[{inspected}] Ignoré: pas une carte Pokémon individuelle")
                    continue

                if lot.source_type == "auction":
                    if lot.minutes_to_end is None:
                        log(f"[{inspected}] Ignoré: fin d'enchère non lisible")
                        continue
                    if lot.minutes_to_end > MAX_AUCTION_MINUTES:
                        log(f"[{inspected}] Ignoré: fin dans {lot.minutes_to_end} min")
                        continue

                history = extract_historical_sales(lot)

                state["seen"][lot.url] = {
                    "price": lot.current_price,
                    "seen_at": now,
                    "title": lot.title,
                    "source_type": lot.source_type,
                    "grade": f"{lot.grader} {lot.grade}".strip(),
                }

                log(
                    f"[{inspected}] {lot.source_type} | {lot.current_price:.2f} € "
                    f"| {lot.grader} {lot.grade} | historique: {len(history)} ventes"
                )

                op = estimate_with_grade(lot, history)
                if op:
                    opportunities.append(op)

            for op in sorted(opportunities, key=lambda x: x.discount_pct, reverse=True):
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
            log(f"Opportunités validées: {len(opportunities)}")

        finally:
            browser.close()

    log(f"=== Scan terminé en {time.monotonic() - started:.1f}s ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
