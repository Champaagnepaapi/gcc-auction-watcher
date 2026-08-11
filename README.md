# GCC Auction Watcher

La version de production recommandée est la **V4 cloud GitHub Actions** : aucun Mac ne doit rester allumé. Voir [`README_CLOUD.md`](README_CLOUD.md) pour l'installation et le fonctionnement détaillé.

## V4 — état de production

Le watcher scanne **GCC Marketplace** toutes les 10 minutes et ne considère que les **cartes Pokémon individuelles**. Les boosters, packs, displays, boxes, ETB, coffrets, blisters, bundles, decks, tins et autres produits scellés/non-cartes sont exclus.

### Univers économique

- découverte : **0 à 100 €** ;
- enchères : timer individuel **≤ 60 minutes** ;
- décote minimale : **30 %**, relevée automatiquement lorsque les comparables sont faibles ;
- aucun achat, aucune enchère et aucun checkout automatique.

La découverte a été volontairement élargie sous 10 € afin de ne pas rater une anomalie extrême. Un prix très bas ne suffit jamais à créer une opportunité : les mêmes contrôles d'identité, de grade, de comparables et de valorisation restent obligatoires.

## Découverte GCC

### Prix fixes

Les prix fixes utilisent l'API publique GCC `/on-sale-items`, avec pagination complète et filtres Pokémon/cartes/prix appliqués par GCC puis défendus localement.

### Enchères

La découverte primaire reproduit la logique de `/filtres/auctions` au **niveau des lots**, via l'API publique GCC :

```text
/on-sale-items
sellingTypeGroup=AUCTION
sortType=ENDING_SOON
status=ON_SALE
        ↓
lots individuels
        ↓
endTime individuel
        ↓
Pokémon + carte + 0–100 € + ≤60 min
        ↓
analyse économique V4
```

Le watcher s'arrête lorsque l'ordre `ENDING_SOON` permet de prouver que l'horizon de 60 minutes a été franchi, ou lorsque l'inventaire est épuisé. Lorsque cette preuve est obtenue, le statut spécifique est :

```text
COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
```

Si l'API, la pagination, l'ordre ou les `endTime` deviennent incohérents, l'ancien collector auction reste disponible comme **fallback de sécurité**.

## Valorisation

La valorisation utilise une médiane pondérée par récence, un filtre robuste MAD/IQR, une fourchette prudente et un seuil de décote adaptatif.

Pour les cartes PSA suffisamment identifiées, **PSA Auction Prices Realized** est interrogé en premier comme source indépendante de validation, puis eBay public sert de fallback lorsque les données PSA sont insuffisantes ou indisponibles. Les prix fixes comme les enchères doivent rester sous le prix maximal conseillé.

Une carte de grade supérieur proposée autour du marché robuste d'un grade inférieur de la **même société de grading** peut être signalée comme **ARBITRAGE GRADE**, sans inventer la valeur du grade supérieur. Cette voie exige une preuve externe exacte suffisante avant notification. Les comparables d'autres graders restent secondaires et ne créent pas seuls une valeur achetable sans ratio empirique suffisamment documenté.

## État, anti-spam et observabilité

`state.json` est restauré/sauvegardé via le cache GitHub Actions. La file fixed priorise `NEW → CHANGED → NEVER_EVALUATED → STALE`, avec une réévaluation à 24 h par défaut.

Une opportunité déjà signalée n'est renotifiée que si le prix baisse d'au moins 10 %, si la décote gagne au moins 5 points, ou si une enchère franchit un seuil temporel important. Une alerte haute priorité unique peut être envoyée à cinq minutes ou moins si le prix reste sous le prix maximal conseillé.

Chaque run V4 est aussi journalisé dans l'**issue #1** avec notamment :

- `trigger=schedule` ou `workflow_dispatch` ;
- statut/exit code/durée ;
- nombre d'opportunités finales ;
- mode de découverte auction ;
- statut de couverture auction ;
- lots auction découverts ;
- timers parsés ;
- enchères dans l'horizon ;
- utilisation éventuelle du fallback legacy.

## V5 — expérimental, pas en production

La V5 reste séparée de la V4 et travaille actuellement sur les **listings RAW eBay** et leur identité canonique.

- **TCGdex** reste le resolver catalogue multilingue principal ;
- **PokeTrace Free** a été authentifié et testé en live pour les données RAW US, mais le matching nom/set n'est pas encore suffisamment fiable pour être mergé ;
- la PR V5 correspondante reste en **draft** et ne remplace pas le watcher V4 ;
- **Scrydex** reste dans le radar comme éventuel bridge d'identité canonique si la chaîne gratuite TCGdex → PokeTrace ne suffit pas ;
- aucune dépendance payante ni passage à PokeTrace Pro n'est justifié tant que le matching exact n'est pas démontré.

La règle de sécurité reste la même pour toutes les versions : **le projet ne passe jamais d'achat, d'enchère ou de checkout automatiquement**.
