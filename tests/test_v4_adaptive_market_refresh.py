from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import watcher
import v4_canonical_multimarket as mm
import v4_multimarket_safety as safety


NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)


def sale(price: float, grader: str = "PSA", grade: float = 9.0, **kwargs) -> watcher.ComparableSale:
    return watcher.ComparableSale(
        price=price,
        grader=grader,
        grade=grade,
        source=kwargs.get("source", "gcc"),
        context=kwargs.get("context", "Pikachu Holo 025/165 French"),
        match_score=kwargs.get("match_score", 100),
        exact_card=kwargs.get("exact_card", True),
        grade_qualifier=kwargs.get("grade_qualifier"),
        proven_commercial_dimensions=kwargs.get("proven_commercial_dimensions", ()),
        identity_provenance=kwargs.get("identity_provenance", ""),
    )


class V4AdaptiveMarketRefreshTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "seen": {},
            "notified": {},
            "technical_alerts": {},
            watcher.EXTERNAL_CACHE_STATE_KEY: {
                "schema_version": watcher.EXTERNAL_CACHE_SCHEMA_VERSION,
                "entries": {},
            },
        }

    def make_lot(
        self,
        title: str = "Pikachu 025/165 Holo PSA 9",
        price: float = 72.0,
        source_type: str = "fixed",
        url: str = "https://gcc.example.com/item/adaptive-1",
    ) -> watcher.Lot:
        return watcher.Lot(
            url=url,
            title=title,
            current_price=price,
            source_type=source_type,
            grader="PSA",
            grade="9",
            minutes_to_end=None,
            card_set="151",
            card_number="025/165",
            language="fr",
            body="Catégorie: Pokémon\nRéférence: #025/165\nLangue: Français\nGrader: PSA\nGrade: 9",
        )

    def make_estimate(
        self,
        low: float = 95.0,
        central: float = 100.0,
        high: float = 105.0,
        adaptive_discount_pct: float = 30.0,
        grade_arbitrage: bool = False,
    ) -> watcher.MarketEstimate:
        return watcher.MarketEstimate(
            low=low,
            central=central,
            high=high,
            kept_comparables=[],
            rejected_outliers=[],
            recent_90_count=3,
            dated_count=3,
            liquidity="élevée",
            dispersion="faible",
            confidence="élevée",
            adaptive_discount_pct=adaptive_discount_pct,
            rationale="Test market estimate",
            source_counts={"ebay": 3},
            exact_grade_count=3,
            same_grader_count=3,
            grade_arbitrage=grade_arbitrage,
        )

    def make_candidate(
        self,
        lot: watcher.Lot,
        estimate: watcher.MarketEstimate | None = None,
        branch: str = watcher.GCC_BRANCH_UNAVAILABLE,
    ) -> watcher.ValuationCandidate:
        sales = [sale(100.0, grader=lot.grader, grade=9.0)] if estimate else []
        gcc = watcher.GccMarketEvidence(
            branch=branch,
            strength=watcher.EVIDENCE_WEAK if estimate is None else watcher.EVIDENCE_STRONG,
            estimate=estimate,
            sales=sales,
            lot=lot,
            rejection="décote insuffisante" if estimate else "aucun historique",
            rejection_category=watcher.REJECTION_INSUFFICIENT_DISCOUNT if estimate else watcher.REJECTION_EMPTY_HISTORY,
            opportunity=None,
        )
        return watcher.ValuationCandidate(gcc=gcc)

    # -------------------------------------------------------------------------
    # 1. Deterministic Proximity Calculation
    # -------------------------------------------------------------------------
    def test_adaptive_ttl_tiers_deterministic_calculation(self):
        est = self.make_estimate(low=100.0, central=100.0, adaptive_discount_pct=30.0)

        # Gap <= 3% (discount 28% -> gap 2%) -> 1 hour
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(72.0, est), 1)

        # Gap <= 6% (discount 25% -> gap 5%) -> 2 hours
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(75.0, est), 2)

        # Gap <= 10% (discount 21% -> gap 9%) -> 3 hours
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(79.0, est), 3)

        # Gap <= 15% (discount 16% -> gap 14%) -> 6 hours
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(84.0, est), 6)

        # Gap > 15% (discount 10% -> gap 20%) -> 24 hours
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(90.0, est), 24)

        # Negative discount (overpriced item: price 130 on 100 market) -> 24 hours
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(130.0, est), 24)

        # None / invalid inputs -> default 24h
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(None, est), 24)
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(70.0, None), 24)
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(0.0, est), 24)

    def test_adaptive_ttl_grade_arbitrage(self):
        est = self.make_estimate(low=100.0, central=120.0, grade_arbitrage=True)
        # Price <= low -> 1h
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(98.0, est), 1)
        # Overhang <= 3% (price 102 on low 100 -> 2%) -> 1h
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(102.0, est), 1)
        # Overhang <= 6% (price 105 on low 100 -> 5%) -> 2h
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(105.0, est), 2)
        # Overhang <= 10% (price 109 on low 100 -> 9%) -> 3h
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(109.0, est), 3)
        # Overhang <= 15% (price 114 on low 100 -> 14%) -> 6h
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(114.0, est), 6)
        # Overhang > 15% (price 125 on low 100 -> 25%) -> 24h
        self.assertEqual(watcher.adaptive_ttl_hours_for_estimate(125.0, est), 24)

    # -------------------------------------------------------------------------
    # 2. Ordinary Listings Stay 24h
    # -------------------------------------------------------------------------
    def test_ordinary_listings_stay_24h_ttl(self):
        lot = self.make_lot(price=95.0)  # Gap > 15% on 100.0 estimate
        key = watcher.external_commercial_identity_key(lot)
        est = self.make_estimate(low=95.0, central=100.0, adaptive_discount_pct=30.0)
        evidence = watcher.ExternalMarketEvidence(
            identity_key=key,
            status=watcher.EXTERNAL_MATCHED,
            strength=watcher.EVIDENCE_STRONG,
            source="poketrace",
            estimate=est,
            fetched_at=NOW,
        )
        watcher.store_external_evidence(self.state, evidence)

        # At age 2h -> HIT (ordinary stays 24h)
        cached, status = watcher.cached_external_evidence(
            self.state, key, NOW + timedelta(hours=2), candidate_prices=[lot.current_price]
        )
        self.assertEqual(status, "HIT")
        self.assertIsNotNone(cached)

        # At age 23h -> still HIT
        cached, status = watcher.cached_external_evidence(
            self.state, key, NOW + timedelta(hours=23), candidate_prices=[lot.current_price]
        )
        self.assertEqual(status, "HIT")

        # At age 25h -> STALE
        cached, status = watcher.cached_external_evidence(
            self.state, key, NOW + timedelta(hours=25), candidate_prices=[lot.current_price]
        )
        self.assertEqual(status, "STALE")

    # -------------------------------------------------------------------------
    # 3. Near-Threshold Listings Refresh Earlier (1–6h)
    # -------------------------------------------------------------------------
    def test_near_threshold_listings_refresh_earlier(self):
        # Listing 1: Gap <= 3% (Price 72 on 100 central / 100 low) -> 1h TTL
        lot_1h = self.make_lot(price=72.0)
        key_1h = watcher.external_commercial_identity_key(lot_1h)
        est_1h = self.make_estimate(low=100.0, central=100.0, adaptive_discount_pct=30.0)
        ev_1h = watcher.ExternalMarketEvidence(
            identity_key=key_1h,
            status=watcher.EXTERNAL_MATCHED,
            strength=watcher.EVIDENCE_STRONG,
            source="poketrace",
            estimate=est_1h,
            fetched_at=NOW,
        )
        watcher.store_external_evidence(self.state, ev_1h)

        # At 30 min -> HIT
        _, status = watcher.cached_external_evidence(
            self.state, key_1h, NOW + timedelta(minutes=30), candidate_prices=[lot_1h.current_price]
        )
        self.assertEqual(status, "HIT")

        # At 1h 10m -> STALE (refreshes after 1h!)
        _, status = watcher.cached_external_evidence(
            self.state, key_1h, NOW + timedelta(minutes=70), candidate_prices=[lot_1h.current_price]
        )
        self.assertEqual(status, "STALE")

        # Listing 2: Gap <= 6% (Price 75 on 100 central / 100 low) -> 2h TTL
        lot_2h = self.make_lot(price=75.0, url="https://gcc.example.com/item/adaptive-2h")
        key_2h = watcher.external_commercial_identity_key(lot_2h)
        ev_2h = watcher.ExternalMarketEvidence(
            identity_key=key_2h,
            status=watcher.EXTERNAL_MATCHED,
            strength=watcher.EVIDENCE_STRONG,
            source="poketrace",
            estimate=est_1h,
            fetched_at=NOW,
        )
        watcher.store_external_evidence(self.state, ev_2h)

        # At 1h 30m -> HIT
        _, status = watcher.cached_external_evidence(
            self.state, key_2h, NOW + timedelta(hours=1.5), candidate_prices=[lot_2h.current_price]
        )
        self.assertEqual(status, "HIT")

        # At 2h 10m -> STALE (refreshes after 2h!)
        _, status = watcher.cached_external_evidence(
            self.state, key_2h, NOW + timedelta(hours=2.2), candidate_prices=[lot_2h.current_price]
        )
        self.assertEqual(status, "STALE")

        # Listing 3: Gap <= 10% (Price 79 on 100 central) -> 3h TTL
        lot_3h = self.make_lot(price=79.0, url="https://gcc.example.com/item/adaptive-3h")
        key_3h = watcher.external_commercial_identity_key(lot_3h)
        ev_3h = watcher.ExternalMarketEvidence(
            identity_key=key_3h,
            status=watcher.EXTERNAL_MATCHED,
            strength=watcher.EVIDENCE_STRONG,
            source="poketrace",
            estimate=est_1h,
            fetched_at=NOW,
        )
        watcher.store_external_evidence(self.state, ev_3h)

        # At 2h 30m -> HIT
        _, status = watcher.cached_external_evidence(
            self.state, key_3h, NOW + timedelta(hours=2.5), candidate_prices=[lot_3h.current_price]
        )
        self.assertEqual(status, "HIT")

        # At 3h 10m -> STALE (refreshes after 3h!)
        _, status = watcher.cached_external_evidence(
            self.state, key_3h, NOW + timedelta(hours=3.2), candidate_prices=[lot_3h.current_price]
        )
        self.assertEqual(status, "STALE")

        # Listing 4: Gap <= 15% (Price 84 on 100 central) -> 6h TTL
        lot_6h = self.make_lot(price=84.0, url="https://gcc.example.com/item/adaptive-6h")
        key_6h = watcher.external_commercial_identity_key(lot_6h)
        ev_6h = watcher.ExternalMarketEvidence(
            identity_key=key_6h,
            status=watcher.EXTERNAL_MATCHED,
            strength=watcher.EVIDENCE_STRONG,
            source="poketrace",
            estimate=est_1h,
            fetched_at=NOW,
        )
        watcher.store_external_evidence(self.state, ev_6h)

        # At 5h -> HIT
        _, status = watcher.cached_external_evidence(
            self.state, key_6h, NOW + timedelta(hours=5), candidate_prices=[lot_6h.current_price]
        )
        self.assertEqual(status, "HIT")

        # At 6h 10m -> STALE (refreshes after 6h!)
        _, status = watcher.cached_external_evidence(
            self.state, key_6h, NOW + timedelta(hours=6.2), candidate_prices=[lot_6h.current_price]
        )
        self.assertEqual(status, "STALE")

    def test_auctions_retain_standard_24h_external_cache_ttl(self):
        # Auction with near-threshold price (72 € on 100 € estimate)
        lot_auction = self.make_lot(price=72.0, source_type="auction", url="https://gcc.example.com/item/auction-1")
        key = watcher.external_commercial_identity_key(lot_auction)
        est = self.make_estimate(low=100.0, central=100.0, adaptive_discount_pct=30.0)
        ev = watcher.ExternalMarketEvidence(
            identity_key=key,
            status=watcher.EXTERNAL_MATCHED,
            strength=watcher.EVIDENCE_STRONG,
            source="poketrace",
            estimate=est,
            fetched_at=NOW,
        )
        watcher.store_external_evidence(self.state, ev)

        candidate = self.make_candidate(lot_auction, est)
        budgets = watcher.ValidationBudgets()
        diag = watcher.RunDiagnostics()

        # At age 2h: process_external_market_candidates with auction candidate MUST hit 24h cache (not stale at 1h/2h)
        now_2h = NOW + timedelta(hours=2)
        provider_called = {"called": False}

        def mock_provider(*_):
            provider_called["called"] = True
            return ev

        watcher.process_external_market_candidates(
            None,
            [candidate],
            self.state,
            budgets,
            diag,
            now_2h,
            provider=mock_provider,
        )

        self.assertFalse(
            provider_called["called"],
            "Auctions must NOT trigger early adaptive refresh; they must use the standard 24h cache",
        )
        self.assertEqual(diag.external_market.cache_hits, 1)

    # -------------------------------------------------------------------------
    # 4. Fixed Queue Adaptive Staleness & Priority
    # -------------------------------------------------------------------------
    def test_fixed_queue_adaptive_re_evaluation_and_ordering(self):
        lot_near = self.make_lot(price=74.0, url="https://gcc.example.com/item/near")
        lot_far = self.make_lot(price=95.0, url="https://gcc.example.com/item/far")
        item_near = watcher.fixed_listing_id(lot_near)
        item_far = watcher.fixed_listing_id(lot_far)

        fp_near = watcher.fixed_metadata_fingerprint(lot_near)
        fp_far = watcher.fixed_metadata_fingerprint(lot_far)

        record_near = {
            "item_id": item_near,
            "first_seen_at": NOW.isoformat(),
            "last_seen_at": NOW.isoformat(),
            "last_evaluated_at": NOW.isoformat(),
            "last_price": 74.0,
            "metadata_fingerprint": fp_near,
            "evaluated_fingerprint": fp_near,
            "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
            "last_evaluation_status": watcher.REJECTION_INSUFFICIENT_DISCOUNT,
            "adaptive_ttl_hours": 2,
            "retry_count": 0,
            "retry_after": None,
            "active": True,
        }

        record_far = {
            "item_id": item_far,
            "first_seen_at": NOW.isoformat(),
            "last_seen_at": NOW.isoformat(),
            "last_evaluated_at": (NOW - timedelta(hours=5)).isoformat(),
            "last_price": 95.0,
            "metadata_fingerprint": fp_far,
            "evaluated_fingerprint": fp_far,
            "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
            "last_evaluation_status": watcher.REJECTION_INSUFFICIENT_DISCOUNT,
            "adaptive_ttl_hours": 24,
            "retry_count": 0,
            "retry_after": None,
            "active": True,
        }

        # At NOW + 1h: both are fresh
        t_1h = NOW + timedelta(hours=1)
        self.assertEqual(watcher._fixed_queue_category(record_near, fp_near, t_1h), watcher.QUEUE_FRESH)
        self.assertEqual(watcher._fixed_queue_category(record_far, fp_far, t_1h), watcher.QUEUE_FRESH)

        # At NOW + 2h 30m: near listing (TTL=2h) is STALE, far listing (TTL=24h, evaluated 7.5h ago) is still FRESH
        t_2h30 = NOW + timedelta(hours=2.5)
        self.assertEqual(watcher._fixed_queue_category(record_near, fp_near, t_2h30), watcher.QUEUE_P3_STALE)
        self.assertEqual(watcher._fixed_queue_category(record_far, fp_far, t_2h30), watcher.QUEUE_FRESH)

        # Sort key prioritizes near listing (adaptive_ttl_hours=2) over 24h stale listing in P3_STALE
        record_far["last_evaluated_at"] = (NOW - timedelta(hours=25)).isoformat()
        self.assertEqual(watcher._fixed_queue_category(record_far, fp_far, t_2h30), watcher.QUEUE_P3_STALE)

        records = {item_near: record_near, item_far: record_far}
        key_near = watcher._fixed_queue_sort_key(lot_near, watcher.QUEUE_P3_STALE, records)
        key_far = watcher._fixed_queue_sort_key(lot_far, watcher.QUEUE_P3_STALE, records)
        self.assertLess(key_near, key_far, "Near-threshold STALE (2h) must sort before standard STALE (24h)")

    # -------------------------------------------------------------------------
    # 5. Market Price Increase Rescues Previously Rejected Listing
    # -------------------------------------------------------------------------
    def test_market_price_increase_rescues_rejected_listing(self):
        lot = self.make_lot(price=72.0)
        key = watcher.external_commercial_identity_key(lot)
        item_id = watcher.fixed_listing_id(lot)

        # Setup initial state with rejected fixed listing record
        self.state[watcher.FIXED_QUEUE_STATE_KEY] = {
            "schema_version": watcher.FIXED_QUEUE_SCHEMA_VERSION,
            "items": {
                item_id: {
                    "item_id": item_id,
                    "first_seen_at": NOW.isoformat(),
                    "last_seen_at": NOW.isoformat(),
                    "last_evaluated_at": NOW.isoformat(),
                    "last_price": 72.0,
                    "metadata_fingerprint": watcher.fixed_metadata_fingerprint(lot),
                    "evaluated_fingerprint": watcher.fixed_metadata_fingerprint(lot),
                    "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
                    "last_evaluation_status": watcher.REJECTION_INSUFFICIENT_DISCOUNT,
                    "adaptive_ttl_hours": 2,
                    "retry_count": 0,
                    "retry_after": None,
                    "active": True,
                }
            },
        }

        # Run 1: Initial market estimate = 100 € (low 95 €, max_rec = 66.50 €)
        initial_est = self.make_estimate(low=95.0, central=100.0, adaptive_discount_pct=30.0)
        initial_ev = watcher.ExternalMarketEvidence(
            identity_key=key,
            status=watcher.EXTERNAL_MATCHED,
            strength=watcher.EVIDENCE_STRONG,
            source="poketrace",
            estimate=initial_est,
            fetched_at=NOW,
        )
        watcher.store_external_evidence(self.state, initial_ev)

        candidate = self.make_candidate(lot, initial_est)
        diag = watcher.RunDiagnostics()
        budgets = watcher.ValidationBudgets()

        # In Run 1, listing price (72 €) > max_recommended (66.50 €), so NO opportunity
        ops_1 = watcher.process_external_market_candidates(
            None,
            [candidate],
            self.state,
            budgets,
            diag,
            NOW,
            provider=lambda *_: initial_ev,
        )
        self.assertEqual(len(ops_1), 0, "Run 1 must reject listing (72 € > max_rec 66.50 €)")

        # Verify fixed record was assigned adaptive_ttl_hours = 2
        record = self.state[watcher.FIXED_QUEUE_STATE_KEY]["items"][item_id]
        self.assertEqual(record["adaptive_ttl_hours"], 2)

        # Run 2: 2h 30min later, external market value rises to 110 € (low 105 €, max_rec = 73.50 €)
        now_run2 = NOW + timedelta(hours=2.5)

        # Check queue classification at Run 2: becomes STALE after 2h
        cat = watcher._fixed_queue_category(
            record, watcher.fixed_metadata_fingerprint(lot), now_run2
        )
        self.assertEqual(cat, watcher.QUEUE_P3_STALE, "Must be classified as STALE after adaptive 2h TTL")

        # Cache check at Run 2: cache is STALE
        _, cache_status = watcher.cached_external_evidence(
            self.state, key, now_run2, candidate_prices=[lot.current_price]
        )
        self.assertEqual(cache_status, "STALE", "Cache must expire after adaptive 2h TTL")

        # Fresh provider returns higher market price
        rose_est = self.make_estimate(low=105.0, central=110.0, adaptive_discount_pct=30.0)
        rose_ev = watcher.ExternalMarketEvidence(
            identity_key=key,
            status=watcher.EXTERNAL_MATCHED,
            strength=watcher.EVIDENCE_STRONG,
            source="poketrace",
            estimate=rose_est,
            fetched_at=now_run2,
        )

        candidate_run2 = self.make_candidate(lot, None)  # GCC weak/unavailable
        diag_run2 = watcher.RunDiagnostics()
        budgets_run2 = watcher.ValidationBudgets()

        ops_2 = watcher.process_external_market_candidates(
            None,
            [candidate_run2],
            self.state,
            budgets_run2,
            diag_run2,
            now_run2,
            provider=lambda *_: rose_ev,
        )

        self.assertEqual(len(ops_2), 1, "Market rise must rescue previously rejected listing into an Opportunity!")
        op = ops_2[0]
        self.assertEqual(op.lot.url, lot.url)
        self.assertGreaterEqual(op.discount_pct, 30.0)
        self.assertLessEqual(op.lot.current_price, op.max_recommended)
        self.assertEqual(op.valuation_path, watcher.PATH_EXTERNAL_RESCUE)

    # -------------------------------------------------------------------------
    # 6. Provider Call Budgets Remain Strictly Bounded
    # -------------------------------------------------------------------------
    def test_provider_budgets_remain_strictly_bounded(self):
        candidates = []
        for i in range(15):
            lot = self.make_lot(
                title=f"Card #{i} PSA 9",
                price=70.0,
                url=f"https://gcc.example.com/item/budget-{i}",
            )
            candidates.append(self.make_candidate(lot))

        budgets = watcher.ValidationBudgets(
            psa_apr_cards=0,
            ebay_cards=0,
        )
        diag = watcher.RunDiagnostics()

        calls = {"count": 0}

        def mock_provider(candidate, b, now):
            calls["count"] += 1
            if b.psa_apr_cards >= watcher.PSA_APR_MAX_CARDS_PER_RUN:
                return watcher.ExternalMarketEvidence(
                    identity_key=watcher.external_commercial_identity_key(candidate.lot),
                    status=watcher.EXTERNAL_PENDING,
                    note="budget épuisé",
                )
            b.psa_apr_cards += 1
            est = self.make_estimate(low=100.0, central=100.0)
            return watcher.ExternalMarketEvidence(
                identity_key=watcher.external_commercial_identity_key(candidate.lot),
                status=watcher.EXTERNAL_MATCHED,
                strength=watcher.EVIDENCE_STRONG,
                source="psa",
                estimate=est,
                fetched_at=now,
            )

        watcher.process_external_market_candidates(
            None,
            candidates,
            self.state,
            budgets,
            diag,
            NOW,
            provider=mock_provider,
        )

        self.assertEqual(budgets.psa_apr_cards, watcher.PSA_APR_MAX_CARDS_PER_RUN, "PSA APR budget must match max limit")
        self.assertLessEqual(budgets.psa_apr_cards, watcher.PSA_APR_MAX_CARDS_PER_RUN)

    # -------------------------------------------------------------------------
    # 7. Anti-Starvation Guarantees
    # -------------------------------------------------------------------------
    def test_anti_starvation_guarantees_with_adaptive_p3(self):
        # 10 NEW items, 5 CHANGED items, 20 NEVER_EVALUATED items, 50 STALE items
        candidates = []
        lots_by_cat = {}

        # 5 CHANGED
        for i in range(5):
            lot = self.make_lot(url=f"https://gcc.example.com/item/changed-{i}", price=50.0)
            candidates.append(lot)
            lots_by_cat.setdefault("P1", []).append(lot)

        # 10 NEW
        for i in range(10):
            lot = self.make_lot(url=f"https://gcc.example.com/item/new-{i}", price=50.0)
            candidates.append(lot)
            lots_by_cat.setdefault("P0", []).append(lot)

        # 20 NEVER_EVALUATED
        for i in range(20):
            lot = self.make_lot(url=f"https://gcc.example.com/item/never-{i}", price=50.0)
            candidates.append(lot)
            lots_by_cat.setdefault("P2", []).append(lot)

        # 50 STALE (with adaptive TTLs 1h, 2h, 24h)
        for i in range(50):
            lot = self.make_lot(url=f"https://gcc.example.com/item/stale-{i}", price=50.0)
            candidates.append(lot)
            lots_by_cat.setdefault("P3", []).append(lot)

        # Populate state
        state = {
            watcher.FIXED_QUEUE_STATE_KEY: {
                "schema_version": watcher.FIXED_QUEUE_SCHEMA_VERSION,
                "items": {},
            }
        }
        items = state[watcher.FIXED_QUEUE_STATE_KEY]["items"]

        # CHANGED
        for lot in lots_by_cat["P1"]:
            item_id = watcher.fixed_listing_id(lot)
            fp = watcher.fixed_metadata_fingerprint(lot)
            items[item_id] = {
                "item_id": item_id,
                "first_seen_at": (NOW - timedelta(days=2)).isoformat(),
                "last_seen_at": (NOW - timedelta(days=1)).isoformat(),
                "last_evaluated_at": (NOW - timedelta(days=1)).isoformat(),
                "last_price": 40.0,  # price changed from 40 to 50
                "metadata_fingerprint": fp,
                "evaluated_fingerprint": "old_fp",
                "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
                "last_evaluation_status": "insufficient_discount",
                "adaptive_ttl_hours": 2,
                "retry_count": 0,
                "retry_after": None,
                "active": True,
            }

        # NEVER_EVALUATED
        for lot in lots_by_cat["P2"]:
            item_id = watcher.fixed_listing_id(lot)
            fp = watcher.fixed_metadata_fingerprint(lot)
            items[item_id] = {
                "item_id": item_id,
                "first_seen_at": (NOW - timedelta(hours=12)).isoformat(),
                "last_seen_at": (NOW - timedelta(hours=1)).isoformat(),
                "last_evaluated_at": None,
                "last_price": 50.0,
                "metadata_fingerprint": fp,
                "evaluated_fingerprint": None,
                "evaluation_version": None,
                "last_evaluation_status": None,
                "adaptive_ttl_hours": 24,
                "retry_count": 0,
                "retry_after": None,
                "active": True,
            }

        # STALE
        for i, lot in enumerate(lots_by_cat["P3"]):
            item_id = watcher.fixed_listing_id(lot)
            fp = watcher.fixed_metadata_fingerprint(lot)
            items[item_id] = {
                "item_id": item_id,
                "first_seen_at": (NOW - timedelta(days=5)).isoformat(),
                "last_seen_at": (NOW - timedelta(hours=5)).isoformat(),
                "last_evaluated_at": (NOW - timedelta(hours=3 if i < 10 else 25)).isoformat(),
                "last_price": 50.0,
                "metadata_fingerprint": fp,
                "evaluated_fingerprint": fp,
                "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
                "last_evaluation_status": "insufficient_discount",
                "adaptive_ttl_hours": 2 if i < 10 else 24,
                "retry_count": 0,
                "retry_after": None,
                "active": True,
            }

        diag = watcher.RunDiagnostics()
        selected, cat_by_id, records = watcher._prepare_fixed_economic_queue(
            candidates, state, NOW, diag, valuation_cap=40
        )

        # Budget is 40:
        # Urgent: 5 CHANGED + 10 NEW = 15
        # Remaining budget = 25
        # Stale floor = 20, NEVER_EVALUATED = 5, total = 40
        p0_selected = sum(cat_by_id[watcher.fixed_listing_id(l)] == watcher.QUEUE_P0_NEW for l in selected)
        p1_selected = sum(cat_by_id[watcher.fixed_listing_id(l)] == watcher.QUEUE_P1_CHANGED for l in selected)
        p2_selected = sum(cat_by_id[watcher.fixed_listing_id(l)] == watcher.QUEUE_P2_NEVER_EVALUATED for l in selected)
        p3_selected = sum(cat_by_id[watcher.fixed_listing_id(l)] == watcher.QUEUE_P3_STALE for l in selected)

        self.assertEqual(p0_selected, 10, "All 10 NEW items must be selected")
        self.assertEqual(p1_selected, 5, "All 5 CHANGED items must be selected")
        self.assertGreaterEqual(p2_selected, 5, "NEVER_EVALUATED must not be starved by STALE queue")
        self.assertGreaterEqual(p3_selected, 20, "STALE must receive its reserved floor")
        self.assertEqual(len(selected), 40, "Total selected must equal valuation cap")

    # -------------------------------------------------------------------------
    # 8. Transient / Rate Limit Failures are Never Cached as Clean Negatives
    # -------------------------------------------------------------------------
    def test_transient_failures_never_cached_as_clean_negatives(self):
        lot = self.make_lot()
        key = watcher.external_commercial_identity_key(lot)

        for err_status in (
            watcher.EXTERNAL_PROVIDER_ERROR,
            watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
            watcher.EXTERNAL_RATE_LIMITED,
        ):
            ev = watcher.ExternalMarketEvidence(
                identity_key=key,
                status=err_status,
                fetched_at=NOW,
            )
            # Store must reject caching transient failures
            stored = watcher.store_external_evidence(self.state, ev)
            self.assertFalse(stored)
            self.assertNotIn(key, self.state[watcher.EXTERNAL_CACHE_STATE_KEY]["entries"])


if __name__ == "__main__":
    unittest.main()
