# V4 PokeTrace run #1076 audit — 17 August 2026

## Production symptom

First production run on post-PR #123 `main`:

- workflow run `32041486642` / run #1076: SUCCESS;
- TCGdex: `11 attempted | 8 exact | 2 no-match | 1 ambiguous | 0 errors`;
- PokeTrace: `8 attempted | 0 exact | 8 no-match | 0 errors`.

The failure therefore occurred after deterministic TCGdex identity had already succeeded.

## Reuse audit

The current V5 PokeTrace market provider already solved the retrieval problem and remains market-only in the normal identity path. In `v5/market_values/poketrace.py`, market lookup sends:

- a bounded `search` term;
- structured `card_number`;
- structured `game` (`pokemon`, `pokemon-japanese`, etc.);
- `market` and `product_type=single`.

V4 had not recovered that provider contract. It sent a combined free-text query such as `Lapras 177/172` with `market=US`, but no `card_number` and no `game`. This is particularly important for Japanese cards because PokeTrace separates the Japanese catalogue as `pokemon-japanese`.

This is a retrieval defect, not evidence that the eight TCGdex identities were bad and not evidence that PokeTrace has no market record.

## Recovery implemented on this branch

`v4_poketrace_market_retrieval.py` backports only the proven V5 market-retrieval contract:

- EN -> `game=pokemon`;
- JA -> `game=pokemon-japanese`;
- canonical collector number sent as structured `card_number`;
- `search` reduced to the already-TCGdex-proven canonical/provider-facing card name;
- FR/DE/etc. are not queried as exact graded PokeTrace records because V4's existing exact-language acceptance gate cannot accept them; APR/eBay fallback remains available.

The existing V4 candidate acceptance function still decides exactness after retrieval. Set, collector number, language/game, sensitive commercial dimensions, grader and grade gates are unchanged. PokeTrace does not become an identity resolver.

## Safety

No fuzzy matching, translation-as-proof, ask-as-SOLD conversion, fair-value threshold change, automatic purchase, bid, checkout or payment is introduced.

No production live run is claimed for this branch. A live production run requires a separate explicit user authorization after merge; this branch is validated through the existing V4 PR CI first.
