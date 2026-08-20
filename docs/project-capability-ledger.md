# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel vérifié le **20 août 2026** après le merge production marketplace-first #148.

Ce fichier sert d'index anti-réimplémentation et de registre de supersession. Toujours re-vérifier `main` et les PRs live avant une action.

## Autorité courante

```text
V4 production branch             : main
Dernier runtime Global           : #148 / ea9a69b375434031c935de8d25fcc12acd1a1c93
Global marketplace-first         : #147 + #148
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

Capacités structurantes déjà livrées : #9, #50, #52, #104. Ne pas reconstruire un second collector GCC parallèle.

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

RAW Cardmarket/TCGplayer reste un signal secondaire/manual-review ; jamais fair value automatique d'un slab.

## TCGdex / PokeTrace #119→#135 — `PROD_V4`

Déjà présent :

- exact-coordinate ;
- padding collector ;
- set/localId ;
- unicité catalogue ;
- bridges provider exacts ;
- finish/set source-pinnés ;
- fallback générique catalogue immuable lorsque REST TCGdex est stale ;
- PokeTrace market-only après identité TCGdex.

Preuve prod #135 : run `32160680888` SUCCESS. Houndoom `100/098`, Meowth `109/098`, Moltres ex `112/098` récupérés vers `SV10`.

**Pas de treadmill d'alias carte-par-carte.** Toute correction future doit être une classe déterministe répétée et prouvée.

PR #126 = `SUPERSEDED`, ne pas merger.

## Autres capacités V4 déjà présentes

- queue anti-starvation ;
- smart external priority ;
- refresh adaptatif ;
- exact active eBay ASK context ;
- Structural Edge Hunter V2 ;
- Japan Edge Hunter séparé ;
- cert/OCR historiques ;
- Mislisted Slab hard-disabled ;
- Robot KB mirror/collectors séparés.

---

# Global Multi-Vault

## #139 — réintégration — `MAIN_SUPPORT`

A absorbé/revalidé le stack historique #108→#115 : common valuation, identité stricte, GCC/Cardova/magi/Fanatics/COMC, diagnostics, retrieval hardening, Magi SOLD guard, COMC fallback et live shadow read-only.

Anciennes PR #108/#109/#110/#113/#114/#115/#138 = historiques/superseded pour l'intégration.

## #140 — confirmation économique — `MAIN_SUPPORT`

- `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` seulement comme offres actionnables ;
- `ACTIVE_AUCTION` non actionnable ;
- `all_in_eur` obligatoire ;
- externe gradé exact obligatoire avant notification ;
- minimum 3 ventes agrégées ;
- PPT/PokeTrace/eBay = famille corrélée `EBAY_GRADED_AGGREGATE` ;
- conflit GCC/externe matériel => `MARKET_CONFLICT_BLOCKED` ;
- avec GCC : fair confirmé = `min(GCC, externe)` ;
- aucune transaction.

## #142 — bridge exact provider — `MAIN_SUPPORT`

Après preuve macro exacte uniquement :

- full collector number ;
- set exact ou préfixe TCGdex exact ;
- langue exacte ;
- nomenclature mécanique bornée provider ;
- `Unlimited` non matériel uniquement lorsque le catalogue exact prouve `firstEdition=false` ;
- `externalCatalogId` conflictuel bloque ;
- aucun fuzzy.

Validation #140/#142 : Global 146/146, V4 51/51, live `32344120993`, TCGdex 5/5, PPT 4/5, PokeTrace 4/5, 1 conflit Mewtwo correctement bloqué.

## #145 — notifications confirmées — `MAIN_SUPPORT`

- notification uniquement après gate économique complet ;
- dédup 14 jours ;
- re-alert après TTL ou baisse `>=5%` ;
- state corrompu = fail-closed si delivery active ;
- `workflow_dispatch` toujours dry-run ;
- cron horaire minute 41 ;
- aucune transaction.

### Résilience TCGdex Global-only

- max 2 tentatives ;
- timeout 10 s ;
- backoff 0.25 s ;
- retry Timeout/ConnectionError/502/503/504 ;
- 404/no-match jamais transformé ;
- échec final reste erreur ;
- aucun gate identité relâché ;
- scanner V4 canonique inchangé.

Validation #145 : Global 164/164, V4 51/51, run `32359861668` SUCCESS, merge `929d0d24ba959ba1ff30b2d73b1df5adc1d460e6`.

## #146 — activation réelle — `GLOBAL_NOTIFY_ACTIVE`

- `.github/global-notify-activation = true` pour les schedules ;
- repo var `GLOBAL_NOTIFY_ENABLED=true` supportée ;
- repo var `GLOBAL_NOTIFY_ENABLED=false` = kill switch prioritaire ;
- manual dispatch toujours dry-run ;
- `NTFY_TOPIC` absent => fail-closed ;
- aucune transaction.

Preuve production activation : run `32379733361`, job `96459686467`, `GLOBAL_NOTIFICATION_ACTIVE`, activation true, 0 notification faute d'opportunité confirmée, aucune transaction.

## #147 — marketplace-first discovery — `MAIN_SUPPORT`

La discovery principale Global est désormais **offre-first** :

```text
GCC / Fanatics / COMC / magi / Cardova
 -> inventaire courant
 -> identité exacte
 -> TCGdex exact
 -> GCC SOLD exact optionnel
 -> PPT + PokeTrace
 -> décision économique
```

Comportement :

- bootstrap : inventaire existant mis en file immédiatement et évalué économiquement ;
- ensuite : nouvelles annonces + changements économiques + retryables ;
- disparition != SOLD ;
- ancienne seed list = retrieval/benchmark uniquement ;
- GCC fair est optionnel ;
- `EXTERNAL_ONLY` possible uniquement avec externe exact/fort >=3 ventes ;
- état discovery persistant ;
- active auction non actionnable ;
- snapshot `≤5 min` observation seulement ;
- Cardova `AUTH_SESSION_INPUT_REQUIRED` sans session sûre.

### Correctif GCC request-type

Régression découverte en live : l'API GCC n'écho pas toujours `sellingTypeGroup` dans chaque row. Le parser utilisait alors un mauvais fallback et pouvait transformer une auction en `FIXED_ASK`.

Fix final : le type de requête `FIXED_PRICE/AUCTION` est propagé explicitement au parser. Deux tests dédiés verrouillent ce contrat.

Validation #147 :

```text
head                          2e65631416d0b39947de47ed4df3d37a4a87cbdc
merge                         5a1b0f050098b560e812a4dc6e64a9f8d40a8897
CI/live                       32397363626 SUCCESS
Global                        201/201 PASS
V4                             51/51 PASS
GCC exact                     1172
Fanatics exact                1
COMC exact                    11
magi exact                    0
inventory                     1184
selected/pending              10 / 1174
PPT                           1 match · 6 HTTP · 28 credits
PokeTrace                     4 matches · 6 requests
confirmed_would_notify        0
transactions                  false
```

## #148 — production cutover marketplace-first — `GLOBAL_NOTIFY_ACTIVE`

Le workflow permanent `.github/workflows/v4-global-notify.yml` reste l'unique cron Global et exécute désormais `v4_global_marketplace_notify_resilient.py`.

Contrat :

- cron `41 * * * *` inchangé ;
- manual dispatch dry-run ;
- activation #146 inchangée ;
- state `.global-marketplace-state` ;
- 10 pending evaluations/run initialement ;
- PPT 12 HTTP / 60 credits / daily floor 15000 ;
- résilience TCGdex bornée ;
- aucune transaction ;
- aucun second schedule.

Validation #148 :

```text
branch                        ops/v4-global-marketplace-cutover-20260820
head                          9ff96e9cd9124944e50bb55e990289f5fd07492f
merge                         ea9a69b375434031c935de8d25fcc12acd1a1c93
CI/live                       32398465774 SUCCESS
Global                        202/202 PASS
V4                             51/51 PASS
compile/YAML/diff             PASS
GCC exact                     1172
Fanatics exact                1
COMC exact                    11
magi exact                    0
inventory                     1184
selected/pending              10 / 1174
catalog SOLD                  780
catalog fair                  100
TCGdex exact                  5
PPT                           1 match · 6 HTTP · 28 credits
PokeTrace                     4 matches · 6 requests
market conflicts              4 blocked
confirmed_would_notify        0
artifact                      9417682288
transactions                  false
identity_gate_relaxed         false
```

Le cutover code est mergé et le workflow de production pointe vers marketplace-first. La preuve encore à observer est le premier vrai run `schedule` post-#148 sur `main` ; ne pas prétendre l'avoir observé sans run ID/logs.

---

# Robot KB / Neon — `ROBOT_KB`

- append-only ;
- provenance + payload brut ;
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

TCGdex reste le resolver normal. Emergency uniquement après panne technique réelle et toujours fail-closed.

PR #92/#96 restent des child/shadow/deferred. **PR #8 ne doit jamais être mergée dans `main` sans autorisation explicite.**

---

# PPT / corrélation

Les métriques eBay gradées PPT sont `SOLD_AGGREGATED`, jamais item-level SOLD. PPT/PokeTrace/eBay peuvent être corrélés et ne comptent pas naïvement comme marchés indépendants.

PR #106/#107 restent des shadows historiques séparés ; Global utilise son adapter strict intégré.

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