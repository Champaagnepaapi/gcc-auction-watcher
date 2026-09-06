# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel re-vérifié le **6 septembre 2026** après les merges production #253/#254/#255 et le premier Main Scanner exact post-#255. Le code/Git/GitHub réel reste prioritaire sur ce document.

Statuts : `PROD_V4`, `MAIN_SUPPORT`, `ROBOT_KB`, `P3_ONLY`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`, `STALE_OPEN`.

## Autorité courante

```text
V4 production branch                 : main
V4 live GitHub HEAD                   : dfc548021c561479cc8758e2949d2c4629388d9d
V4 runtime tree baseline              : 9d3bb1b84d22c1534c24d7c58c5897ecce4b817f / #255
External fair-value authority         : #255 / PROD_V4 / live fail-closed proven
Bounded eBay structured salvage       : #254 / PROD_V4 / live proven
Structured eBay body-timeout salvage  : #253 / PROD_V4
PokeTrace aggregate quality           : #247 / PROD_V4
Auction pagination preservation       : #245 / PROD_V4
Auction recovery capacity             : #229/#231 / PROD_V4 / hard cap 250
Auction order hardening               : #211/#212 / PROD_V4
Future-start auction guard            : #220 + #243 / PROD_V4
V4 run registry                       : issue #235 ACTIVE / #237 MAIN_SUPPORT
eBay normal bulk result text          : #238/#239 / PROD_V4
eBay result before teardown           : #242 / PROD_V4
eBay timeout diagnostics              : #241/#250/#252 / PROD_V4
eBay same-DOM body fallback           : #251 / PROD_V4
TCGdex transport resilience           : #216/#217 / PROD_V4
TCGdex outage fallback                : #222/#224 / PROD_V4
External pending throughput           : #214 / PROD_V4
Magi native identity                  : #174/#177/#178 / PROD_V4
Global schedule watchdog              : #179 / PROD_V4
Robot KB local cutover                : #166 / ROBOT_KB / PostgreSQL Mac
Robot KB multisource                  : #180 / ROBOT_KB
P3 rarity-symbol print_run            : #207 / P3_ONLY
Cardova durable commit guard          : #210 / OPEN DRAFT / P3_ONLY
V5 expérimentale                      : PR #8 / V5_ONLY / OPEN DRAFT NON-MERGED
TCGdex source pin                     : af33c9ac882e2acfadffaf19e8083aa976d12983
```

`main` a avancé de deux commits net-zero après #255 jusqu'à `dfc548...`; la comparaison depuis `9d3bb1...` contient **0 fichier modifié**. Le runtime tree est inchangé.

## #255 — external market evidence sole fair-value authority — `PROD_V4`

Validated head `e886c649eea8633d39585aabca8fff0b58be4324`; CI `34036063564`, `34036063610`, `34036063594` SUCCESS; production merge `9d3bb1b84d22c1534c24d7c58c5897ecce4b817f`.

Contract:
- GCC = listing identity/current price/timing, not fair-value authority ;
- GCC history remains observable for diagnostics/Robot KB only ;
- external `PENDING`, `WEAK`, error or unavailable => fail-closed ;
- no economic fallback from historical `GCC_ONLY` evidence ;
- strong external evidence may still use the existing rescue path ;
- terminal GCC safety rejection remains terminal ;
- SOLD semantics, identity, provider budgets, thresholds and transaction prohibition unchanged.

### Live proof

First exact natural Main Scanner: `34037313029` / #3936 / exact `9d3bb1...` / SUCCESS.

```text
fixed discovery                   3259 / 33 pages / COMPLETE
auction rows/timers               100 / 100
auction scope                     COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
external deterministic candidates 9
usable STRONG                     0 / 9
PokeTrace                         0 STRONG / 9 WEAK
PSA APR                           HTTP 403 -> breaker
 eBay                              16 attempted / 0 sufficient / 11 insufficient / 5 unavailable / 5 errors
final opportunities               0
```

The historical/internal `GCC_ONLY` label can still occur in telemetry, but it no longer creates fair value or an opportunity. With no STRONG external sample, the run remained fail-closed. Positive `EXTERNAL_RESCUE` was not observed live in this sample and remains proven by focused tests rather than by this run.

Run `34037829669` was CANCELLED and is not live evidence.

## #254 — bounded structured eBay salvage — `PROD_V4`

Validated head `fbb7041f9fc44c338b102ec7325a6d6316f1e529`; run `34031695933` attempt 2 SUCCESS; `920 PASS / 2 skipped`; production merge `00e5502fb15c9a89d67a55b70cd566099911bcdb`.

After exact body `TimeoutError`, probe max 4 already-loaded `li.s-item` rows using `inner_text(timeout=600)`. Require non-empty EUR/€ evidence. Failure re-raises original timeout. No goto/reload/wait/provider retry. After successful salvage, canonical per-item bounded parsing remains authority.

### Live proof

Run `34037313029` exercised the real timeout path multiple times:
- `body_inner_text` ~2500 ms timeout ;
- #251 `body_text_content` ~700 ms timeout/error ;
- exactly bounded `items_item_text` probes, max 4 × ~600 ms ;
- worker result preserved around 7.6–7.9 s ;
- no new 30 s hard-timeout regression from the #253 salvage path.

This supersedes only the **unbounded salvage path** introduced by #253; it does not remove the normal #238/#239 bulk fast path.

## #253 — structured eBay body-timeout salvage — `PROD_V4`

Validated head `4ced75070cc274abf99ea59f7995d356cbb6dd77`; production merge `23e8e9904072d986e24d2a8fbccaa87568851f69`.

Reuse of same-loaded-DOM structured `li.s-item` rows after the #251 body path fails. Conservative EUR/€ gate; canonical parser remains authoritative. Natural runs exposed the unbounded `all_inner_texts()` regression, corrected by #254.

## eBay resilience chain — `PROD_V4`

- #137: navigation-timeout same-host DOM salvage precedent ;
- #175: disposable worker hard deadline ;
- #189: run-local circuit breaker ;
- #238/#239: normal-path bulk result text ;
- #241: safe stage timing ;
- #242: preserve result before teardown hangs ;
- #250: safe navigation-timeout reason diagnostic ;
- #251: bounded body `text_content(timeout=700)` fallback ;
- #252: safe parent timing summary ;
- #253: structured same-DOM salvage after body timeout ;
- #254: bounded structured salvage, fixing the post-#253 hard-timeout regression.

No WAF bypass, no provider request expansion, no SOLD/identity/economic relaxation in this chain.

## #247 — PokeTrace aggregate quality guard — `PROD_V4`

Degenerate `MATCHED + STRONG` aggregate envelopes (`<=0.01 EUR`, invalid or non-positive) are downgraded to `CLEAN_INSUFFICIENT / WEAK` and their estimate leaves the economic path. PSA APR/eBay must take over. A PokeTrace aggregate is never promoted to item-level SOLD.

## Auction discovery stack — `PROD_V4`

- #211/#212: fixed and auction discovery hardening ;
- #220/#243: future-start exclusion / rendered-page verification ;
- #229/#231: adaptive recovery after proven order drift ;
- #245: preserve hardened default `100 rows/page` ;
- recovery hard ceiling remains `250` pages ;
- auction economic cap remains `360` ;
- priority remains `<=5m -> <=12m -> <=60m`.

Do not raise caps merely to hide provider/order problems.

## TCGdex identity stack — `PROD_V4`

TCGdex remains the exact identity authority. #216/#217 add bounded transport retry + run breaker. #222/#224 add a source-pinned Japanese outage fallback only after retryable transport error and exact reviewed coordinates. `NO_MATCH`, `AMBIGUOUS`, incompatible language/finish/microvariant remain blocked.

TCGdex RAW/third-party pricing is not slab fair value.

## #214 — external pending throughput — `PROD_V4`

```text
P4 scheduling                    16/run
P4 hard ceiling                  20/run
eBay SOLD total                  16/run
fixed eBay reserve               12/run
auction eBay max                 4/run
budget-only cooldown             5 min
PSA APR max                      2/run
provider-error backoff           unchanged
```

Provider errors remain fail-visible. Do not raise caps only to drain backlog.

## Global / Magi

Global production marketplace-first stack remains separate from #255 until explicitly validated for the same economic policy. `ACTIVE_AUCTION` is non-actionable; disappearance != SOLD; correlated aggregate families remain labelled as such.

Magi #174/#177 exact native identity + #178 bounded recovery remain production authority. No name-only fallback or card-by-card alias treadmill.

## Robot KB — `ROBOT_KB`

PostgreSQL local Mac, `V4_USE=false`, automatic Neon writers OFF. Append-only immutable dated provenance. Final proven SOLD prioritized; fixed asks remain ASK; auction final SOLD preferred, snapshot <=5m only tagged fallback.

External SOLD reuse inventory:
- current eBay RapidAPI shadow exists but deliberately marks `genuine_sale_evidence=false` without independent final-price/finality proof ;
- #192/#193/#195/#196 form the historical eBay corroboration research stack ;
- #197 proved Fanatics provider rows with explicit `PAID + isComplete=true`, but the documented contract still lacks proven currency before `SALE_TRANSACTION` ;
- #198 proved anonymous headless COMC historical-sales access blocked by HTTP 403; do not bypass ;
- #199/#204/#205/#206/#208/#209/#210 form the Cardova strict SOLD/canonicalization/durable-guard stack ;
- #207 is P3-only and not merged into V4 `main` as production runtime.

No durable Cardova write without explicit operator authorization, fresh backup/locks/preflight and exact SHA.

## PriceCharting / V5

V5 contains an experimental official PriceCharting integration that returns guide values and requires a token. It is not item-level SOLD history and must not outrank exact recent SOLD. PR #8 remains `V5_ONLY`, OPEN/DRAFT/NON-MERGED and cannot be merged without explicit user authorization.

## Supersessions / stale open PRs

- #226/#228/#233 historical eBay bulk proposals are superseded by #238/#239 ;
- #234 is validation-only/inconclusive, do not merge ;
- #248 is an old navigation-timeout diagnostic predating production #250, do not revive directly ;
- #230 validation-only, do not merge ;
- #126 superseded by #127→#135 ;
- #108/#109/#110/#113/#114/#115/#138 absorbed by #139 ;
- #159 superseded functionally by #177.

## Current capability gap

The principal remaining gap is no longer GCC discovery but **coverage of strong exact external SOLD evidence**. New work must reuse the lanes above and close, explicitly and independently, all required dimensions before promotion:

```text
sale finality
final price semantics
currency
exact card identity
language
grader + grade
commercial microvariant
```

Only then may an observation become an exact `SALE_TRANSACTION` in Robot KB or be considered for future V4 economic use.

Detailed phase matrix: `docs/external-sold-coverage-phase-20260906.md`.

## Invariants de reprise

- V4/main canonique ;
- PR #8 protégée ;
- aucun achat/bid/checkout/paiement ;
- Robot KB local séparé de V4 ;
- aucune écriture durable Cardova sans autorisation explicite ;
- identité ambiguë/microvariante incertaine = fail-closed ;
- ASK, enchère live, disparition et provider outage != SOLD ;
- avant nouveau code, réutiliser d'abord les capacités recensées ici et dans le README.
