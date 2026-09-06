# V4 — external fair-value authority — 2026-09-06

## Status

```text
PR                         #255 MERGED
branch                     v4-external-fair-value-authority-20260906
base at development        23e8e9904072d986e24d2a8fbccaa87568851f69
validated head             e886c649eea8633d39585aabca8fff0b58be4324
production merge           9d3bb1b84d22c1534c24d7c58c5897ecce4b817f
merge parents              00e5502fb15c9a89d67a55b70cd566099911bcdb + e886c649...
live GitHub main later     dfc548021c561479cc8758e2949d2c4629388d9d / net-zero tree vs 9d3bb1
Fast Lane post-merge       34037049703 SUCCESS
first Main Scanner         34037313029 / #3936 / exact 9d3bb1... / SUCCESS
```

GitHub merge signature on `9d3bb1...` is verified. The user explicitly authorized deployment despite the active 2026-09-06 weekly auction window. No purchase, bid, checkout or payment automation was introduced.

After #255, `main` advanced through an accidental placeholder + revert to `dfc548...`. GitHub compare from `9d3bb1...` to `dfc548...` shows **0 changed files**, so the runtime tree is unchanged.

## Motivation

GCC is the venue where opportunities are discovered, but its displayed sales history can be stale, sparse or unrepresentative of the current global market. That history must not anchor V4 fair value.

Concrete edge: a GCC buyer may see old sales around 18–25 EUR and consider a 30 EUR live bid expensive, while recent exact external SOLD evidence can place the same card/grade/language around 45–50 EUR. V4 must detect the current global-market discount rather than reproduce the stale GCC anchor.

## Production policy

For V4 economics:

- GCC remains authoritative for the live listing itself: URL, exact card identity fields, grader, grade, language, current price and auction timing.
- GCC historical sales remain observable for diagnostics/Robot KB only.
- GCC historical sales cannot create, anchor, confirm or cap fair value.
- A buy opportunity requires strong external market evidence through the existing strict external-provider tree.
- External `PENDING`, `WEAK`, provider failure or unavailable evidence fails closed; it cannot fall back to historical `GCC_ONLY` economics.
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

The first natural Main Scanner on the exact production merge is **`34037313029`**, run #3936, completed **SUCCESS**.

```text
head                              9d3bb1b84d22c1534c24d7c58c5897ecce4b817f
fixed discovery                   3259 listings / 33 pages / COMPLETE
auction rows / timers             100 / 100
auction scope                     COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
external deterministic candidates 9
external usable STRONG            0 / 9
PokeTrace                         0 STRONG / 9 WEAK
PSA APR                           HTTP 403 -> breaker fail-closed
eBay                              attempted 16 / sufficient 0 / insufficient 11 / unavailable 5 / errors 5
final opportunities               0
```

### #254 proof inside the same run

Affected eBay workers reproduced the pre-#254 body failure, but not the #253 hard-timeout regression:

1. `body_inner_text` reaches ~2500 ms timeout ;
2. #251 `body_text_content` reaches ~700 ms and errors ;
3. #254 executes at most four `items_item_text` reads with `inner_text(timeout=600)` ;
4. result is returned/preserved around ~7.6–7.9 s on the sampled workers ;
5. no new 30 s hard-timeout from unbounded structured salvage appears.

Therefore #254 is **live-proven** for the exact regression it targeted.

### #255 proof inside the same run

All nine deterministic external candidates lacked STRONG usable evidence. V4 created **0 opportunities**. Historical/internal `GCC_ONLY` labels can still appear in telemetry, but they no longer create fair value or an economic opportunity. This is positive live proof of the #255 fail-closed behavior for weak/unavailable external evidence.

The sample did **not** contain a STRONG external case, so it does not live-prove positive `EXTERNAL_RESCUE`; that path remains covered by focused tests.

Run `34037829669` was later CANCELLED and must not be cited as the first/authoritative live proof.

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

See `docs/external-sold-coverage-phase-20260906.md`.
