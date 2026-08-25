# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel vérifié le **25 août 2026** après merge production de la PR #174 et premier schedule Global post-merge.

Ce fichier sert d'index anti-réimplémentation et de registre de supersession. Toujours re-vérifier `main`, les PRs et les workflows live avant une action.

## Autorité courante

```text
V4 production branch             : main
main runtime Magi                : #174 / merge 3d1589e0086c264e9f910a15fb6b037e20938970
main docs closeout               : 6760376a54c386f9a53d93091c56c999ac952de2
Global marketplace-first         : #147 + #148
Global scale                     : #156 / 50 listings par run
Global cadence                   : 20 min (`1,21,41`)
Global schedule run registry     : issue #150 + #151 / PROUVÉ LIVE
Global activation                : #145 + #146
Cardova public read-only         : #168
Global timeout recovery          : #169
Magi native identity             : #173 + #174 / PROD_V4
Robot KB local cutover           : #166 / PostgreSQL Mac ACTIF
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

## Architecture

#139 a absorbé/revalidé le stack historique #108→#115. #140/#142 ont ajouté la confirmation économique exacte. #145/#146 ont ajouté puis activé la notification. #147/#148 ont basculé la découverte en marketplace-first. #151 a ajouté le registre #150.

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

PR #156 fournit le scale 50. PR #169 protège la cadence 20 min contre l'empilement de runs longs.

---

# Magi native identity — #173 + #174 — `PROD_V4`

## Capability

PR #174 est mergée en production sur :

```text
feature head                     593c417ec526aba39f7d388bb3a61d868650c15a
merge main                       3d1589e0086c264e9f910a15fb6b037e20938970
```

Elle ajoute/réutilise uniquement des classes de récupération déterministes :

- full collector number globalement unique ;
- retry détail Magi borné ;
- budget recovery TCGdex séparé et télémétré ;
- exact set coordinate avec cache ;
- exact Japanese name + reviewed rarity + unicité + card-detail revalidation ;
- preuves source-pinnées pour classes standard/sensibles ;
- priorité du budget pour préserver les preuves finales utiles.

Aucun fuzzy, traduction supposée ou name-only acceptance.

## Validation offline / read-only avant merge

Dernier head PR #174 :

```text
Global tests                     407/407 PASS
V4 multimarket                   51/51 PASS
live read-only                   SUCCESS
Magi                             31/96 EXACT
TCGdex recovery ceiling          36
identity gate relaxed            false
transactions                     false
```

## Premier schedule production post-merge

Run **`32893130902`** sur `main@3d1589e...` : **SUCCESS**.

```text
mode                             GLOBAL_MARKETPLACE_NOTIFICATION_ACTIVE
activation                       true
Magi candidates                  96
Magi EXACT                       31
sold_listing filtered            54
japanese_set_name_unproven       5
target_catalog_unproven          4
target_japanese_card_name        2
TCGdex recovery requests         36
notification sent                0
automatic purchase/bid/checkout  false/false/false
automatic payment                false
identity gate relaxed            false
```

Recovery breakdown observé : `card_detail:4`, `card_search:4`, `set_coordinate:19`, `set_detail:1`, `sets_catalog:1`, `sets_filtered:7`.

## Cas volontairement bloqués

Les cinq `japanese_set_name_unproven` restent bloqués : Lugia GR団参上 old-back promo, Misty's Horsea old-back No.116, Pokémon Pal City 2007, Rayquaza VMAX Dragon Pokémon Get Challenge promo, Scizor Championship Series 2025 promo.

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

Writers Neon automatiques retirés ; Neon conservé comme rollback/recovery manuel. Robot KB reste séparé de la décision commerciale V4/Global.

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

- #54 : stale/superseded ;
- #111 : ancien snapshot docs ;
- #126 : superseded par #127→#135 ;
- #108/#109/#110/#113/#114/#115/#138 : absorbées par #139 ;
- #141 : diagnostic superseded par #142/#140 ;
- #174 : **MERGED / PROD_V4**, ne plus traiter comme PR pending ;
- ancien moteur seed-rotation Global : benchmark/historique après #147/#148 ;
- one-shots/temp : provenance uniquement, suppression seulement avec autorisation destructive explicite.

PR #159 reste ouverte et séparée : correction Battle Partners TCGdex. Elle doit être revalidée contre le `main` courant avant toute décision ; ne pas la confondre avec #174.

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
