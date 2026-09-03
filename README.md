# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/Git/GitHub live reste l'autorité. Les SHA ci-dessous sont des ancres runtime/capacité ; toujours re-vérifier `main`, les PR et les workflows live avant une action importante.

## État canonique — 3 septembre 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production branch             : main
V4 runtime production            : 3ada7785d3fbef8050a7712bc773a52fd569716d (#243)
eBay worker bulk text            : #238/#239 MERGED / validated head 90741ac0eaca42f90a6bc7fca816d347aaccafeb
eBay result before teardown      : #242 MERGED / validated head 7c97d73a9caf93871d918a8dabc5a7be72375697 / merge 0410160d62492682027ed6d80036daa4cf133777
V4 run registry                  : issue #235 ACTIVE / issue #1 archive saturée / #237 MERGED
Auction recovery capacity        : #229/#231 MERGED / b6a7c834264c062ea81b64c714e6916aa8bfe9f2
Auction order-drift hardening    : #211/#212 MERGED
Future-start auction guard       : #220 + #243 MERGED / validated head 20e1a12e35464840952cdb9079e6063f014e3bef
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

### Validation du runtime eBay #238/#239

```text
validated head                   : 90741ac0eaca42f90a6bc7fca816d347aaccafeb
validation run                   : 33650958804 SUCCESS
V4 complete suite                : 875 PASS / 2 skipped
compile / YAML / diff-check      : PASS
read-only live auction compare   : PASS
comparison effective / legacy    : 80 / 80
legacy_only / unresolved         : 0 / 0
production merge                 : 0cab2f3868e80c7c0ed9e6829e44123a2ecd3005
Fast Lane post-merge             : 33741652374 SUCCESS
Main Scanner post-merge          : 33741995589 SUCCESS / natural external scheduler
scan total / registry duration   : 173.68 s / 175 s
eBay post-merge                  : 12 attempted / 2 insufficient / 10 unavailable / 10 errors
hard-timeout class               : PERSISTS / 2 × 30 s then run breaker
external pending backlog         : 1970
```

Le toggle GitHub `Ready for review` de #238 a de nouveau échoué sur le bug GraphQL `fullDatabaseId`. #239 a donc servi de miroir non-draft **sur le même head exact**. GitHub marque #238/#239 comme mergées vers le même merge production.

La première preuve naturelle post-merge montre que le bulk text est **non-régressif mais insuffisant pour supprimer le problème dominant eBay** : deux hard timeouts de 30 s persistent puis le breaker s'ouvre. La durée totale a baissé sur ce run, mais le panel/queue diffère ; **ne pas attribuer cette baisse à #239** sans preuve contrôlée supplémentaire.

### Validation du guard future-start #243

Incident naturel reproduit le 3 septembre 2026 : Braixen #069/068 PSA 9 et Altaria #194/172 PSA 10 ont été notifiées comme `GCC AUCTION — EXTERNAL RESCUE` à 10 € avec `Fin : ~45 min`, alors que GCC affichait en réalité le **prix de départ** et le compte à rebours **jusqu'au début** de l'enchère.

La cause exacte était un bypass Main Scanner : les rows API déjà munies de `minutes_to_end` ne passaient pas par le fallback `inspect_item`, donc le guard rendu de #220 n'était jamais consulté.

```text
validated head                   : 20e1a12e35464840952cdb9079e6063f014e3bef
validation run                   : 33794118816 SUCCESS
V4 complete suite                : 896 PASS / 2 skipped
compile / YAML / diff-check      : PASS
read-only live auction compare   : PASS
effective / legacy               : 73 / 71
legacy_only / unresolved         : 0 / 0
production merge                 : 3ada7785d3fbef8050a7712bc773a52fd569716d
```

#243 ajoute une vérification de l'état rendu **avant toute économie** pour les auctions avec timer mais sans preuve structurée qu'elles ont déjà commencé. `Enchères à venir` / `Programmer une enchère` => exclusion ; page ambiguë ou erreur => fail-closed ; une vraie enchère live exige une sémantique d'action de bid + fin explicite. Aucun heuristique `10 €`, `0 enchère`, etc. n'est utilisé comme preuve d'état.

### Registre V4 #235

Issue #1 a dépassé la limite GitHub de 2500 commentaires et faisait échouer uniquement l'étape d'archivage après un scan réussi. #237 a déplacé le registre actif vers **issue #235** sans changer le scanner.

Preuve naturelle : run `33741053547` SUCCESS sur `9fac4bd5...`; étape `Register V4 run in issue #235` SUCCESS ; commentaire #235 écrit avec `scan_exit_code=0`, discovery auctions `COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS`, `24/24` timers et `fallback=false`. Le premier run post-#239 `33741995589` s'est également enregistré avec succès dans #235.

Issue #1 reste l'archive historique ; ne pas la supprimer/réécrire.

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

Le Main Scanner est cadencé extérieurement. **Ne jamais ajouter un cron GitHub parallèle.** Son registre actif est désormais l'issue #235 ; l'issue #1 est archive historique.

## eBay exact SOLD — worker isolé + bulk text #238/#239

Le provider eBay public reste dans le worker enfant déjà isolé par hard timeout. Les runs naturels pré-fix continuaient à montrer des hard timeouts de 30 s et ouverture du breaker.

#238/#239 change uniquement l'extraction DOM des lignes de résultats :

```text
li.s-item visible text            une lecture bulk all_inner_texts()
fallback                          nth(i).inner_text() historique si bulk échoue/partiel/non-list
worker isolation                  inchangée
hard timeout / breaker            inchangés
queries / SOLD parsing            inchangés
identity / grade / language       inchangés
fair value / budgets / ntfy       inchangés
```

La validation CI prouve l'équivalence contractuelle et la non-régression. Le benchmark public #234 était inconclusif car le runner n'a vu aucun `li.s-item`.

### Premier live naturel post-#239

Run `33741995589`, exact `main@0cab2f3868e8...` :

```text
workflow                         SUCCESS
total_seconds                    173.68
registry duration                175 s
eBay attempted                   12
eBay sufficient                  0
eBay insufficient                2
eBay unavailable / errors        10 / 10
hard timeouts                    2 × 30 s
breaker                          OPEN après les 2 hard timeouts
external pending backlog         1970
fixed discovery                  3268 / 33 pages / COMPLETE
auction discovery                24 rows / 24 timers / COMPLETE / fallback=false
```

Conclusion : **la classe de panne hard-timeout persiste**. #239 peut réduire l'IPC lorsque des rows DOM sont effectivement exploitables, mais ce premier live ne prouve pas que l'IPC était la cause dominante. La baisse de durée vs certaines baselines est confondue par un panel externe différent ; ne pas la créditer au patch.

Prochaine investigation eBay : instrumenter de façon bornée/read-only les étapes du worker isolé (navigation, présence/challenge/row count, bulk extraction, parsing) pour localiser les 30 s, sans changer matching/SOLD/économie et sans contournement anti-bot.

## Auction discovery — #211/#212 + #229/#231

Chemin normal : `AUCTION + ON_SALE + ENDING_SOON` avec `endTime` individuel.

- ordre GCC valide : fast path inchangé ;
- dérive d'ordre prouvée : récupération exhaustive bornée de la requête filtrée puis horizon appliqué localement ;
- erreurs de requête/pagination/endTime/repeated-page/no-progress restent fail-closed vers le fallback legacy existant.

### Capacity hardening #229/#231

Le marché `AUCTION + ON_SALE` a dépassé l'ancienne capacité de récupération de 100 pages. Le recovery adapte uniquement son budget après dérive d'ordre :

```text
budget = ceil(api_total / page_size) + 2
minimum = ancien bound
hard ceiling = 250 pages
```

`api_total` est **uniquement un indice de capacité**. Il ne prouve jamais la complétude. Le statut `COMPLETE` exige toujours l'épuisement réel de l'API (`nextPage` absent).

Aucun changement : cap économique auctions `360`, priorité `≤5 min` puis `≤12 min` puis `≤60 min`, fair value, identité, providers, notifications ou transactions.

## Future-start auction guard — #220 + #243

Une enchère prouvée comme n'ayant pas encore commencé est exclue avant interprétation du prix/countdown :

- `startTime > observed_at` avec row id stable => exclusion structurée ;
- `startTime <= observed_at` => démarrage structuré prouvé, chemin live normal conservé ;
- timestamp manquant/malformé => aucune supposition ;
- si l'API fournit déjà un timer mais ne prouve pas le démarrage, #243 vérifie la fiche GCC rendue **avant toute valorisation** ;
- `Enchères à venir` / `Programmer une enchère` ou upcoming + start label explicite => exclusion ;
- vraie enchère live rendue => action de bid + sémantique explicite de fin ;
- page ambiguë / erreur de vérification => fail-closed ;
- starting price et countdown-to-start ne deviennent jamais bid courant / temps avant fin.

Le guard se superpose au hardening de discovery ; il ne le remplace pas. #243 ferme explicitement le bypass observé sur Braixen/Altaria où un timer API évitait auparavant `inspect_item`. Fast Lane reste protégée par le guard rendu. Aucun changement de fair value, discount, prix max, identité, providers ou transaction.

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

Baseline immédiatement pré-#239 : run `33741053547`, backlog `EXTERNAL_PENDING=1976`, eBay `attempted=16 / insufficient=7 / unavailable=9 / errors=9`; plusieurs hard timeouts de 30 s puis breaker. Cette baseline est **pré-fix** car le run avait démarré sur `9fac4bd5...` avant le merge #239.

Premier run post-#239 `33741995589` : backlog `1970`; eBay `attempted=12 / insufficient=2 / unavailable=10 / errors=10`; exactement deux hard timeouts de 30 s puis breaker. Le backlog continue à drainer lentement, mais la disponibilité eBay reste le bottleneck.

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
  -> #243 est mergé : le bypass timer API des enchères non démarrées est fermé
  -> observer les prochains scans naturels pour confirmer absence de faux `EXTERNAL RESCUE` pre-start
  -> #242 conserve les résultats eBay validés avant teardown, mais continuer d'observer le provider
  -> ne pas augmenter les caps et ne pas contourner anti-bot/WAF
  -> continuer d'observer PSA/EXTERNAL_PENDING
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