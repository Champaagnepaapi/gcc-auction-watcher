# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/Git/GitHub live reste l'autorité. Ce README décrit l'état fonctionnel courant ; les détails historiques et de gouvernance sont dans `docs/`.

## État canonique — 24 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production canonique          : main @ 950694d66b04112fc1182f0b21d6008bb4560204
V4 eBay hard-hang isolation      : PR #175 / MERGED / 950694d66b04112fc1182f0b21d6008bb4560204
Magi native identity             : PR #173 / MERGED / b5ddc393850303e7ca542ae68e4ed4d1145340d3
Magi coverage hardening          : PR #174 / OPEN / DRAFT / NON MERGED
Robot KB cutover runtime         : PR #166 / 611edf469dfe5e5bfc46390ba6680b9c2ebe9fee
Global scale production          : PR #156 / f43e7f5aa01bd84ee3a575232ca966bf2ab01d19
Cardova public read-only         : PR #168 / 48caf402e851e2d888999ba94f93a9355f14d7bb
Global schedule recovery         : PR #169 / 81db5cf2ffc788a517c9cb63d36cfd1f88c347a6
Global cadence                   : toutes les 20 min / workflow unique
Global schedule run registry     : issue #150 / finalizer séparé fail-visible
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
Robot KB durable                 : PostgreSQL local Mac ACTIF
Neon                             : writers automatiques RETIRÉS ; rollback manuel conservé
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Toujours re-vérifier le HEAD `main`, les PR et les workflows live avant une action importante.

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

Bootstrap : tout l'inventaire découvert entre dans la file. Ensuite : nouvelles annonces, changements économiques utiles et retryables. Une disparition reste `missing`, **jamais SOLD**.

Providers validés :

```text
GCC       public /on-sale-items                  OK
Fanatics  direct marketplace browse              OK
COMC      direct PSA10 Pokemon inventory sweep   OK
magi      broad Pokemon PSA10 inventory query    OK
Cardova   public anonymous read-only inventory   OK
```

Cardova n'utilise **aucun login/cookie/session** dans GitHub Actions : seules les réponses JSON publiques GET utiles sont capturées et sanitizées. Aucun token ou donnée de compte n'est conservé.

## Gate économique

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
- conflit GCC/externe matériel => `MARKET_CONFLICT_BLOCKED` ;
- avec GCC fair : fair confirmé = `min(GCC fair, external fair)` ;
- sans GCC fair exact : `EXTERNAL_ONLY` possible si externe exact/fort.

## Scale production — PR #156

PR #156 est mergée en production.

```text
batch Global scheduled           50 listings/run
PPT max HTTP                     35/run
PPT max credits                  180/run
PPT daily remaining floor        15000
PokeTrace max requests           60/run
```

Preuve production observée : run `32467460797`, success, 50 selected/acknowledged, 27 identités commerciales, TCGdex exact 23, 7 conflits, 18 sans confirmation externe, 0 notification, `transactions=false`.

## Cardova + récupération schedule — PR #168/#169

PR #168 a activé la lecture Cardova publique anonyme en read-only, sans session persistante ni secret. PR #169 a corrigé l'exploitation du schedule Global après observation de runs dépassant la cadence historique de 10 min :

```text
cadence Global                   20 min (`1,21,41`)
batch                            50 listings/run
marketplace inner timeout        17 min
job scan timeout                 25 min
cache state                      sauvegardé seulement après scan success
registre #150                    job séparé `register` + `always()`
```

Validation PR #169 : run `32567032852`, **240/240 Global + 51/51 V4 PASS**, compile/YAML/diff-check PASS, live marketplace read-only PASS et safety contract PASS. Aucune modification de l'identité, de l'économie ou des fournisseurs n'a été faite par #169.

## Magi native identity — PR #173

PR #173 est mergée. Magi n'est plus dépendant d'une projection latine lorsque l'identité japonaise TCGdex est déjà prouvée exactement.

- preuve japonaise TCGdex exacte obligatoire ;
- nom japonais exact présent dans le contenu produit ;
- set/localId/dénominateur compatibles ;
- source TCGdex japonaise immuable prioritaire pour les promos `S-P` ;
- absence propre d'alias latin peut retomber sur une identité commerciale japonaise native ;
- aucune traduction/fuzzy ; erreurs provider/budget restent bloquantes ;
- ASK Magi reste ASK, jamais SOLD.

Preuve production post-merge : run `32634964197` sur `b5ddc393850303e7ca542ae68e4ed4d1145340d3`, SUCCESS, Magi **9 exact**, sécurité verte, aucune transaction.

PR #174 poursuit séparément la récupération déterministe des annonces Magi encore sous-spécifiées. Elle reste **OPEN / DRAFT / NON MERGED** ; aucune identité incertaine ne doit être forcée pour augmenter la couverture.

---

# TCGdex — identité et microvariantes

La lignée #119→#135 reste l'autorité de récupération exacte : coordinate, aliases de set prouvés, unicité catalogue et fallback source-pinné immuable.

`variants_detailed` est exploité après identité TCGdex exacte comme preuve commerciale déterministe :

- normal / holo / reverse ;
- First Edition / Unlimited / Shadowless quand explicitement prouvés ;
- Poké Ball / Master Ball / Cosmos / Galaxy / Cracked Ice ;
- langue exacte ;
- axes inconnus, multiples, malformés ou contradictoires => blocage fail-closed.

Une entrée affirmant deux valeurs incompatibles sur le même axe ne devient jamais un comparable exact. Le `pricing` / `thirdParty` de TCGdex n'est pas utilisé pour valoriser un slab.

PR #159 reste une correction TCGdex séparée et **non mergée** ; la re-vérifier contre le `main` courant avant toute décision.

---

# V4 — production canonique

## Main Scanner

```text
Cron-job.org ~toutes les 10 min
  -> workflow_dispatch
  -> .github/workflows/watcher.yml
  -> run_watcher_multimarket.py
```

Le workflow V4 utilise :

```text
concurrency.group        gcc-auction-watcher
cancel-in-progress       false
```

Donc un run V4 bloqué peut faire attendre les runs suivants de **la même lane V4**, sans bloquer les workflows indépendants.

## Incident eBay hard hang — PR #175

Deux runs V4 production (`32664106071`, `32682740195`) sont restés bloqués environ 6 h. Le dernier événement scanner était une requête eBay : `page.goto(... timeout=10000)` n'a ni retourné ni levé `TimeoutError`, ce qui indiquait un blocage du RPC Playwright/driver, pas un simple timeout navigation.

PR #175 est mergée sur `main` au SHA **`950694d66b04112fc1182f0b21d6008bb4560204`**.

Correctif :

- chaque scrape eBay SOLD est isolé dans un sous-processus/browser jetable ;
- deadline dure bornée à 30 s par défaut ;
- en cas de hang, kill du groupe de processus ;
- retour `PROVIDER_ERROR` fail-closed puis V4 continue ;
- credentials inutiles retirés de l'environnement enfant ;
- aucun changement du matching, de la fair value, des seuils notification ou des règles commerciales.

Validation pré-merge : **771 tests PASS**, compile/YAML/live comparison read-only PASS.

Preuve production post-merge sur le SHA #175 :

```text
32738091183   SUCCESS   578 s
32739149539   SUCCESS   464 s
32740157203   SUCCESS   496 s
32741180104   SUCCESS   598 s
32742259467   SUCCESS   129 s
```

Le mode de panne de 6 h n'est plus observé sur ces runs. Continuer à surveiller la lane V4 lors des périodes d'enchères denses, notamment le dimanche.

## Fast Lane

```text
Cron-job.org toutes les 3 min
  -> .github/workflows/v4-final-auction-check.yml
  -> recheck ciblé des auctions déjà armées à ≤5 min
```

Ne jamais ajouter de cron GitHub parallèle à ces lanes.

PSA scope économique : `8`, `8.5`, `9`, `10`. PSA <8 hors scope ; jamais de PSA 9.5 synthétique.

---

# Robot KB — PostgreSQL local Mac ACTIF

Robot KB reste séparé de la décision commerciale V4/Global. `V4_USE=false` tant que l'activation économique KB-first n'est pas explicitement décidée et suffisamment prouvée.

## Contrat historique

- observations append-only, datées, immuables ;
- payload brut + provenance ;
- priorité aux ventes finales `SOLD` prouvées ;
- fixed : baseline puis changements utiles ;
- auctions : SOLD final prioritaire ; snapshot `≤5 min` seulement fallback identifié ;
- disparition/ask/live auction ne devient jamais vente ;
- `WAITING_FOR_PAYMENT` n'est **jamais** un SOLD ;
- objectif : courbes 30j/90j/1an/multi-années, liquidité, tendance, calibration.

## Migration Neon → Mac : vérifiée

Migration réelle terminée et prouvée :

```text
lignes source/local identiques   1,087,015
nombre de tables                 35
marker                           MIGRATION_VERIFIED
PostgreSQL                       health OK
schema versions                  [1, 2]
```

La migration ne doit pas être relancée sur une base déjà vérifiée.

## Collecte locale active

Cible : PostgreSQL local sur le Mac mini, loopback uniquement.

```text
database                         robot_pokemon_kb
user                             robotpokemon_kb
host                             127.0.0.1
runtime P3 validé                1d06fe33b6fc640657255e15a8d17251aa02b6ce
fixed + auctions                 LaunchAgent à :32
SOLD fresh + backfill            LaunchAgent à :17 et :47
backup                           LaunchAgent quotidien 03:10
backups conservés                7 dumps complets locaux
```

Dernier run local de preuve avant cutover cloud :

```text
fixed observations acceptées     494
fresh SOLD nouveaux              6
historical SOLD backfill         400
fresh WAITING_FOR_PAYMENT         102 différés
historical WAITING_FOR_PAYMENT    209 différés
strict_sales                     546
exact_tiers                      427
kb_first_ready                   27
grader_spreads                   0
health                           OK
transactions                     false
```

Le backfill historique était encore `complete=false` : il continue automatiquement via la lane locale, sans bloquer l'exploitation des données déjà présentes.

## Viewer local

Après `Pull origin`, double-clic :

```text
mac/robot-kb-local/Ouvrir Robot KB.command
```

Le viewer est **read-only**, lié à `127.0.0.1`, et permet de parcourir/rechercher les données sans exposer le mot de passe PostgreSQL.

## Cutover Neon — PR #166

PR #166 a retiré les **writers automatiques Neon** après preuve complète de la collecte locale :

- `robot-kb-cloud-shadow.yml` : plus de cron ; manual-only ;
- `robot-kb-sold-shadow.yml` : plus de cron ; manual-only ;
- `v4-kb-shadow-ingest.yml` : plus de `workflow_run` automatique ; replay manuel avec `source_run_id` explicite.

Le projet Neon et son secret ne sont **pas supprimés**. Ils restent disponibles comme rollback/recovery manuel borné. Ne pas réactiver les writers automatiques sans raison et validation explicites.

---

# V5 — EXPÉRIMENTALE

```text
PR #8        OPEN / DRAFT / NON MERGED
branch       agent/v5-poketrace-cardmarket-market-data
head         bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

**Ne jamais merger PR #8 dans `main` sans autorisation explicite.**

---

# Workflows / séparation des responsabilités

À retenir :

- Main Scanner et Fast Lane : cadence externe ;
- Global : workflow schedule unique toutes les 20 min ;
- Robot KB production : **LaunchAgents locaux Mac** ;
- anciens workflows Neon Robot KB : **manual-only rollback/recovery** ;
- `robot-kb-local-postgres-validation.yml` : validation CI/manual de la lane Mac ;
- V5 lives : manuels/expérimentaux uniquement.

Voir `docs/project-workflow-inventory.md` et toujours comparer avec le tree Git courant si l'inventaire documentaire est plus ancien.

---

# Gouvernance avant changement important

1. lire entièrement ce README ;
2. lire `.agents/rules/gcc-project-governance.md` ;
3. lire `AGENTS.md` s'il existe ;
4. lire capability ledger + inventaires pertinents ;
5. vérifier `main`, SHA, PRs, branches et workflows live ;
6. chercher une capacité existante avant de réimplémenter ;
7. branche/PR dédiée ;
8. SHA précis ;
9. tests ciblés + suite pertinente ;
10. compile/YAML/`git diff --check` ;
11. live read-only lorsque pertinent ;
12. aucune transaction/secret ;
13. merge seulement avec l'autorisation requise ;
14. mettre à jour le handoff documentaire après une phase importante.

Documents de reprise :

- `docs/project-current-phase.md`
- `docs/project-capability-ledger.md`
- `docs/project-open-pr-inventory.md`
- `docs/project-branch-inventory.md`
- `docs/project-workflow-inventory.md`
- `docs/project-issue-inventory.md`
- `docs/project-repository-snapshot.md`
- `docs/robot-kb-local-cutover-close-20260821.md`

---

# Prochaine direction canonique

```text
V4
  -> incident eBay #175 corrigé et prouvé en production
  -> surveiller les runs, surtout lors des enchères dominicales
  -> ne jamais laisser un provider externe immobiliser la lane entière

Global / Magi
  -> reprendre PR #174 depuis le main courant post-#175
  -> continuer uniquement les récupérations d'identité déterministes
  -> maintenir les ambiguïtés / variantes sensibles fail-closed

Robot KB
  -> laisser le backfill local continuer
  -> surveiller health/logs/backups locaux
  -> accumuler davantage de SOLD exacts et de tiers exacts
  -> intégrer PPT/PokeTrace à la KB dans une phase séparée si utile
  -> ne pas activer KB-first économiquement sans profondeur/preuve suffisante

TCGdex
  -> traiter PR #159 séparément après rebase/revalidation si souhaité
  -> ne jamais fabriquer une microvariante

Neon
  -> conserver comme rollback manuel pour l'instant
  -> ne pas supprimer le projet tant qu'une période d'observation locale n'est pas terminée
```

Aucun achat, bid, checkout ou paiement automatique.
