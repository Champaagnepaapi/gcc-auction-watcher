from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import quote

import requests

import japan_edge_hunter as japan
from ecb_fx import ECBCurrencyConverter
from v4_global_market_core import (
    ACTIVE_AUCTION,
    AUCTION_SNAPSHOT_LE5,
    FIXED_ASK,
    SOLD_EXACT,
    CommercialIdentity,
    FairValue,
    PriceObservation,
    all_in_eur,
    build_fair_value,
    to_eur,
)
from v4_market_cardova import parse_auction_payload, parse_fixed_payload
from v4_market_fanatics_bridge import fanatics_fixed_offer
from v4_market_gcc_bridge import gcc_offer_to_observation
from v4_market_magi_bridge import magi_fixed_ask_to_observation
from v4_market_comc_bridge import comc_fixed_offer


GCC_API_URL = "https://api.gradedcardcenter.com/on-sale-items"
FANATICS_MARKETPLACE = "https://www.fanaticscollect.com/marketplace?type=FIXED&similarQuery={query}"
COMC_POKEMON = "https://www.comc.com/Cards/Pokemon"
CARD_RE = re.compile(r"(?<![A-Z0-9])#?([A-Z0-9-]{1,16})\s*/\s*([A-Z0-9-]{1,16})(?![A-Z0-9])", re.I)
PSA10_RE = re.compile(r"\bPSA\s*(?:GEM\s*MT\s*)?10(?:\.0)?\b", re.I)
USD_RE = re.compile(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.\d{1,2})?|[0-9]+(?:\.\d{1,2})?)")
SENSITIVE_WORDS = (
    "1st edition",
    "first edition",
    "shadowless",
    "incorrect texture",
    "error",
    "stamp",
    "stamped",
    "reverse",
    "master ball",
    "pokeball",
)


@dataclass(frozen=True)
class Seed:
    source_identity: japan.Identity
    identity: CommercialIdentity
    fair_value: FairValue


@dataclass(frozen=True)
class ShadowOffer:
    market: str
    evidence_type: str
    source_id: str
    source_url: str
    title: str
    currency: str
    price: float
    raw_eur: Optional[float]
    raw_discount_pct: Optional[float]
    all_in_eur: Optional[float]
    all_in_discount_pct: Optional[float]
    economic_basis: str
    note: str


@dataclass(frozen=True)
class SourceStatus:
    market: str
    status: str
    detail: str = ""
    searches: int = 0
    candidates: int = 0
    exact: int = 0


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _number(value: object) -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).upper().replace(" ", "").lstrip("#")
    if "/" not in raw:
        return raw.lstrip("0") or "0"
    left, right = raw.split("/", 1)
    if left.isdigit():
        left = str(int(left))
    if right.isdigit():
        right = str(int(right))
    return f"{left}/{right}"


def _grade(value: object) -> str:
    try:
        number = float(str(value or "").strip())
    except (TypeError, ValueError):
        return str(value or "").strip()
    return str(int(number)) if number.is_integer() else f"{number:g}"


def global_identity(identity: japan.Identity) -> CommercialIdentity:
    finish = str(identity.attribute or "").strip()
    variant = " | ".join(
        part for part in (str(identity.variety or "").strip(), str(identity.rarity or "").strip()) if part
    )
    return CommercialIdentity(
        name=identity.name,
        set_name=identity.set_name,
        number=identity.number,
        language="ja",
        grader=identity.grader,
        grade=identity.grade,
        edition=identity.edition,
        finish=finish,
        variant=variant,
    )


def _sold_observation(sale: japan.Sold, observed_at: datetime) -> PriceObservation:
    return PriceObservation(
        source="gcc",
        identity=global_identity(sale.identity),
        evidence_type=SOLD_EXACT,
        price=sale.price_eur,
        currency="EUR",
        observed_at=observed_at,
        identity_proven=True,
        sold_at=sale.sold_at,
        source_id=sale.source_id,
        note="GCC exact Japanese PSA10 SOLD",
    )


def build_seed_panel(
    sales: Sequence[japan.Sold],
    *,
    observed_at: datetime,
    max_identities: int,
) -> list[Seed]:
    grouped: dict[str, list[japan.Sold]] = {}
    identities: dict[str, japan.Identity] = {}
    for sale in sales:
        identity = global_identity(sale.identity)
        grouped.setdefault(identity.strict_key, []).append(sale)
        identities[identity.strict_key] = sale.identity
    seeds: list[Seed] = []
    for key, rows in grouped.items():
        identity = global_identity(identities[key])
        fair = build_fair_value(
            identity,
            [_sold_observation(row, observed_at) for row in rows],
            now=observed_at,
            currency_per_eur={},
        )
        if fair is None or not fair.notification_safe:
            continue
        seeds.append(Seed(identities[key], identity, fair))
    seeds.sort(
        key=lambda seed: (
            seed.fair_value.recent_90_count,
            seed.fair_value.evidence_count,
            seed.fair_value.central_eur,
        ),
        reverse=True,
    )
    return seeds[: max(1, max_identities)]


def _number_tokens(text: str) -> set[str]:
    return {_number(match.group(0)) for match in CARD_RE.finditer(unicodedata.normalize("NFKC", text or "").upper())}


def _sensitive_required(identity: japan.Identity) -> list[str]:
    values = [identity.edition, identity.attribute, identity.variety, identity.rarity]
    output: list[str] = []
    for value in values:
        normalized = _norm(value)
        for word in SENSITIVE_WORDS:
            if word in normalized and word not in output:
                output.append(word)
    return output


def strict_text_identity(text: str, identity: japan.Identity) -> tuple[bool, str]:
    normalized = _norm(text)
    if not normalized:
        return False, "empty_text"
    if _number(identity.number) not in _number_tokens(text):
        return False, "collector_number_unproven"
    if not PSA10_RE.search(unicodedata.normalize("NFKC", text or "")):
        return False, "psa10_unproven"
    if not any(token in normalized for token in ("japanese", "japan", "jpn")):
        return False, "language_unproven"
    if _norm(identity.name) not in normalized:
        return False, "card_name_unproven"
    target_set = _norm(identity.set_name)
    if target_set and target_set not in normalized:
        return False, "set_unproven"
    for word in _sensitive_required(identity):
        if word not in normalized:
            return False, f"sensitive_variant_unproven:{word}"
    return True, "strict_text_identity"


def _price_from_usd_text(text: str) -> Optional[float]:
    values: list[float] = []
    for match in USD_RE.finditer(text or ""):
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if 0.01 <= value <= 10_000_000:
            values.append(value)
    return values[0] if values else None


def _fx_map(converter: ECBCurrencyConverter) -> dict[str, float]:
    snapshot = converter.get_snapshot()
    if snapshot is None:
        return {}
    output: dict[str, float] = {}
    for currency in ("USD", "JPY", "CHF", "GBP"):
        value = snapshot.units_per_eur.get(currency)
        if value is not None and value > 0:
            output[currency] = float(value)
    return output


def _discount(fair: FairValue, value_eur: Optional[float]) -> Optional[float]:
    if value_eur is None or fair.central_eur <= 0:
        return None
    return round((fair.central_eur - value_eur) / fair.central_eur * 100.0, 1)


def _shadow_offer(
    observation: PriceObservation,
    fair: FairValue,
    *,
    fx: Mapping[str, float],
    source_url: str = "",
    title: str = "",
    economic_basis: str,
) -> ShadowOffer:
    raw = to_eur(observation.price, observation.currency, fx)
    landed = all_in_eur(observation, fx)
    return ShadowOffer(
        market=observation.source,
        evidence_type=observation.evidence_type,
        source_id=observation.source_id,
        source_url=source_url,
        title=title,
        currency=observation.currency,
        price=round(float(observation.price), 2),
        raw_eur=round(raw, 2) if raw is not None else None,
        raw_discount_pct=_discount(fair, raw),
        all_in_eur=round(landed, 2) if landed is not None else None,
        all_in_discount_pct=_discount(fair, landed),
        economic_basis=economic_basis,
        note=observation.note,
    )


def _gcc_row_identity(row: Mapping[str, Any]) -> Optional[japan.Identity]:
    item = row.get("item")
    if not isinstance(item, Mapping):
        return None
    collectible = item.get("collectible")
    if not isinstance(collectible, Mapping):
        return None
    if _norm(collectible.get("category")) != "pokemon" or _norm(collectible.get("type")) != "cards":
        return None
    if _norm(collectible.get("language")) != "japanese":
        return None
    if str(item.get("gradingCompany") or "").strip().upper() != "PSA" or _grade(item.get("grade")) != "10":
        return None
    character = collectible.get("character")
    name = ""
    if isinstance(character, Mapping):
        name = str(character.get("englishName") or character.get("name") or "").strip()
    try:
        year = int(collectible.get("yearOfDistribution"))
    except (TypeError, ValueError):
        return None
    identity = japan.Identity(
        name=name,
        set_name=str(collectible.get("set") or "").strip(),
        number=japan.number(collectible.get("reference")),
        language="Japanese",
        grader="PSA",
        grade="10",
        year=year,
        edition=str(collectible.get("edition") or "").strip(),
        attribute=str(collectible.get("attribute") or "").strip(),
        variety=str(collectible.get("variety") or "").strip(),
        rarity=str(collectible.get("rarity") or "").strip(),
    )
    if not identity.name or not identity.set_name or not identity.number:
        return None
    return identity


def _gcc_price(row: Mapping[str, Any]) -> Optional[float]:
    cents = row.get("priceInCents")
    if isinstance(cents, int) and not isinstance(cents, bool) and cents > 0:
        return cents / 100.0
    try:
        value = float(row.get("price") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _parse_time(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def fetch_gcc_live(
    seeds: Sequence[Seed],
    *,
    observed_at: datetime,
    max_pages_each: int = 8,
    session: Optional[requests.Session] = None,
) -> tuple[dict[str, list[tuple[PriceObservation, str, str]]], SourceStatus]:
    target = {seed.source_identity.key: seed for seed in seeds}
    found: dict[str, list[tuple[PriceObservation, str, str]]] = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    http = session or requests.Session()
    try:
        for group in ("FIXED_PRICE", "AUCTION"):
            for page_number in range(1, max(1, max_pages_each) + 1):
                params = {
                    "sellingTypeGroup": group,
                    "status": "ON_SALE",
                    "sortType": "ENDING_SOON" if group == "AUCTION" else "MOST_RECENT",
                    "page": page_number,
                    "limit": 100,
                    "includeCounts": "true" if page_number == 1 else "false",
                }
                response = http.get(GCC_API_URL, params=params, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"}, timeout=15)
                response.raise_for_status()
                searches += 1
                payload = response.json()
                rows = payload.get("results") if isinstance(payload, Mapping) else None
                if not isinstance(rows, list):
                    return found, SourceStatus("gcc", "MALFORMED", "results missing", searches, candidates, exact)
                if not rows:
                    break
                for raw in rows:
                    if not isinstance(raw, Mapping):
                        continue
                    candidates += 1
                    source_identity = _gcc_row_identity(raw)
                    if source_identity is None or source_identity.key not in target:
                        continue
                    seed = target[source_identity.key]
                    price = _gcc_price(raw)
                    if price is None:
                        continue
                    source_id = str(raw.get("id") or "").strip()
                    url = f"https://gradedcardcenter.com/item/{source_id}" if source_id else ""
                    if group == "FIXED_PRICE":
                        observation = gcc_offer_to_observation(
                            identity=seed.identity,
                            price_eur=price,
                            observed_at=observed_at,
                            source_id=source_id,
                            offer_type="fixed",
                            identity_proven=True,
                            buyer_fee_rate=None,
                            note="GCC fixed ASK; buyer/logistics all-in not modeled in global shadow",
                        )
                    else:
                        end_at = _parse_time(raw.get("endTime") or raw.get("endAt"))
                        remaining = (end_at - observed_at).total_seconds() / 60.0 if end_at is not None else None
                        within_five = remaining is not None and 0 <= remaining <= 5
                        observation = gcc_offer_to_observation(
                            identity=seed.identity,
                            price_eur=price,
                            observed_at=observed_at,
                            source_id=source_id,
                            offer_type="auction",
                            identity_proven=True,
                            buyer_fee_rate=None,
                            end_at=end_at,
                            within_five_minutes=within_five,
                            note="GCC live auction; weak unless observed <=5m; never SOLD",
                        )
                    found[seed.identity.strict_key].append((observation, url, ""))
                    exact += 1
                info = payload.get("info") if isinstance(payload, Mapping) else None
                if isinstance(info, Mapping) and not info.get("nextPage"):
                    break
    except Exception as error:
        return found, SourceStatus("gcc", "ERROR", type(error).__name__, searches, candidates, exact)
    finally:
        if session is None:
            http.close()
    return found, SourceStatus("gcc", "OK", "public GET-only", searches, candidates, exact)


def _magi_provider() -> japan.Provider:
    return next(provider for provider in japan.PROVIDERS if provider.code == "magi")


def collect_magi(
    page: Any,
    seeds: Sequence[Seed],
    *,
    observed_at: datetime,
    max_candidates: int = 12,
) -> tuple[dict[str, list[tuple[PriceObservation, str, str]]], SourceStatus]:
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    provider = _magi_provider()
    for seed in seeds:
        try:
            asks = japan.collect(page, provider, seed.source_identity, max_items=max_candidates)
            searches += 1
        except Exception as error:
            return found, SourceStatus("magi", "ERROR", type(error).__name__, searches, candidates, exact)
        for ask in asks:
            candidates += 1
            try:
                detailed = japan.detail(page, ask)
            except Exception:
                continue
            ok, _proof = japan.identity_check(detailed, seed.source_identity)
            if not ok:
                continue
            observation = magi_fixed_ask_to_observation(
                identity=seed.identity,
                price_jpy=detailed.price_jpy,
                observed_at=observed_at,
                source_id=detailed.url,
                identity_proven=True,
                buyer_fee_rate=None,
                note="magi fixed ASK; buyer/logistics all-in intentionally unproven in global shadow",
            )
            found[seed.identity.strict_key].append((observation, detailed.url, detailed.title))
            exact += 1
    return found, SourceStatus("magi", "OK", "public read-only browser", searches, candidates, exact)


def _fanatics_candidate_links(page: Any, seed: Seed, max_candidates: int) -> list[str]:
    query = quote(
        f"{seed.source_identity.name} {seed.source_identity.number} {seed.source_identity.set_name} Japanese PSA 10",
        safe="",
    )
    page.goto(FANATICS_MARKETPLACE.format(query=query), wait_until="domcontentloaded", timeout=25000)
    page.wait_for_timeout(1200)
    links = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href*="/buy-now/"]')).map(a => a.href).filter(Boolean)"""
    )
    output: list[str] = []
    for link in links if isinstance(links, list) else []:
        value = str(link).split("#", 1)[0].split("?", 1)[0]
        if value not in output:
            output.append(value)
        if len(output) >= max_candidates:
            break
    return output


def collect_fanatics(
    page: Any,
    seeds: Sequence[Seed],
    *,
    observed_at: datetime,
    max_candidates: int = 8,
) -> tuple[dict[str, list[tuple[PriceObservation, str, str]]], SourceStatus]:
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    for seed in seeds:
        try:
            links = _fanatics_candidate_links(page, seed, max_candidates)
            searches += 1
        except Exception as error:
            return found, SourceStatus("fanatics", "ERROR", type(error).__name__, searches, candidates, exact)
        for url in links:
            candidates += 1
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(700)
                title = page.locator("h1").first.inner_text(timeout=4000).strip()
                body = page.locator("body").inner_text(timeout=5000)
            except Exception:
                continue
            upper = body.upper()
            if "THIS ITEM IS NOT AVAILABLE" in upper or re.search(r"\bSOLD\s*:", upper):
                continue
            before_guide = re.split(r"Guide Price", body, maxsplit=1, flags=re.I)[0]
            price = _price_from_usd_text(before_guide)
            if price is None:
                continue
            ok, _proof = strict_text_identity(f"{title}\n{before_guide}", seed.source_identity)
            if not ok:
                continue
            observation = fanatics_fixed_offer(
                identity=seed.identity,
                price_usd=price,
                observed_at=observed_at,
                source_id=url,
                identity_proven=True,
                buyer_fee_rate=0.0,
                note="Fanatics Buy Now ASK; official Buy Now buyer fee 0; vault acquisition basis; tax/payment/shipping excluded",
            )
            found[seed.identity.strict_key].append((observation, url, title))
            exact += 1
    return found, SourceStatus("fanatics", "OK", "public Buy Now read-only; vault-price basis", searches, candidates, exact)


def _comc_player_url(page: Any, name: str) -> Optional[str]:
    page.goto(COMC_POKEMON, wait_until="domcontentloaded", timeout=25000)
    page.wait_for_timeout(800)
    links = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href*="/Players/Pokemon/"]')).map(a => ({href:a.href, text:(a.innerText||a.textContent||'').trim()}))"""
    )
    target = _norm(name)
    for row in links if isinstance(links, list) else []:
        if isinstance(row, Mapping) and _norm(row.get("text")) == target:
            return str(row.get("href") or "").split("?", 1)[0]
    return None


def _comc_candidate_links(page: Any, seed: Seed, max_candidates: int) -> list[str]:
    player_url = _comc_player_url(page, seed.source_identity.name)
    if not player_url:
        return []
    page.goto(player_url, wait_until="domcontentloaded", timeout=25000)
    page.wait_for_timeout(800)
    rows = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href*="/Cards/Pokemon/"]')).map(a => {let n=a;let t='';for(let i=0;i<5&&n;i++,n=n.parentElement){const x=(n.innerText||n.textContent||'').trim();if(x.length>t.length)t=x;}return {href:a.href,text:t};})"""
    )
    target_number = _number(seed.source_identity.number)
    output: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        text = str(row.get("text") or "")
        if target_number not in _number_tokens(text):
            continue
        url = str(row.get("href") or "").split("?", 1)[0]
        if url and url not in output:
            output.append(url)
        if len(output) >= max_candidates:
            break
    return output


def _comc_ask_price(body: str) -> Optional[float]:
    match = re.search(r"All Sellers\s*(?:\||:)?\s*\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)", body or "", re.I)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def collect_comc(
    page: Any,
    seeds: Sequence[Seed],
    *,
    observed_at: datetime,
    max_candidates: int = 8,
) -> tuple[dict[str, list[tuple[PriceObservation, str, str]]], SourceStatus]:
    found = {seed.identity.strict_key: [] for seed in seeds}
    searches = candidates = exact = 0
    for seed in seeds:
        try:
            links = _comc_candidate_links(page, seed, max_candidates)
            searches += 1
        except Exception as error:
            return found, SourceStatus("comc", "ERROR", type(error).__name__, searches, candidates, exact)
        for url in links:
            candidates += 1
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(600)
                title = page.locator("h1").first.inner_text(timeout=4000).strip()
                body = page.locator("body").inner_text(timeout=5000)
            except Exception:
                continue
            if "SOLD OUT" in body.upper() or "0 RESULTS" in body.upper():
                continue
            price = _comc_ask_price(body)
            if price is None:
                continue
            evidence_text = f"{title}\n{body[:6000]}"
            ok, _proof = strict_text_identity(evidence_text, seed.source_identity)
            if not ok:
                continue
            observation = comc_fixed_offer(
                identity=seed.identity,
                price_usd=price,
                observed_at=observed_at,
                source_id=url,
                identity_proven=True,
                buyer_fee_rate=None,
                note="COMC Buy Now ASK; buyer/logistics all-in intentionally unproven in global shadow",
            )
            found[seed.identity.strict_key].append((observation, url, title))
            exact += 1
    return found, SourceStatus("comc", "OK", "public read-only; exact listing proof required", searches, candidates, exact)


def load_cardova(
    seeds: Sequence[Seed],
    *,
    observed_at: datetime,
    fixed_path: Optional[Path],
    auction_path: Optional[Path],
) -> tuple[dict[str, list[tuple[PriceObservation, str, str]]], SourceStatus]:
    found = {seed.identity.strict_key: [] for seed in seeds}
    if fixed_path is None and auction_path is None:
        return found, SourceStatus(
            "cardova",
            "AUTH_SESSION_INPUT_REQUIRED",
            "GitHub shadow never receives browser cookies/tokens; provide a local sanitized JSON snapshot instead",
        )
    target = {seed.identity.strict_key: seed for seed in seeds}
    candidates = exact = 0
    try:
        observations: list[PriceObservation] = []
        if fixed_path is not None:
            payload = json.loads(fixed_path.read_text())
            observations.extend(parse_fixed_payload(payload, observed_at=observed_at, buyer_fee_rate=0.0, logistics_jpy=0.0))
        if auction_path is not None:
            payload = json.loads(auction_path.read_text())
            observations.extend(parse_auction_payload(payload, observed_at=observed_at, buyer_premium_rate=None, logistics_jpy=0.0))
        for observation in observations:
            candidates += 1
            for seed in seeds:
                candidate = observation.identity
                same = (
                    _norm(candidate.name) == _norm(seed.identity.name)
                    and _norm(candidate.set_name) == _norm(seed.identity.set_name)
                    and _number(candidate.number) == _number(seed.identity.number)
                    and candidate.language == seed.identity.language
                    and _norm(candidate.grader) == _norm(seed.identity.grader)
                    and _grade(candidate.grade) == _grade(seed.identity.grade)
                )
                if not same:
                    continue
                rebound = PriceObservation(
                    source=observation.source,
                    identity=seed.identity,
                    evidence_type=observation.evidence_type,
                    price=observation.price,
                    currency=observation.currency,
                    observed_at=observation.observed_at,
                    identity_proven=True,
                    end_at=observation.end_at,
                    buyer_fee_rate=observation.buyer_fee_rate,
                    buyer_fee_flat=observation.buyer_fee_flat,
                    logistics_cost=observation.logistics_cost,
                    note=observation.note,
                    source_id=observation.source_id,
                )
                found[target[seed.identity.strict_key].identity.strict_key].append((rebound, "", ""))
                exact += 1
                break
    except Exception as error:
        return found, SourceStatus("cardova", "ERROR", type(error).__name__, 0, candidates, exact)
    return found, SourceStatus("cardova", "OK", "sanitized same-browser JSON input; no credentials", 0, candidates, exact)


def best_offer(offers: Sequence[ShadowOffer]) -> tuple[str, Optional[float], str]:
    actionable = [offer for offer in offers if offer.evidence_type in {FIXED_ASK, AUCTION_SNAPSHOT_LE5}]
    all_in = [offer for offer in actionable if offer.all_in_eur is not None]
    if all_in:
        winner = min(all_in, key=lambda offer: float(offer.all_in_eur or 10**18))
        return winner.market, winner.all_in_discount_pct, "PROVEN_OR_DECLARED_ALL_IN_BASIS"
    raw = [offer for offer in actionable if offer.raw_eur is not None]
    if raw:
        winner = min(raw, key=lambda offer: float(offer.raw_eur or 10**18))
        return winner.market, winner.raw_discount_pct, "RAW_ASK_ONLY"
    return "", None, "NO_ACTIONABLE_PRICE"


def build_report(
    seeds: Sequence[Seed],
    source_rows: Mapping[str, Mapping[str, Sequence[tuple[PriceObservation, str, str]]]],
    *,
    fx: Mapping[str, float],
    statuses: Sequence[SourceStatus],
    observed_at: datetime,
) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    for seed in seeds:
        offers: list[ShadowOffer] = []
        for market, per_identity in source_rows.items():
            for observation, url, title in per_identity.get(seed.identity.strict_key, ()):
                if observation.identity.strict_key != seed.identity.strict_key:
                    continue
                basis = {
                    "fanatics": "VAULT_ACQUISITION_PRICE",
                    "cardova": "VAULT_PRICE_IF_FIXED; AUCTION_PREMIUM_UNPROVEN",
                    "gcc": "RAW_PLATFORM_PRICE",
                    "magi": "RAW_ASK",
                    "comc": "RAW_ASK",
                }.get(market, "RAW_PRICE")
                offers.append(_shadow_offer(observation, seed.fair_value, fx=fx, source_url=url, title=title, economic_basis=basis))
        offers.sort(key=lambda offer: (offer.raw_eur is None, offer.raw_eur or 10**18, offer.market))
        market, discount, ranking_basis = best_offer(offers)
        cards.append(
            {
                "identity": asdict(seed.identity),
                "fair_value_eur": seed.fair_value.central_eur,
                "fair_low_eur": seed.fair_value.low_eur,
                "fair_high_eur": seed.fair_value.high_eur,
                "fair_method": seed.fair_value.method,
                "fair_evidence_count": seed.fair_value.evidence_count,
                "fair_recent_90_count": seed.fair_value.recent_90_count,
                "fair_sources": list(seed.fair_value.sources),
                "offers": [asdict(offer) for offer in offers],
                "best_market": market,
                "best_discount_pct": discount,
                "best_ranking_basis": ranking_basis,
            }
        )
    return {
        "schema_version": 1,
        "observed_at": observed_at.isoformat(),
        "mode": "READ_ONLY_SHADOW",
        "notifications": False,
        "transactions": False,
        "identity_scope": "Japanese PSA10 exact seeds from GCC SOLD for first live benchmark",
        "source_status": [asdict(status) for status in statuses],
        "cards": cards,
    }


def write_report(report: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "global_market_shadow.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    rows: list[dict[str, Any]] = []
    for card in report.get("cards", []):
        identity = card.get("identity", {})
        offers = card.get("offers", [])
        if not offers:
            rows.append(
                {
                    "name": identity.get("name", ""),
                    "set": identity.get("set_name", ""),
                    "number": identity.get("number", ""),
                    "language": identity.get("language", ""),
                    "grader": identity.get("grader", ""),
                    "grade": identity.get("grade", ""),
                    "fair_eur": card.get("fair_value_eur"),
                    "market": "",
                    "evidence": "",
                    "price": "",
                    "currency": "",
                    "raw_eur": "",
                    "raw_discount_pct": "",
                    "all_in_eur": "",
                    "all_in_discount_pct": "",
                    "best_market": card.get("best_market", ""),
                    "best_ranking_basis": card.get("best_ranking_basis", ""),
                }
            )
            continue
        for offer in offers:
            rows.append(
                {
                    "name": identity.get("name", ""),
                    "set": identity.get("set_name", ""),
                    "number": identity.get("number", ""),
                    "language": identity.get("language", ""),
                    "grader": identity.get("grader", ""),
                    "grade": identity.get("grade", ""),
                    "fair_eur": card.get("fair_value_eur"),
                    "market": offer.get("market"),
                    "evidence": offer.get("evidence_type"),
                    "price": offer.get("price"),
                    "currency": offer.get("currency"),
                    "raw_eur": offer.get("raw_eur"),
                    "raw_discount_pct": offer.get("raw_discount_pct"),
                    "all_in_eur": offer.get("all_in_eur"),
                    "all_in_discount_pct": offer.get("all_in_discount_pct"),
                    "best_market": card.get("best_market", ""),
                    "best_ranking_basis": card.get("best_ranking_basis", ""),
                }
            )
    fieldnames = list(rows[0]) if rows else ["name", "fair_eur", "market"]
    with (output_dir / "global_market_shadow.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> dict[str, Any]:
    observed_at = now_utc()
    diagnostics = japan.Diagnostics()
    sales = japan.fetch_gcc(max_pages=max(1, args.gcc_sold_pages), diag=diagnostics)
    seeds = build_seed_panel(sales, observed_at=observed_at, max_identities=max(1, args.max_identities))
    fx_converter = ECBCurrencyConverter()
    fx = _fx_map(fx_converter)
    rows: dict[str, Mapping[str, Sequence[tuple[PriceObservation, str, str]]]] = {}
    statuses: list[SourceStatus] = []

    gcc_rows, gcc_status = fetch_gcc_live(seeds, observed_at=observed_at, max_pages_each=max(1, args.gcc_live_pages))
    rows["gcc"] = gcc_rows
    statuses.append(gcc_status)

    cardova_rows, cardova_status = load_cardova(
        seeds,
        observed_at=observed_at,
        fixed_path=Path(args.cardova_fixed_json) if args.cardova_fixed_json else None,
        auction_path=Path(args.cardova_auction_json) if args.cardova_auction_json else None,
    )
    rows["cardova"] = cardova_rows
    statuses.append(cardova_status)

    if not args.no_browser_sources and seeds:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(locale="en-US", user_agent="Mozilla/5.0")
            page = context.new_page()
            magi_rows, magi_status = collect_magi(page, seeds, observed_at=observed_at, max_candidates=args.market_candidates)
            rows["magi"] = magi_rows
            statuses.append(magi_status)
            fanatics_rows, fanatics_status = collect_fanatics(page, seeds, observed_at=observed_at, max_candidates=args.market_candidates)
            rows["fanatics"] = fanatics_rows
            statuses.append(fanatics_status)
            comc_rows, comc_status = collect_comc(page, seeds, observed_at=observed_at, max_candidates=args.market_candidates)
            rows["comc"] = comc_rows
            statuses.append(comc_status)
            context.close()
            browser.close()
    else:
        for market in ("magi", "fanatics", "comc"):
            rows[market] = {seed.identity.strict_key: [] for seed in seeds}
            statuses.append(SourceStatus(market, "SKIPPED", "browser sources disabled"))

    report = build_report(seeds, rows, fx=fx, statuses=statuses, observed_at=observed_at)
    report["gcc_sold_diagnostics"] = asdict(diagnostics)
    report["fx"] = {
        "provider": "ECB",
        "currency_per_eur": fx,
        "available": bool(fx),
    }
    write_report(report, Path(args.output_dir))
    return report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Read-only V4 global multi-market live shadow")
    value.add_argument("--output-dir", default="global_shadow_out")
    value.add_argument("--max-identities", type=int, default=5)
    value.add_argument("--gcc-sold-pages", type=int, default=20)
    value.add_argument("--gcc-live-pages", type=int, default=8)
    value.add_argument("--market-candidates", type=int, default=8)
    value.add_argument("--cardova-fixed-json", default="")
    value.add_argument("--cardova-auction-json", default="")
    value.add_argument("--no-browser-sources", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    report = run(args)
    print(json.dumps({
        "mode": report.get("mode"),
        "cards": len(report.get("cards", [])),
        "source_status": report.get("source_status", []),
        "output": str(Path(args.output_dir).resolve()),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
