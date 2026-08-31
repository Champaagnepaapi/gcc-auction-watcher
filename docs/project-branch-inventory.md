# Robot Pokémon / GCC Auction Watcher — inventaire des branches

État pertinent vérifié le **21 août 2026** après merge #154 et préparation Robot KB #157.

> Addendum **31 août 2026** : le runtime V4 canonique est désormais `main@c2bb3890fcf6e98e29d3ccf937b42ae2fddbae09` après #214, qui augmente de façon bornée le débit `EXTERNAL_PENDING`. Aucun nouvel audit exhaustif du nombre total de branches n'a été effectué pendant cet addendum.

## Autorités

```text
production canonique              main @ c2bb3890fcf6e98e29d3ccf937b42ae2fddbae09
External pending throughput       fix/v4-external-pending-throughput-20260831 / PR #214 mergée
Auction order hardening           fix/v4-auction-order-exhaustive-coverage-20260831 / PR #211 mergée
Auction merge mirror              merge/v4-auction-order-hardening-20260831 / PR #212 mergée
Global marketplace-first          feat/v4-global-marketplace-discovery-20260820 / PR #147 mergée
Global cutover production         ops/v4-global-marketplace-cutover-20260820 / PR #148 mergée
Global schedule registry          ops/v4-global-run-registry-20260820 / PR #151 mergée
Global cadence 10 min             ops/v4-global-10min-cadence-20260820 / PR #153 mergée
TCGdex detailed variants          feat/v4-tcgdex-detailed-variants-20260820 / PR #154 mergée
Global activation                 ops/v4-global-notify-activate-20260820 / PR #146 mergée
Robot KB local migration          feat/robot-kb-local-postgres-mac-20260821 / PR #157 OPEN
V5 expérimentale                  agent/v5-poketrace-cardmarket-market-data / PR #8
```

Toujours re-vérifier le HEAD GitHub live avant une action.

PR #8 reste expérimentale/draft/non mergée, head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f` ; ne jamais la merger dans `main` sans autorisation explicite.

## Comptage

Le dernier audit exhaustif, le 18 août, comptait **158 branches distantes**. Plusieurs branches ont été créées depuis, dont #156/#157 ; **ne pas présenter `158` comme nombre actuel** sans nouvel audit exhaustif.

Toute suppression de branche exige un audit + autorisation explicite.

## Branches Global / V4 récentes

- `fix/v4-external-pending-throughput-20260831` — PR #214, head validé `5aa3acd3ea3d52bb2c5fca4cf8b0c0c0901ba595`, merge runtime `c2bb3890fcf6e98e29d3ccf937b42ae2fddbae09` ; porte P4/eBay à 16/run avec auctions eBay toujours max 4 et breakers/provider backoff inchangés ; provenance à conserver ;
- `fix/v4-auction-order-exhaustive-coverage-20260831` — PR #211, head validé `461e0ec57271901033426f3566f6ab1f6b38e86a`, capacité mergée dans `main` au merge runtime `20bd6aca88b37a07d8a0c28295c2fe4734f30d5e` ; provenance à conserver ;
- `merge/v4-auction-order-hardening-20260831` — PR #212, miroir non-draft du même head, créé uniquement parce que la mutation GraphQL ready-for-review du connecteur a échoué ; même capacité/runtime que #211 ;
- `shadow/v4-global-current-main-reintegration-20260819` — PR #138, superseded par #139 ;
- `feat/v4-global-multivault-reintegration-20260819` — #139 ;
- `feat/v4-global-economic-confirmation-20260819` — #140, mergée ;
- `diag/v4-global-provider-coverage-20260820` — #141, diagnostic superseded ;
- branches `diag/v4-global-provider-coverage-20260820-*` — diagnostics/provenance ;
- `fix/v4-global-external-exact-bridge-20260820` — #142, absorbée dans #140 ;
- `feat/v4-global-notification-activation-20260820` — #145 mergée ;
- `ops/v4-global-notify-activate-20260820` — #146 mergée ;
- `feat/v4-global-marketplace-discovery-20260820` — #147 mergée, merge `5a1b0f050098b560e812a4dc6e64a9f8d40a8897` ;
- `ops/v4-global-marketplace-cutover-20260820` — #148 mergée, merge `ea9a69b375434031c935de8d25fcc12acd1a1c93` ;
- `docs/v4-global-marketplace-cutover-close-20260820` — #149 docs mergée ;
- `ops/v4-global-run-registry-20260820` — #151 mergée, merge `c9539ca521f69b43b3d93e621fb21447a69f3fe7` ;
- `ops/v4-global-10min-cadence-20260820` — #153 mergée, merge `e79e939c22173a020d12cb8a0878aa682df2a7a5` ;
- `feat/v4-tcgdex-detailed-variants-20260820` — #154 mergée, merge `c3e3da39b79eb71cfdfc864bb865c4a4e7154e0c` ;
- `docs/v4-tcgdex-detailed-variants-close-20260821` — docs #155 ;
- `feat/v4-global-scale-15-20260821` — PR #156 OPEN, ligne Global séparée ;
- `feat/robot-kb-local-postgres-mac-20260821` — PR #157 OPEN, migration stockage Robot KB préparée ; Neon reste actif jusqu'au cutover local vérifié.

`main` reste l'autorité après merge explicite. Les branches fonctionnelles mergées sont conservées comme provenance ; aucune suppression n'est autorisée implicitement.

## Provenance importante conservée

Les branches suivantes restent utiles à l'audit historique, même lorsqu'elles sont superseded :

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