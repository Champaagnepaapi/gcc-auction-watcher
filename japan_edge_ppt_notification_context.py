"""PokemonPriceTracker context displayed alongside Japan Edge market prices.

This module is deliberately downstream of the Japan Edge market decision. PPT may
be displayed in a notification/report, but it cannot create/suppress an
opportunity, change fair value, change the Japan Edge verdict, purchase, bid,
checkout, pay, or write commercial state.

PPT eBay graded evidence is SOLD_AGGREGATED, not item-level SOLD. The provider
is in the same eBay aggregate correlation family as PokeTrace and therefore is
never counted as an additional independent market.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional

import requests

from ecb_fx import ECBCurrencyConverter
import japan_edge_hunter as base
import japan_edge_ppt_provider_catalog_fix as catalog_fix

shadow = catalog_fix.shadow


@dataclass(frozen=True)
class PptNotificationContext:
    status: str
    fair_eur: Optional[float] = None
    discount_pct: Optional[float] = None
    sales_count: int = 0
    last_sale_date: Optional[str] = None
    momentum_30d_pct: Optional[float] = None
    momentum_90d_pct: Optional[float] = None
    momentum_180d_pct: Optional[float] = None
    evidence_class: str = shadow.EVIDENCE_CLASS
    correlation_group: str = shadow.CORRELATION_GROUP
    source: str = "PokemonPriceTracker eBay aggregate"
    note: str = ""
    production_decision_use: bool = False
    notification_decision_use: bool = False
    notification_display_use: bool = True


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default)).strip()))
    except ValueError:
        return default


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default)).strip()))
    except ValueError:
        return default


def _enabled() -> bool:
    return os.getenv("JAPAN_EDGE_PPT_CONTEXT_ENABLED", "false").strip().casefold() in {
        "1",
        "true",
        "yes",
    }


def not_requested(reason: str) -> PptNotificationContext:
    return PptNotificationContext(status=reason, notification_display_use=False)


class PptNotificationClient:
    """Small bounded client shared across one Japan Edge run."""

    def __init__(
        self,
        *,
        enabled: bool,
        api_key: str,
        max_candidates: int,
        budget: shadow.PptBudget,
        session: requests.Session,
        fx: ECBCurrencyConverter,
        timeout: float,
    ) -> None:
        self.enabled = enabled
        self.api_key = api_key.strip()
        self.max_candidates = max(0, int(max_candidates))
        self.budget = budget
        self.session = session
        self.fx = fx
        self.timeout = timeout
        self.attempted = 0
        self.matched = 0

    @classmethod
    def from_env(cls) -> "PptNotificationClient":
        return cls(
            enabled=_enabled(),
            api_key=os.getenv("POKEMONPRICETRACKER_API_KEY", ""),
            max_candidates=_env_int("JAPAN_EDGE_PPT_CONTEXT_MAX_CANDIDATES", 4, 0),
            budget=shadow.PptBudget(
                max_http_calls=_env_int("JAPAN_EDGE_PPT_CONTEXT_MAX_HTTP_CALLS", 8, 1),
                max_credits=_env_int("JAPAN_EDGE_PPT_CONTEXT_MAX_CREDITS", 40, 1),
                daily_remaining_floor=_env_int(
                    "JAPAN_EDGE_PPT_CONTEXT_DAILY_REMAINING_FLOOR", 15_000, 0
                ),
                interval_seconds=_env_float(
                    "JAPAN_EDGE_PPT_CONTEXT_INTERVAL_SECONDS", 1.10, 0.0
                ),
            ),
            session=requests.Session(),
            fx=ECBCurrencyConverter(),
            timeout=_env_float("JAPAN_EDGE_PPT_CONTEXT_TIMEOUT_SECONDS", 15.0, 1.0),
        )

    def fetch(self, op: base.Opportunity, now: datetime) -> PptNotificationContext:
        if not self.enabled:
            return PptNotificationContext(
                status="DISABLED",
                note="JAPAN_EDGE_PPT_CONTEXT_ENABLED=false",
                notification_display_use=False,
            )
        if not self.api_key:
            return PptNotificationContext(
                status="NO_API_KEY",
                note="PPT context enabled but API key is unavailable",
            )
        if self.attempted >= self.max_candidates:
            return PptNotificationContext(
                status="PENDING_BUDGET",
                note="PPT notification candidate cap reached",
            )

        self.attempted += 1
        try:
            snapshot, _diagnostics = shadow.fetch_japanese_snapshot(
                op.identity,
                api_key=self.api_key,
                budget=self.budget,
                session=self.session,
                fx=self.fx,
                timeout=self.timeout,
                now=now,
            )
        except Exception as error:
            return PptNotificationContext(
                status=f"ERROR_{type(error).__name__}",
                note="PPT notification lookup failed closed",
            )

        fair_eur = snapshot.fair_value_eur
        discount = None
        if fair_eur is not None and fair_eur > 0:
            discount = (fair_eur - float(op.landed_eur)) / fair_eur * 100.0
        if snapshot.status == "MATCHED":
            self.matched += 1

        return PptNotificationContext(
            status=snapshot.status,
            fair_eur=round(float(fair_eur), 2) if fair_eur is not None else None,
            discount_pct=round(discount, 1) if discount is not None else None,
            sales_count=max(0, int(snapshot.sales_count or 0)),
            last_sale_date=snapshot.last_sale_date,
            momentum_30d_pct=snapshot.momentum_30d_pct,
            momentum_90d_pct=snapshot.momentum_90d_pct,
            momentum_180d_pct=snapshot.momentum_180d_pct,
            note=snapshot.note,
        )

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": "PokemonPriceTracker",
            "evidence_class": shadow.EVIDENCE_CLASS,
            "correlation_group": shadow.CORRELATION_GROUP,
            "attempted": self.attempted,
            "matched": self.matched,
            "http_calls": self.budget.http_calls,
            "credits": self.budget.credits,
            "daily_remaining": self.budget.daily_remaining,
            "blocked_reason": self.budget.blocked_reason,
            "production_decision_use": False,
            "notification_decision_use": False,
            "notification_display_use": True,
        }


def as_payload(context: PptNotificationContext) -> dict[str, Any]:
    return asdict(context)


def notification_lines(context: PptNotificationContext) -> list[str]:
    if (
        context.status == "MATCHED"
        and context.fair_eur is not None
        and context.discount_pct is not None
    ):
        freshness = (
            f" | dernière {context.last_sale_date}"
            if context.last_sale_date
            else ""
        )
        return [
            (
                f"PPT eBay agrégé JP PSA10: €{context.fair_eur:.0f} | "
                f"{context.sales_count} ventes agrégées{freshness}"
            ),
            f"→ décote vs PPT: -{context.discount_pct:.0f}%",
        ]
    if context.notification_display_use:
        return [f"PPT eBay agrégé JP PSA10: non confirmé ({context.status})"]
    return []
