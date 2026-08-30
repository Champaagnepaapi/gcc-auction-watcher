from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse


P3_AVAILABLE = importlib.util.find_spec("robot_kb") is not None
PATH = Path("mac/robot-kb-local/robot_kb_cardova_paid_sold_recurring.py")
RUNNER_PATH = Path("mac/robot-kb-local/robot_kb_cardova_paid_sold_runner.sh")
INSTALLER_PATH = Path("mac/robot-kb-local/Installer Cardova SOLD Local.command")

if P3_AVAILABLE:
    SPEC = importlib.util.spec_from_file_location("cardova_paid_sold_recurring", PATH)
    MOD = importlib.util.module_from_spec(SPEC)
    assert SPEC.loader is not None
    SPEC.loader.exec_module(MOD)
else:
    MOD = None


def paid_row(native: str, *, bid: int = 123456) -> dict:
    return {
        "ulid": native,
        "listing_type": 1,
        "bid_price": bid,
        "finished": 1,
        "end_date": "2026-08-29T21:00:00+09:00",
        "bid_payment_status": 5,
        "seller_payment_status": None,
        "canceled_at": None,
        "re_listed": 0,
        "re_listing_count": 0,
        "authentication_company_code": "P",
        "grade": "10.0",
        "language": "Japanese",
        "player": "Pikachu",
        "variety": "Pokemon TCG: Japanese XY Promo",
        "variety_short": "20th Anniversary Festa",
        "series": "Pokemon TCG: Japanese XY Promo",
        "title": "Pikachu 279/XY-P PSA 10",
        "item_name": "Pikachu",
        "card_ulid": f"CARD-{native}",
        "card_number": "#279/XY-P",
        "certificate_number": "123456789",
        "category": "Pokemon",
        "attribute": "Holo",
        "attribute2": "",
        "attribute3": "",
    }


def capture(rows: list[dict]) -> dict:
    return {
        "page_http_status": 200,
        "captured_api_http_status": 200,
        "rows": rows,
    }


def fetcher_for(pages: dict[int, dict]):
    calls: list[int] = []

    def fetch(url: str):
        page = int(parse_qs(urlparse(url).query)["page"][0])
        calls.append(page)
        return pages.get(page, capture([]))

    return fetch, calls


@unittest.skipUnless(P3_AVAILABLE, "pinned Robot KB P3 runtime is not present in this V4-only test lane")
class CardovaPaidSoldRecurringTests(unittest.TestCase):
    def test_page_url_is_public_closed_tcg_and_bounded(self):
        url = MOD.page_url(3, page_size=24)
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.hostname, "www.cardova.co.jp")
        self.assertEqual(parsed.path, "/en/auction/close")
        query = parse_qs(parsed.query)
        self.assertEqual(query["kind"], ["1"])
        self.assertEqual(query["limit"], ["24"])
        self.assertEqual(query["page"], ["3"])
        self.assertEqual(query["status"], ["close"])
        self.assertNotIn("sort", query)
        with self.assertRaises(ValueError):
            MOD.page_url(0, page_size=24)
        with self.assertRaises(ValueError):
            MOD.page_url(1, page_size=25)

    def test_front_pages_plus_rotation_advance_without_assumed_sort(self):
        fetch, calls = fetcher_for(
            {
                1: capture([paid_row("A")]),
                2: capture([paid_row("B")]),
                3: capture([paid_row("C")]),
                4: capture([paid_row("D")]),
            }
        )
        records, diag, next_state = MOD.collect_cycle(
            MOD.empty_state(),
            front_pages=2,
            rotation_pages=4,
            page_size=24,
            wait_ms=500,
            fetch_page=fetch,
        )
        self.assertEqual(calls, [1, 2, 3, 4])
        self.assertEqual(diag["planned_pages"], [1, 2, 3, 4])
        self.assertFalse(diag["rotation_boundary_detected"])
        self.assertEqual(diag["rotation_next_page"], 5)
        self.assertEqual(next_state["next_rotation_page"], 5)
        self.assertEqual({row["source_native_record_id"] for row in records}, {"A", "B", "C", "D"})
        self.assertFalse(diag.get("sort_order_proven", False))

    def test_duplicate_consecutive_rotation_page_resets_cursor(self):
        state = {**MOD.empty_state(), "next_rotation_page": 5}
        same = [paid_row("SAME")]
        fetch, calls = fetcher_for(
            {
                1: capture([paid_row("FRONT")]),
                5: capture(same),
                6: capture(same),
                7: capture([paid_row("SHOULD-NOT-BE-FETCHED")]),
            }
        )
        records, diag, next_state = MOD.collect_cycle(
            state,
            front_pages=1,
            rotation_pages=3,
            page_size=24,
            wait_ms=500,
            fetch_page=fetch,
        )
        self.assertEqual(calls, [1, 5, 6])
        self.assertTrue(diag["rotation_boundary_detected"])
        self.assertEqual(next_state["next_rotation_page"], 1)
        self.assertEqual({row["source_native_record_id"] for row in records}, {"FRONT", "SAME"})

    def test_empty_rotation_page_resets_cursor(self):
        state = {**MOD.empty_state(), "next_rotation_page": 9}
        fetch, calls = fetcher_for(
            {
                1: capture([paid_row("FRONT")]),
                9: capture([paid_row("OLD")]),
                10: capture([]),
                11: capture([paid_row("NEVER")]),
            }
        )
        _records, diag, next_state = MOD.collect_cycle(
            state,
            front_pages=1,
            rotation_pages=3,
            page_size=24,
            wait_ms=500,
            fetch_page=fetch,
        )
        self.assertEqual(calls, [1, 9, 10])
        self.assertTrue(diag["rotation_boundary_detected"])
        self.assertEqual(next_state["next_rotation_page"], 1)

    def test_capture_error_fails_before_any_state_mutation(self):
        state = {**MOD.empty_state(), "next_rotation_page": 7}
        original = dict(state)

        def bad_fetch(_url: str):
            return {"error": "TEST_FAILURE"}

        with self.assertRaises(RuntimeError):
            MOD.collect_cycle(
                state,
                front_pages=1,
                rotation_pages=1,
                page_size=24,
                wait_ms=500,
                fetch_page=bad_fetch,
            )
        self.assertEqual(state, original)

    def test_dry_run_is_memory_only_and_does_not_advance_cursor_file(self):
        fetch, _calls = fetcher_for(
            {
                1: capture([paid_row("A")]),
                2: capture([paid_row("B")]),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            result = MOD.run(
                state_path=state_path,
                commit=False,
                database_url="",
                front_pages=1,
                rotation_pages=2,
                page_size=24,
                wait_ms=500,
                fetch_page=fetch,
                observed_at="2026-08-30T08:00:00+00:00",
            )
            self.assertFalse(state_path.exists())
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["committed"])
        self.assertFalse(result["state_advanced"])
        self.assertEqual(result["prepared_sale_transactions"], 2)
        self.assertEqual(result["sale_transactions_stored_in_memory"], 2)
        self.assertEqual(result["sale_transactions_after_replay"], 2)
        self.assertEqual(result["duplicate_sale_replays"], 2)
        self.assertEqual(result["canonical_card_links"], 0)

    def test_provider_variant_surfaces_are_raw_evidence_not_exact_identity(self):
        record, reason = MOD._paid_record(paid_row("ATTR"))
        self.assertEqual(reason, "PAID_SOLD_EVIDENCE_READY")
        assert record is not None
        self.assertEqual(record["provider_attribute"], "Holo")
        built, build_reason = MOD.dry_run.build_p3_sale(
            record,
            observed_at="2026-08-30T08:00:00+00:00",
        )
        self.assertEqual(build_reason, "P3_SALE_READY_UNRESOLVED_IDENTITY")
        assert built is not None
        _raw, observation = built
        self.assertFalse(observation.exact_identity_eligible)
        claim_names = {claim.field_name for claim in observation.claims}
        self.assertNotIn("provider_attribute", claim_names)
        self.assertNotIn("finish", claim_names)
        self.assertIn("commercial_microvariant", observation.unresolved_dimensions)

    def test_safety_contract_keeps_v4_and_commerce_off(self):
        dry = MOD.safe_summary(commit=False)
        self.assertFalse(dry["durable_robot_kb_write"])
        self.assertTrue(dry["front_plus_rotation_strategy"])
        self.assertFalse(dry["unproven_sort_required"])
        self.assertFalse(dry["provider_variant_fields_are_exact_identity"])
        commit = MOD.safe_summary(commit=True)
        self.assertTrue(commit["durable_robot_kb_write"])
        self.assertTrue(commit["local_postgres_only"])
        self.assertFalse(commit["remote_cloud_write_allowed"])
        for key in (
            "v4_economic_use",
            "notification_sent",
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
        ):
            self.assertFalse(commit[key], key)

    def test_local_runner_has_bounded_cardova_readiness_retry_and_local_db_only(self):
        text = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertIn('waits=(5000 6500 8000)', text)
        self.assertIn("TARGET_CLOSED_API_RESPONSE_NOT_OBSERVED", text)
        self.assertIn('--commit', text)
        self.assertIn('RobotPokemonKB.local-postgres', text)
        self.assertIn('postgresql://robotpokemon_kb@127.0.0.1/robot_pokemon_kb', text)
        self.assertIn('cardova-sold.lock', text)
        self.assertNotIn('https://api.psacard.com', text)
        subprocess.run(["bash", "-n", str(RUNNER_PATH)], check=True)

    def test_launchagent_installer_is_pinned_separate_and_secret_free(self):
        text = INSTALLER_PATH.read_text(encoding="utf-8")
        self.assertIn('CODE_SHA="a2f1878186a8850d5a4c4763518a10ecfd16f2fc"', text)
        self.assertIn('com.robotpokemon.kb.cardova-sold', text)
        self.assertIn('{"Hour": 2, "Minute": 23}', text)
        self.assertIn('{"Hour": 8, "Minute": 23}', text)
        self.assertIn('{"Hour": 14, "Minute": 23}', text)
        self.assertIn('{"Hour": 20, "Minute": 23}', text)
        self.assertIn('"RunAtLoad": False', text)
        self.assertNotIn('PGPASSWORD', text)
        self.assertNotIn('security find-generic-password', text)
        self.assertIn('git -C "$REPO_ROOT" archive "$CODE_SHA"', text)
        subprocess.run(["bash", "-n", str(INSTALLER_PATH)], check=True)


if __name__ == "__main__":
    unittest.main()
