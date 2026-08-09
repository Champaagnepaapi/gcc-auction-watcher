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
MAX_PRICE = float(os.getenv("MAX_PRICE_EUR", "100"))
MIN_DISCOUNT = float(os.getenv("MIN_DISCOUNT_PCT", "20"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()

NAV_TIMEOUT = 15000
TEXT_TIMEOUT = 3000
MAX_SCAN_SECONDS = 240
MAX_CANDIDATES = 80

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


def collect_live_auction_urls(page) -> list[str]:
    log("Ouverture de la page d'accueil GCC...")
    page.goto(BASE, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    page.wait_for_timeout(1500)

    links = page.locator("a[href]")
    count = links.count()
    log(f"{count} liens trouvés sur la page d'accueil")

    urls = set()

    for i in range(count):
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


def collect_lots_from_sale(page, sale_url: str) -> list[Lot]:
    log(f"Ouverture vente: {sale_url}")
    page.goto(sale_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    page.wait_for_timeout(1500)

    last_height = 0
    stable = 0

    for _ in range(30):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(150)

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
    count = anchors.count()
    log(f"{count} liens d'items détectés")

    lots: dict[str, Lot] = {}

    for i in range(count):
        try:
            a = anchors.nth(i)
            href = a.get_attribute("href") or ""

            if not HREF_ITEM_RE.search(href):
                continue

            url = BASE + href if href.startswith("/") else href
            url = url.split("?")[0]

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

            price = parse_money(blob)

            title = ""
            for line in blob.splitlines():
                line = line.strip()
                if not line or "€" in line or line.upper() in {"LIVE", "ENDED", "SOON"}:
                    continue
                if len(line) >= 4:
                    title = line
                    break

            if not title:
                title = text.splitlines()[0].strip() if text else url.rsplit("/", 1)[-1]

            lots[url] = Lot(
                url=url,
                title=title,
                current_price=price,
                sale_name=sale_name,
            )

        except Exception:
            continue

    return list(lots.values())


def inspect_item(page, lot: Lot) -> tuple[Lot, list[float]]:
    try:
        page.goto(lot.url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        page.wait_for_timeout(700)

        body = page.locator("body").inner_text(timeout=TEXT_TIMEOUT)

        if lot.current_price is None:
            lot.current_price = parse_money(body)

        try:
            h1 = page.locator("h1").first.inner_text(timeout=800).strip()
            if h1:
                lot.title = h1
        except Exception:
            pass

        for line in body.splitlines():
            s = line.strip()
            if re.search(r"\b(Fin|Ends?)\b", s, re.I) and ("@" in s or ":" in s):
                lot.end_text = s[:180]
                break

        if not re.search(r"Historique des ventes|Sales history", body, re.I):
            return lot, []

        if re.search(r"Connectez-vous.*historique|log in.*history", body, re.I | re.S):
            return lot, []

        m = re.search(r"(Historique des ventes|Sales history)(.*)", body, re.I | re.S)
        if not m:
            return lot, []

        section = m.group(2)[:5000]
        vals = [float(x.replace(",", ".")) for x in MONEY_RE.findall(section)]
        vals = [v for v in vals if 1 <= v <= 50000]

        return lot, vals[:20]

    except PlaywrightTimeoutError:
        log(f"Timeout fiche: {lot.url}")
        return lot, []
    except Exception as e:
        log(f"Erreur fiche: {type(e).__name__}")
        return lot, []


def estimate_opportunity(lot: Lot, comps: list[float]) -> Optional[Opportunity]:
    if lot.current_price is None or lot.current_price > MAX_PRICE:
        return None

    if len(comps) < 2:
        return None

    market = median(comps)

    if market <= 0:
        return None

    discount = (market - lot.current_price) / market * 100

    if discount < MIN_DISCOUNT:
        return None

    confidence = "élevée" if len(comps) >= 5 else "moyenne"

    return Opportunity(
        lot=lot,
        estimated_market=market,
        discount_pct=discount,
        comps=comps,
        confidence=confidence,
    )


def notify(op: Opportunity) -> None:
    title = f"GCC: {op.discount_pct:.0f}% sous estimation"

    msg = (
        f"{op.lot.title}\n"
        f"Enchère: {op.lot.current_price:.2f} €\n"
        f"Marché estimé: {op.estimated_market:.2f} €\n"
        f"Décote: {op.discount_pct:.1f}% | confiance {op.confidence}\n"
        f"{op.lot.end_text}\n"
        f"{op.lot.url}"
    )

    log("*** OPPORTUNITÉ DÉTECTÉE ***")
    print(msg, flush=True)

    if NTFY_TOPIC:
        try:
            r = requests.post(
                f"{NTFY_SERVER}/{NTFY_TOPIC}",
                data=msg.encode("utf-8"),
                headers={
                    "Title": title,
                    "Priority": "4",
                    "Tags": "moneybag,card_index",
                },
                timeout=10,
            )
            r.raise_for_status()
            log("Notification ntfy envoyée")
        except Exception as e:
            log(f"Notification ntfy échouée: {e}")


def main() -> int:
    started = time.monotonic()
    log("=== GCC Auction Watcher démarré ===")
    log(f"Budget max: {MAX_PRICE:.0f} €")
    log(f"Décote minimale: {MIN_DISCOUNT:.0f}%")

    state = load_state()
    now = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as p:
        log("Lancement Chromium...")
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
            sales = collect_live_auction_urls(page)
            log(f"Ventes live détectées: {len(sales)}")

            for sale in sales:
                log(f"  - {sale}")

            if not sales:
                log("Aucune vente live détectée. Fin du scan.")
                return 0

            all_lots: dict[str, Lot] = {}

            for sale in sales:
                if time.monotonic() - started > MAX_SCAN_SECONDS:
                    log("Durée maximale du scan atteinte.")
                    break

                try:
                    lots = collect_lots_from_sale(page, sale)
                    log(f"{len(lots)} lots récupérés dans cette vente")

                    for lot in lots:
                        all_lots.setdefault(lot.url, lot)

                except PlaywrightTimeoutError:
                    log(f"Timeout vente: {sale}")

            log(f"Total lots uniques: {len(all_lots)}")

            candidates = [
                x
                for x in all_lots.values()
                if x.current_price is not None
                and x.current_price <= MAX_PRICE
            ]

            candidates.sort(key=lambda x: x.current_price or 999999)

            if len(candidates) > MAX_CANDIDATES:
                log(
                    f"{len(candidates)} candidats <= {MAX_PRICE:.0f} €, "
                    f"analyse limitée aux {MAX_CANDIDATES} moins chers."
                )
                candidates = candidates[:MAX_CANDIDATES]
            else:
                log(f"Candidats <= {MAX_PRICE:.0f} €: {len(candidates)}")

            opportunities = []

            total = len(candidates)

            for idx, lot in enumerate(candidates, start=1):
                elapsed = time.monotonic() - started

                if elapsed > MAX_SCAN_SECONDS:
                    log("Durée maximale du scan atteinte pendant l'analyse.")
                    break

                log(
                    f"[{idx}/{total}] {lot.current_price:.2f} € "
                    f"| {lot.title[:80]}"
                )

                lot, comps = inspect_item(page, lot)

                state["seen"][lot.url] = {
                    "price": lot.current_price,
                    "seen_at": now,
                    "title": lot.title,
                }

                if comps:
                    log(f"    {len(comps)} comparables GCC trouvés")
                else:
                    log("    Aucun historique public exploitable")

                op = estimate_opportunity(lot, comps)

                if op:
                    log(
                        f"    Candidat intéressant: "
                        f"{op.discount_pct:.1f}% sous estimation"
                    )
                    opportunities.append(op)

            for op in sorted(
                opportunities,
                key=lambda x: x.discount_pct,
                reverse=True,
            ):
                prev = state["notified"].get(op.lot.url)

                if not prev or op.discount_pct >= float(
                    prev.get("discount_pct", 0)
                ) + 5:
                    notify(op)

                    state["notified"][op.lot.url] = {
                        "discount_pct": op.discount_pct,
                        "price": op.lot.current_price,
                        "notified_at": now,
                    }

            save_state(state)

            log(f"Opportunités validées: {len(opportunities)}")

        finally:
            browser.close()

    elapsed = time.monotonic() - started
    log(f"=== Scan terminé en {elapsed:.1f} s ===")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
