# eBay ASP Basic — Source Scout operating policy

Status: benchmark-only, not wired to V4 production or V5 PR #8.

## Query policy

1. Resolve commercial identity deterministically first.
2. Query eBay ASP only for economically interesting candidates with exact identity.
3. Reuse cached exact SOLD evidence before spending quota.
4. Query US first.
5. Query UK only when US yields fewer than 3 strong exact SOLD comps.
6. One eBay `item_id` is one market event globally; US/UK storefront views are provenance only and must be deduplicated.
7. Marketplace US vs UK does not create a distinct English card identity by itself. A proven regional printing/promo/microvariant remains separate.
8. Auction / Buy It Now rows can be strong provider-reported price evidence after strict identity validation. Best Offer exact price remains weaker until provider semantics are independently proven.
9. Provider failure or quota exhaustion is never negative market evidence.

## Basic quota telemetry

Track separately:

- `eligible_candidates`: exact identity + economically interesting + insufficient cached SOLD evidence;
- `lookups_attempted`;
- `lookups_blocked_quota`;
- `pending_identity_keys` for `PENDING_EBAY_QUOTA` replay;
- `confirmed_missed_due_to_quota`: increment only after retrospective replay proves that SOLD evidence already available at the original snapshot would have confirmed the opportunity.

This makes the paid-plan decision empirical. Upgrade only if repeated `confirmed_missed_due_to_quota` events show that the 50-request/month Basic hard limit is materially suppressing real opportunities.

## Provider migration status — 2026-08-15

- RapidAPI `/findCompletedItems` worked in run `31884480189`.
- Provider response marks it deprecated and recommends `/search`.
- `/search` returned HTTP 404 in run `31888822689`; the replacement endpoint is not currently usable through this RapidAPI product.
- Keep the provider benchmark safe-off after bounded tests and do not spend additional quota merely to poll for endpoint deployment.

## Safety

No purchase, bid, checkout, payment or paid grading action. No provider key is stored in repository content.
