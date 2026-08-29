from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "mac" / "robot-kb-local" / "robot_kb_psa_corroboration_harvest.py"
)
SPEC = importlib.util.spec_from_file_location(
    "robot_kb_psa_corroboration_harvest", MODULE_PATH
)
assert SPEC and SPEC.loader
harvest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harvest
SPEC.loader.exec_module(harvest)


def target(**overrides):
    values = dict(
        gcc_url="https://gradedcardcenter.com/item/3edd662b-258c-4d73-bd76-5078a48bd02c",
        title="PSA 10 N's Zoroark Ex",
        card_set="Mega Dream Ex",
        collector_number="#242/193",
        language="JA",
        grader="PSA",
        grade="10",
        year=2025,
    )
    values.update(overrides)
    return harvest.BenchmarkTarget(**values)


def identity(**overrides):
    values = dict(
        listing_id="3edd662b-258c-4d73-bd76-5078a48bd02c",
        gcc_url="https://gradedcardcenter.com/item/3edd662b-258c-4d73-bd76-5078a48bd02c",
        title="PSA 10 N's Zoroark Ex",
        card_set="Mega Dream Ex",
        collector_number="#242/193",
        language_code="ja",
        grader="PSA",
        grade="10",
        year=2025,
        structured_finish="",
        structured_variant="",
        structured_stamp="",
        structured_edition="Unlimited",
        structured_shadow_treatment="",
    )
    values.update(overrides)
    return harvest.GccIdentity(**values)


def candidate(**overrides):
    values = dict(
        item_id="287464263284",
        title="Pokemon Japanese PSA 10 N's Zoroark ex Mega Dream ex 242/193",
        date_sold="2026-08-01",
        sale_price_minor=13000,
        currency="USD",
        buying_format="Buy It Now",
        accepted_offer_ambiguous=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def psa_body(*, best_offer=False, price="130.00", date="08/01/26", format_text="Buy It Now"):
    offer = "Best Offer\n" if best_offer else ""
    return (
        "Certification Number 145414399\n"
        "2025 POKEMON JAPANESE M2a MEGA DREAM ex N'S ZOROARK ex SPECIAL ART RARE 242\n"
        "Item Grade 10\n"
        "Sales of Similar Items\n"
        "PSA 10\n"
        f"{date}\n"
        "eBay\n"
        f"{format_text}\n"
        f"{offer}"
        "287464263284\n"
        f"${price}\n"
    )


class IdentityTests(unittest.TestCase):
    def test_target_matches_retained_gcc_identity(self):
        self.assertTrue(harvest._target_matches_identity(target(), identity()))
        self.assertFalse(
            harvest._target_matches_identity(target(language="EN"), identity())
        )
        self.assertFalse(
            harvest._target_matches_identity(target(grade="9"), identity())
        )

    def test_psa_cert_requires_one_stable_retained_serial(self):
        class KB:
            def raw_source_payload(self, record_id):
                return {
                    "item": {
                        "serialNumber": "145414399" if record_id != "bad" else "145414398"
                    }
                }

        with mock.patch.object(harvest, "_gcc_source_record_ids", return_value=["a", "b"]):
            self.assertEqual(harvest.load_psa_cert_number(KB(), "listing"), "145414399")
        with mock.patch.object(harvest, "_gcc_source_record_ids", return_value=["a", "bad"]):
            with self.assertRaisesRegex(harvest.PsaCorroborationError, "stable PSA serialNumber"):
                harvest.load_psa_cert_number(KB(), "listing")


class SaleProofTests(unittest.TestCase):
    def test_exact_fixed_sale_row_proves_item_date_and_price(self):
        proof = harvest._candidate_sale_proof(candidate(), psa_body(), 10.0)
        self.assertEqual(proof["date_sold"], "2026-08-01")
        self.assertEqual(proof["sale_price_minor"], 13000)
        self.assertEqual(proof["format_family"], "FIXED")

    def test_exact_auction_sale_row_is_supported(self):
        proof = harvest._candidate_sale_proof(
            candidate(buying_format="Auction"),
            psa_body(format_text="Auction"),
            10.0,
        )
        self.assertEqual(proof["format_family"], "AUCTION")

    def test_best_offer_never_proves_final_price(self):
        with self.assertRaisesRegex(harvest.PsaCorroborationError, "exactly one non-Best-Offer"):
            harvest._candidate_sale_proof(candidate(), psa_body(best_offer=True), 10.0)

    def test_price_or_date_conflict_stays_blocked(self):
        with self.assertRaisesRegex(harvest.PsaCorroborationError, "sale price mismatch"):
            harvest._candidate_sale_proof(candidate(), psa_body(price="131.00"), 10.0)
        with self.assertRaisesRegex(harvest.PsaCorroborationError, "sale date mismatch"):
            harvest._candidate_sale_proof(candidate(), psa_body(date="08/02/26"), 10.0)


class PsaPageTests(unittest.TestCase):
    def test_cert_page_requires_cert_grade_and_existing_v4_identity_score(self):
        with (
            mock.patch.object(harvest.watcher, "_target_grade", return_value=10.0),
            mock.patch.object(
                harvest.watcher,
                "psa_apr_match_score",
                return_value=(100, "exact"),
            ),
        ):
            grade, reason = harvest.validate_psa_page(
                identity(), "145414399", psa_body()
            )
        self.assertEqual(grade, 10.0)
        self.assertEqual(reason, "exact")

        with mock.patch.object(harvest.watcher, "_target_grade", return_value=10.0):
            with self.assertRaisesRegex(harvest.PsaCorroborationError, "certificate number"):
                harvest.validate_psa_page(identity(), "999999999", psa_body())


class BenchmarkSelectionTests(unittest.TestCase):
    def _report(self, *, accepted_offer=False):
        return {
            "mode": "READ_ONLY_GCC_EBAY_EXACT_BENCHMARK",
            "robot_kb_write": False,
            "v4_economic_use": False,
            "targets": [
                {
                    "target": {
                        "gcc_url": target().gcc_url,
                        "title": target().title,
                        "card_set": target().card_set,
                        "collector_number": target().collector_number,
                        "language": target().language,
                        "grader": target().grader,
                        "grade": target().grade,
                        "year": target().year,
                    },
                    "manual_review": [
                        {
                            "item_id": candidate().item_id,
                            "title": candidate().title,
                            "date_sold": candidate().date_sold,
                            "sale_price_minor": candidate().sale_price_minor,
                            "currency": candidate().currency,
                            "buying_format": "Best Offer" if accepted_offer else candidate().buying_format,
                            "accepted_offer_ambiguous": accepted_offer,
                        }
                    ],
                }
            ],
        }

    def test_only_title_compatible_non_offer_candidates_are_selected(self):
        groups = harvest.candidate_groups(self._report())
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][1][0].item_id, "287464263284")
        self.assertEqual(harvest.candidate_groups(self._report(accepted_offer=True)), [])

    def test_non_fail_closed_benchmark_is_rejected(self):
        report = self._report()
        report["robot_kb_write"] = True
        with self.assertRaisesRegex(harvest.PsaCorroborationError, "safety flags"):
            harvest.candidate_groups(report)


class OrchestrationTests(unittest.TestCase):
    def test_run_harvest_composes_tcgdex_and_psa_without_robot_kb_write(self):
        report = BenchmarkSelectionTests()._report()
        plan = SimpleNamespace(tcgdex_card_id="M2a-242")
        with (
            mock.patch.object(harvest, "load_gcc_identity", return_value=identity()),
            mock.patch.object(harvest, "load_psa_cert_number", return_value="145414399"),
            mock.patch.object(harvest, "resolve_tcgdex_exact", return_value=object()),
            mock.patch.object(harvest, "canonical_plan", return_value=plan),
            mock.patch.object(harvest, "_fetch_psa_body", return_value=(200, psa_body())),
            mock.patch.object(harvest.watcher, "_target_grade", return_value=10.0),
            mock.patch.object(
                harvest.watcher,
                "psa_apr_match_score",
                return_value=(100, "exact"),
            ),
        ):
            code, payload = harvest.run_harvest(
                object(), report, object(), max_cert_pages=10, delay_seconds=0
            )
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["records"]), 1)
        self.assertFalse(payload["robot_kb_write"])
        self.assertFalse(payload["sale_transaction_stored"])
        self.assertTrue(payload["records"][0]["exact_identity_proven"])
        self.assertTrue(payload["records"][0]["microvariant_compatible_proven"])
        self.assertFalse(payload["records"][0]["best_offer"])

    def test_psa_403_opens_circuit_and_emits_no_record(self):
        report = BenchmarkSelectionTests()._report()
        with (
            mock.patch.object(harvest, "load_gcc_identity", return_value=identity()),
            mock.patch.object(harvest, "load_psa_cert_number", return_value="145414399"),
            mock.patch.object(harvest, "resolve_tcgdex_exact", return_value=object()),
            mock.patch.object(
                harvest, "canonical_plan", return_value=SimpleNamespace(tcgdex_card_id="M2a-242")
            ),
            mock.patch.object(harvest, "_fetch_psa_body", return_value=(403, "")),
        ):
            code, payload = harvest.run_harvest(
                object(), report, object(), max_cert_pages=10, delay_seconds=0
            )
        self.assertEqual(code, 1)
        self.assertTrue(payload["psa_circuit_open"])
        self.assertEqual(payload["records"], [])


if __name__ == "__main__":
    unittest.main()
