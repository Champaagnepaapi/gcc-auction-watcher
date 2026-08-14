from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import quote

import requests

from .card_identity_catalog import MultilingualPokemonCardResolver
from .ebay import RAW_CONDITION_ID, parse_ebay_item, resolve_card_identity
from .ebay_live_diagnostic import DEFAULT_LIVE_MARKETPLACES, EbayLiveDiagnostic
from .justtcg_identity import JustTCGIdentityResolver
from .models import CardIdentity
from .poketrace_matching import (
    _card_number_parts,
    _normalize,
    _normalize_card_name,
    _normalize_card_number,
    _set_similarity,
)

PROVIDERS = (
    "poketrace", "pokemonpricetracker", "justtcg", "tcgdex",
    "pokewallet", "tcgapi_dev", "tcg_cardmarket", "cmapi", "cardtrader",
)
UPSTREAM = {
    "poketrace": "eBay + TCGPlayer + Cardmarket",
    "pokemonpricetracker": "TCGPlayer + eBay",
    "justtcg": "TCGPlayer-oriented",
    "tcgdex": "TCGPlayer + Cardmarket",
    "pokewallet": "TCGPlayer + Cardmarket",
    "tcgapi_dev": "provider-aggregated marketplace pricing",
    "tcg_cardmarket": "Cardmarket",
    "cmapi": "Cardmarket + TCGPlayer + eBay graded",
    "cardtrader": "CardTrader asks; Cardmarket/TCGPlayer IDs",
}
PLAN = {
    "poketrace": "Pro; 10k/day; US+EU; graded; full history",
    "pokemonpricetracker": "Free; 100 credits/day; 3-day history; eBay graded costs credits",
    "justtcg": "Free; 100/day; 1000/month; 10/min",
    "tcgdex": "Free/no key",
    "pokewallet": "Free endpoints only; 7-day Pro trial NOT activated",
    "tcgapi_dev": "Free; 100/day; current prices",
    "tcg_cardmarket": "Free; 100/day; hard 429",
    "cmapi": "RapidAPI Basic; 100/day then PAID overage; disabled by default",
    "cardtrader": "Full API; current marketplace asks",
}

PANEL_SIZE = 20
DETAIL_BUDGET = 50
DEPTH_SENTINELS = 5
CMAPI_CALL_CAP = 30
CMAPI_RESPONSE_CAP = 1_000_000
CMAPI_TOTAL_CAP = 30_000_000
CMAPI_REMAINING_BUFFER = 30


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def lang(value: object) -> str:
    token = norm(value)
    aliases = {
        "english": "en", "anglais": "en", "en": "en",
        "french": "fr", "francais": "fr", "fr": "fr",
        "german": "de", "allemand": "de", "de": "de",
        "italian": "it", "italien": "it", "it": "it",
        "spanish": "es", "espagnol": "es", "es": "es",
        "japanese": "ja", "japonais": "ja", "jp": "ja", "ja": "ja",
    }
    return aliases.get(token, token or "en")


def number_ok(expected: object, actual: object) -> bool:
    left, right = _normalize_card_number(expected), _normalize_card_number(actual)
    if not left or not right:
        return False
    if left == right:
        return True
    ln, ld = _card_number_parts(expected)
    rn, rd = _card_number_parts(actual)
    if not ln or ln != rn:
        return False
    return not (ld and rd and ld != rd)


def candidate_identity(
    canonical: CardIdentity,
    *,
    name: object,
    set_name: object,
    number: object,
) -> str:
    if not name:
        return "INSUFFICIENT"
    if _normalize_card_name(name) != _normalize_card_name(canonical.card_name):
        return "MISMATCH"
    if canonical.set:
        if not set_name:
            return "INSUFFICIENT"
        if _set_similarity(canonical.set, set_name, None) < 0.86:
            return "MISMATCH"
    if canonical.card_number:
        if not number:
            return "INSUFFICIENT"
        if not number_ok(canonical.card_number, number):
            return "MISMATCH"
    return "EXACT"


def expected_printing(identity: CardIdentity) -> Optional[str]:
    finish, edition = norm(identity.finish or identity.variant), norm(identity.edition)
    if "reverse" in finish:
        return "reverse"
    if "holo" in finish or "foil" in finish:
        if "1st" in edition or "first" in edition:
            return "1st edition holo"
        if "unlimited" in edition:
            return "unlimited holo"
        return "holo"
    if "1st" in edition or "first" in edition:
        return "1st edition"
    if "unlimited" in edition:
        return "unlimited"
    return None


def variant_status(identity: CardIdentity, values: Iterable[object]) -> str:
    expected = expected_printing(identity)
    if expected is None:
        return "NOT_REQUIRED"
    variants = [norm(value) for value in values if value not in (None, "")]
    if not variants:
        return "NOT_EXPOSED"
    if expected == "reverse" and any("reverse" in value for value in variants):
        return "EXACT"
    if expected == "holo" and any("holo" in value and "reverse" not in value for value in variants):
        return "EXACT"
    if expected == "1st edition" and any("1st edition" in value or "first edition" in value for value in variants):
        return "EXACT"
    if expected == "1st edition holo" and any(
        ("1st edition" in value or "first edition" in value) and "holo" in value
        for value in variants
    ):
        return "EXACT"
    if expected == "unlimited" and any("unlimited" in value for value in variants):
        return "EXACT"
    if expected == "unlimited holo" and any("unlimited" in value and "holo" in value for value in variants):
        return "EXACT"
    return "MISMATCH"


def language_status(identity: CardIdentity, values: Iterable[object]) -> str:
    actual = {lang(value) for value in values if value not in (None, "")}
    if not actual:
        return "NOT_EXPOSED"
    return "EXACT" if lang(identity.language) in actual else "MISMATCH"


def num(*values: object) -> Optional[float]:
    for value in values:
        try:
            if value is not None and not isinstance(value, bool):
                return float(value)
        except (TypeError, ValueError):
            pass
    return None


def maps(value: object) -> list[Mapping[str, object]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [row for row in value if isinstance(row, Mapping)]
    return []


def freshest(*values: object) -> Optional[str]:
    rows = [str(value) for value in values if value not in (None, "")]
    return max(rows) if rows else None


@dataclass(frozen=True)
class PanelCard:
    identity: CardIdentity
    tcgdex_id: str
    tcgdex_language: str
    marketplace: str

    @property
    def label(self) -> str:
        return self.identity.display_name()


@dataclass
class Observation:
    provider: str
    card: str
    identity: str = "UNAVAILABLE"
    variant: str = "NOT_EXPOSED"
    language: str = "NOT_EXPOSED"
    raw_usd: Optional[float] = None
    raw_eur: Optional[float] = None
    psa10_usd: Optional[float] = None
    psa10_eur: Optional[float] = None
    graded_available: bool = False
    history: str = "NONE"
    freshness: Optional[str] = None
    liquidity: Optional[int] = None
    error: Optional[str] = None


@dataclass
class Runtime:
    calls: int = 0
    bytes_read: int = 0
    rate_limited: int = 0
    quota_remaining: Optional[int] = None
    blocked: bool = False
    errors: list[str] = field(default_factory=list)


class SafeClient:
    def __init__(
        self,
        provider: str,
        *,
        call_cap: int,
        interval: float = 0.0,
        response_cap: int = 2_000_000,
        total_cap: int = 100_000_000,
    ) -> None:
        self.provider = provider
        self.call_cap = call_cap
        self.interval = interval
        self.response_cap = response_cap
        self.total_cap = total_cap
        self.session = requests.Session()
        self.runtime = Runtime()
        self.last_call: Optional[float] = None

    def request(self, method: str, url: str, **kwargs: Any) -> tuple[Optional[requests.Response], Optional[object]]:
        if self.runtime.calls >= self.call_cap or self.runtime.bytes_read >= self.total_cap:
            self.runtime.blocked = True
            return None, None
        if self.last_call is not None and self.interval:
            wait = self.interval - (time.monotonic() - self.last_call)
            if wait > 0:
                time.sleep(wait)
        self.last_call = time.monotonic()
        self.runtime.calls += 1
        kwargs.setdefault("timeout", 15)
        kwargs["stream"] = True
        try:
            response = self.session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            self.runtime.errors.append(type(exc).__name__)
            return None, None
        if response.status_code == 429:
            self.runtime.rate_limited += 1
        declared = response.headers.get("Content-Length")
        try:
            if declared and int(declared) > self.response_cap:
                response.close()
                self.runtime.errors.append("RESPONSE_TOO_LARGE")
                return response, None
        except ValueError:
            pass
        body = bytearray()
        try:
            for chunk in response.iter_content(65536):
                if chunk:
                    body.extend(chunk)
                if len(body) > self.response_cap:
                    response.close()
                    self.runtime.errors.append("RESPONSE_TOO_LARGE")
                    return response, None
        except requests.RequestException as exc:
            self.runtime.errors.append(type(exc).__name__)
            return response, None
        self.runtime.bytes_read += len(body)
        response._content = bytes(body)
        response._content_consumed = True
        try:
            return response, response.json()
        except ValueError:
            return response, None


def build_panel(client_id: str, client_secret: str, size: int) -> tuple[list[PanelCard], dict[str, object]]:
    resolver = MultilingualPokemonCardResolver()
    diagnostic = EbayLiveDiagnostic(
        client_id, client_secret, result_limit=20,
        marketplaces=DEFAULT_LIVE_MARKETPLACES,
    )
    token, oauth = diagnostic._application_token()
    info: dict[str, object] = {"oauth": oauth.http_status, "detail_calls": 0}
    if not token:
        return [], info
    buckets: dict[str, list[object]] = {}
    for market in DEFAULT_LIVE_MARKETPLACES:
        aggregate, records = diagnostic._discover_marketplace(market, token)
        buckets[market] = list(records)
        info[market] = {
            "http": aggregate.http_status,
            "results": aggregate.results_received,
            "taxonomy_ok": aggregate.taxonomy_ok,
        }
    positions = {market: 0 for market in DEFAULT_LIVE_MARKETPLACES}
    panel: list[PanelCard] = []
    seen: set[tuple[str, str, str, str]] = set()
    while len(panel) < size and int(info["detail_calls"]) < DETAIL_BUDGET:
        progressed = False
        for market in DEFAULT_LIVE_MARKETPLACES:
            bucket, pos = buckets[market], positions[market]
            if pos >= len(bucket):
                continue
            progressed = True
            record = bucket[pos]
            positions[market] += 1
            item_id = getattr(record, "item_id", None)
            if not item_id:
                continue
            ok, detail = diagnostic._get_item(item_id, market, token)
            info["detail_calls"] = int(info["detail_calls"]) + 1
            if not ok:
                continue
            enriched = {**getattr(record, "summary", {}), **detail}
            try:
                listing = parse_ebay_item(enriched)
            except Exception:
                continue
            if listing.condition_id != RAW_CONDITION_ID:
                continue
            identity = resolve_card_identity(enriched).identity
            if not (identity.card_name and identity.set and identity.card_number):
                continue
            result = resolver._resolve_tcgdex(identity)
            if result is None or not result.matched or result.ambiguous:
                continue
            provenance = getattr(result, "set_provenance", None)
            card_id = str(getattr(provenance, "catalog_card_id", "") or "")
            if not card_id:
                continue
            key = (
                _normalize_card_name(result.identity.card_name),
                _normalize(result.identity.set),
                _normalize_card_number(result.identity.card_number),
                lang(result.identity.language),
            )
            if key in seen:
                continue
            seen.add(key)
            panel.append(PanelCard(
                result.identity, card_id,
                str(getattr(provenance, "language", "") or lang(result.identity.language)),
                market,
            ))
            if len(panel) >= size:
                break
        if not progressed:
            break
    info["panel_size"] = len(panel)
    return panel, info


def tcgdex(panel: Sequence[PanelCard]) -> tuple[list[Observation], Runtime]:
    client = SafeClient("tcgdex", call_cap=25)
    out = []
    for card in panel:
        response, payload = client.request(
            "GET",
            f"https://api.tcgdex.net/v2/{quote(lang(card.tcgdex_language), safe='')}/cards/{quote(card.tcgdex_id, safe='')}",
        )
        obs = Observation("tcgdex", card.label)
        if not response or response.status_code != 200 or not isinstance(payload, Mapping):
            obs.error = f"HTTP_{getattr(response, 'status_code', 'REQUEST')}"
            out.append(obs); continue
        set_row = payload.get("set") if isinstance(payload.get("set"), Mapping) else {}
        obs.identity = candidate_identity(
            card.identity, name=payload.get("name"),
            set_name=set_row.get("name"), number=payload.get("localId"),
        )
        obs.language = "EXACT"
        variants = payload.get("variants") if isinstance(payload.get("variants"), Mapping) else {}
        obs.variant = variant_status(card.identity, [key for key, value in variants.items() if value is True])
        pricing = payload.get("pricing") if isinstance(payload.get("pricing"), Mapping) else {}
        tp = pricing.get("tcgplayer") if isinstance(pricing.get("tcgplayer"), Mapping) else {}
        cm = pricing.get("cardmarket") if isinstance(pricing.get("cardmarket"), Mapping) else {}
        expected = expected_printing(card.identity)
        candidates = []
        if expected:
            candidates += [expected.replace(" ", "-"), expected.replace(" ", "-") + "foil"]
        candidates += ["holofoil", "reverse-holofoil", "normal"]
        chosen = next((tp.get(key) for key in candidates if isinstance(tp.get(key), Mapping)), {})
        obs.raw_usd = num(chosen.get("marketPrice"), chosen.get("midPrice"), chosen.get("lowPrice"))
        holo = expected is not None and "holo" in expected and "reverse" not in expected
        obs.raw_eur = num(
            cm.get("trend-holo") if holo else cm.get("trend"),
            cm.get("avg-holo") if holo else cm.get("avg"),
            cm.get("low-holo") if holo else cm.get("low"),
        )
        obs.history = "ROLLING_30D" if any(cm.get(k) is not None for k in ("avg1", "avg7", "avg30", "avg1-holo", "avg7-holo", "avg30-holo")) else "NONE"
        obs.freshness = freshest(tp.get("updated"), cm.get("updated"))
        out.append(obs)
    return out, client.runtime


class RecordingSession(requests.Session):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.last: Optional[requests.Response] = None

    def get(self, *args: Any, **kwargs: Any) -> requests.Response:
        self.calls += 1
        self.last = super().get(*args, **kwargs)
        return self.last


def justtcg(panel: Sequence[PanelCard], key: str) -> tuple[list[Observation], Runtime]:
    session = RecordingSession()
    resolver = JustTCGIdentityResolver(api_key=key, session=session)
    runtime, out = Runtime(), []
    for card in panel:
        before = session.calls
        result = resolver.resolve_identity(card.identity)
        runtime.calls += session.calls - before
        obs = Observation("justtcg", card.label)
        obs.identity = "AMBIGUOUS" if result.ambiguous else ("EXACT" if result.matched else "UNRESOLVED")
        payload = None
        if session.last is not None:
            if session.last.status_code == 429:
                runtime.rate_limited += 1
            try:
                payload = session.last.json()
            except ValueError:
                pass
        rows = maps(payload.get("data")) if isinstance(payload, Mapping) else []
        row = next((candidate for candidate in rows if result.card_id and str(candidate.get("id")) == result.card_id), rows[0] if rows and result.matched else None)
        if isinstance(row, Mapping):
            variants = maps(row.get("variants"))
            obs.variant = variant_status(card.identity, [v.get("printing") for v in variants])
            obs.language = language_status(card.identity, [v.get("language") for v in variants])
            prices = [num(v.get("price")) for v in variants]
            prices = [value for value in prices if value is not None]
            obs.raw_usd = statistics.median(prices) if prices else None
            obs.history = "RETURNED" if any(v.get("priceHistory") for v in variants) else "NONE"
            obs.freshness = freshest(*[v.get("lastUpdated") for v in variants])
        meta = payload.get("_metadata") if isinstance(payload, Mapping) and isinstance(payload.get("_metadata"), Mapping) else {}
        try:
            runtime.quota_remaining = int(meta["apiRequestsRemaining"]) if meta.get("apiRequestsRemaining") is not None else runtime.quota_remaining
        except (TypeError, ValueError):
            pass
        out.append(obs)
    runtime.rate_limited += resolver.counters.rate_limited
    runtime.errors += ["REQUEST_FAILURE"] * resolver.counters.request_failures
    return out, runtime


def simple_search(
    provider: str,
    panel: Sequence[PanelCard],
    client: SafeClient,
    url: str,
    key_headers: Mapping[str, str],
    params_builder: Any,
    rows_builder: Any,
    candidate_builder: Any,
    price_builder: Any,
) -> tuple[list[Observation], Runtime]:
    out = []
    for card in panel:
        response, payload = client.request("GET", url, headers=dict(key_headers), params=params_builder(card))
        obs = Observation(provider, card.label)
        if not response or response.status_code != 200:
            obs.error = f"HTTP_{getattr(response, 'status_code', 'REQUEST')}"
            out.append(obs); continue
        rows = rows_builder(payload)
        exact = [row for row in rows if candidate_builder(card, row) == "EXACT"]
        if len(exact) == 1:
            obs.identity = "EXACT"
            price_builder(card, exact[0], obs)
        elif len(exact) > 1:
            obs.identity = "AMBIGUOUS"
        elif rows:
            obs.identity = "MISMATCH_OR_INSUFFICIENT"
        else:
            obs.identity = "UNRESOLVED"
        out.append(obs)
    return out, client.runtime


def pokewallet(panel: Sequence[PanelCard], key: str) -> tuple[list[Observation], Runtime]:
    client = SafeClient("pokewallet", call_cap=25)
    def params(card: PanelCard) -> dict[str, object]:
        return {"q": " ".join(filter(None, (card.identity.card_name, card.identity.set, card.identity.card_number))), "limit": 20}
    def rows(payload: object) -> list[Mapping[str, object]]:
        return maps(payload.get("results")) if isinstance(payload, Mapping) else []
    def identity(card: PanelCard, row: Mapping[str, object]) -> str:
        info = row.get("card_info") if isinstance(row.get("card_info"), Mapping) else {}
        return candidate_identity(card.identity, name=info.get("name"), set_name=info.get("set_name"), number=info.get("card_number"))
    def prices(card: PanelCard, row: Mapping[str, object], obs: Observation) -> None:
        info = row.get("card_info") if isinstance(row.get("card_info"), Mapping) else {}
        obs.language = language_status(card.identity, [info.get("language")])
        tp = row.get("tcgplayer") if isinstance(row.get("tcgplayer"), Mapping) else {}
        cm = row.get("cardmarket") if isinstance(row.get("cardmarket"), Mapping) else {}
        tpr, cmr = maps(tp.get("prices")), maps(cm.get("prices"))
        obs.variant = variant_status(card.identity, [r.get("printing") or r.get("variant_type") for r in tpr + cmr])
        usd = [num(r.get("market_price"), r.get("marketPrice"), r.get("mid_price"), r.get("low_price")) for r in tpr]
        eur = [num(r.get("trend"), r.get("avg"), r.get("low")) for r in cmr]
        obs.raw_usd = statistics.median([v for v in usd if v is not None]) if any(v is not None for v in usd) else None
        obs.raw_eur = statistics.median([v for v in eur if v is not None]) if any(v is not None for v in eur) else None
        obs.freshness = freshest(*[r.get("updated_at") for r in tpr + cmr])
        obs.history = "ENDPOINT_NOT_AVAILABLE"
    return simple_search("pokewallet", panel, client, "https://api.pokewallet.io/search", {"X-API-Key": key}, params, rows, identity, prices)


def tcgapi_dev(panel: Sequence[PanelCard], key: str) -> tuple[list[Observation], Runtime]:
    client = SafeClient("tcgapi_dev", call_cap=25)
    def identity(card: PanelCard, row: Mapping[str, object]) -> str:
        return candidate_identity(card.identity, name=row.get("name"), set_name=row.get("set_name"), number=row.get("number"))
    def prices(card: PanelCard, row: Mapping[str, object], obs: Observation) -> None:
        obs.variant = variant_status(card.identity, [row.get("printing")])
        obs.raw_usd = num(row.get("market_price"), row.get("median_price"), row.get("low_price"))
        obs.freshness = freshest(row.get("price_updated_at"))
        try:
            obs.liquidity = int(row["total_listings"]) if row.get("total_listings") is not None else None
        except (TypeError, ValueError):
            pass
        obs.history = "PLAN_GATED"
    out, runtime = simple_search(
        "tcgapi_dev", panel, client, "https://api.tcgapi.dev/v1/search",
        {"X-API-Key": key},
        lambda card: {"q": card.identity.card_name or "", "game": "pokemon", "type": "Cards", "per_page": 50},
        lambda payload: maps(payload.get("data")) if isinstance(payload, Mapping) else [],
        identity, prices,
    )
    return out, runtime


def tcg_cardmarket(panel: Sequence[PanelCard], key: str) -> tuple[list[Observation], Runtime]:
    client, out = SafeClient("tcg_cardmarket", call_cap=25), []
    for card in panel:
        response, payload = client.request(
            "GET", "https://tcg-api-production-5148.up.railway.app/cards/search",
            headers={"X-API-Key": key},
            params={"game": "pokemon", "name": card.identity.card_name or "", "page": 1, "limit": 100},
        )
        obs = Observation("tcg_cardmarket", card.label)
        if not response or response.status_code != 200 or not isinstance(payload, Mapping):
            obs.error = f"HTTP_{getattr(response, 'status_code', 'REQUEST')}"; out.append(obs); continue
        rows = maps(payload.get("data"))
        name_matches = [row for row in rows if _normalize_card_name(row.get("name")) == _normalize_card_name(card.identity.card_name)]
        if len(name_matches) == 1:
            obs.identity = "INSUFFICIENT"
            price = name_matches[0].get("price") if isinstance(name_matches[0].get("price"), Mapping) else {}
            obs.raw_eur = num(price.get("trend"), price.get("avg7"), price.get("sell"), price.get("low"))
            obs.history = "ROLLING_30D" if any(price.get(k) is not None for k in ("avg1", "avg7", "avg30")) else "NONE"
            obs.freshness = freshest(price.get("updatedAt"))
            obs.variant = "PARTIAL_HOLO_ONLY" if any(price.get(k) is not None for k in ("foilSell", "foilLow", "foilTrend")) else "NOT_EXPOSED"
        elif len(name_matches) > 1:
            obs.identity = "AMBIGUOUS"
        else:
            obs.identity = "UNRESOLVED"
        out.append(obs)
    return out, client.runtime


def pokemonpricetracker(panel: Sequence[PanelCard], key: str) -> tuple[list[Observation], Runtime]:
    client, out, depth = SafeClient("pokemonpricetracker", call_cap=45), [], []
    for index, card in enumerate(panel):
        query = " ".join(filter(None, (card.identity.card_name, card.identity.set, card.identity.card_number)))
        response, payload = client.request(
            "GET", "https://www.pokemonpricetracker.com/api/v2/cards",
            headers={"Authorization": f"Bearer {key}"},
            params={"search": query, "limit": 10},
        )
        obs = Observation("pokemonpricetracker", card.label)
        if not response or response.status_code != 200 or not isinstance(payload, Mapping):
            obs.error = f"HTTP_{getattr(response, 'status_code', 'REQUEST')}"; out.append(obs); continue
        rows = maps(payload.get("data"))
        exact = [
            row for row in rows
            if candidate_identity(
                card.identity, name=row.get("name"),
                set_name=row.get("setName") or row.get("set_name"),
                number=row.get("number") or row.get("cardNumber"),
            ) == "EXACT"
        ]
        if len(exact) == 1:
            row = exact[0]; obs.identity = "EXACT"
            p = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
            obs.raw_usd = num(p.get("market"), p.get("mid"), p.get("low"))
            obs.freshness = freshest(p.get("lastUpdated"), row.get("updatedAt"))
            obs.variant = variant_status(card.identity, [row.get("printing"), row.get("variant")])
            obs.language = language_status(card.identity, [row.get("language")])
            tcg_id = row.get("tcgPlayerId") or row.get("tcgplayerId")
            if tcg_id and len(depth) < DEPTH_SENTINELS:
                depth.append((index, str(tcg_id)))
        elif len(exact) > 1:
            obs.identity = "AMBIGUOUS"
        elif rows:
            obs.identity = "MISMATCH_OR_INSUFFICIENT"
        else:
            obs.identity = "UNRESOLVED"
        for header in ("X-RateLimit-Daily-Remaining", "x-ratelimit-daily-remaining"):
            if header in response.headers:
                try: client.runtime.quota_remaining = int(response.headers[header])
                except ValueError: pass
        out.append(obs)
    for index, tcg_id in depth:
        if client.runtime.quota_remaining is not None and client.runtime.quota_remaining < 15:
            client.runtime.blocked = True; break
        response, payload = client.request(
            "GET", "https://www.pokemonpricetracker.com/api/v2/cards",
            headers={"Authorization": f"Bearer {key}"},
            params={"tcgPlayerId": tcg_id, "includeHistory": "true", "includeEbay": "true", "days": 3},
        )
        if response and response.status_code == 200 and isinstance(payload, Mapping):
            row = payload.get("data")
            if isinstance(row, list): row = row[0] if row else None
            if isinstance(row, Mapping):
                out[index].history = "3D_RETURNED" if row.get("priceHistory") else "NONE"
                ebay = row.get("ebay") or row.get("ebayData") or row.get("gradedPrices")
                out[index].graded_available = bool(ebay)
    return out, client.runtime


def poketrace(panel: Sequence[PanelCard], key: str) -> tuple[list[Observation], Runtime]:
    client, out, depth = SafeClient("poketrace", call_cap=55, interval=0.40), [], []
    for index, card in enumerate(panel):
        exact_rows: list[tuple[str, Mapping[str, object]]] = []
        for market in ("US", "EU"):
            response, payload = client.request(
                "GET", "https://api.poketrace.com/v1/cards",
                headers={"X-API-Key": key},
                params={"search": card.identity.card_name or "", "market": market, "limit": 20, "product_type": "single"},
            )
            if not response or response.status_code != 200 or not isinstance(payload, Mapping):
                continue
            for row in maps(payload.get("data")):
                set_row = row.get("set") if isinstance(row.get("set"), Mapping) else {}
                if candidate_identity(
                    card.identity, name=row.get("name"), set_name=set_row.get("name"),
                    number=row.get("cardNumber") or row.get("number"),
                ) == "EXACT":
                    exact_rows.append((market, row))
        obs = Observation("poketrace", card.label)
        if not exact_rows:
            obs.identity = "UNRESOLVED"; out.append(obs); continue
        obs.identity = "EXACT"
        obs.variant = variant_status(card.identity, [row.get("variant") for _, row in exact_rows])
        obs.language = language_status(card.identity, [row.get("language") for _, row in exact_rows])
        liquidity = 0
        for market, row in exact_rows:
            prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
            if market == "US":
                tp = prices.get("tcgplayer") if isinstance(prices.get("tcgplayer"), Mapping) else {}
                eb = prices.get("ebay") if isinstance(prices.get("ebay"), Mapping) else {}
                raw = tp.get("NEAR_MINT") if isinstance(tp.get("NEAR_MINT"), Mapping) else {}
                if not raw: raw = eb.get("NEAR_MINT") if isinstance(eb.get("NEAR_MINT"), Mapping) else {}
                obs.raw_usd = num(raw.get("avg"), raw.get("median7d"), raw.get("low")) or obs.raw_usd
                grade_keys = [k for k in eb if any(tag in str(k).upper() for tag in ("PSA_", "BGS_", "CGC_", "SGC_"))]
                if grade_keys:
                    obs.graded_available = True
                    psa10 = eb.get("PSA_10") if isinstance(eb.get("PSA_10"), Mapping) else {}
                    obs.psa10_usd = num(psa10.get("median7d"), psa10.get("avg"), psa10.get("low"))
                    if len(depth) < DEPTH_SENTINELS and row.get("id"):
                        depth.append((index, str(row["id"]), "PSA_10" if "PSA_10" in eb else grade_keys[0]))
                for source in (tp, eb):
                    nm = source.get("NEAR_MINT") if isinstance(source.get("NEAR_MINT"), Mapping) else {}
                    try: liquidity += int(nm.get("saleCount") or 0)
                    except (TypeError, ValueError): pass
            else:
                cm = prices.get("cardmarket") if isinstance(prices.get("cardmarket"), Mapping) else {}
                agg = cm.get("AGGREGATED") if isinstance(cm.get("AGGREGATED"), Mapping) else {}
                obs.raw_eur = num(agg.get("avg"), agg.get("avg7d"), agg.get("avg30d")) or obs.raw_eur
                unsold = prices.get("cardmarket_unsold") if isinstance(prices.get("cardmarket_unsold"), Mapping) else {}
                nm = unsold.get("NEAR_MINT") if isinstance(unsold.get("NEAR_MINT"), Mapping) else {}
                try: liquidity += int(nm.get("saleCount") or 0)
                except (TypeError, ValueError): pass
            obs.freshness = freshest(obs.freshness, row.get("lastUpdated"))
        obs.liquidity = liquidity or None
        obs.history = "AVAILABLE_PRO"
        out.append(obs)
    for index, card_id, tier in depth:
        response, payload = client.request(
            "GET", f"https://api.poketrace.com/v1/cards/{quote(card_id, safe='')}/prices/{quote(tier, safe='')}/history",
            headers={"X-API-Key": key}, params={"period": "30d", "limit": 30},
        )
        if response and response.status_code == 200 and isinstance(payload, Mapping) and payload.get("data"):
            out[index].history = "30D_RETURNED"
    return out, client.runtime


def cmapi(panel: Sequence[PanelCard], key: str) -> tuple[list[Observation], Runtime]:
    client = SafeClient(
        "cmapi", call_cap=CMAPI_CALL_CAP,
        response_cap=CMAPI_RESPONSE_CAP, total_cap=CMAPI_TOTAL_CAP,
    )
    out = []
    host = os.getenv("CMAPI_RAPIDAPI_HOST", "cardmarket-api-tcg.p.rapidapi.com").strip()
    for card in panel:
        response, payload = client.request(
            "GET", f"https://{host}/pokemon/cards",
            headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": host},
            params={"search": "+".join(filter(None, (card.identity.card_name, card.identity.card_number))), "sort": "price_highest"},
        )
        obs = Observation("cmapi", card.label)
        if response:
            remaining = response.headers.get("x-ratelimit-requests-remaining")
            try:
                if remaining is not None: client.runtime.quota_remaining = int(float(remaining))
            except ValueError: pass
        if not response or response.status_code != 200:
            obs.error = f"HTTP_{getattr(response, 'status_code', 'REQUEST')}"; out.append(obs); continue
        rows = maps(payload.get("data") or payload.get("cards") or payload.get("results")) if isinstance(payload, Mapping) else maps(payload)
        if isinstance(payload, Mapping) and payload.get("name") and not rows:
            rows = [payload]
        exact = []
        for row in rows:
            episode = row.get("episode") if isinstance(row.get("episode"), Mapping) else {}
            if candidate_identity(
                card.identity, name=row.get("name"), set_name=episode.get("name") or row.get("set_name"),
                number=row.get("card_number") or row.get("number"),
            ) == "EXACT":
                exact.append(row)
        if len(exact) == 1:
            row = exact[0]; obs.identity = "EXACT"
            prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
            cm = prices.get("cardmarket") if isinstance(prices.get("cardmarket"), Mapping) else {}
            tp = prices.get("tcg_player") if isinstance(prices.get("tcg_player"), Mapping) else {}
            eb = prices.get("ebay") if isinstance(prices.get("ebay"), Mapping) else {}
            obs.raw_eur = num(cm.get("lowest_near_mint"), cm.get("7d_average"), cm.get("30d_average"))
            obs.raw_usd = num(tp.get("market_price"), tp.get("mid_price"))
            cmg = cm.get("graded") if isinstance(cm.get("graded"), Mapping) else {}
            ebg = eb.get("graded") if isinstance(eb.get("graded"), Mapping) else {}
            obs.graded_available = bool(cmg or ebg)
            cmpsa = cmg.get("psa") if isinstance(cmg.get("psa"), Mapping) else {}
            ebpsa = ebg.get("psa") if isinstance(ebg.get("psa"), Mapping) else {}
            eb10 = ebpsa.get("10") if isinstance(ebpsa.get("10"), Mapping) else {}
            obs.psa10_eur = num(cmpsa.get("psa10"), cmpsa.get("10"))
            obs.psa10_usd = num(eb10.get("median_price"))
            obs.history = "ROLLING_30D" if cm.get("30d_average") is not None else "NONE"
            samples = []
            for grade in ebpsa.values():
                if isinstance(grade, Mapping):
                    try: samples.append(int(grade.get("sample_size") or 0))
                    except (TypeError, ValueError): pass
            obs.liquidity = sum(samples) or None
        elif len(exact) > 1: obs.identity = "AMBIGUOUS"
        elif rows: obs.identity = "MISMATCH_OR_INSUFFICIENT"
        else: obs.identity = "UNRESOLVED"
        out.append(obs)
        if client.runtime.quota_remaining is not None and client.runtime.quota_remaining <= CMAPI_REMAINING_BUFFER:
            client.runtime.blocked = True; break
    return out, client.runtime


def cardtrader(panel: Sequence[PanelCard], token: str) -> tuple[list[Observation], Runtime]:
    client = SafeClient("cardtrader", call_cap=45, interval=1.05)
    headers = {"Authorization": f"Bearer {token}"}
    out = [Observation("cardtrader", card.label) for card in panel]
    gr, gp = client.request("GET", "https://api.cardtrader.com/api/v2/games", headers=headers)
    games = maps(gp) if gr and gr.status_code == 200 else []
    pokemon_ids = {int(row["id"]) for row in games if row.get("id") is not None and "pokemon" in norm(row.get("name"))}
    er, ep = client.request("GET", "https://api.cardtrader.com/api/v2/expansions", headers=headers)
    if not er or er.status_code != 200:
        for obs in out: obs.error = f"HTTP_{getattr(er, 'status_code', 'REQUEST')}"
        return out, client.runtime
    expansions = [row for row in maps(ep) if not pokemon_ids or int(row.get("game_id") or -1) in pokemon_ids]
    cache: dict[int, list[Mapping[str, object]]] = {}
    for index, card in enumerate(panel):
        exps = [row for row in expansions if _set_similarity(card.identity.set, row.get("name"), row.get("code")) >= 0.95]
        if len(exps) != 1:
            out[index].identity = "AMBIGUOUS" if len(exps) > 1 else "UNRESOLVED"; continue
        eid = int(exps[0]["id"])
        if eid not in cache:
            br, bp = client.request("GET", "https://api.cardtrader.com/api/v2/blueprints/export", headers=headers, params={"expansion_id": eid})
            cache[eid] = maps(bp) if br and br.status_code == 200 else []
        matches = [row for row in cache[eid] if _normalize_card_name(row.get("name")) == _normalize_card_name(card.identity.card_name)]
        if len(matches) != 1:
            out[index].identity = "AMBIGUOUS" if len(matches) > 1 else "UNRESOLVED"; continue
        blueprint = matches[0]
        out[index].identity = "INSUFFICIENT"  # documented blueprint core does not guarantee collector number
        props = maps(blueprint.get("editable_properties"))
        names = [norm(row.get("name")) for row in props]
        out[index].variant = "EXPOSED" if any("foil" in name or "edition" in name for name in names) else "NOT_EXPOSED"
        out[index].language = "EXPOSED" if any("language" in name for name in names) else "NOT_EXPOSED"
        mr, mp = client.request("GET", "https://api.cardtrader.com/api/v2/marketplace/products", headers=headers, params={"blueprint_id": blueprint.get("id")})
        products = maps(mp) if mr and mr.status_code == 200 else []
        eur, usd, langs = [], [], []
        for product in products:
            if product.get("graded") is True:
                out[index].graded_available = True; continue
            price = product.get("price") if isinstance(product.get("price"), Mapping) else product.get("seller_price")
            if isinstance(price, Mapping):
                cents = num(price.get("cents"))
                currency = str(price.get("currency") or "").upper()
                if cents is not None:
                    (eur if currency == "EUR" else usd if currency == "USD" else []).append(cents / 100)
            p = product.get("properties") if isinstance(product.get("properties"), Mapping) else {}
            langs += [value for key, value in p.items() if "language" in norm(key)]
        out[index].raw_eur = min(eur) if eur else None
        out[index].raw_usd = min(usd) if usd else None
        out[index].liquidity = len(products) or None
        if langs: out[index].language = language_status(card.identity, langs)
    return out, client.runtime


def summary(provider: str, rows: Sequence[Observation], runtime: Runtime) -> dict[str, object]:
    return {
        "provider": provider, "upstream": UPSTREAM[provider], "plan": PLAN[provider],
        "cards": len(rows),
        "identity_exact": sum(row.identity == "EXACT" for row in rows),
        "identity_ambiguous": sum(row.identity == "AMBIGUOUS" for row in rows),
        "identity_insufficient": sum(row.identity == "INSUFFICIENT" for row in rows),
        "variant_exact": sum(row.variant == "EXACT" for row in rows),
        "language_exact": sum(row.language == "EXACT" for row in rows),
        "raw_usd": sum(row.raw_usd is not None for row in rows),
        "raw_eur": sum(row.raw_eur is not None for row in rows),
        "psa10_usd": sum(row.psa10_usd is not None for row in rows),
        "psa10_eur": sum(row.psa10_eur is not None for row in rows),
        "graded": sum(row.graded_available for row in rows),
        "history": sum(row.history not in {"NONE", "PLAN_GATED", "ENDPOINT_NOT_AVAILABLE"} for row in rows),
        "freshness": sum(row.freshness is not None for row in rows),
        "liquidity": sum(row.liquidity is not None for row in rows),
        "calls": runtime.calls, "bytes_read": runtime.bytes_read,
        "rate_limited": runtime.rate_limited, "quota_remaining": runtime.quota_remaining,
        "blocked": runtime.blocked, "errors": sorted(set(runtime.errors)),
    }


def agreement(rows: Mapping[str, Sequence[Observation]], panel: Sequence[PanelCard]) -> dict[str, object]:
    result = {}
    for currency, attr in (("USD", "raw_usd"), ("EUR", "raw_eur")):
        errors = {provider: [] for provider in PROVIDERS}
        comparable = 0
        for index in range(len(panel)):
            values = []
            for provider in PROVIDERS:
                provider_rows = rows.get(provider, ())
                if index < len(provider_rows):
                    value = getattr(provider_rows[index], attr, None)
                    if isinstance(value, (int, float)) and value > 0:
                        values.append((provider, float(value)))
            if len(values) < 2: continue
            comparable += 1
            median = statistics.median(value for _, value in values)
            for provider, value in values:
                errors[provider].append(abs(value - median) / median * 100)
        result[currency] = {
            "comparable_cards": comparable,
            "median_absolute_pct_deviation": {
                provider: round(statistics.median(values), 2) if values else None
                for provider, values in errors.items()
            },
        }
    return result


def fingerprint(panel: Sequence[PanelCard]) -> str:
    rows = [
        "|".join((
            _normalize_card_name(card.identity.card_name), _normalize(card.identity.set),
            _normalize_card_number(card.identity.card_number), lang(card.identity.language),
            card.tcgdex_id,
        ))
        for card in panel
    ]
    return hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()[:16] if rows else "EMPTY"


def run() -> dict[str, object]:
    secrets = {
        name: os.getenv(name, "").strip()
        for name in (
            "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "POKETRACE_API_KEY",
            "POKEMONPRICETRACKER_API_KEY", "JUSTTCG_API_KEY", "POKEWALLET_API_KEY",
            "TCGAPI_DEV_API_KEY", "TCG_CARDMARKET_API_KEY", "CMAPI_RAPIDAPI_KEY",
            "CARDTRADER_API_TOKEN",
        )
    }
    missing = [name for name, value in secrets.items() if not value and name != "CMAPI_RAPIDAPI_KEY"]
    if missing: raise RuntimeError("Missing secrets: " + ", ".join(missing))
    size = int(os.getenv("SOURCE_SCOUT_PANEL_SIZE", str(PANEL_SIZE)))
    if not 5 <= size <= PANEL_SIZE: raise ValueError("SOURCE_SCOUT_PANEL_SIZE must be 5..20")
    panel, panel_diag = build_panel(secrets["EBAY_CLIENT_ID"], secrets["EBAY_CLIENT_SECRET"], size)
    if len(panel) < 5: raise RuntimeError(f"Canonical panel too small: {len(panel)}")
    adapters = (
        ("poketrace", lambda: poketrace(panel, secrets["POKETRACE_API_KEY"])),
        ("pokemonpricetracker", lambda: pokemonpricetracker(panel, secrets["POKEMONPRICETRACKER_API_KEY"])),
        ("justtcg", lambda: justtcg(panel, secrets["JUSTTCG_API_KEY"])),
        ("tcgdex", lambda: tcgdex(panel)),
        ("pokewallet", lambda: pokewallet(panel, secrets["POKEWALLET_API_KEY"])),
        ("tcgapi_dev", lambda: tcgapi_dev(panel, secrets["TCGAPI_DEV_API_KEY"])),
        ("tcg_cardmarket", lambda: tcg_cardmarket(panel, secrets["TCG_CARDMARKET_API_KEY"])),
        ("cmapi", lambda: cmapi(panel, secrets["CMAPI_RAPIDAPI_KEY"]) if (
            os.getenv("SOURCE_SCOUT_ENABLE_CMAPI", "false").lower() == "true"
            and secrets["CMAPI_RAPIDAPI_KEY"]
        ) else (
            [Observation("cmapi", card.label, error="SKIPPED_SAFETY_ENABLE_REQUIRED") for card in panel],
            Runtime(blocked=True),
        )),
        ("cardtrader", lambda: cardtrader(panel, secrets["CARDTRADER_API_TOKEN"])),
    )
    rows: dict[str, list[Observation]] = {}
    runtimes: dict[str, Runtime] = {}
    for provider, adapter in adapters:
        try:
            provider_rows, runtime = adapter()
        except Exception as exc:
            provider_rows = [Observation(provider, card.label, error=f"ADAPTER_EXCEPTION:{type(exc).__name__}") for card in panel]
            runtime = Runtime(errors=[type(exc).__name__])
        rows[provider] = provider_rows
        runtimes[provider] = runtime
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_SOURCE_SCOUT",
        "panel_size": len(panel), "panel_fingerprint": fingerprint(panel),
        "panel_diagnostics": panel_diag,
        "safety": {
            "purchase": 0, "bid": 0, "checkout": 0, "paid_grading": 0,
            "pokewallet_trial_activated": False,
            "cmapi_enabled": os.getenv("SOURCE_SCOUT_ENABLE_CMAPI", "false").lower() == "true",
            "cmapi_call_cap": CMAPI_CALL_CAP,
            "cmapi_total_bytes_cap": CMAPI_TOTAL_CAP,
            "cmapi_remaining_buffer": CMAPI_REMAINING_BUFFER,
        },
        "panel": [{
            "card": card.label, "language": lang(card.identity.language),
            "finish": card.identity.finish, "edition": card.identity.edition,
            "source_marketplace": card.marketplace, "tcgdex_id": card.tcgdex_id,
        } for card in panel],
        "providers": {provider: summary(provider, rows[provider], runtimes[provider]) for provider in PROVIDERS},
        "price_agreement": agreement(rows, panel),
        "observations": {provider: [asdict(row) for row in rows[provider]] for provider in PROVIDERS},
    }


def markdown(report: Mapping[str, object]) -> str:
    lines = [
        "# Source Scout benchmark", "",
        f"- Panel: {report.get('panel_size')} canonical TCGdex cards",
        f"- Fingerprint: `{report.get('panel_fingerprint')}`",
        "- Read-only: purchase/bid/checkout/paid grading = 0", "",
        "## Provider summary", "",
        "| Provider | Exact ID | Variant | Lang | RAW USD | RAW EUR | PSA10 USD | Graded | History | Fresh | Liquid | Calls |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    providers = report.get("providers")
    if isinstance(providers, Mapping):
        for provider in PROVIDERS:
            row = providers.get(provider)
            if isinstance(row, Mapping):
                lines.append(
                    f"| {provider} | {row.get('identity_exact')}/{row.get('cards')} | "
                    f"{row.get('variant_exact')} | {row.get('language_exact')} | {row.get('raw_usd')} | "
                    f"{row.get('raw_eur')} | {row.get('psa10_usd')} | {row.get('graded')} | "
                    f"{row.get('history')} | {row.get('freshness')} | {row.get('liquidity')} | {row.get('calls')} |"
                )
    lines += ["", "## Safety", ""]
    safety = report.get("safety")
    if isinstance(safety, Mapping):
        lines += [f"- `{key}`: {value}" for key, value in safety.items()]
    lines += ["", "## Upstream / plan", ""]
    if isinstance(providers, Mapping):
        for provider in PROVIDERS:
            row = providers.get(provider)
            if isinstance(row, Mapping):
                lines.append(f"- **{provider}** — {row.get('upstream')} — {row.get('plan')}")
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        report = run()
    except Exception as exc:
        print(f"SOURCE_SCOUT_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    with open(os.getenv("SOURCE_SCOUT_JSON", "source_scout_report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    rendered = markdown(report)
    with open(os.getenv("SOURCE_SCOUT_MARKDOWN", "source_scout_report.md"), "w", encoding="utf-8") as handle:
        handle.write(rendered)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
