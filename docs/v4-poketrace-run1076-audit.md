# V4 PokeTrace run #1076 / PR #124 audit — updated 18 August 2026

## Original production symptom

First production run on post-PR #123 `main`:

- workflow run `32041486642` / run #1076: SUCCESS;
- TCGdex: `11 attempted | 8 exact | 2 no-match | 1 ambiguous | 0 errors`;
- PokeTrace: `8 attempted | 0 exact | 8 no-match | 0 errors`.

The failure therefore occurred after deterministic TCGdex identity had already succeeded.

## Reuse audit

The current V5 PokeTrace market provider already had a stronger retrieval contract while remaining market-only in the normal identity path. In `v5/market_values/poketrace.py`, market lookup sends:

- a bounded `search` term;
- structured `card_number`;
- structured `game` (`pokemon`, `pokemon-japanese`, etc.);
- `market` and `product_type=single`.

V4 had not recovered those retrieval fields. It sent a combined free-text query such as `Lapras 177/172` with `market=US`, but no `card_number` and no `game`.

## PR #124 recovery

PR #124 backported only that proven V5 market-retrieval contract:

- EN -> `game=pokemon`;
- JA -> `game=pokemon-japanese`;
- canonical collector number sent as structured `card_number`;
- `search` reduced to the already-TCGdex-proven canonical/provider-facing card name;
- FR/DE/etc. are not queried as exact graded PokeTrace records because V4's exact-language acceptance gate cannot accept them; APR/eBay fallback remains available.

The existing V4 candidate acceptance function still decides exactness after retrieval. Set, collector number, language/game, sensitive commercial dimensions, grader and grade gates remain fail-closed. PokeTrace does not become an identity resolver.

PR #124 merged into production at:

```text
c0dc89edc17cad475219cf4b18b1d13561460d71
```

Validation before merge: run `32043507608`, job `95426837095` — SUCCESS; `676/676` tests PASS, compile/YAML/diff PASS, discovery comparison read-only PASS.

## First production run after PR #124

Workflow run `32112552901` on the exact merge SHA above: SUCCESS.

- TCGdex: `14 attempted | 9 exact | 1 no-match | 4 ambiguous | 0 errors`;
- PokeTrace: `3 attempted | 0 exact | 3 no-match | 0 errors`;
- final opportunities: `0`.

Conclusion: PR #124 improved request applicability/budget use (`8` routine attempts in #1076 -> `3` EN/JA attempts in this sample), but **did not yet recover a PokeTrace exact match**. Therefore the original structured-retrieval defect was real but incomplete as a root-cause explanation.

The next phase must identify the final rejection reason for those three provider attempts before changing matching. The current V5 deterministic set-bridge/provider-alias lineage is the first capability to audit if the blocker is PokeTrace set nomenclature.

## Safety

No fuzzy matching, translation-as-proof, ask-as-SOLD conversion, fair-value threshold change, automatic purchase, bid, checkout or payment is introduced. PR #8 remains experimental and unmerged.
