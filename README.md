# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/GitHub live reste l'autorité. Ce README résume l'état fonctionnel courant ; les supersessions et détails de gouvernance sont dans `docs/`.

## État canonique — 21 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production canonique          : main @ c3e3da39b79eb71cfdfc864bb865c4a4e7154e0c
Dernier merge runtime            : PR #154 / TCGdex variants_detailed
Global discovery                 : marketplace-first / #147 + #148
Global cadence                   : toutes les 10 min / PR #153
Global schedule run registry     : issue #150 / PR #151 / PROUVÉ LIVE
Global activation                : PR #146 / marker versionné + repo-var override
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
Robot KB                         : Neon actif ; migration PostgreSQL Mac préparée par PR #157
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Toujours re-vérifier le HEAD `main` live avant une action importante.

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
Cardova   AUTH_SESSION_INPUT_REQUIRED             fail-closed
```

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

Le correctif #147 transmet explicitement le type GCC `FIXED_PRICE/AUCTION` depuis la requête : une auction dont la row omet `sellingTypeGroup` ne peut pas devenir `FIXED_ASK`.

---

# TCGdex — identité et microvariantes

La lignée #119→#135 reste l'autorité de récupération exacte : coordinate, aliases de set prouvés, unicité catalogue et fallback source-pinné immuable.

## PR #154 — `variants_detailed` en production

Merge : `c3e3da39b79eb71cfdfc864bb865c4a4e7154e0c`.

Après une identité TCGdex déjà exacte, V4/Global consomme désormais `variants_detailed` comme **preuve commerciale déterministe** :

- normal / holo / reverse ;
- First Edition / Unlimited / Shadowless quand explicitement prouvés ;
- Poké Ball / Master Ball / Cosmos / Galaxy / Cracked Ice ;
- langue exacte ;
- axes inconnus, multiples, malformés ou contradictoires => blocage fail-closed.

Une entrée qui affirme deux valeurs incompatibles sur le même axe, par exemple `Unlimited + 1st Edition` ou `Poké Ball + Master Ball`, reste bloquée : aucune logique “last write wins”.

Le proof source-pinné japonais reste prioritaire lorsqu'il existe. Le `pricing` / `thirdParty` de `variants_detailed` est **ignoré pour la valorisation des slabs**.

Validation #154 :

```text
head                           bb21aeb118c66a3da5df6bc949ce64d23bab2c1b
merge main                     c3e3da39b79eb71cfdfc864bb865c4a4e7154e0c
Global CI/live                 32444255909 SUCCESS
validate/live jobs             96660771327 / 96660823079 SUCCESS
Global tests                   221/221 PASS
V4 multimarket                  51/51 PASS
full V4 validation             SUCCESS
compile / YAML / diff-check    PASS
live mode                      READ_ONLY_MARKETPLACE_DISCOVERY_VALIDATION
inventory                      1196
selected / pending after       10 / 1186
TCGdex exact                   5
PPT                            1 match / 6 HTTP / 28 credits
PokeTrace                      4 matches / 6 requests
market conflicts               4 blocked
confirmed_would_notify         0
transactions                   false
artifact                       9433579221
artifact sha256                1779cb1e3613795e83e414f1ae1b7118a8ad495523ef0cb2c5b1b5427f6436a4
```

Le live read-only n'a pas relâché le gate d'identité et n'a envoyé aucune notification.

---

# Notifications Global — production

Workflow unique : `.github/workflows/v4-global-notify.yml`.

```text
workflow_dispatch   -> toujours dry-run
schedule            -> 1,11,21,31,41,51 * * * *
runner              -> v4_global_marketplace_notify_resilient.py
batch               -> 10 pending/run actuellement
state               -> .global-marketplace-state
```

PR #153 a accéléré **le même workflow** d'horaire à toutes les 10 minutes ; aucun second cron n'a été ajouté, les budgets/run restent inchangés.

Activation :

- `.github/global-notify-activation=true` ;
- `vars.GLOBAL_NOTIFY_ENABLED=true` supportée ;
- `vars.GLOBAL_NOTIFY_ENABLED=false` = kill switch prioritaire ;
- `workflow_dispatch` reste dry-run ;
- `NTFY_TOPIC` absent/vide => fail-closed avant scan.

Budgets :

```text
PPT max HTTP                   12/run
PPT max credits                60/run
PPT daily remaining floor      15000
TCGdex max attempts            2
TCGdex timeout                 10 s
TCGdex retry backoff           0.25 s
```

Dédup notification : TTL 14 jours ; re-alert seulement après expiration ou baisse de prix `>=5%`.

## Registre schedule #150 — preuve production observée

Depuis #151, chaque vrai `schedule` poste des **métadonnées agrégées minimales** dans l'issue #150. Aucun log complet, secret, session ou détail listing-level n'y est copié.

Première preuve réelle post-#151 :

```text
run_id                 32411433425
trigger                schedule
commit                  c9539ca521f69b43b3d93e621fb21447a69f3fe7
activation              true
mode                    GLOBAL_MARKETPLACE_NOTIFICATION_ACTIVE
marketplace_status      success
selected/pending        10 / 1166
TCGdex exact            3
PPT                     0 match / 3 HTTP / 15 credits
PokeTrace               1 match / 4 requests
confirmed/sent          0 / 0
identity relaxed        false
transactions            false
```

La cadence 10 minutes de #153 est aussi prouvée en production. Dernier schedule observé avant le merge #154 : run `32443663511` sur `e79e939c...`, success, activation true, 10 évaluées, 1137 pending, 0 notification, transactions false.

Un schedule spécifique au commit #154 n'était pas encore apparu dans #150 au moment de cette fermeture documentaire ; ne pas le revendiquer avant observation explicite.

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

# Robot KB — migration Neon → PostgreSQL local Mac

Robot KB reste séparé de la décision commerciale V4/Global.

Contrat historique inchangé :

- observations append-only, datées, immuables ;
- payload brut + provenance ;
- priorité aux ventes finales `SOLD` prouvées ;
- fixed : baseline puis changements utiles ;
- auctions : SOLD final prioritaire ; snapshot `≤5 min` seulement fallback identifié ;
- disparition/ask/live auction ne devient jamais vente ;
- objectif : courbes 30j/90j/1an/multi-années, liquidité, tendance, calibration.

## PR #157 — lane Mac préparée, cutover Neon pas encore exécuté

Le quota Neon `robot-pokemon-kb` a atteint sa limite de stockage. La cible durable devient PostgreSQL local sur le Mac mini, sans exposer la base à Internet.

PR #157 prépare :

```text
PostgreSQL 16 local             127.0.0.1 / robot_pokemon_kb
runtime Robot KB                P3 validé @ 1d06fe33b6fc640657255e15a8d17251aa02b6ce
fixed + auctions               LaunchAgent à :32
SOLD fresh/backfill             LaunchAgent à :17 et :47
backup                          LaunchAgent quotidien 03:10
backups conservés               7 dumps complets locaux
```

Migration : saisie masquée de la DATABASE URL Neon → `pg_dump` secret-safe → restore local → comparaison fingerprints/row counts source/local → marker `MIGRATION_VERIFIED` seulement si identique.

**Cutover volontairement en deux phases** :

1. merger/préparer les scripts locaux tout en laissant les collectors Neon existants actifs ;
2. exécuter et vérifier réellement la migration sur le Mac ;
3. seulement ensuite retirer les schedules/workflow_run Neon dans une PR de cutover séparée et abandonner Neon.

Ne jamais supprimer le projet Neon avant la preuve source ↔ local. Si Neon refuse le dump à cause du quota, attendre le retour lecture/reset ou utiliser un accès temporaire permettant uniquement l'export ; ne jamais démarrer une base locale vide comme remplacement silencieux.

Pas de hard gate KB-first tant que la profondeur exacte n'est pas suffisante.

---

# V5 — EXPÉRIMENTALE

```text
PR #8        OPEN / DRAFT / NON MERGED
branch       agent/v5-poketrace-cardmarket-market-data
head         bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

**Ne jamais merger PR #8 dans `main` sans autorisation explicite.**

---

# Workflows permanents

Après merge de la préparation #157, le tree contient **17 workflows YAML** : les 16 workflows existants restent inchangés et `robot-kb-local-postgres-validation.yml` ajoute uniquement une validation CI/manual de la lane Mac.

À retenir :

- Main Scanner et Fast Lane : cadence externe ;
- Robot KB Neon : collecte encore active jusqu'au cutover Mac vérifié ;
- Robot KB local Mac : scripts/LaunchAgents préparés, pas un workflow cloud de collecte ;
- `v4-global-live-shadow.yml` : manuel/read-only ;
- `v4-global-market-offline-validation.yml` : CI Global + live PR read-only ;
- `v4-global-notify.yml` : unique Global schedule toutes les 10 min + registre #150 ;
- V5 lives : manuels/expérimentaux uniquement.

Voir `docs/project-workflow-inventory.md`.

---

# Gouvernance avant changement important

1. lire entièrement ce README ;
2. lire `.agents/rules/gcc-project-governance.md` ;
3. lire capability ledger + inventaires pertinents ;
4. vérifier `main`, SHA, PRs, branches et workflows live ;
5. chercher une capacité existante avant de réimplémenter ;
6. branche/PR dédiée ;
7. SHA précis ;
8. tests ciblés + suite pertinente ;
9. compile/YAML/`git diff --check` ;
10. live read-only lorsque pertinent ;
11. aucune transaction/secret ;
12. merge seulement avec l'autorisation requise ;
13. mettre à jour README/ledger/inventaires après phase importante.

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
Global marketplace-first
  -> observer/valider séparément les changements de scale de la PR #156

Robot KB
  -> merger la préparation locale #157 après CI verte
  -> pull sur le Mac mini
  -> exécuter Installer Robot KB Local.command
  -> migrer Neon et obtenir MIGRATION_VERIFIED + health OK
  -> seulement alors cutover des writers Neon

TCGdex
  -> utiliser variants_detailed quand présent
  -> ne jamais fabriquer une microvariante quand plusieurs axes restent possibles

Cardova
  -> reste fail-closed AUTH_SESSION_INPUT_REQUIRED
  -> ne jamais stocker session/cookie/token dans le repo
```

Aucun achat, bid, checkout ou paiement automatique.