from __future__ import annotations

import unittest

from v5.identity_observability import CoordinateState, UnresolvedIdentityDiagnostic
from v5.pokemonpricetracker_identity_shadow import (
    PokemonPriceTrackerIdentityShadow,
)


class FakeResponse:
    def __init__(self, payload, *, status=200, consumed=4, remaining=19000):
        self._payload = payload
        self.status_code = status
        self.headers = {
            "X-Api-Calls-Consumed": str(consumed),
            "X-Ratelimit-Daily-Remaining": str(remaining),
        }

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def diag(*, set_name="Evolving Skies", name="Umbreon VMAX", number="215/203"):
    return UnresolvedIdentityDiagnostic(
        record=9,
        item_id="item-9",
        title="test listing",
        card_name=name,
        set_name=set_name,
        card_number=number,
        language="English",
        final_status="INSUFFICIENT",
        coordinates=CoordinateState(
            name="known",
            set_name="known" if set_name else "missing",
            number="known",
            denominator="known" if "/" in number else "missing",
        ),
        reason_code="SET_UNPROVEN" if not set_name else "UNKNOWN",
    )


class PokemonPriceTrackerIdentityShadowTests(unittest.TestCase):
    def test_known_set_exact_observation_is_shadow_only(self):
        original = diag()
        session = FakeSession([
            FakeResponse({"data": [{
                "name": "Umbreon VMAX (Alternate Art Secret)",
                "setName": "Evolving Skies",
                "cardNumber": "215/203",
                "externalCatalogId": "swsh7-215",
            }]})
        ])
        shadow = PokemonPriceTrackerIdentityShadow(
            enabled=True, api_key="secret", session=session, interval_seconds=0
        )

        result = shadow.observe_one(original)

        self.assertEqual(result.status, "EXACT_SET_NUMBER_SHADOW")
        self.assertEqual(result.external_catalog_id, "swsh7-215")
        self.assertIn("NOT_ACCEPTANCE", result.proof_level)
        self.assertEqual(original.set_name, "Evolving Skies")
        self.assertEqual(original.final_status, "INSUFFICIENT")
        self.assertEqual(shadow.counters.exact_set_number_observations, 1)

    def test_missing_set_can_only_report_unique_candidate(self):
        original = diag(set_name="", name="Riolu", number="215/198")
        session = FakeSession([
            FakeResponse({"data": [{
                "name": "Riolu - Illustration Rare",
                "setName": "Scarlet & Violet",
                "cardNumber": "215/198",
                "externalCatalogId": "sv1-215",
            }]})
        ])
        shadow = PokemonPriceTrackerIdentityShadow(
            enabled=True, api_key="secret", session=session, interval_seconds=0
        )

        result = shadow.observe_one(original)

        self.assertEqual(result.status, "UNIQUE_NAME_NUMBER_SET_SHADOW")
        self.assertEqual(result.recovered_set, "Scarlet & Violet")
        self.assertIn("SET_CANDIDATE_NOT_ACCEPTANCE", result.proof_level)
        self.assertIsNone(original.set_name or None)
        self.assertEqual(original.final_status, "INSUFFICIENT")

    def test_multiple_candidates_are_ambiguous(self):
        original = diag(set_name="", name="Pikachu", number="35/108")
        session = FakeSession([
            FakeResponse({"data": [
                {"name": "Pikachu", "setName": "Set A", "cardNumber": "35/108"},
                {"name": "Pikachu", "setName": "Set B", "cardNumber": "35/108"},
            ]})
        ])
        shadow = PokemonPriceTrackerIdentityShadow(
            enabled=True, api_key="secret", session=session, interval_seconds=0
        )

        result = shadow.observe_one(original)

        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(shadow.counters.ambiguous, 1)

    def test_wrong_number_is_no_match(self):
        session = FakeSession([
            FakeResponse({"data": [{
                "name": "Umbreon VMAX",
                "setName": "Evolving Skies",
                "cardNumber": "214/203",
            }]})
        ])
        shadow = PokemonPriceTrackerIdentityShadow(
            enabled=True, api_key="secret", session=session, interval_seconds=0
        )
        result = shadow.observe_one(diag())
        self.assertEqual(result.status, "NO_MATCH")

    def test_missing_quota_header_fails_closed(self):
        response = FakeResponse({"data": []})
        del response.headers["X-Api-Calls-Consumed"]
        shadow = PokemonPriceTrackerIdentityShadow(
            enabled=True,
            api_key="secret",
            session=FakeSession([response]),
            interval_seconds=0,
        )

        result = shadow.observe_one(diag())

        self.assertIsNone(result)
        self.assertEqual(shadow.counters.unavailable, 1)
        self.assertEqual(shadow.counters.calls, 1)

    def test_disabled_shadow_never_calls_provider(self):
        session = FakeSession([])
        shadow = PokemonPriceTrackerIdentityShadow(
            enabled=False, api_key="secret", session=session, interval_seconds=0
        )
        shadow.observe([diag()])
        self.assertEqual(session.calls, [])
        self.assertEqual(shadow.counters.calls, 0)

    def test_render_explicitly_states_no_acceptance_or_variant_effect(self):
        shadow = PokemonPriceTrackerIdentityShadow(enabled=False, api_key=None)
        rendered = shadow.render()
        self.assertIn("changes identity acceptance: false", rendered)
        self.assertIn("changes microvariant gates: false", rendered)
        self.assertIn("provider candidate proves finish/edition: false", rendered)


if __name__ == "__main__":
    unittest.main()
