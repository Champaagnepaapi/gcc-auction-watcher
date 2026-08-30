import importlib.util
from pathlib import Path
import unittest
from unittest import mock


PATH = Path("mac/robot-kb-local/robot_kb_cardova_legacy_macro_finish_probe.py")
SPEC = importlib.util.spec_from_file_location("cardova_legacy_macro_finish", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)

NO_RARITY_PATH = Path(
    "mac/robot-kb-local/robot_kb_cardova_no_rarity_printing_probe.py"
)
NO_RARITY_SPEC = importlib.util.spec_from_file_location(
    "cardova_no_rarity_printing", NO_RARITY_PATH
)
NO_RARITY = importlib.util.module_from_spec(NO_RARITY_SPEC)
assert NO_RARITY_SPEC.loader is not None
NO_RARITY_SPEC.loader.exec_module(NO_RARITY)


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


def no_rarity_finish_row(
    *,
    name="Sandshrew",
    provider_number="#027",
    source_finishes=("normal",),
    token="no rarity original print",
):
    return {
        "source_native_record_id": "01NO-RARITY",
        "card_name_provider_claim": name,
        "collector_number_provider_claim": provider_number,
        "provider_set_label": NO_RARITY.BASIC_PROVIDER_SET,
        "grader": "PSA",
        "grade": "9",
        "tcgdex_card_id": "PMCG1-051",
        "tcgdex_set_id": NO_RARITY.BASIC_TCGDEX_SET,
        "tcgdex_local_id": "051",
        "pinned_source_path": "data-asia/PMCG/PMCG1/051.ts",
        "pinned_source_commit": NO_RARITY.SOURCE_COMMIT,
        "source_finish_choices": list(source_finishes),
        "provider_finish_state": "OPAQUE_MATERIAL",
        "provider_finish_claim": "",
        "provider_opaque_material_tokens": [token],
        "finish_exact": False,
        "finish": "",
        "finish_proof_reason": "PROVIDER_MATERIAL_TOKEN_UNCORROBORATED",
        "commercial_axes_proven": {},
        "macro_identity_status": "EXACT",
        "macro_identity_exact": True,
        "microvariant_exact": False,
        "exact_identity_link_candidate": False,
        "exact_card_sale_evidence_ready": False,
        "sale_transaction_ready": False,
        "v4_economic_use": False,
    }


def no_rarity_html(*rows):
    body = "".join(
        f"<tr><td>{name}</td><td>{number}</td><td>1.00</td></tr>"
        for name, number in rows
    )
    return (
        "<html><body>"
        "<h1>1996 Pokemon Japanese Basic No Rarity Symbol Set Checklist</h1>"
        f"<table>{body}</table>"
        "</body></html>"
    )


def finish_payload(*rows):
    return {
        "unresolved_sale_transactions_available": 244,
        "selected_records": 244,
        "macro_identity_exact_count": len(rows),
        "macro_blocked": {},
        "records": list(rows),
    }


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


class CardovaNoRarityPrintingProbeTests(unittest.TestCase):
    def test_exact_no_rarity_psa_row_proves_printing_but_not_edition_or_microvariant(self):
        row = no_rarity_finish_row()
        summary = NO_RARITY.run_records(
            finish_payload(row),
            psa_fetcher=lambda _url: no_rarity_html(("SANDSHREW", "27")),
            pacing_seconds=0,
        )
        self.assertEqual(summary["no_rarity_candidates"], 1)
        self.assertEqual(summary["psa_no_rarity_rows_proven"], 1)
        self.assertEqual(summary["printing_exact_count"], 1)
        self.assertEqual(summary["finish_exact_count"], 1)
        proven = summary["records"][0]
        self.assertEqual(proven["printing"], "no_rarity_symbol")
        self.assertTrue(proven["printing_exact"])
        self.assertEqual(proven["finish"], "normal")
        self.assertTrue(proven["finish_exact"])
        self.assertFalse(proven["edition_exact"])
        self.assertEqual(proven["edition"], "")
        self.assertFalse(proven["no_rarity_is_first_edition"])
        self.assertFalse(proven["provider_original_print_wording_proven"])
        self.assertFalse(proven["microvariant_exact"])
        self.assertFalse(proven["exact_identity_link_candidate"])
        self.assertFalse(proven["sale_transaction_ready"])

    def test_provider_token_must_be_exact_and_never_uses_substring_semantics(self):
        for token in (
            "No Rarity Symbol",
            "No Rarity Original Print First Edition",
            "Original Print",
        ):
            with self.subTest(token=token):
                fetch = mock.Mock(side_effect=AssertionError("must not fetch PSA"))
                summary = NO_RARITY.run_records(
                    finish_payload(no_rarity_finish_row(token=token)),
                    psa_fetcher=fetch,
                    pacing_seconds=0,
                )
                self.assertEqual(summary["no_rarity_candidates"], 0)
                self.assertEqual(summary["printing_exact_count"], 0)
                fetch.assert_not_called()

    def test_psa_name_number_mismatch_fails_closed(self):
        summary = NO_RARITY.run_records(
            finish_payload(no_rarity_finish_row()),
            psa_fetcher=lambda _url: no_rarity_html(("SANDSHREW", "28")),
            pacing_seconds=0,
        )
        self.assertEqual(summary["psa_no_rarity_rows_proven"], 0)
        self.assertEqual(summary["printing_exact_count"], 0)
        self.assertEqual(summary["finish_exact_count"], 0)
        self.assertEqual(
            summary["blocked"], {"PSA_NO_RARITY_NAME_NUMBER_NOT_FOUND": 1}
        )

    def test_printing_can_be_exact_while_finish_remains_ambiguous(self):
        row = no_rarity_finish_row(source_finishes=("normal", "holo"))
        summary = NO_RARITY.run_records(
            finish_payload(row),
            psa_fetcher=lambda _url: no_rarity_html(("SANDSHREW", "27")),
            pacing_seconds=0,
        )
        self.assertEqual(summary["printing_exact_count"], 1)
        self.assertEqual(summary["finish_exact_count"], 0)
        proven = summary["records"][0]
        self.assertEqual(proven["commercial_axes_proven"], {"printing": "no_rarity_symbol"})
        self.assertFalse(proven["microvariant_exact"])

    def test_psa_403_opens_fail_visible_circuit_without_promotion(self):
        def blocked(_url):
            raise NO_RARITY.NoRarityProofError("PSA_NO_RARITY_HTTP_403")

        summary = NO_RARITY.run_records(
            finish_payload(no_rarity_finish_row()),
            psa_fetcher=blocked,
            pacing_seconds=0,
        )
        self.assertTrue(summary["psa_no_rarity_circuit_open"])
        self.assertEqual(summary["psa_no_rarity_rows_proven"], 0)
        self.assertEqual(summary["blocked"], {"PSA_NO_RARITY_HTTP_403": 1})
        self.assertEqual(summary["printing_exact_count"], 0)

    def test_database_mode_composes_existing_finish_probe_without_writes(self):
        inherited = finish_payload(no_rarity_finish_row())
        inherited.update(
            {
                "database_scope": "LOCAL_MAC_POSTGRES_READ_ONLY",
                "database_host_class": "LOOPBACK",
                "database_name": "robot_pokemon_kb",
                "db_read_blocked": {},
            }
        )
        with mock.patch.object(
            NO_RARITY.finish_probe, "run_database", return_value=inherited
        ) as run_finish:
            summary = NO_RARITY.run_database(
                "postgresql://robotpokemon_kb@127.0.0.1/robot_pokemon_kb",
                max_records=500,
                max_groups=20,
                min_distinct_dexids=2,
                timeout_seconds=4.0,
                source_fetcher=lambda _path: source_file("normal"),
                psa_fetcher=lambda _url: no_rarity_html(("SANDSHREW", "27")),
                pacing_seconds=0,
            )
        run_finish.assert_called_once()
        self.assertEqual(summary["database_scope"], "LOCAL_MAC_POSTGRES_READ_ONLY")
        self.assertEqual(summary["printing_exact_count"], 1)
        self.assertEqual(summary["microvariant_exact_count"], 0)
        self.assertEqual(summary["exact_identity_link_candidate_count"], 0)

    def test_safety_summary_never_converts_no_rarity_to_first_edition_or_write(self):
        summary = NO_RARITY.safe_summary()
        self.assertTrue(summary["database_read_only_transaction"])
        self.assertFalse(summary["provider_no_rarity_claim_is_identity_proof_alone"])
        self.assertTrue(summary["psa_checklist_can_prove_printing_only"])
        self.assertFalse(summary["no_rarity_is_first_edition"])
        self.assertFalse(summary["provider_original_print_wording_proven"])
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
