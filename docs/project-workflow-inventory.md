# Robot Pokémon / GCC Auction Watcher — inventaire workflows GitHub Actions

Audit vérifié le **20 août 2026** après le merge marketplace-first #148.

## Résultat clé

Le tree `main` contient **16 fichiers workflow YAML**. #147/#148 n'ont créé aucun second workflow Global planifié : `v4-global-notify.yml` reste l'unique lane Global schedule et exécute désormais le runner marketplace-first.

L'API Actions peut conserver des records historiques de workflows supprimés ; **le tree Git courant est l'autorité** pour les YAML réellement déclenchables.

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
| `v4-global-market-offline-validation.yml` | PR ciblée | CI Global + live marketplace-first read-only sur PR pertinente. |
| `v4-global-notify.yml` | `workflow_dispatch` + `41 * * * *` | **Unique lane Global production, marketplace-first depuis #148.** Manual toujours dry-run. |
| `v4-global-shadow-dispatch-ci.yml` | PR ciblée | Contrat dispatcher Global. |
| `v4-kb-shadow-ingest.yml` | `workflow_run` après succès V4 | Ingestion passive Robot KB/Neon. |
| `v5-gcc-catalog-refresh.yml` | `workflow_dispatch` + cron | Support V5 legacy actuel. |
| `v5-live-raw-pipeline-diagnostic.yml` | `workflow_dispatch` | V5 diagnostic manuel. |
| `watcher.yml` | `workflow_dispatch` | V4 Main Scanner, cadence externe Cron-job.org. |

---

# Global production après #148

```text
v4-global-notify.yml
 -> Resolve notification activation
 -> restore .global-marketplace-state
 -> v4_global_marketplace_notify_resilient.py
 -> marketplace inventory discovery
 -> baseline/new/changed pending queue
 -> max 10 evaluations/run initialement
 -> TCGdex exact + bounded retry
 -> PPT / PokeTrace confirmation
 -> MULTIMARKET_CONFIRMED gate
 -> dedupe notification
 -> save state
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

Cache séparé par event `schedule` / `workflow_dispatch`.

Discovery : bootstrap complet, puis nouvelles annonces/changements utiles/retryables. Disparition != SOLD.

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
#148 Global tests               202/202 PASS
#148 V4 regressions              51/51 PASS
#148 GCC exact                  1172
#148 inventory                  1184
#148 selected/pending           10 / 1174
```

Le premier vrai run `schedule` **post-#148** doit encore être observé explicitement avant de revendiquer la preuve live production du nouveau runner.

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

Ne jamais ajouter de cron GitHub parallèle au Main Scanner/Fast Lane.

---

# Règle future

Avant d'ajouter/modifier un workflow :

1. vérifier le tree courant ;
2. rechercher la capacité existante ;
3. réutiliser le workflow consolidé quand possible ;
4. diagnostics ponctuels : préférer manuel ;
5. pas de second cron Main Scanner/Fast Lane/Global ;
6. ne pas supprimer workflow/branche/issue sans autorisation destructive explicite ;
7. aucune transaction automatique.