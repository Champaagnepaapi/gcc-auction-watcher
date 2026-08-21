# Robot KB — GCC WAITING_FOR_PAYMENT safety note

Observed on the local Mac PostgreSQL catch-up on 21 Aug 2026: the GCC `status=SOLD` scope returned a row whose payload status was `WAITING_FOR_PAYMENT`.

Safety contract:
- `WAITING_FOR_PAYMENT` is never persisted as a final SOLD;
- the row is deferred and the durable fresh SOLD watermark is not allowed to advance past the unresolved non-final row;
- already proven final SOLD rows in the same fresh scan may still be ingested and retained in the pending backlog;
- when the same row later becomes explicit `SOLD`, it is ingested normally and the fresh watermark may advance after the committed boundary is reached;
- the historical SOLD backfill also tolerates this known provider leak during page probing/scanning, excludes it from fixtures and timestamp bounds, and leaves its eventual finalization to the fresh watermark lane;
- any other unexpected non-final status remains fail-closed.

This is a Robot KB collection hardening only. It does not change V4/Global economics or notifications and performs no commercial action.
