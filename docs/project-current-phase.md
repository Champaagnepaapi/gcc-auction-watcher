# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **21 août 2026** après le cutover Robot KB local.

## Autorité

```text
V4 production                  main
Global discovery               marketplace-first
Global scale                   PR #156 MERGED / batch 50
Global cadence                 10 min
Global schedule registry       issue #150 / PROUVÉ LIVE
Robot KB storage               PostgreSQL local Mac ACTIF
Robot KB cutover               PR #166 / 611edf469dfe5e5bfc46390ba6680b9c2ebe9fee
Neon writers                   AUTOMATIQUES OFF / rollback manuel conservé
V5                             PR #8 / draft / non mergée
```

Toujours re-vérifier le HEAD GitHub live ; des commits docs-only peuvent suivre le SHA runtime.

## Robot KB — phase active

La migration Neon → PostgreSQL local a été exécutée et vérifiée :

```text
lignes source/local            1,087,015
nombre de tables               35
marker                         MIGRATION_VERIFIED
PostgreSQL health              OK
schema versions                [1, 2]
```

Collecte locale prouvée :

```text
fixed/auction                  LaunchAgent :32
SOLD fresh + backfill          LaunchAgent :17 / :47
backup                         03:10 / 7 dumps locaux
fixed acceptés dernier run     494
fresh SOLD nouveaux            6
backfill SOLD                  400
strict_sales                   546
exact_tiers                    427
kb_first_ready                 27
V4_USE                         false
```

`WAITING_FOR_PAYMENT` reste non-SOLD et est différé. Le backfill historique est encore en progression (`complete=false`) mais fonctionne sans erreur et avance automatiquement.

PR #166 a retiré les déclencheurs automatiques Neon :

- `robot-kb-cloud-shadow.yml` : manual-only ;
- `robot-kb-sold-shadow.yml` : manual-only ;
- `v4-kb-shadow-ingest.yml` : replay manuel avec `source_run_id` explicite.

Le projet Neon n'est pas supprimé et aucun secret n'a été modifié. Il sert uniquement de rollback/recovery manuel pour l'instant.

## Global marketplace-first

PR #156 est en production :

```text
batch                          50/run
PPT                            35 HTTP / 180 credits / floor 15000
PokeTrace                      60 requests/run
```

Run production de preuve `32467460797` : success, 50 selected/acknowledged, 27 identités commerciales, 23 TCGdex exactes, 7 conflits, 18 sans confirmation externe, 0 notification, `transactions=false`.

## TCGdex

- `variants_detailed` reste la preuve de microvariante déterministe quand disponible.
- source pin japonais immuable prioritaire lorsqu'il existe.
- PR #159 reste séparée, ouverte/non mergée et doit être revalidée contre le `main` courant avant décision.
- aucune identité incertaine ne devient comparable exact.

## V5

PR #8 reste **OPEN / DRAFT / NON MERGED** sur `agent/v5-poketrace-cardmarket-market-data`.

Ne jamais merger #8 sans autorisation explicite utilisateur.

## Prochaine phase recommandée

1. Laisser le backfill PostgreSQL local continuer et surveiller health/logs/backups.
2. Accumuler davantage de SOLD exacts et tiers exacts avant toute activation KB-first.
3. Étudier séparément la persistance PPT/PokeTrace dans Robot KB si utile.
4. Garder Neon comme rollback manuel pendant une période d'observation ; ne pas le supprimer immédiatement.
5. Traiter PR #159 séparément si souhaité.

Aucun achat, bid, checkout ou paiement automatique.
