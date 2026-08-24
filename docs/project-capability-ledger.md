# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel vérifié le **24 août 2026** après merge #175 et preuves production post-merge.

Ce fichier sert d'index anti-réimplémentation et de registre de supersession. Toujours re-vérifier `main` et les PRs live avant une action.

## Autorité courante

```text
V4 production branch             : main
main                              : 950694d66b04112fc1182f0b21d6008bb4560204 / #175
Global marketplace-first         : PROD
Global scale                     : #156 / PROD
Global cadence                   : 20 min / workflow unique
Global schedule run registry     : issue #150 / PROUVÉ LIVE
Global notifications             : ACTIVES derrière gate complet
Magi native identity             : #173 / PROD
Magi coverage hardening          : #174 / OPEN / DRAFT / NON MERGED
V4 eBay hard-hang isolation      : #175 / PROD
Robot KB storage                 : PostgreSQL local Mac ACTIF
Neon automatic writers           : OFF / rollback manuel conservé
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Statuts utilisés : `PROD_V4`, `MAIN_SUPPORT`, `GLOBAL_NOTIFY_ACTIVE`, `ROBOT_KB`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`.

---

# V4 production

## Discovery GCC — `PROD_V4`

- fixed : `/on-sale-items`, discovery complète avant caps économiques ;
- auctions : `/on-sale-items`, `AUCTION`, `ENDING_SOON`, `ON_SALE`, `endTime` individuel ;
- horizon principal ≤60 min + safety-net legacy ;
- Main Scanner cadencé extérieurement via `workflow_dispatch`, pas de cron GitHub parallèle.

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

## TCGdex `variants_detailed` — #154 — `PROD_V4 / MAIN_SUPPORT`

Après identité TCGdex déjà `EXACT`, la réponse détaillée peut prouver des axes commerciaux déterministes : normal/holo/reverse, First Edition/Unlimited/Shadowless quand explicites, Poké Ball/Master Ball/Cosmos/Galaxy/Cracked Ice, langue exacte.

Axe inconnu, malformed, signatures incompatibles ou contradiction interne => fail-closed. `pricing` / `thirdParty` ne valorisent jamais automatiquement un slab.

## eBay hard-hang isolation — #175 — `PROD_V4`

Incident : runs `32664106071` et `32682740195` bloqués ~6 h après un appel eBay. `page.goto(... timeout=10000)` n'a ni retourné ni levé `TimeoutError`, indiquant un deadlock RPC Playwright/driver.

Correctif #175 :

- scrape eBay SOLD dans un sous-processus/browser jetable ;
- hard deadline 30 s par défaut ;
- kill du groupe de processus en cas de hang ;
- retour `PROVIDER_ERROR` fail-closed ;
- la lane V4 continue ;
- credentials inutiles retirés du child ;
- aucun changement matching/fair value/seuil notification.

Validation : **771 tests PASS** + compile/YAML/live comparison read-only PASS.

Preuve production post-merge sur `950694d66b04112fc1182f0b21d6008bb4560204` : runs `32738091183`, `32739149539`, `32740157203`, `32741180104`, `32742259467` tous SUCCESS, durées 129–598 s. Le mode de panne ~6 h n'est plus observé.

Le workflow V4 conserve `concurrency.group=gcc-auction-watcher` et `cancel-in-progress=false` : un run V4 bloqué faisait attendre les suivants de cette lane, mais n'immobilisait pas les workflows indépendants.

## Autres capacités V4 présentes

- queue anti-starvation ; smart external priority ; refresh adaptatif ;
- exact active eBay ASK context ;
- Structural Edge Hunter V2 ; Japan Edge séparé ;
- cert/OCR historiques ; Mislisted Slab hard-disabled ;
- Robot KB mirror/collectors séparés.

---

# Global Multi-Vault

## Réintégration / économie / activation — `GLOBAL_NOTIFY_ACTIVE`

Le stack historique #108→#115 a été absorbé par #139. #140/#142 ont posé la confirmation économique et les bridges exacts. #145/#146 ont activé les notifications. #147/#148 ont basculé en marketplace-first. #151 fournit le registre schedule issue #150. #156 scale à 50 listings/run. #168 ajoute Cardova public read-only. #169 porte la cadence à 20 min avec recovery/finalizer.

Architecture :

```text
GCC / Fanatics / COMC / magi / Cardova
 -> inventaire courant
 -> identité commerciale exacte
 -> TCGdex exact
 -> GCC SOLD exact optionnel
 -> PPT + PokeTrace
 -> décision économique
 -> notification seulement après gate complet
```

Invariants :

- actionnable : `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` seulement ;
- `ACTIVE_AUCTION` non actionnable ;
- all-in prouvé ;
- externe gradé exact suffisamment fort ;
- PPT/PokeTrace/eBay = famille corrélée `EBAY_GRADED_AGGREGATE` ;
- conflit matériel => blocage conservateur ;
- disparition != SOLD ;
- aucune transaction.

## Magi native identity — #173 — `GLOBAL_NOTIFY_ACTIVE`

#173 supprime l'obligation d'une projection latine après preuve japonaise TCGdex exacte.

- Unicode japonais supporté uniquement dans le runtime Global ; contrat de normalisation latin historique inchangé ;
- preuve japonaise TCGdex exacte obligatoire ;
- set/localId/dénominateur cohérents ;
- nom japonais exact présent dans le contenu produit ;
- source-pinned `S-P` prioritaire ;
- absence propre d'alias latin peut devenir identité commerciale japonaise native ;
- erreurs provider/budget/transient restent bloquantes ;
- aucune traduction/fuzzy.

Preuve production : run `32634964197` sur `b5ddc393850303e7ca542ae68e4ed4d1145340d3`, SUCCESS, Magi 9 exact, safety verte.

## Magi coverage hardening — #174 — `OPEN / DRAFT / NON MERGED`

Mission : réduire les rejets actifs restants sans relâcher l'identité.

Capacités en cours sur la branche `feat/v4-global-magi-coverage-20260823` : fallback full-number unique, retry détail borné, budget recovery séparé, set-name+unique-card exact lorsque prouvable. Les variantes sensibles, ambiguïtés et listings sous-spécifiés restent bloquants.

Dernier head avant synchronisation avec #175 : `b2bb6087cd7d6122b20a9a919839334f09e773a6`. Reprendre cette PR sur le `main` courant avant nouvelle modification. **Ne pas merger sans autorisation explicite.**

---

# Fondations récupérées / ne pas réimplémenter

- P0/P1/P3 Robot KB et stack #51/#59/#60/#62/#68/#72/#75/#76 ;
- TCGdex identity cache ;
- `agent/source-scout-benchmark-20260814` ;
- stack Global historique #108→#115 absorbé par #139 ;
- #126 superseded par #127→#135 ;
- #141 diagnostic superseded par #142/#140 ;
- anciens one-shots/temp = provenance seulement.

Une PR fermée/non mergée peut rester une source de récupération ; suivre les chaînes de supersession avant toute réimplémentation.

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

## PostgreSQL local Mac — ACTIF

Migration Neon → PostgreSQL local exécutée et vérifiée :

```text
lignes source/local             1,087,015
nombre de tables                35
marker                          MIGRATION_VERIFIED
schema versions                 [1, 2]
```

Runtime P3 réutilisé : `1d06fe33b6fc640657255e15a8d17251aa02b6ce`.

Collecte locale : fixed/auction `:32`, SOLD fresh/backfill `:17/:47`, backup `03:10`, 7 dumps locaux. `V4_USE=false`.

PR #166 a retiré les writers automatiques Neon. Neon reste rollback/recovery manuel ; ne pas réactiver automatiquement ni supprimer sans décision séparée.

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
- ancien moteur seed-rotation Global : historique/benchmark après #147/#148 ;
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
- Robot KB local séparé de la décision économique tant que `V4_USE=false` ;
- un provider externe doit échouer fail-closed sans immobiliser la lane entière.
