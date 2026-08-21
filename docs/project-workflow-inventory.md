# Robot Pokémon / GCC Auction Watcher — inventaire workflows GitHub Actions

Audit vérifié le **21 août 2026** après le merge #154.

## Résultat clé

Le tree `main` contient **16 fichiers workflow YAML**. L'API Actions peut conserver des records historiques de workflows supprimés ; **le tree Git courant est l'autorité**.

`v4-global-notify.yml` reste l'**Unique lane Global production** : #153 a changé sa cadence à toutes les 10 minutes, sans créer de second workflow/cron. #154 ne modifie aucun trigger.

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
| `v4-global-notify.yml` | `workflow_dispatch` + `1,11,21,31,41,51 * * * *` | **Unique lane Global production.** Marketplace-first + registre #150. Manual toujours dry-run. |
| `v4-global-shadow-dispatch-ci.yml` | PR ciblée | Contrat dispatcher Global. |
| `v4-kb-shadow-ingest.yml` | `workflow_run` après succès V4 | Ingestion passive Robot KB/Neon. |
| `v5-gcc-catalog-refresh.yml` | `workflow_dispatch` + cron | Support V5 legacy actuel. |
| `v5-live-raw-pipeline-diagnostic.yml` | `workflow_dispatch` | V5 diagnostic manuel. |
| `watcher.yml` | `workflow_dispatch` | V4 Main Scanner, cadence externe Cron-job.org. |

---

# Global production

```text
v4-global-notify.yml
 -> Resolve notification activation
 -> restore .global-marketplace-state
 -> v4_global_marketplace_notify_resilient.py
 -> marketplace inventory discovery
 -> pending queue (max 10/run)
 -> TCGdex exact + variants_detailed gate quand disponible
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

## Cadence #153

```text
1,11,21,31,41,51 * * * *
```

La cadence augmente le nombre de batches, pas la taille d'un batch : 10 évaluations/run et budgets provider/run inchangés. Même `concurrency`, aucun second cron.

## Schedule run registry #150

Le finalizer #151 :

- `if: always() && github.event_name == 'schedule'` ;
- poste run_id/SHA/activation/outcome + métriques agrégées ;
- aucun log complet, secret, session ou donnée listing-level ;
- manual dispatch ne poste rien ;
- registre V4 issue #1 séparé.

Le registre est **prouvé en production**. Premier record post-#151 : run `32411433425`, schedule, activation true, `GLOBAL_MARKETPLACE_NOTIFICATION_ACTIVE`, success, 0 notification, transactions false.

La cadence #153 est aussi observée en production. Run `32443663511` sur `e79e939c...` : success, activation true, inventory 1196, selected 10, pending 1137, 0 sent, transactions false.

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

## Preuves récentes

```text
#151 registry CI/live           32410224171 SUCCESS
first schedule registry proof   32411433425 SUCCESS
#153 10-min schedule proof      32443663511 SUCCESS
#154 detailed variants CI/live  32444255909 SUCCESS
#154 Global tests               221/221 PASS
#154 V4 regressions              51/51 PASS
#154 artifact                   9433579221
```

Le premier `schedule` contenant explicitement le merge #154 `c3e3da39...` reste à observer ; la validation read-only #154 est déjà verte.

---

# Triggers automatiques permanents

GitHub cron :

```text
Japan Edge Hunter
Robot KB cloud shadow
Robot KB SOLD shadow
V5 GCC Catalog Refresh
V4 Global Confirmed Notifications @ minutes 1,11,21,31,41,51
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