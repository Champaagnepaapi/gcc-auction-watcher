# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/Git/GitHub live reste l'autorité. Ce README décrit l'état fonctionnel courant ; les détails historiques et de gouvernance sont dans `docs/`.

## État canonique — 26 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production canonique          : main @ 9365f5cd9f8949580c4e48f00ba8c4e419c22145 (runtime merge #180)
Magi coverage production         : PR #174 + #177 MERGED
Magi production proof            : run 32893130902 SUCCESS / 31 EXACT sur 96
Magi budget fix                  : PR #178 MERGED / 545223613ce21e6c4cf886e07201bc3c105a5e69
Magi #178 read-only proof        : run 32943536626 SUCCESS / 30 EXACT + 55 SOLD / 0 budget-exhausted
Global schedule watchdog         : PR #179 MERGED / ac5f7c734685422612a0f24690af22910eefa951
Robot KB cutover runtime         : PR #166 / 611edf469dfe5e5bfc46390ba6680b9c2ebe9fee
Robot KB multisource runtime     : PR #180 MERGED / 9365f5cd9f8949580c4e48f00ba8c4e419c22145
Robot KB multisource Mac install : PENDING — repo prêt, installateur à exécuter sur le Mac
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

Toujours re-vérifier le HEAD `main`, les PR et les workflows live avant une action importante. Un commit docs-only peut suivre le dernier SHA runtime ; distinguer les deux dans le handoff.

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

## Scale production

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

Le workflow Global production reste unique : `.github/workflows/v4-global-notify.yml`. PR #179 ajoute un watchdog/rattrapage borné depuis le heartbeat Main Scanner pour les schedules GitHub manqués, sans seconde lane économique.

---

# Magi — identité native japonaise en production

## PR #173 + #174

PR #174 a été mergée dans `main` le 25 août 2026 :

```text
feature head                     593c417ec526aba39f7d388bb3a61d868650c15a
merge main                       3d1589e0086c264e9f910a15fb6b037e20938970
premier schedule production      32893130902
résultat                         SUCCESS
Magi candidates                  96
Magi EXACT                       31
TCGdex recovery budget           36 max/run
notifications envoyées           0
transactions                     false
```

Le premier vrai schedule post-merge a chargé exactement `main@3d1589e...`, activation Global `true`, puis terminé avec les jobs `scan` et `register` en succès.

Couverture Magi observée dans ce run :

```text
31 EXACT / 96
54 sold_listing filtrés
5 japanese_set_name_unproven
4 target_catalog_unproven:TCGDEX_NO_CARD_FOR_FULL_NUMBER
2 target_japanese_card_name_unproven
```

Recovery TCGdex :

```text
requests total                   36
card_detail                      4
card_search                      4
set_coordinate                  19
set_detail                       1
sets_catalog                     1
sets_filtered                    7
```

Le plafond n'a pas été augmenté pour gagner la couverture.

## PR #177 — Battle Partners en production

PR #177 a été mergée le 25 août 2026 :

```text
feature head                     def78bfefff01ddb6690e9a21616ae65d0eb14c8
merge main                       2114b20077605a96a3cf3211f225e1e774bbe9ea
preuve                           Battle Partners = SV9 / 100
```

La correction reste une revalidation TCGdex exacte ; aucune identité n'est créée par fuzzy ou traduction supposée.

## PR #178 — correction de saturation du budget recovery — EN PRODUCTION

Après #177, les workflows nocturnes sont restés techniquement SUCCESS, mais Magi a parfois chuté jusqu'à **28/96 EXACT** avec `TCGDEX_BUDGET_EXHAUSTED`. Le problème venait de l'allocation des 36 appels recovery, pas du plafond lui-même.

PR #178 garde donc **36 appels max/run** et sépare le budget par classe :

```text
recovery total max               36
broad/nonpriority max            28
exact card-search/detail reserve  8
merge main                       545223613ce21e6c4cf886e07201bc3c105a5e69
```

Les requêtes larges `sets/*` ne peuvent plus consommer les appels nécessaires aux paires strictes `card_search -> card_detail`. La limite broad est comptée indépendamment de l'ordre des listings ; le plafond global de 36 reste inchangé.

Validation #178 :

```text
branch                            fix/v4-global-magi-recovery-priority-20260826
validated head                    8fd51c34dd2550b4748dc790e17b74af8612b975
base main                         2114b20077605a96a3cf3211f225e1e774bbe9ea
CI/live run                       32943536626 SUCCESS
focused Global tests              409/409 PASS
V4 multimarket tests              51/51 PASS
compile/YAML/diff-check           PASS
```

Live read-only :

```text
Magi candidates                   96
Magi EXACT                        30
sold_listing                      55
japanese_set_name_unproven        5
target_catalog_unproven           4
target_japanese_card_name         2
TCGdex recovery requests          36
nonpriority recovery              28
card_search                       4
card_detail                       4
set_coordinate                   19
set_detail                        1
sets_catalog                      1
sets_filtered                     7
TCGDEX_BUDGET_EXHAUSTED           0
notifications sent                0
identity gate relaxed             false
transactions                      false
```

Le `30/96` ne représente pas une perte d'identité par rapport au baseline `31/96` : `sold_listing` est passé de **54 à 55**, tandis que les rejets non-SOLD restent exactement `4 + 5 + 2 = 11`. La saturation évitable est donc supprimée sans augmenter 36 et sans relâcher l'identité.

## Classes déterministes ajoutées

#174 n'ajoute pas un resolver fuzzy. Les chemins récupérés restent bornés et revalidés :

- full collector number globalement unique ;
- détail Magi retry borné ;
- coordinate/set exact avec cache recovery ;
- exact Japanese name + reviewed rarity + unicité puis revalidation card-detail ;
- preuves source-pinnées pour certaines classes standard/sensibles lorsque l'identité commerciale est déterministe ;
- priorité du budget recovery pour éviter qu'un travail redondant consomme la preuve finale d'une identité utile.

Exemples validés pendant la phase :

- `かんこうきゃく TR` : `TR` est traité comme le token commercial revu correspondant au `Rare Holo` TCGdex uniquement dans la lane exact-name + rarity + unicité + detail revalidation ;
- Solgaleo & Lunala GX SR : récupéré sans augmenter le plafond recovery.

## Ce qui reste volontairement bloqué

Les cinq classes `japanese_set_name_unproven` restent bloquées tant qu'une preuve déterministe suffisante n'existe pas :

- Lugia `GR団参上！` old-back promo ;
- Misty's Horsea / `カスミのタッツー` old-back No.116 ;
- Pokémon Pal City Battle Road Summer 2007 ;
- Rayquaza VMAX Dragon Pokémon Get Challenge promo ;
- Scizor Championship Series 2025 promo.

Ne pas ajouter un fallback name-only ou un treadmill d'alias carte-par-carte pour forcer ces cinq cas.

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

PR #159 est superseded fonctionnellement par #177 déjà mergée ; elle reste historique/provenance et ne doit pas être rejouée telle quelle.

---

# V4 — production canonique

## Main Scanner

```text
Cron-job.org ~toutes les 10 min
  -> workflow_dispatch
  -> .github/workflows/watcher.yml
  -> run_watcher_multimarket.py
```

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

Migration Neon → Mac vérifiée :

```text
lignes source/local identiques   1,087,015
nombre de tables                 35
marker                           MIGRATION_VERIFIED
PostgreSQL                       health OK
schema versions                  [1, 2]
```

Collecte locale historique déjà active :

```text
database                         robot_pokemon_kb
host                             127.0.0.1
runtime P3 validé                1d06fe33b6fc640657255e15a8d17251aa02b6ce
fixed + auctions                 LaunchAgent à :32
SOLD fresh + backfill            LaunchAgent à :17 et :47
backup                           LaunchAgent quotidien 03:10
backups conservés                7 dumps complets locaux
```

PR #166 a retiré les writers automatiques Neon. Le projet Neon reste disponible uniquement comme rollback/recovery manuel borné.

## PR #180 — harvest multisource local, code mergé

PR #180 est mergée dans `main` :

```text
feature head                     4194730490efbf879188069de4cc4d17642aad46
merge main                       9365f5cd9f8949580c4e48f00ba8c4e419c22145
Robot KB CI                      run 32999776457 SUCCESS
V4 validation                    run 32999776492 SUCCESS
Mac physical install             PENDING
```

La nouvelle lane ajoute, sans modifier le gate économique V4/Global :

- Fanatics, COMC, Magi et Cardova publics : baseline puis changements matériels ;
- PokeTrace : marchés US/EU, Pokémon EN/JP, **single cards uniquement**, prix courants + historique `period=all`, priorité PSA 10/9/8/8.5 ;
- PokemonPriceTracker : sets EN/JP, historique 180 jours, eBay gradé agrégé + métriques CardMarket/TCGplayer ;
- provenance, payload brut et `observed_at` conservés dans Robot KB ;
- `SOLD_AGGREGATED` reste agrégé et ne devient jamais un item-level SOLD ;
- `cardmarket_unsold` reste `FIXED_ASK_AGGREGATED` ; ASK reste ASK.

Après exécution de l'installateur #180 sur le Mac :

```text
public multi-vault               LaunchAgent toutes les 2 h à :05
PokeTrace + PPT                  LaunchAgent 01:08 / 07:08 / 13:08 / 19:08
PPT remaining reserve            15000
PokeTrace remaining reserve      5000
paid runtime max                 1800 s/run
```

Les clés PokeTrace/PPT doivent rester **uniquement dans le Trousseau macOS**. Elles ne doivent apparaître ni dans Git, ni dans les plist, ni dans les states/logs. Le harvest provider utilise un lock séparé du collector GCC pour ne pas bloquer fixed/SOLD.

**Important : le merge #180 rend le code/installateur disponible sur `main`, mais ne prouve pas encore que les nouveaux LaunchAgents ont été installés et chargés sur le Mac.** Cette vérification doit être faite après exécution réelle de l'installateur sur la machine.

---

# V5 — EXPÉRIMENTALE

```text
PR #8        OPEN / DRAFT / NON MERGED
branch       agent/v5-poketrace-cardmarket-market-data
head         bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

TCGdex reste le resolver normal V5 ; PokeTrace sert au marché/prix après identité.

**Ne jamais merger PR #8 dans `main` sans autorisation explicite.**

---

# Workflows / séparation des responsabilités

- Main Scanner et Fast Lane : cadence externe ;
- Global : workflow schedule unique toutes les 20 min + watchdog #179 ;
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
7. branche/PR dédiée pour les changements runtime ;
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
Robot KB #180
  -> code multisource mergé sur main@9365f5cd9f8949580c4e48f00ba8c4e419c22145
  -> prochaine étape : exécuter l'installateur #180 sur le Mac
  -> vérifier LaunchAgents public :05 / paid 01:08,07:08,13:08,19:08
  -> vérifier premier catch-up public puis paid borné, logs et nouvelles observations PostgreSQL
  -> confirmer qu'aucun secret n'apparaît hors Trousseau
  -> garder V4_USE=false pendant cette phase

Global / Magi
  -> #177, #178 et #179 sont en production
  -> conserver le plafond TCGdex recovery à 36 et la réserve broad 28
  -> conserver les 5 set-name cases bloqués tant qu'aucune preuve exacte n'existe
  -> chercher seulement des classes déterministes répétées, pas des aliases carte-par-carte

TCGdex
  -> #159 est superseded fonctionnellement par #177 ; ne pas la rejouer telle quelle
  -> ne jamais fabriquer une microvariante

V5
  -> PR #8 reste expérimentale/draft/non mergée
  -> aucun merge sans autorisation explicite

Neon
  -> conserver comme rollback manuel
```

Aucun achat, bid, checkout ou paiement automatique.
