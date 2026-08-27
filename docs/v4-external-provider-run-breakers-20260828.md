# V4 external provider run breakers — 2026-08-28

Base: `main@52deb7f50e194b04552800bfe328df5be9e1d3a2`.

Production run `33102143231` proved two runner/provider-wide failure classes while the external fixed backlog was large:

- PSA APR: 2/2 attempts returned explicit HTTP 403;
- eBay: 8 attempts, 7 errors/unavailable, including repeated 30-second isolated hard timeouts.

Existing protections remain authoritative:

- PR #137 navigation-timeout DOM salvage;
- PR #175 disposable-process hard isolation for eBay;
- provider failures remain retryable and are never converted to clean no-match.

This phase adds only process-local circuit breakers:

- PSA APR: after one explicit HTTP 403 or 429, skip remaining APR network calls in the current scanner process;
- eBay: after two hard timeouts without an intervening usable provider result, skip remaining eBay network calls in the current scanner process;
- every new scanner run starts closed and retries providers normally;
- ordinary eBay navigation/provider errors alone do not trip the hard-timeout breaker;
- clean/matched/insufficient eBay provider responses reset accumulated hard-timeout pressure.

No identity, TCGdex, microvariant, fair value, discount threshold, `max_recommended`, purchase, bid, checkout, payment or PR #8/V5 behavior is changed.
