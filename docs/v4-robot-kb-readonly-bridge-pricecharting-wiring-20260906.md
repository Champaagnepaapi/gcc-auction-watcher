# V4 PriceCharting mandatory reference + Robot KB read-only bridge — 2026-09-06

## Scope

This integration keeps the production truth hierarchy unchanged:

1. exact recent item-level SOLD;
2. exact older SOLD when still usable;
3. compatible fixed ASK;
4. auction snapshot <=5 minutes only as fallback;
5. active auction is weak signal only.

PriceCharting is now a systematic valuation **GUIDE** reference in the canonical V4 bootstrap. It is not converted into SOLD evidence and never outranks stronger exact/recent SOLD evidence. The existing mandatory policy remains bounded (default 50 PriceCharting identities/run).

## Robot KB -> V4

V4 can optionally query the Mac Mini Robot KB through an authenticated, typed, read-only HTTP bridge. PostgreSQL itself remains bound to `127.0.0.1` and is never exposed by this repository.

The bridge returns only sanitized exact-sale fields and requires:

- one PROVEN `TCGDEX_CARD_ID` -> canonical-card mapping;
- PROVEN grader and grade field resolutions for the sale source record;
- `SALE_TRANSACTION` + `COMPLETED` + `SEALED`;
- a known positive `ITEM_PRICE`, `HAMMER_PRICE`, `ACCEPTED_OFFER`, or `TOTAL` component;
- no superseding revision/cancel/void meaning.

ASKs, listing snapshots, provider metrics, raw payloads, source URLs and credentials are never exported by the bridge. V4 additionally excludes Robot KB `gcc` historical rows from fair-value authority, preserving the external-FV policy.

## Network boundary

GitHub-hosted runners cannot reach the Mac Mini `127.0.0.1` directly. The code is fail-closed and disabled unless both are configured at runtime:

- `ROBOT_KB_V4_READONLY_URL`
- `ROBOT_KB_V4_READONLY_TOKEN`

Remote URLs must be HTTPS. Plain HTTP is accepted only for localhost testing. A user-managed authenticated HTTPS/private tunnel may proxy the local bridge; PostgreSQL must never be published directly.

The Mac helper `mac/robot-kb-local/Demarrer Pont V4 Robot KB.command` loads the existing PostgreSQL credential and the bridge token from macOS Keychain and starts the localhost service without putting either secret in Git, plist state or logs.

## Safety

- no database writes;
- no Neon automatic writer;
- no automatic purchase, bid, checkout or payment;
- no fuzzy identity proof;
- no GCC historical fair-value resurrection;
- provider/tunnel failure remains visible and cannot fabricate a clean no-match or SOLD.
