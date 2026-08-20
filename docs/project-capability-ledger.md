# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel vérifié le **20 août 2026**.

Ce fichier sert d'index anti-réimplémentation. Avant tout changement non trivial, vérifier si la capacité existe déjà sur V4, Global, V5, Robot KB ou une branche historique/shadow.

## Autorité courante

```text
V4 production branch            : main
Last functional/runtime merge   : c012284c423e9526fd2712001fdbce3a5cfafda3
V5 expérimentale                : PR #8 / agent/v5-poketrace-cardmarket-market-data
V5 head validé                  : bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
TCGdex source pin               : af33c9ac882e2acfadffaf19e8083aa976d12983
Global notification candidate   : PR #145 / default-off / non mergée à ce snapshot
```

Des commits docs-only suivent `c012284c...` sur `main`. Toujours re-vérifier le HEAD live ; le SHA ci-dessus est le **baseline runtime**, pas une promesse que le HEAD Git est identique.

Statuts : `PROD_V4`, `MAIN_SUPPORT`, `GLOBAL_READ_ONLY`, `GLOBAL_NOTIFY_DEFAULT_OFF`, `ROBOT_KB`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`.

---

# V4 production

## Discovery GCC — `PROD_V4`

- auctions item-level via `/on-sale-items`, `ENDING_SOON`, `ON_SALE`, `endTime` individuel ;
- horizon ≤60 min + safety-net legacy ;
- fixed discovery complète avant caps économiques.

PRs structurantes : #9, #50, #52, #104. Ne pas reconstruire un second collector parallèle.

## Fast Lane — `PROD_V4`

PR #45 + #55 : recheck ciblé, aucun nouveau discovery/provider, `max_recommended` immuable, aucune transaction.

## Arbitrage multi-marché — `PROD_V4`

```text
GCC listing
 -> identité TCGdex exacte
 -> GCC SOLD
 -> PokeTrace graded exact
 -> PSA APR / eBay SOLD exact
 -> arbitrage evidence-strength
```

Chemins : `GCC_ONLY`, `GCC_EXTERNAL_CONFIRMED`, `EXTERNAL_RESCUE`, `EXTERNAL_PENDING`, `MARKET_CONFLICT_BLOCKED`. RAW n'est jamais fair value de slab.

## TCGdex / PokeTrace #119→#135 — `PROD_V4`

- exact-coordinate, aliases revus, set/localId, unicité catalogue, `2 coordonnées sur 3` ;
- PokeTrace structuré après TCGdex ;
- padding collector préservé ;
- bridges provider exacts ;
- finish/set source-pinnés ;
- fallback générique catalogue immuable quand REST TCGdex est stale.

Preuve prod #135 : run `32160680888`, SUCCESS. Houndoom `100/098`, Meowth `109/098`, Moltres ex `112/098` -> `SV10`.

**Pas de treadmill d'alias carte-par-carte.** Toute correction future doit être une classe répétée, déterministe et prouvée.

PR #126 = `SUPERSEDED`, ne pas merger.

## Autres capacités V4 déjà présentes

- queue anti-starvation / smart external priority / refresh adaptatif ;
- exact active eBay ASK context ;
- Structural Edge Hunter V2 ;
- Japan Edge Hunter séparé ;
- cert/OCR historiques ; Mislisted Slab hard-disabled ;
- Robot KB mirror/collectors séparés.

---

# Global Multi-Vault

## #139 — réintégration — `GLOBAL_READ_ONLY`

A absorbé/revalidé les capacités historiques #108→#115 : common valuation, strict identity, GCC/Cardova/magi/Fanatics/COMC, diagnostics, retrieval hardening, Magi SOLD guard, COMC fallback, runner manuel/read-only et CI Global.

Les PR #108/#109/#110/#113/#114/#115 et #138 sont désormais historiques/superseded pour l'intégration.

## #140 — confirmation économique — `GLOBAL_READ_ONLY`

Dernier merge fonctionnel/runtime : `c012284c423e9526fd2712001fdbce3a5cfafda3`.

- `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` seulement comme offres actionnables ;
- `ACTIVE_AUCTION` non actionnable ;
- `all_in_eur` obligatoire ;
- confirmation gradée externe obligatoire avant `would_notify` ;
- minimum 3 ventes agrégées ;
- GCC/externe >1.25 -> `MARKET_CONFLICT_BLOCKED` ;
- fair confirmé = `min(GCC, externe)` ;
- PPT/PokeTrace/eBay = une seule famille `EBAY_GRADED_AGGREGATE` ;
- aucune notification réelle ni transaction.

## #142 — bridge exact provider — `MAIN_SUPPORT`

Absorbée dans #140 avant merge vers main.

Après preuve macro exacte uniquement :

- full collector number avec dénominateur exact ;
- set exact ou préfixe TCGdex exact ;
- langue exacte ;
- nom canonique + suffixe borné `V/VSTAR/VMAX/ex/GX` ou `Mega <nom> ex` ;
- hardening dimensions V4 conservé ;
- `Unlimited` non matériel uniquement si TCGdex exact prouve `firstEdition=false` ;
- fallback PPT uniquement si `externalCatalogId` absent + full number/set-code/name/unique ;
- `externalCatalogId` conflictuel bloque ;
- aucun fuzzy.

### Validation #140/#142

```text
Head #140        b10adebc1f6866ae4ec37e9ea01eeddd2a240c60
Offline CI       32351952230 SUCCESS
Dispatcher CI    32351952209 SUCCESS
Global tests     146/146 PASS
V4 regressions    51/51 PASS
compile/YAML/diff PASS
```

Live `32344120993` : TCGdex 5/5, PPT 4/5, PokeTrace 4/5, `would_notify=0`, 1 conflit bloqué. Mewtwo 183/165 : GCC ~€155, externe ~€103.40, Fanatics ASK ~€99.10 -> `MARKET_CONFLICT_BLOCKED`.

Pikachu M-P reste `CLEAN_NO_MATCH`. Ne pas ajouter un alias ponctuel sans classe répétée prouvée.

## #145 — notifications Global confirmées — `GLOBAL_NOTIFY_DEFAULT_OFF`

Phase séparée, construite au-dessus des décisions #140 et du bridge #142 ; aucun nouveau moteur de matching/fair value parallèle.

Capacités :

- notification uniquement après `would_notify=true` + `MULTIMARKET_CONFIRMED` ;
- offre exacte actionnable `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` + `all_in_eur` prouvé ;
- externe gradé >=3 ventes ;
- déduplication persistante 14 jours par identité + marché + URL ;
- re-alert uniquement après expiration TTL ou baisse de prix >=5 % ;
- rotation persistante des seeds ;
- état corrompu = fail-closed si livraison activée ;
- `workflow_dispatch` = toujours dry-run ;
- cron candidat horaire minute 41, mais job scheduled skip tant que `vars.GLOBAL_NOTIFY_ENABLED != 'true'` ;
- aucune transaction possible.

### Résilience TCGdex Global-only

Le premier dry-run notification `32357750921` a validé les garde-fous mais TCGdex a `ReadTimeout` sur 5/5, donc 0/5 exact et PokeTrace 0/5. Le correctif #145 ajoute une résilience **transport uniquement**, isolée à la lane Global :

- max 2 tentatives au total ;
- timeout 10 s ;
- backoff 0.25 s ;
- retry seulement Timeout/ConnectionError/HTTP 502/503/504 ;
- 404/non-match jamais transformé ;
- échec après retry reste `ERROR` et fail-closed ;
- aucune règle d'identité n'est relâchée ;
- le scanner V4 canonique n'installe pas ce wrapper.

Validation offline du correctif :

```text
head fonctionnel pré-one-shot  3c459ac561013eaf49b5475d7d89222a8b9efdda
Offline CI                    32359793387 SUCCESS
Dispatcher CI                 32359793463 SUCCESS
Global tests                  164/164 PASS
V4 regressions                 51/51 PASS
compile/YAML/diff             PASS
```

Live dry-run résilient :

```text
run / job              32359861668 / 96396943369
mode                   READ_ONLY_NOTIFICATION_VALIDATION
TCGdex exact           5/5
PPT matched            4/5
PokeTrace matched      4/5
confirmed_would_notify 0
market conflicts       1 blocked
sent                   0
notifications          false
transactions           false
identity_gate_relaxed  false
artifact               9403172623
artifact digest        sha256:68054acd9468b7f3e1ac5fdcb9720a9bcba38d19e7440dc96bbb59e61b1ad2b0
```

Le one-shot ayant produit ce live est supprimé avant le head final de la PR. L'activation réelle `GLOBAL_NOTIFY_ENABLED=true` reste une **autorisation séparée** et ne doit pas être inférée d'un merge.

PR #141 = `SUPERSEDED_DIAGNOSTIC`, ne pas merger comme fonctionnalité.

---

# Robot KB / Neon — `ROBOT_KB`

- append-only ; provenance + raw payload ;
- SOLD uniquement si vente finale explicite + date + prix ;
- fixed recent + rotation + targeted ;
- SOLD frais + backfill avec watermarks ;
- auction ≤5m reste observation, pas vente ;
- aucun hard gate KB-first sans profondeur suffisante.

---

# V5 — `V5_ONLY`

PR #8 reste **OPEN / DRAFT / NON MERGED**.

```text
branch agent/v5-poketrace-cardmarket-market-data
head   bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

TCGdex reste resolver normal. Emergency uniquement après panne technique réelle, via cache prouvé/TCG API/PokeTrace emergency, fail-closed. PR #92/#96 restent shadow/deferred.

---

# PPT

Agrégats eBay gradés = `SOLD_AGGREGATED`, jamais item-level SOLD. PPT/PokeTrace/eBay peuvent être corrélés et ne comptent pas naïvement comme marchés indépendants.

PR #106/#107 restent des shadows historiques séparés ; Global #140 utilise son adapter strict dédié.

---

# Supersessions importantes

- #54 : stale/superseded ;
- #111 : ancien snapshot docs ;
- #126 : ancienne lignée PokeTrace ;
- #108/#109/#110/#113/#114/#115/#138 : stack Global historique absorbée par #139 ;
- #141 : diagnostic absorbé par #142 ;
- #142 : absorbée dans #140 puis main ;
- one-shots/temp : provenance uniquement, à supprimer après validation.

## Invariants

- V4/main canonique ;
- PR #8 jamais mergée sans autorisation explicite ;
- PokeTrace marché/prix après identité ;
- ASK/live auction != SOLD ;
- RAW != valeur slab ;
- aucune identité/langue/grader/grade/microvariante incompatible mélangée ;
- aucun achat, bid, checkout ou paiement automatique ;
- aucun secret dans repo/logs ;
- merge #145 != activation réelle : le feature flag reste default-off jusqu'à autorisation explicite.
