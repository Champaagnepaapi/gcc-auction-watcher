# Japan Edge — external-first Mercari + SNKRDUNK — 2026-09-06

## Scope

Branch: `v4-jp-market-providers-20260906`

Stacked PR: #256 on top of PR #255. Nothing in this phase is merged to `main` yet.

## Economic policy

- GCC supplies strict Japanese PSA 10 identity seeds only.
- GCC historical prices are ignored for fair value.
- Fair value requires strong external graded SOLD evidence.
- PokeTrace exact graded SOLD is the bounded prefilter.
- Promising exact active asks receive final confirmation through the existing eBay SOLD family + PSA APR tree where available.
- External unavailable/weak evidence fails closed.

## Marketplace semantics

### Mercari Japan

Mercari already existed in Japan Edge. This phase hardens availability:

- explicit sold/fulfilled page => rejected;
- explicit active purchase control => ASK eligible for identity/economic checks;
- ambiguous availability => fail-closed;
- ASK never becomes SOLD.

Mercari's official overseas-transaction support uses approved cross-border EC partners; sellers ship to a designated Japanese address and the partner handles overseas shipment/export/customs. No automatic purchase is implemented.

### SNKRDUNK

SNKRDUNK is added as a read-only ASK provider.

- explicit sold page => rejected;
- explicit active purchase control => ASK eligible;
- ambiguous availability => fail-closed;
- Switzerland is not claimed as a supported direct destination by the robot;
- any Japanese forwarding/warehouse route remains an operator-side/manual compatibility check.

## Safety

- Pokémon single cards only;
- exact identity remains mandatory;
- no fuzzy proof;
- no buy/bid/checkout/payment;
- no secrets added;
- no current auction/live listing is treated as SOLD.

## Validation

Implementation head before this documentation commit: `c49ef9342c5494ada178f1bdac882d31d82d3081`.

GitHub Actions:

```text
workflow : Japan Edge Offline Validation
run      : 34037590449
job      : 101498384043
result   : SUCCESS
unit     : 31 tests PASS
compile  : PASS
YAML     : PASS
diff     : PASS
```

Live Mercari/SNKRDUNK extraction coverage is not yet claimed; the phase is draft and fail-closed until a dedicated read-only live proof is obtained.
