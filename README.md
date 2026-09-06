# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/Git/GitHub live reste l'autorité. Les SHA et états ci-dessous sont des ancres de reprise ; toujours re-vérifier `main`, les PR et les workflows live avant une action importante.

## État canonique — 6 septembre 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production branch                 : main
V4 production HEAD                   : dfc548021c561479cc8758e2949d2c4629388d9d
V4 external fair-value authority     : #255 MERGED
PR #255 merge commit                 : 9d3bb1b84d22c1534c24d7c58c5897ecce4b817f
Source-role / PriceCharting phase    : PR #257 OPEN / DRAFT / NON MERGED
PR #257 branch                        : fix/v4-source-role-pricecharting-20260906
Japan vault providers                : PR #256 OPEN / DRAFT / NON MERGED
PokeTrace aggregate guard            : #247 MERGED
Auction pagination preservation      : #245 MERGED
Auction recovery capacity            : #229/#231 MERGED / adaptive sizing / hard cap 250
Auction order-drift hardening        : #211/#212 MERGED
Future-start auction guard           : #220 + #243 MERGED
eBay worker resilience               : #238/#239 + #242 + #253 MERGED
V4 run registry                      : issue #235 ACTIVE / issue #1 archive saturée
TCGdex transport resilience          : #216/#217 MERGED
TCGdex outage fallback               : #222/#224 MERGED
External pending throughput          : #214 MERGED
Magi deterministic identity          : #174/#177 MERGED
Magi recovery budget                 : #178 MERGED / recovery 36 / broad max 28
Global schedule watchdog             : #179 MERGED
Robot KB local cutover               : #166 / PostgreSQL Mac ACTIF
Robot KB multisource                 : #180 MERGED
Robot KB durable                     : PostgreSQL local Mac / V4_USE=false
Neon                                 : writers automatiques OFF / rollback manuel
V5 expérimentale                     : PR #8 / OPEN / DRAFT / NON MERGED
TCGdex source pin                    : af33c9ac882e2acfadffaf19e8083aa976d12983
```

### Production actuelle — #255 : GCC n'est plus une autorité de fair value

Depuis #255, GCC reste une source de **listing/opportunité** et d'identité live, mais son historique ne peut plus créer, ancrer, confirmer ou plafonner la fair value V4.

Exemple canonique :

```text
GCC historique visible            : 18 / 20 / 25 EUR
GCC prix live                     : 30 EUR
preuve externe forte             : ~45–50 EUR
interprétation correcte           : opportunité potentielle forte
interprétation interdite          : "30 EUR est cher car GCC a vendu 20–25 EUR"
```

Les ventes historiques GCC restent observables pour diagnostics / Robot KB. `PENDING`, `WEAK`, provider error ou `UNAVAILABLE` externe restent fail-closed. Les rejets terminaux de sécurité restent terminaux.

### Phase active — PR #257 : séparer complètement opportunités et valorisation

Objectif : chaque marketplace/vault est un **scanner d'offres indépendant**, tandis que la fair value vient d'une couche de providers de valorisation séparée.

Architecture cible :

```text
GCC ───────┐
Fanatics ──┤
COMC ──────┤
Magi ──────┤──> offres normalisées / identité stricte ──┐
Cardova ───┘                                             │
                                                        ├──> edge par offre ──> notification
providers de valorisation séparés ──────────────────────┘
```

Règles de #257 :

- un seul orchestrateur Global, mais **un adapter indépendant par marketplace** ;
- le prix d'un vault est uniquement un **prix d'achat potentiel** ;
- une offre Fanatics/COMC/Cardova/Magi/GCC ne peut jamais devenir la fair value d'une autre offre ;
- historique GCC = diagnostic/Robot KB uniquement ;
- direct eBay SOLD scraping = retiré de l'autorité de valorisation dans cette phase ;
- eBay actif, lorsqu'il sera ajouté, devra être un **adapter d'opportunités** séparé ;
- PR #256 ajoute Mercari/SNKRDUNK dans une phase Japan Edge séparée : ne pas dupliquer ni merger indépendamment sans validation ;
- aucune transaction automatique.

### PriceCharting dans #257

PriceCharting est ajouté à la **couche de valorisation**, pas à la couche marketplace.

Point important : PriceCharting expose un **guide de prix**. Le robot peut utiliser ce guide comme estimation secondaire, mais il ne doit jamais le présenter comme une liste de ventes `SOLD` individuelles prouvées.

Politique proposée :

- PokeTrace / PokemonPriceTracker et PSA APR gardent la priorité lorsqu'une preuve forte compatible existe ;
- PriceCharting = fallback borné ;
- seul le bucket **PSA 10 explicitement identifiable** peut produire une preuve automatique ;
- guide PriceCharting seul => seuil économique plus conservateur, **décote minimale 40 %** ;
- buckets grade 9/8 génériques = `WEAK` / contexte seulement, car ils ne prouvent pas le grader exact ;
- un guide PriceCharting ne peut jamais résoudre/écraser un conflit entre preuves SOLD fortes ;
- aucune valeur PriceCharting n'est transformée en faux comparable item-level.

PR #257 reste **DRAFT / NON MERGED** jusqu'à suite V4 + suite Global + compile/YAML/diff-check + bootstrap live read-only verts, puis autorisation explicite avant merge.

---

# Principes non négociables

- **V4 sur `main` = production canonique.**
- **PR #8 / V5 ne doit jamais être mergée dans `main` sans autorisation explicite utilisateur.**
- Pokémon **cartes individuelles uniquement** ; sealed/lots hors scope.
- Aucun achat, bid, checkout, paiement ou grading payant automatique.
- Aucun secret, token, cookie, session ou mot de passe dans le repo/logs.
- Identité incertaine, contradictoire ou microvariante non prouvée = fail-closed / revue manuelle.
- Ne jamais mélanger langue, grader, grade ou microvariante incompatibles.
- Aucun fuzzy, substring, token overlap, traduction supposée ou Levenshtein comme preuve exacte.
- ASK, enchère live et disparition d'annonce ne deviennent jamais des ventes.

---

# V4 — production canonique

## Main Scanner

```text
Cron-job.org ~toutes les 10 min
  -> workflow_dispatch
  -> .github/workflows/watcher.yml
  -> run_watcher_multimarket_resilient.py
  -> run_watcher_multimarket.py
```

Le Main Scanner est cadencé extérieurement. **Ne jamais ajouter un cron GitHub parallèle.** Son registre actif est l'issue #235.

## Auction discovery

Chemin normal : `AUCTION + ON_SALE + ENDING_SOON` avec `endTime` individuel.

- ordre GCC valide : fast path ;
- dérive d'ordre prouvée : récupération exhaustive bornée puis horizon appliqué localement ;
- erreurs requête/pagination/endTime/repeated-page/no-progress : fail-closed vers le fallback legacy existant ;
- `api_total` sert uniquement au sizing, jamais à prouver la complétude ;
- statut `COMPLETE` uniquement après preuve d'épuisement réel de l'API ou horizon correctement franchi dans un ordre vérifié.

Recovery :

```text
stable page_size default          100 rows/page
budget                            ceil(api_total / page_size) + 2
minimum                           ancien bound
hard ceiling                     250 pages
auction economic cap             360
priority                         ≤5 min -> ≤12 min -> ≤60 min
```

#245 garantit qu'un wrapper future-start sans override explicite ne remplace plus silencieusement `100` par `24`.

## Future-start auction guard — #220 + #243

Une auction prouvée non démarrée est exclue avant interprétation du prix/countdown :

- `startTime > observed_at` avec row id stable => exclusion structurée ;
- `startTime <= observed_at` => démarrage structuré prouvé ;
- timestamp absent/malformé => aucune supposition ;
- si timer API sans preuve de démarrage => vérification fiche GCC rendue avant valorisation ;
- `Enchères à venir` / `Programmer une enchère` / start explicite => exclusion ;
- vraie auction live rendue => action de bid + fin explicite ;
- page ambiguë/erreur => fail-closed ;
- starting price et countdown-to-start ne deviennent jamais bid courant / temps avant fin.

## Marché externe V4

Production `main` contient #255 : l'historique GCC n'a plus d'autorité économique. Avant #257, le transport externe historique reste encore présent dans le code production.

PR #257 propose l'ordre de rôle suivant :

```text
PokeTrace / PokemonPriceTracker   -> valorisation SOLD-derived quand preuve forte
PSA APR                           -> valorisation exacte PSA fallback
PriceCharting                     -> guide de valorisation fallback, PSA10 auto seulement
Direct eBay SOLD scraper          -> aucune autorité de fair value
Marketplace ask/current price     -> aucune autorité de fair value
```

Les erreurs provider restent fail-visible. Ne pas augmenter les caps uniquement pour masquer les timeouts/403 ou forcer un résultat.

### PokeTrace aggregate quality — #247

PokeTrace reste une source **agrégée** et corrélée à la famille eBay. Après identité TCGdex exacte, une preuve PokeTrace `STRONG` dont l'enveloppe est invalide, non positive ou `<= 0.01 EUR` est rétrogradée `CLEAN_INSUFFICIENT / WEAK` et son estimate est retiré du chemin économique.

Un agrégat n'est jamais transformé artificiellement en vente item-level.

### PSA APR / PriceCharting / eBay

- PSA APR peut renvoyer HTTP 403 : erreur visible, fail-closed, aucun contournement WAF ;
- PriceCharting #257 : guide secondaire borné, jamais `SOLD` item-level ;
- eBay actif n'est **pas encore** un scanner d'opportunités Global dans #257 ; c'est une phase suivante ;
- les anciens modules de transport eBay restent dans le repo mais #257 les retire du rôle de fair-value authority.

## TCGdex — identité et microvariantes

TCGdex reste la couche d'identité exacte. `variants_detailed` peut prouver après identité exacte : normal/holo/reverse, First Edition/Unlimited/Shadowless quand explicites, Poké Ball/Master Ball/Cosmos/Galaxy/Cracked Ice et langue exacte.

Axes inconnus, multiples, malformés ou contradictoires => blocage. `pricing` / `thirdParty` TCGdex n'est pas une fair value slab.

Transport : retry borné sur timeout/connexion/HTTP 502/503/504, breaker run-wide après échecs répétés, jamais de panne convertie en clean no-match.

Fallback outage source-pinned uniquement après erreur transport retryable et preuve japonaise exacte via la source immuable `af33c9ac...`. `NO_MATCH`, `AMBIGUOUS`, autre langue ou preuve incomplète restent bloqués.

## Fast Lane

```text
Cron-job.org ~toutes les 3 min
  -> workflow_dispatch
  -> .github/workflows/v4-final-auction-check.yml
  -> recheck ciblé des auctions déjà armées à ≤5 min
```

Aucun bid automatique. PSA scope économique : `8`, `8.5`, `9`, `10`; jamais de PSA 9.5 synthétique.

---

# Global Multi-Vault

Production actuelle : `.github/workflows/v4-global-notify.yml` reste l'unique lane Global.

PR #257 conserve **un seul robot/orchestrateur Global** plutôt qu'un bot complet par vault. Le découpage est fait au niveau des adapters : chaque vault peut tomber en panne, changer son HTML ou être durci indépendamment, sans dupliquer la logique d'identité, de valorisation, de déduplication et de notification.

```text
opportunity adapters
  GCC / Fanatics / COMC / Magi / Cardova
        ↓
CommercialIdentity stricte
        ↓
TCGdex exact + microvariante déterministe
        ↓
valuation providers indépendants
  PPT/PokeTrace -> PriceCharting fallback
        ↓
décision par offre
        ↓
notification seulement si gate complet
```

Règles :

- `FIXED_ASK` = offre actionnable potentielle, jamais vente ;
- `AUCTION_SNAPSHOT_LE5` = offre potentielle bornée, jamais vente finale ;
- `ACTIVE_AUCTION` non actionnable ;
- disparition != SOLD ;
- une marketplace ne confirme jamais la fair value d'une autre ;
- aucun provider d'opportunité n'obtient une autorité économique simplement parce qu'il est dans le même processus.

Scale production avant #257 : 50 listings/run, PPT 35 HTTP / 180 credits / floor 15000, PokeTrace 60, cadence 20 min (`1,21,41`), inner timeout 17 min, job timeout 25 min.

---

# Japan Edge / Mercari / SNKRDUNK

PR #256 est **OPEN / DRAFT / NON MERGED**. Elle traite Mercari et SNKRDUNK comme sources d'ASK/opportunités dans la lane Japan Edge. Elle reste séparée de #257 et ne doit pas être mergée indépendamment sans validation explicite.

---

# Magi — identité native japonaise

#174 + #177 = récupération déterministe. #178 protège le budget : recovery total 36, broad/nonpriority 28 max, réserve exact card-search/detail 8.

Pas de fallback name-only ni d'alias carte-par-carte pour les cas non prouvés.

---

# Robot KB — PostgreSQL local Mac

Robot KB reste séparé de la décision commerciale V4/Global. `V4_USE=false`.

Contrat : observations append-only datées, payload brut + provenance, priorité aux SOLD finaux prouvés, fixed baseline + changements utiles, auctions SOLD final prioritaire, snapshot ≤5 min seulement fallback identifié. ASK/live/disparition/`WAITING_FOR_PAYMENT` != SOLD.

Migration Neon → Mac historiquement vérifiée : 1 087 015 lignes, 35 tables, `MIGRATION_VERIFIED`, health OK. Writers Neon automatiques OFF ; Neon = rollback/recovery manuel.

#180 ajoute les collectors multisource locaux avec séparation stricte des sémantiques. Les clés provider restent uniquement dans le Trousseau macOS.

## P3 / Cardova durable

- #207 est mergée **uniquement dans `agent/p3-postgres-durable-shadow`** ; aucune migration durable utilisateur exécutée.
- #210 reste OPEN/DRAFT/NON-MERGED et prépare seulement un commit durable Cardova gardé par autorisation explicite + backup + locks.
- Aucun write durable Cardova sans autorisation explicite opérateur.

---

# V5 — EXPÉRIMENTALE

```text
PR #8        OPEN / DRAFT / NON MERGED
branch       agent/v5-poketrace-cardmarket-market-data
```

**Ne jamais merger PR #8 dans `main` sans autorisation explicite.**

---

# Gouvernance avant changement important

1. lire entièrement ce README ;
2. lire `.agents/rules/gcc-project-governance.md` ;
3. lire `AGENTS.md` s'il existe ; son absence n'est pas une erreur ;
4. lire capability ledger + inventaires pertinents ;
5. vérifier Git local seulement si le worktree est réellement accessible ;
6. vérifier `main`, SHA, PRs, branches et workflows live ;
7. rechercher une capacité existante avant de réimplémenter ;
8. branche/PR dédiée pour changement non trivial ;
9. SHA précis + tests ciblés + suite pertinente ;
10. compile/YAML/`git diff --check` ;
11. live read-only lorsque pertinent ;
12. aucune transaction/secret ;
13. merge seulement avec l'autorisation requise ;
14. mettre à jour ce README / le handoff après une phase importante.

Documents de reprise :
- `docs/project-current-phase.md`
- `docs/project-capability-ledger.md`
- `docs/project-open-pr-inventory.md`
- `docs/project-branch-inventory.md`
- `docs/project-workflow-inventory.md`
- `docs/project-issue-inventory.md`
- `docs/project-repository-snapshot.md`
- `docs/v4-external-fair-value-authority-20260906.md`
- `docs/v4-source-role-pricecharting-20260906.md`

---

# Prochaine direction canonique

```text
PR #257
  -> terminer CI + bootstrap Global live read-only
  -> aucun merge avant autorisation explicite
  -> après validation : source roles marketplace/valuation deviennent canoniques

Opportunity adapters
  -> conserver GCC/Fanatics/COMC/Magi/Cardova indépendants
  -> #256 couvre Mercari/SNKRDUNK séparément
  -> ajouter eBay ACTIF plus tard comme adapter d'opportunités, pas comme fair value

Valuation providers
  -> priorité aux preuves SOLD fortes compatibles
  -> PSA APR exact quand disponible
  -> PriceCharting guide = fallback secondaire, pas faux SOLD
  -> generic grade buckets ne deviennent jamais grader exact

Robot KB
  -> rester séparé de V4 / V4_USE=false
  -> aucune écriture durable Cardova sans autorisation explicite

V5
  -> PR #8 reste expérimentale/draft/non mergée
```

Aucun achat, bid, checkout ou paiement automatique.
