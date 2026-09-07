# V4 coordinate-authoritative card identity — validation note

Status: DRAFT / NON-MERGED until the branch CI is green and the user explicitly authorizes merge.

Base: `main@b43dec6084f341b2b52301a4f0542d6f616cf1e2`.

Scope:
- exact language + exact set + localId is the primary macro-card coordinate;
- a missing intrinsic form token (`GX`, `V`, `ex`, etc.) may be tolerated only after that exact coordinate proof;
- two explicit incompatible form tokens remain blocking;
- trailing presentation labels (`Holo`, `Reverse`, `Rainbow`, `Full Art`, `FA`) cannot manufacture card identity;
- same-coordinate material variants still require a unique compatible finish/signature;
- First Edition/Unlimited is not made globally applicable; existing catalogue applicability rules remain authoritative;
- #260's already-merged constrained name-filter installer is wired after the unique-coordinate fallback, fixing the production-entrypoint omission discovered during this reuse audit.

No pricing semantics, SOLD/ASK semantics, provider budget, notification threshold, purchase, bid, checkout or payment behavior is changed.
