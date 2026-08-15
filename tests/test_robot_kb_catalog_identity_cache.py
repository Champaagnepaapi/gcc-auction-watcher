from __future__ import annotations

import unittest

from robot_kb.catalog_identity_cache import (
    AMBIGUOUS,
    DENOMINATOR_CONFLICT,
    DENOMINATOR_UNPROVEN,
    MATCHED,
    NO_MATCH,
    TCGdexMacroSnapshot,
    lookup_tcgdex_macro,
    store_tcgdex_macro_snapshot,
)
from robot_kb.repository import KnowledgeBase


T0 = "2026-08-15T18:00:00Z"
T1 = "2026-08-15T18:10:00Z"
T2 = "2026-08-15T18:20:00Z"


def snapshot(
    native_id: str = "base1-4",
    *,
    language: str = "en",
    set_id: str = "base1",
    set_name: str = "Base Set",
    name: str = "Charizard",
    local_id: str = "4",
    official: int | None = 102,
    observed_at: str = T0,
    variants=None,
) -> TCGdexMacroSnapshot:
    return TCGdexMacroSnapshot(
        source_native_id=native_id,
        language_code=language,
        provider_set_id=set_id,
        provider_set_name=set_name,
        provider_card_name=name,
        local_id=local_id,
        official_card_count=official,
        variants=variants,
        observed_at=observed_at,
    )


class TCGdexMacroIdentityCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kb = KnowledgeBase.open()

    def tearDown(self) -> None:
        self.kb.close()

    def lookup(self, **overrides):
        values = {
            "language_code": "en",
            "card_name": "Charizard",
            "set_name": "Base Set",
            "card_number": "4/102",
        }
        values.update(overrides)
        return lookup_tcgdex_macro(self.kb, **values)

    def test_exact_macro_round_trip_without_creating_microvariant_card(self):
        stored = store_tcgdex_macro_snapshot(
            self.kb,
            snapshot(variants={"holo": True, "firstEdition": True}),
        )

        result = self.lookup(card_number="004/102")

        self.assertTrue(result.matched)
        self.assertEqual(result.status, MATCHED)
        self.assertEqual(result.candidate.snapshot_id, stored)
        self.assertEqual(result.candidate.source_native_id, "base1-4")
        self.assertEqual(result.candidate.variants["holo"], True)
        self.assertEqual(
            self.kb.connection.execute("SELECT count(*) AS n FROM canonical_card").fetchone()["n"],
            0,
        )

    def test_consecutive_identical_payload_is_idempotent(self):
        first = store_tcgdex_macro_snapshot(self.kb, snapshot(observed_at=T0))
        second = store_tcgdex_macro_snapshot(self.kb, snapshot(observed_at=T1))

        self.assertEqual(first, second)
        self.assertEqual(
            self.kb.connection.execute(
                "SELECT count(*) AS n FROM catalog_identity_snapshot"
            ).fetchone()["n"],
            1,
        )

    def test_changed_then_reverted_payload_preserves_history_and_latest_truth(self):
        first = store_tcgdex_macro_snapshot(self.kb, snapshot(observed_at=T0))
        changed = store_tcgdex_macro_snapshot(
            self.kb,
            snapshot(set_id="base1-corrected", set_name="Base Set Corrected", observed_at=T1),
        )
        reverted = store_tcgdex_macro_snapshot(self.kb, snapshot(observed_at=T2))

        self.assertNotEqual(first, changed)
        self.assertNotEqual(changed, reverted)
        self.assertNotEqual(first, reverted)
        self.assertEqual(
            self.kb.connection.execute(
                "SELECT count(*) AS n FROM catalog_identity_snapshot"
            ).fetchone()["n"],
            3,
        )
        self.assertEqual(self.lookup().status, MATCHED)
        self.assertEqual(
            self.lookup(set_name="Base Set Corrected").status,
            NO_MATCH,
        )

    def test_latest_corrected_snapshot_supersedes_old_macro_key(self):
        store_tcgdex_macro_snapshot(self.kb, snapshot(observed_at=T0))
        store_tcgdex_macro_snapshot(
            self.kb,
            snapshot(set_id="base1-fixed", set_name="Corrected Base", observed_at=T1),
        )

        self.assertEqual(self.lookup().status, NO_MATCH)
        corrected = self.lookup(set_name="Corrected Base")
        self.assertTrue(corrected.matched)
        self.assertEqual(corrected.candidate.provider_set_id, "base1-fixed")

    def test_two_latest_native_ids_for_same_macro_are_ambiguous(self):
        store_tcgdex_macro_snapshot(self.kb, snapshot("base1-4"))
        store_tcgdex_macro_snapshot(self.kb, snapshot("other-4"))

        result = self.lookup()

        self.assertEqual(result.status, AMBIGUOUS)
        self.assertTrue(result.ambiguous)
        self.assertEqual(
            [candidate.source_native_id for candidate in result.candidates],
            ["base1-4", "other-4"],
        )

    def test_denominator_conflict_fails_closed(self):
        store_tcgdex_macro_snapshot(self.kb, snapshot(official=102))

        result = self.lookup(card_number="4/130")

        self.assertEqual(result.status, DENOMINATOR_CONFLICT)
        self.assertFalse(result.matched)

    def test_unknown_denominator_fails_closed_even_when_macro_matches(self):
        store_tcgdex_macro_snapshot(self.kb, snapshot(official=None))

        result = self.lookup(card_number="4/102")

        self.assertEqual(result.status, DENOMINATOR_UNPROVEN)
        self.assertFalse(result.matched)

    def test_language_is_part_of_identity(self):
        store_tcgdex_macro_snapshot(
            self.kb,
            snapshot(
                native_id="base1-fr-4",
                language="fr",
                set_name="Set de Base",
                name="Dracaufeu",
            ),
        )

        self.assertEqual(self.lookup().status, NO_MATCH)
        fr = self.lookup(
            language_code="fr",
            card_name="Dracaufeu",
            set_name="Set de Base",
        )
        self.assertTrue(fr.matched)
        self.assertEqual(fr.candidate.language_code, "fr")

    def test_macro_cache_never_uses_variants_to_unblock_identity(self):
        store_tcgdex_macro_snapshot(
            self.kb,
            snapshot(variants={"firstEdition": True, "holo": True, "reverse": False}),
        )

        result = self.lookup()

        self.assertTrue(result.matched)
        self.assertEqual(result.candidate.variants["firstEdition"], True)
        # Variant metadata is returned only as catalogue evidence. The cache has
        # no API that creates a canonical microvariant card or declares a finish.
        self.assertEqual(
            self.kb.connection.execute("SELECT count(*) AS n FROM canonical_card").fetchone()["n"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
