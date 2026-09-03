# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/Git/GitHub live reste l'autorité. Les SHA ci-dessous sont des ancres runtime/capacité ; toujours re-vérifier `main`, les PR et les workflows live avant une action importante.

## État canonique — 3 septembre 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production branch             : main
V4 production HEAD               : a39c693d629b003f69f66ba20753303b197737af (#245)
Auction pagination preservation  : #245 MERGED / validated head c553796d8829e5f6dd615acfc7177ddb60f4bf91
Auction recovery capacity        : #229/#231 MERGED / adaptive sizing / hard cap 250
Auction order-drift hardening    : #211/#212 MERGED
Future-start auction guard       : #220 + #243 MERGED / validated head 20e1a12e35464840952cdb9079e6063f014e3bef
eBay worker bulk text            : #238/#239 MERGED / validated head 90741ac0eaca42f90a6bc7fca816d347aaccafeb
eBay result before teardown      : #242 MERGED / validated head 7c97d73a9caf93871d918a8dabc5a7be72375697
V4 run registry                  : issue #235 ACTIVE / issue #1 archive saturée / #237 MERGED
TCGdex transport resilience      : #216/#217 MERGED / 03824158ac899cf142199c42d4525386a573bc15
TCGdex outage fallback           : #222/#224 MERGED / 0be4dca95513e36f4e407ef7bac361fe488c1d36
External pending throughput      : #214 MERGED / P4 16 + eBay 16 / auctions eBay max 4
Magi deterministic identity      : #174/#177 MERGED
Magi recovery budget             : #178 MERGED / recovery 36 / broad max 28
Global schedule watchdog         : #179 MERGED
Robot KB local cutover           : #166 / PostgreSQL Mac ACTIF
Robot KB multisource             : #180 MERGED
Robot KB durable                 : PostgreSQL local Mac / V4_USE=false
Neon                             : writers automatiques OFF / rollback manuel
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

### #245 — préservation du default de pagination auction

Incident naturel pré-fix : run `33795854886` sur `main@a93cd862...`.

```text
ENDING_SOON order drift          : YES
provider count hint              : 16264
recovery capacity                : 100 -> 250 pages
failure                          : auction API safety limit 250 pages reached
result                           : fail-closed vers legacy fallback
```

Cause exacte : le wrapper future-start transmettait implicitement `page_size=24`, écrasant le default durci **100 rows/page** de la couche `v4_auction_pagination_stability`. Avec ~16.2k rows, cela gonflait artificiellement le besoin d'environ 163 pages à ~678 pages.

#245 rend le wrapper transparent quand `page_size` / `max_pages` ne sont pas explicitement fournis. Les overrides explicites restent respectés. **Le hard ceiling 250 pages reste inchangé.**

```text
validated head                   : c553796d8829e5f6dd615acfc7177ddb60f4bf91
validation run                   : 33796972288 SUCCESS
V4 suite                         : 898 PASS / 2 skipped
compile / YAML / diff-check      : PASS
focused pagination regression    : PASS
read-only live auction compare   : PASS
effective / legacy               : 36 / 32
legacy_only / unresolved         : 0 / 0
production merge                 : a39c693d629b003f69f66ba20753303b197737af
Fast Lane post-merge             : 33798827669 SUCCESS
Fast Lane post-merge             : 33799115189 SUCCESS
Main Scanner exact production    : 33799767652 / a39c693d... / IN_PROGRESS au dernier contrôle
```

Le run `33798768727` ne doit **pas** être utilisé comme preuve post-#245 : il a démarré avant le merge et exécute l'ancien `a93cd862...`.

Ledger dédié : `docs/v4-auction-pagination-default-preservation-20260903.md`.

### #243 — guard future-start Main Scanner

Incident naturel du 3 septembre 2026 : Braixen #069/068 PSA 9 et Altaria #194/172 PSA 10 avaient été interprétées comme `GCC AUCTION — EXTERNAL RESCUE` alors que GCC affichait en réalité un starting price et un countdown-to-start.

La cause était un bypass Main Scanner : une row API déjà munie de `minutes_to_end` pouvait éviter la vérification de la fiche GCC rendue.

```text
validated head                   : 20e1a12e35464840952cdb9079e6063f014e3bef
validation run                   : 33794118816 SUCCESS
V4 suite                         : 896 PASS / 2 skipped
compile / YAML / diff-check      : PASS
read-only live auction compare   : PASS
effective / legacy               : 73 / 71
legacy_only / unresolved         : 0 / 0
runtime merge                    : 3ada7785d3fbef8050a7712bc773a52fd569716d
```

Sans preuve structurée de démarrage, la fiche GCC est vérifiée **avant économie**. Upcoming explicite => exclusion ; page ambiguë/erreur => fail-closed ; une vraie auction live rendue exige action de bid + sémantique explicite de fin.

### eBay #238/#239 + #242

#238/#239 réduit l'overhead Playwright des résultats eBay en lisant `li.s-item` via un bulk `all_inner_texts()` avec fallback historique. #242 conserve un résultat eBay déjà validé avant un teardown Chromium bloqué, avec cleanup borné du worker disposable.

Ces changements sont non-régressifs mais **ne prouvent pas la disparition des hard timeouts eBay**. Le prochain travail eBay doit rester un diagnostic borné/read-only par étape : navigation, challenge/provider page, row count, extraction, parsing, teardown. Aucun contournement anti-bot/WAF.

### Registre V4 #235

Issue #1 a dépassé la limite GitHub de commentaires. #237 a déplacé uniquement le registre actif Main Scanner vers **issue #235**. Issue #1 reste archive historique et ne doit pas être supprimée/réécrite.

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

## Hiérarchie des preuves prix

1. ventes **SOLD exactes et récentes** ;
2. ventes SOLD exactes anciennes, ajustées temporellement si défendable ;
3. asks fixes compatibles, explicitement étiquetés **ASK** ;
4. snapshot d'enchère observé à `≤5 min` si aucun SOLD n'est disponible ;
5. enchère en cours = signal faible.

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

## Auction discovery — #211/#212 + #229/#231 + #245

Chemin normal : `AUCTION + ON_SALE + ENDING_SOON` avec `endTime` individuel.

- ordre GCC valide : fast path ;
- dérive d'ordre prouvée : récupération exhaustive bornée puis horizon appliqué localement ;
- erreurs requête/pagination/endTime/repeated-page/no-progress : fail-closed vers le fallback legacy existant ;
- `api_total` sert uniquement au sizing, jamais à prouver la complétude ;
- statut `COMPLETE` uniquement après preuve d'épuisement réel de l'API (`nextPage` absent).

Recovery après dérive :

```text
stable page_size default          100 rows/page
budget                            ceil(api_total / page_size) + 2
minimum                           ancien bound
hard ceiling                     250 pages
```

#245 garantit qu'un wrapper future-start sans override explicite ne remplace plus silencieusement `100` par `24`.

Aucun changement : cap économique auctions `360`, priorité `≤5 min` puis `≤12 min` puis `≤60 min`, fair value, identité, providers, notifications ou transactions.

## Future-start auction guard — #220 + #243

Une auction prouvée non démarrée est exclue avant interprétation du prix/countdown :

- `startTime > observed_at` avec row id stable => exclusion structurée ;
- `startTime <= observed_at` => démarrage structuré prouvé ;
- timestamp absent/malformé => aucune supposition ;
- si timer API mais pas preuve de démarrage => vérification fiche GCC rendue avant valorisation ;
- `Enchères à venir` / `Programmer une enchère` / start explicite => exclusion ;
- vraie auction live rendue => action de bid + fin explicite ;
- page ambiguë/erreur => fail-closed ;
- starting price et countdown-to-start ne deviennent jamais bid courant / temps avant fin.

## TCGdex transport resilience — #216/#217

```text
appel logique                     max 2 tentatives
retry                             Timeout / ConnectionError / HTTP 502/503/504
breaker Main                      après 2 appels logiques épuisés consécutifs
après ouverture                   appels réseau restants sautés ce run
classification                    ERROR / fail-closed
vraie réponse provider            reset du streak
nouveau process                   circuit fermé / provider retenté
```

Une panne n'est jamais transformée en clean no-match.

## TCGdex source-pinned outage fallback — #222/#224

Fallback uniquement après `ERROR` transport retryable et avec : japonais + alias set déjà reviewé + numéro/denominator exact + source immuable `af33c9ac...` + exact `set/localId` + finish admis.

`NO_MATCH`, `AMBIGUOUS`, autre langue, set non reviewé ou preuve incomplète restent bloqués.

## External pending throughput — #214

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

Les erreurs provider restent fail-visible. Ne pas augmenter les caps uniquement pour forcer le drainage de `EXTERNAL_PENDING`.

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
GCC SOLD exact si disponible
        ↓
PPT + PokeTrace graded aggregate
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

# TCGdex — identité et microvariantes

La lignée #119→#135 reste l'autorité de récupération exacte. `variants_detailed` peut prouver après identité exacte : normal/holo/reverse, First Edition/Unlimited/Shadowless quand explicites, Poké Ball/Master Ball/Cosmos/Galaxy/Cracked Ice, langue exacte.

Axes inconnus, multiples, malformés ou contradictoires => blocage. `pricing` / `thirdParty` TCGdex n'est pas une fair value slab.

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
14. mettre à jour le handoff après une phase importante.

Documents de reprise :
- `docs/project-current-phase.md`
- `docs/project-capability-ledger.md`
- `docs/project-open-pr-inventory.md`
- `docs/project-branch-inventory.md`
- `docs/project-workflow-inventory.md`
- `docs/project-issue-inventory.md`
- `docs/project-repository-snapshot.md`

---

# Prochaine direction canonique

```text
V4 auction discovery
  -> #245 est mergé sur a39c693d...
  -> attendre/valider le premier Main Scanner naturel exact a39c693d...
  -> ne pas utiliser 33798768727 comme preuve post-merge : ancien SHA
  -> si un vrai drift ENDING_SOON survient, vérifier que recovery reste sous 250 avec default 100
  -> si 250 pages reached réapparaît, inspecter les logs avant toute autre modification
  -> ne pas augmenter le hard cap par réflexe
  -> aucun dispatch manuel uniquement pour fabriquer une preuve

V4 eBay / providers
  -> continuer l'investigation stage-timed read-only eBay
  -> ne pas contourner anti-bot/WAF
  -> continuer d'observer PSA / EXTERNAL_PENDING
  -> ne pas augmenter les caps pour masquer les erreurs provider

Robot KB
  -> rester séparé de V4 / V4_USE=false
  -> aucune écriture durable Cardova sans autorisation explicite

Global / Magi
  -> conserver les gates exacts et budgets bornés

V5
  -> PR #8 reste expérimentale/draft/non mergée
```

Aucun achat, bid, checkout ou paiement automatique.
