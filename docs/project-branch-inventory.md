# Robot Pokémon / GCC Auction Watcher — inventaire des branches

État pertinent vérifié le **24 août 2026** après merge #175.

## Autorités

```text
production canonique              main @ 950694d66b04112fc1182f0b21d6008bb4560204
Magi native identity              feat/v4-global-magi-native-identity-20260822 / #173 MERGED
Magi coverage active              feat/v4-global-magi-coverage-20260823 / #174 OPEN DRAFT
V4 eBay hard-hang fix             fix/v4-ebay-hard-hang-isolation-20260824 / #175 MERGED
Global marketplace-first          #147/#148 lineage / PROD
Global schedule registry          #151 / issue #150
Global scale                      #156 / PROD
Global schedule recovery          #169 / PROD
Robot KB local                    #166 / PostgreSQL local ACTIF
V5 expérimentale                  agent/v5-poketrace-cardmarket-market-data / PR #8
```

Toujours re-vérifier le HEAD GitHub live avant une action.

PR #8 reste expérimentale/draft/non mergée ; ne jamais la merger dans `main` sans autorisation explicite.

## Comptage

Le dernier audit exhaustif historique comptait plus de 158 branches distantes. Plusieurs branches ont été créées depuis ; **ne pas donner de nombre actuel sans nouvel audit exhaustif**.

Toute suppression de branche exige un audit + autorisation explicite.

## Branches Global / V4 récentes

- `feat/v4-global-multivault-reintegration-20260819` — #139 mergée ;
- `feat/v4-global-economic-confirmation-20260819` — #140 mergée ;
- `diag/v4-global-provider-coverage-20260820` — #141 diagnostic superseded ;
- `fix/v4-global-external-exact-bridge-20260820` — #142 absorbée dans #140 ;
- `feat/v4-global-notification-activation-20260820` — #145 mergée ;
- `ops/v4-global-notify-activate-20260820` — #146 mergée ;
- `feat/v4-global-marketplace-discovery-20260820` — #147 mergée ;
- `ops/v4-global-marketplace-cutover-20260820` — #148 mergée ;
- `ops/v4-global-run-registry-20260820` — #151 mergée ;
- `feat/v4-tcgdex-detailed-variants-20260820` — #154 mergée ;
- `feat/v4-global-scale-15-20260821` — #156 mergée ;
- `feat/robot-kb-local-postgres-mac-20260821` — #157 historique de préparation ; cutover final livré via #166 ;
- `feat/v4-global-fanatics-native-identity-*` — ligne #171 mergée ;
- `feat/v4-global-magi-native-identity-20260822` — #173 mergée, production prouvée ;
- `feat/v4-global-magi-coverage-20260823` — **#174 OPEN/DRAFT**, ligne Magi active ;
- `fix/v4-ebay-hard-hang-isolation-20260824` — #175 mergée, production prouvée ;
- `docs/v4-ebay-hang-closeout-20260824` — branche docs de closeout créée depuis `main@950694d...`.

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
- `main`.

## Historique à ne pas rejouer

- anciennes branches Global #108→#115 : absorbées par #139 ;
- PR #126 : superseded par #127→#135 ;
- ancien moteur Global seed-rotation : historique/benchmark après #148 ;
- one-shots/temp/diagnostics : provenance uniquement ;
- CLL/CLK Magi sans preuve catalogue exacte : ne pas réintroduire comme mapping supposé.

## Règle cleanup branches

1. inventaire distant exhaustif ;
2. PR/supersession ;
3. atteignabilité du SHA utile ;
4. références workflow ;
5. autorisation explicite ;
6. jamais de suppression V5/branche active par simple housekeeping.

Aucune branche n'a été supprimée pendant cette phase.
