# V4 — external fair-value authority — 2026-09-06

## Status

```text
PR                         #255 MERGED
branch                     v4-external-fair-value-authority-20260906
base at development        23e8e9904072d986e24d2a8fbccaa87568851f69
validated head             e886c649eea8633d39585aabca8fff0b58be4324
production merge           9d3bb1b84d22c1534c24d7c58c5897ecce4b817f
merge parents              00e5502fb15c9a89d67a55b70cd566099911bcdb + e886c649...
Fast Lane post-merge       34037049703 SUCCESS
first Main Scanner         34037829669 / exact 9d3bb1... / natural external dispatch
```

GitHub merge signature on `9d3bb1...` is verified. The user explicitly authorized deployment despite the active 2026-09-06 weekly auction window. No purchase, bid, checkout or payment automation was introduced.

## Motivation

GCC is the venue where opportunities are discovered, but its displayed sales history can be stale, sparse or unrepresentative of the current global market. That history must not anchor V4 fair value.

Concrete edge: a GCC buyer may see old sales around 18–25 EUR and consider a 30 EUR live bid expensive, while recent exact external SOLD evidence can place the same card/grade/language around 45–50 EUR. V4 must detect the current global-market discount rather than reproduce the stale GCC anchor.

## Production policy

For V4 economics:

- GCC remains authoritative for the live listing itself: URL, exact card identity fields, grader, grade, language, current price and auction timing.
- GCC historical sales remain observable for diagnostics/Robot KB only.
- GCC historical sales cannot create, anchor, confirm or cap fair value.
- A buy opportunity requires strong external market evidence through the existing strict external-provider tree.
- External `PENDING`, `WEAK`, provider failure or unavailable evidence fails closed; it cannot fall back to `GCC_ONLY` economics.
- Existing terminal GCC safety rejection remains terminal and is not bypassed.
- Identity rules, SOLD semantics, provider budgets, notification thresholds and transaction prohibition are unchanged.

## Implementation

`v4_external_fair_value_authority.py` wraps the existing `watcher.arbitrate_market_evidence` at runtime. For non-terminal listings it presents arbitration with an economic GCC view containing no sales, no GCC estimate and no GCC opportunity. The existing external arbitration remains responsible for producing an `EXTERNAL_RESCUE` only when its own evidence is sufficiently strong and buyable.

This is deliberately narrower than adding a new market provider. PriceCharting can be a discovery/reference source, but its V5 official API integration returns guide values rather than item-level SOLD history and requires a token. It is therefore not promoted above exact recent SOLD evidence in this V4 change.

## Validation

Exact head `e886c649eea8633d39585aabca8fff0b58be4324`:

```text
V4 Auction Discovery Validation   34036063564 SUCCESS
V4 Global Market Offline          34036063610 SUCCESS
Robot KB local PostgreSQL         34036063594 SUCCESS
focused policy tests              PASS
workflow / compile / diff review  PASS via CI gates
```

Focused policy coverage proves:
- GCC economic neutralization ;
- terminal GCC rejection preservation ;
- external PENDING/WEAK/unavailable remains fail-closed ;
- strong external evidence can still use the existing external rescue path ;
- no transaction capability is introduced.

## Post-merge live proof

Fast Lane `34037049703` completed SUCCESS on exact production `9d3bb1...`.

The first Main Scanner observed on this SHA is `34037829669`, launched naturally by the external `workflow_dispatch` cadence. At documentation preparation time it was still pending. Do not claim complete Main Scanner live proof until this exact run completes and its logs are audited.

Required live audit after completion:
- #254 eBay body/structured salvage stages and absence of a new 30 s hard-timeout regression ;
- eBay attempted/sufficient/insufficient/unavailable/errors ;
- PSA APR HTTP 403 + breaker state ;
- TCGdex/PokeTrace state ;
- fixed/external backlog and auction scope ;
- no `GCC_ONLY` economics ;
- weak/pending/error external evidence fail-closed ;
- external strong rescue still possible if the sample contains such a case.

## Safety

- individual Pokémon cards only ;
- no SOLD semantic relaxation ;
- no identity, language, grader, grade or microvariant relaxation ;
- no provider cap/budget expansion ;
- no WAF/anti-bot bypass ;
- no Robot KB durable write ;
- V5/PR #8 untouched ;
- no purchase, bid, offer, checkout or payment.

## Next phase

The main remaining economic bottleneck is **coverage of exact external SOLD evidence**, not GCC discovery. New work should be Robot-KB/read-only first and reuse existing eBay/Fanatics/Cardova research before any new provider integration or V4 economic use.
