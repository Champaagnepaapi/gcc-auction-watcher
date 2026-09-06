# V4 source roles / PriceCharting — 2026-09-06

## Scope

PR #257, branch `fix/v4-source-role-pricecharting-20260906`.

This phase separates **where the robot can buy** from **how the robot values a card**.

## Opportunity sources

Current Global adapters:

- GCC
- Fanatics
- COMC
- Magi
- Cardova

Their listing price is only a candidate acquisition cost. `FIXED_ASK` and `AUCTION_SNAPSHOT_LE5` may be evaluated as offers; neither is a SOLD record. A marketplace listing cannot create, anchor, confirm, cap or conflict-block fair value.

Mercari/SNKRDUNK remain in separate draft PR #256. Active eBay opportunity discovery is not implemented in #257 and must be added later as another independent adapter.

## Valuation sources

Priority in #257:

1. strong compatible SOLD-derived aggregate evidence from the existing PokeTrace / PokemonPriceTracker path;
2. PSA APR exact PSA evidence where applicable;
3. bounded PriceCharting guide fallback.

Direct eBay SOLD page scraping loses fair-value authority in #257. Existing legacy transport code may remain in the repository for compatibility, but the source-role wrapper disables it during economic valuation.

## GCC history

PR #255 is already merged on `main`. GCC historical sales are diagnostic/Robot-KB context only for economics. They cannot create, anchor, confirm or cap fair value.

Global #257 extends the same rule explicitly: `gcc_fair_eur` may remain in diagnostic payloads but is not used in the marketplace decision.

## PriceCharting semantics

PriceCharting is treated as a **price guide**, not as item-level SOLD evidence.

- no synthetic `ComparableSale` rows;
- no synthetic SOLD count;
- exact PSA 10 guide bucket only may be automatic evidence;
- generic grade 9/8 buckets remain WEAK/context-only because grader identity is not proven by those buckets;
- PriceCharting-only economic path requires at least 40% discount;
- a PriceCharting guide cannot override a strong SOLD-derived provider or resolve a material conflict between strong correlated SOLD providers;
- public read-only guide retrieval is bounded and does not require a stored token; official Prices API remains optional if a token is supplied through environment only.

## Architecture decision

Keep **one Global orchestrator with independent marketplace adapters**, rather than one complete bot per vault.

Reason: adapters remain isolated at retrieval/normalization level, while strict identity, valuation providers, FX, deduplication, economic gates and notification semantics stay single-source-of-truth. Separate complete bots would duplicate these safety-critical rules and create drift.

## Safety

Unchanged:

- Pokémon single cards only;
- strict commercial identity / microvariant fail-closed;
- ASK/current auction/disappearance != SOLD;
- no automatic purchase, bid, checkout or payment;
- no secrets in repository/logs;
- PR #8/V5 remains experimental and non-merged.

## Validation gate

Before merge:

- full V4 suite;
- focused Global suite;
- targeted PriceCharting/source-role tests;
- Python compile;
- workflow YAML parse;
- `git diff --check`;
- Global marketplace bootstrap live read-only with notifications and transactions disabled;
- explicit live assertions that marketplace listings have no valuation authority and GCC history has no economic authority.

Do not merge PR #257 without explicit user authorization.
