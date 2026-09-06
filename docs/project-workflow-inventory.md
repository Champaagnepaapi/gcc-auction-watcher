# Robot Pokémon / GCC Auction Watcher — inventaire workflows GitHub Actions

Audit re-vérifié le **6 septembre 2026** sur `main@9d3bb1b84d22c1534c24d7c58c5897ecce4b817f`.

Le tree Git courant est l'autorité pour l'existence des workflows. L'API Actions peut conserver des records historiques de workflows supprimés ou de triggers anciens.

## Règles d'architecture actuelles

- `watcher.yml` = **V4 Main Scanner production**, `workflow_dispatch`, cadence externe Cron-job.org ;
- `v4-final-auction-check.yml` = **Fast Lane production**, `workflow_dispatch`, cadence externe ;
- ne jamais ajouter de cron GitHub parallèle à ces deux lanes ;
- `v4-global-notify.yml` reste l'unique lane Global production ;
- Robot KB durable est sur PostgreSQL local Mac ; les writers Neon automatiques sont **OFF** ;
- les workflows Neon historiques existent encore uniquement comme chemins manuels bornés de rollback/recovery ;
- V5 live reste manuel/expérimental.

## Workflows clés

| Workflow | Trigger / rôle courant |
|---|---|
| `watcher.yml` | `workflow_dispatch` — Main Scanner V4 ; cadence externe. |
| `v4-final-auction-check.yml` | `workflow_dispatch` — Fast Lane ≤5 min ; cadence externe. |
| `v4-auction-discovery-validation.yml` | PR ciblée + manuel — tests V4, compile/YAML/diff et comparaison auction read-only. |
| `v4-global-market-offline-validation.yml` | validation Global/offline + live read-only selon contrat. |
| `v4-global-notify.yml` | unique lane Global production ; ne pas dupliquer. |
| `v4-global-live-shadow.yml` | manuel/read-only. |
| `v4-global-shadow-dispatch-ci.yml` | CI contrat dispatcher Global. |
| `v4-gcc-coverage-audit.yml` | audit GCC manuel/read-only. |
| `v4-cardova-public-validation.yml` | validation Cardova publique bornée. |
| `robot-kb-local-postgres-validation.yml` | CI Robot KB/P3/scripts Mac ; pas un writer production V4. |
| `robot-kb-cloud-shadow.yml` | **manual-only** rollback/recovery Neon ; automatic schedule retired. |
| `robot-kb-sold-shadow.yml` | **manual-only** rollback/recovery Neon ; automatic schedule retired. |
| `v4-kb-shadow-ingest.yml` | **manual-only** replay d'un run V4 vers legacy Neon ; ancien `workflow_run` auto retiré. |
| `psa-api-diagnostic.yml` | diagnostic PSA manuel. |
| `japan-edge-hunter.yml` | lane Japan Edge ; vérifier son trigger live avant modification. |
| `japan-edge-offline-validation.yml` | CI/offline Japan Edge. |
| `v5-gcc-catalog-refresh.yml` | support V5 legacy ; séparé de V4. |
| `v5-live-raw-pipeline-diagnostic.yml` | diagnostic V5 manuel ; PR #8 reste non-mergeable/non-production. |

## Main Scanner / Fast Lane

```text
Cron-job.org ~10 min
  -> workflow_dispatch
  -> watcher.yml
  -> V4 Main Scanner

Cron-job.org ~3 min
  -> workflow_dispatch
  -> v4-final-auction-check.yml
  -> Fast Lane
```

Le run Main Scanner naturel exact post-#255 observé est `34037829669` sur `9d3bb1...`. Ne pas lancer un deuxième scanner manuel pour fabriquer une preuve post-merge.

Fast Lane exact post-#255 : `34037049703` SUCCESS.

## Robot KB — état après cutover Mac

Les fichiers de workflows Neon restent dans le tree mais leurs triggers automatiques ont été retirés :

```text
robot-kb-cloud-shadow.yml   workflow_dispatch only
robot-kb-sold-shadow.yml    workflow_dispatch only
v4-kb-shadow-ingest.yml     workflow_dispatch only
```

Leurs commentaires YAML indiquent explicitement que l'automatisation Neon a été retirée après le cutover PostgreSQL local vérifié. Ils sont des chemins de rollback/recovery, pas des writers automatiques normaux.

Robot KB production durable : PostgreSQL local Mac, `V4_USE=false`. Neon = recovery manuel.

## Validation #254 / #255

```text
#254 V4 Auction Discovery Validation   34031695933 attempt 2 SUCCESS
#254 suite                             920 PASS / 2 skipped
#255 V4 Auction Discovery Validation   34036063564 SUCCESS
#255 V4 Global Market Offline          34036063610 SUCCESS
#255 Robot KB local PostgreSQL         34036063594 SUCCESS
```

## External SOLD phase

Ne pas créer un nouveau cron/provider collector GitHub simplement pour augmenter la couverture. Réutiliser d'abord :
- eBay V4 courant ;
- Robot KB eBay shadow ;
- Fanatics/Cardova research lanes historiques ;
- collectors PostgreSQL Mac existants.

Toute nouvelle collecte durable doit rester Robot KB-first, provenance datée, sémantique SOLD stricte, et séparée de V4 jusqu'à validation explicite.

## Règle avant ajout/modification workflow

1. vérifier le tree courant et les triggers exacts ;
2. rechercher la capacité existante ;
3. réutiliser/consolider plutôt que créer une lane parallèle ;
4. diagnostic ponctuel => manuel/read-only ;
5. pas de second cron Main Scanner/Fast Lane/Global ;
6. Neon automatique reste OFF sauf rollback explicitement autorisé ;
7. aucune suppression workflow/branche/issue sans autorisation destructive ;
8. aucune transaction, bid, achat, checkout ou paiement automatique.
