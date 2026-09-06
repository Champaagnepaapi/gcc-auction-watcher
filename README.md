# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/Git/GitHub live reste l'autorité. Les SHA et états ci-dessous sont des ancres de reprise ; toujours re-vérifier `main`, les PR et les workflows live avant une action importante.

## État canonique — 6 septembre 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production branch                 : main
V4 production HEAD                   : 23e8e9904072d986e24d2a8fbccaa87568851f69
V4 external fair-value authority     : PR #255 DRAFT / NON MERGED
PR #255 branch                        : v4-external-fair-value-authority-20260906
PR #255 base                          : 23e8e9904072d986e24d2a8fbccaa87568851f69
PokeTrace aggregate guard            : #247 MERGED
Auction pagination preservation      : #245 MERGED
Auction recovery capacity            : #229/#231 MERGED / adaptive sizing / hard cap 250
Auction order-drift hardening        : #211/#212 MERGED
Future-start auction guard           : #220 + #243 MERGED
eBay worker resilience               : #238/#239 + #242 + #253 MERGED
V4 run registry                      : issue #235 ACTIVE / issue #1 archive saturée
TCGdex transport resilience          : #216/#217 MERGED
TCGdex outage fallback               : #222/#224 MERGED
External pending throughput          : #214 MERGED / P4 16 + eBay 16 / auctions eBay max 4
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

### Phase active — PR #255 : GCC n'est plus une autorité de fair value

Objectif économique : exploiter les cartes GCC sous-évaluées lorsque les acheteurs restent ancrés sur un historique GCC ancien, rare ou peu représentatif du marché global actuel.

Exemple canonique :

```text
GCC historique visible            : 18 / 20 / 25 EUR
GCC prix live                     : 30 EUR
SOLD externes exacts récents      : ~45–50 EUR
interprétation correcte           : opportunité potentielle forte
interprétation interdite          : "30 EUR est cher car GCC a vendu 20–25 EUR"
```

Politique V4 cible de #255 :

- GCC reste la source du **listing live** : URL, carte exacte, set/numéro, langue, grader, grade, prix courant et timing ;
- les ventes historiques GCC restent observables pour diagnostics / Robot KB ;
- l'historique GCC **ne peut plus créer, ancrer, confirmer ou plafonner la fair value** ;
- une opportunité d'achat exige une preuve marché externe suffisamment forte ;
- `PENDING`, `WEAK`, provider error ou `UNAVAILABLE` externe => **fail-closed**, jamais fallback économique `GCC_ONLY` ;
- les rejets GCC terminaux de sécurité restent terminaux ;
- aucune identité, définition SOLD, limite provider, seuil économique ou transaction automatique n'est relâchée.

Ordre de preuve prix canonique :

1. **SOLD exacts et récents** sur le marché global ;
2. SOLD exacts plus anciens, ajustés temporellement si défendable ;
3. asks fixes compatibles, explicitement étiquetés `ASK` ;
4. snapshot d'enchère observé à `≤5 min` uniquement si aucun SOLD n'est disponible ;
5. enchère en cours = signal faible seulement.

**PriceCharting / agrégateurs :** utiles pour localiser et résumer le marché global, mais un guide price agrégé ne doit jamais surclasser des SOLD item-level exacts et récents. La V5 possède une intégration API PriceCharting expérimentale qui retourne des guide values et exige un token ; elle n'est pas backportée automatiquement et PR #8 reste strictement non mergée.

Implémentation #255 : `v4_external_fair_value_authority.py` neutralise uniquement l'autorité économique de l'historique GCC avant l'arbitrage existant. Le provider tree externe, les gates d'identité et la sémantique SOLD restent inchangés.

Ledger : `docs/v4-external-fair-value-authority-20260906.md`.

**Sécurité déploiement :** #255 a été préparée sur branche dédiée pendant les enchères Weekly Auction du 6 septembre. **Ne pas merger/déployer pendant les enchères actives.** Aucun achat, bid, checkout ou paiement automatique n'est introduit.

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

Les preuves externes passent par l'arbre existant PokeTrace / PSA APR / eBay avec identité commerciale stricte.

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

Les erreurs provider restent fail-visible. Ne pas augmenter les caps uniquement pour masquer les timeouts/403 ou forcer le drainage de `EXTERNAL_PENDING`.

### PokeTrace aggregate quality — #247

PokeTrace reste une source **agrégée** et corrélée à la famille eBay. Après identité TCGdex exacte, une preuve PokeTrace `STRONG` dont l'enveloppe est invalide, non positive ou `<= 0.01 EUR` est rétrogradée `CLEAN_INSUFFICIENT / WEAK` et son estimate est retiré du chemin économique. APR/eBay doit prendre le relais.

Un agrégat n'est jamais transformé artificiellement en vente item-level.

### eBay / PSA APR

Les protections #238/#239/#242/#253 bornent les opérations eBay et préservent un résultat déjà prouvé avant certains timeouts/teardown. PSA APR peut encore renvoyer HTTP 403 et eBay peut encore timeout. Ces erreurs doivent rester visibles et fail-closed ; aucun contournement anti-bot/WAF.

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

# Global Multi-Vault — production marketplace-first

Global reste séparé du changement V4 #255 tant qu'une phase dédiée ne l'a pas validé.

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

Actionnable seulement si identité exacte + `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` + all-in EUR prouvé + TCGdex exact + externe gradé assez fort + décote requise + aucun conflit matériel.

- `ACTIVE_AUCTION` non actionnable ;
- PPT/PokeTrace/eBay = famille corrélée `EBAY_GRADED_AGGREGATE` ;
- disparition != SOLD ;
- `.github/workflows/v4-global-notify.yml` reste l'unique lane Global production.

Scale canonique : 50 listings/run, PPT 35 HTTP / 180 credits / floor 15000, PokeTrace 60, cadence 20 min (`1,21,41`), inner timeout 17 min, job timeout 25 min.

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

---

# Prochaine direction canonique

```text
V4 external fair value
  -> PR #255 DRAFT / NON MERGED
  -> GCC = listing identity/current price/timing, pas fair-value authority
  -> valider suite + live read-only sur le head exact
  -> vérifier un cas Poochyena-like avec strong external SOLD evidence
  -> ne pas merger pendant les enchères actives

V4 providers
  -> priorité aux SOLD exacts récents
  -> investigation eBay/PSA APR read-only si timeout/403
  -> PriceCharting peut compléter la couverture dans une phase dédiée
  -> un guide value agrégé ne remplace jamais des SOLD exacts récents
  -> aucun secret ni contournement anti-bot/WAF

V4 auction discovery
  -> default 100 rows/page et hard ceiling 250 inchangés
  -> si 250 pages reached réapparaît, inspecter avant toute modification

Robot KB
  -> rester séparé de V4 / V4_USE=false
  -> aucune écriture durable Cardova sans autorisation explicite

Global / Magi
  -> conserver les gates exacts et budgets bornés

V5
  -> PR #8 reste expérimentale/draft/non mergée
```

Aucun achat, bid, checkout ou paiement automatique.
