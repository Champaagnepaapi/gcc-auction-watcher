# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **6 septembre 2026**. Le code/Git/GitHub live reste l'autorité ; re-vérifier le HEAD avant toute action importante.

## Autorité

```text
V4 production branch             main
V4 production HEAD               dfc548021c561479cc8758e2949d2c4629388d9d
#255 external FV authority       MERGED / production
#257 source-role separation      OPEN / DRAFT / NON MERGED
#257 branch                      fix/v4-source-role-pricecharting-20260906
#256 Japan providers             OPEN / DRAFT / NON MERGED
V5                               PR #8 / OPEN / DRAFT / NON MERGED
Robot KB durable                 PostgreSQL local Mac / séparé de V4 / V4_USE=false
Neon                             writers automatiques OFF / rollback manuel
```

## Phase active — #257

Objectif : conserver **un seul orchestrateur** tout en rendant les vaults/marketplaces économiquement indépendants.

```text
GCC / Fanatics / COMC / Magi / Cardova
        -> listing / coût potentiel uniquement
        -> identité exacte
        -> providers externes de valorisation
        -> décision
```

Un prix de vault n'est jamais une fair value. L'historique GCC est diagnostic/Robot KB seulement et ne peut pas plafonner ou conflict-block une valorisation externe.

### PriceCharting — décision produit mise à jour

PriceCharting doit être **consulté systématiquement comme guide de référence** pour chaque identité PSA compatible évaluée.

- PriceCharting reste `GUIDE`, pas `SOLD` item-level ;
- `PSA 10` -> guide PSA 10 ;
- `Grade 9` -> guide de valorisation PSA 9 lorsque le listing est déjà prouvé PSA 9 exact ;
- `Grade 8` -> guide de valorisation PSA 8 lorsque le listing est déjà prouvé PSA 8 exact ;
- PSA 8.5 reste distinct ;
- le guide peut suffire seul si aucune meilleure preuve SOLD-derived n'est disponible ;
- SOLD exact/récent plus fort garde la priorité ;
- pas de floor spécial 40 % : seuil normal V4 = 30 % actuellement ;
- panne PriceCharting visible, sans effacer une preuve SOLD forte déjà établie.

Exemple : guide 100 EUR -> seuil économique normal 30 % -> offre <=70 EUR potentiellement admissible si tous les autres gates sont satisfaits.

### Source roles

Opportunity-only : GCC, Fanatics, COMC, Magi, Cardova, futur eBay actif ; Mercari/SNKRDUNK restent dans #256 séparée.

Valuation : preuves SOLD-derived compatibles + PSA APR/PokeTrace/PPT + PriceCharting guide systématique. Direct eBay SOLD scraper perd son autorité de fair value dans #257.

## Validation en cours

La première CI après le changement de politique a détecté :

1. un matching public PriceCharting qui normalisait trop tôt le label et supprimait `#208`, empêchant la preuve du numéro ; corrigé sur la branche ;
2. des marqueurs historiques retirés du capability ledger lors du closeout ; restaurés sans changer le runtime.

Les workflows sont relancés sur le nouveau head. Ne pas annoncer la phase validée tant que suite V4 + Global + tests ciblés + compile/YAML/diff-check + live read-only ne sont pas verts sur un SHA exact.

## Invariants

- ASK/current auction/disparition != SOLD ;
- aucune identité/langue/grader/grade/microvariante incompatible mélangée ;
- aucun achat, bid, checkout ou paiement automatique ;
- PR #8 reste protégée ;
- Robot KB reste séparé ;
- aucun durable write Cardova sans autorisation explicite ;
- #257 reste DRAFT/NON MERGED sans autorisation explicite utilisateur.

## Prochaine étape

1. attendre/analyser CI sur le head exact ;
2. corriger uniquement les régressions prouvées ;
3. obtenir le bootstrap Global live read-only avec `notifications=false`, `transactions=false`, `marketplace_listing_is_valuation=false`, `gcc_history_economic_authority=false` ;
4. inscrire SHA/runs finaux dans README + ledger ;
5. ne pas merger #257 sans autorisation explicite.

Ledger : `docs/v4-source-role-pricecharting-20260906.md`.
