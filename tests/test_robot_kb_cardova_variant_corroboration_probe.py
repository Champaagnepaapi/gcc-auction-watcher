import importlib.util
from pathlib import Path
import unittest


PATH = Path("mac/robot-kb-local/robot_kb_cardova_variant_corroboration_probe.py")
SPEC = importlib.util.spec_from_file_location("cardova_variant_corroboration", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def official_row():
    return {
        "source_native_record_id": "01ABC",
        "certification_number": "123456789",
        "card_name": "Pikachu",
        "collector_number": "#279/XY-P",
        "language": "Japanese",
        "grader": "PSA",
        "grade": "10",
        "printed_namespace": "XY-P",
        "official_card_id": "32387",
        "official_detail_url": "https://www.pokemon-card.com/card-search/details.php/card/32387",
        "macro_identity_status": "EXACT",
        "official_catalog_entry_unique": True,
    }


def variant_row(attribute="Holo"):
    return {
        "source_native_record_id": "01ABC",
        "certification_number": "123456789",
        "collector_number": "#279/XY-P",
        "japanese_structured_promo_candidate": True,
        "provider_attribute": attribute,
        "provider_attribute2": "",
        "provider_attribute3": "",
    }


def holo_html():
    return """
    <html><body>
      <a href="/card-search/index.php?pg=10526&regulation_detail=all">
        ポケモンカードゲーム 20th アニバーサリーフェスタ オリジナルキラカード
      </a>
    </body></html>
    """


class CardovaVariantCorroborationProbeTests(unittest.TestCase):
    def test_provider_attribute_parser_never_hides_extra_material_tokens(self):
        self.assertEqual(
            MOD._provider_attribute_state("Holo"),
            ("EXPLICIT_HOLO_ONLY", "holo", ()),
        )
        self.assertEqual(
            MOD._provider_attribute_state("Holo Shiny"),
            ("EXPLICIT_HOLO_PLUS_MATERIAL", "holo", ("shiny",)),
        )
        self.assertEqual(
            MOD._provider_attribute_state("FA"),
            ("OPAQUE_OR_NON_FINISH", "", ("fa",)),
        )
        self.assertEqual(
            MOD._provider_attribute_state("SR"),
            ("OPAQUE_OR_NON_FINISH", "", ("sr",)),
        )

    def test_official_holo_label_must_be_on_safe_official_anchor(self):
        html = """
        <a href="/card-search/index.php?pg=1">オリジナルキラカード</a>
        <a href="https://evil.example/x">キラカード</a>
        <div>キラカード</div>
        """
        self.assertEqual(MOD.official_holo_labels(html), ("オリジナルキラカード",))

    def test_exact_holo_claim_plus_official_holo_label_only_proves_partial_axes(self):
        row, reason = MOD.reconcile_record(
            official_row(), variant_row("Holo"), detail_fetcher=lambda _card_id: holo_html()
        )
        self.assertEqual(reason, "PARTIAL_OFFICIAL_PROVIDER_FINISH_CORROBORATED")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row["finish_holo_corroborated"])
        self.assertEqual(row["commercial_axes_proven"], {"printing": "promo", "finish": "holo"})
        self.assertFalse(row["microvariant_exact"])
        self.assertFalse(row["exact_card_sale_evidence_ready"])
        self.assertFalse(row["sale_transaction_ready"])
        self.assertIn("edition_applicability", row["remaining_unproven_axes"])
        self.assertIn("special_finish_applicability", row["remaining_unproven_axes"])
        self.assertIn("variant_applicability", row["remaining_unproven_axes"])

    def test_holo_shiny_remains_blocked_even_when_official_page_says_holo(self):
        row, reason = MOD.reconcile_record(
            official_row(), variant_row("Holo Shiny"), detail_fetcher=lambda _card_id: holo_html()
        )
        self.assertEqual(reason, "PARTIAL_PROVIDER_MATERIAL_TOKEN_UNCORROBORATED")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertFalse(row["finish_holo_corroborated"])
        self.assertEqual(row["provider_opaque_material_tokens"], ["shiny"])
        self.assertFalse(row["microvariant_exact"])

    def test_fa_and_sr_never_become_finish_or_exact_microvariant(self):
        for attribute in ("FA", "SR"):
            row, reason = MOD.reconcile_record(
                official_row(), variant_row(attribute), detail_fetcher=lambda _card_id: holo_html()
            )
            self.assertEqual(reason, "PARTIAL_PROVIDER_MATERIAL_TOKEN_UNCORROBORATED")
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row["provider_finish_claim"], "")
            self.assertFalse(row["finish_holo_corroborated"])
            self.assertFalse(row["microvariant_exact"])

    def test_identity_join_and_macro_uniqueness_fail_closed(self):
        bad = variant_row()
        bad["certification_number"] = "999999999"
        row, reason = MOD.reconcile_record(
            official_row(), bad, detail_fetcher=lambda _card_id: holo_html()
        )
        self.assertIsNone(row)
        self.assertEqual(reason, "INPUT_IDENTITY_CONFLICT")

        off = official_row()
        off["official_catalog_entry_unique"] = False
        row, reason = MOD.reconcile_record(
            off, variant_row(), detail_fetcher=lambda _card_id: holo_html()
        )
        self.assertIsNone(row)
        self.assertEqual(reason, "OFFICIAL_COORDINATE_NOT_UNIQUE")

    def test_run_counts_finish_corroboration_without_promoting_microvariant(self):
        summary = MOD.run(
            [official_row()],
            [variant_row()],
            max_records=1,
            detail_fetcher=lambda _card_id: holo_html(),
        )
        self.assertEqual(summary["joined_records"], 1)
        self.assertEqual(summary["promo_printing_proven_count"], 1)
        self.assertEqual(summary["finish_holo_corroborated_count"], 1)
        self.assertEqual(summary["exact_microvariant_count"], 0)
        self.assertEqual(summary["blocked"], {})

    def test_safety_summary_remains_read_only(self):
        summary = MOD.safe_summary()
        self.assertFalse(summary["provider_attribute_is_identity_proof_alone"])
        self.assertFalse(summary["premium_variant_from_provider_alone"])
        self.assertFalse(summary["microvariant_exact"])
        for key in (
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
