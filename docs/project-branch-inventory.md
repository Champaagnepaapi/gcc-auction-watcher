# Robot Pokémon / GCC Auction Watcher — inventaire des branches

État pertinent vérifié le **20 août 2026**.

## Autorités

```text
production canonique              main
last functional/runtime merge     c012284c423e9526fd2712001fdbce3a5cfafda3
V5 expérimentale                  agent/v5-poketrace-cardmarket-market-data / PR #8
```

Des commits docs-only suivent le baseline runtime `c012284c...` sur `main`. Toujours re-vérifier le HEAD GitHub live avant une action.

PR #8 reste expérimentale/draft/non mergée ; ne jamais la merger dans `main` sans autorisation explicite.

## Comptage

Le dernier audit exhaustif, le 18 août, comptait 158 branches distantes. Plusieurs branches Global/diagnostic/docs ont été créées depuis. Le nombre courant n'a pas été reconstitué exhaustivement pendant cette fermeture ; ne pas présenter `158` comme nombre actuel.

Toute suppression de branche exige un nouvel audit exhaustif + autorisation explicite.

## Branches Global récentes

- `shadow/v4-global-current-main-reintegration-20260819` — PR #138, superseded par #139 ;
- `feat/v4-global-multivault-reintegration-20260819` — #139 ;
- `feat/v4-global-economic-confirmation-20260819` — #140, mergée ;
- `diag/v4-global-provider-coverage-20260820` — #141, diagnostic superseded ;
- `diag/v4-global-provider-coverage-20260820-check` ;
- `diag/v4-global-provider-coverage-20260820-final` ;
- `diag/v4-global-provider-coverage-20260820-impl` ;
- `diag/v4-global-provider-coverage-20260820-run` ;
- `diag/v4-global-provider-coverage-20260820-work` ;
- `fix/v4-global-external-exact-bridge-20260820` — #142, absorbée dans #140 ;
- `docs/v4-global-economic-confirmation-close-20260820` — #143, docs ;
- `docs/fix-global-runtime-baseline-wording-20260820` — correction docs-only de terminologie SHA.

Ces branches ne deviennent pas production ; `main` reste l'autorité.

## Historique à ne pas rejouer

- anciennes branches Global #108→#115 : absorbées par #139 ;
- PR #126 : superseded par #127→#135 ;
- one-shots/temp/diagnostics : provenance uniquement.

## Règle cleanup branches

1. inventaire distant exhaustif ;
2. PR/supersession ;
3. atteignabilité du SHA utile ;
4. références workflow ;
5. autorisation explicite ;
6. jamais de suppression V5/branche active par simple housekeeping.

Aucune branche n'a été supprimée pendant la phase Global.
