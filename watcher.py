from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Optional

import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv()

BASE = "https://gradedcardcenter.com"
MAX_PRICE = float(os.getenv("MAX_PRICE_EUR", "100"))
MIN_DISCOUNT = float(os.getenv("MIN_DISCOUNT_PCT", "20"))
MAX_HOURS_TO_END = float(os.getenv("MAX_HOURS_TO_END", "12"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()

MONEY_RE = re.compile(r"(?<!\d)(\d{1,5}(?:[.,]\d{1,2})?)\s*€")
HREF_ITEM_RE = re.compile(r"/item/[0-9a-f-]{20,}", re.I)


@dataclass
class Lot:
    url: str
    title: str
    current_price: Optional[float]
    end_text: str = ""
    sale_name: str = ""


@dataclass
class Opportunity:
    lot: Lot
    estimated_market: float
    discount_pct: float
    comps: list[float]
    confidence: str


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"notified": {}, "seen": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_money(text: str) -> Optional[float]:
    vals = []
    for m in MONEY_RE.findall(text or ""):
        try:
            vals.append(float(m.replace(",", ".")))
        except ValueError:
            continue
    # Sur une carte de listing, le premier prix visible est généralement le prix courant.
    return vals[0] if vals else None


def collect_live_auction_urls(page) -> list[str]:
    page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    links = page.locator("a[href]")
    urls = set()
    for i in range(links.count()):
        a = links.nth(i)
        try:
            href = a.get_attribute("href") or ""
            txt = (a.inner_text(timeout=500) or "").strip()
        except Exception:
            continue
        # GCC utilise /filtres/auction/... ou /en/filters/auction/...
        if "/auction/" in href and ("LIVE" in txt.upper() or "AUCTION" in href.upper()):
            if href.startswith("/"):
                href = BASE + href
            if href.startswith(BASE):
                urls.add(href.split("?")[0])
    return sorted(urls)


def collect_lots_from_sale(page, sale_url: str) -> list[Lot]:
    page.goto(sale_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)

    # Déclenche le lazy-loading en scrollant progressivement.
    last_height = 0
    stable = 0
    for _ in range(60):
        page.mouse.wheel(0, 2200)
        page.wait_for_timeout(250)
        h = page.evaluate("document.body.scrollHeight")
        if h == last_height:
            stable += 1
            if stable >= 4:
                break
        else:
            stable = 0
            last_height = h

    sale_name = ""
    try:
        sale_name = page.locator("h1").first.inner_text(timeout=1000).strip()
    except Exception:
        pass

    # Cherche tous les liens d'items; remonte à un conteneur raisonnable pour récupérer le texte/prix.
    anchors = page.locator('a[href*="/item/"]')
    lots: dict[str, Lot] = {}
    for i in range(anchors.count()):
        a = anchors.nth(i)
        try:
            href = a.get_attribute("href") or ""
            if not HREF_ITEM_RE.search(href):
                continue
            url = BASE + href if href.startswith("/") else href
            url = url.split("?")[0]

            text = (a.inner_text(timeout=500) or "").strip()
            # Souvent le lien lui-même ne contient pas tout; remonter de 1 à 4 parents.
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
            blob = min((t for t in candidate_texts if "€" in t), key=len, default=max(candidate_texts, key=len, default=""))
            price = parse_money(blob)

            # Titre: première ligne informative qui n'est pas juste un prix/badge.
            title = ""
            for line in blob.splitlines():
                line = line.strip()
                if not line or "€" in line or line.upper() in {"LIVE", "ENDED", "SOON"}:
                    continue
                if len(line) >= 4:
                    title = line
                    break
            if not title:
                title = (text.splitlines()[0].strip() if text else url.rsplit("/", 1)[-1])

            if url not in lots or (lots[url].current_price is None and price is not None):
                lots[url] = Lot(url=url, title=title, current_price=price, sale_name=sale_name)
        except Exception:
            continue
    return list(lots.values())


def fetch_item_details(page, lot: Lot) -> Lot:
    try:
        page.goto(lot.url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1200)
        body = page.locator("body").inner_text(timeout=3000)
        if lot.current_price is None:
            lot.current_price = parse_money(body)
        # Capture une ligne "Fin ..." / "Ends ..." si présente.
        for line in body.splitlines():
            s = line.strip()
            if re.search(r"\b(Fin|Ends?)\b", s, re.I) and ("@" in s or ":" in s):
                lot.end_text = s[:180]
                break
        # Titre plus fiable via h1.
        try:
            h1 = page.locator("h1").first.inner_text(timeout=800).strip()
            if h1:
                lot.title = h1
        except Exception:
            pass
    except Exception:
        pass
    return lot


def gcc_historical_comps(page, lot: Lot) -> list[float]:
    """Extraction conservatrice des prix d'historique visibles publiquement sur la fiche.
    Si GCC exige une connexion pour l'historique, retourne [].
    """
    try:
        page.goto(lot.url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1000)
        body = page.locator("body").inner_text(timeout=2500)
    except Exception:
        return []

    # On ne prend des valeurs que si la page semble exposer une section historique.
    if not re.search(r"Historique des ventes|Sales history", body, re.I):
        return []
    if re.search(r"Connectez-vous.*historique|log in.*history", body, re.I | re.S):
        return []

    # Limitation volontaire: éviter de confondre prix courant, shipping, etc.
    # Cherche des montants après le début de la section historique.
    m = re.search(r"(Historique des ventes|Sales history)(.*)", body, re.I | re.S)
    if not m:
        return []
    section = m.group(2)[:5000]
    vals = [float(x.replace(",", ".")) for x in MONEY_RE.findall(section)]
    vals = [v for v in vals if 1 <= v <= 50000]
    return vals[:20]


def estimate_opportunity(page, lot: Lot) -> Optional[Opportunity]:
    if lot.current_price is None or lot.current_price > MAX_PRICE:
        return None

    comps = gcc_historical_comps(page, lot)
    if len(comps) < 2:
        # Pas assez de données fiables : on n'invente pas une valeur.
        return None

    market = median(comps)
    if market <= 0:
        return None
    discount = (market - lot.current_price) / market * 100
    if discount < MIN_DISCOUNT:
        return None

    confidence = "élevée" if len(comps) >= 5 else "moyenne"
    return Opportunity(lot=lot, estimated_market=market, discount_pct=discount, comps=comps, confidence=confidence)


def notify(op: Opportunity) -> None:
    title = f"GCC: {op.discount_pct:.0f}% sous estimation"
    msg = (
        f"{op.lot.title}\n"
        f"Enchère: {op.lot.current_price:.2f} €\n"
        f"Marché estimé: {op.estimated_market:.2f} €\n"
        f"Décote: {op.discount_pct:.1f}% | confiance {op.confidence}\n"
        f"{op.lot.end_text}\n{op.lot.url}"
    )
    print("\n*** OPPORTUNITÉ ***\n" + msg + "\n")

    if NTFY_TOPIC:
        try:
            requests.post(
                f"{NTFY_SERVER}/{NTFY_TOPIC}",
                data=msg.encode("utf-8"),
                headers={"Title": title, "Priority": "4", "Tags": "moneybag,card_index"},
                timeout=15,
            ).raise_for_status()
        except Exception as e:
            print(f"Notification ntfy échouée: {e}")


def main() -> int:
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(locale="fr-FR", timezone_id="Europe/Zurich")
        page = context.new_page()

        try:
            sales = collect_live_auction_urls(page)
            print(f"Ventes détectées: {len(sales)}")
            all_lots: dict[str, Lot] = {}
            for sale in sales:
                try:
                    lots = collect_lots_from_sale(page, sale)
                    print(f"- {sale}: {len(lots)} lots détectés")
                    for lot in lots:
                        if lot.url not in all_lots:
                            all_lots[lot.url] = lot
                except PlaywrightTimeoutError:
                    print(f"Timeout: {sale}")

            candidates = [x for x in all_lots.values() if x.current_price is not None and x.current_price <= MAX_PRICE]
            candidates.sort(key=lambda x: x.current_price or 999999)
            print(f"Lots <= {MAX_PRICE:.0f} €: {len(candidates)}")

            # Pour éviter de marteler GCC, on enrichit seulement les candidats budget.
            opportunities = []
            for lot in candidates:
                lot = fetch_item_details(page, lot)
                state["seen"][lot.url] = {"price": lot.current_price, "seen_at": now, "title": lot.title}
                op = estimate_opportunity(page, lot)
                if op:
                    opportunities.append(op)
                time.sleep(0.15)

            for op in sorted(opportunities, key=lambda x: x.discount_pct, reverse=True):
                key = op.lot.url
                prev = state["notified"].get(key)
                # Renotifie si l'opportunité s'améliore de >=5 points ou si jamais notifiée.
                if not prev or op.discount_pct >= float(prev.get("discount_pct", 0)) + 5:
                    notify(op)
                    state["notified"][key] = {
                        "discount_pct": op.discount_pct,
                        "price": op.lot.current_price,
                        "notified_at": now,
                    }

            save_state(state)
            print(f"Opportunités validées: {len(opportunities)}")
        finally:
            browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
