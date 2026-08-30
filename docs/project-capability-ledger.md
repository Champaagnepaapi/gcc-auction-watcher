# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot re-vérifié le **30 août 2026**. Le code/Git/GitHub live reste prioritaire. Ce ledger sert d'index anti-réimplémentation et de registre des capacités/supersessions.

## Autorité courante

```text
V4 production                    main @ 1a4b18e98937769bb6924a79aca7dcd36729d25a
V4 auction priority/cap          #188 MERGED
PSA/eBay breakers                #189 MERGED
eBay completed shadow            #191 MERGED
Global marketplace-first         #139/#145/#146/#147/#148
Global scale/cadence             #156/#169/#179
Robot KB local cutover           #166 / PostgreSQL Mac ACTIF
Robot KB multisource             #180 MERGED / LaunchAgents installés
Cardova paid SOLD                #199 OPEN/DRAFT / local ACTIF / NON MERGED
Cardova activation head          31378bd04e44c60fa1259605b67d2aabc4a89129
Cardova durable SOLD             90
Neon automatic writers           OFF / rollback manuel
V5                               PR #8 OPEN / DRAFT / NON MERGED
```

Statuts : `PROD_V4`, `GLOBAL_NOTIFY_ACTIVE`, `ROBOT_KB`, `SHADOW`, `V5_ONLY`, `DEFERRED`, `SUPERSEDED`, `STALE_OPEN`.

---

# V4 — `PROD_V4`

## GCC discovery / auctions

- fixed `/on-sale-items` ; auctions `AUCTION/ENDING_SOON/ON_SALE` ;
- horizon principal ≤60 min + safety-net legacy ;
- #188 : priorité ≤5, puis ≤12, puis reste ≤60 ; cap 360 ;
- Main Scanner et Fast Lane gardent leurs cadences externes ; pas de cron GitHub parallèle.

## Arbitrage multi-marché

- identité exacte avant valorisation ;
- GCC SOLD exact si disponible ;
- PokeTrace/PPT graded aggregate ;
- PSA APR/eBay exact seulement quand prouvés ;
- RAW Cardmarket/TCGplayer secondaire/manual-review ;
- #189 : breakers PSA 403/429 et eBay hard-timeout ;
- #191 : eBay completed-item shadow = candidate, jamais item-level SOLD prouvé automatiquement.

## TCGdex

Lignée #119→#135 : coordinate, padding, set/localId, unicité catalogue, bridges provider exacts, source-pin. #154 ajoute `variants_detailed` après identité exacte. Aucun fuzzy comme preuve exacte.

PR #126 = superseded par #127→#135.

---

# Global Multi-Vault — `GLOBAL_NOTIFY_ACTIVE`

Surface : GCC / Fanatics / COMC / magi / Cardova.

- #139 réintègre le stack historique #108→#115 ;
- #145/#146 notification + activation ;
- #147/#148 marketplace-first ;
- #151 registre issue #150 ;
- #156 batch 50 ;
- #169 cadence/timeout ;
- #179 watchdog schedule.

Gate : identité exacte + listing actionnable + externe gradé suffisamment fort + conflit matériel bloquant. ASK/current auction/disappearance != SOLD. Aucune transaction.

Ancien stack #108/#109/#110/#113/#114/#115/#138 = superseded/absorbé par #139.

---

# Magi native identity — `PROD_V4`

#174 + #177 : récupération déterministe native JP. #178 protège le budget sans augmenter le plafond : total 36, broad/nonpriority 28, réserve stricte 8. Cas non prouvés restent bloqués ; pas d'alias carte-par-carte.

---

# Robot KB — `ROBOT_KB`

Contrat : append-only, provenance + payload brut, observations datées, final SOLD prioritaire, fixed baseline/changements, snapshot auction ≤5 min uniquement fallback clairement identifié.

Cutover #166 : PostgreSQL local Mac actif ; migration Neon vérifiée 1,087,015 lignes / 35 tables / `MIGRATION_VERIFIED`. Neon automatic writers retirés ; rollback manuel seulement.

Collectors locaux :

```text
fixed/auction                     :32
GCC SOLD fresh/backfill           :17 / :47
backup                            03:10
multisource public #180           toutes les 2 h à :05
PokeTrace/PPT #180                01:08 / 07:08 / 13:08 / 19:08
Cardova paid SOLD #199            02:23 / 08:23 / 14:23 / 20:23
```

#180 : Fanatics/COMC/Magi/Cardova public baseline+changes ; PokeTrace/PPT historiques agrégés. `SOLD_AGGREGATED` reste agrégé ; `cardmarket_unsold` reste ASK.

## Cardova paid/completed SOLD — #199 `ROBOT_KB / DRAFT`

Provider gate : status paiement 5 + finished + non cancelled/relisted + JPY + final winning bid positif.

P3 semantics :

- `SALE_TRANSACTION` ;
- `sale_occurred_at = auction_end_at_utc` ;
- `HAMMER_PRICE` JPY ;
- payment completion timestamp/all-in non fabriqués ;
- unresolved identity conservée ;
- exact identity/V4 eligibility = false tant que non prouvée.

Identity research : TCGdex gap pratique sur promos JP `XY-P/BW-P/L-P`. Fallback exact Pokémon Japon : 7/7 macro exactes, 0/7 microvariantes exactes, 1/7 holo corroboré. PSA HTML/API = 403 ; aucun bypass.

Live storage :

```text
initial one-shot                   20
recurring pages 1-4               15
recurring pages 5-8               55
TOTAL                              90 SOLD
canonical links                     0
V4_USE                              false
```

Recurring architecture : front pages + rotation historique, idempotence P3, state only after commit, DB loopback only, readiness retry 5000→6500→8000 ms, lock séparé.

Activation : head `31378bd04e44c60fa1259605b67d2aabc4a89129`, runtime pin `a2f1878186a8850d5a4c4763518a10ecfd16f2fc`, LaunchAgent `com.robotpokemon.kb.cardova-sold`, cadence 4×/jour. Runner post-install live : +55 ventes, cursor page 9, error null. Premier fire réellement planifié à observer encore.

#199 reste OPEN/DRAFT/NON MERGED. Ne pas merger sans décision explicite.

---

# V5 — `V5_ONLY`

PR #8 `agent/v5-poketrace-cardmarket-market-data`, head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f` : expérimentale, draft, non mergée. TCGdex reste resolver principal ; PokeTrace marché/prix. **Ne jamais merger #8 sans autorisation explicite.**

#92/#96 = V5 child/shadow/deferred.

---

# Supersessions / PRs à ne pas rejouer automatiquement

- #54 stale/superseded ;
- #108/#109/#110/#113/#114/#115/#138 absorbées par #139 ;
- #111 ancien snapshot docs ;
- #126 superseded par #127→#135 ;
- #141 diagnostic superseded par #142/#140 ;
- #159 superseded fonctionnellement par #177 ;
- #174/#177/#178/#179/#180/#188/#189/#191 déjà mergées ;
- #87 décision produit V4 séparée, ne pas mélanger à un autre changement ;
- #199 actif/draft Robot KB, non mergé ;
- #8 protégé V5, non mergé.

Issues particulières : #1 registre V4 vivant ; #150 registre Global vivant ; #28 spec historique livrée ; #58 planning Robot KB historique largement livré, ne pas traiter comme backlog neuf.

---

# Règles de reprise

Avant implémentation non triviale : lire README + gouvernance + ce ledger + inventaires, rechercher une capacité antérieure, suivre les supersessions, isoler V4/V5/Robot KB, utiliser SHA précis, tests ciblés + suite pertinente, compile/YAML/diff-check, live read-only lorsque pertinent, puis documenter la phase.

Aucun achat, bid, offer, checkout ou paiement automatique.
