# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **6 septembre 2026**. Le code/Git/GitHub live reste l'autorité.

## Autorité

```text
V4 production branch             main
V4 production HEAD               dfc548021c561479cc8758e2949d2c4629388d9d
External fair-value authority    #255 MERGED / 9d3bb1b84d22c1534c24d7c58c5897ecce4b817f
Phase active                     #257 OPEN / DRAFT / NON MERGED
#257 branch                      fix/v4-source-role-pricecharting-20260906
Japan vault phase                #256 OPEN / DRAFT / NON MERGED
V5                               #8 OPEN / DRAFT / NON MERGED
Robot KB                         PostgreSQL local Mac / V4_USE=false
```

## Phase active — #257

### Problème

Le Global Multi-Vault savait déjà scanner plusieurs marketplaces, mais le chemin économique pouvait encore réutiliser une fair value GCC/historique dans la décision. Cela violait le rôle souhaité : **les vaults servent à trouver des offres, pas à valoriser les cartes**.

Direct eBay SOLD scraping était également encore présent comme fallback économique alors que la cible utilisateur est : eBay, lorsqu'il est scanné, doit servir à trouver des offres actives ; la fair value doit venir des providers de valorisation dédiés.

### Architecture retenue

Conserver **un seul orchestrateur Global** avec des adapters indépendants par marketplace :

```text
GCC / Fanatics / COMC / Magi / Cardova
        -> offre normalisée
        -> identité stricte
        -> valuation providers séparés
        -> décision par offre
        -> notification
```

Pas un bot complet par vault : cela dupliquerait TCGdex, identité, FX, déduplication, providers de valorisation et règles économiques, avec risque de drift.

### Source roles

Opportunity-only :

- GCC ;
- Fanatics ;
- COMC ;
- Magi ;
- Cardova ;
- futur eBay actif ;
- Mercari/SNKRDUNK dans #256 séparée.

Valuation-only dans #257 :

- PokeTrace / PokemonPriceTracker quand preuve forte compatible ;
- PSA APR exact ;
- PriceCharting guide fallback borné.

GCC historique reste diagnostic/Robot KB uniquement. Direct eBay SOLD scraper perd son autorité de fair value.

### PriceCharting

PriceCharting est explicitement un **guide**, pas une collection de `SOLD` item-level :

- aucune vente synthétique ;
- aucune fausse quantité de SOLD ;
- PSA 10 explicite uniquement pour preuve automatique ;
- grade 9/8 générique = WEAK/contexte ;
- guide seul => décote minimale 40 % ;
- preuve SOLD forte prioritaire ;
- guide incapable de résoudre un conflit entre providers SOLD forts ;
- public read-only fallback borné sans secret.

### Sécurité

Inchangée : identité exacte, ASK/current auction/disappearance != SOLD, aucune transaction automatique, aucun secret, PR #8 intacte.

## Validation en cours

PR #257 a été créée en DRAFT. Les workflows automatiques doivent prouver :

1. suite V4 complète ;
2. suite Global ;
3. tests ciblés source-role / PriceCharting ;
4. compile Python ;
5. workflow YAML parse ;
6. `git diff --check` ;
7. comparaison auction read-only ;
8. bootstrap Global live read-only avec `notifications=false`, `transactions=false` ;
9. assertions live : `marketplace_listing_is_valuation=false`, `marketplace_sources_have_valuation_authority=false`, `gcc_history_economic_authority=false`, `direct_ebay_sold_is_valuation_source=false`.

Aucun merge tant que ces preuves ne sont pas vertes et sans autorisation explicite utilisateur.

## Séparations à préserver

- #256 Mercari/SNKRDUNK reste une phase Japan Edge séparée ;
- eBay actif Global n'est pas ajouté dans #257 ; phase suivante après stabilisation ;
- Robot KB ne participe pas à la décision V4/Global ;
- V5/PR #8 ne doit jamais être mergée sans autorisation explicite.

Ledger : `docs/v4-source-role-pricecharting-20260906.md`.
