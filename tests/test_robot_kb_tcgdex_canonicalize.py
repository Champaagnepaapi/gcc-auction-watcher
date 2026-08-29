from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "mac" / "robot-kb-local" / "robot_kb_tcgdex_canonicalize.py"
SPEC = importlib.util.spec_from_file_location("robot_kb_tcgdex_canonicalize", MODULE_PATH)
assert SPEC and SPEC.loader
canonicalize = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = canonicalize
SPEC.loader.exec_module(canonicalize)

try:
    from robot_kb.repository import KnowledgeBase

    HAS_P3 = True
except ModuleNotFoundError:
    KnowledgeBase = None
    HAS_P3 = False


GCC_ID = "3edd662b-258c-4d73-bd76-5078a48bd02c"


def payload(**overrides):
    collectible = {
        "category": "Pokemon",
        "type": "CARD",
        "language": "Japanese",
        "yearOfDistribution": 2025,
        "set": "Mega Dream Ex",
        "extension": "Mega Dream Ex",
        "reference": "#242/193",
    }
    collectible.update(overrides.pop("collectible", {}))
    item = {
        "title": "PSA 10 N's Zoroark Ex",
        "gradingCompany": "PSA",
        "grade": "10",
        "collectible": collectible,
    }
    item.update(overrides.pop("item", {}))
    row = {
        "id": GCC_ID,
        "item": item,
        "sellingType": "FIXED_PRICE",
        "status": "ON_SALE",
    }
    row.update(overrides)
    return row


def resolved(**overrides):
    values = {
        "status": "EXACT",
        "card_id": "m2a-242",
        "set_id": "m2a",
        "set_name": "Mega Dream ex",
        "local_id": "242",
        "full_number": "242/193",
        "name": "N's Zoroark ex",
        "language_code": "ja",
        "variants": {
            "normal": False,
            "holo": True,
            "reverse": False,
            "firstEdition": False,
        },
        "reason": "exact V4 TCGdex proof",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def identity(**overrides):
    values = {
        "listing_id": GCC_ID,
        "gcc_url": f"https://gradedcardcenter.com/item/{GCC_ID}",
        "title": "PSA 10 N's Zoroark Ex",
        "card_set": "Mega Dream Ex",
        "collector_number": "#242/193",
        "language_code": "ja",
        "grader": "PSA",
        "grade": "10",
        "year": 2025,
        "structured_finish": "",
        "structured_variant": "",
        "structured_stamp": "",
        "structured_edition": "",
        "structured_shadow_treatment": "",
    }
    values.update(overrides)
    return canonicalize.GccIdentity(**values)


class ResolverStackTests(unittest.TestCase):
    def test_resolver_installs_production_identity_stack_in_order(self):
        calls = []
        definitions = (
            (
                "v4_tcgdex_exact_coordinate_recovery",
                "install_v4_tcgdex_exact_coordinate_recovery",
                "exact_coordinate",
            ),
            (
                "v4_tcgdex_run1054_set_aliases",
                "install_v4_tcgdex_run1054_set_aliases",
                "run1054_aliases",
            ),
            (
                "v4_tcgdex_japanese_set_aliases",
                "install_v4_tcgdex_japanese_set_aliases",
                "japanese_aliases",
            ),
            (
                "v4_tcgdex_generalized_coordinate_recovery",
                "install_v4_tcgdex_generalized_coordinate_recovery",
                "generalized_coordinate",
            ),
            (
                "v4_tcgdex_two_of_three_backport",
                "install_v4_tcgdex_two_of_three_backport",
                "two_of_three",
            ),
            (
                "v4_tcgdex_unique_coordinate_fallback",
                "install_v4_tcgdex_unique_coordinate_fallback",
                "unique_coordinate",
            ),
            (
                "v4_tcgdex_source_pinned_finish",
                "install_v4_tcgdex_source_pinned_finish",
                "source_pinned_finish",
            ),
        )
        fake_modules = {}
        for module_name, function_name, label in definitions:
            module = types.ModuleType(module_name)

            def installer(label=label):
                calls.append(label)

            setattr(module, function_name, installer)
            fake_modules[module_name] = module

        exact = resolved()
        canonical = types.ModuleType("v4_canonical_multimarket")
        canonical.resolve_tcgdex_card = lambda lot: exact
        fake_modules["v4_canonical_multimarket"] = canonical

        with mock.patch.dict(sys.modules, fake_modules):
            observed = canonicalize.resolve_tcgdex_exact(identity())

        self.assertIs(observed, exact)
        self.assertEqual(calls, [definition[2] for definition in definitions])


class CanonicalPlanTests(unittest.TestCase):
    def test_exact_single_holo_builds_phase1_plan(self):
        plan = canonicalize.canonical_plan(identity(), resolved())
        self.assertEqual(plan.finish, "HOLO")
        self.assertEqual(plan.language_code, "ja")
        self.assertEqual(plan.collector_number, "242/193")
        self.assertEqual(plan.profile_assignments, {"finish": "HOLO"})

    def test_multiple_active_finishes_fail_closed(self):
        with self.assertRaisesRegex(canonicalize.CanonicalizationError, "finish is ambiguous"):
            canonicalize.canonical_plan(
                identity(),
                resolved(
                    variants={
                        "normal": True,
                        "holo": True,
                        "reverse": False,
                        "firstEdition": False,
                    }
                ),
            )

    def test_missing_full_collector_number_fails_closed(self):
        with self.assertRaisesRegex(canonicalize.CanonicalizationError, "collector number conflicts"):
            canonicalize.canonical_plan(identity(), resolved(full_number="242"))

    def test_sensitive_microvariant_title_is_blocked(self):
        with self.assertRaisesRegex(canonicalize.CanonicalizationError, "sensitive microvariant"):
            canonicalize.canonical_plan(
                identity(title="PSA 10 Pikachu Master Ball 242/193"),
                resolved(name="Pikachu"),
            )

    def test_structured_finish_must_agree(self):
        with self.assertRaisesRegex(canonicalize.CanonicalizationError, "finish conflicts"):
            canonicalize.canonical_plan(
                identity(structured_finish="Reverse Holo"),
                resolved(),
            )

    def test_first_edition_true_is_explicit_but_false_is_not_no_stamp(self):
        first = canonicalize.canonical_plan(
            identity(),
            resolved(
                variants={
                    "normal": False,
                    "holo": True,
                    "reverse": False,
                    "firstEdition": True,
                }
            ),
        )
        self.assertEqual(first.edition_stamp, "FIRST_EDITION")
        ordinary = canonicalize.canonical_plan(identity(), resolved())
        self.assertEqual(ordinary.edition_stamp, "")
        self.assertNotIn("edition_stamp", ordinary.profile_assignments)

    def test_explicit_gcc_unlimited_plus_tcgdex_false_proves_no_first_stamp(self):
        plan = canonicalize.canonical_plan(
            identity(structured_edition="Unlimited"),
            resolved(),
        )
        self.assertEqual(plan.edition_stamp, "NO_FIRST_EDITION_STAMP")
        self.assertEqual(
            plan.profile_assignments,
            {"finish": "HOLO", "edition_stamp": "NO_FIRST_EDITION_STAMP"},
        )

    def test_gcc_unlimited_requires_explicit_tcgdex_false(self):
        variants = {
            "normal": False,
            "holo": True,
            "reverse": False,
        }
        with self.assertRaisesRegex(
            canonicalize.CanonicalizationError,
            "Unlimited requires explicit TCGdex firstEdition=false",
        ):
            canonicalize.canonical_plan(
                identity(structured_edition="Unlimited"),
                resolved(variants=variants),
            )

    def test_unknown_structured_edition_remains_blocking(self):
        with self.assertRaisesRegex(
            canonicalize.CanonicalizationError,
            "structured GCC edition is not supported",
        ):
            canonicalize.canonical_plan(
                identity(structured_edition="Special Edition"),
                resolved(),
            )


@unittest.skipUnless(HAS_P3, "pinned Robot KB P3 runtime is required")
class CanonicalPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeBase.open()
        source = self.kb.create_source_system("gcc", "GCC Marketplace", "LISTING_PLATFORM")
        obj = self.kb.create_external_object(source, "LISTING", GCC_ID)
        self.gcc_identifier = self.kb.add_external_identifier(obj, "GCC_LISTING_ID", GCC_ID)
        self.kb.append_source_record(
            source,
            GCC_ID,
            payload(),
            retrieved_at="2026-08-29T08:00:00+00:00",
            external_object_id=obj,
        )

    def tearDown(self):
        self.kb.close()

    def test_retained_gcc_identity_is_loaded_without_free_form_override(self):
        loaded = canonicalize.load_gcc_identity(self.kb, GCC_ID)
        self.assertEqual(loaded.collector_number, "#242/193")
        self.assertEqual(loaded.language_code, "ja")
        self.assertEqual(loaded.card_set, "Mega Dream Ex")

    def test_conflicting_retained_gcc_identity_fails_closed(self):
        source = self.kb.connection.execute(
            "SELECT id FROM source_system WHERE code='gcc'"
        ).fetchone()["id"]
        obj = self.kb.connection.execute(
            "SELECT external_object_id FROM external_identifier WHERE id=?",
            (self.gcc_identifier,),
        ).fetchone()["external_object_id"]
        self.kb.append_source_record(
            source,
            GCC_ID,
            payload(collectible={"set": "Different Set"}),
            retrieved_at="2026-08-29T09:00:00+00:00",
            external_object_id=obj,
        )
        with self.assertRaisesRegex(canonicalize.CanonicalizationError, "changed or conflicts"):
            canonicalize.load_gcc_identity(self.kb, GCC_ID)

    def test_write_creates_one_canonical_card_and_two_proven_links(self):
        loaded = canonicalize.load_gcc_identity(self.kb, GCC_ID)
        plan = canonicalize.canonical_plan(loaded, resolved())
        result = canonicalize.persist_plan(self.kb, loaded, plan)
        self.assertTrue(result["canonical_card_id"].startswith("card_"))
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) AS n FROM canonical_card").fetchone()["n"],
            1,
        )
        links = self.kb.connection.execute(
            "SELECT resolution_state, canonical_card_id FROM identifier_link ORDER BY id"
        ).fetchall()
        self.assertEqual(len(links), 2)
        self.assertEqual({row["resolution_state"] for row in links}, {"PROVEN"})
        self.assertEqual({row["canonical_card_id"] for row in links}, {result["canonical_card_id"]})

    def test_identical_write_replay_is_idempotent(self):
        loaded = canonicalize.load_gcc_identity(self.kb, GCC_ID)
        plan = canonicalize.canonical_plan(loaded, resolved())
        first = canonicalize.persist_plan(self.kb, loaded, plan)
        second = canonicalize.persist_plan(self.kb, loaded, plan)
        self.assertEqual(first["canonical_card_id"], second["canonical_card_id"])
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) AS n FROM canonical_card").fetchone()["n"],
            1,
        )
        self.assertEqual(
            self.kb.connection.execute("SELECT COUNT(*) AS n FROM identifier_link").fetchone()["n"],
            2,
        )
        self.assertTrue(second["gcc_link_already_proven"])
        self.assertTrue(second["tcgdex_link_already_proven"])


if __name__ == "__main__":
    unittest.main()
