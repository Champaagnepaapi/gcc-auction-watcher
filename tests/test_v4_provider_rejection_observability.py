from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as mm
import v4_provider_rejection_observability as obs


def _lot(
    *,
    name="Charizard",
    language="English",
    series="Base Set",
    reference="4/102",
):
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/provider-observability-test",
        title=name,
        current_price=40.0,
        source_type="fixed",
        grader="PSA",
        grade="10",
        card_number=reference,
        card_set=series,
        language=language,
        body=(
            "Catégorie: Pokémon\n"
            f"Référence: #{reference}\n"
            f"Série: {series}\n"
            f"Langue: {language}\n"
            "Société de gradation: PSA\n"
            "Note: 10\n"
        ),
    )


def _canonical(
    *,
    name="Charizard",
    full_number="4/102",
    local_id="4",
    set_name="Base Set",
    set_id="base1",
    language_code="en",
    unique=False,
    variants=None,
):
    return mm.CanonicalCard(
        "EXACT",
        card_id=f"{set_id}-{local_id}",
        set_id=set_id,
        set_name=set_name,
        local_id=local_id,
        full_number=full_number,
        name=name,
        language_code=language_code,
        variants={"holo": True} if variants is None else variants,
        reason="TCGDEX_EXACT_SET_LOCALID",
        unique_name_number=unique,
    )


def _candidate(
    *,
    name="Charizard",
    set_name="Base Set",
    game="pokemon",
    number="4/102",
    variant="Holofoil",
):
    return {
        "id": "pt-observability-card",
        "name": name,
        "cardNumber": number,
        "set": {"name": set_name, "slug": "fixture-set", "id": "fixture-id"},
        "variant": variant,
        "productType": "single",
        "game": game,
    }


class ProviderRejectionObservabilityTests(unittest.TestCase):
    def test_reason_distinguishes_set_number_language_and_match(self):
        target = _lot()
        canonical = _canonical()

        self.assertEqual(
            obs._candidate_rejection_reason(
                target, canonical, _candidate(set_name="Jungle")
            ),
            "SET",
        )
        self.assertEqual(
            obs._candidate_rejection_reason(
                target, canonical, _candidate(number="5/102")
            ),
            "CARD_NUMBER",
        )
        self.assertEqual(
            obs._candidate_rejection_reason(
                target, canonical, _candidate(game="pokemon-japanese")
            ),
            "LANGUAGE_GAME",
        )
        self.assertEqual(
            obs._candidate_rejection_reason(target, canonical, _candidate()),
            "MATCH",
        )

    def test_post129_charizard_live_shape_is_not_misdiagnosed_as_name_or_set(self):
        target = _lot(
            name="Charizard VStar",
            language="Japanese",
            series="Brilliant Stars",
            reference="015/100",
        )
        canonical = _canonical(
            name="Charizard VStar",
            full_number="015/100",
            local_id="015",
            set_name="Brilliant Stars",
            set_id="S9",
            language_code="ja",
        )
        candidate = _candidate(
            name="Charizard VSTAR (Japanese)",
            number="015/100",
            set_name="S9: Star Birth",
            game="pokemon-japanese",
        )
        self.assertEqual(
            obs._candidate_rejection_reason(target, canonical, candidate),
            "MATCH",
        )

    def test_post129_zorua_explicit_set_namespace_conflict_is_visible(self):
        target = _lot(
            name="Zorua",
            language="Japanese",
            series="Night Wanderer",
            reference="072/064",
        )
        canonical = _canonical(
            name="Zorua",
            full_number="072/064",
            local_id="072",
            set_name="Night Wanderer",
            set_id="SV7a",
            language_code="ja",
        )
        candidate = _candidate(
            name="Zorua (Japanese)",
            number="072/064",
            set_name="SV6a: Night Wanderer",
            game="pokemon-japanese",
        )
        self.assertEqual(
            obs._candidate_rejection_reason(target, canonical, candidate),
            "SET_ID_CONFLICT",
        )

    def test_provider_only_finish_reports_when_tcgdex_finish_is_unproven(self):
        target = _lot()
        canonical = _canonical(variants={})
        self.assertEqual(
            obs._candidate_rejection_reason(target, canonical, _candidate()),
            "PROVIDER_ONLY_FINISH_UNPROVEN",
        )

    def test_paced_probe_logs_counts_and_bounded_identity_examples(self):
        target = _lot()
        canonical = _canonical()
        context = obs.PokeTraceProbeContext(target, canonical)
        token = obs._ACTIVE_POKETRACE_PROBE.set(context)
        messages = []

        def fake_get(_budget, _url, *, params=None):
            return 200, {
                "data": [
                    _candidate(),
                    _candidate(set_name="Jungle"),
                ]
            }, {}

        old_get = obs._ORIGINAL_PACED_GET
        try:
            obs._ORIGINAL_PACED_GET = fake_get
            with patch.object(watcher, "log", side_effect=messages.append):
                result = obs._diagnostic_paced_get(
                    mm.RequestBudget(),
                    f"{mm.POKETRACE_BASE_URL}/cards",
                    params={"search": "Charizard"},
                )
        finally:
            obs._ORIGINAL_PACED_GET = old_get
            obs._ACTIVE_POKETRACE_PROBE.reset(token)

        self.assertEqual(result[0], 200)
        joined = "\n".join(messages)
        self.assertIn("provider_candidates=2", joined)
        self.assertIn("MATCH=1", joined)
        self.assertIn("SET=1", joined)
        self.assertIn("set=Jungle", joined)
        self.assertIn("tcgdex_variants=holo:1", joined)
        self.assertNotIn("api_key", joined.casefold())

    def test_nonexact_tcgdex_result_logs_final_blocker_only(self):
        target = _lot(
            name="Galarian Zapdos",
            language="Japanese",
            series="VSTAR Universe",
            reference="177/172",
        )
        old_resolver = obs._ORIGINAL_TCGDEX_RESOLVER
        messages = []
        try:
            obs._ORIGINAL_TCGDEX_RESOLVER = lambda _lot: mm.CanonicalCard(
                "AMBIGUOUS", reason="two exact coordinate candidates"
            )
            with patch.object(watcher, "log", side_effect=messages.append):
                result = obs._diagnostic_tcgdex_resolver(target)
        finally:
            obs._ORIGINAL_TCGDEX_RESOLVER = old_resolver

        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(len(messages), 1)
        self.assertIn("TCGdex blocker", messages[0])
        self.assertIn("177/172", messages[0])
        self.assertIn("VSTAR Universe", messages[0])
        self.assertIn("two exact coordinate candidates", messages[0])

    def test_installer_is_idempotent_and_wraps_current_final_functions(self):
        old_installed = obs._INSTALLED
        old_resolver = mm.resolve_tcgdex_card
        old_evidence = mm._poketrace_evidence
        old_get = mm._paced_poketrace_get
        old_original_resolver = obs._ORIGINAL_TCGDEX_RESOLVER
        old_original_evidence = obs._ORIGINAL_POKETRACE_EVIDENCE
        old_original_get = obs._ORIGINAL_PACED_GET
        try:
            obs._INSTALLED = False
            obs.install_v4_provider_rejection_observability()
            first = (
                mm.resolve_tcgdex_card,
                mm._poketrace_evidence,
                mm._paced_poketrace_get,
            )
            obs.install_v4_provider_rejection_observability()
            self.assertEqual(
                first,
                (
                    mm.resolve_tcgdex_card,
                    mm._poketrace_evidence,
                    mm._paced_poketrace_get,
                ),
            )
            self.assertIs(first[0], obs._diagnostic_tcgdex_resolver)
            self.assertIs(first[1], obs._diagnostic_poketrace_evidence)
            self.assertIs(first[2], obs._diagnostic_paced_get)
        finally:
            mm.resolve_tcgdex_card = old_resolver
            mm._poketrace_evidence = old_evidence
            mm._paced_poketrace_get = old_get
            obs._ORIGINAL_TCGDEX_RESOLVER = old_original_resolver
            obs._ORIGINAL_POKETRACE_EVIDENCE = old_original_evidence
            obs._ORIGINAL_PACED_GET = old_original_get
            obs._INSTALLED = old_installed


if __name__ == "__main__":
    unittest.main()
