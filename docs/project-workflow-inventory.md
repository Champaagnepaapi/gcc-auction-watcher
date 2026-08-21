# Robot Pokémon / GCC Auction Watcher — inventaire workflows GitHub Actions

Audit vérifié le **21 août 2026** après #154 et pendant la préparation Robot KB #157.

## Résultat clé

`main` contient encore **16 fichiers workflow YAML** avant #157. La PR #157 ajoute **1 validation** `robot-kb-local-postgres-validation.yml`, donc le tree passera à **17** après merge de cette préparation.

**L'API Actions peut conserver des records historiques** même lorsqu'un YAML a disparu du tree courant ; **le tree Git courant est l'autorité** pour l'existence réelle d'un workflow.

Les trois writers Robot KB/Neon existants restent intentionnellement inchangés pendant #157 : le cutover cloud est interdit avant migration locale vérifiée.

`v4-global-notify.yml` reste l'**unique lane Global production** : #153 a changé sa cadence à toutes les 10 minutes, sans créer de second workflow/cron. #154 ne modifie aucun trigger.

## Workflows permanents / préparés

| Workflow | Trigger réel | Statut / notes |
|---|---|---|
| `japan-edge-hunter.yml` | `workflow_dispatch` + cron | PROD Japan Edge ; ASK reste ASK. |
| `japan-edge-offline-validation.yml` | `workflow_dispatch` + PR ciblée | CI/offline Japan Edge. |
| `psa-api-diagnostic.yml` | `workflow_dispatch` | Diagnostic PSA manuel. |
| `robot-kb-cloud-shadow.yml` | `workflow_dispatch` + cron | Robot KB Neon fixed/auction encore actif jusqu'au cutover Mac vérifié. |
| `robot-kb-sold-shadow.yml` | `workflow_dispatch` + cron | Robot KB Neon SOLD/backfill encore actif jusqu'au cutover Mac vérifié. |
| `robot-kb-local-postgres-validation.yml` | `workflow_dispatch` + PR ciblée | **#157** CI seulement : P3 + scripts Mac + contrat migration. Aucun collector cloud local. |
| `v4-auction-discovery-validation.yml` | `workflow_dispatch` + PR ciblée | CI/comparaison V4 read-only. |
| `v4-final-auction-check.yml` | `workflow_dispatch` | Fast Lane production, cadence externe. |
| `v4-gcc-coverage-audit.yml` | `workflow_dispatch` | Audit GCC manuel/read-only. |
| `v4-global-live-shadow.yml` | `workflow_dispatch` | Global manuel/read-only. |
| `v4-global-market-offline-validation.yml` | PR ciblée | CI Global + live marketplace-first read-only. |
| `v4-global-notify.yml` | `workflow_dispatch` + `1,11,21,31,41,51 * * * *` | **Unique lane Global production.** Marketplace-first + registre #150. Manual toujours dry-run. |
| `v4-global-shadow-dispatch-ci.yml` | PR ciblée | Contrat dispatcher Global. |
| `v4-kb-shadow-ingest.yml` | `workflow_run` après succès V4 | Ingestion passive Robot KB/Neon encore active jusqu'au cutover Mac vérifié. |
| `v5-gcc-catalog-refresh.yml` | `workflow_dispatch` + cron | Support V5 legacy actuel. |
| `v5-live-raw-pipeline-diagnostic.yml` | `workflow_dispatch` | V5 diagnostic manuel. |
| `watcher.yml` | `workflow_dispatch` | V4 Main Scanner, cadence externe Cron-job.org. |

---

# Robot KB — transition Neon → Mac

PR #157 **n'est pas le cutover**. Elle ajoute les scripts locaux sous `mac/robot-kb-local/` et une validation CI, tout en maintenant les writers Neon actifs.

Lane locale préparée :

```text
Mac LaunchAgent fixed     : minute 32 de chaque heure
Mac LaunchAgent SOLD      : minutes 17 et 47
Mac LaunchAgent backup    : 03:10
PostgreSQL                : 127.0.0.1 / robot_pokemon_kb
runtime                   : P3 @ 1d06fe33b6fc640657255e15a8d17251aa02b6ce
```

Ordre de cutover obligatoire :

1. installer PostgreSQL/runtime sur le Mac ;
2. dump Neon secret-safe ;
3. restore local ;
4. fingerprints source/local identiques + `MIGRATION_VERIFIED` ;
5. health-check local ;
6. seulement ensuite PR séparée retirant :
   - cron `robot-kb-cloud-shadow.yml` ;
   - cron `robot-kb-sold-shadow.yml` ;
   - `workflow_run` `v4-kb-shadow-ingest.yml`.

Aucun writer Neon n'est retiré dans #157.

---

# Global production

```text
v4-global-notify.yml
 -> Resolve notification activation
 -> restore .global-marketplace-state
 -> v4_global_marketplace_notify_resilient.py
 -> marketplace inventory discovery
 -> pending queue
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

La cadence augmente le nombre de batches, pas la taille d'un batch. #156 est une PR séparée qui expérimente le scale ; ne pas documenter son comportement comme production avant merge explicite.

## Schedule run registry #150

Le finalizer #151 :

- `if: always() && github.event_name == 'schedule'` ;
- poste run_id/SHA/activation/outcome + métriques agrégées ;
- aucun log complet, secret, session ou donnée listing-level ;
- manual dispatch ne poste rien ;
- registre V4 issue #1 séparé.

Le registre est **prouvé en production**. Premier record post-#151 : run `32411433425`, schedule, activation true, `GLOBAL_MARKETPLACE_NOTIFICATION_ACTIVE`, success, 0 notification, transactions false.

La cadence #153 est aussi observée en production. Run `32443663511` sur `e79e939c...` : success, activation true, inventory 1196, selected 10, pending 1137, 0 sent, transactions false.

## Budgets / sécurité production #154

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

---

# Triggers automatiques permanents avant cutover Mac

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
7. cutover Neon uniquement après migration Mac réellement vérifiée ;
8. aucune transaction automatique.