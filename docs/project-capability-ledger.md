# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel re-vérifié le **1 septembre 2026** après #216/#217, #219 et #220. Le code/Git/GitHub réel reste prioritaire sur ce document.

Ce fichier sert d'index anti-réimplémentation et de registre de supersession. Toujours re-vérifier `main`, les PRs et les workflows live avant une action.

## Autorité courante

```text
V4 production branch             : main
V4 runtime production            : 6a33ac33faa324f0fc1c6124fbb49bd736382b75 / #220
TCGdex outage resilience         : #216/#217 / PROD_V4 / merge 03824158ac899cf142199c42d4525386a573bc15
TCGdex validated runtime         : 53a7fd0a47d100d851c347c3fadb79e4f754d07b
TCGdex natural prod proof        : run 33489103277 SUCCESS / breaker exact / 2029 -> 2010
Future-start auction guard       : #220 / PROD_V4 / 6a33ac33faa324f0fc1c6124fbb49bd736382b75
#220 natural production proof    : run 33490823534 SUCCESS / 253 s / discovery COMPLETE / backlog 1998
External pending throughput      : #214 / PROD_V4 / P4 16 + eBay 16 / auction max 4
Auction order hardening          : #211 + #212 / PROD_V4
Magi native identity             : #174 + #177 / PROD_V4
Magi recovery budget             : #178 / PROD_V4 / total 36 / broad 28
Global schedule watchdog         : #179 / PROD_V4
Global marketplace-first         : #147 + #148 / PROD_V4
Global scale                     : #156 / 50 listings par run
Global cadence                   : 20 min (`1,21,41`)
Global schedule run registry     : issue #150 + #151 / PROUVÉ LIVE
Robot KB local cutover           : #166 / PostgreSQL Mac ACTIF
Robot KB multisource             : #180 / ROBOT_KB
Robot KB configurator executable : #219 / MAIN_SUPPORT / 2aef339135df8b4a183ad4ba030b9e603ea9e696
P3 rarity-symbol print_run       : #207 / P3_ONLY / merge df32a19c237a75e4a1c3bb9dba938fd59fc09665
Neon writers                     : automatiques OFF / rollback manuel
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
V5 head                          : bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Statuts : `PROD_V4`, `MAIN_SUPPORT`, `GLOBAL_NOTIFY_ACTIVE`, `ROBOT_KB`, `P3_ONLY`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`, `STALE_OPEN`.

---

# V4 production

## Discovery GCC — `PROD_V4`

- fixed : `/on-sale-items`, discovery complète avant caps économiques ;
- auctions : `AUCTION + ON_SALE + ENDING_SOON` avec `endTime` individuel ;
- horizon principal ≤60 min + safety-net legacy ;
- #211/#212 : dérive d'ordre => récupération exhaustive bornée de la requête filtrée puis horizon local ;
- erreurs structurelles de pagination/endTime restent fail-closed ;
- Main Scanner cadencé extérieurement ; pas de cron GitHub parallèle.

Capacités structurantes : #9, #50, #52, #104, #211/#212, #220.

## #220 — future-start auction guard — `PROD_V4`

Une enchère prouvée comme future-start est exclue avant que starting price ou countdown-to-start puissent être interprétés comme bid courant / temps avant fin.

Preuves admises : timestamp GCC structuré + row id stable, ou preuve UI forte et explicite. Timestamp absent/malformé => aucune supposition. Le guard se superpose au hardening #211/#212.

Aucun changement fair value, threshold, identity, provider budget ou notification.

Première preuve naturelle : run `33490823534` sur `main@6a33ac33...` SUCCESS en 253 s ; discovery auction `COMPLETE`, 24 rows / 24 timers, 0 fallback et 0 enchère éligible ≤60 min. Ce snapshot n'avait donc aucun cas future-start positif à exclure, mais confirme l'absence de régression du collector courant.

## Fast Lane — `PROD_V4`

- recheck ciblé des auctions déjà armées à ≤5 min ;
- `max_recommended` persistant ;
- aucun bid automatique.

PRs structurantes : #45 + #55.

## Arbitrage multi-marché — `PROD_V4`

```text
listing exact
 -> TCGdex exact
 -> GCC SOLD exact si disponible
 -> PokeTrace/PPT graded aggregate exact
 -> PSA APR / eBay SOLD exact lorsque disponible
 -> arbitrage evidence-strength
```

Chemins : `GCC_ONLY`, `GCC_EXTERNAL_CONFIRMED`, `EXTERNAL_RESCUE`, `EXTERNAL_PENDING`, `MARKET_CONFLICT_BLOCKED`.

RAW Cardmarket/TCGplayer reste secondaire/manual-review ; jamais fair value automatique d'un slab.

## #214 — débit `EXTERNAL_PENDING` borné — `PROD_V4`

```text
P4 scheduling                    16/run
P4 hard ceiling                  20/run
eBay SOLD total                  16/run
fixed eBay reserve               12/run
auction eBay max                 4/run
budget-only cooldown             5 min
PSA APR max                      2/run
provider-error backoff           inchangé
```

Le drain est prouvé. Les provider failures restent fail-visible et ne deviennent jamais clean no-match. Backlog observé sur `33490823534` : `1998`.

## #216/#217 — TCGdex transport/run resilience — `PROD_V4`

Réutilise #145 transport + pattern breaker #189 :

```text
logical call                     max 2 attempts
retry                            Timeout / ConnectionError / 502/503/504
breaker                          2 exhausted logical calls in a row
open circuit                     skip remaining TCGdex network calls this run
classification                   ERROR / fail-closed
real provider response           reset streak
new process                      retry provider from closed circuit
```

Validation pré-merge : 845 PASS / 2 skipped, compile/YAML/diff PASS, live compare superset.

Première preuve naturelle `33489103277` sur `main@03824158...` : SUCCESS, 16 attempted / 0 exact / 0 no-match / 16 errors, breaker ouvert exactement après 2 appels épuisés, scanner 274 s vs ~397 s pré-fix, backlog 2029 -> 2010.

Sur le run post-#220 `33490823534`, TCGdex reste en panne : 16 attempted / 0 exact / 0 no-match / 16 errors, avec breaker conforme.

Aucune identité, économie, notification ou sémantique provider n'a été relâchée.

## TCGdex / PokeTrace #119→#135 — `PROD_V4`

- exact-coordinate ; padding collector ; set/localId ; unicité catalogue ;
- bridges provider exacts ;
- finish/set source-pinnés ;
- fallback catalogue immuable quand REST TCGdex est stale ;
- PokeTrace market-only après identité TCGdex.

**Pas de treadmill d'alias carte-par-carte.**

## #154 — TCGdex `variants_detailed` — `PROD_V4 / MAIN_SUPPORT`

Peut prouver après identité TCGdex `EXACT` : normal/holo/reverse, First Edition/Unlimited/Shadowless, Poké Ball/Master Ball/Cosmos/Galaxy/Cracked Ice, langue exacte.

Axes inconnus/multiples/malformés/contradictoires => fail-closed. `pricing` / `thirdParty` TCGdex n'est pas une fair value slab.

---

# Global Multi-Vault — `GLOBAL_NOTIFY_ACTIVE`

Surface canonique : **GCC / Cardova / Magi / Fanatics / COMC**.

```text
marketplace inventory
 -> identité commerciale exacte
 -> TCGdex exact + microvariante
 -> GCC SOLD exact optionnel
 -> PPT + PokeTrace graded aggregate
 -> décision économique
 -> notification seulement si gate complet
```

- disappearance != SOLD ;
- `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` seulement pour l'actionnable ;
- `ACTIVE_AUCTION` non actionnable ;
- PPT/PokeTrace/eBay = famille corrélée `EBAY_GRADED_AGGREGATE` ;
- aucune transaction.

Scale : 50 listings/run, PPT 35 HTTP / 180 credits / floor 15000, PokeTrace 60, cadence 20 min, inner timeout 17 min, job timeout 25 min.

#179 ajoute le watchdog/rattrapage borné sans seconde lane économique.

---

# Magi native identity — `PROD_V4`

#174 + #177 établissent la récupération déterministe. #178 garde le plafond total 36 et réserve la preuve exacte : broad/nonpriority 28 max, exact card-search/detail reserve 8.

Les cinq classes historiques sans preuve suffisante restent bloquées. Pas de fallback name-only ni alias carte-par-carte.

---

# Robot KB — `ROBOT_KB`

Contrat : append-only, provenance + payload brut, SOLD finaux prouvés prioritaires, fixed baseline + changements utiles, auction SOLD final prioritaire, snapshot ≤5 min fallback seulement, ASK/live/disparition/WAITING_FOR_PAYMENT != vente.

PostgreSQL local Mac actif ; `V4_USE=false`. Neon writers automatiques OFF ; rollback/recovery manuel.

## #180 — multisource local — `ROBOT_KB`

Fanatics / COMC / Magi / Cardova publics + PokeTrace + PokemonPriceTracker, avec séparation stricte des sémantiques :

- `SOLD_AGGREGATED` != item-level SOLD ;
- `cardmarket_unsold` = `FIXED_ASK_AGGREGATED` ;
- ASK reste ASK ;
- secrets payants uniquement dans le Trousseau macOS.

## #207 — rarity-symbol `print_run` — `P3_ONLY`

Mergée uniquement dans `agent/p3-postgres-durable-shadow`, merge `df32a19c...`.

Ajoute `NO_RARITY_SYMBOL` et `RARITY_SYMBOL_PRESENT` sur l'axe existant `print_run`. Aucun des deux n'implique First Edition/Unlimited. **Aucune migration durable du PostgreSQL utilisateur n'a été exécutée.**

## #219 — configurateur API exécutable — `MAIN_SUPPORT`

Port propre de #182 : mode `100644 -> 100755`, blob/contenu inchangé. Merge `2aef3391...`.

## Cardova durable — `DEFERRED / EXPLICIT_AUTH_REQUIRED`

Stack #199/#204/#205/#206/#208/#209/#210 : recherche, dry-runs, rollback rehearsal et guarded commit path. #210 reste OPEN/DRAFT/NON-MERGED et **aucune écriture durable n'est autorisée par défaut**.

---

# V5 — `V5_ONLY`

```text
PR      #8 OPEN / DRAFT / NON MERGED
branch  agent/v5-poketrace-cardmarket-market-data
head    bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

TCGdex reste le resolver normal. PokeTrace reste marché/prix après identité. #92/#96 restent child/shadow/deferred.

**PR #8 ne doit jamais être mergée dans `main` sans autorisation explicite.**

---

# Supersessions / provenance importantes

- #54 : stale/superseded ;
- #111 : ancien snapshot docs ;
- #126 : superseded par #127→#135 ;
- #108/#109/#110/#113/#114/#115/#138 : absorbées par #139 ;
- #141 : superseded par #142/#140 ;
- #159 : superseded fonctionnellement par #177 ;
- #174/#177/#178/#179/#180 : MERGED ;
- #211/#212 : MERGED comme une seule capacité runtime ;
- #214 : MERGED ;
- #216/#217 : MERGED comme une seule capacité runtime ; #217 était le miroir de merge ;
- #182 : superseded par le port current-main #219 ;
- #186 : superseded par le port current-main #220 ;
- ancien moteur seed-rotation Global : historique après #147/#148 ;
- one-shots/temp : provenance uniquement.

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
- Robot KB local séparé de V4 ;
- aucune écriture durable Cardova sans autorisation explicite ;
- ambiguïté et variantes sensibles restent fail-closed.
