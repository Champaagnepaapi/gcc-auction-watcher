from __future__ import annotations

import unittest

from v5.market_values.poketrace import (
    PokeTraceConfig,
    _candidate_matches,
)
from v5.market_values.poketrace_free import FreeTierPokeTraceProvider
from v5.models import CardIdentity
from v5.poketrace_identity import (
    PokeTraceIdentityResolver,
    REJECT_CARD_NAME,
    REJECT_CARD_NUMBER,
    REJECT_SET,
    _candidate_score_and_rejection,
    render_poketrace_identity_counters,
)
from v5.poketrace_matching import (
    NAME_DIFF_GENDER,
    NAME_DIFF_LOCALIZATION,
    NAME_DIFF_MECHANIC_SUFFIX,
    NAME_DIFF_PUNCTUATION_ACCENTS,
    NAME_DIFF_SIGNIFICANT_PREFIX,
    NUMBER_DIFF_ALPHANUMERIC_CASE,
    NUMBER_DIFF_CONTRADICTORY_AFFIX,
    NUMBER_DIFF_DENOMINATOR_CONFLICT,
    NUMBER_DIFF_DENOMINATOR_MISSING,
    NUMBER_DIFF_LEADING_ZERO,
    NUMBER_DIFF_LISTING_NUMERATOR_ONLY,
    NUMBER_DIFF_PREFIX_FAMILY,
    SET_DIFF_DANGEROUS_CONTAINMENT,
    SET_DIFF_LANGUAGE_LOCALIZATION,
    SET_DIFF_PARENT_SUBSET,
    SET_DIFF_POKEMON_TCG_WRAPPER,
    SET_DIFF_PUNCTUATION_SPACING,
    _candidate_evidence,
    _normalize_card_number,
)


class _Response:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.payloads:
            raise AssertionError("unexpected PokeTrace request")
        return _Response(self.payloads.pop(0))


def _identity(
    *,
    card_name="Charizard",
    set_name="Pokemon TCG Base Set",
    card_number="4/102",
    language="English",
):
    return CardIdentity(
        game="Pokemon TCG",
        card_name=card_name,
        set=set_name,
        card_number=card_number,
        language=language,
        variant="Holofoil",
    )


def _candidate(
    *,
    card_name="Charizard",
    set_name="Base Set",
    card_number="004/102",
):
    return {
        "id": "pt-card",
        "name": card_name,
        "cardNumber": card_number,
        "set": {"name": set_name, "slug": set_name.casefold().replace(" ", "-")},
        "variant": "Holofoil",
        "productType": "single",
        "currency": "USD",
        "prices": {
            "ebay": {"NEAR_MINT": {"median7d": 100}},
            "tcgplayer": {"NEAR_MINT": {"median7d": 110}},
        },
    }


def _provider(session):
    return FreeTierPokeTraceProvider(
        config=PokeTraceConfig(
            enabled=True,
            api_key="secret-never-render",
            minimum_request_interval_seconds=0,
        ),
        session=session,
        sleeper=lambda _seconds: None,
    )


class PokeTraceIdentityRegressionTests(unittest.TestCase):
    def test_safe_set_spelling_equivalences_are_explainable(self):
        wrapper = _candidate_evidence(
            _identity(set_name="Pokemon TCG Base Set"),
            _candidate(set_name="Base Set"),
        )
        punctuation = _candidate_evidence(
            _identity(set_name="Base-Set"),
            _candidate(set_name="Base Set"),
        )

        self.assertTrue(wrapper.set_matched)
        self.assertEqual(wrapper.set_difference, SET_DIFF_POKEMON_TCG_WRAPPER)
        self.assertTrue(punctuation.set_matched)
        self.assertEqual(
            punctuation.set_difference, SET_DIFF_PUNCTUATION_SPACING
        )

    def test_parent_subset_and_dangerous_containment_remain_rejected(self):
        subset = _candidate_evidence(
            _identity(set_name="Crown Zenith"),
            _candidate(set_name="Crown Zenith: Galarian Gallery"),
        )
        dangerous = _candidate_evidence(
            _identity(set_name="Team Rocket"),
            _candidate(set_name="Team Rocket Returns"),
        )
        localized = _candidate_evidence(
            _identity(set_name="Base Set"),
            _candidate(set_name="拡張パック"),
        )

        self.assertFalse(subset.set_matched)
        self.assertEqual(subset.set_difference, SET_DIFF_PARENT_SUBSET)
        self.assertFalse(dangerous.set_matched)
        self.assertEqual(
            dangerous.set_difference, SET_DIFF_DANGEROUS_CONTAINMENT
        )
        self.assertFalse(localized.set_matched)
        self.assertEqual(
            localized.set_difference, SET_DIFF_LANGUAGE_LOCALIZATION
        )

    def test_prefixed_number_leading_zero_and_case_are_safe(self):
        leading_zero = _candidate_evidence(
            _identity(card_number="TG03/TG30"),
            _candidate(card_number="tg3/tg30"),
        )
        case_only = _candidate_evidence(
            _identity(card_number="SV107/SV122"),
            _candidate(card_number="sv107/sv122"),
        )

        self.assertTrue(leading_zero.card_number_matched)
        self.assertEqual(
            leading_zero.card_number_difference, NUMBER_DIFF_LEADING_ZERO
        )
        self.assertTrue(case_only.card_number_matched)
        self.assertEqual(
            case_only.card_number_difference, NUMBER_DIFF_ALPHANUMERIC_CASE
        )

    def test_number_label_normalization_does_not_strip_real_no_prefix(self):
        self.assertEqual(_normalize_card_number("No. 004/102"), "4/102")
        self.assertEqual(_normalize_card_number("NO1"), "no1")

    def test_number_conflicts_are_classified_without_becoming_equivalent(self):
        denominator = _candidate_evidence(
            _identity(card_number="4/102"),
            _candidate(card_number="4/130"),
        )
        prefix = _candidate_evidence(
            _identity(card_number="TG03/TG30"),
            _candidate(card_number="GG03/GG70"),
        )
        suffix = _candidate_evidence(
            _identity(card_number="4a/102"),
            _candidate(card_number="4b/102"),
        )

        self.assertEqual(denominator.rejection, REJECT_CARD_NUMBER)
        self.assertEqual(
            denominator.card_number_difference,
            NUMBER_DIFF_DENOMINATOR_CONFLICT,
        )
        self.assertEqual(prefix.rejection, REJECT_CARD_NUMBER)
        self.assertEqual(prefix.card_number_difference, NUMBER_DIFF_PREFIX_FAMILY)
        self.assertEqual(suffix.rejection, REJECT_CARD_NUMBER)
        self.assertEqual(
            suffix.card_number_difference, NUMBER_DIFF_CONTRADICTORY_AFFIX
        )

    def test_name_differences_keep_mechanics_and_gender_significant(self):
        accent = _candidate_evidence(
            _identity(card_name="Flabébé"),
            _candidate(card_name="Flabebe"),
        )
        gender = _candidate_evidence(
            _identity(card_name="Nidoran♀"),
            _candidate(card_name="Nidoran♂"),
        )
        suffix = _candidate_evidence(
            _identity(card_name="Charizard EX"),
            _candidate(card_name="Charizard ex"),
        )
        prefix = _candidate_evidence(
            _identity(card_name="Dark Charizard"),
            _candidate(card_name="Charizard"),
        )
        localized = _candidate_evidence(
            _identity(card_name="Dracaufeu", language="French"),
            _candidate(card_name="Charizard"),
        )

        self.assertTrue(accent.name_matched)
        self.assertEqual(
            accent.name_difference, NAME_DIFF_PUNCTUATION_ACCENTS
        )
        self.assertEqual(gender.rejection, REJECT_CARD_NAME)
        self.assertEqual(gender.name_difference, NAME_DIFF_GENDER)
        self.assertEqual(suffix.rejection, REJECT_CARD_NAME)
        self.assertEqual(suffix.name_difference, NAME_DIFF_MECHANIC_SUFFIX)
        self.assertEqual(prefix.rejection, REJECT_CARD_NAME)
        self.assertEqual(prefix.name_difference, NAME_DIFF_SIGNIFICANT_PREFIX)
        self.assertEqual(localized.rejection, REJECT_CARD_NAME)
        self.assertEqual(localized.name_difference, NAME_DIFF_LOCALIZATION)

    def test_strategy_yield_counts_unique_near_exact_and_redundant_candidates(self):
        wrong_name = _candidate(card_name="Blastoise")
        wrong_number = _candidate(card_number="5/102")
        exact = _candidate()
        session = _Session(
            [
                {"data": [wrong_name]},
                {"data": [wrong_name, wrong_number]},
                {"data": [wrong_number, exact]},
            ]
        )
        resolver = PokeTraceIdentityResolver(_provider(session))

        result = resolver.resolve_identity(_identity())

        self.assertTrue(result.matched)
        canonical = resolver.strategy_counters["contextual_canonical"]
        contextual = resolver.strategy_counters["contextual"]
        structured = resolver.strategy_counters["structured"]
        self.assertEqual(canonical.unique_candidates_introduced, 1)
        self.assertEqual(canonical.near_matches_introduced, 1)
        self.assertEqual(contextual.unique_candidates_introduced, 1)
        self.assertEqual(contextual.redundant_candidates, 1)
        self.assertEqual(structured.unique_candidates_introduced, 1)
        self.assertEqual(structured.redundant_candidates, 1)
        self.assertEqual(structured.all_three_introduced, 1)
        self.assertEqual(structured.exacts_introduced, 1)
        self.assertEqual(session.calls[0][1]["params"]["market"], "US")
        rendered = render_poketrace_identity_counters(resolver)
        self.assertIn("strategy structured:", rendered)
        self.assertNotIn("pt-card", rendered)

    def test_numerator_only_near_match_has_total_and_directional_metrics(self):
        evidence = _candidate_evidence(
            _identity(card_name=None, card_number="4"),
            _candidate(card_number="004/102"),
        )
        resolver = PokeTraceIdentityResolver(_provider(_Session([])))

        self.assertEqual(evidence.failed_core_fields, ("card_number",))
        resolver._count_match_evidence(evidence)
        self.assertEqual(
            resolver.near_match_counters.number_differences[
                NUMBER_DIFF_LISTING_NUMERATOR_ONLY
            ],
            1,
        )
        self.assertEqual(
            resolver.near_match_counters.number_differences[
                NUMBER_DIFF_DENOMINATOR_MISSING
            ],
            1,
        )

    def test_identity_and_market_accept_same_conservative_set_alias_and_partial_number(self):
        identity = _identity(card_number="4")
        candidate = _candidate(card_number="004/102")

        score, rejection = _candidate_score_and_rejection(identity, candidate)

        self.assertIsNotNone(score)
        self.assertIsNone(rejection)
        self.assertTrue(_candidate_matches(identity, candidate))

    def test_distinct_numbered_set_is_rejected_even_when_base_tokens_overlap(self):
        identity = _identity(set_name="Base Set")
        candidate = _candidate(set_name="Base Set 2")

        score, rejection = _candidate_score_and_rejection(identity, candidate)

        self.assertIsNone(score)
        self.assertEqual(rejection, REJECT_SET)
        self.assertFalse(_candidate_matches(identity, candidate))

    def test_contained_but_distinct_set_name_is_not_a_fuzzy_alias(self):
        identity = _identity(set_name="Team Rocket")
        candidate = _candidate(set_name="Team Rocket Returns")

        score, rejection = _candidate_score_and_rejection(identity, candidate)

        self.assertIsNone(score)
        self.assertEqual(rejection, REJECT_SET)
        self.assertFalse(_candidate_matches(identity, candidate))

    def test_meaningful_name_suffix_case_is_not_erased(self):
        identity = _identity(card_name="Charizard EX")
        candidate = _candidate(card_name="Charizard ex")

        score, rejection = _candidate_score_and_rejection(identity, candidate)

        self.assertIsNone(score)
        self.assertEqual(rejection, REJECT_CARD_NAME)
        self.assertFalse(_candidate_matches(identity, candidate))

    def test_contextual_retrieval_combines_clues_without_unverified_set_filter(self):
        session = _Session([{"data": [_candidate()]}])
        resolver = PokeTraceIdentityResolver(_provider(session))

        result = resolver.resolve_identity(_identity())

        self.assertTrue(result.matched)
        params = session.calls[0][1]["params"]
        self.assertEqual(params["search"], "Charizard Base Set 4/102")
        self.assertEqual(params["card_number"], "4/102")
        self.assertNotIn("set", params)
        self.assertEqual(resolver.counters.contextual_searches, 0)
        self.assertEqual(resolver.counters.canonical_contextual_searches, 1)

    def test_candidate_field_counters_are_independent_of_rejection_order(self):
        wrong_name = _candidate(card_name="Blastoise")
        session = _Session([{"data": [wrong_name]}, {"data": []}])
        resolver = PokeTraceIdentityResolver(_provider(session))

        result = resolver.resolve_identity(_identity())

        self.assertFalse(result.matched)
        self.assertEqual(resolver.counters.candidates_name_matched, 0)
        self.assertEqual(resolver.counters.candidates_set_matched, 1)
        self.assertEqual(resolver.counters.candidates_card_number_matched, 1)
        self.assertEqual(resolver.counters.candidates_set_number_matched, 1)
        self.assertEqual(resolver.counters.candidates_failing_only_name, 1)
        self.assertGreaterEqual(
            resolver.counters.candidate_queries_without_exact_match, 1
        )
        self.assertEqual(resolver.counters.zero_candidate_queries, 1)

    def test_primed_identity_snapshot_counts_avoided_market_request(self):
        session = _Session([{"data": [_candidate()]}])
        market = _provider(session)
        resolver = PokeTraceIdentityResolver(market)

        resolved = resolver.resolve_identity(_identity())
        snapshot = market.snapshot_for(resolved.identity)

        self.assertIsNotNone(snapshot.us_values)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(market.counters.primed_market_calls_avoided, 1)


if __name__ == "__main__":
    unittest.main()
