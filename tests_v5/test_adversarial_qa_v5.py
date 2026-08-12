from __future__ import annotations

import unittest

from v5.market_values.gcc_history.identity import match_identity
from v5.market_values.gcc_history.models import CanonicalCollectible, MatchClass


class AdversarialQAV5Tests(unittest.TestCase):
    """Red Team regressions and boundary tests for GCC history matching."""

    def test_strong_match_vulnerability(self):
        """Red Team regression: missing target discriminator evidence must NEVER

        prove parity with a premium candidate or result in STRONG_MATCH.
        """
        target = CanonicalCollectible(
            card_name="Charizard",
            set_name="Base Set",
            card_number="4/102",
            language="English",
            first_edition=None,
            finish=None,
            special_print=None,
        )
        premium_candidate = CanonicalCollectible(
            card_name="Charizard",
            set_name="Base Set",
            card_number="4/102",
            language="English",
            first_edition=True,
            finish="Holo",
            special_print="Shadowless",
        )
        result = match_identity(target, premium_candidate)
        self.assertNotEqual(
            result.match_class,
            MatchClass.STRONG_MATCH,
            "A target with missing discriminator evidence must NEVER STRONG_MATCH a premium candidate",
        )
        self.assertNotEqual(
            result.match_class,
            MatchClass.EXACT_MATCH,
            "A target with missing discriminator evidence must NEVER EXACT_MATCH a premium candidate",
        )
        self.assertEqual(result.match_class, MatchClass.AMBIGUOUS)
        self.assertIn("target_first_edition", result.missing_fields)
        self.assertIn("target_finish", result.missing_fields)
        self.assertIn("target_special_print", result.missing_fields)

    def test_first_edition_candidate_only_fails_closed_to_ambiguous(self):
        target = CanonicalCollectible("Charizard", "Base Set", "4/102", "English", first_edition=None)
        candidate = CanonicalCollectible("Charizard", "Base Set", "4/102", "English", first_edition=True)
        result = match_identity(target, candidate)
        self.assertEqual(result.match_class, MatchClass.AMBIGUOUS)
        self.assertIn("target_first_edition", result.missing_fields)

    def test_finish_candidate_only_fails_closed_to_ambiguous(self):
        target = CanonicalCollectible("Charizard", "Base Set", "4/102", "English", finish=None)
        candidate = CanonicalCollectible("Charizard", "Base Set", "4/102", "English", finish="Holo")
        result = match_identity(target, candidate)
        self.assertEqual(result.match_class, MatchClass.AMBIGUOUS)
        self.assertIn("target_finish", result.missing_fields)

    def test_special_print_candidate_only_fails_closed_to_ambiguous(self):
        target = CanonicalCollectible("Charizard", "Base Set", "4/102", "English", special_print=None)
        candidate = CanonicalCollectible("Charizard", "Base Set", "4/102", "English", special_print="Shadowless")
        result = match_identity(target, candidate)
        self.assertEqual(result.match_class, MatchClass.AMBIGUOUS)
        self.assertIn("target_special_print", result.missing_fields)

    def test_stamped_candidate_only_fails_closed_to_ambiguous(self):
        target = CanonicalCollectible("Pikachu", "Jungle", "60/64", "English", stamped=None)
        candidate = CanonicalCollectible("Pikachu", "Jungle", "60/64", "English", stamped="W Stamp")
        result = match_identity(target, candidate)
        self.assertEqual(result.match_class, MatchClass.AMBIGUOUS)
        self.assertIn("target_stamped", result.missing_fields)

    def test_promo_candidate_only_fails_closed_to_ambiguous(self):
        target = CanonicalCollectible("Mewtwo", "Promo", "14", "English", promo=None)
        candidate = CanonicalCollectible("Mewtwo", "Promo", "14", "English", promo=True)
        result = match_identity(target, candidate)
        self.assertEqual(result.match_class, MatchClass.AMBIGUOUS)
        self.assertIn("target_promo", result.missing_fields)

    def test_variant_candidate_only_fails_closed_to_ambiguous(self):
        target = CanonicalCollectible("Pikachu", "Jungle", "60/64", "English", variant=None)
        candidate = CanonicalCollectible("Pikachu", "Jungle", "60/64", "English", variant="Staff")
        result = match_identity(target, candidate)
        self.assertEqual(result.match_class, MatchClass.AMBIGUOUS)
        self.assertIn("target_variant", result.missing_fields)

    def test_explicit_parity_is_exact_match(self):
        target = CanonicalCollectible("Charizard", "Base Set", "4/102", "English", first_edition=True, finish="Holo")
        candidate = CanonicalCollectible("Charizard", "Base Set", "4/102", "English", first_edition=True, finish="Holo")
        result = match_identity(target, candidate)
        self.assertEqual(result.match_class, MatchClass.EXACT_MATCH)

    def test_explicit_conflict_is_rejected(self):
        target = CanonicalCollectible("Charizard", "Base Set", "4/102", "English", first_edition=False)
        candidate = CanonicalCollectible("Charizard", "Base Set", "4/102", "English", first_edition=True)
        result = match_identity(target, candidate)
        self.assertEqual(result.match_class, MatchClass.REJECTED)
        self.assertIn("first_edition", result.conflicts)

    def test_strong_match_only_for_partial_macro_with_no_candidate_only_discriminators(self):
        target = CanonicalCollectible(
            card_name="Charizard",
            set_name=None,
            card_number="4/102",
            language="English",
            first_edition=False,
            finish="Holo",
        )
        candidate = CanonicalCollectible(
            card_name="Charizard",
            set_name="Base Set",
            card_number="4/102",
            language="English",
            first_edition=False,
            finish="Holo",
        )
        result = match_identity(target, candidate)
        self.assertEqual(result.match_class, MatchClass.STRONG_MATCH)


if __name__ == "__main__":
    unittest.main()
