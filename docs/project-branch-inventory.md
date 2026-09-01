# Robot Pokémon / GCC Auction Watcher — inventaire des branches

État pertinent re-vérifié le **1 septembre 2026** après #222/#224.

> `main` runtime production est ancré à `0be4dca95513e36f4e407ef7bac361fe488c1d36` (#224). Toujours re-vérifier le HEAD GitHub live avant une action.

## Autorités

```text
V4 production                     main
V4 runtime production             0be4dca95513e36f4e407ef7bac361fe488c1d36
TCGdex transport resilience       fix/v4-tcgdex-transport-resilience-20260901 / #216 MERGED
TCGdex transport merge mirror     merge/v4-tcgdex-transport-resilience-20260901 / #217 MERGED
TCGdex outage fallback source     fix/v4-tcgdex-source-outage-fallback-20260901 / #222 MERGED
TCGdex outage merge mirror        merge/v4-tcgdex-source-outage-fallback-20260901 / #224 MERGED
Docs governance repair            fix/docs-capability-recovery-markers-20260901 / #223 MERGED
Robot KB configurator port        fix/robot-kb-configurer-executable-current-main-20260901 / #219 MERGED
Future-start guard                fix/v4-upcoming-auction-start-guard-current-main-20260901 / #220 MERGED
External pending throughput       fix/v4-external-pending-throughput-20260831 / #214 MERGED
Auction order hardening           fix/v4-auction-order-exhaustive-coverage-20260831 / #211 MERGED
Auction merge mirror              merge/v4-auction-order-hardening-20260831 / #212 MERGED
Robot KB P3 rarity-symbol         feat/robot-kb-print-run-rarity-symbol-20260831 / #207 MERGED TO P3 ONLY
V5 expérimentale                  agent/v5-poketrace-cardmarket-market-data / #8 OPEN DRAFT
Docs closeout current             docs/post-224-tcgdex-outage-fallback-closeout-20260901
```

PR #8 reste expérimentale/draft/non mergée, head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f` au dernier contrôle ; ne jamais la merger dans `main` sans autorisation explicite.

## Comptage

Le dernier audit exhaustif connu, le 18 août, comptait 158 branches distantes. Plusieurs branches ont été créées depuis ; **ne pas présenter `158` comme nombre actuel** sans nouvel audit exhaustif.

Toute suppression de branche exige audit + autorisation explicite.

## Branches V4 / main récentes

- `fix/v4-tcgdex-source-outage-fallback-20260901` — #222, head validé `4cd3b215267dfc504b535831d70637e42adfb247`, exact tested tree `8ae11e351add5e78b3765bfe410ab884ac649586`, capacité mergée via #224 ; provenance à conserver ;
- `merge/v4-tcgdex-source-outage-fallback-20260901` — #224, miroir non-draft du même head exact utilisé car le toggle Ready GitHub échoue sur `fullDatabaseId`; merge production `0be4dca95513e36f4e407ef7bac361fe488c1d36` ;
- `fix/docs-capability-recovery-markers-20260901` — #223, docs-only, merge `42b7ca686114f02ad0b72375b194c2c7390c1f38` ;
- `docs/post-224-tcgdex-outage-fallback-closeout-20260901` — branche docs-only courante, base `main@0be4dca95513e36f4e407ef7bac361fe488c1d36` ;
- `fix/v4-tcgdex-transport-resilience-20260901` — #216, validated runtime `53a7fd0a...`, capacité mergée via #217 au merge `03824158ac899cf142199c42d4525386a573bc15` ;
- `merge/v4-tcgdex-transport-resilience-20260901` — #217, miroir non-draft du même head `812faf3314747004949945e650e76ec9389973de` ;
- `fix/robot-kb-configurer-executable-current-main-20260901` — #219, merge `2aef339135df8b4a183ad4ba030b9e603ea9e696`, mode exécutable seulement ;
- `fix/v4-upcoming-auction-start-guard-current-main-20260901` — #220, head `eecf845942a60fc6585f592da7aff41f66be4af0`, merge `6a33ac33faa324f0fc1c6124fbb49bd736382b75` ; future-start auctions exclues avant économie ;
- `fix/v4-external-pending-throughput-20260831` — #214, merge runtime `c2bb3890fcf6e98e29d3ccf937b42ae2fddbae09` ;
- `fix/v4-auction-order-exhaustive-coverage-20260831` — #211, capacité mergée ;
- `merge/v4-auction-order-hardening-20260831` — #212, miroir de merge de la même capacité ;
- `feat/v4-global-marketplace-discovery-20260820` — #147 mergée ;
- `ops/v4-global-marketplace-cutover-20260820` — #148 mergée ;
- `ops/v4-global-run-registry-20260820` — #151 mergée ;
- `feat/v4-tcgdex-detailed-variants-20260820` — #154 mergée ;
- `ops/v4-global-notify-activate-20260820` — #146 mergée.

## Robot KB / P3 / Cardova

- `feat/robot-kb-print-run-rarity-symbol-20260831` — #207, **mergée uniquement dans `agent/p3-postgres-durable-shadow`**, merge `df32a19c237a75e4a1c3bb9dba938fd59fc09665`; aucune migration durable utilisateur exécutée ;
- `agent/p3-postgres-durable-shadow` — P3 durable/shadow, séparé de `main` ;
- Cardova stack #199/#204/#205/#206/#208/#209/#210 — branches stackées, principalement OPEN/DRAFT ; ne pas merger/écrire durablement par housekeeping ;
- #210 prépare un commit durable gardé par autorisation explicite + backup + locks ; aucune exécution durable autorisée par défaut.

## Global / historique

- `shadow/v4-global-current-main-reintegration-20260819` — #138 superseded par #139 ;
- #108/#109/#110/#113/#114/#115 — stack historique absorbé par #139 ;
- PR #126 : superseded par #127→#135 ;
- #159 — superseded fonctionnellement par #177 ;
- anciens one-shots/temp/diagnostics — provenance uniquement.

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

## Règle cleanup branches

1. inventaire distant exhaustif ;
2. PR/supersession ;
3. atteignabilité du SHA utile ;
4. références workflow ;
5. fichiers/tests/docs uniques ;
6. autorisation explicite ;
7. jamais de suppression V5/P3/branche active par simple housekeeping.

Aucune branche n'a été supprimée par ce closeout.
