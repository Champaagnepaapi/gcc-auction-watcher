# Latest project status — 11 August 2026

> Temporary canonical status supplement. Read `README.md` first, then this file until its contents are folded into the README canonical handoff section.

## V4 production

- `main` remains the canonical production branch.
- Current production main includes the item-level GCC auction API discovery, Cron-job.org → `workflow_dispatch` scheduling, Playwright/pip caching, and the technical-ntfy noise suppression policy.
- Harmless fixed inventory drift such as `2953/2954` with healthy pagination/accounting remains log-only; structural/actionable failures still notify.
- V4 is independent from V5 and must not be replaced implicitly.

## V5 PR #8 — current state

- PR: #8
- Branch: `agent/v5-poketrace-cardmarket-market-data`
- Status: open, draft, **do not merge yet**.
- Resolver architecture remains:
  1. TCGdex principal multilingual resolver.
  2. PokeTrace Free fallback identity + RAW US market data.
  3. Pokémon TCG API fallback.
  4. Local visual matching + targeted OCR only for ambiguous/insufficient identities.
  5. JustTCG remains a candidate same-run second opinion/fallback.
  6. Scrydex/Vision remains reserved for persistent ambiguous cases after the free chain is exhausted.

### Post-Codex blockers: fixed

The latest Codex patch fixed the previously blocking issues:

- no unverified display set name is sent as PokeTrace `set=`;
- `name + set` with a missing card number can reach PokeTrace and recover the third discriminator when evidence is unique;
- complete TCGdex denominator conflicts such as `4/130` vs `004/102` are blocking;
- numerator-only `4 -> 004/102` remains allowed when deterministic;
- TCGdex deterministic set-id resolution and reason counters were added;
- local PokeTrace acceptance remains strict.

### Current-main resync + offline proof

Current `main` was merged **into V5 only** before the controlled live run.

Offline validation run: `31482959188`

- V4: **167/167**
- V5: **234/234**
- `compileall -q v5`: OK
- workflow YAML: OK
- `git diff --check`: OK
- V4 files vs current main: **IDENTICAL**
- PokeTrace live calls: 0
- secrets injected: 0
- purchases/bids/checkout/CardGrader: 0

The temporary offline CI workflow was deleted after this proof.

## Latest controlled PokeTrace Free live

Run: **`31483091017`**
Job: **`93752247632`**
Sample fingerprint: **`c48b11c284cf453b`**
Conclusion: success

The temporary push trigger used to launch exactly one controlled Free run was immediately removed. `V5 Live Raw Pipeline Diagnostic` is again **manual `workflow_dispatch` only**.

### eBay

- OAuth HTTP 200
- search results: 20
- getItem success: 20
- RAW accepted: 19

### Identity summary

- usable: **11/20**
- ambiguous: 4
- insufficient: 5
- card-name coverage: 12
- set coverage: 18
- card-number coverage: 14

The fingerprint differs from previous runs, therefore `9/20 -> 11/20` is **not** an apples-to-apples improvement claim.

### TCGdex

- requests: 16
- hits: **2**
- TCGdex-only rescues: **2**
- PokeTrace calls avoided via TCGdex: **2**
- unique set-alias resolutions: 4
- ambiguous set aliases: 1
- skipped because set/card number missing: 6
- no-match set: 5
- no-match card: 6
- catalog request failures: **3**
- denominator conflicts: 0 on this sample
- numerator-only canonicalizations: 0 on this sample
- canonical name/set/number changes: 0/0/0 on this sample

TCGdex remains principal for now, but the low `2/20` hit count plus the reason buckets/request failures need direct audit before assuming the catalogue itself is the limiting factor.

### PokeTrace identity

- identities queried: 12
- HTTP search attempts: 30
- structured strategies: 12
- broad-name: 10
- broad-number: 2
- exact matches: **0**
- ambiguous: 0
- no match: 12
- request failures: 0
- 429: 0
- unique candidates received: **189**
- name matched: 21
- set matched: 13
- card number matched: 5
- name + set matched: 2
- name + number matched: 1
- set + number matched: 3
- **name + set + number matched: 1**
- rejected only name: 2
- rejected only set: 0
- rejected only card number: 3
- rejected variant: **1**
- recovered fields: 0

### Critical new diagnosis

PokeTrace now returns a candidate for which **name + set + card number all match**, yet no exact identity is accepted and the run records **one variant rejection**.

This makes **variant semantics** the next high-value PokeTrace audit target. Do not weaken the variant gate blindly: determine whether PokeTrace and eBay/TCGdex describe the same variant using different semantics, or whether this is a genuine conflict.

Retrieval still returns many candidates (189), so the problem is no longer simply “PokeTrace returns nothing.” Structured queries are often empty while broad fallback returns candidates; query/canonical alias quality still matters.

### Visual / OCR

- visual attempts: 6
- no candidates after metadata filter: 4
- candidate scans considered: 16
- candidate scans downloaded: 7
- candidate image failures: **8**
- visual rescues: 0
- OCR attempts: 2
- OCR calls: 12
- OCR rescues: 0

Canonical candidate-image reliability is therefore also a secondary issue; do not rely on visual rescue as the primary identity solution yet.

### PokeTrace Free market

- live calls: **32**
- cache hits: **9**
- exact US market matches: **0**
- no match: 14
- ambiguous: 1
- request failures: 0
- rate limited: 0
- EU/CardMarket requests: 0
- graded values accepted: 0
- market values found: **0**

The provider enforces `>=2.25s` despite the workflow still containing the stale compatibility env value `2.05`; align that displayed env to `2.25` in a future cleanup.

### Safety

- CardGrader calls: 0
- purchases: 0
- bids: 0
- checkout: 0
- persisted eBay records: 0
- persisted PokeTrace records: 0

## Next V5 actions

Do **not** merge PR #8 yet.

Priority order:

1. Audit the one PokeTrace candidate that passes name + set + number but fails variant; preserve strict ambiguity safety.
2. Audit TCGdex's low hit count, `no-match set/card` buckets and 3 request failures using only aggregate/safe diagnostics.
3. Align the workflow's displayed PokeTrace interval from `2.05` to `2.25` for configuration clarity; runtime is already safe.
4. If free-chain coverage remains low, benchmark **JustTCG in parallel on the exact same eBay sample** before promoting it to principal. The user has already created the JustTCG GitHub secret.
5. Keep Scrydex/Vision in reserve for persistent ambiguity after TCGdex/PokeTrace/JustTCG/local arbiters; do not pay merely to force hit count.

Target `15+/20` remains an aspirational coverage goal only when evidence supports it. `AMBIGUOUS` remains blocking and no source may invent a buyable identity or value.
