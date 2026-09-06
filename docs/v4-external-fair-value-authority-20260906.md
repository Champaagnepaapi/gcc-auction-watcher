# V4 — external fair-value authority — 2026-09-06

## Motivation

GCC is the venue where opportunities are discovered, but its displayed sales history can be stale, sparse or unrepresentative of the current global market. That history must not anchor V4 fair value.

Concrete edge: a GCC buyer may see old sales around 18–25 EUR and consider a 30 EUR live bid expensive, while recent exact external SOLD evidence can place the same card/grade/language around 45–50 EUR. V4 must detect the current global-market discount rather than reproduce the stale GCC anchor.

## Policy

For V4 economics:

- GCC remains authoritative for the live listing itself: URL, exact card identity fields, grader, grade, language, current price and auction timing.
- GCC historical sales remain observable for diagnostics/Robot KB only.
- GCC historical sales cannot create, anchor, confirm or cap fair value.
- A buy opportunity requires strong external market evidence through the existing strict external-provider tree.
- External `PENDING`, `WEAK`, provider failure or unavailable evidence fails closed; it cannot fall back to `GCC_ONLY` economics.
- Existing terminal GCC safety rejection remains terminal and is not bypassed.
- Identity rules, SOLD semantics, provider budgets, notification thresholds and transaction prohibition are unchanged.

## Implementation

`v4_external_fair_value_authority.py` wraps the existing `watcher.arbitrate_market_evidence` at runtime. For non-terminal listings it presents arbitration with an economic GCC view containing no sales, no GCC estimate and no GCC opportunity. The existing external arbitration then remains responsible for producing an `EXTERNAL_RESCUE` only when its own evidence is sufficiently strong and buyable.

This is deliberately narrower than adding a new market provider. PriceCharting can be a discovery/reference source, but its V5 official API integration returns current guide values rather than item-level SOLD history and requires a token. It is therefore not promoted above exact recent SOLD evidence in this V4 change.

## Safety / deployment

Base production SHA at branch creation:

`23e8e9904072d986e24d2a8fbccaa87568851f69`

The change is developed on branch:

`v4-external-fair-value-authority-20260906`

Do not merge/deploy while the 2026-09-06 GCC weekly auctions are active. No bid, checkout or payment automation is introduced.

## Validation required before merge

- focused tests for GCC economic neutralization and terminal rejection preservation;
- V4 regression suite;
- compile/import check;
- workflow/diff review;
- read-only comparison on live/representative auction inventory after the active auction window;
- verify that a Poochyena-like case becomes `EXTERNAL_RESCUE` when recent strong external SOLD evidence is available and remains fail-closed when providers are unavailable.
