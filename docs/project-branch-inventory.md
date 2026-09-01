# Robot Pokémon / GCC Auction Watcher — inventaire des branches

État pertinent re-vérifié le **1 septembre 2026** après #227 et #229/#231.

> `main` runtime production est ancré à `b6a7c834264c062ea81b64c714e6916aa8bfe9f2`. Toujours re-vérifier le HEAD GitHub live avant une action.

## Autorités

```text
V4 production                     main / b6a7c834264c062ea81b64c714e6916aa8bfe9f2
Auction recovery source           fix/v4-auction-recovery-capacity-20260901 / #229 MERGED
Auction recovery merge mirror     merge/v4-auction-recovery-capacity-20260901 / #231 MERGED
Auction recovery validation       validate/v4-auction-recovery-capacity-20260901 / #230 OPEN DRAFT DO NOT MERGE
Docs marker repair                fix/docs-open-pr-inventory-marker-20260901 / #227 MERGED
TCGdex transport source           fix/v4-tcgdex-transport-resilience-20260901 / #216 MERGED
TCGdex transport mirror           merge/v4-tcgdex-transport-resilience-20260901 / #217 MERGED
TCGdex outage source              fix/v4-tcgdex-source-outage-fallback-20260901 / #222 MERGED
TCGdex outage mirror              merge/v4-tcgdex-source-outage-fallback-20260901 / #224 MERGED
Future-start guard                fix/v4-upcoming-auction-start-guard-current-main-20260901 / #220 MERGED
Auction order hardening           fix/v4-auction-order-exhaustive-coverage-20260831 / #211 MERGED
Auction order mirror              merge/v4-auction-order-hardening-20260831 / #212 MERGED
Robot KB P3 rarity-symbol         feat/robot-kb-print-run-rarity-symbol-20260831 / #207 MERGED TO P3 ONLY
V5 expérimentale                  agent/v5-poketrace-cardmarket-market-data / #8 OPEN DRAFT
Docs closeout current             docs/post-231-auction-recovery-capacity-closeout-20260901
```

PR #8 reste expérimentale/draft/non mergée ; ne jamais la merger dans `main` sans autorisation explicite.

## Comptage / provenance

Le **dernier audit exhaustif** connu, le 18 août, comptait **158 branches distantes**. Des branches ont été créées depuis : **ne pas présenter `158` comme nombre actuel** sans nouvel audit exhaustif.

Toute suppression exige audit + autorisation explicite. **Aucune branche n'a été supprimée** par cette phase.

## Branches V4 / main récentes

- `fix/v4-auction-recovery-capacity-20260901` — #229, head final validé `f81f81d1cf349a298d07867e9750704a9ea0c2bd`, même tree `0170d41c...`; GitHub la marque mergée vers le runtime #231 `b6a7c834...` ;
- `merge/v4-auction-recovery-capacity-20260901` — #231, miroir non-draft exact créé car le toggle Ready de #229 échouait sur `fullDatabaseId`; validation `33563438585` SUCCESS ; merge production `b6a7c834264c062ea81b64c714e6916aa8bfe9f2` ;
- `validate/v4-auction-recovery-capacity-20260901` — #230, validation temporaire combinant le fix + marqueur docs avant #227 ; **OPEN/DRAFT/DO NOT MERGE**, provenance seulement ;
- `fix/docs-open-pr-inventory-marker-20260901` — #227, docs-only, merge `4323822fa324f6f9a089a1e1447b41f611ea8b95` ;
- `docs/post-231-auction-recovery-capacity-closeout-20260901` — branche docs-only courante, base `main@b6a7c834...` ;
- `fix/v4-tcgdex-source-outage-fallback-20260901` — #222, capacité mergée via #224 ;
- `merge/v4-tcgdex-source-outage-fallback-20260901` — #224, miroir non-draft du même head exact ; merge `0be4dca95513e36f4e407ef7bac361fe488c1d36` ;
- `fix/v4-tcgdex-transport-resilience-20260901` — #216, capacité mergée via #217 ;
- `merge/v4-tcgdex-transport-resilience-20260901` — #217, miroir de merge ;
- `fix/v4-upcoming-auction-start-guard-current-main-20260901` — #220, merge `6a33ac33faa324f0fc1c6124fbb49bd736382b75` ;
- `fix/v4-external-pending-throughput-20260831` — #214, mergée ;
- `fix/v4-auction-order-exhaustive-coverage-20260831` — #211, mergée ;
- `merge/v4-auction-order-hardening-20260831` — #212, miroir de la même capacité ;
- `feat/v4-global-marketplace-discovery-20260820` — #147 mergée ;
- `ops/v4-global-marketplace-cutover-20260820` — #148 mergée ;
- `ops/v4-global-run-registry-20260820` — #151 mergée ;
- `feat/v4-tcgdex-detailed-variants-20260820` — #154 mergée ;
- `ops/v4-global-notify-activate-20260820` — #146 mergée.

## Robot KB / P3 / Cardova

- `feat/robot-kb-print-run-rarity-symbol-20260831` — #207, mergée uniquement dans `agent/p3-postgres-durable-shadow`; aucune migration durable utilisateur exécutée ;
- `agent/p3-postgres-durable-shadow` — P3 durable/shadow séparé de `main` ;
- Cardova stack #199/#204/#205/#206/#208/#209/#210 — principalement OPEN/DRAFT ; aucun write durable par housekeeping ;
- #210 prépare un chemin durable avec backup/locks/autorisation explicite ; aucune exécution autorisée par défaut.

## V5

- `agent/v5-poketrace-cardmarket-market-data` — PR #8, OPEN/DRAFT/NON-MERGED ;
- V5 et ses child/shadow ne sont pas des branches de production V4.

## Global / historique

- `feat/v4-global-marketplace-discovery-20260820` — provenance #147 ;
- `ops/v4-global-marketplace-cutover-20260820` — provenance #148 ;
- `ops/v4-global-run-registry-20260820` — provenance #151 ;
- `shadow/v4-global-current-main-reintegration-20260819` — #138 superseded par #139 ;
- #108/#109/#110/#113/#114/#115 — stack historique absorbé par #139 ;
- **PR #126 : superseded** par #127→#135 ;
- #159 superseded fonctionnellement par #177 ;
- anciens one-shots/temp/diagnostics = provenance uniquement.

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
