# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/GitHub live reste l'autorité pour les faits techniques. Ce README résume l'état fonctionnel courant ; l'historique détaillé et les supersessions sont dans `docs/project-capability-ledger.md`.

## État canonique — 20 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production canonique          : main
Dernier merge runtime            : PR #148 / ea9a69b375434031c935de8d25fcc12acd1a1c93
Global discovery                 : marketplace-first / PR #147 mergée
Global notification cutover      : marketplace-first / PR #148 mergée
Global activation                : PR #146 / marker versionné + repo-var override
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
Robot KB / Neon                  : historique durable séparé de V4/V5
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Le SHA exact de `main` doit toujours être re-vérifié live. Les SHA ci-dessus servent de points de reprise fonctionnels ; des commits docs-only peuvent suivre un merge runtime.

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
2. ventes SOLD exactes anciennes, ajustées temporellement lorsque la méthode est défendable ;
3. asks fixes compatibles, explicitement étiquetés **ASK** ;
4. snapshot d'enchère observé à `≤5 min` si aucun SOLD n'est disponible ;
5. enchère en cours = signal faible.

**Un ask ou une enchère en cours n'est jamais une vente.**

---

# Global Multi-Vault — production marketplace-first

## Architecture courante

Depuis #147/#148, le Global ne choisit plus arbitrairement quelques seeds avant de chercher des offres.

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

Au premier passage :

- l'inventaire existant est réellement analysé ;
- les offres déjà présentes peuvent donc déclencher une décote immédiatement ;
- elles sont aussi enregistrées comme baseline de discovery.

Aux passages suivants :

- nouvelles annonces ;
- changements économiques utiles, notamment prix ;
- listings pending/retryables ;
- les annonces inchangées déjà traitées ne sont pas réévaluées inutilement.

Une disparition d'annonce est seulement `missing` : **jamais SOLD fabriqué**.

Les anciennes seeds GCC restent utilisables comme catalogue exact de retrieval/benchmark, pas comme moteur principal de discovery.

## Providers de discovery

État validé live #147/#148 :

```text
GCC       public /on-sale-items                  OK
Fanatics  direct marketplace browse              OK
COMC      direct PSA10 Pokemon inventory sweep   OK
magi      broad Pokemon PSA10 inventory query    OK
Cardova   AUTH_SESSION_INPUT_REQUIRED             fail-closed
```

Cardova ne doit recevoir aucun secret/session commité. Tant qu'une auth automatisable sûre n'est pas fournie, sa couverture reste explicitement incomplète.

## Correctif GCC FIXED/AUCTION

Le premier live marketplace-first a révélé une régression locale : GCC n'écho pas toujours `sellingTypeGroup` dans chaque row. Le nouveau parser pouvait alors confondre une enchère à faible prix avec un `FIXED_ASK`.

Correctif livré avant le merge #147 :

- le scanner transmet explicitement au parser le type **de la requête envoyée** : `FIXED_PRICE` ou `AUCTION` ;
- le type n'est plus deviné depuis un champ row optionnel ;
- tests dédiés couvrent row sans type + auction active et row sans type + snapshot `≤5 min`.

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
- PPT/PokeTrace/eBay appartiennent à la même famille corrélée `EBAY_GRADED_AGGREGATE` et ne comptent pas comme marchés indépendants ;
- si GCC fair exact existe et contredit matériellement l'externe, blocage `MARKET_CONFLICT_BLOCKED` ;
- avec GCC fair, fair confirmé conservateur = `min(GCC fair, external fair)` ;
- sans GCC fair exact, un externe exact/fort peut confirmer `EXTERNAL_ONLY` ;
- aucune absence provider n'est interprétée comme mauvaise valeur.

Le bridge provider exact #142 ne tolère que des différences mécaniques bornées après preuve macro exacte : full collector number, set/préfixe TCGdex, langue, et suffixes provider explicitement supportés. Aucun fuzzy.

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

Après #148, ce workflow exécute :

```text
v4_global_marketplace_notify_resilient.py
```

et utilise l'état durable :

```text
.global-marketplace-state/discovery.json
.global-marketplace-state/notifications.json
```

Le workflow Global existant a été réutilisé : **aucun second cron Global n'a été créé.**

## Activation #146

- `.github/global-notify-activation = true` active les runs `schedule` lorsque la repo var n'impose rien ;
- `vars.GLOBAL_NOTIFY_ENABLED=true` reste supporté ;
- `vars.GLOBAL_NOTIFY_ENABLED=false` est le kill switch d'urgence prioritaire ;
- `workflow_dispatch` reste toujours dry-run ;
- `NTFY_TOPIC` absent/vide => fail-closed avant le scan.

Premier schedule réellement notification-capable de l'ancienne lane seed :

```text
run / job              32379733361 / 96459686467
mode                   GLOBAL_NOTIFICATION_ACTIVE
activation             true
sent                   0
transactions           false
identity_gate_relaxed  false
```

Cela prouve l'activation #146. Après le cutover #148, la **première exécution `schedule` marketplace-first sur le nouveau runtime doit encore être observée explicitement avant de revendiquer une preuve live production post-cutover**.

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

Retry TCGdex Global-only sur Timeout/ConnectionError/HTTP 502/503/504. Un échec final reste une erreur ; aucun no-match n'est fabriqué et aucun gate identité n'est relâché.

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

Live final #147 :

```text
GCC candidates / exact          14375 / 1172
Fanatics candidates / exact     24 / 1
COMC candidates / exact         11 / 11
magi candidates / exact         96 / 0
inventory queued                1184
selected / pending after        10 / 1174
TCGdex exact                    5
PPT matched                     1 ; 6 HTTP ; 28 credits
PokeTrace matched               4 ; 6 requests
market conflicts                4 blocked
confirmed_would_notify          0
notifications                   false pendant validation
transactions                    false
```

## #148 — cutover du workflow production

```text
branch                          ops/v4-global-marketplace-cutover-20260820
head validé                     9ff96e9cd9124944e50bb55e990289f5fd07492f
merge main                      ea9a69b375434031c935de8d25fcc12acd1a1c93
CI / live                       32398465774 SUCCESS
validate job                    96520726453 SUCCESS
live read-only job              96520818899 SUCCESS
Global tests                    202/202 PASS
V4 multimarket                   51/51 PASS
py_compile / YAML / diff-check  PASS
artifact                        9417682288
artifact digest                 sha256:9e7d17471b49d90496a0aaf9fcb5f4b5d2dd72cba8888f818c1f1bebe5d126ef
```

Live #148 :

```text
GCC candidates / exact          14373 / 1172
Fanatics candidates / exact     24 / 1
COMC candidates / exact         11 / 11
magi candidates / exact         96 / 0
inventory                       1184
selected / pending after        10 / 1174
catalog SOLD                    780
catalog fair                    100
TCGdex exact                    5
PPT                             1 match ; 6 HTTP ; 28 credits
PokeTrace                       4 matches ; 6 requests
market conflicts                4 blocked
confirmed_would_notify          0
notifications                   false pendant validation
identity_gate_relaxed           false
transactions                    false
```

Le cœur V4 canonique n'a pas été remplacé par le Global ; #148 change uniquement la lane Global de notification/discovery.

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

Architecture prix/identité V4 :

```text
GCC listing
  -> TCGdex exact / déterministe
  -> PokeTrace marché/prix
  -> PSA APR / eBay SOLD fallback ou confirmation selon scope
  -> arbitrage économique
```

PSA scope économique production : `8`, `8.5`, `9`, `10`. PSA <8 hors scope économique ; ne jamais synthétiser PSA 9.5.

Chemins V4 principaux :

- `GCC_ONLY`
- `GCC_EXTERNAL_CONFIRMED`
- `EXTERNAL_RESCUE`
- `EXTERNAL_PENDING`
- `MARKET_CONFLICT_BLOCKED`

La lignée TCGdex/PokeTrace #123→#135 reste l'autorité V4 pour l'identité exacte, les bridges déterministes, les microvariantes et le fallback catalogue source-pinné. PR #126 est superseded et ne doit pas être mergée.

---

# Robot KB / Neon

Robot KB reste séparé de la décision commerciale V4/Global.

- observations append-only, datées, immuables ;
- payload brut + provenance ;
- priorité aux ventes finales `SOLD` prouvées ;
- fixed : baseline puis changements utiles ;
- auctions : SOLD final prioritaire ; snapshot `≤5 min` uniquement fallback explicitement identifié ;
- disparition/ask/live auction ne devient jamais vente ;
- objectif : courbes 30j/90j/1an/multi-années, liquidité, tendance, calibration.

Ne pas activer un hard gate KB-first tant que la profondeur exacte par identité/grader/grade n'est pas démontrée suffisante.

---

# V5 — EXPÉRIMENTALE

```text
PR #8        OPEN / DRAFT / NON MERGED
branch       agent/v5-poketrace-cardmarket-market-data
head         bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

**Ne jamais merger PR #8 dans `main` sans autorisation explicite.**

V5 et ses child PRs restent séparées de V4/Global production.

---

# Workflows permanents

Le tree `main` contient **16 workflows YAML** au dernier audit live de cette phase.

À retenir :

- Main Scanner et Fast Lane : cadence externe ;
- Robot KB : collecte séparée ;
- `v4-global-live-shadow.yml` : manuel/read-only ;
- `v4-global-market-offline-validation.yml` : CI Global + live PR read-only pertinent ;
- `v4-global-notify.yml` : unique Global schedule, marketplace-first depuis #148 ;
- V5 lives : manuels/expérimentaux uniquement.

Voir `docs/project-workflow-inventory.md` pour le détail.

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
13. mettre à jour README/ledger/inventaires après une phase importante.

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
  -> laisser le bootstrap drainer les 1174 listings pending par batches bornés
  -> observer explicitement le premier vrai schedule post-#148 sur main
  -> ensuite mesurer débit, backlog et coûts avant tout scale-up >10/run
  -> si anomalie : vars.GLOBAL_NOTIFY_ENABLED=false = kill switch

Cardova
  -> reste fail-closed AUTH_SESSION_INPUT_REQUIRED
  -> ne jamais stocker session/cookie/token dans le repo

V4
  -> cœur production inchangé ; continuer normalement
```

Aucun achat, bid, checkout ou paiement automatique.