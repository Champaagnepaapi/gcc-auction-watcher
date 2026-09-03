# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel re-vérifié le **3 septembre 2026** après #237 et #238/#239. Le code/Git/GitHub réel reste prioritaire sur ce document.

Statuts : `PROD_V4`, `MAIN_SUPPORT`, `ROBOT_KB`, `P3_ONLY`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`, `STALE_OPEN`.

## Autorité courante

```text
V4 production branch             : main
V4 runtime production            : 0cab2f3868e80c7c0ed9e6829e44123a2ecd3005 / #238/#239
V4 run registry                  : issue #235 ACTIVE / issue #1 archive / #237
V4 eBay bulk result text         : #238/#239 / PROD_V4 / validated head 90741ac0eaca42f90a6bc7fca816d347aaccafeb
Auction recovery capacity        : #229/#231 / PROD_V4 / adaptive sizing / hard cap 250
Auction order hardening          : #211/#212 / PROD_V4
Future-start auction guard       : #220 / PROD_V4 / 6a33ac33faa324f0fc1c6124fbb49bd736382b75
TCGdex transport resilience      : #216/#217 / PROD_V4 / 03824158ac899cf142199c42d4525386a573bc15
TCGdex outage fallback           : #222/#224 / PROD_V4 / 0be4dca95513e36f4e407ef7bac361fe488c1d36
External pending throughput      : #214 / PROD_V4 / P4 16 + eBay 16 / auction max 4
Magi native identity             : #174/#177/#178 / PROD_V4
Global schedule watchdog         : #179 / PROD_V4
Robot KB local cutover           : #166 / PostgreSQL Mac ACTIF
Robot KB multisource             : #180 / ROBOT_KB
P3 rarity-symbol print_run       : #207 / P3_ONLY
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

---

# V4 production

## #238/#239 — eBay bulk visible-text extraction — `PROD_V4`

But : réduire l'overhead Playwright dans le worker eBay déjà isolé, sans changer la preuve économique.

```text
locator                          li.s-item
lecture principale               all_inner_texts() une fois
fallback                         nth(i).inner_text() si bulk échoue/partiel/non-list
worker hard isolation            inchangée
30s hard timeout / run breaker   inchangés
queries / matching / SOLD        inchangés
identity / grade / language      inchangés
pricing / budgets / ntfy         inchangés
```

Validation exacte : head `90741ac0eaca42f90a6bc7fca816d347aaccafeb`, run `33650958804` SUCCESS, `875 PASS / 2 skipped`, compile/YAML/diff PASS, live auction compare read-only `80=80`, `legacy_only=0`, unresolved=0. Merge production `0cab2f3868e80c7c0ed9e6829e44123a2ecd3005` via miroir #239 après bug GitHub Ready `fullDatabaseId` sur #238.

**Limite de preuve :** benchmark #234 inconclusif (0 `li.s-item` visible au runner). La première mesure Main Scanner naturelle sur `0cab2f...` est encore attendue ; ne pas revendiquer de gain live avant elle.

Baseline pré-fix utile : run `33741053547`, eBay `attempted=16 / insufficient=7 / unavailable=9 / errors=9`, plusieurs hard timeouts de 30 s puis breaker, backlog externe `1976`.

## #237 — rollover du registre Main Scanner — `MAIN_SUPPORT`

Issue #1 a atteint la limite GitHub de commentaires et reste archive. Le workflow actif écrit désormais les métadonnées minimales dans l'issue #235.

Preuve naturelle `33741053547` : workflow SUCCESS, `scan_exit_code=0`, étape registre #235 SUCCESS, auctions `24/24`, scope COMPLETE, fallback false. Aucun comportement scanner économique n'a changé.

## #229/#231 — auction order-drift recovery capacity — `PROD_V4`

Après dérive d'ordre prouvée uniquement :

```text
budget = ceil(api_total / page_size) + 2
minimum = ancien bound
hard ceiling = 250 pages
```

`api_total` sert au sizing seulement ; `COMPLETE` exige l'épuisement API réel. Fast path, cap économique auctions `360`, identité, valorisation, providers, notifications et transactions inchangés. Merge capacité `b6a7c834264c062ea81b64c714e6916aa8bfe9f2`.

## Discovery GCC #211/#212 — `PROD_V4`

- fixed : `/on-sale-items`, discovery avant caps économiques ;
- auctions : `AUCTION + ON_SALE + ENDING_SOON` avec `endTime` individuel ;
- horizon principal ≤60 min + safety-net legacy ;
- dérive d'ordre => récupération exhaustive bornée puis horizon local ;
- pagination/endTime invalides restent fail-closed ;
- Main Scanner cadencé extérieurement ; pas de cron GitHub parallèle.

Capacités structurantes : #9, #50, #52, #104, #211/#212, #220, #229/#231.

## #220 — future-start auction guard — `PROD_V4`

Une enchère prouvée future-start est exclue avant que starting price/countdown-to-start puissent devenir bid courant/temps avant fin. Preuve absente ou malformée => aucune supposition. Premier cas positif naturel toujours à observer.

## #216/#217 — TCGdex transport/run resilience — `PROD_V4`

2 tentatives max ; retry Timeout/ConnectionError/502/503/504 ; breaker après 2 appels logiques épuisés ; erreurs restent `ERROR`/fail-closed ; vraie réponse reset ; nouveau process circuit fermé.

## #222/#224 — TCGdex source-pinned outage fallback — `PROD_V4`

Fallback seulement après `ERROR` transport retryable avec japonais + alias set reviewé + numéro/denominator exact + source TCGdex immuable `af33c9ac...` + exact set/localId + finish admis. `NO_MATCH`, `AMBIGUOUS`, non-Japonais ou preuve incomplète restent bloqués.

## #214 — débit `EXTERNAL_PENDING` — `PROD_V4`

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

Provider failures restent fail-visible et ne deviennent jamais clean no-match.

## TCGdex / PokeTrace #119→#135 — `PROD_V4`

Exact-coordinate, set/localId, unicité catalogue, bridges exacts, finish/set source-pinnés et fallback générique catalogue immuable lorsque le REST TCGdex est stale ; PokeTrace market-only après identité TCGdex. Aucun alias treadmill. PR #126 = `SUPERSEDED` par #127→#135.

---

# Global Multi-Vault

## #139 — réintégration du stack historique

#139 a réintégré/revalidé le stack #108/#109/#110/#113/#114/#115/#138. Surface : GCC/Cardova/magi/Fanatics/COMC → identité commerciale exacte → TCGdex exact + microvariante → SOLD exact optionnel → PPT/PokeTrace graded aggregate → décision.

- disappearance != SOLD ;
- ACTIVE_AUCTION non actionnable ;
- PPT/PokeTrace/eBay corrélés `EBAY_GRADED_AGGREGATE` ;
- PPT = `SOLD_AGGREGATED`, jamais item-level SOLD ;
- aucune transaction.

Scale courant : 50 listings/run, PPT 35 HTTP / 180 credits / floor 15000, PokeTrace 60, cadence 20 min, inner timeout 17 min, job timeout 25 min. #179 apporte le watchdog borné sans seconde lane économique.

---

# Magi — `PROD_V4`

#174 + #177 = identité native déterministe ; #178 = recovery total 36, broad/nonpriority max 28, reserve exact search/detail 8. Pas de name-only/alias carte-par-carte.

---

# Robot KB — `ROBOT_KB`

PostgreSQL local Mac actif, `V4_USE=false`, Neon writers automatiques OFF. Append-only daté ; SOLD final prouvé prioritaire ; ASK/live/disparition/WAITING_FOR_PAYMENT != vente.

**Robot KB mirror/collectors séparés** de la décision V4/Global. #180 collecte Fanatics/COMC/Magi/Cardova + PokeTrace/PPT en conservant les sémantiques ; `SOLD_AGGREGATED` != item-level SOLD et `FIXED_ASK_AGGREGATED` reste ASK.

#207 est `P3_ONLY` et n'a exécuté aucune migration durable utilisateur. #210 reste OPEN/DRAFT ; aucun durable write Cardova sans autorisation explicite.

---

# V5 / non-production

PR #8 = **`V5_ONLY`**, OPEN/DRAFT/NON-MERGED. Ne jamais merger PR #8 dans `main` sans autorisation explicite.

---

# Supersessions / provenance historiques/superseded

- #54 : stale/superseded ;
- #111 : ancien snapshot docs ;
- #126 : `SUPERSEDED` par #127→#135 ;
- #108/#109/#110/#113/#114/#115/#138 : absorbées par #139 ;
- #141 : superseded par #142/#140 ;
- #159 : superseded fonctionnellement par #177 ;
- #211/#212 : une capacité runtime ;
- #216/#217 : une capacité runtime, #217 mirror ;
- #222/#224 : une capacité runtime, #224 mirror ;
- #229/#231 : une capacité runtime ;
- #238/#239 : une capacité eBay runtime, #239 mirror ;
- #234 : diagnostic benchmark read-only inconclusif, ne pas traiter comme preuve de performance.

---

# Invariants de reprise

- V4/main canonique ;
- PR #8 protégée ;
- aucun achat/bid/checkout/paiement ;
- Robot KB local séparé de V4 ;
- aucune écriture durable Cardova sans autorisation explicite ;
- identité ambiguë/microvariante incertaine = fail-closed ;
- avant nouveau code, réutiliser d'abord les capacités recensées ici et dans le README.
