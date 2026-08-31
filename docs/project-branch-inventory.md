# Robot Pokémon / GCC Auction Watcher — inventaire des branches

État pertinent complété le **31 août 2026** pour la phase V4 auction order hardening. Ce n'est pas un nouvel audit exhaustif de toutes les branches distantes.

## Autorités

```text
production canonique              main @ 20bd6aca88b37a07d8a0c28295c2fe4734f30d5e
auction hardening source          fix/v4-auction-order-exhaustive-coverage-20260831 / PR #211 / MERGED
auction hardening mirror          merge/v4-auction-order-hardening-20260831 / PR #212 / MERGED
Global marketplace-first          feat/v4-global-marketplace-discovery-20260820 / PR #147 mergée
Global cutover production         ops/v4-global-marketplace-cutover-20260820 / PR #148 mergée
Global schedule registry          ops/v4-global-run-registry-20260820 / PR #151 mergée
TCGdex detailed variants          feat/v4-tcgdex-detailed-variants-20260820 / PR #154 mergée
Global activation                 ops/v4-global-notify-activate-20260820 / PR #146 mergée
V5 expérimentale                  agent/v5-poketrace-cardmarket-market-data / PR #8
```

Toujours re-vérifier le HEAD GitHub live avant une action.

PR #8 reste expérimentale/draft/non mergée ; ne jamais la merger dans `main` sans autorisation explicite.

## Comptage

Le dernier audit exhaustif, le 18 août, comptait **158 branches distantes**. Plusieurs branches ont été créées depuis ; **ne pas présenter `158` comme nombre actuel** sans nouvel audit exhaustif.

Toute suppression de branche exige un audit + autorisation explicite.

## Branches Global / V4 récentes

- `fix/v4-auction-order-exhaustive-coverage-20260831` — PR #211, head validé `461e0ec57271901033426f3566f6ab1f6b38e86a`, capacité mergée dans `main` via #212 ; provenance à conserver ;
- `merge/v4-auction-order-hardening-20260831` — PR #212, miroir non-draft du même head uniquement pour contourner le bug GraphQL du toggle draft du connecteur ; merge runtime `20bd6aca88b37a07d8a0c28295c2fe4734f30d5e` ;
- `shadow/v4-global-current-main-reintegration-20260819` — PR #138, superseded par #139 ;
- `feat/v4-global-multivault-reintegration-20260819` — #139 ;
- `feat/v4-global-economic-confirmation-20260819` — #140, mergée ;
- `diag/v4-global-provider-coverage-20260820` — #141, diagnostic superseded ;
- branches `diag/v4-global-provider-coverage-20260820-*` — diagnostics/provenance ;
- `fix/v4-global-external-exact-bridge-20260820` — #142, absorbée dans #140 ;
- `feat/v4-global-notification-activation-20260820` — #145 mergée ;
- `ops/v4-global-notify-activate-20260820` — #146 mergée ;
- `feat/v4-global-marketplace-discovery-20260820` — #147 mergée ;
- `ops/v4-global-marketplace-cutover-20260820` — #148 mergée ;
- `ops/v4-global-run-registry-20260820` — #151 mergée ;
- `ops/v4-global-10min-cadence-20260820` — #153 mergée ;
- `feat/v4-tcgdex-detailed-variants-20260820` — #154 mergée ;
- `feat/v4-global-scale-15-20260821` — ligne Global historique/récente ;
- `feat/robot-kb-local-postgres-mac-20260821` — migration stockage Robot KB historique/récente.

`main` reste l'autorité après merge explicite. Les branches fonctionnelles mergées sont conservées comme provenance ; aucune suppression n'est autorisée implicitement.

## Provenance importante conservée

- `fix/v4-recover-existing-capabilities-20260817` ;
- `fix/v4-poketrace-deterministic-market-retrieval-20260817` ;
- `fix/v4-poketrace-exact-provider-bridges-20260818` ;
- `fix/v4-poketrace-preserve-provider-number-20260818` ;
- `fix/v4-poketrace-provider-bridges-after-127-20260818` ;
- `fix/v4-poketrace-ja-search-regression-20260818` ;
- `diag/v4-provider-rejection-observability-20260818` ;
- `agent/p0-card-knowledge-base-foundation` ;
- `agent/source-scout-benchmark-20260814` ;
- `feat/v4-global-multivault-edge-foundation` ;
- `tmp-noop-check` ;
- `oops-no-more` ;
- `main`.

## Historique à ne pas rejouer

- anciennes branches Global #108→#115 : absorbées par #139 ;
- PR #126 : superseded par #127→#135 ;
- ancien moteur Global seed-rotation : historique/benchmark après #148 ;
- one-shots/temp/diagnostics : provenance uniquement.

## Règle cleanup branches

1. inventaire distant exhaustif ;
2. PR/supersession ;
3. atteignabilité du SHA utile ;
4. références workflow ;
5. autorisation explicite ;
6. jamais de suppression V5/branche active par simple housekeeping.

Aucune branche n'a été supprimée pendant cette phase.