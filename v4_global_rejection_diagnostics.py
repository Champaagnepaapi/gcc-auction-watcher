from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import japan_edge_hunter as japan
from v4_global_live_shadow import (
    _comc_ask_price,
    _comc_candidate_links,
    _fanatics_candidate_links,
    _magi_provider,
    _price_from_usd_text,
    build_seed_panel,
    now_utc,
    strict_text_identity,
)


MAX_EXAMPLES_PER_REASON = 3


@dataclass
class ReasonTracker:
    market: str
    searches: int = 0
    candidates: int = 0
    exact: int = 0
    reject_reasons: Counter[str] = field(default_factory=Counter)
    examples: dict[str, list[dict[str, str]]] = field(default_factory=lambda: defaultdict(list))
    per_identity: dict[str, dict[str, Any]] = field(default_factory=dict)

    def _identity_bucket(self, label: str) -> dict[str, Any]:
        return self.per_identity.setdefault(
            label,
            {
                "search_candidates": 0,
                "exact": 0,
                "reject_reasons": {},
            },
        )

    def add_search(self, label: str, count: int) -> None:
        self.searches += 1
        self.candidates += max(0, count)
        bucket = self._identity_bucket(label)
        bucket["search_candidates"] += max(0, count)
        if count == 0:
            self.reject(label, "search_no_candidates")

    def add_exact(self, label: str) -> None:
        self.exact += 1
        self._identity_bucket(label)["exact"] += 1

    def reject(self, label: str, reason: str, *, title: str = "", url: str = "") -> None:
        key = normalize_reason(reason)
        self.reject_reasons[key] += 1
        bucket = self._identity_bucket(label)
        local = bucket.setdefault("reject_reasons", {})
        local[key] = int(local.get(key, 0)) + 1
        examples = self.examples[key]
        if len(examples) < MAX_EXAMPLES_PER_REASON:
            example = {"identity": label}
            if title:
                example["title"] = title[:300]
            if url:
                example["url"] = url[:500]
            examples.append(example)

    def export(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "searches": self.searches,
            "candidates": self.candidates,
            "exact": self.exact,
            "reject_reasons": dict(self.reject_reasons.most_common()),
            "reason_buckets": summarize_reason_buckets(self.reject_reasons),
            "examples": {key: rows for key, rows in sorted(self.examples.items())},
            "per_identity": self.per_identity,
        }


def normalize_reason(reason: object) -> str:
    value = str(reason or "unknown").strip().casefold()
    value = re.sub(r"\s+", "_", value)
    return value or "unknown"


def reason_bucket(reason: str) -> str:
    value = normalize_reason(reason)
    if value in {"search_no_candidates", "player_or_card_number_not_found"}:
        return "RETRIEVAL_GAP"
    if value in {
        "collector_number_unproven",
        "psa10_unproven",
        "language_unproven",
        "card_name_unproven",
        "set_unproven",
        "card_or_set_unproven",
        "edition_unproven",
        "microvariant_unproven",
    } or value.startswith("sensitive_variant_unproven"):
        return "METADATA_OR_IDENTITY_PROOF_GAP"
    if value in {
        "ongoing_auction",
        "multi_item_listing",
        "unavailable_or_sold",
        "price_unproven",
    }:
        return "TRUE_INCOMPATIBLE_OR_NON_ACTIONABLE"
    if value in {"detail_error", "search_error", "page_error", "provider_error"}:
        return "TECHNICAL_ERROR"
    return "OTHER"


def summarize_reason_buckets(reasons: Mapping[str, int]) -> dict[str, int]:
    output: Counter[str] = Counter()
    for reason, count in reasons.items():
        output[reason_bucket(reason)] += int(count)
    return dict(output.most_common())


def identity_label(seed: Any) -> str:
    identity = seed.source_identity
    return " | ".join(
        [
            str(identity.name),
            str(identity.set_name),
            str(identity.number),
            "Japanese",
            "PSA 10",
        ]
    )


def diagnose_magi(page: Any, seeds: Sequence[Any], *, max_candidates: int) -> ReasonTracker:
    tracker = ReasonTracker("magi")
    provider = _magi_provider()
    for seed in seeds:
        label = identity_label(seed)
        try:
            asks = japan.collect(page, provider, seed.source_identity, max_items=max_candidates)
        except Exception:
            tracker.reject(label, "search_error")
            tracker.searches += 1
            continue
        tracker.add_search(label, len(asks))
        for ask in asks:
            try:
                detailed = japan.detail(page, ask)
            except Exception:
                tracker.reject(label, "detail_error", title=ask.title, url=ask.url)
                continue
            ok, reason = japan.identity_check(detailed, seed.source_identity)
            if not ok:
                tracker.reject(label, reason, title=detailed.title, url=detailed.url)
                continue
            tracker.add_exact(label)
    return tracker


def diagnose_fanatics(page: Any, seeds: Sequence[Any], *, max_candidates: int) -> ReasonTracker:
    tracker = ReasonTracker("fanatics")
    for seed in seeds:
        label = identity_label(seed)
        try:
            links = _fanatics_candidate_links(page, seed, max_candidates)
        except Exception:
            tracker.reject(label, "search_error")
            tracker.searches += 1
            continue
        tracker.add_search(label, len(links))
        for url in links:
            title = ""
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(700)
                title = page.locator("h1").first.inner_text(timeout=4000).strip()
                body = page.locator("body").inner_text(timeout=5000)
            except Exception:
                tracker.reject(label, "page_error", title=title, url=url)
                continue
            upper = body.upper()
            if "THIS ITEM IS NOT AVAILABLE" in upper or re.search(r"\bSOLD\s*:", upper):
                tracker.reject(label, "unavailable_or_sold", title=title, url=url)
                continue
            before_guide = re.split(r"Guide Price", body, maxsplit=1, flags=re.I)[0]
            if _price_from_usd_text(before_guide) is None:
                tracker.reject(label, "price_unproven", title=title, url=url)
                continue
            ok, reason = strict_text_identity(f"{title}\n{before_guide}", seed.source_identity)
            if not ok:
                tracker.reject(label, reason, title=title, url=url)
                continue
            tracker.add_exact(label)
    return tracker


def diagnose_comc(page: Any, seeds: Sequence[Any], *, max_candidates: int) -> ReasonTracker:
    tracker = ReasonTracker("comc")
    for seed in seeds:
        label = identity_label(seed)
        try:
            links = _comc_candidate_links(page, seed, max_candidates)
        except Exception:
            tracker.reject(label, "search_error")
            tracker.searches += 1
            continue
        tracker.add_search(label, len(links))
        if not links:
            tracker.reject(label, "player_or_card_number_not_found")
            continue
        for url in links:
            title = ""
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(600)
                title = page.locator("h1").first.inner_text(timeout=4000).strip()
                body = page.locator("body").inner_text(timeout=5000)
            except Exception:
                tracker.reject(label, "page_error", title=title, url=url)
                continue
            upper = body.upper()
            if "SOLD OUT" in upper or "0 RESULTS" in upper:
                tracker.reject(label, "unavailable_or_sold", title=title, url=url)
                continue
            if _comc_ask_price(body) is None:
                tracker.reject(label, "price_unproven", title=title, url=url)
                continue
            ok, reason = strict_text_identity(f"{title}\n{body[:6000]}", seed.source_identity)
            if not ok:
                tracker.reject(label, reason, title=title, url=url)
                continue
            tracker.add_exact(label)
    return tracker


def build_fix_priorities(trackers: Sequence[ReasonTracker]) -> list[dict[str, Any]]:
    merged: Counter[tuple[str, str]] = Counter()
    for tracker in trackers:
        for reason, count in tracker.reject_reasons.items():
            merged[(tracker.market, reason)] += int(count)
    rows = [
        {
            "market": market,
            "reason": reason,
            "bucket": reason_bucket(reason),
            "count": count,
            "recommended_action": recommended_action(reason),
        }
        for (market, reason), count in merged.most_common()
    ]
    return rows


def recommended_action(reason: str) -> str:
    bucket = reason_bucket(reason)
    if reason in {"search_no_candidates", "player_or_card_number_not_found"}:
        return "Improve retrieval/query/catalog navigation without relaxing the exact identity gate."
    if reason == "collector_number_unproven":
        return "Improve page extraction or structured collector-number parsing; keep full numerator/denominator mandatory."
    if reason == "language_unproven":
        return "Find a deterministic language field/catalog invariant; do not infer Japanese from market geography alone."
    if reason in {"card_name_unproven", "set_unproven", "card_or_set_unproven"}:
        return "Add deterministic catalog alias/provenance for retrieval/proof; no fuzzy acceptance."
    if reason in {"psa10_unproven"}:
        return "Extract grader/grade from structured page metadata or slab data before accepting."
    if reason in {"edition_unproven", "microvariant_unproven"} or reason.startswith("sensitive_variant_unproven"):
        return "Add explicit edition/finish/microvariant proof; never assume missing qualifiers."
    if bucket == "TECHNICAL_ERROR":
        return "Harden page navigation/parsing and retry semantics; keep provider failures distinct from no-match."
    if bucket == "TRUE_INCOMPATIBLE_OR_NON_ACTIONABLE":
        return "No identity relaxation: keep excluded or improve listing-type/price extraction only if evidence supports it."
    return "Inspect bounded examples before changing retrieval or proof logic."


def run(args: argparse.Namespace) -> dict[str, Any]:
    observed_at = now_utc()
    diagnostics = japan.Diagnostics()
    sales = japan.fetch_gcc(max_pages=max(1, args.gcc_sold_pages), diag=diagnostics)
    seeds = build_seed_panel(sales, observed_at=observed_at, max_identities=max(1, args.max_identities))

    trackers: list[ReasonTracker] = []
    if seeds:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(locale="en-US", user_agent="Mozilla/5.0")
            page = context.new_page()
            trackers.append(diagnose_magi(page, seeds, max_candidates=max(1, args.market_candidates)))
            trackers.append(diagnose_fanatics(page, seeds, max_candidates=max(1, args.market_candidates)))
            trackers.append(diagnose_comc(page, seeds, max_candidates=max(1, args.market_candidates)))
            context.close()
            browser.close()

    report = {
        "schema_version": 1,
        "observed_at": observed_at.isoformat(),
        "mode": "READ_ONLY_REJECTION_DIAGNOSTIC",
        "scope": "Japanese PSA10 exact seeds from GCC SOLD fair-value panel",
        "identity_policy": "retrieval may improve; exact proof gate remains deterministic and fail-closed",
        "notifications": False,
        "transactions": False,
        "cardova": {
            "status": "AUTH_SESSION_INPUT_REQUIRED",
            "detail": "Not diagnosed from GitHub Actions; no browser cookies/tokens/headers are imported.",
        },
        "seed_count": len(seeds),
        "seeds": [identity_label(seed) for seed in seeds],
        "markets": [tracker.export() for tracker in trackers],
        "fix_priorities": build_fix_priorities(trackers),
        "gcc_sold_diagnostics": asdict(diagnostics),
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "global_rejection_diagnostics.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Read-only rejection diagnostics for V4 global market shadow")
    value.add_argument("--output-dir", default="global_shadow_out")
    value.add_argument("--max-identities", type=int, default=5)
    value.add_argument("--gcc-sold-pages", type=int, default=20)
    value.add_argument("--market-candidates", type=int, default=8)
    return value


def main() -> int:
    args = parser().parse_args()
    report = run(args)
    print(
        json.dumps(
            {
                "mode": report.get("mode"),
                "seed_count": report.get("seed_count"),
                "markets": [
                    {
                        "market": row.get("market"),
                        "candidates": row.get("candidates"),
                        "exact": row.get("exact"),
                        "reject_reasons": row.get("reject_reasons"),
                    }
                    for row in report.get("markets", [])
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
