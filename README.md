# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/Git/GitHub live reste l'autorité. Les SHA ci-dessous sont des ancres runtime/capacité ; toujours re-vérifier `main`, les PR et les workflows live avant une action importante.

## État canonique — 1 septembre 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production branch             : main
V4 runtime production            : b6a7c834264c062ea81b64c714e6916aa8bfe9f2 (#229/#231)
Auction recovery capacity        : #229/#231 MERGED / adaptive count-hint sizing / hard cap 250
Auction order-drift hardening    : #211/#212 MERGED
Future-start auction guard       : #220 MERGED / 6a33ac33faa324f0fc1c6124fbb49bd736382b75
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

### Validation du runtime auction #229/#231

```text
validated head/tree              : f81f81d1cf349a298d07867e9750704a9ea0c2bd / 0170d41c548878f4a4a77b7662f0b0a6e0f002c2
#229 clean validation            : run 33563203801 SUCCESS
#231 merge-mirror validation     : run 33563438585 SUCCESS
V4 complete suite                : PASS
compile / YAML / diff-check      : PASS
read-only live compare           : PASS
api_primary_complete             : true
api_primary_scope                : COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
legacy_only / unresolved         : 0 / 0
production merge                 : b6a7c834264c062ea81b64c714e6916aa8bfe9f2
natural post-merge prod proof    : en attente ; aucun dispatch manuel
```

Le toggle GitHub `Ready for review` de #229 a échoué sur le bug GraphQL connu `fullDatabaseId`. #231 a donc servi de miroir non-draft **sur le même head/tree exact**. GitHub marque désormais #229 et #231 comme mergées vers le même runtime de production.

---

# Principes non négociables

- **V4 sur `main` = production canonique.**
- **PR #8 / V5 ne doit jamais être mergée dans `main` sans autorisation explicite utilisateur.**
- Pokémon **cartes individuelles uniquement** ; sealed/lots hors scope.
- Aucun achat, bid, checkout, paiement ou grading payant automatique.
- Aucun secret, token, cookie, session ou mot de passe dans le repo/logs.
- Identité incertaine, contradictoire ou microvariante non prouvée = fail-closed / revue manuelle.
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

Le Main Scanner est cadencé extérieurement. **Ne jamais ajouter un cron GitHub parallèle.**

## Auction discovery — #211/#212 + #229/#231

Chemin normal : `AUCTION + ON_SALE + ENDING_SOON` avec `endTime` individuel.

- ordre GCC valide : fast path inchangé ;
- dérive d'ordre prouvée : récupération exhaustive bornée de la requête filtrée puis horizon appliqué localement ;
- erreurs de requête/pagination/endTime/repeated-page/no-progress restent fail-closed vers le fallback legacy existant.

### Capacity hardening #229/#231

Le marché `AUCTION + ON_SALE` a dépassé l'ancienne capacité de récupération de 100 pages : les runs naturels `33547948642` et `33549911988` ont atteint `auction API safety limit 100 pages reached`, alors qu'un snapshot voisin `33548929050` restait sain sur le fast path.

Le nouveau recovery ne change **que son budget de requêtes après dérive d'ordre** :

```text
budget = ceil(api_total / page_size) + 2
minimum = ancien bound
hard ceiling = 250 pages
```

`api_total` est **uniquement un indice de capacité**. Il ne prouve jamais la complétude. Le statut `COMPLETE` exige toujours l'épuisement réel de l'API (`nextPage` absent). Pour ~15 049 rows à 100/page, la capacité devient 153 pages au lieu de 100.

Aucun changement :
- cap économique auctions `360` ;
- priorité `≤5 min`, puis `≤12 min`, puis `≤60 min` ;
- fair value / `max_recommended` / seuil de décote ;
- identité ;
- TCGdex/PokeTrace/eBay/PSA ;
- notifications ;
- transactions.

Première preuve naturelle **post-merge** à observer : un run `main@b6a7c834...` avec vraie dérive d'ordre. Ne pas provoquer ce cas ni lancer un scanner manuel juste pour le tester.

## Future-start auction guard — #220

Une enchère prouvée comme n'ayant pas encore commencé est exclue avant interprétation du prix/countdown :

- timestamp GCC structuré + row id stable => exclusion ;
- timestamp manquant/malformé => aucune supposition ;
- preuve UI uniquement si forte (`Schedule a bid` / équivalent ou upcoming + start label explicite) ;
- starting price et countdown-to-start ne deviennent jamais bid courant / temps avant fin.

Le guard se superpose au hardening de discovery ; il ne le remplace pas.

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

Aucune panne n'est transformée en clean no-match.

## TCGdex source-pinned outage fallback — #222/#224

Le fallback ne peut agir qu'après un `ERROR` transport retryable et exige simultanément : langue japonaise, alias de set déjà reviewé, numéro/denominator exact compatible, source TCGdex immuable `af33c9ac...`, exact `set/localId` et finish déjà admis.

`NO_MATCH`, `AMBIGUOUS`, autre langue, set non reviewé ou preuve incomplète restent bloqués. Aucun alias treadmill ni relaxation d'identité.

Preuve production post-#224 : run `33500303400` SUCCESS, TCGdex `17 exact / 1 no-match / 0 ambiguous / 0 errors`, PokeTrace sain, discovery auctions `24/24 COMPLETE`, backlog `1966`. Provider sain ce jour-là : preuve de non-régression, pas d'activation positive de l'outage fallback.

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

Les erreurs provider restent fail-visible et ne deviennent jamais une preuve négative fabriquée. Ne pas augmenter les caps uniquement pour forcer le drainage.

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

Actionnable seulement si identité exacte + `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` + all-in EUR prouvé + TCGdex exact + externe gradé exact assez fort + décote ≥30 % + aucun conflit matériel.

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

Migration Neon → Mac vérifiée : 1 087 015 lignes, 35 tables, `MIGRATION_VERIFIED`, health OK. Writers Neon automatiques OFF ; Neon = rollback/recovery manuel.

#180 a ajouté les collectors multisource locaux avec séparation stricte des sémantiques. Les clés provider restent uniquement dans le Trousseau macOS.

## P3 / Cardova durable

- #207 est mergée **uniquement dans `agent/p3-postgres-durable-shadow`** ; aucune migration durable utilisateur exécutée.
- #210 reste OPEN/DRAFT/NON-MERGED et prépare seulement un commit durable Cardova gardé par autorisation explicite + backup + locks.
- Aucun write durable Cardova sans autorisation explicite opérateur.

---

# V5 — EXPÉRIMENTALE

```text
PR #8        OPEN / DRAFT / NON MERGED
branch       agent/v5-poketrace-cardmarket-market-data
head         bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

**Ne jamais merger PR #8 dans `main` sans autorisation explicite.**

---

# Gouvernance avant changement important

1. lire entièrement ce README ;
2. lire `.agents/rules/gcc-project-governance.md` ;
3. lire `AGENTS.md` s'il existe ;
4. lire capability ledger + inventaires pertinents ;
5. vérifier Git local si le worktree est réellement accessible ;
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
V4
  -> attendre un run naturel main@b6a7c834... avec vraie dérive d'ordre
  -> vérifier que le recovery adaptatif atteint l'épuisement API ou reste fail-closed
  -> continuer d'observer le premier cas future-start réellement exclu
  -> continuer d'observer eBay/PSA/EXTERNAL_PENDING
  -> aucun dispatch manuel uniquement pour fabriquer une preuve

Robot KB
  -> rester séparé de V4 / V4_USE=false
  -> aucune écriture durable Cardova sans autorisation explicite

Global / Magi
  -> conserver les gates exacts et budgets bornés

V5
  -> PR #8 reste expérimentale/draft/non mergée
```

Aucun achat, bid, checkout ou paiement automatique.
