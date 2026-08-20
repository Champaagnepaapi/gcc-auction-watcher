# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/GitHub live reste l'autorité pour les faits techniques. Ce README résume l'état fonctionnel courant ; l'historique détaillé et les supersessions sont dans `docs/project-capability-ledger.md`.

## État canonique — 20 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production canonique          : main
Dernier merge runtime Global     : PR #151 / c9539ca521f69b43b3d93e621fb21447a69f3fe7
Global discovery                 : marketplace-first / PR #147 mergée
Global notification cutover      : marketplace-first / PR #148 mergée
Global schedule run registry     : issue #150 / PR #151 mergée
Global activation                : PR #146 / marker versionné + repo-var override
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
Robot KB / Neon                  : historique durable séparé de V4/V5
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Le SHA exact de `main` doit toujours être re-vérifié live. Les SHA ci-dessus sont des points de reprise fonctionnels ; des commits docs-only peuvent suivre un merge runtime.

---

# Principes non négociables

- **V4 sur `main` = production canonique.**
- **PR #8 / V5 ne doit jamais être mergée dans `main` sans autorisation explicite utilisateur.**
- Pokémon **cartes individuelles uniquement** ; sealed/lots hors scope.
- Aucun achat, bid, checkout, paiement ou grading payant automatique.
- Ne jamais exposer, logger ou commiter une clé API, token, cookie, session ou mot de passe.
- Identité incertaine, contradictoire ou microvariante non prouvée = fail-closed / revue manuelle.
- Aucun fuzzy, substring, token overlap, traduction supposée ou Levenshtein comme preuve d'identité exacte.
- ASK, enchère live et disparition d'annonce ne deviennent jamais des ventes.

## Hiérarchie des preuves prix

1. ventes **SOLD exactes et récentes** ;
2. ventes SOLD exactes anciennes, ajustées temporellement lorsque défendable ;
3. asks fixes compatibles, explicitement étiquetés **ASK** ;
4. snapshot d'enchère observé à `≤5 min` si aucun SOLD n'est disponible ;
5. enchère en cours = signal faible.

**Un ask ou une enchère en cours n'est jamais une vente.**

---

# Global Multi-Vault — production marketplace-first

## Architecture courante

Depuis #147/#148, le Global ne choisit plus quelques seeds avant de chercher des offres.

```text
GCC / Fanatics / COMC / magi / Cardova
        ↓
scan inventaire courant
        ↓
identité commerciale exacte
        ↓
TCGdex exact
        ↓
GCC SOLD exact si disponible
        ↓
PPT + PokeTrace graded aggregate
        ↓
décision économique
        ↓
notification seulement si gate complet
```

### Bootstrap puis incrémental

Premier passage :

- tout l'inventaire découvert est mis en file ;
- les offres déjà présentes peuvent être évaluées immédiatement ;
- elles forment ensuite la baseline de discovery.

Passages suivants :

- nouvelles annonces ;
- changements économiques utiles, notamment prix ;
- listings pending/retryables ;
- pas de retraitement inutile des annonces inchangées déjà terminales.

Une disparition d'annonce est seulement `missing` : **jamais SOLD fabriqué**.

Les anciennes seeds GCC restent un catalogue de retrieval/benchmark, pas le moteur de discovery.

## Providers de discovery

État validé live :

```text
GCC       public /on-sale-items                  OK
Fanatics  direct marketplace browse              OK
COMC      direct PSA10 Pokemon inventory sweep   OK
magi      broad Pokemon PSA10 inventory query    OK
Cardova   AUTH_SESSION_INPUT_REQUIRED             fail-closed
```

Cardova ne doit recevoir aucun secret/session commité. Tant qu'une auth automatisable sûre n'existe pas, sa couverture reste explicitement incomplète.

## Correctif GCC FIXED/AUCTION

Le premier live marketplace-first a montré que GCC n'écho pas toujours `sellingTypeGroup` dans chaque row. Le parser pouvait alors confondre une enchère à faible prix avec un `FIXED_ASK`.

Correctif livré avant #147 :

- le scanner transmet le type **de la requête envoyée** : `FIXED_PRICE` ou `AUCTION` ;
- le type n'est plus déduit d'un champ row optionnel ;
- tests dédiés couvrent auction active et snapshot `≤5 min` sans champ type.

Une enchère active reste non actionnable ; un snapshot `≤5 min` reste une observation, jamais une vente.

---

# Gate économique Global

Une opportunité Global n'est actionnable que si :

```text
identité exacte
+ offre FIXED_ASK ou AUCTION_SNAPSHOT_LE5
+ all_in_eur prouvé
+ TCGdex exact
+ externe gradé exact suffisamment fort
+ décote >= 30 %
+ aucun conflit matériel de marché
```

Règles :

- `ACTIVE_AUCTION` non actionnable ;
- externe gradé : minimum 3 ventes agrégées ;
- PPT/PokeTrace/eBay appartiennent à la même famille corrélée `EBAY_GRADED_AGGREGATE` ;
- si GCC fair exact contredit matériellement l'externe : `MARKET_CONFLICT_BLOCKED` ;
- avec GCC fair : fair confirmé conservateur = `min(GCC fair, external fair)` ;
- sans GCC fair exact : `EXTERNAL_ONLY` possible avec externe exact/fort ;
- absence provider ≠ mauvaise valeur.

Le bridge provider exact #142 ne tolère que des différences mécaniques bornées après preuve macro exacte. Aucun fuzzy.

---

# Notifications Global — production

Workflow unique :

```text
.github/workflows/v4-global-notify.yml
```

Triggers :

```text
workflow_dispatch   -> toujours dry-run
schedule            -> 41 * * * *
```

Depuis #148 :

```text
v4_global_marketplace_notify_resilient.py
```

État durable :

```text
.global-marketplace-state/discovery.json
.global-marketplace-state/notifications.json
```

Le workflow existant a été réutilisé : **aucun second cron Global**.

## Activation #146

- `.github/global-notify-activation = true` active les runs `schedule` si la repo var n'impose rien ;
- `vars.GLOBAL_NOTIFY_ENABLED=true` reste supporté ;
- `vars.GLOBAL_NOTIFY_ENABLED=false` = kill switch prioritaire ;
- `workflow_dispatch` reste toujours dry-run ;
- `NTFY_TOPIC` absent/vide => fail-closed avant scan.

Preuve historique de l'activation notification : run `32379733361`, mode `GLOBAL_NOTIFICATION_ACTIVE`, activation true, 0 sent, transactions false.

## Registre autonome des runs Global — #150 / #151

Le connecteur utilisé par ChatGPT ne sait pas lister génériquement les runs GitHub Actions `schedule` sans connaître leur `run_id`. Depuis #151, chaque vrai run `schedule` Global écrit donc une ligne minimale dans l'issue **#150 `Global Run Registry — ChatGPT log access`**.

Le registre contient uniquement :

- timestamp UTC, `run_id`, attempt, trigger, commit SHA ;
- activation et outcome du runner ;
- métriques agrégées sûres discovery/TCGdex/PPT/PokeTrace/notification ;
- flags explicites `automatic_purchase/bid/checkout/payment`.

Il ne recopie **aucun log complet**, secret, token, cookie/session, identité listing-level ou donnée de paiement. Le registre V4 historique reste séparé dans l'issue #1.

`workflow_dispatch` n'écrit pas dans #150 : seuls les vrais `schedule` le font. Le finalizer tourne avec `always()` afin qu'un run provider en échec laisse quand même son `run_id` et son statut lorsque GitHub peut exécuter la fin du job.

Validation #151 avant merge :

```text
branch                         ops/v4-global-run-registry-20260820
head                           a424fb62cb5e0553929847d3b973411a8b61a561
merge main                     c9539ca521f69b43b3d93e621fb21447a69f3fe7
CI / live                      32410224171 SUCCESS
validate / live jobs           96558656377 / 96558728745
Global tests                   203/203 PASS
V4 multimarket                  51/51 PASS
compile / YAML / diff-check    PASS
live mode                      READ_ONLY_MARKETPLACE_DISCOVERY_VALIDATION
inventory                      1186
selected / pending after       10 / 1176
TCGdex exact                   5
PPT                            1 match / 6 HTTP / 28 credits
PokeTrace                      4 matches / 6 requests
market conflicts               4 blocked
confirmed_would_notify         0
notifications                  false pendant validation
transactions                   false
artifact                       9421951722
```

La prochaine preuve à capturer est le **premier commentaire réel de #150 créé par un `schedule` sur `main` après #151**. À partir de là, ChatGPT peut récupérer le `run_id`, lire jobs/logs/artifacts et vérifier la prod sans demander de lien à l'utilisateur.

## Budgets / résilience

```text
pending evaluations/run        10 initialement
PPT max HTTP                   12
PPT max credits                60
PPT daily remaining floor      15000
TCGdex max attempts            2
TCGdex timeout                 10 s
TCGdex retry backoff           0.25 s
```

Retry TCGdex Global-only sur Timeout/ConnectionError/HTTP 502/503/504. Échec final = erreur ; aucun no-match fabriqué et aucun gate identité relâché.

Dédup notification : TTL 14 jours ; re-alert seulement après expiration ou baisse de prix `>=5%`.

---

# Validation #147 / #148

## #147 — moteur marketplace-first

```text
head #147                       2e65631416d0b39947de47ed4df3d37a4a87cbdc
merge main                      5a1b0f050098b560e812a4dc6e64a9f8d40a8897
CI / live                       32397363626 SUCCESS
Global tests                    201/201 PASS
V4 multimarket                   51/51 PASS
py_compile / YAML / diff-check  PASS
```

Live : GCC 1172 exact, Fanatics 1, COMC 11, magi 0 ; inventory 1184 ; 10 évaluées ; TCGdex 5 ; PPT 1 ; PokeTrace 4 ; 4 conflits bloqués ; 0 would-notify ; transactions false.

## #148 — cutover production

```text
branch                          ops/v4-global-marketplace-cutover-20260820
head validé                     9ff96e9cd9124944e50bb55e990289f5fd07492f
merge main                      ea9a69b375434031c935de8d25fcc12acd1a1c93
CI / live                       32398465774 SUCCESS
Global tests                    202/202 PASS
V4 multimarket                   51/51 PASS
py_compile / YAML / diff-check  PASS
```

Le cœur V4 canonique n'a pas été remplacé par Global ; #148 change uniquement la lane Global notification/discovery.

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

Ne jamais ajouter de cron GitHub parallèle à ces deux lanes.

Architecture :

```text
GCC listing
  -> TCGdex exact / déterministe
  -> PokeTrace marché/prix
  -> PSA APR / eBay SOLD fallback ou confirmation selon scope
  -> arbitrage économique
```

PSA scope production : `8`, `8.5`, `9`, `10`. PSA <8 hors scope économique ; jamais de PSA 9.5 synthétique.

Chemins principaux : `GCC_ONLY`, `GCC_EXTERNAL_CONFIRMED`, `EXTERNAL_RESCUE`, `EXTERNAL_PENDING`, `MARKET_CONFLICT_BLOCKED`.

La lignée TCGdex/PokeTrace #123→#135 reste l'autorité V4. PR #126 est superseded et ne doit pas être mergée.

---

# Robot KB / Neon

Robot KB reste séparé de la décision commerciale V4/Global.

- observations append-only, datées, immuables ;
- payload brut + provenance ;
- priorité aux ventes finales `SOLD` prouvées ;
- fixed : baseline puis changements utiles ;
- auctions : SOLD final prioritaire ; snapshot `≤5 min` seulement fallback identifié ;
- disparition/ask/live auction ne devient jamais vente ;
- objectif : courbes 30j/90j/1an/multi-années, liquidité, tendance, calibration.

Pas de hard gate KB-first tant que la profondeur exacte par identité/grader/grade n'est pas suffisante.

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

Le tree `main` contient **16 workflows YAML**. #151 n'en ajoute aucun : il modifie seulement le workflow Global existant.

À retenir :

- Main Scanner et Fast Lane : cadence externe ;
- Robot KB : collecte séparée ;
- `v4-global-live-shadow.yml` : manuel/read-only ;
- `v4-global-market-offline-validation.yml` : CI Global + live PR read-only ;
- `v4-global-notify.yml` : unique Global schedule, marketplace-first + registre #150 ;
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
  -> récupérer automatiquement le prochain run_id schedule via issue #150
  -> inspecter jobs/logs/artifact du premier schedule post-#151
  -> laisser le bootstrap drainer le backlog par batches de 10
  -> mesurer débit, backlog et coûts avant scale-up >10/run
  -> anomalie : vars.GLOBAL_NOTIFY_ENABLED=false = kill switch

Cardova
  -> reste fail-closed AUTH_SESSION_INPUT_REQUIRED
  -> ne jamais stocker session/cookie/token dans le repo

V4
  -> cœur production inchangé ; continuer normalement
```

Aucun achat, bid, checkout ou paiement automatique.