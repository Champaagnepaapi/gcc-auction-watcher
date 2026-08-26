# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel re-vérifié le **26 août 2026** sur GitHub live. Le code/Git/GitHub réel reste prioritaire sur ce document.

Ce fichier sert d'index anti-réimplémentation et de registre de supersession. Toujours re-vérifier `main`, les PRs et les workflows live avant une action.

## Autorité courante

```text
V4 production branch             : main
main runtime #180                : 9365f5cd9f8949580c4e48f00ba8c4e419c22145
main docs closeout               : 6fcda6b5dda576f2648c1f6a05a98f7d8638d385
Magi native identity             : #173 + #174 + #177 / PROD_V4
Magi recovery budget             : #178 MERGED / 545223613ce21e6c4cf886e07201bc3c105a5e69
Global schedule watchdog         : #179 MERGED / ac5f7c734685422612a0f24690af22910eefa951
Global marketplace-first         : #147 + #148
Global scale                     : #156 / 50 listings par run
Global cadence                   : 20 min (`1,21,41`)
Global schedule run registry     : issue #150 + #151 / PROUVÉ LIVE
Global activation                : #145 + #146
Cardova public read-only         : #168
Global timeout recovery          : #169
Robot KB local cutover           : #166 / PostgreSQL Mac ACTIF
Robot KB multisource             : #180 MERGED / code prêt / Mac install PENDING
Neon writers                     : automatiques OFF / rollback manuel
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
V5 head                          : bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Statuts utilisés : `PROD_V4`, `MAIN_SUPPORT`, `GLOBAL_NOTIFY_ACTIVE`, `ROBOT_KB`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`, `STALE_OPEN`.

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
listing exact
 -> TCGdex exact
 -> GCC SOLD exact si disponible
 -> PokeTrace/PPT graded aggregate exact
 -> PSA APR / eBay SOLD exact lorsque disponible
 -> arbitrage evidence-strength
```

Chemins historiques conservés : `GCC_ONLY`, `GCC_EXTERNAL_CONFIRMED`, `EXTERNAL_RESCUE`, `EXTERNAL_PENDING`, `MARKET_CONFLICT_BLOCKED`.

RAW Cardmarket/TCGplayer reste secondaire/manual-review ; jamais fair value automatique d'un slab.

## TCGdex / PokeTrace #119→#135 — `PROD_V4`

- exact-coordinate ; padding collector ; set/localId ; unicité catalogue ;
- bridges provider exacts ;
- finish/set source-pinnés ;
- fallback générique catalogue immuable quand REST TCGdex est stale ;
- PokeTrace market-only après identité TCGdex.

**Pas de treadmill d'alias carte-par-carte.** Toute correction future doit être une classe déterministe répétée et prouvée.

PR #126 = `SUPERSEDED`, ne pas merger.

## #154 — TCGdex `variants_detailed` — `PROD_V4 / MAIN_SUPPORT`

Après identité TCGdex déjà `EXACT`, la réponse détaillée peut prouver des axes commerciaux sans créer un resolver parallèle : normal/holo/reverse, First Edition/Unlimited/Shadowless, Poké Ball/Master Ball/Cosmos/Galaxy/Cracked Ice et langue exacte.

Axes inconnus, multiples, malformés ou contradictoires restent fail-closed. `pricing` / `thirdParty` TCGdex n'est pas utilisé pour valoriser un slab.

---

# Global Multi-Vault — `GLOBAL_NOTIFY_ACTIVE`

## #139 — réintégration du stack Global historique

#139 a absorbé/revalidé le stack historique #108→#115. #140/#142 ont ajouté la confirmation économique exacte. #145/#146 ont ajouté puis activé la notification. #147/#148 ont basculé la découverte en marketplace-first. #151 a ajouté le registre #150. #179 ajoute la récupération des schedules GitHub manqués depuis le heartbeat Main Scanner sans créer une seconde lane économique.

Surface marketplace canonique : **GCC/Cardova/magi/Fanatics/COMC**.

```text
GCC / Fanatics / COMC / magi / Cardova
 -> inventaire courant
 -> identité exacte
 -> TCGdex exact
 -> GCC SOLD exact optionnel
 -> PPT + PokeTrace graded aggregate
 -> décision économique
 -> notification seulement si gate complet
```

- bootstrap puis new/changed/retryable ;
- disparition != SOLD ;
- `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` seulement pour l'actionnable ;
- `ACTIVE_AUCTION` non actionnable ;
- PPT/PokeTrace/eBay = même famille corrélée `EBAY_GRADED_AGGREGATE` ;
- aucune transaction.

## Scale + cadence courants

```text
batch                            50 listings/run
PPT HTTP                         35 max/run
PPT credits                      180 max/run
PPT daily floor                  15000
PokeTrace                        60 requests max/run
Global cron                      1,21,41 * * * *
marketplace inner timeout        17 min
scan job timeout                 25 min
```

PR #156 fournit le scale 50. PR #169 protège la cadence 20 min contre l'empilement de runs longs. PR #179 ajoute un watchdog/rattrapage borné des schedules manqués.

---

# Magi native identity — `PROD_V4`

## Base #173 + #174 + #177

PR #174 a établi la récupération déterministe avec plafond recovery **36** ; PR #177 a revalidé Battle Partners (`SV9`, denominator 100) sans fuzzy ni traduction supposée.

Baseline prouvée après #174 : run `32893130902` SUCCESS, **31/96 EXACT**, 54 `sold_listing`, recovery 36/36.

## #178 — priorité du budget recovery — `PROD_V4`

Le post-#177 a montré une saturation d'ordre (`TCGDEX_BUDGET_EXHAUSTED`). #178 a gardé le plafond total à **36** et réservé la preuve finale exacte :

```text
recovery total max               36
broad/nonpriority max            28
exact card-search/detail reserve  8
merge main                       545223613ce21e6c4cf886e07201bc3c105a5e69
```

La validation read-only de #178 a fini avec 0 `TCGDEX_BUDGET_EXHAUSTED`, sans identité relâchée et sans transaction. Le 30/96 observé correspondait à 55 listings déjà SOLD contre 54 dans la baseline ; les classes de rejets actifs restaient stables.

## Cas volontairement bloqués

Les classes sans preuve déterministe suffisante restent bloquées : Lugia GR団参上 old-back promo, Misty's Horsea old-back No.116, Pokémon Pal City 2007, Rayquaza VMAX Dragon Pokémon Get Challenge promo, Scizor Championship Series 2025 promo.

Ne pas créer d'alias carte-par-carte ou de fallback name-only pour forcer ces cas.

---

# Robot KB — `ROBOT_KB`

Contrat : append-only, provenance + payload brut, ventes finales SOLD prouvées prioritaires, fixed baseline + changements utiles, auction SOLD final prioritaire, snapshot ≤5 min fallback seulement, disparition/ASK/live auction != vente.

Le cutover Neon → PostgreSQL local Mac est terminé :

```text
PR cutover                       #166
source/local rows                1,087,015
nombre de tables                 35
marker                           MIGRATION_VERIFIED
PostgreSQL health                OK
fixed/auction                    LaunchAgent :32
SOLD fresh/backfill              LaunchAgent :17/:47
backup                           03:10 / 7 dumps
V4_USE                           false
```

**Robot KB mirror/collectors séparés** : les collectors historiques GCC locaux ci-dessus restent actifs. Les writers Neon automatiques sont retirés ; Neon reste rollback/recovery manuel. Robot KB reste séparé de la décision commerciale V4/Global.

## #180 — multisource local — `ROBOT_KB / MERGED`

PR #180 est **MERGED** sur `main@9365f5cd9f8949580c4e48f00ba8c4e419c22145`. Le code et l'installateur sont disponibles sur `main`, mais la nouvelle lane n'est **pas encore prouvée installée/chargée sur le Mac**.

Elle ajoute, sans toucher au gate économique V4 :

- Fanatics / COMC / Magi / Cardova publics : baseline puis changements matériels ;
- PokeTrace : US/EU, Pokémon EN/JP, `product_type=single`, prix courants + historique `period=all`, priorité PSA10/PSA9/PSA8-8.5 ;
- PokemonPriceTracker : sets EN/JP, historique 180 jours, eBay gradé agrégé + métriques CardMarket/TCGplayer ;
- clés PokeTrace/PPT uniquement dans le Trousseau macOS ;
- lane `markets` toutes les 2 h à `:05` et lane `paid` à 01:08/07:08/13:08/19:08 après installation ;
- locks séparés des collectors GCC et réserves de quota pour ne pas affamer V4.

Sémantique obligatoire : `SOLD_AGGREGATED` n'est jamais item-level SOLD ; `cardmarket_unsold` reste `FIXED_ASK_AGGREGATED` ; une annonce courante reste ASK. Le stockage conserve provenance/payload/date sans fabriquer une vente.

Validation exacte du head mergé `4194730490efbf879188069de4cc4d17642aad46` :

```text
Robot KB local PostgreSQL validation   32999776457 SUCCESS
V4 Auction Discovery Validation        32999776492 SUCCESS
V4 complete tests / compile / YAML     PASS
live discovery comparison              PASS
whitespace check                       PASS
```

Prochaine preuve nécessaire : exécuter l'installateur #180 sur le Mac, vérifier les LaunchAgents, les premiers catch-ups et les nouvelles observations PostgreSQL sans fuite de secret.

---

# V5 — `V5_ONLY`

```text
PR      #8 OPEN / DRAFT / NON MERGED
branch  agent/v5-poketrace-cardmarket-market-data
head    bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

TCGdex reste le resolver normal. PokeTrace reste marché/prix après identité. PR #92/#96 restent child/shadow/deferred.

**PR #8 ne doit jamais être mergée dans `main` sans autorisation explicite.**

---

# PPT / corrélation

PPT = `SOLD_AGGREGATED`, jamais item-level SOLD. PPT/PokeTrace/eBay peuvent être corrélés et ne comptent pas naïvement comme marchés indépendants.

---

# Supersessions importantes

Les branches/PRs **historiques/superseded** restent provenance uniquement ; ne pas les rejouer automatiquement.

- #54 : stale/superseded ;
- #111 : ancien snapshot docs ;
- #126 : superseded par #127→#135 ;
- #108/#109/#110/#113/#114/#115/#138 : absorbées par #139 ;
- #141 : diagnostic superseded par #142/#140 ;
- #159 : superseded fonctionnellement par #177 mergée ; reste ouverte comme provenance, ne pas merger telle quelle ;
- #174/#177/#178/#179/#180 : **MERGED**, ne plus traiter comme PR pending ;
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
- Robot KB local reste séparé de la décision V4 ;
- ambiguïté et variantes sensibles restent fail-closed.
