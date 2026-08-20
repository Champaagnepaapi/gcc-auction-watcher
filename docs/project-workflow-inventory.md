# Robot Pokémon / GCC Auction Watcher — inventaire workflows GitHub Actions

Audit vérifié le **20 août 2026** pendant la phase marketplace-first #147 / cutover production.

## Résultat clé

Le tree `main` contient **16 fichiers workflow YAML**. #147 et le cutover marketplace-first ne créent pas de workflow permanent supplémentaire : le workflow existant `v4-global-notify.yml` reste l'unique lane Global planifiée et change seulement de runner après validation/merge du cutover.

L'API Actions conserve aussi des enregistrements historiques de workflows supprimés ; ces records ne sont pas une preuve qu'un YAML existe encore sur `main`.

**Le tree Git est l'autorité pour ce qui peut réellement être déclenché.**

## Workflows permanents

| Workflow | Trigger réel | Statut / notes |
|---|---|---|
| `japan-edge-hunter.yml` | `workflow_dispatch` + cron | PROD Japan Edge ; ASK reste ASK. |
| `japan-edge-offline-validation.yml` | `workflow_dispatch` + PR ciblée | CI/offline Japan Edge. |
| `psa-api-diagnostic.yml` | `workflow_dispatch` | Diagnostic PSA manuel. |
| `robot-kb-cloud-shadow.yml` | `workflow_dispatch` + cron | Robot KB collecte séparée, aucune transaction. |
| `robot-kb-sold-shadow.yml` | `workflow_dispatch` + cron | Robot KB SOLD/backfill strict. |
| `v4-auction-discovery-validation.yml` | `workflow_dispatch` + PR ciblée | CI/comparaison V4 read-only. |
| `v4-final-auction-check.yml` | `workflow_dispatch` | Fast Lane production, cadence externe. Aucun cron GitHub parallèle. |
| `v4-gcc-coverage-audit.yml` | `workflow_dispatch` | Audit GCC manuel/read-only. |
| `v4-global-live-shadow.yml` | `workflow_dispatch` | Global manuel/read-only ; `economic_confirmation` utilise le stack exact confirmé. |
| `v4-global-market-offline-validation.yml` | PR ciblée | CI Global : tests + regressions V4 + compile/YAML/diff ; sur PR marketplace pertinente, live marketplace-first read-only après validation. |
| `v4-global-notify.yml` | `workflow_dispatch` + cron horaire `41 * * * *` | Unique lane Global production. Manual = toujours dry-run. Après cutover : runner marketplace-first + état durable ; marker/repo-var #146 inchangés. Aucune transaction. |
| `v4-global-shadow-dispatch-ci.yml` | PR ciblée | Vérifie le contrat du dispatcher Global. |
| `v4-kb-shadow-ingest.yml` | `workflow_run` après succès V4 | Ingestion passive vers Robot KB/Neon. |
| `v5-gcc-catalog-refresh.yml` | `workflow_dispatch` + cron | Support V5 legacy ; ne pas supprimer sans audit dédié. |
| `v5-live-raw-pipeline-diagnostic.yml` | `workflow_dispatch` | V5 diagnostic manuel, aucune transaction/grading payant. |
| `watcher.yml` | `workflow_dispatch` | V4 production canonique, cadence externe Cron-job.org. |

## Global après #139/#140/#142/#145/#146/#147

`v4-global-live-shadow.yml` reste volontairement **manuel/read-only**.

#147 ajoute le moteur marketplace-first sur `main` :

```text
inventaire GCC / Fanatics / COMC / magi / Cardova
 -> identité exacte
 -> TCGdex exact
 -> PPT / PokeTrace confirmation
 -> décision économique
```

Le cutover production réutilise **le même** `v4-global-notify.yml` :

```text
marketplace inventory
 -> état durable baseline/incrémental
 -> pending new/changed listings
 -> max 10 évaluations/run initialement
 -> TCGdex exact + retry transport borné
 -> PPT / PokeTrace confirmation
 -> MULTIMARKET_CONFIRMED uniquement
 -> déduplication persistante
 -> notification seulement si activation schedule explicite
```

Activation #146 inchangée :

- `.github/global-notify-activation = true` active les runs `schedule` ;
- `vars.GLOBAL_NOTIFY_ENABLED=true` reste supporté ;
- `vars.GLOBAL_NOTIFY_ENABLED=false` est un override d'urgence prioritaire ;
- le job schedule démarre pour résoudre l'activation, mais les étapes provider ne s'exécutent que si le gate est actif ;
- `workflow_dispatch` reste toujours dry-run ;
- `NTFY_TOPIC` vide = fail-closed avant scan.

État après cutover :

- `.global-marketplace-state/discovery.json` : inventaire observé + pending ;
- `.global-marketplace-state/notifications.json` : dédup notifications ;
- cache séparé par event `schedule` / `workflow_dispatch` ;
- disparition d'un listing != SOLD ;
- baseline puis nouvelles annonces/changements économiques seulement.

Invariants :

- TTL notification 14 jours ; re-alert si baisse >=5 % ou expiration TTL ;
- retry TCGdex Global-only : max 2 tentatives, timeout 10 s, backoff 0.25 s ; échec final reste `ERROR`/fail-closed ;
- PPT : 12 HTTP / 60 crédits / floor quotidien 15000 ;
- ASK/current auction != SOLD ;
- `ACTIVE_AUCTION` non actionnable ; `AUCTION_SNAPSHOT_LE5` reste observation, jamais vente ;
- aucune transaction, achat, bid, checkout ou paiement.

Preuves :

```text
#146 first scheduled active     run 32379733361 SUCCESS
#147 final read-only live       run 32397363626 SUCCESS
#147 Global tests               201/201 PASS
#147 V4 regressions              51/51 PASS
#147 GCC exact                  1172
#147 inventory                  1184
```

Cardova reste `AUTH_SESSION_INPUT_REQUIRED` sans input de session sûre ; aucun secret n'est stocké dans le repo.

## Triggers automatiques permanents

GitHub cron :

```text
Japan Edge Hunter
Robot KB cloud shadow
Robot KB SOLD shadow
V5 GCC Catalog Refresh
V4 Global Confirmed Notifications @ minute 41
```

Pour Global Notifications, `vars.GLOBAL_NOTIFY_ENABLED=false` force l'arrêt immédiat même si le marker versionné vaut `true`.

Événement automatique :

```text
V4 KB shadow ingest <- workflow_run successful GCC Auction Watcher
```

Cadence externe :

```text
GCC Auction Watcher
GCC Final Auction Check
```

## Règle future

Avant d'ajouter un workflow :

1. vérifier le tree courant ;
2. rechercher la capacité dans l'historique/ledger ;
3. réutiliser un workflow consolidé quand il existe ;
4. préférer `workflow_dispatch` pour diagnostics ponctuels ;
5. ne jamais ajouter un cron GitHub parallèle au Main Scanner/Fast Lane ;
6. ne pas supprimer branche/workflow/issue sans autorisation destructive explicite ;
7. aucune transaction automatique.

Le nombre de records historiques Actions n'est pas le nombre de YAML réellement présents dans le tree.
