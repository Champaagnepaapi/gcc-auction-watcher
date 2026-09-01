# Robot Pokémon / GCC Auction Watcher — inventaire des branches

État pertinent re-vérifié le **1 septembre 2026** pendant la validation de PR #216.

> Le HEAD GitHub `main` est `1911ba5cdfd60d4dbc57dbb8ba07c42d3f22aea9` (docs #215) ; le runtime V4 actif reste `c2bb3890fcf6e98e29d3ccf937b42ae2fddbae09` après #214. La branche `fix/v4-tcgdex-transport-resilience-20260901` / PR #216 est un candidat non mergé.

## Autorités

```text
main GitHub / docs                1911ba5cdfd60d4dbc57dbb8ba07c42d3f22aea9
V4 runtime production             c2bb3890fcf6e98e29d3ccf937b42ae2fddbae09
TCGdex outage candidate           fix/v4-tcgdex-transport-resilience-20260901 / PR #216 OPEN DRAFT NON MERGED
#216 runtime validé                53a7fd0a47d100d851c347c3fadb79e4f754d07b
External pending throughput       fix/v4-external-pending-throughput-20260831 / PR #214 mergée
Auction order hardening           fix/v4-auction-order-exhaustive-coverage-20260831 / PR #211 mergée
Auction merge mirror              merge/v4-auction-order-hardening-20260831 / PR #212 mergée
Global marketplace-first          feat/v4-global-marketplace-discovery-20260820 / PR #147 mergée
Global cutover production         ops/v4-global-marketplace-cutover-20260820 / PR #148 mergée
Global schedule registry          ops/v4-global-run-registry-20260820 / PR #151 mergée
TCGdex detailed variants          feat/v4-tcgdex-detailed-variants-20260820 / PR #154 mergée
Global activation                 ops/v4-global-notify-activate-20260820 / PR #146 mergée
Robot KB local migration          feat/robot-kb-local-postgres-mac-20260821 / provenance Robot KB séparée
V5 expérimentale                  agent/v5-poketrace-cardmarket-market-data / PR #8
```

Toujours re-vérifier le HEAD GitHub live avant une action.

PR #8 reste expérimentale/draft/non mergée, head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f` ; ne jamais la merger dans `main` sans autorisation explicite.

## Comptage

Le dernier audit exhaustif, le 18 août, comptait **158 branches distantes**. Plusieurs branches ont été créées depuis ; **ne pas présenter `158` comme nombre actuel** sans nouvel audit exhaustif.

Toute suppression de branche exige un audit + autorisation explicite.

## Branches Global / V4 récentes

- `fix/v4-tcgdex-transport-resilience-20260901` — PR #216 **OPEN / DRAFT / NON MERGED**, runtime validé `53a7fd0a47d100d851c347c3fadb79e4f754d07b` ; réutilise la résilience TCGdex #145 et le pattern breaker #189 avec circuit Main-only après 2 appels logiques transitoires épuisés ; aucune identité/fair value/notification modifiée ; ne pas merger sans autorisation explicite ;
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
- `ops/v4-global-10min-cadence-20260820` — #153 historique cadence ;
- `feat/v4-tcgdex-detailed-variants-20260820` — #154 mergée, merge `c3e3da39b79eb71cfdfc864bb865c4a4e7154e0c` ;
- `docs/v4-tcgdex-detailed-variants-close-20260821` — docs #155 ;
- `feat/v4-global-scale-15-20260821` — provenance Global scale ;
- `feat/robot-kb-local-postgres-mac-20260821` — provenance Robot KB locale ; garder Robot KB séparé de V4.

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
