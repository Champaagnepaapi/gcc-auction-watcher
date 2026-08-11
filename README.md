# GCC Auction Watcher

> **Source de reprise canonique — à lire en premier dans toute nouvelle conversation.**
> Cette section doit être mise à jour à chaque changement important afin qu'une nouvelle conversation puisse reprendre le projet sans reconstruire l'historique complet.

## Reprise du projet / état exact au 11 août 2026

### Production V4 — `main`

- La **V4 GCC** est la production canonique et ne doit pas être remplacée implicitement par V5.
- Scheduler production : **Cron-job.org → `workflow_dispatch` GitHub Actions toutes les ~10 minutes**. Le `schedule:` GitHub historique `3,13,23,33,43,53` a été supprimé car il était irrégulier et créait ensuite un double scan avec Cron-job.org.
- Univers : **cartes Pokémon individuelles uniquement**, découverte **0–100 €**, enchères **≤60 min**, décote plancher **30 %**.
- Enchères : discovery primaire **lot par lot** via `/on-sale-items?sellingTypeGroup=AUCTION&sortType=ENDING_SOON&status=ON_SALE`, avec `endTime` individuel et statut `COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS` lorsque l'horizon est prouvé. L'ancien collector reste fallback de sécurité.
- Prix fixes : API GCC `/on-sale-items`, file `NEW → CHANGED → NEVER_EVALUATED → STALE`, TTL 24 h.
- Valorisation : même grader/même grade prioritaire, médiane pondérée par récence, MAD/IQR, fourchette prudente, PSA APR en premier pour PSA exact lorsque possible, eBay public en fallback.
- Grade arbitrage autorisé uniquement avec référence robuste d'un grade inférieur du **même grader**, sans inventer la valeur du grade supérieur et avec preuve externe exacte avant notification.
- Anti-spam : renotification seulement si baisse de prix ≥10 %, amélioration de décote ≥5 points ou franchissement d'un seuil temporel ; une alerte haute priorité unique peut partir à ≤5 min si le prix reste sous le max prudent.
- `state.json` est persistant via cache GitHub Actions.
- Chaque run est journalisé dans l'**issue #1** avec `trigger`, exit code, durée, opportunités, mode/scope auction, lignes/timers et fallback.
- **Aucun achat, bid ou checkout automatique.**

### V4 — optimisation runtime Playwright déployée

- PR **#13** mergée dans `main` au commit `19942ce7cb26b2ba05bd51de8744d212933299bb`.
- Objectif : éviter de retélécharger Chromium/Headless Shell/FFmpeg à chaque VM GitHub.
- GitHub-hosted runners étant jetables, Chromium ne peut pas rester installé sur la même machine ; la stratégie est donc **cache Playwright + cache pip + probe de lancement**.
- Premier run production post-merge : `31479526838`, **cache miss attendu**, téléchargement initial puis sauvegarde d'environ 279 MB de cache Playwright ; le probe Chromium a réussi sans fallback `playwright install --with-deps chromium` ; scan V4 sain en **15 s**.
- Le prochain run production doit confirmer le **cache hit** : payload navigateur restauré, aucun redownload Chromium/FFmpeg/Headless Shell. Tant que ce deuxième run n'est pas audité, considérer P3 comme déployé mais validation cache-hit encore en attente.
- Si le probe Chromium échoue à cause des libs système d'un runner futur, fallback automatique `playwright install --with-deps chromium`.
- Cette optimisation ne change pas discovery/valorisation/alertes.

### V5 — expérimental, PR #8, NE PAS MERGER

- PR **#8**, branche exacte : `agent/v5-poketrace-cardmarket-market-data`.
- V5 reste un diagnostic **RAW eBay** séparé de la V4 graded GCC.
- Dernier resync complet **main → V5** après README canonique + P3 : merge `a964ffe97f7031d5d5eede74135b0bd86be7c4f0`. Cela ne merge pas V5 dans `main`.
- Dernier gros correctif Codex audité : `840c44f89ad6ba7aa4b9524161203c019b2eff47` (`Fix V5 canonical PokeTrace identity matching`).
- Tests de régression post-audit déjà ajoutés sur la branche V5 : commit `d727ca4325e07087d65d1545fa89219cfa410683`.
- Le workflow live V5 doit rester **manuel (`workflow_dispatch`)** pour protéger le quota PokeTrace Free.
- PokeTrace Free : clé stockée dans GitHub Secret `POKETRACE_API_KEY`, **250 req/j**, US + RAW uniquement, cadence locale effective ≥2.25 s, pas de Cardmarket EU/graded en Free.

#### Architecture resolver V5 retenue pour l'instant

1. **TCGdex = resolver principal multilingue**.
2. **PokeTrace Free = fallback identité + source market RAW US**.
3. Pokémon TCG API = dernier fallback anglais/unknown.
4. Matching visuel local + OCR ciblé = arbitres conservateurs seulement pour `AMBIGUOUS/INSUFFICIENT`.
5. **JustTCG** : candidat futur comme fallback / seconde opinion, pas principal tant qu'un benchmark live n'a pas prouvé qu'il bat TCGdex.
6. **Scrydex / Vision** : option sérieuse pour les cas durablement ambigus après épuisement de la chaîne gratuite ; ne pas introduire le coût avant d'avoir mesuré le pipeline gratuit corrigé.

#### Dernière référence live PokeTrace avant le correctif Codex

Échantillon d'environ 20 listings RAW :

- usable identities : **9** ;
- TCGdex hits : **4** ;
- PokeTrace exact : **0** ;
- rejets apparents nom/set/numéro : **112 / 41 / 2** sur 155 candidats ;
- market values found : **0** ;
- PokeTrace Free cache hits : **5** ;
- achats/bids/checkout : **0/0/0**.

Important : les anciens compteurs de rejet étaient trompeurs parce qu'ils ne comptaient que le premier champ bloquant. Le correctif Codex a ajouté des compteurs indépendants par champ.

#### Correctifs bloquants identifiés après audit du commit Codex

**Ne pas lancer le prochain Free live avant ces points + CI complète :**

1. **P0 — filtre `set` PokeTrace** : ne pas envoyer le nom d'affichage (`Base Set`, etc.) comme `set=`. Le filtre structuré PokeTrace attend son slug. Tant qu'on ne possède pas un slug PokeTrace vérifié, omettre le filtre `set` côté serveur et garder la validation de set stricte **localement**.
2. **P0 — numéro manquant** : `HybridPokemonCardResolver` doit pouvoir appeler PokeTrace avec un fort `name + set` même si `card_number` manque. TCGdex/Pokémon TCG peuvent rester dépendants du numéro ; PokeTrace doit pouvoir récupérer le troisième champ lorsqu'au moins 2 des 3 champs `{name,set,card_number}` sont présents.
3. **P1 — conflit de dénominateur TCGdex** : un numéro eBay complet contradictoire ne doit jamais être silencieusement réécrit. Exemple `4/130` vs TCGdex `004/102` → `AMBIGUOUS/reject`, alors que `4` → `004/102` reste une canonicalisation valide.
4. Refaire ensuite **toute la CI sur le repo synchronisé** : tous les tests V4, tous les tests V5, `compileall`, tous les YAML, `git diff --check`, sans appel PokeTrace live.
5. Seulement après : **un unique nouveau run PokeTrace Free**, comparer aux métriques ci-dessus avant toute décision JustTCG/Scrydex/Pro.

Ces blockers et leurs tests d'acceptation sont également documentés dans la conversation de la PR #8 afin qu'un agent Codex puisse reprendre directement depuis GitHub.

### Règles de gouvernance du projet

- **Ne jamais merger silencieusement la PR #8.** Discuter du live et des métriques avant merge.
- Ne pas passer PokeTrace Pro / Cardmarket payant tant que Free n'est pas correctement exploité et mesuré.
- Ne pas assouplir le matching juste pour atteindre artificiellement `15+/20` : `AMBIGUOUS` reste bloquant.
- Une source externe ne peut pas inventer une valeur achetable ; exact same-card/same-grader/same-grade reste prioritaire.
- Les données eBay listing-level (itemId, titre, URL, images, prix) restent mémoire-only dans le diagnostic V5 et ne doivent pas être persistées/loguées individuellement.
- Scrydex doit rester dans le radar, particulièrement son modèle `number` / `printed_number` / expansion / language et Vision.
- La cible `15+/20` est un objectif de couverture **si les preuves disponibles le permettent**, jamais une obligation qui justifie des faux positifs.

---

La version de production recommandée est la **V4 cloud GitHub Actions** : aucun Mac ne doit rester allumé. Voir [`README_CLOUD.md`](README_CLOUD.md) pour l'installation et le fonctionnement détaillé.

## V4 — état de production

Le watcher scanne **GCC Marketplace** toutes les 10 minutes via un déclencheur externe **Cron-job.org → `workflow_dispatch` GitHub Actions** et ne considère que les **cartes Pokémon individuelles**. Les boosters, packs, displays, boxes, ETB, coffrets, blisters, bundles, decks, tins et autres produits scellés/non-cartes sont exclus.

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

- `trigger=workflow_dispatch` pour la cadence production externe Cron-job.org ;
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
