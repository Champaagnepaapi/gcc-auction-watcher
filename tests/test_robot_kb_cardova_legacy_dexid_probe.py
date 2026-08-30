from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
for candidate in (ROOT, LOCAL):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_legacy_dexid_probe as probe


def paid_record(**updates):
    row = {
        "source": "cardova_public_past_auction",
        "source_native_record_id": "01LEGACY",
        "provider_sale_status": "PAID_COMPLETED",
        "provider_sale_status_proven": True,
        "sale_evidence_ready": True,
        "currency": "JPY",
        "currency_proven": True,
        "final_bid_jpy": 100000,
        "auction_end_at_utc": "2026-01-01T00:00:00+00:00",
        "certification_number": "12345678",
        "card_name": "Weedle",
        "set_name": "Pokemon TCG: Japanese neo 2 Crossing the Ruins…",
        "collector_number": "#013",
        "language": "Japanese",
        "grader": "PSA",
        "grade": "10",
    }
    row.update(updates)
    return row


def source(set_id="neo2", dex_id=13):
    return f'''import {{ Card }} from "../../../interfaces"\nimport Set from "../{set_id}"\nconst card: Card = {{\n  set: Set,\n  category: "Pokemon",\n  dexId: [{dex_id}],\n}}\nexport default card\n'''


class Fetcher:
    def __init__(self, text=None, error=None):
        self.text = text or source()
        self.error = error
        self.requests = 0
        self.paths = []

    def __call__(self, path):
        self.requests += 1
        self.paths.append(path)
        if self.error is not None:
            raise self.error
        return self.text


class CardovaLegacyDexIdProbeTests(unittest.TestCase):
    def test_structural_neo_mapping_is_narrow(self):
        for label, expected in (
            ("Pokemon TCG: Japanese neo 1 Genesis", "neo1"),
            ("Pokemon TCG: Japanese neo 2 Crossing the Ruins…", "neo2"),
            ("Pokemon TCG: Japanese neo 3 Awakening Legends", "neo3"),
            ("Pokemon TCG: Japanese neo 4 Darkness, and to Light...", "neo4"),
        ):
            with self.subTest(label=label):
                self.assertEqual(probe.structural_legacy_set_id(label)[0], expected)
        for label in (
            "Pokemon TCG: Japanese neo Premium File 2",
            "Pokemon TCG: Japanese Fossil",
            "Pokemon TCG: Japanese Jungle",
            "Crossing the Ruins…",
            "",
        ):
            with self.subTest(label=label):
                self.assertEqual(probe.structural_legacy_set_id(label)[0], "")

    def test_numeric_candidate_accepts_only_bounded_plain_number(self):
        self.assertEqual(probe.numeric_dex_candidate("#013")[0], 13)
        self.assertEqual(probe.numeric_dex_candidate("200")[0], 200)
        for value in ("294/XY-P", "L-P", "♡J", "", "9999"):
            with self.subTest(value=value):
                self.assertIsNone(probe.numeric_dex_candidate(value)[0])

    def test_unique_set_dexid_candidate_is_source_pinned_but_not_exact(self):
        fetcher = Fetcher()
        row, reason = probe.probe_record(
            paid_record(),
            dex_searcher=lambda dex_id: [
                {"id": "other-002"},
                {"id": "neo2-002"},
            ],
            source_fetcher=fetcher,
        )
        self.assertEqual(reason, "SOURCE_PINNED_SET_DEXID_UNIQUE_CANDIDATE_ONLY")
        self.assertIsNotNone(row)
        self.assertEqual(row["structural_set_id"], "neo2")
        self.assertEqual(row["dex_id_candidate"], 13)
        self.assertEqual(row["tcgdex_card_id_candidate"], "neo2-002")
        self.assertEqual(row["pinned_source_path"], "data-asia/neo/neo2/002.ts")
        self.assertTrue(row["pinned_source_set_dexid_proven"])
        self.assertFalse(row["provider_numeric_semantics_proven"])
        self.assertFalse(row["macro_identity_exact"])
        self.assertFalse(row["exact_identity_link_candidate"])

    def test_zero_and_multiple_candidates_fail_closed(self):
        fetcher = Fetcher()
        row, reason = probe.probe_record(
            paid_record(),
            dex_searcher=lambda dex_id: [{"id": "neo3-001"}],
            source_fetcher=fetcher,
        )
        self.assertIsNone(row)
        self.assertEqual(reason, "SET_DEXID_CANDIDATE_NOT_FOUND")
        self.assertEqual(fetcher.requests, 0)

        row, reason = probe.probe_record(
            paid_record(),
            dex_searcher=lambda dex_id: [{"id": "neo2-001"}, {"id": "neo2-002"}],
            source_fetcher=fetcher,
        )
        self.assertIsNone(row)
        self.assertEqual(reason, "SET_DEXID_CANDIDATE_AMBIGUOUS")
        self.assertEqual(fetcher.requests, 0)

    def test_source_must_prove_exact_set_and_dexid(self):
        for text in (
            source(set_id="neo3", dex_id=13),
            source(set_id="neo2", dex_id=14),
            'import Set from "../neo2"\nconst card = { category: "Trainer", dexId: [13] }',
        ):
            with self.subTest(text=text):
                row, reason = probe.probe_record(
                    paid_record(),
                    dex_searcher=lambda dex_id: [{"id": "neo2-002"}],
                    source_fetcher=Fetcher(text=text),
                )
                self.assertIsNone(row)
                self.assertEqual(reason, "PINNED_SOURCE_SET_DEXID_CONFLICT")

    def test_provider_failure_is_fail_visible(self):
        result = probe.run_records(
            [paid_record()],
            dex_searcher=lambda dex_id: (_ for _ in ()).throw(
                probe.LegacyDexProviderError("TCGDEX_DEX_SEARCH_HTTP_503")
            ),
            source_fetcher=Fetcher(),
        )
        self.assertEqual(result["source_pinned_unique_dexid_candidate_count"], 0)
        self.assertEqual(result["blocked"], {"TCGDEX_DEX_SEARCH_HTTP_503": 1})

    def test_summary_never_promotes_candidate_or_writes(self):
        summary = probe.safe_summary()
        self.assertTrue(summary["database_read_only_transaction"])
        self.assertTrue(summary["dexid_used_as_retrieval_candidate_only"])
        self.assertFalse(summary["provider_numeric_semantics_proven"])
        for key in (
            "provider_name_translation_assumed",
            "fuzzy_matching",
            "macro_identity_exact",
            "microvariant_exact",
            "canonical_link_written",
            "robot_kb_write",
            "v4_economic_use",
            "notification_sent",
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
        ):
            self.assertIs(summary[key], False, key)


if __name__ == "__main__":
    unittest.main()
