# Current phase — PokeTrace zero-candidate retrieval fix

Production `main`: `20c5e5317974577180786947f8eb76774360a3b1` (merge PR #125).

Fix branch: `fix/v4-poketrace-preserve-provider-number-20260818`.

## Verified live state

Production run `32115020811` on `20c5e5317974577180786947f8eb76774360a3b1` completed successfully.

- TCGdex: `21 attempted | 13 exact | 1 no-match | 7 ambiguous | 0 errors`.
- PokeTrace: `2 attempted | 0 exact | 2 no-match | 0 errors`.
- final opportunities: `0`.
- no purchase, bid, checkout or payment occurred.

PR #125 proved that both actual Japanese PokeTrace misses failed **before local matching**:

- `Team Rocket's Meowth #109/098` -> `provider_candidates=0`;
- `Groudon #069/062` -> `provider_candidates=0`.

Therefore the deterministic set bridge is not the immediate blocker: there is no provider candidate to bridge.

## Root cause

PR #124 reused V5's matching normalizer for the provider request itself. That normalizer intentionally canonicalizes numeric equality by stripping leading zeroes, so the request sent:

```text
109/098 -> 109/98
069/062 -> 69/62
```

PokeTrace's own public catalog exposes those exact cards as `109/098` and `069/062` under `game=pokemon-japanese`, market US. The provider's exact `card_number` filter must therefore receive the proven printed/catalog surface, while V4 may continue using zero-insensitive normalization only **after retrieval** for acceptance.

## Current change

`v4_poketrace_market_retrieval.py` now separates:

1. provider retrieval number -> NFKC/label/whitespace cleanup only, leading zeroes preserved;
2. local matching number -> existing numeric-safe normalization unchanged.

Focused regressions cover the two live blocker shapes (`069/062`, `109/098`) plus alphanumeric surface preservation. No set alias, fuzzy search, translation-as-proof or identity relaxation is introduced.

## Next gate

Run CI first. If green, open the PR and merge only with user authorization. Then inspect the first production run on the merge SHA:

- provider candidate count for the Japanese exact identities;
- PokeTrace exact/strong result after the existing strict card/set/language/variant/grader/grade gates;
- TCGdex blockers remain separate fail-closed work.

PR #8 remains experimental and must not be merged into `main` without explicit user authorization.
