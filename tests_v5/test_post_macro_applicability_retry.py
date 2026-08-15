from __future__ import annotations

import unittest

from v5.live_raw_pipeline_catalog import _refresh_post_macro_applicability
from v5.microvariants import (
    LocalMicrovariantValidator,
    MicrovariantApplicability,
    MICROVARIANT_APPLICABLE,
    MICROVARIANT_APPLICABILITY_UNKNOWN,
)
from v5.models import CardIdentity
from v5.variant_semantics import FINISH_HOLO


class FakeResolver:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def resolve_microvariant_applicability(self, identity):
        self.calls += 1
        return self.result


def identity() -> CardIdentity:
    return CardIdentity(
        game="Pokémon TCG",
        card_name="Examplemon",
        set="Example Set",
        card_number="12/100",
        language="English",
    )


class PostMacroApplicabilityRetryTests(unittest.TestCase):
    def test_exact_tcgdex_single_finish_can_reach_existing_nonblocking_gate(self):
        original = MicrovariantApplicability()
        exact = MicrovariantApplicability(
            status=MICROVARIANT_APPLICABLE,
            source="TCGDEX_EXACT",
            single_finish=FINISH_HOLO,
            finish_proven_single=True,
            edition_proven_single=True,
        )
        resolver = FakeResolver(exact)

        refreshed = _refresh_post_macro_applicability(
            resolver, identity(), original
        )
        resolution = LocalMicrovariantValidator().resolve(identity(), refreshed)

        self.assertIs(refreshed, exact)
        self.assertEqual(resolver.calls, 1)
        self.assertFalse(resolution.blocks_economics)

    def test_provider_or_nonexact_result_cannot_unblock(self):
        original = MicrovariantApplicability()
        provider_only = MicrovariantApplicability(
            status=MICROVARIANT_APPLICABLE,
            source="POKETRACE_PROVIDER_METADATA",
            single_finish=FINISH_HOLO,
            finish_proven_single=True,
            edition_proven_single=True,
        )
        resolver = FakeResolver(provider_only)

        refreshed = _refresh_post_macro_applicability(
            resolver, identity(), original
        )
        resolution = LocalMicrovariantValidator().resolve(identity(), refreshed)

        self.assertIs(refreshed, original)
        self.assertEqual(refreshed.status, MICROVARIANT_APPLICABILITY_UNKNOWN)
        self.assertTrue(resolution.blocks_economics)

    def test_existing_catalog_decision_is_not_requeried(self):
        existing = MicrovariantApplicability(
            status=MICROVARIANT_APPLICABLE,
            source="TCGDEX_EXACT",
            single_finish=FINISH_HOLO,
            finish_proven_single=True,
            edition_proven_single=True,
        )
        resolver = FakeResolver(MicrovariantApplicability())

        refreshed = _refresh_post_macro_applicability(
            resolver, identity(), existing
        )

        self.assertIs(refreshed, existing)
        self.assertEqual(resolver.calls, 0)

    def test_unknown_exact_result_stays_fail_closed(self):
        original = MicrovariantApplicability()
        exact_but_unknown = MicrovariantApplicability(
            status=MICROVARIANT_APPLICABILITY_UNKNOWN,
            source="TCGDEX_EXACT",
        )
        resolver = FakeResolver(exact_but_unknown)

        refreshed = _refresh_post_macro_applicability(
            resolver, identity(), original
        )
        resolution = LocalMicrovariantValidator().resolve(identity(), refreshed)

        self.assertIs(refreshed, exact_but_unknown)
        self.assertTrue(resolution.blocks_economics)

    def test_invalid_resolver_result_is_ignored(self):
        original = MicrovariantApplicability()
        resolver = FakeResolver(object())

        refreshed = _refresh_post_macro_applicability(
            resolver, identity(), original
        )

        self.assertIs(refreshed, original)
        self.assertEqual(resolver.calls, 1)

    def test_missing_retry_capability_is_noop(self):
        original = MicrovariantApplicability()

        refreshed = _refresh_post_macro_applicability(
            object(), identity(), original
        )

        self.assertIs(refreshed, original)


if __name__ == "__main__":
    unittest.main()
