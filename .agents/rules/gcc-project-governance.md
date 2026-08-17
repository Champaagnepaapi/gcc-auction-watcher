---
trigger: always_on
---

# GCC Auction Watcher — Project Governance

You are working on the repository:

Champaagnepaapi/gcc-auction-watcher

Project: Robot Pokémon / GCC Auction Watcher.

## Mandatory startup procedure

Before making any modification:

1. Read README.md completely. It is the canonical project handoff.
2. Read `docs/project-capability-ledger.md` when it exists. It is the durable capability/supersession registry used to prevent reimplementing work that already exists on V4, V5, Robot KB or historical/shadow branches.
3. Read `docs/project-branch-inventory.md` when it exists. It is the exhaustive remote-branch recovery index. Use it to discover work that may be absent from `main` and from open PRs.
4. Read `docs/project-open-pr-inventory.md` when it exists. It records the current open-PR surface, stale-open PRs, pending behavior changes and PR stacks that must not be merged independently.
5. Inspect the actual local Git state:
   - current branch
   - HEAD SHA
   - git status
   - relevant branches
6. When GitHub access is available, verify relevant PRs, commits, workflow runs and logs. For any merge/close decision, re-check the live GitHub state rather than trusting the inventory snapshot.
7. Never assume an old summary, old SHA, previous agent report or previous chat reflects the current repository state.
8. Reconstruct the current production and experimental architecture before changing code.

If README, the capability ledger, the branch inventory, the open-PR inventory, an old report and the actual repository disagree:
- actual code/GitHub state is authoritative for technical facts;
- README, the ledgers/inventories and prior discussions are used to understand intent/history;
- `docs/project-open-pr-inventory.md` supersedes older static PR-status statements in the capability ledger until the ledger is refreshed;
- report important inconsistencies rather than silently guessing.

## Mandatory capability-recovery check

Before implementing or designing any non-trivial capability, perform a reuse audit first.

1. Search `README.md`, `docs/project-capability-ledger.md`, `docs/project-branch-inventory.md` and `docs/project-open-pr-inventory.md` for the capability and functional synonyms.
2. Search GitHub PRs, branches and historical commits for equivalent or predecessor work. Do not limit the search to open PRs or branches based on current `main`.
3. Inspect the relevant current V4, V5, Robot KB, Source Scout, Japan Edge and global-shadow modules instead of assuming absence from `main` means the capability was never built.
4. Follow documented supersession chains and start from the newest compatible validated implementation.
5. Prefer reusing, porting or adapting proven code/tests over implementing an independent equivalent.
6. If a new implementation is still required, record why the prior implementation is incompatible, unsafe, obsolete or belongs to a deliberately separate architecture.
7. Never revive a `SUPERSEDED` or `DISABLED` implementation without first reading the successor/root-cause history that replaced or disabled it.
8. Treat closed/unmerged PRs and historical branches as recoverable project assets until ancestry and supersession prove otherwise.
9. Explicitly check for `STALE_OPEN` PRs before merging: an open PR may already be fully absorbed by later `main` history.
10. After a significant validated phase, update README, the capability ledger and the inventories when topology/status materially changed.

A closed or unmerged PR is not automatically discarded work. `SHADOW`, `DEFERRED`, `BENCHMARK` and `V5_ONLY` branches may contain the canonical implementation to reuse later.

If the same capability appears in multiple lines (for example V4 and V5), compare the actual implementations and invariants before choosing one. Do not silently copy an older implementation over a newer safety hardening.

## Branch hygiene / deletion safety

The repository intentionally contains a large historical branch surface because significant validated work lives outside `main`.

- Never delete a branch merely because it is old, closed, unmerged, documentation-only or absent from current workflows.
- Before any branch deletion, verify its tip SHA, ancestry against `main`/V5/current successor, associated PRs, workflow references, unique files/tests/docs and whether the capability ledger marks it as historical evidence.
- Temporary/no-op branches may be cleanup candidates, but cleanup remains destructive and requires explicit user authorization.
- Do not rewrite history or force-push recovery branches.

## Open PR hygiene

- Open does not mean current, mergeable does not mean desired, and draft/non-draft does not imply authorization.
- Before merging an old PR, compare its exact patch against current `main`; if the same behavior already exists, classify it `STALE_OPEN/SUPERSEDED` instead of replaying it.
- Preserve genuinely pending product/economic changes as separate decisions. Example: PR #87's 30% GCC-only illiquid notification behavior must not be smuggled into unrelated recovery work.
- Keep stacked shadow PRs together. The Global Multi-Vault line #108→#109→#110→#113→#114→#115 must be recovered as a stack, not by merging a child directly to `main`.
- PR #122 and PR #123 are separate until the user explicitly decides which line supersedes/merges; never auto-close either.

## Project governance

- `main` is the canonical V4 production branch.
- Experimental V5 work must remain isolated from V4 production.
- PR #8 / the V5 experimental line must never be merged into `main` without explicit user authorization.
- Never merge another agent's work automatically.
- Never push destructive changes or force-push without explicit authorization.
- Do not dispatch live workflows when project policy says the user launches them manually.
- No automatic purchase, bid, checkout, grading purchase or other commercial transaction.
- Pokémon individual cards only. No sealed products or unrelated products.
- Do not relax identity or safety constraints merely to improve coverage.

## Multi-agent rules

Multiple agents may work on this repository simultaneously.

For any non-trivial implementation task:
- work in a dedicated branch/worktree;
- do not modify another agent's branch;
- keep scope limited to the assigned mission;
- avoid unrelated refactors;
- do not merge your own branch unless explicitly instructed;
- document dependencies on other agents instead of reimplementing their work independently.

Before editing shared/core files such as `watcher.py`, workflow files, market arbitration code or V5 identity code, inspect whether your task can be isolated into a smaller component.

## Identity safety

Commercial identity must remain deterministic and fail-closed where ambiguity is material.

Keep separate:
- card name
- set
- card number/localId
- language
- edition
- printing
- finish
- special finish
- variant
- grader
- grade

Do not use fuzzy matching, substring matching, token overlap, containment, assumed translation or Levenshtein similarity as proof of exact identity unless the project explicitly defines a safe retrieval-only use that cannot create identity.

Retrieval may be fuzzy only when a separate deterministic proof step remains mandatory.

Never infer:
- Unlimited from absence of First Edition;
- Non-Holo from absence of Holo;
- premium variants from provider metadata alone;
- a localized identity from an English provider alias.

An English/provider alias may assist provider lookup only when deterministic catalog invariants prove it maps to the same card.

`AMBIGUOUS` must remain blocking.

## Market evidence safety

Keep these concepts separate:
- identity evidence
- RAW market evidence
- graded market evidence
- grader
- grade
- currency
- provider
- market
- estimate provenance
- cache freshness

Never silently mix:
- RAW and graded values;
- different graders;
- different grades;
- materially different commercial variants;
- USD and EUR;
- US and EU market context.

RAW Cardmarket/TCGplayer evidence may be used as a secondary signal/manual-review trigger, but RAW must never automatically become the value or maximum bid of a graded slab.

Automatic graded valuation requires sufficiently strong evidence for the exact commercial identity, grader and grade.

An absent provider result does NOT mean the card has low value.

Keep distinct statuses for concepts such as:
- clean no match
- insufficient evidence
- provider error
- transient unavailable
- rate limit
- pending budget

Transient/provider failures must not be converted into clean negative evidence or hidden for a long cache TTL.

## External-market philosophy

GCC history is one market source, not the sole source of truth.

Eligible economic evaluations should be able to use independent evidence such as:
- GCC history
- canonical TCGdex identity
- PokeTrace graded market
- PSA APR exact grade
- exact eBay sold comparables
- TCGdex Cardmarket / TCGplayer RAW signals

Strong external evidence may rescue a listing with weak or absent GCC history.

Strong disagreement between trustworthy markets must be surfaced or blocked conservatively rather than averaged away.

A card that cannot currently be valued precisely should remain distinguishable from a card proven to be a bad opportunity.

## Auctions

Preserve the existing prudent `Opportunity.max_recommended` semantics unless a task explicitly redesigns economics.

- A current auction price above the applicable maximum must not remain automatically actionable.
- Final auction alerts must use the same persisted maximum.
- No automatic bidding is ever allowed.

## Provider / API discipline

Respect documented provider authentication, rate limits and plan constraints.

Use bounded request budgets and caching.

Do not create unnecessary high-volume provider calls merely because an API is available.

Provider fallback must remain independent where possible so one provider outage does not silently become a global market failure.

## Tests and validation

Every behavior change requires regression tests.

For implementation tasks, run the relevant existing suite plus focused new tests.

Also run, where applicable:
- Python compilation
- YAML parsing/validation
- `git diff --check`

Do not claim a live validation occurred unless it actually occurred.

Do not claim GitHub CI is green from local tests alone.

Do not weaken existing tests merely to make a change pass.

## Live and production safety

A diagnostic/live run must never:
- purchase
- bid
- checkout
- mutate commercial state
- send unintended user notifications

When a live diagnostic is required but project policy reserves manual launching to the user, prepare the code and tell the user which existing workflow to launch instead of dispatching it yourself.

## Documentation

README.md is the canonical project handoff.

`docs/project-capability-ledger.md` is the durable capability/history/supersession registry. Its purpose is to make previously validated work discoverable even when it is V5-only, shadow, deferred, disabled or no longer present on `main`.

`docs/project-branch-inventory.md` is the exhaustive branch recovery index. It exists so a capability hidden on a historical/shadow/benchmark branch cannot silently disappear from project memory.

`docs/project-open-pr-inventory.md` is the current open-PR recovery/status index. It prevents stale-open PRs, pending product decisions and stacked shadow PRs from being mistaken for production or independently mergeable work.

After a significant validated architecture, provider, production, workflow or live-phase change, update README.md and the capability ledger before considering the phase complete. Update the branch inventory when branches are created/retired/superseded, and the open-PR inventory whenever open PR status/topology changes materially.

Do not document an unverified claim as completed.

## End-of-task report

At the end of every non-trivial task, provide:

- mission completed;
- branch/worktree used;
- base SHA;
- final SHA;
- files modified;
- exact behavior changed;
- tests executed and exact results;
- compile/YAML/diff-check results where applicable;
- live/workflow runs actually executed;
- unresolved risks;
- recommended next step;
- explicit confirmation of:
  - no purchase
  - no bid
  - no checkout
  - no unauthorized merge

If no code change was necessary, state that explicitly.

The goal is to leave work sufficiently auditable that another agent or ChatGPT can verify it from Git/GitHub without guessing.