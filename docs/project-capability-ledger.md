# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel re-vérifié le **6 septembre 2026**. Le code/Git/GitHub réel reste prioritaire sur ce document.

Statuts : `PROD_V4`, `MAIN_SUPPORT`, `ROBOT_KB`, `P3_ONLY`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`, `STALE_OPEN`, `DRAFT_VALIDATION`.

## Autorité courante

```text
V4 production branch             : main
V4 production HEAD               : dfc548021c561479cc8758e2949d2c4629388d9d
External fair-value authority    : #255 / PROD_V4 / merge 9d3bb1b84d22c1534c24d7c58c5897ecce4b817f
Vault/source-role separation     : #257 / DRAFT_VALIDATION / NON MERGED
Japan Mercari/SNKRDUNK           : #256 / DRAFT_VALIDATION / NON MERGED
PokeTrace aggregate quality      : #247 / PROD_V4
Auction pagination preservation  : #245 / PROD_V4
Auction recovery capacity        : #229/#231 / PROD_V4 / adaptive sizing / hard cap 250
Auction order hardening          : #211/#212 / PROD_V4
Future-start auction guard       : #220 + #243 / PROD_V4
V4 run registry                  : issue #235 ACTIVE / issue #1 archive
eBay worker resilience           : #238/#239 + #242 + #253 / PROD_V4
TCGdex transport resilience      : #216/#217 / PROD_V4
TCGdex outage fallback           : #222/#224 / PROD_V4
External pending throughput      : #214 / PROD_V4
Magi native identity             : #174/#177/#178 / PROD_V4
Global schedule watchdog         : #179 / PROD_V4
Robot KB local cutover           : #166 / PostgreSQL Mac ACTIF
Robot KB multisource             : #180 / ROBOT_KB
P3 rarity-symbol print_run       : #207 / P3_ONLY
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

---

# Phase active — #257 — `DRAFT_VALIDATION`

But : séparer strictement **sources d'opportunités** et **sources de valorisation**.

## Opportunity adapters

```text
GCC / Fanatics / COMC / Magi / Cardova
        -> offre normalisée
        -> CommercialIdentity stricte
        -> prix = coût d'achat potentiel uniquement
```

Contrat :

- `FIXED_ASK` / `AUCTION_SNAPSHOT_LE5` peuvent être évalués comme offres ;
- ils ne deviennent jamais `SOLD` ;
- une marketplace ne peut créer, ancrer, confirmer, plafonner ou conflict-block la fair value ;
- un adapter peut casser/être corrigé indépendamment sans dupliquer tout le robot ;
- eBay actif n'est pas encore implémenté dans #257 ; il devra être un adapter d'opportunités ;
- Mercari/SNKRDUNK sont traités séparément dans PR #256.

## Valuation providers

#257 propose :

```text
preuve forte PPT/PokeTrace SOLD-derived
        -> PSA APR exact si applicable
        -> PriceCharting guide fallback borné
```

Direct eBay SOLD page scraping perd son autorité de fair value dans #257.

PriceCharting :

- guide de prix, jamais faux SOLD item-level ;
- aucune `ComparableSale` synthétique ;
- PSA 10 explicite seulement pour usage automatique ;
- grade 9/8 générique = WEAK/contexte ;
- guide seul => décote minimale 40 % ;
- guide ne peut pas écraser une preuve SOLD forte ni résoudre un conflit de providers SOLD ;
- public read-only fallback borné sans secret ; API officielle facultative si token injecté par environnement.

Architecture retenue : **un orchestrateur Global + adapters indépendants**, pas un bot complet par vault. Cela conserve une seule implémentation des gates d'identité, FX, valorisation, déduplication, économie et notifications.

Validation requise avant merge : suite V4, suite Global, tests ciblés, compile, YAML, diff-check, bootstrap live read-only et assertions `marketplace_listing_is_valuation=false` / `gcc_history_economic_authority=false`. Aucun merge sans autorisation explicite.

Ledger détaillé : `docs/v4-source-role-pricecharting-20260906.md`.

---

# V4 production

## #255 — external fair-value authority — `PROD_V4`

Merge production : `9d3bb1b84d22c1534c24d7c58c5897ecce4b817f`.

GCC reste la source de listing live et d'identité/prix/timing, mais son historique est observationnel pour l'économie : il ne peut plus créer, ancrer, confirmer ou plafonner la fair value. Une preuve externe forte est requise ; `PENDING/WEAK/UNAVAILABLE` ne retombe pas sur une économie `GCC_ONLY`. Les rejets terminaux restent terminaux.

## #247 — PokeTrace aggregate quality guard — `PROD_V4`

Un agrégat PokeTrace `STRONG` sans dispersion informative ou à prix non positif/dégénéré est rétrogradé `CLEAN_INSUFFICIENT / WEAK` et son estimate est retiré du chemin économique. Aucun agrégat n'est transformé artificiellement en vente item-level.

## #245 — preserve hardened auction pagination defaults — `PROD_V4`

Le wrapper future-start ne remplace plus silencieusement le default `100 rows/page` de la pagination durcie. Recovery : `ceil(api_total/page_size)+2`, hard ceiling 250, economic cap 360, priorité `<=5m -> <=12m -> <=60m`.

## #220 + #243 — future-start auction guard — `PROD_V4`

Une auction prouvée future-start est exclue avant que starting price/countdown-to-start puissent devenir bid courant/temps avant fin. Sans preuve structurée de démarrage, la fiche rendue doit confirmer une vraie auction live ; ambiguïté/erreur = fail-closed.

## #229/#231 — auction order-drift recovery capacity — `PROD_V4`

Après dérive d'ordre prouvée uniquement : budget adaptatif borné, `api_total` utilisé au sizing seulement, `COMPLETE` exige une preuve réelle de couverture.

## Discovery GCC #211/#212 — `PROD_V4`

Fixed `/on-sale-items`, auctions `AUCTION + ON_SALE + ENDING_SOON`, horizon principal <=60 min + safety-net legacy, dérive d'ordre récupérée de manière exhaustive bornée. Main Scanner cadencé extérieurement ; pas de cron GitHub parallèle.

## #238/#239 + #242 + #253 — eBay worker resilience — `PROD_V4`

Résilience transport historique sans changement de matching/SOLD/identité. #257 est distinct : il change le **rôle économique** du direct eBay scraper, pas ses anciens mécanismes de transport.

## #237 — rollover du registre Main Scanner — `MAIN_SUPPORT`

Issue #1 archive saturée ; issue #235 registre actif.

## #216/#217 — TCGdex transport/run resilience — `PROD_V4`

Retry borné ; breaker après échecs logiques répétés ; erreurs restent `ERROR`/fail-closed.

## #222/#224 — TCGdex source-pinned outage fallback — `PROD_V4`

Fallback uniquement après erreur transport retryable avec preuve japonaise exacte et source TCGdex immuable `af33c9ac...`. `NO_MATCH`, `AMBIGUOUS`, autre langue ou preuve incomplète restent bloqués.

## #214 — débit `EXTERNAL_PENDING` — `PROD_V4`

Budgets/cooldowns historiques restent bornés ; provider failures restent fail-visible.

## TCGdex / PokeTrace #119→#135 — `PROD_V4`

Exact-coordinate, catalogue uniqueness, source-pinned finish/set et PokeTrace market-only après identité TCGdex. Aucun alias treadmill.

---

# Global Multi-Vault

Production actuelle : GCC/Cardova/Magi/Fanatics/COMC → identité commerciale exacte → TCGdex exact + microvariante → preuves externes → décision. Disappearance != SOLD ; ACTIVE_AUCTION non actionnable ; aucune transaction.

PR #257 remplace le couplage économique restant par une séparation explicite : marketplace adapters = opportunités uniquement ; valuation providers = fair value uniquement.

Scale production avant #257 : 50 listings/run, PPT 35 HTTP / 180 credits / floor 15000, PokeTrace 60, cadence 20 min (`1,21,41`), inner timeout 17 min, job timeout 25 min. #179 apporte le watchdog sans seconde lane économique.

---

# Japan Edge — #256 — `DRAFT_VALIDATION`

Mercari/SNKRDUNK = sources ASK/opportunités dans une branche séparée. Ne pas dupliquer cette capacité dans #257 et ne pas merger indépendamment sans validation explicite.

---

# Magi — `PROD_V4`

#174 + #177 = identité native déterministe ; #178 = recovery total 36, broad/nonpriority max 28, réserve exact search/detail 8. Pas de name-only/alias carte-par-carte.

---

# Robot KB — `ROBOT_KB`

PostgreSQL local Mac actif, `V4_USE=false`, Neon writers automatiques OFF. Append-only daté ; SOLD final prouvé prioritaire ; ASK/live/disparition/WAITING_FOR_PAYMENT != vente.

#180 collecte Fanatics/COMC/Magi/Cardova + PokeTrace/PPT en conservant les sémantiques. `SOLD_AGGREGATED` != item-level SOLD et `FIXED_ASK_AGGREGATED` reste ASK.

#207 est `P3_ONLY`. #210 reste OPEN/DRAFT ; aucun durable write Cardova sans autorisation explicite.

---

# V5 / non-production

PR #8 = **`V5_ONLY`**, OPEN/DRAFT/NON-MERGED. Ne jamais merger PR #8 dans `main` sans autorisation explicite.

---

# Supersessions / provenance

- #126 : `SUPERSEDED` par #127→#135 ;
- #108/#109/#110/#113/#114/#115/#138 : absorbées par #139 ;
- #159 : superseded fonctionnellement par #177 ;
- #211/#212 : une capacité runtime ;
- #216/#217 : une capacité runtime ;
- #222/#224 : une capacité runtime ;
- #229/#231 : une capacité runtime ;
- #238/#239 : une capacité eBay runtime ;
- #243 complète #220 ;
- #245 complète #229/#231 et #243 ;
- #247 complète la lignée PokeTrace ;
- #255 rend l'historique GCC observationnel pour l'économie ;
- #257, si validée/mergée, rend tous les opportunity adapters économiquement indépendants des providers de fair value.

---

# Invariants de reprise

- V4/main canonique ;
- PR #8 protégée ;
- aucun achat/bid/checkout/paiement ;
- Robot KB local séparé de V4 ;
- aucune écriture durable Cardova sans autorisation explicite ;
- identité ambiguë/microvariante incertaine = fail-closed ;
- ASK, enchère live et disparition != SOLD ;
- marketplace/opportunity source != valuation source ;
- avant nouveau code, réutiliser d'abord les capacités recensées ici et dans le README.
