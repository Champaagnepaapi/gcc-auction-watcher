from __future__ import annotations

import unittest

from robot_kb.repository import KnowledgeBase
from robot_kb.postgres import POSTGRES_MIGRATION_DIRECTORY, _migration_catalog


class PrintRunRaritySymbolRegistryTests(unittest.TestCase):
    def test_sqlite_registry_exposes_both_exact_print_states(self):
        with KnowledgeBase.open(":memory:") as kb:
            rows = kb.connection.execute(
                """
                SELECT code, label
                FROM variant_value
                WHERE dimension_id = 'vdim_print_run'
                ORDER BY code
                """
            ).fetchall()
            values = {row["code"]: row["label"] for row in rows}
            self.assertEqual(
                values["NO_RARITY_SYMBOL"],
                "No rarity symbol",
            )
            self.assertEqual(
                values["RARITY_SYMBOL_PRESENT"],
                "Rarity symbol present",
            )
            self.assertIn("UNKNOWN", values)

    def test_print_run_states_keep_same_finish_as_distinct_profiles(self):
        with KnowledgeBase.open(":memory:") as kb:
            no_rarity = kb.create_variant_profile(
                {
                    "finish": "HOLO",
                    "print_run": "NO_RARITY_SYMBOL",
                }
            )
            with_symbol = kb.create_variant_profile(
                {
                    "finish": "HOLO",
                    "print_run": "RARITY_SYMBOL_PRESENT",
                }
            )
            self.assertNotEqual(no_rarity, with_symbol)

    def test_no_rarity_print_run_does_not_imply_edition(self):
        with KnowledgeBase.open(":memory:") as kb:
            profile = kb.create_variant_profile(
                {
                    "finish": "HOLO",
                    "print_run": "NO_RARITY_SYMBOL",
                }
            )
            rows = kb.connection.execute(
                """
                SELECT dimension.code AS dimension_code, value.code AS value_code
                FROM variant_assignment AS assignment
                JOIN variant_dimension AS dimension
                  ON dimension.id = assignment.dimension_id
                JOIN variant_value AS value
                  ON value.id = assignment.value_id
                WHERE assignment.profile_id = ?
                ORDER BY dimension.code
                """,
                (profile,),
            ).fetchall()
            assignments = {
                row["dimension_code"]: row["value_code"]
                for row in rows
            }
            self.assertEqual(
                assignments,
                {
                    "finish": "HOLO",
                    "print_run": "NO_RARITY_SYMBOL",
                },
            )
            self.assertNotIn("edition_stamp", assignments)

    def test_postgres_forward_migration_has_exact_parity(self):
        catalog = _migration_catalog()
        self.assertEqual(list(catalog), [1, 2, 3])
        script = (
            POSTGRES_MIGRATION_DIRECTORY
            / "0003_print_run_rarity_symbol.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("'vdim_print_run'", script)
        self.assertIn("'NO_RARITY_SYMBOL'", script)
        self.assertIn("'RARITY_SYMBOL_PRESENT'", script)
        self.assertNotIn("FIRST_EDITION", script)
        self.assertNotIn("NO_FIRST_EDITION_STAMP", script)


if __name__ == "__main__":
    unittest.main()
