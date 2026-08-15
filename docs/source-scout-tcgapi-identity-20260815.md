# tcgapi.dev identity benchmark — 2026-08-15

Branch: `agent/source-scout-tcgapi-identity-20260815`

Successful run: `31903069901` / job `95056687686`.

Same 18-card English panel used by the PokemonPriceTracker benchmark.

Safety / budget:

- authenticated key injected through GitHub Secret `TCGAPI_DEV_API_KEY`; value never printed;
- hard cap: 18 calls per run;
- two branch pushes ultimately triggered two benchmark runs, therefore 36 authenticated requests were consumed in total;
- final reported daily remaining: 64/100;
- no paid overage, purchase, bid or checkout;
- one-shot workflow deleted after capture.

Result of the final run:

- cards attempted: 18;
- HTTP calls: 18;
- macro exact but language unproven: 3;
- ambiguous: 0;
- no match under strict exact name + exact set + exact collector-number acceptance: 15;
- provider/API failures: 0;
- exact macro targets: `base1-4`, `neo1-9`, `base1-58`;
- language accepted as proof: NO;
- microvariant accepted as proof: NO.

Interpretation:

`tcgapi.dev` is not promoted as an automatic strict identity fallback. Its documented search/card payload is useful for TCGPlayer-style card retrieval and pricing, but the current benchmark coverage is materially below PokemonPriceTracker on this same panel and the documented card/search schema does not expose a language field suitable for our commercial-identity proof.

Current fallback-candidate ranking from available same-sample evidence:

1. PokemonPriceTracker: promising macro fallback / retrieval source; 16/18 exact on its 2026-08-15 full benchmark, with the two Base Set vintage targets left ambiguous rather than guessed.
2. tcgapi.dev: 3/18 macro exact, language unproven.
3. JustTCG: 0/20 exact on the corrected set-aware same-sample benchmark; do not promote for strict identity.

None of these providers may prove edition, Shadowless, premium finish, promo/stamp or another sensitive microvariant unless an independent deterministic catalogue rule proves that dimension.