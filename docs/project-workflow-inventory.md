# Robot Pokémon / GCC Auction Watcher — inventaire workflows GitHub Actions

Audit du tree `main` vérifié le **20 août 2026** après merge #140.

## Résultat clé

Le tree `main` contient **15 fichiers workflow YAML**. L'API Actions conserve aussi des enregistrements historiques de workflows supprimés ; ces records ne sont pas une preuve qu'un YAML existe encore sur `main`.

**Le tree Git de `main` est l'autorité pour ce qui peut réellement être déclenché.**

## 15 workflows présents sur main

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
| `v4-global-live-shadow.yml` | `workflow_dispatch` | **Global manuel/read-only**. Peut lancer `economic_confirmation`; notifications et transactions restent désactivées. |
| `v4-global-market-offline-validation.yml` | PR ciblée | CI Global : tests + regressions V4 + compile/YAML/diff. |
| `v4-global-shadow-dispatch-ci.yml` | PR ciblée | Vérifie le contrat manual-only/read-only du dispatcher Global. |
| `v4-kb-shadow-ingest.yml` | `workflow_run` après succès V4 | Ingestion passive vers Robot KB/Neon. |
| `v5-gcc-catalog-refresh.yml` | `workflow_dispatch` + cron | Support V5 legacy ; ne pas supprimer sans audit dédié. |
| `v5-live-raw-pipeline-diagnostic.yml` | `workflow_dispatch` | V5 diagnostic manuel, aucune transaction/grading payant. |
| `watcher.yml` | `workflow_dispatch` | V4 production canonique, cadence externe Cron-job.org. |

## Global après #139/#140/#142

`v4-global-live-shadow.yml` reste volontairement **manuel**.

Mode normal : shadow Global read-only.

Mode `economic_confirmation` :

```text
Global exact offers
 -> TCGdex exact
 -> PPT / PokeTrace confirmation
 -> would_notify diagnostic only
```

Invariants :

- `NTFY_TOPIC` vide dans le diagnostic ;
- `JAPAN_EDGE_NOTIFY_ENABLED=false` ;
- `notifications=false` ;
- `transactions=false` ;
- aucune activation/schedule Global ajoutée par #140 ;
- ASK/current auction != SOLD.

Le one-shot `.github/workflows/v4-global-exact-bridge-once.yml` utilisé pour le live #142 a été **supprimé avant merge**. Ne pas le recréer : le workflow permanent suffit pour les futurs diagnostics.

## Triggers automatiques permanents

GitHub cron :

```text
Japan Edge Hunter
Robot KB cloud shadow
Robot KB SOLD shadow
V5 GCC Catalog Refresh
```

Événement automatique :

```text
V4 KB shadow ingest <- workflow_run successful GCC Auction Watcher
```

Cadence externe :

```text
GCC Auction Watcher
GCC Final Auction Check
```

Global n'a **aucun trigger automatique**.

## Règle future

Avant d'ajouter un workflow :

1. vérifier ces 15 fichiers ;
2. rechercher la capacité dans l'historique/ledger ;
3. réutiliser un workflow consolidé quand il existe ;
4. préférer `workflow_dispatch` pour diagnostics ponctuels ;
5. ne jamais ajouter un cron GitHub parallèle au Main Scanner/Fast Lane ;
6. retirer les one-shots après leur validation ;
7. aucune transaction automatique.

Le nombre de records historiques Actions n'a pas été ré-audité exhaustivement pendant cette phase ; le dernier audit détaillé en comptait 80. Ne pas confondre ce nombre historique avec les **15 YAML réellement présents sur main**.
