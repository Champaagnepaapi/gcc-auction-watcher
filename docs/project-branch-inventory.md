# Robot Pokémon / GCC Auction Watcher — inventaire des branches

État pertinent vérifié le **20 août 2026** après merge #148.

## Autorités

```text
production canonique              main @ ea9a69b375434031c935de8d25fcc12acd1a1c93
Global marketplace-first          feat/v4-global-marketplace-discovery-20260820 / PR #147 mergée
Global cutover production         ops/v4-global-marketplace-cutover-20260820 / PR #148 mergée
Global activation                 ops/v4-global-notify-activate-20260820 / PR #146 mergée
V5 expérimentale                  agent/v5-poketrace-cardmarket-market-data / PR #8
```

Toujours re-vérifier le HEAD GitHub live avant une action.

PR #8 reste expérimentale/draft/non mergée, head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f` ; ne jamais la merger dans `main` sans autorisation explicite.

## Comptage

Le dernier audit exhaustif, le 18 août, comptait 158 branches distantes. Plusieurs branches Global/diagnostic/docs ont été créées depuis. Le nombre courant n'a pas été reconstitué exhaustivement pendant cette phase ; ne pas présenter `158` comme nombre actuel.

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
- `docs/fix-global-runtime-baseline-wording-20260820` — correction docs-only ;
- `feat/v4-global-notification-activation-20260820` — PR #145 mergée ;
- `ops/v4-global-notify-activate-20260820` — PR #146 mergée, marker d'activation réelle ;
- `feat/v4-global-marketplace-discovery-20260820` — PR #147 mergée, merge `5a1b0f050098b560e812a4dc6e64a9f8d40a8897` ;
- `ops/v4-global-marketplace-cutover-20260820` — PR #148 mergée, merge `ea9a69b375434031c935de8d25fcc12acd1a1c93` ;
- `docs/v4-global-marketplace-cutover-close-20260820` — branche docs de fermeture courante.

`main` reste l'autorité après merge explicite. Les branches #147/#148 sont conservées comme provenance ; aucune suppression n'est autorisée implicitement.

## Historique à ne pas rejouer

- anciennes branches Global #108→#115 : absorbées par #139 ;
- PR #126 : superseded par #127→#135 ;
- ancien moteur Global seed-rotation : historique/benchmark uniquement après cutover #148 ;
- one-shots/temp/diagnostics : provenance uniquement.

## Règle cleanup branches

1. inventaire distant exhaustif ;
2. PR/supersession ;
3. atteignabilité du SHA utile ;
4. références workflow ;
5. autorisation explicite ;
6. jamais de suppression V5/branche active par simple housekeeping.

Aucune branche n'a été supprimée pendant cette phase.
