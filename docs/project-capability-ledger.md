# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel re-vérifié le **1 septembre 2026** après #229/#231. Le code/Git/GitHub réel reste prioritaire sur ce document.

Ce fichier sert d'index anti-réimplémentation et de registre de supersession. Statuts : `PROD_V4`, `MAIN_SUPPORT`, `ROBOT_KB`, `P3_ONLY`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`, `STALE_OPEN`.

## Autorité courante

```text
V4 production branch             : main
V4 runtime production            : b6a7c834264c062ea81b64c714e6916aa8bfe9f2 / #229/#231
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

## #229/#231 — auction order-drift recovery capacity — `PROD_V4`

Cause : l'univers GCC `AUCTION + ON_SALE` a dépassé l'ancien safety bound de 100 pages. Les runs naturels pré-fix `33547948642` et `33549911988` ont atteint `auction API safety limit 100 pages reached` puis fallback legacy ; `33548929050` confirmait que le fast path voisin restait sain.

Le nouveau sizing s'applique **uniquement après dérive d'ordre prouvée** :

```text
budget = ceil(api_total / page_size) + 2
minimum = ancien bound
hard ceiling = 250 pages
```

`api_total` est un **indice de capacité seulement** et n'est jamais une preuve de complétude. `COMPLETE` exige toujours l'épuisement API réel (`nextPage` absent). Les erreurs request/malformed/endTime/repeated-page/no-progress/invalid-nextPage/hard-ceiling restent fail-closed vers le fallback existant.

Pour ~15 049 rows à 100/page : capacité 153 pages au lieu de 100. Fast path, cap économique auctions `360`, identité, valorisation, providers, notifications et transactions restent inchangés.

Validation exacte :

```text
validated head/tree              f81f81d1cf349a298d07867e9750704a9ea0c2bd / 0170d41c548878f4a4a77b7662f0b0a6e0f002c2
#229 clean CI                    33563203801 SUCCESS
#231 merge-mirror CI             33563438585 SUCCESS
complete V4 suite                PASS
compile / YAML / diff            PASS
read-only live compare           PASS
api_primary_complete             true
legacy_only                      0
unresolved effective/legacy      0 / 0
production merge                 b6a7c834264c062ea81b64c714e6916aa8bfe9f2
natural post-merge proof         en attente
```

Le toggle Ready de #229 a rencontré le bug GitHub GraphQL `fullDatabaseId`; #231 a servi de miroir non-draft sur le **même head/tree**. GitHub marque désormais #229 et #231 comme mergées vers le même merge production.

## Discovery GCC #211/#212 — `PROD_V4`

- fixed : `/on-sale-items`, discovery avant caps économiques ;
- auctions : `AUCTION + ON_SALE + ENDING_SOON` avec `endTime` individuel ;
- horizon principal ≤60 min + safety-net legacy ;
- dérive d'ordre => récupération exhaustive bornée puis horizon local ;
- pagination/endTime invalides restent fail-closed ;
- Main Scanner cadencé extérieurement ; pas de cron GitHub parallèle.

**Capacités structurantes : #9, #50, #52, #104**, #211/#212, #220 et désormais #229/#231.

## #220 — future-start auction guard — `PROD_V4`

Une enchère prouvée future-start est exclue avant que starting price/countdown-to-start puissent devenir bid courant/temps avant fin. Preuve absente ou malformée => aucune supposition. Aucun changement fair value, threshold, identity, provider budget ou notification.

Première preuve naturelle post-#220 `33490823534` : SUCCESS, discovery `COMPLETE`, 24 rows / 24 timers, fallback false, mais aucun cas positif future-start. Le premier cas positif naturel reste à observer.

## #216/#217 — TCGdex transport/run resilience — `PROD_V4`

2 tentatives max ; retry Timeout/ConnectionError/502/503/504 ; breaker après 2 appels logiques épuisés ; erreurs restent `ERROR`/fail-closed ; vraie réponse reset ; nouveau process circuit fermé. Merge `03824158...`.

## #222/#224 — TCGdex source-pinned outage fallback — `PROD_V4`

Fallback seulement après `ERROR` transport retryable avec japonais + alias set reviewé + numéro/denominator exact + source TCGdex immuable `af33c9ac...` + exact set/localId + finish admis. `NO_MATCH`, `AMBIGUOUS`, non-Japonais ou preuve incomplète restent bloqués.

Run naturel `33500303400` : SUCCESS, provider sain, `17 exact / 1 no-match / 0 ambiguous / 0 errors`, backlog `1966`, auctions 24/24 `COMPLETE`. Preuve de non-régression ; pas activation positive du chemin outage.

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

Les provider failures restent fail-visible et ne deviennent jamais clean no-match.

## TCGdex / PokeTrace #119→#135 — `PROD_V4`

Exact-coordinate, set/localId, unicité catalogue, bridges exacts, finish/set source-pinnés et **fallback générique catalogue immuable** lorsque le REST TCGdex est stale ; PokeTrace market-only après identité TCGdex. Aucun alias treadmill.

PR #126 = `SUPERSEDED` par #127→#135.

---

# Global Multi-Vault

## #139 — réintégration du stack historique

**#139 — réintégration** a absorbé/revalidé le stack Global historique **#108/#109/#110/#113/#114/#115/#138**. Ces PRs restent historiques/superseded comme provenance, pas comme lane actuelle.

Surface : **GCC/Cardova/magi/Fanatics/COMC** → identité commerciale exacte → TCGdex exact + microvariante → SOLD exact optionnel → PPT/PokeTrace graded aggregate → décision.

- disappearance != SOLD ;
- ACTIVE_AUCTION non actionnable ;
- PPT/PokeTrace/eBay corrélés `EBAY_GRADED_AGGREGATE` ;
- **PPT = `SOLD_AGGREGATED`**, jamais item-level SOLD ;
- aucune transaction.

Scale courant : 50 listings/run, PPT 35 HTTP / 180 credits / floor 15000, PokeTrace 60, cadence 20 min, inner timeout 17 min, job timeout 25 min. #179 apporte le watchdog borné sans seconde lane économique.

---

# Magi — `PROD_V4`

#174 + #177 = identité native déterministe ; #178 = recovery total 36, broad/nonpriority max 28, reserve exact search/detail 8. Les classes non prouvées restent bloquées ; pas de name-only/alias carte-par-carte.

---

# Robot KB — `ROBOT_KB`

PostgreSQL local Mac actif, `V4_USE=false`, Neon writers automatiques OFF. Append-only daté ; SOLD final prouvé prioritaire ; ASK/live/disparition/WAITING_FOR_PAYMENT != vente.

**Robot KB mirror/collectors séparés** de la décision V4/Global. #180 collecte Fanatics/COMC/Magi/Cardova + PokeTrace/PPT en conservant les sémantiques ; `SOLD_AGGREGATED` != item-level SOLD et `FIXED_ASK_AGGREGATED` reste ASK.

#207 est `P3_ONLY` et n'a exécuté aucune migration durable utilisateur. #210 reste OPEN/DRAFT ; aucun durable write Cardova n'est autorisé sans autorisation explicite.

---

# V5 / non-production

PR #8 = **`V5_ONLY`**, OPEN/DRAFT/NON-MERGED. Les child/shadow restent `SHADOW` ou `DEFERRED`; les fonctionnalités non câblées restent `DISABLED`.

Ne jamais merger PR #8 dans `main` sans autorisation explicite.

---

# Supersessions / provenance

Les branches et PRs **historiques/superseded** restent provenance uniquement.

- #54 : stale/superseded ;
- #111 : ancien snapshot docs ;
- PR #126 = `SUPERSEDED` ;
- #108/#109/#110/#113/#114/#115/#138 : absorbées par #139 ;
- #141 : superseded par #142/#140 ;
- #159 : superseded fonctionnellement par #177 ;
- #211/#212 : une capacité runtime ;
- #216/#217 : une capacité runtime, #217 mirror ;
- #222/#224 : une capacité runtime, #224 mirror ;
- #229/#231 : une capacité runtime, même head/tree de merge ;
- #230 : validation temporaire seulement, ne pas merger.

---

# Invariants de reprise

- V4/main canonique ;
- PR #8 protégée ;
- aucun achat/bid/checkout/paiement ;
- Robot KB local séparé de V4 ;
- aucune écriture durable Cardova sans autorisation explicite ;
- identité ambiguë/microvariante incertaine = fail-closed ;
- avant nouveau code, réutiliser d'abord les capacités déjà recensées ici et dans le README.
