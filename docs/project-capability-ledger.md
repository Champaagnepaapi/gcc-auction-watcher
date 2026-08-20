# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel vérifié le **20 août 2026** après le merge #151.

Ce fichier sert d'index anti-réimplémentation et de registre de supersession. Toujours re-vérifier `main` et les PRs live avant une action.

## Autorité courante

```text
V4 production branch             : main
Dernier runtime Global           : #151 / c9539ca521f69b43b3d93e621fb21447a69f3fe7
Global marketplace-first         : #147 + #148
Global schedule run registry     : issue #150 + #151
Global activation                : #145 + #146
V5 expérimentale                 : PR #8 / agent/v5-poketrace-cardmarket-market-data
V5 head                          : bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Statuts utilisés : `PROD_V4`, `MAIN_SUPPORT`, `GLOBAL_NOTIFY_ACTIVE`, `ROBOT_KB`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`.

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

#108/#109/#110/#113/#114/#115/#138 = historiques/superseded pour l'intégration.

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

Validation : Global 146/146, V4 51/51, live `32344120993`, TCGdex 5/5, PPT 4/5, PokeTrace 4/5, 1 conflit Mewtwo correctement bloqué.

## #145 / #146 — notifications + activation — `GLOBAL_NOTIFY_ACTIVE`

- gate économique complet avant notification ;
- dédup 14 jours ; re-alert TTL ou baisse `>=5%` ;
- state corrompu = fail-closed si delivery active ;
- `workflow_dispatch` toujours dry-run ;
- schedule heure minute 41 ;
- `.github/global-notify-activation=true` ;
- repo var `true` supportée ; `false` = kill switch prioritaire ;
- `NTFY_TOPIC` absent => fail-closed ;
- TCGdex Global-only : 2 tentatives, timeout 10 s, backoff .25, retry transport/502/503/504 seulement ;
- aucune transaction.

Preuve activation : run `32379733361`, job `96459686467`, `GLOBAL_NOTIFICATION_ACTIVE`, activation true, 0 notification faute d'opportunité confirmée.

## #147 — marketplace-first discovery — `MAIN_SUPPORT`

```text
GCC / Fanatics / COMC / magi / Cardova
 -> inventaire courant
 -> identité exacte
 -> TCGdex exact
 -> GCC SOLD exact optionnel
 -> PPT + PokeTrace
 -> décision économique
```

- bootstrap : inventaire existant mis en file immédiatement ;
- ensuite : new/changed/retryable ;
- disparition != SOLD ;
- seed list = retrieval/benchmark seulement ;
- GCC fair optionnel ; `EXTERNAL_ONLY` seulement avec externe exact/fort >=3 ventes ;
- state discovery persistant ;
- active auction non actionnable ; snapshot `≤5 min` observation seulement ;
- Cardova `AUTH_SESSION_INPUT_REQUIRED` sans session sûre.

Correctif GCC : le type de requête `FIXED_PRICE/AUCTION` est propagé explicitement au parser parce que `sellingTypeGroup` n'est pas toujours présent par row. Une auction sans champ type ne peut plus devenir `FIXED_ASK`.

Validation : head `2e656314...`, merge `5a1b0f05...`, run `32397363626`, Global 201/201, V4 51/51, inventory 1184, selected/pending 10/1174, transactions false.

## #148 — production cutover marketplace-first — `GLOBAL_NOTIFY_ACTIVE`

Le workflow permanent `v4-global-notify.yml` reste l'unique cron Global et exécute `v4_global_marketplace_notify_resilient.py`.

- cron `41 * * * *` inchangé ;
- manual dry-run ; activation #146 inchangée ;
- state `.global-marketplace-state` ;
- 10 pending/run initialement ;
- PPT 12 HTTP / 60 credits / floor 15000 ;
- aucun second schedule ; aucune transaction.

Validation : head `9ff96e9c...`, merge `ea9a69b3...`, run `32398465774`, Global 202/202, V4 51/51, inventory 1184, selected/pending 10/1174, TCGdex 5, PPT 1, PokeTrace 4, 4 conflits, 0 would-notify, transactions false.

## #151 — Global schedule run registry — `GLOBAL_NOTIFY_ACTIVE`

Problème résolu : le connecteur ChatGPT disponible peut lire un run connu mais ne peut pas énumérer directement les runs GitHub Actions `schedule` sans `run_id`.

Réutilisation : même pattern que le registre V4 issue #1 (`actions/github-script` + métadonnées minimales), mais registre séparé **issue #150** pour ne pas mélanger V4 et Global.

Contrat #151 :

- `v4-global-notify.yml` reste le même unique cron ; aucun workflow/schedule supplémentaire ;
- permission `issues: write` ajoutée uniquement pour commenter #150 ; `contents: read` conservé ;
- seul `github.event_name == 'schedule'` écrit dans #150 ; manual dispatch reste dry-run et sans registre ;
- finalizer `always()` ; si report absent/illisible, conserve au minimum run_id/SHA/activation/outcome/report_status ;
- si report disponible : inventaire, selected/pending, TCGdex/PPT/PokeTrace, confirmed candidates, sent et flags transaction ;
- aucun log complet, secret, cookie/session, donnée listing-level ou donnée de paiement recopié ;
- issue #1 reste V4-only.

Validation #151 :

```text
branch                        ops/v4-global-run-registry-20260820
head                          a424fb62cb5e0553929847d3b973411a8b61a561
merge                         c9539ca521f69b43b3d93e621fb21447a69f3fe7
CI/live                       32410224171 SUCCESS
validate/live jobs            96558656377 / 96558728745 SUCCESS
Global                        203/203 PASS
V4                             51/51 PASS
compile/YAML/diff             PASS
inventory                     1186
selected/pending              10 / 1176
TCGdex exact                  5
PPT                           1 match · 6 HTTP · 28 credits
PokeTrace                     4 matches · 6 requests
market conflicts              4 blocked
confirmed_would_notify        0
artifact                      9421951722
transactions                  false
```

La première vraie preuve du registre sera le premier commentaire automatique de #150 généré par un `schedule` post-#151 ; son `run_id` permettra ensuite l'inspection autonome jobs/logs/artifact.

---

# Robot KB / Neon — `ROBOT_KB`

- append-only ; provenance + payload brut ;
- SOLD uniquement si vente finale explicite + date + prix ;
- fixed baseline puis changements utiles ;
- fresh SOLD + historical backfill avec watermarks ;
- auction `≤5 min` reste observation, pas vente ;
- aucune disparition ne devient SOLD ;
- aucun hard gate KB-first sans profondeur suffisante.

Robot KB n'est pas la décision commerciale V4/Global.

---

# V5 — `V5_ONLY`

```text
PR      #8 OPEN / DRAFT / NON MERGED
branch  agent/v5-poketrace-cardmarket-market-data
head    bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

TCGdex reste le resolver normal. Emergency seulement après panne technique réelle, toujours fail-closed. PR #92/#96 restent child/shadow/deferred.

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
- Cardova reste fail-closed sans session sûre.