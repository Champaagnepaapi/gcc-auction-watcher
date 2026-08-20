# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel vérifié le **20 août 2026**.

Ce fichier sert d'index anti-réimplémentation. Avant tout changement non trivial, vérifier si la capacité existe déjà sur V4, Global, V5, Robot KB ou une branche historique/shadow.

## Autorité courante

```text
V4 production branch            : main
Global notification runtime     : PR #145 / merge 929d0d24ba959ba1ff30b2d73b1df5adc1d460e6
Global notification activation  : PR #146 / marker versionné + override repo variable
V5 expérimentale                : PR #8 / agent/v5-poketrace-cardmarket-market-data
V5 head validé                  : bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
TCGdex source pin               : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Toujours re-vérifier le HEAD live de `main` avant une action. Les SHA ci-dessus sont des points de reprise fonctionnels.

Statuts : `PROD_V4`, `MAIN_SUPPORT`, `GLOBAL_READ_ONLY`, `GLOBAL_NOTIFY_ACTIVE`, `ROBOT_KB`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`.

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

- `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` seulement comme offres actionnables ;
- `ACTIVE_AUCTION` non actionnable ;
- `all_in_eur` obligatoire ;
- confirmation gradée externe obligatoire avant `would_notify` ;
- minimum 3 ventes agrégées ;
- GCC/externe >1.25 -> `MARKET_CONFLICT_BLOCKED` ;
- fair confirmé = `min(GCC, externe)` ;
- PPT/PokeTrace/eBay = une seule famille `EBAY_GRADED_AGGREGATE` ;
- aucune transaction.

## #142 — bridge exact provider — `MAIN_SUPPORT`

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

Validation #140/#142 : Global 146/146, V4 51/51, live `32344120993` avec TCGdex 5/5, PPT 4/5, PokeTrace 4/5 et 1 conflit Mewtwo correctement bloqué.

Pikachu M-P reste `CLEAN_NO_MATCH`. Ne pas ajouter un alias ponctuel sans classe répétée prouvée.

## #145 — notifications Global confirmées — `MAIN_SUPPORT`

Phase séparée au-dessus des décisions #140 et du bridge #142.

- notification uniquement après `would_notify=true` + `MULTIMARKET_CONFIRMED` ;
- offre exacte actionnable `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` + `all_in_eur` prouvé ;
- externe gradé >=3 ventes ;
- déduplication persistante 14 jours ;
- re-alert uniquement après TTL ou baisse >=5 % ;
- rotation persistante ;
- état corrompu = fail-closed si livraison activée ;
- `workflow_dispatch` = toujours dry-run ;
- cron horaire minute 41 ;
- aucune transaction possible.

### Résilience TCGdex Global-only

- max 2 tentatives ;
- timeout 10 s ;
- backoff 0.25 s ;
- retry seulement Timeout/ConnectionError/HTTP 502/503/504 ;
- 404/non-match jamais transformé ;
- échec final reste `ERROR` ;
- aucune identité relâchée ;
- scanner V4 canonique inchangé.

Validation finale #145 :

```text
head                          1b20f583a31e5488acbb7e4eace488e2675ffbc0
Offline CI                    32360818382 SUCCESS
Dispatcher CI                 32360818383 SUCCESS
Global tests                  164/164 PASS
V4 regressions                 51/51 PASS
compile/YAML/diff             PASS
live run                      32359861668 SUCCESS
TCGdex/PPT/PokeTrace          5/5 · 4/5 · 4/5
merge main                    929d0d24ba959ba1ff30b2d73b1df5adc1d460e6
```

## #146 — activation réelle — `GLOBAL_NOTIFY_ACTIVE`

Activation explicitement autorisée après merge #145.

Le connecteur ne permettant pas d'écrire directement les repository variables Actions, la lane utilise un feature flag versionné et auditable :

- `.github/global-notify-activation = true` active les runs `schedule` ;
- `vars.GLOBAL_NOTIFY_ENABLED=true` reste supporté ;
- `vars.GLOBAL_NOTIFY_ENABLED=false` est un override d'urgence prioritaire ;
- `workflow_dispatch` reste toujours dry-run ;
- `NTFY_TOPIC` absent/vide -> `GLOBAL_NOTIFY_ENABLED_WITHOUT_TOPIC` avant scan ;
- aucune règle identité/prix modifiée ; aucune transaction ajoutée.

Validation PR #146 avant merge :

```text
head                          5311329f9e8f3a7ce164032a426d54b112132194
Offline CI                    32368400673 SUCCESS
Global tests                  166/166 PASS
V4 regressions                 51/51 PASS
compile/YAML/diff             PASS
```

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
- notification Global uniquement après gate économique complet + activation explicite ;
- `vars.GLOBAL_NOTIFY_ENABLED=false` coupe la lane immédiatement.
