"""Restore the Magi native TCGdex proof budget to the resolver baseline.

The generic Japanese proof resolver is designed with a 60-request default, but
the Magi-native scanner overrides it to 40.  Live run 34113005261 exhausted that
40-call ceiling and rejected 13 otherwise eligible listings as
TCGDEX_BUDGET_EXHAUSTED.  This installer restores 60 for the Magi native lane.

No identity, language, grader, grade, set/name/number, microvariant or economic
gate changes.  Requests remain bounded and read-only; recovery-only Magi budgets
stay separate and unchanged.
"""
from __future__ import annotations

import v4_global_marketplace_magi_native_identity as native


MAGI_NATIVE_TCGDEX_REQUEST_BUDGET = 60
_INSTALLED = False


def install_global_marketplace_magi_native_budget() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    native._MAX_TCGDEX_JA_REQUESTS = MAGI_NATIVE_TCGDEX_REQUEST_BUDGET
    _INSTALLED = True
