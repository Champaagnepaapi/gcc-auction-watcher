# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/Git/GitHub live reste l'autorité. Les SHA et états ci-dessous sont des ancres de reprise ; toujours re-vérifier `main`, les PR et les workflows live avant une action importante.

## État canonique — 7 septembre 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production branch                 : main
V4 production HEAD avant PR #261     : db4954f5b223817fe14ccfeb9dcac80c960d5dd9
V4 external fair-value authority     : #255 MERGED / production
Vault/source-role + PriceCharting    : #257 + #259 MERGED / production
Global/Japan integration             : #259 MERGED / production
Cross-grader calibration             : PR #261 DRAFT / NON MERGED
PR #261 branch                        : fix/v4-crossgrader-proxy-calibration-20260907
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
Magi recovery budget                 : #178 MERGED
Global schedule watchdog             : #179 MERGED
Robot KB local cutover               : #166 / PostgreSQL Mac ACTIF
Robot KB multisource                 : #180 MERGED
Robot KB durable                     : PostgreSQL local Mac / V4_USE=false
Neon                                 : writers automatiques OFF / rollback manuel
V5 expérimentale                     : PR #8 / OPEN / DRAFT / NON MERGED
TCGdex source pin                    : af33c9ac882e2acfadffaf19e8083aa976d12983
```

### Phase active — PR #261 : calibration des alertes CROSS-GRADER

Objectif : conserver une lane de rappel utile pour les graders secondaires sans transformer PSA en comparable exact ni produire des faux positifs comme les cas opérateur CA10 Glaceon / PCA9.5 Eevee / CA10 Riolu.

Règles #261 :

- cible non-PSA à demi-grade (`9.5`, etc.) : proxy **même grade numérique** CGC puis BGS ; aucun fallback automatique `PCA 9.5 -> PSA 9` ;
- cible non-PSA à grade entier : préférer CGC même grade ; PSA même grade seulement comme fallback conservateur ;
- si plusieurs proxies secondaires exact-grade existent, retenir la référence centrale la plus basse ;
- haircuts d'incertitude PSA fallback : PCA 30 %, CCC 35 %, CA 45 %, autre grader secondaire 40 % ;
- haircuts proxy secondaire même grade : PCA 10 %, CCC 15 %, CA 20 %, défaut 20 % ;
- cross-language ajoute 20 %, haircut combiné plafonné à 65 % ;
- PriceCharting compatible peut seulement **plafonner** la référence brute : `min(PokeTrace proxy, PriceCharting GUIDE)` ; il reste `GUIDE`, jamais `SOLD` ;
- toute alerte cross-grader exige au moins **30 % de décote après haircut** ;
- le grader/langue proxy reste explicitement affiché comme proxy de revue, jamais comparable exact ;
- schéma de déduplication cross-market v2 afin de réévaluer les anciennes alertes sous la nouvelle calibration.

Validation code/tests avant documentation : head `c58aa4c75768144946f858267a13eb493bf7a420`, workflow `V4 Auction Discovery Validation` run `34092254431` SUCCESS, 742 tests OK, compile/YAML/diff-check/comparaison live read-only PASS. Toujours revalider le head exact après les commits de documentation avant merge.

Ledger : `docs/v4-crossgrader-proxy-calibration-20260907.md`.

---

# Principes non négociables

- **V4 sur `main` = production canonique.**
- **PR #8 / V5 ne doit jamais être mergée dans `main` sans autorisation explicite utilisateur.**
- Pokémon **cartes individuelles uniquement** ; sealed/lots hors scope.
- Aucun achat, bid, checkout, paiement ou grading payant automatique.
- Aucun secret, token, cookie, session ou mot de passe dans le repo/logs.
- Identité incertaine, contradictoire ou microvariante non prouvée = fail-closed / revue manuelle.
- Ne jamais mélanger langue, grader, grade ou microvariante incompatibles.
- Aucun fuzzy, substring, token overlap, traduction supposée ou Levenshtein comme preuve exacte hors lane explicitement bornée et non économique.
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

Une auction prouvée non démarrée est exclue avant interprétation du prix/countdown : start future explicite => exclusion structurée ; preuve de démarrage explicite => admissible ; ambiguïté/erreur => fail-closed. Starting price et countdown-to-start ne deviennent jamais bid courant / temps avant fin.

## Marché externe V4

Production #255 : GCC n'a plus d'autorité économique de fair value. L'historique GCC est observationnel ; une opportunité économique doit venir d'une preuve externe compatible.

Production #257/#259 sépare strictement les rôles :

```text
opportunity sources    GCC / Fanatics / COMC / Magi / Cardova / Mercari / SNKRDUNK / asks actifs compatibles
valuation references   SOLD-derived compatibles + PSA APR/PokeTrace/PPT + PriceCharting GUIDE
```

Un marketplace/vault découvre un coût d'achat potentiel ; son ask ou enchère live ne devient jamais fair value. L'historique GCC reste diagnostic / Robot KB uniquement.

PriceCharting est consulté comme guide de référence pour les identités compatibles. Il reste `GUIDE`, jamais faux `SOLD` item-level. Les SOLD exacts/récents et preuves SOLD-derived plus fortes gardent la priorité économique. Pour un listing PSA déjà prouvé exact, Grade 9/8 PriceCharting peut servir de guide PSA 9/8 ; PSA 8.5 reste distinct.

Le seuil économique normal reste celui de V4 ; aucun floor spécial 40 % n'est imposé uniquement parce que la référence est PriceCharting.

### Cross-grader manual review — PR #261

La lane cross-grader est une **lane de revue manuelle**, pas une fair-value conversion automatique entre graders. Les demi-grades non-PSA exigent un proxy secondaire de même grade numérique ; les grades entiers préfèrent CGC même grade avant tout fallback PSA. PriceCharting peut plafonner une référence compatible mais reste un guide. Une alerte cross-grader exige au moins 30 % de décote après haircut.

### PokeTrace aggregate quality — #247

PokeTrace reste une source agrégée et corrélée à la famille eBay. Une preuve PokeTrace `STRONG` dont l'enveloppe est invalide/non positive/dégénérée est rétrogradée `CLEAN_INSUFFICIENT / WEAK` et son estimate est retiré du chemin économique. Aucun agrégat n'est transformé artificiellement en vente item-level.

### eBay / PSA APR

Les protections #238/#239/#242/#253 bornent les opérations eBay. PSA APR peut encore renvoyer HTTP 403 et eBay peut encore timeout. Ces erreurs restent visibles/fail-closed ; aucun contournement anti-bot/WAF.

## TCGdex — identité et microvariantes

TCGdex reste la couche d'identité exacte. `variants_detailed` peut prouver les axes matériels après identité exacte. Axes inconnus, multiples, malformés ou contradictoires => blocage. `pricing` / `thirdParty` TCGdex n'est pas une fair value slab.

Transport : retry borné sur timeout/connexion/HTTP 502/503/504, breaker run-wide après échecs répétés, jamais de panne convertie en clean no-match.

## Fast Lane

```text
Cron-job.org ~toutes les 3 min
  -> workflow_dispatch
  -> .github/workflows/v4-final-auction-check.yml
  -> recheck ciblé des auctions déjà armées à ≤5 min
```

Aucun bid automatique. PSA scope économique : `8`, `8.5`, `9`, `10`; jamais de PSA 9.5 synthétique.

---

# Global Multi-Vault — production marketplace-first

```text
GCC / Fanatics / COMC / Magi / Cardova / Mercari / SNKRDUNK
        ↓
identité commerciale exacte
        ↓
TCGdex exact + microvariante déterministe
        ↓
providers de valorisation séparés
        ↓
décision économique
        ↓
notification seulement si gate complet
```

Actionnable seulement si identité exacte + offre admissible + all-in EUR prouvé + TCGdex exact + preuve de valorisation assez forte + décote requise + aucun conflit matériel.

- marketplace/vault = opportunité uniquement ;
- `ACTIVE_AUCTION` non actionnable hors règle explicitement bornée de snapshot final ;
- disparition != SOLD ;
- `.github/workflows/v4-global-notify.yml` reste l'unique lane Global production ;
- PriceCharting/PokeTrace/PPT/PSA APR restent séparés des adapters d'opportunités.

Scale production : 50 listings/run, PPT 35 HTTP / 180 credits / floor 15000, PokeTrace 60, cadence 20 min (`1,21,41`), inner timeout 17 min, job timeout 25 min.

---

# Magi — identité native japonaise

#174 + #177 = récupération déterministe. #178 protège le budget : recovery total 36, broad/nonpriority 28 max, réserve exact card-search/detail 8. Pas de fallback name-only ni d'alias carte-par-carte pour les cas non prouvés.

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
- `docs/v4-crossgrader-proxy-calibration-20260907.md`

---

# Prochaine direction canonique

```text
PR #261
  -> cross-grader fractional: même grade CGC/BGS, jamais PCA9.5 -> PSA9
  -> whole grade secondaire: CGC même grade préféré, PSA fallback conservateur
  -> PriceCharting = cap GUIDE compatible, jamais SOLD
  -> floor revue cross-grader 30 % après haircut
  -> revalider CI sur le head exact après docs
  -> NE PAS MERGER sans autorisation explicite

V4 providers
  -> priorité aux SOLD exacts récents lorsqu'ils existent
  -> PriceCharting = référence guide systématique compatible, jamais faux SOLD
  -> aucun secret ni contournement anti-bot/WAF

Robot KB
  -> rester séparé de V4 / V4_USE=false
  -> aucune écriture durable Cardova sans autorisation explicite

V5
  -> PR #8 reste expérimentale/draft/non mergée
```

Aucun achat, bid, checkout ou paiement automatique.
