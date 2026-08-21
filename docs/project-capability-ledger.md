# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel vérifié le **21 août 2026** après le merge #154 et préparation de la migration Robot KB locale #157.

Ce fichier sert d'index anti-réimplémentation et de registre de supersession. Toujours re-vérifier `main` et les PRs live avant une action.

## Autorité courante

```text
V4 production branch             : main
main runtime                     : #154 / c3e3da39b79eb71cfdfc864bb865c4a4e7154e0c
Global marketplace-first         : #147 + #148
Global cadence 10 min            : #153 / e79e939c22173a020d12cb8a0878aa682df2a7a5
Global schedule run registry     : issue #150 + #151 / PROUVÉ LIVE
Global activation                : #145 + #146
TCGdex detailed variants         : #154
Robot KB storage migration       : PR #157 / PREPARED_LOCAL_MAC / NEON_CUTOVER_PENDING
V5 expérimentale                 : PR #8 / agent/v5-poketrace-cardmarket-market-data
V5 head                          : bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Statuts utilisés : `PROD_V4`, `MAIN_SUPPORT`, `GLOBAL_NOTIFY_ACTIVE`, `ROBOT_KB`, `PREPARED_LOCAL_MAC`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`.

---

# V4 production

## Discovery GCC — `PROD_V4`

- fixed : `/on-sale-items`, discovery complète avant caps économiques ;
- auctions : `/on-sale-items`, `AUCTION`, `ENDING_SOON`, `ON_SALE`, `endTime` individuel ;
- horizon principal ≤60 min + safety-net legacy ;
- Main Scanner cadencé extérieurement, pas de cron GitHub parallèle.

Capacités structurantes : #9, #50, #52, #104. Ne pas reconstruire un second collector GCC parallèle.

## Fast Lane — `PROD_V4`

- recheck ciblé des auctions déjà armées ;
- aucun nouveau discovery/provider ;
- `max_recommended` persistant ;
- aucun bid automatique.

PRs structurantes : #45 + #55.

## Arbitrage multi-marché — `PROD_V4`

```text
GCC listing
 -> TCGdex exact
 -> GCC SOLD exact
 -> PokeTrace graded exact
 -> PSA APR / eBay SOLD exact fallback/confirmation
 -> arbitrage evidence-strength
```

Chemins : `GCC_ONLY`, `GCC_EXTERNAL_CONFIRMED`, `EXTERNAL_RESCUE`, `EXTERNAL_PENDING`, `MARKET_CONFLICT_BLOCKED`.

RAW Cardmarket/TCGplayer reste secondaire/manual-review ; jamais fair value automatique d'un slab.

## TCGdex / PokeTrace #119→#135 — `PROD_V4`

- exact-coordinate ; padding collector ; set/localId ; unicité catalogue ;
- bridges provider exacts ;
- finish/set source-pinnés ;
- fallback générique catalogue immuable quand REST TCGdex est stale ;
- PokeTrace market-only après identité TCGdex.

Preuve prod #135 : run `32160680888` SUCCESS. Houndoom `100/098`, Meowth `109/098`, Moltres ex `112/098` récupérés vers `SV10`.

**Pas de treadmill d'alias carte-par-carte.** Toute correction future doit être une classe déterministe répétée et prouvée.

PR #126 = `SUPERSEDED`, ne pas merger.

## #154 — TCGdex `variants_detailed` — `PROD_V4 / MAIN_SUPPORT`

Après identité TCGdex déjà `EXACT`, la réponse détaillée peut désormais prouver des axes commerciaux sans créer un resolver parallèle :

- `normal` / `holo` / `reverse` ;
- `First Edition` / `Unlimited` / `Shadowless` quand explicites ;
- special foils supportés : Poké Ball, Master Ball, Cosmos, Galaxy, Cracked Ice ;
- langue détaillée doit rester compatible avec la langue canonique ;
- axe inconnu, malformed, plusieurs signatures restantes ou contradiction interne => fail-closed.

Une même entrée détaillée ne peut pas écraser silencieusement une valeur par une autre : `Unlimited + 1st Edition` ou `Poké Ball + Master Ball` devient `OPAQUE_MATERIAL_VARIANT` et bloque.

Le proof source-pinné japonais conserve la priorité ; `variants_detailed` ne peut pas le rétrécir. `pricing` et `thirdParty` dans ce payload sont ignorés pour la fair value des slabs.

Wiring : V4 canonical provider gate + Global PPT/PokeTrace après macro identité exacte.

Validation #154 :

```text
head                    bb21aeb118c66a3da5df6bc949ce64d23bab2c1b
merge                   c3e3da39b79eb71cfdfc864bb865c4a4e7154e0c
run                     32444255909 SUCCESS
validate/live           96660771327 / 96660823079 SUCCESS
Global                  221/221 PASS
V4 multimarket           51/51 PASS
full V4 validation      SUCCESS
inventory               1196
selected/pending        10 / 1186
TCGdex exact            5
PPT                     1 match · 6 HTTP · 28 credits
PokeTrace               4 matches · 6 requests
conflicts               4 blocked
would_notify            0
artifact                9433579221
transactions            false
```

## Autres capacités V4 déjà présentes

- queue anti-starvation ; smart external priority ; refresh adaptatif ;
- exact active eBay ASK context ;
- Structural Edge Hunter V2 ; Japan Edge séparé ;
- cert/OCR historiques ; Mislisted Slab hard-disabled ;
- Robot KB mirror/collectors séparés.

---

# Global Multi-Vault

## #139 — réintégration — `MAIN_SUPPORT`

A absorbé/revalidé le stack historique #108→#115 : common valuation, identité stricte, GCC/Cardova/magi/Fanatics/COMC, diagnostics, retrieval hardening, Magi SOLD guard, COMC fallback et live shadow read-only.

#108/#109/#110/#113/#114/#115/#138 = historiques/superseded pour l'intégration. Ce Stack #108→#115 reste `SHADOW/DEFERRED` en tant que provenance historique, pas une seconde production.

## #140 / #142 — économie + bridge exact — `MAIN_SUPPORT`

- actionnable : `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` seulement ;
- `ACTIVE_AUCTION` non actionnable ;
- `all_in_eur` obligatoire ;
- externe gradé exact obligatoire, minimum 3 ventes agrégées ;
- PPT/PokeTrace/eBay = famille corrélée `EBAY_GRADED_AGGREGATE` ;
- conflit GCC/externe matériel => `MARKET_CONFLICT_BLOCKED` ;
- avec GCC : fair confirmé = `min(GCC, externe)` ;
- bridge provider seulement après preuve macro exacte ; aucun fuzzy ;
- aucune transaction.

## #145 / #146 — notifications + activation — `GLOBAL_NOTIFY_ACTIVE`

- gate économique complet avant notification ;
- dédup 14 jours ; re-alert TTL ou baisse `>=5%` ;
- state corrompu = fail-closed si delivery active ;
- `workflow_dispatch` toujours dry-run ;
- `.github/global-notify-activation=true` ;
- repo var `true` supportée ; `false` = kill switch prioritaire ;
- `NTFY_TOPIC` absent => fail-closed ;
- aucune transaction.

Preuve activation historique : run `32379733361`.

## #147 / #148 — marketplace-first + cutover — `GLOBAL_NOTIFY_ACTIVE`

```text
GCC / Fanatics / COMC / magi / Cardova
 -> inventaire courant
 -> identité exacte
 -> TCGdex exact
 -> GCC SOLD exact optionnel
 -> PPT + PokeTrace
 -> décision économique
```

- bootstrap puis new/changed/retryable ;
- disparition != SOLD ;
- seed list = retrieval/benchmark seulement ;
- GCC fair optionnel ; `EXTERNAL_ONLY` seulement avec externe exact/fort >=3 ventes ;
- Cardova `AUTH_SESSION_INPUT_REQUIRED` sans session sûre ;
- state `.global-marketplace-state` ;
- 10 pending/run actuellement ;
- PPT 12 HTTP / 60 credits / floor 15000 ;
- aucune transaction.

Correctif GCC #147 : le type de requête `FIXED_PRICE/AUCTION` est propagé explicitement ; une auction sans `sellingTypeGroup` row-level ne peut pas devenir `FIXED_ASK`.

## #151 — Global schedule run registry — `GLOBAL_NOTIFY_ACTIVE`

Même pattern minimal que le registre V4 issue #1, mais registre séparé **issue #150**.

- seul `schedule` écrit dans #150 ;
- finalizer `always()` ;
- run_id/SHA/activation/outcome + métriques agrégées ;
- aucun log complet, secret, cookie/session, donnée listing-level ou paiement.

**Preuve production observée** : premier commentaire post-#151 = run `32411433425`, trigger `schedule`, commit `c9539ca...`, activation true, mode `GLOBAL_MARKETPLACE_NOTIFICATION_ACTIVE`, status success, 10 évaluées / 1166 pending, 0 sent, identity relaxed false, transactions false.

## #153 — cadence Global 10 min — `GLOBAL_NOTIFY_ACTIVE`

Le **même** `v4-global-notify.yml` passe à :

```text
1,11,21,31,41,51 * * * *
```

- aucun second cron ;
- batch 10/run et budgets/run inchangés ;
- manual toujours dry-run ; activation/kill switch inchangés.

Preuve schedule #153 : run `32443663511` sur `e79e939c...`, success, activation true, inventory 1196, selected 10, pending 1137, TCGdex 6, PPT 1, PokeTrace 2, 0 sent, transactions false.

---

# Fondations récupérées / ne pas réimplémenter

Le registre historique conserve notamment : P0/P1/P3 et PRs #51/#59/#60 ; PR #68/#72/#76 ; PR #62/#75 ; TCGdex identity cache ; `agent/source-scout-benchmark-20260814`. Aucun benchmark vérifié ne prouve un TCGdex `500/500`. #115 COMC fait partie du stack historique absorbé par #139.

---

# Robot KB — `ROBOT_KB`

- append-only ; provenance + payload brut ;
- SOLD uniquement si vente finale explicite + date + prix ;
- fixed baseline puis changements utiles ;
- fresh SOLD + historical backfill avec watermarks ;
- auction `≤5 min` reste observation, pas vente ;
- aucune disparition ne devient SOLD ;
- aucun hard gate KB-first sans profondeur suffisante.

Robot KB n'est pas la décision commerciale V4/Global.

## #157 — Neon → PostgreSQL Mac — `PREPARED_LOCAL_MAC / NEON_CUTOVER_PENDING`

La limite de stockage Neon a déclenché une migration de stockage, sans changement du contrat de données.

Réutilisation obligatoire : runtime P3 validé `1d06fe33b6fc640657255e15a8d17251aa02b6ce`, avec `KnowledgeBase.open(postgresql://...)`, sidecar et `postgres_backup` existants. Ne pas réimplémenter un second repository Robot KB.

Préparation #157 :

- PostgreSQL 16 local sur `127.0.0.1`, base `robot_pokemon_kb` ;
- migration source Neon par `pg_dump` secret-safe puis restore ;
- vérification stricte fingerprints/row counts source ↔ local avant marker `MIGRATION_VERIFIED` ;
- aucune URL Neon persistée : saisie masquée et variable éphémère seulement ;
- fixed/auction local à `:32`, SOLD fresh/backfill à `:17/:47`, backup local `03:10` ;
- 7 dumps complets locaux conservés ;
- base locale existante sans marker de migration = activation refusée ;
- cloud Neon reste actif pendant cette PR : le cutover est une phase séparée après preuve réelle sur le Mac.

**Ne jamais supprimer/couper Neon avant migration locale vérifiée.** Si le quota bloque les reads/dump, conserver Neon jusqu'au reset ou à un accès temporaire permettant l'export.

---

# V5 — `V5_ONLY`

```text
PR      #8 OPEN / DRAFT / NON MERGED
branch  agent/v5-poketrace-cardmarket-market-data
head    bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

TCGdex reste le resolver normal. PR #92/#96 restent child/shadow/deferred.

**PR #8 ne doit jamais être mergée dans `main` sans autorisation explicite.**

---

# PPT / corrélation

PPT = `SOLD_AGGREGATED`, jamais item-level SOLD. PPT/PokeTrace/eBay peuvent être corrélés et ne comptent pas naïvement comme marchés indépendants.

---

# Supersessions importantes

- #54 : stale/superseded ;
- #111 : ancien snapshot docs ;
- #126 : superseded par #127→#135 ;
- #108/#109/#110/#113/#114/#115/#138 : absorbées par #139 ;
- #141 : diagnostic superseded par #142/#140 ;
- ancien moteur seed-rotation Global : benchmark/historique après #147/#148 ;
- one-shots/temp : provenance uniquement, suppression seulement avec autorisation destructive explicite.

---

# Invariants

- V4/main canonique ;
- PR #8 jamais mergée sans autorisation explicite ;
- PokeTrace marché/prix après identité ;
- ASK/live auction/disparition != SOLD ;
- RAW != valeur slab ;
- aucune identité/langue/grader/grade/microvariante incompatible mélangée ;
- aucun achat, bid, checkout ou paiement automatique ;
- aucun secret dans repo/logs ;
- notification Global seulement après gate complet + activation ;
- `vars.GLOBAL_NOTIFY_ENABLED=false` coupe la lane immédiatement ;
- Robot KB local ne remplace Neon qu'après vérification source ↔ local ;
- Cardova reste fail-closed sans session sûre.