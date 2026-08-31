# Cardova exact SOLD — guarded durable commit preparation (2026-08-31)

Status: PR #210 OPEN / DRAFT / NON-MERGED. **No durable execution authorized or performed.**

## Stack

- #207 P3 `print_run` runtime: `38288a950db8285bcbf279d91354f8a1ad3a8c2f`
- #208 exact Cardova print-run SOLD dry-run
- #209 append-only `REVISION_OF` rollback rehearsal
- #209 successful live rehearsal code head: `d6f9c3887bab8af4bdfd05182464dbae36366767`
- #210 validated implementation head before this documentation commit: `0b5f026e843971dd5c6ac98d1fbc40c882971f5e`

## Proven prerequisite — #209

Real local PostgreSQL rollback rehearsal succeeded:

```text
unresolved Cardova sales available  356
exact identity rows                  38
identity blockers                     6
inside schema versions              [1,2,3]
exact revision rows                  38
PROVEN identifier links              38
replay exact matches                 38/38
rollback executed                    true
after schema versions               [1,2]
durable exact revisions after         0
durable PROVEN identifiers after      0
error                                null
```

This proves the actual local dataset accepts migration 0003 and all 38 append-only exact revisions while preserving sale economics and idempotency.

## #210 purpose

Prepare the durable commit path without executing it.

It reuses the exact #209 cohort/migration/promotion logic and adds operator and recovery gates around the only `COMMIT` path.

## Required gates

A durable run is unreachable unless all of the following are true:

1. target is loopback `robot_pokemon_kb`;
2. operator passes explicit `--commit`;
3. operator passes the exact confirmation phrase;
4. all known local Robot KB writer lanes are quiesced through their existing lock dirs;
5. a fresh secret-safe custom-format PostgreSQL dump is created while those locks are held;
6. the dump is nontrivial and `pg_restore --list` confirms it is readable;
7. preflight sees schema exactly `[1,2]`;
8. every exact target still has one unresolved logical leaf and no exact durable revision;
9. target cohort has zero durable PROVEN Cardova identifier links;
10. migration 0003 + all promotions succeed in one advisory-locked transaction;
11. exact leaf state, PROVEN links and replay idempotency pass before COMMIT;
12. post-COMMIT schema, registry and target state verification pass.

Exact confirmation phrase:

`I AUTHORIZE CARDOVA DURABLE EXACT SALE WRITE`

## Writer quiescence

#210 holds the exact lock directories already used by local writers:

```text
collector.lock             fixed / SOLD / backup
multisource.lock           public markets / paid providers
cardova-sold.lock          recurring Cardova paid SOLD
ebay-rapidapi-shadow.lock  eBay shadow writer
```

The locks are held from before cohort composition through backup, transaction, COMMIT and post-COMMIT verification.

If any lock already exists, #210 fails closed. It never deletes another lane's lock, including a stale/unknown one.

## Backup / recovery

The existing P3 `postgres_backup.dump_database()` path is reused. The backup stays under the existing local Robot KB backup tree unless an operator explicitly chooses another directory.

Before the transaction:

- custom-format `pg_dump`;
- file must exceed the minimum sanity size;
- `pg_restore --list` must succeed;
- path, byte size and SHA-256 are recorded;
- credentials are not printed.

There is deliberately no automatic restore or destructive rollback. If verification fails after COMMIT, the retained fresh dump is surfaced for manual recovery.

## CI on validated implementation head

```text
Robot KB local PostgreSQL validation  33407466207 SUCCESS
V4 Auction Discovery Validation       33407466294 SUCCESS
V4 live effective-vs-legacy compare   SUCCESS
compile / YAML / diff-check           PASS
```

Focused #210 tests cover:

- `--commit` + exact phrase double gate;
- unauthorized invocation fails before backup/DB access;
- all writer locks are acquired/released;
- an existing writer lock blocks and is not deleted;
- backup archive readability gate;
- unreadable backup fails closed;
- V4/notification/commerce flags remain false.

## Current durable state

#210 has **not** been executed against the durable database.

Therefore the last proven durable state remains:

```text
PostgreSQL schema versions              [1,2]
exact Cardova revisions                 0
PROVEN Cardova identifiers              0
V4_USE                                  false
```

## Next action

Do not run the commit script until the user explicitly authorizes the durable write after final SHA/CI verification.

If authorization is given, re-verify the exact #210 head and both CI runs immediately before execution, then run the guarded script once and inspect its post-COMMIT JSON before any further runtime/collector/V4 activation work.

No purchase, bid, offer, checkout or payment is part of this phase.