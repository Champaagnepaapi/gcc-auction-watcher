# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/Git/GitHub live reste l'autorité. Les SHA et états ci-dessous sont des ancres de reprise ; toujours re-vérifier `main`, les PR et les workflows live avant une action importante.

## État canonique — 6 septembre 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production branch                 : main
V4 production HEAD                   : dfc548021c561479cc8758e2949d2c4629388d9d
V4 external fair-value authority     : #255 MERGED / production
Vault/source-role separation         : PR #257 DRAFT / NON MERGED
PR #257 branch                        : fix/v4-source-role-pricecharting-20260906
Japan Edge Mercari/SNKRDUNK          : PR #256 DRAFT / NON MERGED
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

### Phase active — PR #257 : vaults indépendants + PriceCharting systématique

Architecture cible : **un seul orchestrateur**, avec adapters d'opportunités indépendants et providers de valorisation séparés.

```text
GCC / Fanatics / COMC / Magi / Cardova
        ↓
listing exact + coût all-in uniquement
        ↓
CommercialIdentity stricte
        ↓
TCGdex exact / microvariante
        ↓
providers de valorisation externes
        ↓
décision économique
```

Règles #257 :

- un vault/marketplace découvre une offre ; son prix ne devient jamais la fair value ;
- l'historique GCC reste diagnostic / Robot KB uniquement et ne peut créer, ancrer, confirmer, plafonner ou conflict-block la fair value ;
- PriceCharting est **consulté systématiquement comme guide de référence** pour chaque identité PSA compatible évaluée ;
- PriceCharting reste `GUIDE`, jamais faux `SOLD` item-level ; aucune `ComparableSale` synthétique ;
- `PSA 10` PriceCharting -> guide PSA 10 ;
- `Grade 9` PriceCharting -> accepté comme **guide PSA 9** lorsque le listing est déjà prouvé PSA 9 exact ;
- `Grade 8` PriceCharting -> accepté comme **guide PSA 8** lorsque le listing est déjà prouvé PSA 8 exact ;
- PSA 8.5 reste distinct : aucun rabattement automatique sur Grade 8 ;
- un guide PriceCharting compatible peut suffire seul à établir une estimation quand de meilleures preuves SOLD-derived sont indisponibles ;
- les SOLD exacts/récents et preuves SOLD-derived plus fortes gardent la priorité économique ;
- **pas de marge spéciale 40 %** : le seuil économique normal V4 s'applique, actuellement 30 % ;
- une panne PriceCharting reste visible mais ne détruit pas une preuve SOLD forte déjà établie ;
- direct eBay SOLD scraping n'a plus d'autorité de fair value dans cette phase ; eBay actif futur devra être un adapter d'opportunités séparé ;
- Mercari/SNKRDUNK restent séparés dans PR #256.

Exemple : PriceCharting guide `100 EUR`, aucune meilleure preuve externe, seuil V4 `30 %` => une offre `<=70 EUR all-in` peut passer le gate économique si tous les autres gates sont satisfaits. L'ancien floor spécifique `40 %` (`<=60 EUR`) est supprimé.

La PR #257 est toujours **DRAFT / NON MERGED**. Sa validation finale doit prouver suite V4 + Global + tests ciblés + compile/YAML/diff-check + bootstrap Global live read-only avant tout merge.

Ledger : `docs/v4-source-role-pricecharting-20260906.md`.

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

Une auction prouvée non démarrée est exclue avant interprétation du prix/countdown : start future explicite => exclusion structurée ; preuve de démarrage explicite => admissible ; ambiguïté/erreur => fail-closed. Starting price et countdown-to-start ne deviennent jamais bid courant / temps avant fin.

## Marché externe V4

Production #255 : GCC n'a plus d'autorité économique de fair value. L'historique GCC est observationnel ; une opportunité économique doit venir d'une preuve externe compatible.

PR #257 ajoute, sans être encore déployée, la séparation de rôles suivante :

```text
opportunity sources    GCC / Fanatics / COMC / Magi / Cardova
valuation references   SOLD-derived compatibles + PSA APR/PokeTrace/PPT + PriceCharting GUIDE
```

PriceCharting est une estimation/guide issue de l'historique de marché selon PriceCharting, pas une liste de ventes item-level. Cette distinction reste visible dans le payload et les notifications.

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
GCC / Fanatics / COMC / Magi / Cardova
        ↓
identité commerciale exacte
        ↓
TCGdex exact + microvariante déterministe
        ↓
preuves marché externes compatibles
        ↓
décision économique
        ↓
notification seulement si gate complet
```

Actionnable seulement si identité exacte + `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` + all-in EUR prouvé + TCGdex exact + preuve de valorisation assez forte + décote requise + aucun conflit matériel.

- `ACTIVE_AUCTION` non actionnable ;
- disparition != SOLD ;
- `.github/workflows/v4-global-notify.yml` reste l'unique lane Global production ;
- PR #257 conserve un seul orchestrateur mais isole économiquement chaque adapter marketplace.

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

---

# Prochaine direction canonique

```text
PR #257
  -> PriceCharting guide systématique PSA 8/9/10 compatibles
  -> Grade 8/9 acceptés comme guides PSA 8/9 sur listing PSA exact
  -> seuil normal V4 30 %, pas floor spécial 40 %
  -> SOLD exact/récent reste prioritaire
  -> finir CI + live read-only
  -> NE PAS MERGER sans autorisation explicite

V4 providers
  -> priorité aux SOLD exacts récents lorsqu'ils existent
  -> PriceCharting = référence guide systématique, jamais faux SOLD
  -> aucun secret ni contournement anti-bot/WAF

Robot KB
  -> rester séparé de V4 / V4_USE=false
  -> aucune écriture durable Cardova sans autorisation explicite

V5
  -> PR #8 reste expérimentale/draft/non mergée
```

Aucun achat, bid, checkout ou paiement automatique.
