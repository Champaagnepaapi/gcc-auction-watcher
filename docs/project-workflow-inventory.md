# Robot Pokémon / GCC Auction Watcher — inventaire workflows GitHub Actions

Audit vérifié le **20 août 2026** après le merge #151.

## Résultat clé

Le tree `main` contient **16 fichiers workflow YAML**. #151 n'en ajoute aucun : `v4-global-notify.yml` reste l'unique lane Global schedule, marketplace-first, avec un finalizer de registre vers l'issue #150.

L'API Actions peut conserver des records historiques de workflows supprimés ; **le tree Git courant est l'autorité**.

## Workflows permanents

| Workflow | Trigger réel | Statut / notes |
|---|---|---|
| `japan-edge-hunter.yml` | `workflow_dispatch` + cron | PROD Japan Edge ; ASK reste ASK. |
| `japan-edge-offline-validation.yml` | `workflow_dispatch` + PR ciblée | CI/offline Japan Edge. |
| `psa-api-diagnostic.yml` | `workflow_dispatch` | Diagnostic PSA manuel. |
| `robot-kb-cloud-shadow.yml` | `workflow_dispatch` + cron | Robot KB collecte séparée. |
| `robot-kb-sold-shadow.yml` | `workflow_dispatch` + cron | Robot KB SOLD/backfill strict. |
| `v4-auction-discovery-validation.yml` | `workflow_dispatch` + PR ciblée | CI/comparaison V4 read-only. |
| `v4-final-auction-check.yml` | `workflow_dispatch` | Fast Lane production, cadence externe. |
| `v4-gcc-coverage-audit.yml` | `workflow_dispatch` | Audit GCC manuel/read-only. |
| `v4-global-live-shadow.yml` | `workflow_dispatch` | Global manuel/read-only. |
| `v4-global-market-offline-validation.yml` | PR ciblée | CI Global + live marketplace-first read-only. |
| `v4-global-notify.yml` | `workflow_dispatch` + `41 * * * *` | **Unique lane Global production.** Marketplace-first + registre schedule #150. Manual toujours dry-run. |
| `v4-global-shadow-dispatch-ci.yml` | PR ciblée | Contrat dispatcher Global. |
| `v4-kb-shadow-ingest.yml` | `workflow_run` après succès V4 | Ingestion passive Robot KB/Neon. |
| `v5-gcc-catalog-refresh.yml` | `workflow_dispatch` + cron | Support V5 legacy actuel. |
| `v5-live-raw-pipeline-diagnostic.yml` | `workflow_dispatch` | V5 diagnostic manuel. |
| `watcher.yml` | `workflow_dispatch` | V4 Main Scanner, cadence externe Cron-job.org. |

---

# Global production après #151

```text
v4-global-notify.yml
 -> Resolve notification activation
 -> restore .global-marketplace-state
 -> v4_global_marketplace_notify_resilient.py
 -> marketplace inventory discovery
 -> pending queue (max 10/run initialement)
 -> TCGdex exact + bounded retry
 -> PPT / PokeTrace confirmation
 -> MULTIMARKET_CONFIRMED gate
 -> dedupe notification
 -> save state
 -> schedule-only registry finalizer -> issue #150
```

## Activation

- `.github/global-notify-activation=true` active les schedules si la repo var ne force rien ;
- `vars.GLOBAL_NOTIFY_ENABLED=true` supportée ;
- `vars.GLOBAL_NOTIFY_ENABLED=false` = kill switch prioritaire ;
- `workflow_dispatch` = toujours dry-run ;
- `NTFY_TOPIC` absent/vide = fail-closed avant scan.

## État durable

```text
.global-marketplace-state/discovery.json
.global-marketplace-state/notifications.json
```

Cache séparé par event `schedule` / `workflow_dispatch`. Discovery : bootstrap, puis new/changed/retryable. Disparition != SOLD.

## Schedule run registry #150

PR #151 ajoute au **même workflow** :

```text
permissions:
  contents: read
  issues: write
```

Le `issues: write` sert uniquement au commentaire automatique dans #150.

Finalizer :

- `if: always() && github.event_name == 'schedule'` ;
- lit `global_marketplace_out/global_marketplace_report.json` si disponible ;
- poste run_id/SHA/activation/outcome et métriques agrégées ;
- report absent/illisible => `report_status` explicite, sans fabriquer de métriques ;
- manual dispatch ne poste rien ;
- aucun log complet, secret, session ou donnée listing-level n'est copié.

Le registre V4 issue #1 reste séparé.

## Budgets / sécurité

```text
PPT max HTTP             12
PPT max credits          60
PPT daily floor          15000
TCGdex max attempts      2
TCGdex timeout           10 s
TCGdex backoff           0.25 s
```

- ASK/current auction != SOLD ;
- `ACTIVE_AUCTION` non actionnable ;
- `AUCTION_SNAPSHOT_LE5` observation uniquement ;
- aucune transaction, achat, bid, checkout ou paiement ;
- aucun gate identité relâché.

## Preuves

```text
#146 activation schedule        32379733361 SUCCESS
#147 final marketplace live     32397363626 SUCCESS
#148 cutover CI/live            32398465774 SUCCESS
#151 registry CI/live           32410224171 SUCCESS
#151 Global tests               203/203 PASS
#151 V4 regressions              51/51 PASS
#151 inventory                  1186
#151 selected/pending           10 / 1176
```

Le premier vrai commentaire #150 produit par un `schedule` post-#151 reste la preuve finale attendue du registre en production.

---

# Triggers automatiques permanents

GitHub cron :

```text
Japan Edge Hunter
Robot KB cloud shadow
Robot KB SOLD shadow
V5 GCC Catalog Refresh
V4 Global Confirmed Notifications @ minute 41
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

Ne jamais ajouter de cron GitHub parallèle au Main Scanner/Fast Lane/Global.

---

# Règle future

Avant d'ajouter/modifier un workflow :

1. vérifier le tree courant ;
2. rechercher la capacité existante ;
3. réutiliser le workflow consolidé ;
4. diagnostics ponctuels : préférer manuel ;
5. pas de second cron Main Scanner/Fast Lane/Global ;
6. pas de suppression workflow/branche/issue sans autorisation destructive ;
7. aucune transaction automatique.