# GCC Auction Watcher — Cloud GitHub Actions

Cette version tourne dans **GitHub Actions** : aucun Mac ne doit rester allumé.

## Réglage de production actuel

- marketplace : **GCC Marketplace** ;
- produits : **cartes Pokémon individuelles uniquement** ;
- découverte prix : **0 à 100 €** ;
- enchères : timer individuel **≤ 60 minutes** ;
- décote minimale : **30 %**, relevée automatiquement lorsque les comparables sont faibles ;
- scan : **toutes les 10 minutes, 24/7** ;
- notification : **ntfy** ;
- aucun achat, aucune enchère et aucun checkout automatique.

La cible économique historique était principalement 10–100 €. La découverte a ensuite été élargie à **0–100 €** pour éviter de rater une anomalie extrême. Un prix très bas ne crée jamais à lui seul une opportunité : les contrôles d'identité, de grade, de comparables, de prix maximal prudent et de validation externe restent obligatoires.

Les produits scellés/non-cartes sont exclus : boosters, packs, displays, boxes, ETB, coffrets, blisters, bundles, decks, tins, cases, etc.

## Fréquence GitHub Actions

Le workflow `.github/workflows/watcher.yml` utilise :

```yaml
schedule:
  - cron: "3,13,23,33,43,53 * * * *"
```

Les minutes `03,13,23,33,43,53` évitent les pics habituels du début de l'heure. GitHub Actions n'est pas un ordonnanceur temps réel : un run planifié peut parfois démarrer avec un léger retard.

Le workflow peut également être lancé manuellement via **Actions → GCC Auction Watcher → Run workflow**.

## Architecture de découverte

### 1. Prix fixes

Le watcher utilise l'API publique GCC `/on-sale-items` avec pagination jusqu'à couverture complète de la requête de production.

Le chemin fixed applique les filtres GCC disponibles puis conserve des défenses locales :

```text
/on-sale-items
        ↓
FIXED_PRICE
        ↓
Pokémon
        ↓
CARDS
        ↓
0–100 €
        ↓
file économique V4
```

La file économique fixed ne réanalyse pas inutilement tout l'inventaire à chaque run. Elle priorise :

```text
NEW → CHANGED → NEVER_EVALUATED → STALE
```

La TTL de réévaluation est de 24 h par défaut.

### 2. Enchères — item-level

Le chemin primaire auction ne dépend plus de la découverte des pages de ventes une par une. Il reproduit la logique de `/filtres/auctions` via l'API publique GCC :

```text
/on-sale-items
sellingTypeGroup=AUCTION
sortType=ENDING_SOON
status=ON_SALE
        ↓
pagination
        ↓
lots individuels
        ↓
endTime individuel
        ↓
Pokémon
+ carte
+ 0–100 €
+ timer ≤60 min
        ↓
analyse économique V4
```

Le watcher parcourt les lots dans l'ordre `ENDING_SOON`. Il peut s'arrêter lorsque :

- l'horizon de 60 minutes est prouvé comme franchi dans cet ordre ; ou
- l'inventaire correspondant est épuisé.

Chaque lot doit fournir un `endTime` exploitable. Si le watcher ne peut plus prouver correctement l'ordre, la pagination ou l'horizon, il ne prétend pas avoir une couverture complète.

### Statut spécifique auction

Lorsque le primaire item-level a correctement parcouru tout ce qui devait l'être jusqu'à l'horizon, le watcher expose :

```text
COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
```

Ce statut signifie que la couverture est complète pour les **listings auction découverts selon la requête production et l'ordre ENDING_SOON**, pas que le bot affirme avoir audité tout GCC sans filtre.

### Fallback legacy

L'ancien collector auction reste présent comme fallback de sécurité. Il est utilisé si le chemin API item-level ne peut plus établir une couverture fiable.

Le log expose explicitement :

```text
auction discovery mode: AUCTION_API_ITEM_LEVEL
auction discovery scope status: COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
auction legacy fallback used: false
```

## Couverture et diagnostic

Le watcher sépare désormais clairement :

1. **discovery coverage** : avons-nous correctement parcouru l'univers de découverte configuré ?
2. **economic coverage** : avons-nous correctement comptabilisé/évalué les candidats économiques ?

Le log affiche notamment pour fixed et auctions :

- protocole utilisé ;
- pages demandées/réussies/échouées ;
- retries ;
- lignes reçues ;
- listings uniques ;
- doublons ;
- raison de fin de pagination ;
- listings comptabilisés/non comptabilisés ;
- rejets par règles existantes ;
- échecs de parsing ;
- statut de couverture final.

Pour les auctions, on suit également :

- nombre de lots découverts ;
- nombre de `endTime` parsés ;
- nombre de candidats dans l'horizon ≤60 min ;
- nombre de lots sans timer exploitable ;
- utilisation ou non du fallback legacy.

Un résultat `0 opportunities` n'est présenté comme fiable que si les invariants de couverture sont cohérents.

## Journal issue #1

Chaque run V4, planifié ou manuel, écrit un commentaire dans l'**issue #1**.

Exemple de champs :

```text
timestamp_utc=...
run_id=...
run_attempt=1
trigger=schedule
commit_sha=...
scan_status=success
scan_exit_code=0
duration_seconds=...
final_opportunities=...
auction_discovery_mode=AUCTION_API_ITEM_LEVEL
auction_scope_status=COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
auction_discovered_rows=...
auction_timer_parsed=...
auction_ending_soon=...
auction_fallback_used=false
```

`trigger=schedule` permet de distinguer un vrai cron de production d'un `workflow_dispatch` manuel.

## État et anti-spam

GitHub Actions utilise des machines éphémères. Le workflow sauvegarde donc `state.json` dans le cache Actions et restaure cet état au run suivant.

La file économique fixed stocke uniquement les informations minimales nécessaires à son fonctionnement : identifiant GCC, dates de première/dernière observation et d'évaluation, dernier prix, empreintes de métadonnées cheap, version d'évaluation, dernier statut et indicateur actif. Aucun HTML, historique complet de ventes ou image n'est persisté dans cet état.

Une opportunité déjà signalée n'est renotifiée que si :

- son prix baisse d'au moins **10 %** ;
- sa décote gagne au moins **5 points** ; ou
- une enchère franchit un seuil temporel important.

Une alerte haute priorité unique peut être envoyée à **≤5 minutes** si le prix reste inférieur ou égal au prix maximal conseillé.

## Valorisation robuste

Le scanner GCC fonctionne indépendamment des sources externes. Le moteur de valorisation reste volontairement conservateur : il ne valide une opportunité que lorsque les comparables sont suffisamment exploitables.

### Pondération de récence

- ≤30 jours : `1.00` ;
- ≤90 jours : `0.70` ;
- ≤180 jours : `0.40` ;
- ≤365 jours : `0.20` ;
- au-delà : minimum `0.10` ;
- date inconnue : poids prudent `0.45`.

### Outliers

Les prix aberrants sont filtrés par **MAD** (écart absolu médian), avec fallback **IQR** lorsque le MAD est nul.

La notification peut afficher : borne basse, estimation centrale, borne haute, prix maximal conseillé, liquidité, dispersion, confiance, langue, numéro de carte et série.

Le prix actuel doit rester inférieur ou égal au prix maximal conseillé pour un prix fixe comme pour une enchère.

## Grades et arbitrage de grade

Le signal principal est toujours une vente de la **même société de grading et du même grade**.

En l'absence de marché suffisamment exploitable au grade cible, un grade inférieur de la même société peut produire une voie distincte **ARBITRAGE GRADE** lorsque son marché robuste justifie le prix actuel.

Cette logique ne transforme jamais artificiellement la valeur du grade inférieur en valeur du grade supérieur :

- la valeur exacte du grade supérieur reste inconnue ;
- le prix max reste prudent ;
- la confiance est réduite ;
- une preuve externe exacte suffisante est exigée avant notification.

Les ventes d'autres graders restent secondaires. Elles ne peuvent créer seules une estimation achetable sans ratio empirique suffisamment documenté et fondé sur assez d'observations.

## PSA Auction Prices Realized et eBay

Pour les lots PSA correctement identifiés, **PSA Auction Prices Realized (APR)** est interrogé en premier comme source indépendante.

Le numéro de carte est prioritaire dans le matching et les résultats ambigus sont rejetés. Les ventes du grade cible sont converties en euros avec le taux de référence disponible, puis estimées séparément afin que leur volume n'écrase pas l'historique GCC.

Si APR fournit au moins deux ventes fiables du grade exact, eBay public n'est pas lancé pour cette carte afin d'éviter les doubles comptes.

Si APR est insuffisant ou indisponible, eBay reste le fallback à échec rapide. Les graders autres que PSA ne déclenchent pas APR directement.

Budgets eBay actuels :

```yaml
EBAY_MAX_QUERIES_PER_CARD: "2"
EBAY_MAX_CARDS_PER_RUN: "2"
```

## Installation

### 1. Repository GitHub

Le code doit être présent dans un repository GitHub avec Actions activé.

### 2. Secrets

Dans :

**Repository → Settings → Secrets and variables → Actions**

les secrets utilisés par la V4 incluent notamment :

```text
NTFY_TOPIC
GCC_SESSION_B64
```

Ne jamais committer leur valeur dans le repository.

### 3. Lancer un test manuel

Dans l'onglet **Actions** :

**GCC Auction Watcher → Run workflow**

Puis vérifier notamment les sections :

```text
=== DISCOVERY COVERAGE ===
=== ECONOMIC COVERAGE ===
auction discovery mode: ...
auction discovery scope status: ...
auction legacy fallback used: ...
```

## Paramètres principaux

Dans `.github/workflows/watcher.yml` :

```yaml
MAX_PRICE_EUR: "100"
MIN_DISCOUNT_PCT: "30"
MAX_AUCTION_MINUTES: "60"
FIXED_REEVALUATION_TTL_HOURS: "24"
EBAY_MAX_QUERIES_PER_CARD: "2"
EBAY_MAX_CARDS_PER_RUN: "2"
PSA_APR_ENABLED: "true"
PSA_APR_MIN_COMPS: "2"
PSA_APR_MAX_CARDS_PER_RUN: "2"
PSA_APR_MAX_RESULTS: "20"
PSA_APR_NAV_TIMEOUT: "6000"
```

## V5 — expérimental

La V5 n'est **pas** la production actuelle et ne remplace pas la V4.

Son diagnostic RAW eBay travaille sur l'identité canonique et les données de marché :

- **TCGdex** : resolver catalogue multilingue principal ;
- **PokeTrace Free** : authentification et appels live validés, US RAW uniquement dans la phase actuelle ;
- matching exact PokeTrace : encore insuffisant sur le nom/set, donc aucune valeur n'est acceptée artificiellement ;
- PR V5 : conservée en draft tant que le matching exact n'est pas démontré ;
- **Scrydex** : candidat possible comme bridge d'identité canonique si la chaîne gratuite ne suffit pas.

Aucun passage à une dépendance payante ou à PokeTrace Pro n'est considéré comme nécessaire avant d'avoir prouvé le chemin d'identité de façon fiable.

## Optimisation future — Playwright/Chromium

Le workflow V4 exécute encore :

```text
playwright install --with-deps chromium
```

à chaque run. Le téléchargement/installation de Chromium représente une part importante du temps de préparation GitHub Actions, même si le scan V4 lui-même est désormais rapide grâce à l'API item-level.

Cette optimisation est volontairement classée **P3** : elle pourra être traitée plus tard via cache/image/installation conditionnelle après stabilisation fonctionnelle. Elle ne doit pas modifier la logique de découverte ou de valorisation.

## Sécurité

Le projet est un watcher/outil d'aide à la décision uniquement.

**Purchases = 0 — Bids = 0 — Checkout = 0.**
