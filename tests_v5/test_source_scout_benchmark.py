import unittest

from v5.models import CardIdentity
from v5.source_scout_benchmark import (
    CMAPI_CALL_CAP,
    CMAPI_REMAINING_BUFFER,
    CMAPI_TOTAL_CAP,
    SafeClient,
    candidate_identity,
    language_status,
    number_ok,
    variant_status,
)


class SourceScoutIdentityTests(unittest.TestCase):
    def setUp(self):
        self.base = CardIdentity(
            game="Pokémon TCG",
            card_name="Charizard ex",
            set="Obsidian Flames",
            card_number="125/197",
            language="English",
            finish="Holofoil",
        )

    def test_exact_identity_requires_name_set_and_number(self):
        self.assertEqual(
            candidate_identity(
                self.base,
                name="Charizard ex",
                set_name="Obsidian Flames",
                number="125/197",
            ),
            "EXACT",
        )
        self.assertEqual(
            candidate_identity(
                self.base,
                name="Charizard ex",
                set_name=None,
                number="125/197",
            ),
            "INSUFFICIENT",
        )

    def test_identity_mismatch_is_not_rescued_by_name_only(self):
        self.assertEqual(
            candidate_identity(
                self.base,
                name="Charizard ex",
                set_name="151",
                number="125/197",
            ),
            "MISMATCH",
        )
        self.assertEqual(
            candidate_identity(
                self.base,
                name="Charizard ex",
                set_name="Obsidian Flames",
                number="126/197",
            ),
            "MISMATCH",
        )

    def test_denominator_enrichment_is_compatible_but_conflict_is_not(self):
        self.assertTrue(number_ok("125", "125/197"))
        self.assertTrue(number_ok("125/197", "125"))
        self.assertFalse(number_ok("125/197", "125/198"))

    def test_finish_and_language_are_measured_separately(self):
        self.assertEqual(variant_status(self.base, ["Holofoil"]), "EXACT")
        self.assertEqual(variant_status(self.base, ["Reverse Holofoil"]), "MISMATCH")
        self.assertEqual(language_status(self.base, ["English"]), "EXACT")
        self.assertEqual(language_status(self.base, ["French"]), "MISMATCH")


class SourceScoutSafetyTests(unittest.TestCase):
    def test_safe_client_fails_closed_when_call_budget_is_zero(self):
        client = SafeClient("test", call_cap=0)
        response, payload = client.request("GET", "https://example.invalid")
        self.assertIsNone(response)
        self.assertIsNone(payload)
        self.assertTrue(client.runtime.blocked)
        self.assertEqual(client.runtime.calls, 0)

    def test_cmapi_budget_stays_well_below_paid_threshold(self):
        self.assertLessEqual(CMAPI_CALL_CAP, 30)
        self.assertGreaterEqual(CMAPI_REMAINING_BUFFER, 30)
        self.assertLessEqual(CMAPI_TOTAL_CAP, 30_000_000)


if __name__ == "__main__":
    unittest.main()
