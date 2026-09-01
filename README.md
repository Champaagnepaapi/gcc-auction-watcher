# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/Git/GitHub live reste l'autorité. Ce README décrit l'état fonctionnel courant ; les détails historiques et de gouvernance sont dans `docs/`.

## État canonique — 1 septembre 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
main GitHub / docs               : 1911ba5cdfd60d4dbc57dbb8ba07c42d3f22aea9 (docs closeout #215)
V4 runtime production            : c2bb3890fcf6e98e29d3ccf937b42ae2fddbae09 (runtime merge #214)
TCGdex outage resilience         : PR #216 OPEN / DRAFT / NON MERGED
#216 runtime validé              : 53a7fd0a47d100d851c347c3fadb79e4f754d07b
#216 V4 validation               : run 33484132586 SUCCESS / 845 PASS / 2 skipped / live compare PASS
#216 docs-head validation        : run 33484530583 SUCCESS / 845 PASS / 2 skipped / live compare PASS
Dernier outage naturel TCGdex    : run 33484902370 / 18 attempted / 0 exact / 18 ConnectionError / backlog 2029
External pending throughput      : PR #214 MERGED / head 5aa3acd3ea3d52bb2c5fca4cf8b0c0c0901ba595
#214 validation                  : run 33441243258 SUCCESS / 834 tests PASS / live compare PASS
#214 production proof            : run 33441714954 SUCCESS / P4 16 / eBay 16 / auctions max 4 / backlog ETA 141
Auction order-drift hardening    : PR #211 + mirror #212 MERGED / head 461e0ec57271901033426f3566f6ab1f6b38e86a
Auction hardening validation     : run 33438530882 SUCCESS / 831 tests PASS / live compare PASS
Magi coverage production         : PR #174 + #177 MERGED
Magi production proof            : run 32893130902 SUCCESS / 31 EXACT sur 96
Magi budget fix                  : PR #178 MERGED / 545223613ce21e6c4cf886e07201bc3c105a5e69
Magi #178 read-only proof        : run 32943536626 SUCCESS / 30 EXACT + 55 SOLD / 0 budget-exhausted
Global schedule watchdog         : PR #179 MERGED / ac5f7c734685422612a0f24690af22910eefa951
Robot KB cutover runtime         : PR #166 / 611edf469dfe5e5bfc46390ba6680b9c2ebe9fee
Robot KB multisource runtime     : PR #180 MERGED / 9365f5cd9f8949580c4e48f00ba8c4e419c22145
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
sets_catalog                     1
sets_filtered                    7
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

## Transport outage — PR #216 CANDIDATE / NON DÉPLOYÉE

Les runs naturels de `main` ont confirmé une panne TCGdex provider-wide en `ConnectionError`. Le run `33484902370` a tenté **18** identités, obtenu **0 exact** et **18 erreurs**, avec PokeTrace non appelé faute d'identité TCGdex. Le backlog externe restait à **2029**.

Un simple retry 2×10 s sur chaque carte aurait pu augmenter dangereusement la durée du Main Scanner. #216 réutilise donc deux patterns existants sans toucher à l'identité :

```text
transport #145                  2 tentatives max / timeout effectif >=10 s
retry                            Timeout / ConnectionError / HTTP 502/503/504 seulement
404 / vraie réponse provider     pas de retry synthétique ; reset du streak
breaker Main-only #189 pattern   après 2 appels logiques épuisés consécutifs
circuit ouvert                   appels réseau TCGdex restants sautés ce run
sémantique                       ERROR / fail-closed, jamais clean no-match fabriqué
nouveau process                  circuit fermé, provider retenté
```

Runtime validé : `53a7fd0a47d100d851c347c3fadb79e4f754d07b`. V4 CI `33484132586` : **845 PASS / 2 skipped**, compile/YAML/diff PASS, live auction compare superset (`94 vs 91`, `legacy_only=0`). Le docs-head `fa3914fb...` a aussi validé V4 (`33484530583`, `96 vs 93`, `legacy_only=0`) et Robot KB (`33484530594` SUCCESS). Les validations Global offline sont vertes ; leurs `marketplace-live-once` read-only étaient encore en cours au dernier contrôle. Le breaker #216 est Main-only et ne modifie pas le comportement Global #145.

#216 reste **OPEN / DRAFT / NON MERGED**. Aucun déploiement sans autorisation explicite utilisateur.

---

# V4 — production canonique

## Main Scanner

```text
Cron-job.org ~toutes les 10 min
  -> workflow_dispatch
  -> .github/workflows/watcher.yml
  -> run_watcher_multimarket.py
```

Le chemin ci-dessus est le runtime actuellement déployé. Si #216 était explicitement autorisée puis mergée, `watcher.yml` passerait par le bootstrap mince `run_watcher_multimarket_resilient.py`, qui installe la résilience TCGdex puis délègue au runner canonique inchangé.

## Auction discovery hardening — #211 / #212

Le chemin normal reste le collector rapide `AUCTION + ON_SALE + ENDING_SOON` avec `endTime` individuel. Lorsque l'ordre `ENDING_SOON` est valide, aucun scan exhaustif supplémentaire n'est exécuté.

Si GCC renvoie un ordre localement incohérent, V4 tente uniquement pour ce snapshot une récupération exhaustive **bornée** sur la requête filtrée, puis applique l'horizon `≤60 min` localement. Toute erreur structurelle (requête, pagination, `endTime`, page répétée, absence de progrès, `nextPage` invalide ou limite de pages) reste **fail-closed** et déclenche le fallback legacy existant.

Validation avant production : run `33438530882` SUCCESS, **831 tests PASS**, compile/YAML/diff-check PASS, live compare PASS. Le snapshot live normal a gardé le fast path : API total 15049 mais seulement **1 page / 100 lignes** lue. Aucun changement des règles identité, fair value, décote, providers ou notifications économiques.

L'alerte technique fixed distingue désormais explicitement `first-evaluation backlog`, `external pending retry` et `fresh already evaluated` ; un backlog `EXTERNAL_PENDING` n'est plus présenté comme un stock de cartes jamais évaluées.

## External pending throughput — #214

PR #214 augmente uniquement le débit borné de la file fixed `EXTERNAL_PENDING` en réutilisant le stack existant de drain/provider resilience/run breakers :

```text
P4 scheduling                    16/run
P4 hard configuration ceiling    20/run
eBay SOLD total                  16/run
fixed eBay reserve               12/run
auction eBay max                 4/run
budget-only cooldown             5 min
PSA APR max                      2/run
provider-error backoff           inchangé
```

Validation avant merge : run `33441243258` SUCCESS, **834 tests PASS**, compile/YAML/diff-check PASS et live compare PASS. Le premier run naturel post-merge `33441714954` sur `main@c2bb3890fcf6e98e29d3ccf937b42ae2fddbae09` est SUCCESS en 205 s et confirme au démarrage `P4 max 16/run | eBay SOLD total 16/run | auctions max 4 | fixed reserve 12`.

Le même run prouve que les protections restent fail-closed : eBay a ouvert son circuit après **2 hard timeouts de 30 s** sans bloquer le scanner ; PSA APR a ouvert son circuit après le premier **HTTP 403**. La file externe restait `INCOMPLETE` avec **2241 pending** et une ETA diagnostique de **141 runs**. Les runs suivants ont continué à drainer le backlog jusqu'à **2029**, mais TCGdex est devenu le plafond provider avec des `ConnectionError` répétés. Aucun provider failure n'est transformé en clean no-match.

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
```

La lane multisource reste séparée du gate économique V4/Global :

- Fanatics, COMC, Magi et Cardova publics : baseline puis changements matériels ;
- PokeTrace : marchés US/EU, Pokémon EN/JP, **single cards uniquement**, prix courants + historique `period=all`, priorité PSA 10/9/8/8.5 ;
- PokemonPriceTracker : sets EN/JP, historique 180 jours, eBay gradé agrégé + métriques CardMarket/TCGplayer ;
- provenance, payload brut et `observed_at` conservés dans Robot KB ;
- `SOLD_AGGREGATED` reste agrégé et ne devient jamais un item-level SOLD ;
- `cardmarket_unsold` reste `FIXED_ASK_AGGREGATED` ; ASK reste ASK.

Les clés PokeTrace/PPT doivent rester **uniquement dans le Trousseau macOS**. Elles ne doivent apparaître ni dans Git, ni dans les plist, ni dans les states/logs.

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
V4 / TCGdex provider outage
  -> #216 est CANDIDATE / OPEN / DRAFT / NON MERGED ; runtime validé 53a7fd0a47d100d851c347c3fadb79e4f754d07b
  -> panne toujours observée sur main : run 33484902370 = 18/18 ConnectionError ; backlog EXTERNAL_PENDING 2029
  -> conserver le fail-closed : une panne TCGdex reste ERROR, jamais clean no-match
  -> conserver le breaker Main-only proposé : 2 appels logiques épuisés puis coupe réseau du run ; nouvel essai au run suivant
  -> attendre/observer les lives Global read-only déjà lancés, sans confondre une panne provider Global avec une régression du breaker Main-only
  -> aucun merge/déploiement #216 sans autorisation explicite utilisateur
  -> après autorisation seulement : merge avec SHA attendu, vérifier main, puis run naturel de production pour mesurer durée + TCGdex + backlog

V4 external-market backlog
  -> #214 reste en production : P4 16/run, eBay 16/run, reserve fixed 12, auctions max 4, hard ceiling P4 20
  -> le backlog a drainé de 2241 à 2029 mais la couverture externe reste INCOMPLETE
  -> conserver les breakers fail-closed eBay/PSA et le provider-error backoff
  -> ne pas augmenter encore les caps uniquement pour forcer le drainage

Robot KB
  -> rester séparé de V4 ; V4_USE=false
  -> conserver observations immuables et priorité SOLD exact final
  -> Neon reste rollback manuel

Global / Magi
  -> #177, #178 et #179 sont en production
  -> conserver le plafond TCGdex recovery à 36 et la réserve broad 28
  -> conserver les 5 set-name cases bloqués tant qu'aucune preuve exacte n'existe
  -> chercher seulement des classes déterministes répétées, pas des aliases carte-par-carte

V5
  -> PR #8 reste expérimentale/draft/non mergée
  -> aucun merge sans autorisation explicite
```

Aucun achat, bid, checkout ou paiement automatique.
