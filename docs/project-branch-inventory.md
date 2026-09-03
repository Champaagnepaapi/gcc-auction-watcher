# Robot Pokémon / GCC Auction Watcher — inventaire des branches

État pertinent re-vérifié le **3 septembre 2026** après #237 et #238/#239.

> `main` runtime production est ancré à `0cab2f3868e80c7c0ed9e6829e44123a2ecd3005`. Toujours re-vérifier le HEAD GitHub live avant une action.

## Autorités

```text
V4 production                     main / 0cab2f3868e80c7c0ed9e6829e44123a2ecd3005
eBay bulk source                  fix/v4-ebay-bulk-result-extraction-current-main-post237-20260902 / #238 MERGED
eBay bulk merge mirror            merge/v4-ebay-bulk-result-extraction-20260903 / #239 MERGED
eBay duplicate exact branch       merge/v4-ebay-bulk-result-extraction-20260903-mirror / same 90741ac0... / NO PR / DO NOT DELETE WITHOUT AUTH
V4 registry rollover              fix/v4-run-registry-rollover-20260902 / #237 lineage MERGED
Auction recovery source           fix/v4-auction-recovery-capacity-20260901 / #229 MERGED
Auction recovery merge mirror     merge/v4-auction-recovery-capacity-20260901 / #231 MERGED
Auction recovery validation       validate/v4-auction-recovery-capacity-20260901 / #230 OPEN DRAFT DO NOT MERGE
TCGdex transport source           fix/v4-tcgdex-transport-resilience-20260901 / #216 MERGED
TCGdex transport mirror           merge/v4-tcgdex-transport-resilience-20260901 / #217 MERGED
TCGdex outage source              fix/v4-tcgdex-source-outage-fallback-20260901 / #222 MERGED
TCGdex outage mirror              merge/v4-tcgdex-source-outage-fallback-20260901 / #224 MERGED
Future-start guard                fix/v4-upcoming-auction-start-guard-current-main-20260901 / #220 MERGED
Auction order hardening           fix/v4-auction-order-exhaustive-coverage-20260831 / #211 MERGED
Auction order mirror              merge/v4-auction-order-hardening-20260831 / #212 MERGED
Robot KB P3 rarity-symbol         feat/robot-kb-print-run-rarity-symbol-20260831 / #207 MERGED TO P3 ONLY
V5 expérimentale                  agent/v5-poketrace-cardmarket-market-data / #8 OPEN DRAFT
Docs closeout current             docs/post-239-ebay-registry-closeout-20260903
```

PR #8 reste expérimentale/draft/non mergée ; ne jamais la merger dans `main` sans autorisation explicite.

## Comptage / provenance

Le **dernier audit exhaustif** connu, le 18 août, comptait **158 branches distantes**. Des branches ont été créées depuis : **ne pas présenter `158` comme nombre actuel** sans nouvel audit exhaustif.

Toute suppression exige audit + autorisation explicite. **Aucune branche n'a été supprimée** par cette phase.

## Branches V4 / main récentes

- `fix/v4-ebay-bulk-result-extraction-current-main-post237-20260902` — #238, head validé `90741ac0eaca42f90a6bc7fca816d347aaccafeb`; GitHub marque la PR mergée vers `0cab2f3868e80c7c0ed9e6829e44123a2ecd3005` ;
- `merge/v4-ebay-bulk-result-extraction-20260903` — #239, miroir non-draft du même head exact créé car le toggle Ready de #238 échouait sur `fullDatabaseId`; merge production `0cab2f3868e80c7c0ed9e6829e44123a2ecd3005` ;
- `merge/v4-ebay-bulk-result-extraction-20260903-mirror` — branche dupliquée accidentellement au même `90741ac0...`, sans PR ; provenance uniquement, **ne pas supprimer sans autorisation explicite** ;
- `fix/v4-run-registry-rollover-20260902` — lignée #236/#237, déplacement du registre actif vers issue #235 ; merge production `9fac4bd5cd8211731ee7eaf21bd0302e71fa3a88` ;
- `docs/post-239-ebay-registry-closeout-20260903` — branche docs/gouvernance courante, base `main@0cab2f...` ;
- `fix/v4-auction-recovery-capacity-20260901` — #229, head validé `f81f81d1cf349a298d07867e9750704a9ea0c2bd` ; capacité mergée via #231 ;
- `merge/v4-auction-recovery-capacity-20260901` — #231, merge production `b6a7c834264c062ea81b64c714e6916aa8bfe9f2` ;
- `validate/v4-auction-recovery-capacity-20260901` — #230, **OPEN/DRAFT/DO NOT MERGE**, validation historique ;
- `fix/v4-tcgdex-source-outage-fallback-20260901` — #222, capacité mergée via #224 ;
- `merge/v4-tcgdex-source-outage-fallback-20260901` — #224, merge `0be4dca95513e36f4e407ef7bac361fe488c1d36` ;
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

## Ancienne lignée eBay devenue provenance

- `fix/v4-ebay-bulk-result-extraction-20260901` et branches associées #226/#228/#233 : superseded par #238/#239 ; ne pas merger automatiquement ;
- `validate/v4-ebay-bulk-live-benchmark-20260902` — #234, validation read-only inconclusive ; ne pas merger.

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
