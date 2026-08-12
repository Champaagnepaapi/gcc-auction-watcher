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
2. Inspect the actual local Git state:
   - current branch
   - HEAD SHA
   - git status
   - relevant branches
3. When GitHub access is available, verify relevant PRs, commits, workflow runs and logs.
4. Never assume an old summary, old SHA, previous agent report or previous chat reflects the current repository state.
5. Reconstruct the current production and experimental architecture before changing code.

If README, an old report and the actual repository disagree:
- actual code/GitHub state is authoritative for technical facts;
- README and prior discussions are used to understand intent;
- report important inconsistencies rather than silently guessing.

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

After a significant validated architecture, provider, production, workflow or live-phase change, update README.md before considering the phase complete.

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