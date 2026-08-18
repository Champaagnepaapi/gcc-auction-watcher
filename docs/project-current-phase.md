# Current phase — post-PR #124 provider rejection diagnosis

Production `main`: `c0dc89edc17cad475219cf4b18b1d13561460d71` (merge PR #124).

Diagnostic branch: `diag/v4-provider-rejection-observability-20260818`.

## Verified live state

Production run `32112552901` on `c0dc89edc17cad475219cf4b18b1d13561460d71` completed successfully.

- TCGdex: `14 attempted | 9 exact | 1 no-match | 4 ambiguous | 0 errors`.
- PokeTrace: `3 attempted | 0 exact | 3 no-match | 0 errors`.
- final opportunities: `0`.
- no purchase, bid, checkout or payment occurred.

PR #124 correctly stopped spending PokeTrace requests on unsupported exact-market languages and sends the V5-proven structured `card_number` + `game` fields for EN/JA. The first production sample nevertheless remained `0/3` exact, so structured retrieval alone is not the complete root cause.

## Current mission

Add bounded diagnostics around the **already-final** V4 TCGdex and PokeTrace gates so the next production run identifies:

1. the exact cards behind current TCGdex `NO_MATCH` / `AMBIGUOUS` outcomes and their final reason codes;
2. whether each PokeTrace miss is caused by zero provider candidates, card number, set nomenclature, language/game, or the existing sensitive-dimension hardening.

The diagnostics log only public card/provider identity fields. They do not change matching, valuation, provider budgets, notification decisions, state, fair value or `max_recommended`.

After evidence is captured, reuse the existing V5 deterministic PokeTrace set-bridge / provider-alias lineage if it is actually the blocker rather than inventing a new heuristic.

PR #8 remains experimental and must not be merged into `main` without explicit user authorization.
