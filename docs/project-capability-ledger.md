# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel vérifié le **20 août 2026**.

Ce fichier sert d'index anti-réimplémentation. Avant tout changement non trivial, vérifier si la capacité existe déjà sur V4, Global, V5, Robot KB ou une branche historique/shadow.

## Autorité courante

```text
V4 production / main : c012284c423e9526fd2712001fdbce3a5cfafda3
V5 expérimentale     : PR #8 / agent/v5-poketrace-cardmarket-market-data
V5 head validé       : bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
TCGdex source pin    : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Statuts : `PROD_V4`, `MAIN_SUPPORT`, `GLOBAL_READ_ONLY`, `ROBOT_KB`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`.

---

# V4 production

## Discovery GCC item-level — `PROD_V4`

- auctions via `/on-sale-items`, `sellingTypeGroup=AUCTION`, `sortType=ENDING_SOON`, `status=ON_SALE`, `endTime` individuel ;
- horizon local ≤60 min ; safety-net legacy ;
- fixed discovery complète avant caps économiques ;
- couverture explicite `COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS`.

PRs structurantes : #9, #50, #52, #104. Ne pas reconstruire un second collector auction parallèle.

## Fast Lane finale — `PROD_V4`

PR #45 + #55 : recheck ciblé, aucun nouveau discovery/provider, `max_recommended` persisté et immuable, alerte finale seulement sous le plafond, aucune transaction.

## Arbitrage multi-marché canonique — `PROD_V4`

PR #33 + #35 et durcissements ultérieurs.

```text
GCC listing
  -> identité déterministe TCGdex
  -> GCC SOLD
  -> PokeTrace graded exact
  -> PSA APR / eBay SOLD exact
  -> arbitrage evidence-strength
```

Chemins : `GCC_ONLY`, `GCC_EXTERNAL_CONFIRMED`, `EXTERNAL_RESCUE`, `EXTERNAL_PENDING`, `MARKET_CONFLICT_BLOCKED`.

RAW Cardmarket/TCGplayer ne devient jamais fair value de slab.

## TCGdex / PokeTrace recovery #119→#135 — `PROD_V4`, AUTORITÉ COURANTE

- #119 : exact-coordinate registry ;
- #120/#121 : récupération déterministe set/localId + aliases set-level ;
- #122/#123 : unicité catalogue / `2 coordonnées sur 3` ;
- #124 : retrieval PokeTrace structuré après TCGdex ;
- #127 : padding collector provider conservé ;
- #128/#129 : bridges exacts + recherche JA canonique ;
- #130→#133 : diagnostics + finish source-pinné généralisé ;
- #134/#135 : réconciliation de set REST stale depuis le catalogue immuable.

Preuve production #135 : run `32160680888`, SUCCESS. Houndoom `100/098`, Meowth `109/098`, Moltres ex `112/098` -> `SV10`.

Règle : **pas de treadmill d'alias carte-par-carte**. Toute nouvelle correction d'identité doit correspondre à une classe répétée, déterministe et prouvée.

## PR #126 — `SUPERSEDED`

Ancienne lignée PokeTrace. Sa logique utile est absorbée par #127→#135. **Ne pas merger.**

## Queue / couverture externe — `PROD_V4`

PRs #43, #47, #77, #116 : anti-starvation, refresh adaptatif, smart priority, budget eBay borné, `PENDING_BUDGET` distinct d'un no-match, backoff provider.

Le backlog externe de la V4 principale reste une métrique opérationnelle séparée de la lane Global.

## Exact active ASK — `PROD_V4`

PR #78/#79 : eBay BIN exact comme contexte d'offre achetable, toujours ASK, jamais fair value ni opportunité à lui seul.

## Structural Edge Hunter V2 — `PROD_V4`

PR #80 : signaux cross-market/grader/stale/liquidity/relative-grade/inventory. Informatifs ; ne remplacent pas les gates économiques.

## Cert / OCR / Mislisted Slab — `DISABLED`

Historique #57, #63→#73. Lane Mislisted Slab hard-disabled en production par #103/#104 après faux positifs. Réactivation interdite sans phase dédiée read-only.

## Japan Edge Hunter — `PROD_V4`, lane séparée

PR #89, #94, #101 : ASK japonais exact PSA10, GCC SOLD exact + contexte externe, `MULTIMARKET_CONFIRMED` / `MARKET_CONFLICT_BLOCKED` etc. Aucun achat automatique.

---

# Global Multi-Vault — `GLOBAL_READ_ONLY` sur main

## Réintégration #139

PR #139 a réintégré proprement sur le `main` courant les capacités historiques #108→#115 :

- common valuation / strict commercial identity ;
- GCC, Cardova, magi, Fanatics, COMC ;
- rejection diagnostics ;
- retrieval hardening ;
- Magi SOLD guard ;
- COMC bounded fallback ;
- runner live manuel/read-only ;
- offline CI Global.

Les anciennes PR #108/#109/#110/#113/#114/#115 et la réintégration préparatoire #138 sont désormais des **sources historiques/superseded**, pas des PR à merger directement dans `main`.

## Confirmation économique #140

PR #140, merge main `c012284c423e9526fd2712001fdbce3a5cfafda3` :

- exact `FIXED_ASK` / `AUCTION_SNAPSHOT_LE5` seulement comme offres actionnables ;
- `ACTIVE_AUCTION` jamais actionnable ;
- `all_in_eur` obligatoire ;
- confirmation gradée externe obligatoire avant `would_notify` ;
- minimum 3 ventes agrégées ;
- GCC/externe >1.25 -> `MARKET_CONFLICT_BLOCKED` ;
- fair confirmé = `min(GCC, externe)` ;
- PPT/PokeTrace/eBay = une seule famille `EBAY_GRADED_AGGREGATE` ;
- conflit intrafamille matériel bloque ;
- PPT récent peut être primaire ; PokeTrace sans last-sale item-level reste corroboration selon contrat ;
- aucune notification réelle ni transaction.

## Bridge exact provider #142

PR #142 a été mergée dans #140 avant son merge vers main.

Capacité : corriger une **classe de nomenclature provider** après preuve macro exacte, sans fuzzy :

- full collector number avec dénominateur exact ;
- set exact ou préfixe set TCGdex exact ;
- langue exacte ;
- nom canonique + suffixe borné `V/VSTAR/VMAX/ex/GX` ou `Mega <nom> ex` ;
- hardening V4 des dimensions toujours appliqué ;
- `Unlimited` non matériel uniquement si TCGdex exact prouve `firstEdition=false` ;
- PPT generic fallback seulement si `externalCatalogId` absent et preuve set-code/full-number/name/unique ;
- `externalCatalogId` conflictuel bloque définitivement le fallback.

### Validation

Head combiné #140 `b10adebc1f6866ae4ec37e9ea01eeddd2a240c60` :

```text
Offline CI       32351952230 SUCCESS
Dispatcher CI    32351952209 SUCCESS
Global tests     146/146 PASS
V4 regressions    51/51 PASS
compile/YAML/diff PASS
```

Live read-only #142 `32344120993` :

```text
TCGdex exact      5/5
PPT matched       4/5
PokeTrace matched 4/5
would_notify      0
conflict blocked  1
```

Mewtwo 183/165 : GCC ~€155, externe ~€103.40, Fanatics ASK ~€99.10 -> ratio 1.499 -> `MARKET_CONFLICT_BLOCKED`.

Pikachu M-P reste `CLEAN_NO_MATCH` externe. **Ne pas ajouter un alias ponctuel sans classe répétée prouvée.**

## Statut d'activation

`GLOBAL_READ_ONLY` uniquement.

- workflow `v4-global-live-shadow.yml` reste `workflow_dispatch` manuel ;
- mode `economic_confirmation` read-only ;
- `notification_capable=false` dans le rapport ;
- aucun schedule Global ;
- aucun achat/bid/checkout/paiement ;
- le one-shot de #142 a été supprimé avant merge.

Une future activation de notifications doit être une **nouvelle phase** avec feature flag default-off, déduplication persistante, cadence explicite et live de validation.

## PR #141 — `SUPERSEDED_DIAGNOSTIC`

Le diagnostic de couverture #141 a servi à prouver la classe corrigée par #142. Ne pas merger #141 comme fonctionnalité : son résultat utile est absorbé par #142/#140.

---

# Robot KB / Neon — `ROBOT_KB`

- observations append-only ; provenance + raw payload ;
- `SALE_TRANSACTION` seulement avec SOLD explicite + date + prix final ;
- fixed hybride : recent + rotation + targeted ;
- SOLD frais + backfill avec watermarks/cursors durables ;
- snapshot auction ≤5m reste observation, pas vente ;
- aucun hard gate KB-first tant que profondeur insuffisante.

Robot KB reste séparé de la décision commerciale V4/Global.

---

# V5 expérimentale — `V5_ONLY`

PR #8 reste **OPEN / DRAFT / NON MERGED** dans `main`.

```text
branch agent/v5-poketrace-cardmarket-market-data
head   bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

Architecture normale : TCGdex exact + unicité déterministe + microvariant gates. Emergency seulement après vraie panne technique TCGdex via cache prouvé / TCG API / PokeTrace emergency, fail-closed.

PR #92 et #96 restent V5 shadow/deferred. Aucune de ces PR n'autorise le merge de #8.

---

# PPT

PokemonPriceTracker fournit des agrégats eBay gradés `SOLD_AGGREGATED`, jamais item-level SOLD. PPT/PokeTrace/eBay peuvent être corrélés ; ne pas les compter naïvement comme marchés indépendants.

PR #106/#107 restent des shadows historiques séparés ; la lane Global #140 réutilise un adapter strict dédié et ne transforme pas ces anciennes PR en production autonome.

---

# Supersessions importantes

- #54 : stale/superseded, dépendance déjà absorbée ;
- #111 : ancien snapshot docs ;
- #126 : ancienne lignée PokeTrace ; **DO NOT MERGE** ;
- #108/#109/#110/#113/#114/#115/#138 : stack Global historique absorbée/reconstruite par #139 ;
- #141 : diagnostic Global absorbé par #142 ;
- #142 : fonctionnalité absorbée dans #140 puis main ;
- anciens one-shots/temp diagnostics : mémoire historique seulement.

---

# Prochaine phase

État fonctionnel actuel :

1. V4 production normale continue indépendamment ;
2. Global Multi-Vault + confirmation économique est disponible sur main **en read-only seulement** ;
3. si une activation notification Global est souhaitée, elle doit être conçue séparément avec déduplication + cadence + feature flag + validation live ;
4. aucune transaction automatique ne doit être ajoutée ;
5. PR #8 reste séparée et non mergée.

## Invariants finaux

- V4/main canonique ;
- PR #8 jamais mergée sans autorisation explicite ;
- PokeTrace marché/prix après identité ;
- ASK/live auction != SOLD ;
- RAW != valeur slab ;
- aucune identité/langue/grader/grade/microvariante incompatible mélangée ;
- aucun achat, bid, checkout ou paiement automatique ;
- aucun secret dans repo/logs.
