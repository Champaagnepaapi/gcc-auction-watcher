# Cardova exact SOLD — PostgreSQL revision rollback rehearsal (2026-08-31)

Status: PR #209 OPEN / DRAFT / NON-MERGED. No durable write authorized.

## Stack

- #208 exact Cardova print-run SOLD dry-run
- #207 P3 `print_run` runtime: `38288a950db8285bcbf279d91354f8a1ad3a8c2f`
- #209 validated code before this documentation commit: `d6f9c3887bab8af4bdfd05182464dbae36366767`

## Purpose

Prove on the real local PostgreSQL dataset that an already-sealed unresolved Cardova `SALE_TRANSACTION` can be promoted without mutation by creating an append-only exact `REVISION_OF` observation carrying the same economic sale facts and a PROVEN canonical identity.

The rehearsal has no commit path. Migration 0003 and all exact revisions exist only inside one outer PostgreSQL transaction, followed by mandatory `ROLLBACK` and before/after verification.

## First live attempt

The first rehearsal failed closed with:

`IdempotencyConflict: source system 'cardova' already differs`

The transaction rolled back. Root cause: the promotion path used memory-only Cardova source metadata instead of reusing the immutable durable `source_system.code='cardova'` row. The implementation was corrected to reuse the existing source-system id/name/role exactly, matching the existing #199 ingest contract. A focused regression test was added.

## CI after correction

- Robot KB local PostgreSQL validation `33402057459`: SUCCESS
- V4 Auction Discovery Validation `33402057489`: SUCCESS
- live effective-vs-legacy V4 comparison: SUCCESS
- compile / YAML / `git diff --check`: PASS

## Successful live rehearsal

Input snapshot:

```text
unresolved Cardova sales available  356
selected sales                      356
exact identity rows                  38
identity blockers                     6
```

Identity blockers remained fail-closed:

```text
CARDOVA_PUBLIC_TITLE_MATERIAL_TAIL_UNRESOLVED  1
PINNED_SOURCE_VARIANT_AMBIGUOUS                1
PROVIDER_MATERIAL_TOKEN_UNRESOLVED             4
```

Inside the transaction:

```text
schema versions                     [1, 2, 3]
exact revision rows                  38
PROVEN Cardova identifier links      38
distinct canonical cards             34
replay exact matches                 38 / 38
target count                          38
```

Rollback verification:

```text
error                                null
rollback_executed                    true
before schema versions               [1, 2]
after schema versions                [1, 2]
migration registry restored          true
target durable state restored        true
durable exact revisions after        0
durable PROVEN identifiers after     0
local_postgres_durable_write         false
```

## Proven invariants

- original sealed unresolved sale is never updated;
- exact identity is represented by append-only `REVISION_OF`;
- economic fact / HAMMER_PRICE JPY is preserved exactly;
- exact identity resolution is `PROVEN` and supersedes the prior UNKNOWN resolution;
- `RESOLVED_AS` points to the exact canonical card;
- logical leaf state becomes the exact revision inside the transaction;
- replay is idempotent and creates no duplicate revision or resolution;
- the #207 migration is transactionally compatible with the real local dataset;
- rollback restores both migration registry and target Cardova state exactly;
- no V4 economic use, notification or commerce action occurs.

## Next phase

Prepare a separate guarded durable-commit path only. It must include:

1. explicit operator authorization;
2. exact implementation SHA;
3. preflight cohort/snapshot assertions;
4. fresh local backup / rollback procedure;
5. migration 0003 + exact revision batch in one controlled transaction;
6. post-commit verification of schema version, leaf exact revisions, PROVEN links, prices and replay;
7. V4 remains `V4_USE=false` until a separate activation decision.

Do not perform the durable migration or exact-sale promotion from PR #209.