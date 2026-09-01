# V4 TCGdex source-pinned outage fallback — 1 septembre 2026

## Incident

Les runs production après #216/#217 continuent de montrer une panne transport TCGdex persistante (`ConnectionError`) malgré le retry borné et le circuit-breaker Main-only. Le run `33491701827` a terminé normalement mais avec 36/36 résolutions TCGdex en `ERROR`, donc PokeTrace n'a pas pu être tenté derrière ces identités.

## Réutilisation

Cette phase ne crée pas un nouveau resolver catalogue. Elle réutilise exactement :

- la classe de panne transitoire déjà validée par #145/#216 : `ConnectionError`, `Timeout`, HTTP 502/503/504 ;
- les aliases japonais déjà reviewés/source-pinnés dans `v4_tcgdex_japanese_set_aliases.py` ;
- la validation exacte du numéro imprimé/denominator de `v4_tcgdex_generalized_coordinate_recovery.py` ;
- le pin TCGdex immuable `af33c9ac882e2acfadffaf19e8083aa976d12983` ;
- la preuve set/localId + import exact du set déjà utilisée par `v4_tcgdex_source_pinned_set_reconciliation.py` et `v4_tcgdex_source_pinned_finish.py`.

## Contrat du fallback

Le resolver REST normal s'exécute d'abord. Le fallback ne peut agir que si le résultat est `ERROR` et que sa raison appartient à la classe transport transitoire ci-dessus.

Ensuite, il exige simultanément :

1. langue japonaise ;
2. set GCC correspondant à un alias japonais déjà reviewé ;
3. numéro imprimé compatible avec le contrat exact de cet alias ;
4. fichier exact `set/localId` présent dans le snapshot TCGdex immuable ;
5. ce fichier importe exactement le set attendu ;
6. variantes de finish uniquement dans le vocabulaire déjà accepté (`normal`, `holo`, `reverse`).

Si une seule preuve manque, le résultat original `ERROR` est conservé. Aucun `NO_MATCH`, `AMBIGUOUS`, autre langue ou set non reviewé n'est récupéré.

## Hors scope

Aucun changement de :

- fair value / seuil / `max_recommended` ;
- caps enchères ou `EXTERNAL_PENDING` ;
- eBay / PSA / PokeTrace provider semantics ;
- notification ;
- Robot KB / PostgreSQL / Neon ;
- V5 / PR #8 ;
- achat, bid, checkout ou paiement.

## Validation attendue avant tout merge

- tests ciblés fallback/source-pinned/transport ;
- suite V4 complète ;
- compile/YAML/diff-check ;
- live comparison read-only ;
- inspection du nombre d'identités récupérées sans faux `NO_MATCH` et sans relaxation d'identité.
