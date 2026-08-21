# Robot KB local PostgreSQL — cutover close 2026-08-21

## Décision

Robot KB utilise désormais PostgreSQL local sur le Mac mini comme writer durable actif. Les writers Neon automatiques sont retirés par PR #166, merge runtime `611edf469dfe5e5bfc46390ba6680b9c2ebe9fee`.

Neon n'est **pas supprimé** : les anciens workflows restent manual-only comme rollback/recovery borné.

## Preuve de migration

```text
source/local rows               1,087,015
source/local tables             35
verification                    exacte
marker                          MIGRATION_VERIFIED
health                          OK
schema versions                 [1, 2]
```

## Preuve de collecte locale avant cutover

```text
fixed observations acceptées    494
fresh SOLD nouveaux             6
historical SOLD acceptés        400
fresh WFP différés              102
historical WFP différés         209
strict_sales                    546
exact_tiers                     427
kb_first_ready                  27
grader_spreads                  0
V4_USE                          false
transactions                    false
```

Le backfill historique restait `complete=false` et continue automatiquement via la lane locale.

## Cadence locale

```text
fixed + auction                 LaunchAgent :32
SOLD fresh + backfill           LaunchAgent :17 / :47
backup                          LaunchAgent 03:10
retention backup                7 dumps complets locaux
```

## Cutover cloud #166

Automatismes retirés :

- cron de `.github/workflows/robot-kb-cloud-shadow.yml` ;
- cron de `.github/workflows/robot-kb-sold-shadow.yml` ;
- `workflow_run` de `.github/workflows/v4-kb-shadow-ingest.yml`.

Rollback conservé :

- les trois workflows restent `workflow_dispatch` ;
- `v4-kb-shadow-ingest.yml` exige un `source_run_id` explicite ;
- `ROBOT_KB_DATABASE_URL` n'est ni affiché ni modifié ;
- projet Neon conservé.

## Sécurité

- `WAITING_FOR_PAYMENT` n'est jamais persisté comme SOLD ;
- unknown non-final status reste fail-closed ;
- aucune modification V4/Global/V5 économique ;
- PR #8 non touchée ;
- PR #159 non touchée ;
- aucun achat, bid, checkout ou paiement.

## Suite

Laisser la base locale accumuler l'historique et terminer progressivement le backfill. Ne pas activer KB-first économiquement avant profondeur suffisante. Ne pas supprimer Neon avant une période d'observation locale satisfaisante.
