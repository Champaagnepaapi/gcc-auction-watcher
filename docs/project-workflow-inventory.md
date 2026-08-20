# Robot Pokémon / GCC Auction Watcher — inventaire workflows GitHub Actions

Audit vérifié le **20 août 2026** pendant la phase #145.

## Résultat clé

Le tree `main` de base contient **15 fichiers workflow YAML**. La branche #145 ajoute **1 workflow permanent** : `.github/workflows/v4-global-notify.yml`. Après merge éventuel de #145, le tree contiendrait donc **16 workflows**.

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
| `v4-global-market-offline-validation.yml` | PR ciblée | CI Global : tests + regressions V4 + compile/YAML/diff. |
| `v4-global-notify.yml` | `workflow_dispatch` + cron horaire `41 * * * *` | **Ajout #145. Default-off.** Manual = toujours dry-run ; schedule ne démarre que si `vars.GLOBAL_NOTIFY_ENABLED == 'true'`. Aucune transaction. |
| `v4-global-shadow-dispatch-ci.yml` | PR ciblée | Vérifie le contrat du dispatcher Global. |
| `v4-kb-shadow-ingest.yml` | `workflow_run` après succès V4 | Ingestion passive vers Robot KB/Neon. |
| `v5-gcc-catalog-refresh.yml` | `workflow_dispatch` + cron | Support V5 legacy ; ne pas supprimer sans audit dédié. |
| `v5-live-raw-pipeline-diagnostic.yml` | `workflow_dispatch` | V5 diagnostic manuel, aucune transaction/grading payant. |
| `watcher.yml` | `workflow_dispatch` | V4 production canonique, cadence externe Cron-job.org. |

## Global après #139/#140/#142 et #145

`v4-global-live-shadow.yml` reste volontairement **manuel/read-only**.

Le workflow #145 `v4-global-notify.yml` est une lane distincte de notification confirmée :

```text
Global exact offers
 -> TCGdex exact + retry transport borné Global-only
 -> PPT / PokeTrace confirmation
 -> MULTIMARKET_CONFIRMED uniquement
 -> déduplication persistante
 -> notification seulement si feature flag schedule explicitement activé
```

Invariants :

- `workflow_dispatch` force `GLOBAL_NOTIFY_ENABLED=false` : validation manuelle = dry-run ;
- schedule horaire existe mais le job scheduled est skip tant que `vars.GLOBAL_NOTIFY_ENABLED != 'true'` ;
- TTL déduplication 14 jours ; re-alert si baisse >=5 % ou expiration TTL ;
- rotation persistante des seeds ;
- retry TCGdex Global-only : max 2 tentatives, timeout 10 s, backoff 0.25 s ; échec final reste `ERROR`/fail-closed ;
- ASK/current auction != SOLD ;
- aucune transaction, achat, bid, checkout ou paiement.

Live dry-run #145 `32359861668` : TCGdex 5/5, PPT 4/5, PokeTrace 4/5, `sent=0`, safety PASS.

Les workflows one-shot utilisés pour les validations #142/#145 ont été **supprimés de la branche finale**. Les records Actions historiques peuvent rester visibles.

## Triggers automatiques permanents

GitHub cron déjà actif sur main :

```text
Japan Edge Hunter
Robot KB cloud shadow
Robot KB SOLD shadow
V5 GCC Catalog Refresh
```

Candidate #145, **désactivée par feature flag par défaut** :

```text
V4 Global Confirmed Notifications @ minute 41
  -> job SKIPPED sauf vars.GLOBAL_NOTIFY_ENABLED == 'true'
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

## Règle future

Avant d'ajouter un workflow :

1. vérifier le tree courant ;
2. rechercher la capacité dans l'historique/ledger ;
3. réutiliser un workflow consolidé quand il existe ;
4. préférer `workflow_dispatch` pour diagnostics ponctuels ;
5. ne jamais ajouter un cron GitHub parallèle au Main Scanner/Fast Lane ;
6. retirer les one-shots après leur validation ;
7. aucune transaction automatique.

Le nombre de records historiques Actions n'est pas le nombre de YAML réellement présents dans le tree.
