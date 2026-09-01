# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/Git/GitHub live reste l'autorité. Les SHA ci-dessous sont des **ancres runtime/capacité** ; toujours re-vérifier le HEAD `main`, les PR et les workflows live avant une action importante.

## État canonique — 1 septembre 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production branch             : main
V4 runtime production            : 6a33ac33faa324f0fc1c6124fbb49bd736382b75 (#220)
TCGdex outage resilience         : #216/#217 MERGED / runtime 03824158ac899cf142199c42d4525386a573bc15
TCGdex resilience validated code : 53a7fd0a47d100d851c347c3fadb79e4f754d07b
Robot KB configurator mode       : #219 MERGED / 2aef339135df8b4a183ad4ba030b9e603ea9e696
Future-start auction guard       : #220 MERGED / 6a33ac33faa324f0fc1c6124fbb49bd736382b75
External pending throughput      : #214 MERGED / P4 16 + eBay 16 / auctions eBay max 4
Auction order-drift hardening    : #211/#212 MERGED
Magi deterministic identity      : #174/#177 MERGED
Magi recovery budget             : #178 MERGED / recovery 36 / broad max 28
Global schedule watchdog         : #179 MERGED
Robot KB local cutover           : #166 / PostgreSQL Mac ACTIF
Robot KB multisource             : #180 MERGED
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
Robot KB durable                 : PostgreSQL local Mac / V4_USE=false
Neon                             : writers automatiques OFF / rollback manuel
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

### Preuves production récentes

```text
#216/#217 first natural prod     : run 33489103277 SUCCESS
TCGdex during that run           : 16 attempted / 0 exact / 0 no-match / 16 errors
TCGdex breaker                   : opened after 2 exhausted logical calls
scanner duration                 : 274 s vs ~397 s comparable pre-fix
EXTERNAL_PENDING                 : 2029 -> 2010
#220 first natural prod run      : run 33490823534 SUCCESS / 253 s
#220 auction discovery           : COMPLETE / 24 rows / 24 timers / 0 fallback
#220 external pending backlog    : 1998
```

Le premier run naturel post-#220 a chargé exactement `main@6a33ac33...`. Le snapshot contenait 0 enchère Pokémon 0–100 € à ≤60 min : il ne fournit donc pas encore un cas positif d'exclusion future-start, mais il confirme que le collector/timers/pagination restent cohérents et que le scan termine proprement avec les breakers provider actifs.

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

Le bootstrap résilient installe la protection TCGdex puis délègue au runner canonique.

### TCGdex outage resilience — #216/#217 EN PRODUCTION

```text
appel TCGdex logique             max 2 tentatives
retry                            Timeout / ConnectionError / HTTP 502/503/504
Main-only breaker threshold      2 appels logiques épuisés consécutifs
après ouverture                  appels réseau TCGdex restants sautés ce run
sémantique                       ERROR / fail-closed
vraie réponse provider           reset du streak
nouveau process                  circuit fermé / provider retenté
```

- 404 / vraie réponse provider : pas de retry synthétique ;
- aucune panne n'est transformée en clean no-match ;
- aucune identité, fair value, décote, notification, PokeTrace, PSA ou eBay n'a été relâchée.

Validation : runtime `53a7fd0a...`, 845 PASS / 2 skipped, compile/YAML/diff PASS, live compare superset. Première preuve naturelle : run `33489103277` SUCCESS, breaker exactement conforme, backlog `2029 -> 2010`.

## Auction discovery hardening — #211/#212

Chemin normal : `AUCTION + ON_SALE + ENDING_SOON` avec `endTime` individuel. Si l'ordre GCC dérive, récupération exhaustive **bornée** de la requête filtrée puis horizon `≤60 min` appliqué localement.

Toute erreur structurelle de requête/pagination/endTime reste fail-closed vers le fallback legacy existant.

## Future-start auction guard — #220 EN PRODUCTION

Une enchère prouvée comme n'ayant **pas encore commencé** est exclue avant interprétation du prix/countdown :

- timestamp GCC structuré + row id stable => exclusion ;
- timestamp manquant/malformé => aucune supposition ;
- preuve UI uniquement si forte (`Schedule a bid` / équivalent ou upcoming + start label explicite) ;
- starting price et countdown-to-start ne deviennent jamais bid courant / temps avant fin.

#220 se superpose au hardening #211/#212 ; il ne remplace pas la découverte actuelle.

Première preuve naturelle post-merge : run `33490823534` SUCCESS, 24 auctions découvertes / 24 timers lisibles, discovery `COMPLETE`, fallback `false`, 0 enchère éligible ≤60 min. Aucun cas future-start positif n'était présent dans ce snapshot.

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

Le drain fonctionne réellement. Les erreurs eBay/PSA/TCGdex restent des erreurs provider, jamais une preuve négative fabriquée. Sur le run post-#220 `33490823534`, le backlog `EXTERNAL_PENDING` est à `1998`.

## Fast Lane

```text
Cron-job.org toutes les 3 min
  -> .github/workflows/v4-final-auction-check.yml
  -> recheck ciblé des auctions déjà armées à ≤5 min
```

Aucun bid automatique. PSA scope économique : `8`, `8.5`, `9`, `10`; jamais de PSA 9.5 synthétique.

---

# Global Multi-Vault — production marketplace-first

```text
GCC / Fanatics / COMC / magi / Cardova
        ↓
scan inventaire courant
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

Providers validés : GCC public, Fanatics direct, COMC direct PSA10 Pokémon, Magi broad Pokémon PSA10, Cardova public anonymous read-only.

### Gate économique

Actionnable seulement si :

```text
identité exacte
+ FIXED_ASK ou AUCTION_SNAPSHOT_LE5
+ all_in_eur prouvé
+ TCGdex exact
+ externe gradé exact suffisamment fort
+ décote >= 30 %
+ aucun conflit matériel
```

- `ACTIVE_AUCTION` non actionnable ;
- externe gradé : minimum 3 ventes agrégées ;
- PPT/PokeTrace/eBay = même famille corrélée `EBAY_GRADED_AGGREGATE` ;
- conflit matériel => `MARKET_CONFLICT_BLOCKED` ;
- disparition d'annonce != SOLD.

### Scale production

```text
batch Global scheduled           50 listings/run
PPT max HTTP                     35/run
PPT max credits                  180/run
PPT daily remaining floor        15000
PokeTrace max requests           60/run
cadence                          20 min (`1,21,41`)
marketplace inner timeout        17 min
job scan timeout                 25 min
```

`.github/workflows/v4-global-notify.yml` reste l'unique lane Global production. #179 fournit le watchdog/rattrapage borné sans créer une seconde lane économique.

---

# Magi — identité native japonaise

#174 + #177 ont établi la récupération déterministe ; #178 protège le budget sans augmenter le plafond :

```text
recovery total max               36
broad/nonpriority max            28
exact card-search/detail reserve 8
```

Le baseline prouvé était 31/96 EXACT ; le run #178 a donné 30/96 avec 55 listings déjà SOLD et 0 `TCGDEX_BUDGET_EXHAUSTED`.

Restent volontairement bloqués tant qu'aucune preuve déterministe suffisante n'existe : Lugia GR団参上 old-back promo, Misty's Horsea old-back No.116, Pokémon Pal City 2007, Rayquaza VMAX Dragon Pokémon Get Challenge promo, Scizor Championship Series 2025 promo.

**Pas de treadmill d'alias carte-par-carte.**

---

# TCGdex — identité et microvariantes

La lignée #119→#135 reste l'autorité de récupération exacte : coordinate, aliases de set prouvés, unicité catalogue et fallback source-pinné immuable.

`variants_detailed` peut prouver après identité exacte :

- normal / holo / reverse ;
- First Edition / Unlimited / Shadowless quand explicitement prouvés ;
- Poké Ball / Master Ball / Cosmos / Galaxy / Cracked Ice ;
- langue exacte.

Axes inconnus, multiples, malformés ou contradictoires => blocage. Le `pricing` / `thirdParty` TCGdex n'est pas une fair value slab.

---

# Robot KB — PostgreSQL local Mac

Robot KB reste séparé de la décision commerciale V4/Global. `V4_USE=false`.

## Contrat historique

- observations append-only, datées, immuables ;
- payload brut + provenance ;
- priorité aux ventes finales `SOLD` prouvées ;
- fixed : baseline puis changements utiles ;
- auctions : SOLD final prioritaire ; snapshot `≤5 min` seulement fallback identifié ;
- disparition/ASK/live auction/`WAITING_FOR_PAYMENT` != SOLD ;
- objectif : courbes 30j/90j/1an/multi-années, liquidité, tendance, calibration.

Migration Neon → Mac vérifiée : 1,087,015 lignes, 35 tables, `MIGRATION_VERIFIED`, health OK. Writers Neon automatiques retirés ; Neon = rollback/recovery manuel.

## #180 — multisource local

Code mergé pour Fanatics/COMC/Magi/Cardova publics + PokeTrace + PokemonPriceTracker, avec provenance/payload/date et sémantique stricte :

- `SOLD_AGGREGATED` != item-level SOLD ;
- `cardmarket_unsold` = `FIXED_ASK_AGGREGATED` ;
- ASK reste ASK ;
- clés PokeTrace/PPT uniquement dans le Trousseau macOS.

## #207 — P3 uniquement

PR #207 est mergée **dans `agent/p3-postgres-durable-shadow` uniquement**, merge `df32a19c...`.

Elle étend l'axe `print_run` avec `NO_RARITY_SYMBOL` / `RARITY_SYMBOL_PRESENT` sans implication First Edition/Unlimited. **Aucune migration PostgreSQL durable utilisateur n'a été exécutée.**

## #219 — configurateur API

Mode Git du script `Configurer APIs Robot KB.command` corrigé en exécutable (`100755`) sur `main`; contenu inchangé.

## Cardova durable

Le stack #199/#204–#210 reste séparé. #210 prépare un commit durable gardé par double autorisation/backup/locks, mais **aucune exécution durable n'est autorisée par défaut**.

---

# V5 — EXPÉRIMENTALE

```text
PR #8        OPEN / DRAFT / NON MERGED
branch       agent/v5-poketrace-cardmarket-market-data
head         bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

TCGdex reste le resolver normal V5 ; PokeTrace sert au marché/prix après identité. Les chemins emergency restent strictement séparés et fail-closed.

**Ne jamais merger PR #8 dans `main` sans autorisation explicite.**

---

# Gouvernance avant changement important

1. lire entièrement ce README ;
2. lire `.agents/rules/gcc-project-governance.md` ;
3. lire `AGENTS.md` s'il existe ;
4. lire capability ledger + inventaires pertinents ;
5. vérifier local Git réel si le worktree est accessible ;
6. vérifier `main`, SHA, PRs, branches et workflows live ;
7. chercher une capacité existante avant de réimplémenter ;
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
  -> continuer d'observer les snapshots auction jusqu'au premier cas future-start réellement exclu
  -> continuer d'observer TCGdex/eBay/PSA et EXTERNAL_PENDING
  -> ne pas augmenter les caps uniquement pour forcer le drainage

Robot KB
  -> rester séparé de V4 / V4_USE=false
  -> aucune migration/écriture durable Cardova sans autorisation explicite
  -> conserver priorité SOLD exact final et observations immuables

Global / Magi
  -> garder le plafond recovery 36 / broad 28
  -> pas d'alias carte-par-carte pour les cas bloqués

V5
  -> PR #8 reste expérimentale/draft/non mergée
  -> aucun merge ou live non autorisé
```

Aucun achat, bid, checkout ou paiement automatique.
