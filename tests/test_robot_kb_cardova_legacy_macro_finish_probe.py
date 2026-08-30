import importlib.util
from pathlib import Path
import unittest
from unittest import mock


PATH = Path("mac/robot-kb-local/robot_kb_cardova_legacy_macro_finish_probe.py")
SPEC = importlib.util.spec_from_file_location("cardova_legacy_macro_finish", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def macro_row():
    return {
        "source_native_record_id": "01ABC",
        "card_name_provider_claim": "Pikachu",
        "collector_number_provider_claim": "#001",
        "provider_set_label": "Basic",
        "grader": "PSA",
        "grade": "10",
        "tcgdex_card_id": "PMCG1-1",
        "tcgdex_set_id": "PMCG1",
        "tcgdex_local_id": "1",
        "pinned_source_path": "data-asia/PMCG/PMCG1/001.ts",
        "pinned_source_commit": MOD.SOURCE_COMMIT,
        "macro_identity_status": "EXACT",
        "macro_identity_exact": True,
        "microvariant_exact": False,
        "exact_identity_link_candidate": False,
    }


def variant_row(attribute=""):
    return {
        "source_native_record_id": "01ABC",
        "certification_number": "123456789",
        "card_name": "Pikachu",
        "collector_number": "#001",
        "language": "Japanese",
        "grader": "PSA",
        "grade": "10",
        "provider_attribute": attribute,
        "provider_attribute2": "",
        "provider_attribute3": "",
    }


def source_file(*finishes):
    variants = ",\n".join(f"    {{ type: '{finish}' }}" for finish in finishes)
    return f"""
import Set from '../PMCG1'

export default {{
  variants: [
{variants}
  ],
  set: Set,
}}
"""


class CardovaLegacyMacroFinishProbeTests(unittest.TestCase):
    def test_unique_pinned_source_finish_is_exact_without_provider_claim(self):
        row, reason = MOD.reconcile_record(
            macro_row(),
            variant_row(),
            source_fetcher=lambda _path: source_file("holo"),
        )
        self.assertEqual(reason, "FINISH_EXACT_UNIQUE_PINNED_SOURCE")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row["finish_exact"])
        self.assertEqual(row["finish"], "holo")
        self.assertEqual(row["commercial_axes_proven"], {"finish": "holo"})
        self.assertFalse(row["microvariant_exact"])
        self.assertFalse(row["exact_card_sale_evidence_ready"])
        self.assertFalse(row["sale_transaction_ready"])

    def test_exact_holo_provider_claim_can_select_holo_from_multi_finish_source(self):
        row, reason = MOD.reconcile_record(
            macro_row(),
            variant_row("Holo"),
            source_fetcher=lambda _path: source_file("normal", "holo"),
        )
        self.assertEqual(reason, "FINISH_EXACT_PROVIDER_SOURCE_CORROBORATED")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row["finish_exact"])
        self.assertEqual(row["finish"], "holo")
        self.assertEqual(row["source_finish_choices"], ["normal", "holo"])

    def test_multi_finish_source_without_provider_claim_remains_ambiguous(self):
        row, reason = MOD.reconcile_record(
            macro_row(),
            variant_row(),
            source_fetcher=lambda _path: source_file("normal", "holo"),
        )
        self.assertEqual(reason, "PINNED_SOURCE_FINISH_AMBIGUOUS")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertFalse(row["finish_exact"])
        self.assertEqual(row["finish"], "")
        self.assertFalse(row["microvariant_exact"])

    def test_holo_shiny_and_opaque_material_tokens_never_prove_finish(self):
        for attribute in ("Holo Shiny", "FA", "SR"):
            row, reason = MOD.reconcile_record(
                macro_row(),
                variant_row(attribute),
                source_fetcher=lambda _path: source_file("holo"),
            )
            self.assertEqual(reason, "PROVIDER_MATERIAL_TOKEN_UNCORROBORATED")
            self.assertIsNotNone(row)
            assert row is not None
            self.assertFalse(row["finish_exact"])
            self.assertFalse(row["microvariant_exact"])
            self.assertTrue(row["provider_opaque_material_tokens"])

    def test_provider_holo_conflicting_with_source_fails_closed(self):
        row, reason = MOD.reconcile_record(
            macro_row(),
            variant_row("Holo"),
            source_fetcher=lambda _path: source_file("normal"),
        )
        self.assertEqual(reason, "PROVIDER_FINISH_SOURCE_CONFLICT")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertFalse(row["finish_exact"])
        self.assertFalse(row["microvariant_exact"])

    def test_input_identity_and_source_pin_conflicts_are_rejected(self):
        bad_variant = variant_row()
        bad_variant["collector_number"] = "#999"
        row, reason = MOD.reconcile_record(
            macro_row(), bad_variant, source_fetcher=lambda _path: source_file("holo")
        )
        self.assertIsNone(row)
        self.assertEqual(reason, "INPUT_IDENTITY_CONFLICT")

        bad_commit = macro_row()
        bad_commit["pinned_source_commit"] = "moving-main"
        row, reason = MOD.reconcile_record(
            bad_commit, variant_row(), source_fetcher=lambda _path: source_file("holo")
        )
        self.assertIsNone(row)
        self.assertEqual(reason, "PINNED_SOURCE_COMMIT_CONFLICT")

        bad_path = macro_row()
        bad_path["pinned_source_path"] = "data-asia/PMCG/PMCG2/001.ts"
        row, reason = MOD.reconcile_record(
            bad_path, variant_row(), source_fetcher=lambda _path: source_file("holo")
        )
        self.assertIsNone(row)
        self.assertEqual(reason, "PINNED_SOURCE_COORDINATE_CONFLICT")

    def test_source_parser_requires_exact_set_import_and_known_finish_types(self):
        self.assertEqual(
            MOD.source_finish_choices(source_file("holo"), set_id="PMCG1"),
            ("holo",),
        )
        self.assertEqual(
            MOD.source_finish_choices(source_file("holo"), set_id="PMCG2"),
            (),
        )
        self.assertEqual(
            MOD.source_finish_choices(source_file("cosmos"), set_id="PMCG1"),
            (),
        )

    def test_run_requires_unique_variant_join_and_never_promotes_microvariant(self):
        duplicate = variant_row()
        summary = MOD.run_records(
            [macro_row()],
            [variant_row(), duplicate],
            max_records=10,
            source_fetcher=lambda _path: source_file("holo"),
        )
        self.assertEqual(summary["joined_records"], 0)
        self.assertEqual(summary["finish_exact_count"], 0)
        self.assertEqual(summary["blocked"], {"VARIANT_SURFACE_JOIN_NOT_UNIQUE": 1})
        self.assertEqual(summary["microvariant_exact_count"], 0)
        self.assertEqual(summary["exact_identity_link_candidate_count"], 0)

    def test_stored_variant_projection_preserves_only_needed_surfaces(self):
        stored = variant_row("Holo")
        stored["attribute2"] = "FA"
        stored["provider_attribute2"] = ""
        stored["secret"] = "never project me"
        projected = MOD._stored_variant_rows([stored])
        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0]["provider_attribute"], "Holo")
        self.assertEqual(projected[0]["provider_attribute2"], "FA")
        self.assertNotIn("secret", projected[0])

    def test_database_mode_reuses_one_read_only_snapshot_and_keeps_microvariant_unproven(self):
        stored = variant_row()
        selected = {
            "unresolved_sale_transactions_available": 237,
            "selected_records": 1,
            "db_read_blocked": {},
            "records": [stored],
        }
        registry_payload = {"sentinel": True}
        composed = {
            "macro_identity_exact_count": 1,
            "blocked": {},
            "records": [macro_row()],
        }
        with (
            mock.patch.object(
                MOD.recovery,
                "validate_local_database_url",
                return_value={"database_host": "127.0.0.1", "database_name": "robot_pokemon_kb"},
            ),
            mock.patch.object(
                MOD.recovery, "_read_unresolved_from_kb", return_value=selected
            ) as read_db,
            mock.patch.object(
                MOD.bounded_macro.registry, "run_records", return_value=registry_payload
            ) as run_registry,
            mock.patch.object(
                MOD.bounded_macro, "compose_registry_result", return_value=composed
            ),
        ):
            summary = MOD.run_database(
                "postgresql://robotpokemon_kb@127.0.0.1/robot_pokemon_kb",
                max_records=50,
                max_groups=20,
                min_distinct_dexids=2,
                source_fetcher=lambda _path: source_file("holo"),
            )
        read_db.assert_called_once()
        run_registry.assert_called_once_with(
            [stored], max_groups=20, min_distinct_dexids=2
        )
        self.assertEqual(summary["unresolved_sale_transactions_available"], 237)
        self.assertEqual(summary["macro_identity_exact_count"], 1)
        self.assertEqual(summary["finish_exact_count"], 1)
        self.assertEqual(summary["microvariant_exact_count"], 0)
        self.assertEqual(summary["exact_identity_link_candidate_count"], 0)

    def test_safety_summary_remains_read_only(self):
        summary = MOD.safe_summary()
        self.assertTrue(summary["database_read_only_transaction"])
        self.assertFalse(summary["provider_attribute_is_identity_proof_alone"])
        self.assertFalse(summary["source_coordinate_selected_by_provider_attribute"])
        self.assertFalse(summary["microvariant_exact"])
        for key in (
            "canonical_link_written",
            "robot_kb_write",
            "sale_transaction_stored",
            "sale_transaction_ready",
            "v4_economic_use",
            "notification_sent",
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
        ):
            self.assertFalse(summary[key], key)


if __name__ == "__main__":
    unittest.main()
