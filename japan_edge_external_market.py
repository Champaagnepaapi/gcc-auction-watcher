"""External-first Japan marketplace hunter.

GCC is used only as a source of exact Japanese PSA 10 identities to rotate through.
Economic fair value comes from external graded SOLD evidence. Marketplace pages are
ASK inventory only; explicit sold/fulfilled pages are rejected. No purchase, bid,
checkout or payment action exists in this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import requests
from ecb_fx import ECBCurrencyConverter
from playwright.sync_api import sync_playwright

import japan_edge_full_market as full
import japan_edge_hunter as base
import japan_edge_hunter_v2 as v2
import japan_edge_hunter_v3 as v3
import v4_canonical_multimarket as multimarket


SNKRDUNK_PROVIDER = base.Provider(
    "snkrdunk",
    "https://snkrdunk.com/en/search/result?keyword={q}",
    re.compile(r"^https://snkrdunk\.com/(?:en/)?apparels/\d+/used/\d+$", re.I),
)

MERCARI_SOLD_MARKERS = (
    "sold out",
    "売り切れ",
    "販売済み",
    "取引が完了",
    "取引完了",
    "配送されました",
)
MERCARI_ACTIVE_MARKERS = (
    "購入手続きへ",
    "購入する",
    "buy now",
)
SNKRDUNK_SOLD_MARKERS = (
    "sold out",
    "売り切れ",
    "販売終了",
    "取引済み",
)
SNKRDUNK_ACTIVE_MARKERS = (
    "購入する",
    "buy now",
    "add to cart",
    "カートに追加",
)


@dataclass(frozen=True)
class IdentitySeed:
    identity: base.Identity
    latest_seen_at: datetime
    observations: int


@dataclass(frozen=True)
class ExternalOpportunity:
    provider: str
    url: str
    title: str
    price_jpy: int
    ask_eur: float
    ask_chf: Optional[float]
    landed_eur: float
    landed_chf: Optional[float]
    external_fair_eur: float
    discount_pct: float
    external_sold_count: int
    external_source: str
    evidence: str
    delivery_route: str
    identity: base.Identity


@dataclass
class Diagnostics:
    gcc_pages: int = 0
    gcc_rows: int = 0
    eligible_identity_observations: int = 0
    identity_seeds: int = 0
    seeds_scanned: int = 0
    external_prefilter_attempted: int = 0
    external_prefilter_strong: int = 0
    external_prefilter_unavailable: int = 0
    provider_searches: int = 0
    search_candidates: int = 0
    cheap_candidates: int = 0
    detail_pages: int = 0
    sold_pages_skipped: int = 0
    availability_unknown_skipped: int = 0
    identity_rejected: int = 0
    exact_active_candidates: int = 0
    external_confirmation_attempted: int = 0
    external_confirmation_strong: int = 0
    external_confirmation_unavailable: int = 0
    opportunities: int = 0
    provider_errors: dict[str, int] = field(default_factory=dict)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _provider_list() -> tuple[base.Provider, ...]:
    providers = list(base.PROVIDERS)
    enabled = os.getenv("JAPAN_EDGE_SNKRDUNK_ENABLED", "true").strip().lower() == "true"
    if enabled and not any(provider.code == "snkrdunk" for provider in providers):
        providers.append(SNKRDUNK_PROVIDER)
    return tuple(providers)


def _listing_scope(ask: base.Ask) -> str:
    text = "\n".join(part for part in (ask.title, ask.text) if part)
    return base.current_text(text)[:12000]


def listing_state(ask: base.Ask) -> str:
    """Return ACTIVE/SOLD/UNKNOWN without ever turning disappearance into SOLD."""
    if ask.provider not in {"mercari", "snkrdunk"}:
        return "ACTIVE_LEGACY_PROVIDER"
    scope = _listing_scope(ask)
    sold_markers = MERCARI_SOLD_MARKERS if ask.provider == "mercari" else SNKRDUNK_SOLD_MARKERS
    active_markers = MERCARI_ACTIVE_MARKERS if ask.provider == "mercari" else SNKRDUNK_ACTIVE_MARKERS
    if base.has_any(scope, sold_markers):
        return "SOLD_PAGE"
    if base.has_any(scope, active_markers):
        return "ACTIVE"
    return "UNKNOWN"


def strict_identity_and_availability(ask: base.Ask, ident: base.Identity) -> tuple[bool, str]:
    state = listing_state(ask)
    if state == "SOLD_PAGE":
        return False, "marketplace_sold_page"
    if state == "UNKNOWN":
        return False, "marketplace_availability_unproven"
    return v2.identity_check(ask, ident)


def _safe_identity_seed(sale: base.Sold) -> bool:
    ident = sale.identity
    if v2._official_surface_error_applicable(ident):
        return v2._surface_variant_from_identity(ident) != "UNPROVEN"
    return True


def identity_seeds(sales: list[base.Sold]) -> list[IdentitySeed]:
    grouped: dict[str, list[base.Sold]] = {}
    for sale in sales:
        if _safe_identity_seed(sale):
            grouped.setdefault(sale.identity.key, []).append(sale)
    seeds = []
    for values in grouped.values():
        values.sort(key=lambda item: item.sold_at, reverse=True)
        seeds.append(IdentitySeed(values[0].identity, values[0].sold_at, len(values)))
    return sorted(seeds, key=lambda seed: (seed.latest_seen_at, seed.observations), reverse=True)


def seed_slice(seeds: list[IdentitySeed], state: dict, count: int) -> tuple[list[IdentitySeed], int]:
    if not seeds:
        return [], 0
    ordered = sorted(seeds, key=lambda seed: seed.identity.key)
    cursor = int(state.get("cursor", 0)) % len(ordered)
    take = min(max(0, count), len(ordered))
    selected = [ordered[(cursor + index) % len(ordered)] for index in range(take)]
    return selected, (cursor + take) % len(ordered)


def _probe(identity: base.Identity) -> base.Opportunity:
    return base.Opportunity(
        provider="external_identity_seed",
        url="https://gradedcardcenter.com/",
        title=f"{identity.name} {identity.number} Japanese PSA 10",
        price_jpy=1,
        ask_eur=0.01,
        ask_chf=None,
        landed_eur=0.01,
        landed_chf=None,
        fair_eur=0.01,
        discount_pct=0.0,
        gcc_sold_count=0,
        gcc_recent_90=0,
        evidence="GCC_IDENTITY_SEED_ONLY",
        identity=identity,
    )


def _prefilter_reference(
    identity: base.Identity,
    budget: multimarket.RequestBudget,
    now: datetime,
) -> v3.ExternalReference:
    """Cheap first-pass external fair. GCC prices are deliberately absent."""
    return v3.fetch_external_reference(_probe(identity), budget, now)


def _confirmed_reference(
    identity: base.Identity,
    budget: multimarket.RequestBudget,
    now: datetime,
) -> v3.ExternalReference:
    """Final exact-SOLD confirmation using the existing full external provider tree."""
    return full.fetch_full_market_reference(_probe(identity), budget, now)


def _strong_external(reference: v3.ExternalReference) -> bool:
    return bool(
        reference.status == "EXACT_SOLD_CONFIRMED"
        and reference.evidence_strength == "STRONG"
        and reference.fair_eur is not None
        and reference.fair_eur > 0
        and reference.sold_count >= 2
    )


def delivery_route(provider: str) -> str:
    if provider == "mercari":
        return "CROSSBORDER_PARTNER_OR_JP_WAREHOUSE"
    if provider == "snkrdunk":
        return "SWITZERLAND_DIRECT_UNSUPPORTED_USE_JP_ROUTE_IF_ALLOWED"
    return "JP_PROXY_OR_FORWARDER"


def build_opportunity(
    ask: base.Ask,
    identity: base.Identity,
    external: v3.ExternalReference,
    jpy_per_eur: Decimal,
    chf_per_eur: Optional[Decimal],
    min_discount: float,
    proxy_jpy: int,
    buffer_pct: float,
) -> Optional[ExternalOpportunity]:
    if not _strong_external(external):
        return None
    fair = float(external.fair_eur or 0)
    landed = base.landed_eur(ask.price_jpy, jpy_per_eur, proxy_jpy, buffer_pct)
    discount = (fair - landed) / fair * 100 if fair > 0 else 0.0
    if discount + 1e-9 < min_discount:
        return None
    ask_eur = float(Decimal(ask.price_jpy) / jpy_per_eur)
    ask_chf = float(Decimal(str(ask_eur)) * chf_per_eur) if chf_per_eur else None
    landed_chf = float(Decimal(str(landed)) * chf_per_eur) if chf_per_eur else None
    return ExternalOpportunity(
        provider=ask.provider,
        url=ask.url,
        title=ask.title,
        price_jpy=ask.price_jpy,
        ask_eur=round(ask_eur, 2),
        ask_chf=round(ask_chf, 2) if ask_chf is not None else None,
        landed_eur=round(landed, 2),
        landed_chf=round(landed_chf, 2) if landed_chf is not None else None,
        external_fair_eur=round(fair, 2),
        discount_pct=round(discount, 1),
        external_sold_count=int(external.sold_count),
        external_source=external.source,
        evidence="GLOBAL_EXACT_GRADED_SOLD",
        delivery_route=delivery_route(ask.provider),
        identity=identity,
    )


def fingerprint(op: ExternalOpportunity) -> str:
    return hashlib.sha256(f"external-first|{op.provider}|{op.url}|{op.price_jpy}".encode()).hexdigest()


def notify(op: ExternalOpportunity, server: str, topic: str) -> None:
    landed = f"{op.landed_chf:.0f} CHF" if op.landed_chf is not None else f"€{op.landed_eur:.0f}"
    body = "\n".join(
        (
            f"{op.identity.name} {op.identity.number} | {op.identity.set_name}",
            "Japanese | PSA 10",
            "",
            f"{op.provider}: ¥{op.price_jpy:,} | rendu estimé {landed}",
            f"Marché externe exact SOLD: €{op.external_fair_eur:.0f}",
            f"Décote externe: -{op.discount_pct:.0f}%",
            f"Preuve: {op.external_source} | {op.external_sold_count} SOLD exacts",
            f"Route: {op.delivery_route}",
            "",
            "ASK ACTIF, PAS UNE VENTE. Vérification manuelle avant achat.",
            op.url,
        )
    )
    requests.post(
        f"{server.rstrip('/')}/{topic}",
        data=body.encode(),
        headers={"Title": "JAPAN EDGE EXTERNAL >=30%", "Priority": "high"},
        timeout=8,
    ).raise_for_status()


def run(
    state_path: Path,
    output_path: Path,
    *,
    max_gcc_pages: int = 20,
    max_seeds: int = 12,
    max_items: int = 25,
    max_confirmations: int = 12,
    min_discount: float = 30.0,
    proxy_jpy: int = 500,
    buffer_pct: float = 12.0,
    notify_enabled: bool = False,
    server: str = "https://ntfy.sh",
    topic: str = "",
) -> dict:
    now = now_utc()
    diag = Diagnostics()
    state = base.load_state(state_path)

    base_diag = base.Diagnostics()
    sold = base.fetch_gcc(max_gcc_pages, base_diag)
    diag.gcc_pages = base_diag.gcc_pages
    diag.gcc_rows = base_diag.gcc_rows
    diag.eligible_identity_observations = len(sold)
    seeds_all = identity_seeds(sold)
    diag.identity_seeds = len(seeds_all)
    seeds, cursor = seed_slice(seeds_all, state, max_seeds)
    diag.seeds_scanned = len(seeds)

    snapshot = ECBCurrencyConverter(timeout_seconds=8).get_snapshot()
    if not snapshot or not snapshot.units_per_eur.get("JPY"):
        raise RuntimeError("ECB JPY rate unavailable; fail-closed")
    jpy = snapshot.units_per_eur["JPY"]
    chf = snapshot.units_per_eur.get("CHF")

    prefilter_budget = multimarket.RequestBudget()
    confirm_budget = multimarket.RequestBudget()
    confirmations_used = 0
    opportunities: list[ExternalOpportunity] = []
    reviews: list[dict] = []
    confirmed_cache: dict[str, v3.ExternalReference] = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(locale="ja-JP")
        try:
            for seed in seeds:
                diag.external_prefilter_attempted += 1
                try:
                    prefilter = _prefilter_reference(seed.identity, prefilter_budget, now)
                except Exception as error:
                    prefilter = v3.ExternalReference(status=f"ERROR_{type(error).__name__}")
                if not _strong_external(prefilter):
                    diag.external_prefilter_unavailable += 1
                    continue
                diag.external_prefilter_strong += 1
                prefilter_fair = float(prefilter.fair_eur or 0)

                for provider in _provider_list():
                    diag.provider_searches += 1
                    try:
                        asks = base.collect(page, provider, seed.identity, max_items)
                    except Exception:
                        diag.provider_errors[provider.code] = diag.provider_errors.get(provider.code, 0) + 1
                        continue
                    diag.search_candidates += len(asks)
                    for ask in asks:
                        rough = base.landed_eur(ask.price_jpy, jpy, proxy_jpy, buffer_pct)
                        rough_discount = (prefilter_fair - rough) / prefilter_fair * 100 if prefilter_fair > 0 else 0
                        if rough_discount + 1e-9 < min_discount:
                            continue
                        diag.cheap_candidates += 1
                        try:
                            detailed = base.detail(page, ask)
                            diag.detail_pages += 1
                        except Exception:
                            detailed = ask
                        ok, reason = strict_identity_and_availability(detailed, seed.identity)
                        if reason == "marketplace_sold_page":
                            diag.sold_pages_skipped += 1
                            continue
                        if reason == "marketplace_availability_unproven":
                            diag.availability_unknown_skipped += 1
                            continue
                        if not ok:
                            diag.identity_rejected += 1
                            reviews.append(
                                {
                                    "provider": ask.provider,
                                    "url": ask.url,
                                    "price_jpy": ask.price_jpy,
                                    "identity_status": "UNPROVEN_LOG_ONLY",
                                    "reason": reason,
                                    "target": asdict(seed.identity),
                                }
                            )
                            continue
                        diag.exact_active_candidates += 1

                        key = seed.identity.key
                        external = confirmed_cache.get(key)
                        if external is None:
                            if confirmations_used >= max(0, max_confirmations):
                                diag.external_confirmation_unavailable += 1
                                continue
                            confirmations_used += 1
                            diag.external_confirmation_attempted += 1
                            try:
                                external = _confirmed_reference(seed.identity, confirm_budget, now)
                            except Exception as error:
                                external = v3.ExternalReference(status=f"ERROR_{type(error).__name__}")
                            confirmed_cache[key] = external
                        if not _strong_external(external):
                            diag.external_confirmation_unavailable += 1
                            continue
                        diag.external_confirmation_strong += 1
                        op = build_opportunity(
                            detailed,
                            seed.identity,
                            external,
                            jpy,
                            chf,
                            min_discount,
                            proxy_jpy,
                            buffer_pct,
                        )
                        if op is not None:
                            opportunities.append(op)
        finally:
            browser.close()

    unique: dict[tuple[str, str], ExternalOpportunity] = {}
    for op in opportunities:
        key = (op.provider, op.url)
        if key not in unique or op.discount_pct > unique[key].discount_pct:
            unique[key] = op
    opportunities = sorted(unique.values(), key=lambda item: item.discount_pct, reverse=True)
    diag.opportunities = len(opportunities)

    cutoff = now - timedelta(days=14)
    notified = {
        key: value
        for key, value in state.get("notified", {}).items()
        if (base.parse_time(value) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    }
    if notify_enabled and topic:
        for op in opportunities:
            fp = fingerprint(op)
            if fp not in notified:
                notify(op, server, topic)
                notified[fp] = now.isoformat().replace("+00:00", "Z")

    base.save_state(
        state_path,
        {
            "cursor": cursor,
            "notified": notified,
            "updated_at": now.isoformat().replace("+00:00", "Z"),
        },
    )
    payload = {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "mode": "READ_ONLY_PRODUCTION_EXTERNAL_FIRST",
        "marketplace_observations_are": "ACTIVE_ASK_NOT_SOLD",
        "gcc_role": "IDENTITY_SEED_ONLY_PRICE_IGNORED",
        "fair_value_role": "GLOBAL_EXACT_GRADED_SOLD_ONLY",
        "providers": [provider.code for provider in _provider_list()],
        "threshold": {
            "min_discount_pct_after_buffer": min_discount,
            "proxy_fixed_jpy": proxy_jpy,
            "logistics_buffer_pct": buffer_pct,
        },
        "diagnostics": asdict(diag),
        "opportunities": [asdict(op) for op in opportunities],
        "manual_reviews_log_only": reviews[:100],
        "safety": {"purchase": False, "bid": False, "checkout": False, "payment": False},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def env_i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=".japan-edge-state/state.json")
    parser.add_argument("--output", default="japan_edge_report.json")
    args = parser.parse_args()
    payload = run(
        Path(args.state),
        Path(args.output),
        max_gcc_pages=max(1, env_i("JAPAN_EDGE_GCC_PAGES", 20)),
        max_seeds=max(1, env_i("JAPAN_EDGE_MAX_SEEDS_PER_RUN", 12)),
        max_items=max(1, env_i("JAPAN_EDGE_MAX_ITEMS_PER_SEARCH", 25)),
        max_confirmations=max(0, min(20, env_i("JAPAN_EDGE_GLOBAL_MAX_CANDIDATES", 12))),
        min_discount=max(0.0, env_f("JAPAN_EDGE_MIN_DISCOUNT_PCT", 30)),
        proxy_jpy=max(0, env_i("JAPAN_EDGE_PROXY_FIXED_JPY", 500)),
        buffer_pct=max(0.0, env_f("JAPAN_EDGE_LOGISTICS_BUFFER_PCT", 12)),
        notify_enabled=os.getenv("JAPAN_EDGE_NOTIFY_ENABLED", "false").lower() == "true",
        server=os.getenv("NTFY_SERVER", "https://ntfy.sh"),
        topic=os.getenv("NTFY_TOPIC", "").strip(),
    )
    print(
        json.dumps(
            {
                "opportunities": len(payload["opportunities"]),
                "diagnostics": payload["diagnostics"],
                "providers": payload["providers"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
