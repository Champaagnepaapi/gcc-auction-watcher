"""Robot KB sidecar for Magi listings explicitly marked SOLD.

This lane is deliberately separate from V4 opportunity discovery. It uses the
provider's public ``status=presented`` filter to identify the active set, then
checks only rows present in the broad result but absent from that active set.
A detail-page explicit SOLD marker is still mandatory before persistence.

A SOLD marker is *not* proof of a completed transaction, final sale price, or
sale date. Stored observations therefore remain ``LISTING_SNAPSHOT`` with
``snapshot_status=SOLD_MARKED``, ``provider_sale_evidence=False`` and
``genuine_sale_evidence=False``. The displayed price is preserved only as the
listing price observed on that page.

No network or database work happens on import. Runtime activation is opt-in via
``ROBOT_KB_MAGI_SOLD_MARKED_ENABLED=true`` and remains Robot-KB-only.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


_PRESENTED_STATUS_PARAMETER = "forms_search_items%5Bstatus%5D=presented"
_EXCLUDED_MARKERS = (
    "ポケモンだいすきクラブ",
    "ポケモンパルシティ",
    "バトルロードサマー",
)


@dataclass(frozen=True)
class MagiSoldMarkedSnapshot:
    url: str
    title: str
    price_jpy: int
    observed_at: datetime
    marker_reason: str

    @property
    def stable_key(self) -> str:
        return f"magi_sold_marked:{self.url}"


def enabled() -> bool:
    return os.getenv("ROBOT_KB_MAGI_SOLD_MARKED_ENABLED", "false").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _compact(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).replace(" ", "")


def excluded_subject(value: object) -> bool:
    text = _compact(value)
    return any(marker in text for marker in _EXCLUDED_MARKERS)


def presented_only_url(url: object) -> str:
    raw = str(url or "")
    if "magi.camp/items/search" not in raw or _PRESENTED_STATUS_PARAMETER in raw:
        return raw
    separator = "&" if "?" in raw else "?"
    return f"{raw}{separator}{_PRESENTED_STATUS_PARAMETER}"


class PresentedOnlyPage:
    """Proxy only Magi search navigation while delegating the Playwright page."""

    def __init__(self, page: Any):
        self._page = page

    def goto(self, url: object, *args, **kwargs):
        return self._page.goto(presented_only_url(url), *args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._page, name)


def eligible_single_card_title(title: object) -> bool:
    """Keep only the existing Robot/V4 Pokémon single-card PSA10 scope."""
    import japan_edge_hunter as japan
    import v4_global_retrieval_hardening_v3 as retrieval_v3

    current = japan.current_text(str(title or ""))
    if not current or excluded_subject(current):
        return False
    if japan.has_any(current, japan.AUCTION) or japan.has_any(current, japan.MULTI):
        return False
    normalized = unicodedata.normalize("NFKC", current)
    return bool(
        retrieval_v3.SINGLE_CARD_RE.search(normalized)
        and retrieval_v3.PSA10_RE.search(normalized)
    )


def semantic_payload(snapshot: MagiSoldMarkedSnapshot) -> dict[str, object]:
    """Material fields only; observed_at is intentionally excluded for dedupe."""
    return {
        "market": "magi",
        "source_url": snapshot.url,
        "title": snapshot.title,
        "price": int(snapshot.price_jpy),
        "currency": "JPY",
        "snapshot_status": "SOLD_MARKED",
        "marker_reason": snapshot.marker_reason,
        "sale_evidence": False,
        "final_transaction_price_proven": False,
        "sale_date_proven": False,
    }


def raw_payload(snapshot: MagiSoldMarkedSnapshot) -> dict[str, object]:
    payload = semantic_payload(snapshot)
    payload["observed_at"] = snapshot.observed_at.isoformat()
    return payload


def collect(page: Any, *, observed_at: datetime, max_detail_pages: int = 120) -> list[MagiSoldMarkedSnapshot]:
    """Read broad + active Magi result sets, then confirm explicit SOLD on detail."""
    import v4_global_magi_registry_hardening as magi_hardening
    import v4_global_marketplace_scan as scan
    import v4_global_retrieval_hardening as retrieval_v1

    all_rows = scan._magi_broad_rows(page)
    presented_rows = scan._magi_broad_rows(PresentedOnlyPage(page))
    active_urls = {str(row.url) for row in presented_rows}

    candidates = [
        row
        for row in all_rows
        if str(row.url) not in active_urls and eligible_single_card_title(row.title)
    ]
    output: list[MagiSoldMarkedSnapshot] = []
    for ask in candidates[: max(1, int(max_detail_pages))]:
        try:
            detailed = retrieval_v1.magi_detail_only(page, ask)
        except Exception:
            continue
        available, reason = magi_hardening.magi_listing_availability_check(page, detailed)
        if available or reason not in {"sold_listing", "sold_listing_dom_marker"}:
            continue
        title = str(detailed.title or ask.title or "").strip()
        if not eligible_single_card_title(title):
            continue
        price = int(getattr(detailed, "price_jpy", 0) or 0)
        if price <= 0:
            continue
        output.append(
            MagiSoldMarkedSnapshot(
                url=str(detailed.url or ask.url),
                title=title[:500],
                price_jpy=price,
                observed_at=observed_at,
                marker_reason=reason,
            )
        )
    return output


def persist(kb: Any, snapshot: MagiSoldMarkedSnapshot, *, runtime: Any) -> None:
    """Persist one non-sale listing snapshot through the existing Robot KB sidecar."""
    (
        InclusionState,
        ObservationType,
        SourceKind,
        _KnowledgeBase,
        PriceComponent,
        IdentityClaim,
        NormalizedObservation,
        RawSourceRecord,
        ShadowDiagnostics,
        ShadowKnowledgePersistence,
    ) = runtime()

    native = snapshot.url
    payload = raw_payload(snapshot)
    prices = (
        PriceComponent(
            "ITEM_PRICE",
            int(snapshot.price_jpy) * 100,
            "JPY",
            inclusion_state=InclusionState.UNKNOWN,
        ),
    )
    claims = (
        IdentityClaim("listing_url", snapshot.url, SourceKind.LISTING),
        IdentityClaim("provider_title", snapshot.title, SourceKind.LISTING),
        IdentityClaim("listing_status", "SOLD_MARKED", SourceKind.LISTING),
    )
    record = RawSourceRecord(
        source_code="magi",
        source_name="Magi",
        source_role="LISTING_PLATFORM",
        source_native_record_id=native,
        payload=payload,
        retrieved_at=snapshot.observed_at.isoformat(),
        object_type="LISTING",
        external_native_id=native,
    )
    observation = NormalizedObservation(
        observation_type=ObservationType.LISTING_SNAPSHOT,
        source_native_record_id=native,
        observed_at=snapshot.observed_at.isoformat(),
        fact={
            "listing_started_at": None,
            "snapshot_status": "SOLD_MARKED",
            "quantity": 1,
            "provider_sale_evidence": False,
        },
        prices=prices,
        identity_subject_type="MAGI_SOLD_MARKED_LISTING",
        identity_subject_label=f"Magi SOLD-marked listing {native}",
        identity_namespace="MAGI_LISTING_URL",
        identity_identifier_value=native,
        unresolved_dimensions=("canonical_identity", "commercial_microvariant", "sale_event"),
        claims=claims,
        exact_identity_eligible=False,
        genuine_sale_evidence=False,
    )
    ShadowKnowledgePersistence(kb).ingest(record, (observation,), ShadowDiagnostics())


def harvest(kb: Any, state: dict[str, Any], diag: Any, *, now_fn: Any, runtime: Any, fingerprint_fn: Any) -> None:
    """Opt-in public collector. Baseline once, then material listing changes only."""
    if not enabled():
        diag.notes.append("magi-sold-marked:disabled")
        return

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(locale="en-US", user_agent="Mozilla/5.0")
            page = context.new_page()
            rows = collect(
                page,
                observed_at=now_fn(),
                max_detail_pages=max(
                    1, int(os.getenv("ROBOT_KB_MAGI_SOLD_MARKED_DETAIL_CAP", "120"))
                ),
            )
            context.close()
            browser.close()
    except Exception as error:
        diag.source_failures += 1
        diag.notes.append(f"magi-sold-marked:error:{type(error).__name__}")
        return

    fingerprints = state.setdefault("marketplace_fingerprints", {})
    stored = unchanged = 0
    for snapshot in rows:
        current = fingerprint_fn(semantic_payload(snapshot))
        if fingerprints.get(snapshot.stable_key) == current:
            unchanged += 1
            continue
        persist(kb, snapshot, runtime=runtime)
        fingerprints[snapshot.stable_key] = current
        stored += 1
    diag.notes.append(
        f"magi-sold-marked:seen={len(rows)}:stored={stored}:unchanged={unchanged}:sale_evidence=false"
    )
