# Current phase — PokeTrace final-gate / Japanese set namespace

Production `main` au début de la phase : `fadefe91c7b35aac37131a1c4f386231d00b45dc` (merge PR #129).

Working branch : `diag/v4-poketrace-final-gate-20260818`.

## Verified live state

Post-#129 production :

- run `32122825454` — SUCCESS, PokeTrace `1 attempted | 0 exact | 1 no-match` ; Charizard VSTAR `015/100` retrouve `1` candidat `S9: Star Birth` ;
- run `32123694201` — SUCCESS, PokeTrace `1 attempted | 0 exact | 1 no-match` ; Zorua `072/064` retrouve `1` candidat `SV6a: Night Wanderer` ;
- final opportunities : `0` ;
- aucun achat, bid, checkout ou paiement.

La régression de retrieval JA est donc corrigée : le blocker est désormais dans le gate final d'identité/hardening.

## Audit déterministe

Le bridge PokeTrace `<catalog-id>: <label>` existe déjà en V4. Le porter une deuxième fois depuis V5 serait redondant.

Le snapshot officiel pin `tcgdex/cards-database@af33c9ac882e2acfadffaf19e8083aa976d12983` prouve :

- `S9` = Star Birth, 100 cartes ; `S9/015` est Charizard VSTAR et son impression catalogue est holo-only ; le candidat PokeTrace `S9: Star Birth` est donc compatible avec le bridge de préfixe exact déjà présent ;
- `SV6a` = Night Wanderer, 64 cartes ; `SV6a/072` est Zorua ;
- `SV7a` est Paradise Dragona, également 64 cartes, et `SV7a/072` est une autre carte. Le live `tcgdex_set=SV7a/Night Wanderer` est donc un mauvais namespace hybride provenant d'un fallback de coordonnée, pas une preuve permettant d'accepter le set PokeTrace par simple label.

## Current change

1. ajoute un alias set-level source-pinned `ja + Night Wanderer -> SV6a`, avec dénominateur exact `64` et exact set/localId toujours obligatoires ;
2. conserve PokeTrace market-only après identité TCGdex ;
3. améliore l'observabilité du gate final pour distinguer `NAME`, `SET`, `SET_ID_CONFLICT`, langue, dimensions commerciales, finish catalogue et hardening final ;
4. ajoute les formes live post-#129 comme régressions offline, notamment `S9: Star Birth` et `SV6a: Night Wanderer`.

Aucun fuzzy, aucune traduction comme preuve, aucun changement de fair value, `max_recommended`, seuil économique, grader/grade, notification ou transaction.

## Next gate

CI complète + compile/YAML/diff + comparaison discovery read-only. Si tout est vert, ouvrir la PR et la laisser non mergée jusqu'à autorisation utilisateur. Après merge autorisé, le premier run prod devra confirmer :

- Zorua résolu sous `SV6a`, jamais `SV7a` ;
- raison exacte du rejet Charizard si PokeTrace reste `0 exact` ;
- aucun relâchement d'identité ou microvariante.

PR #8 reste expérimentale et non mergée ; son bridge de set a été audité en lecture seule uniquement.
