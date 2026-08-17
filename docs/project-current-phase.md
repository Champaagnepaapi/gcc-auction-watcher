# Current phase — V4 PokeTrace structured market retrieval

Base production SHA: `a2878cae20987e3ff16c8aedf6f67d07957f039f`.

Branch: `fix/v4-poketrace-deterministic-market-retrieval-20260817`.

Purpose: recover the already-proven V5 structured PokeTrace market retrieval contract in V4 after production run #1076 showed `TCGdex 8 exact` but `PokeTrace 0/8 exact`.

This phase changes provider retrieval only. Identity remains TCGdex-first; exact candidate, language/game, commercial-variant, grader and grade gates stay fail-closed. No economic threshold or transaction behavior changes.
