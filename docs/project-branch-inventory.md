# Robot Pokémon / GCC Auction Watcher — inventaire des branches

État pertinent re-vérifié le **7 septembre 2026** après les merges production #259/#260/#261.

> `main` est actuellement à `22303a34f7414769a04f4c587338def005b8a5c6` ; dernier SHA runtime #261 `24230552d52574e2769c21dcfa84ba11320da2cf`. Toujours re-vérifier le HEAD GitHub live avant une action.

## Autorités / branches récentes

```text
V4 production main                main / 22303a34f7414769a04f4c587338def005b8a5c6
V4 runtime #261                   24230552d52574e2769c21dcfa84ba11320da2cf
#259 integration source           integration/v4-recall-pricecharting-global-japan-20260906 / 7b444a242723b66894e02114fc6c8f2c0710ba24 / MERGED
#260 TCGdex recovery source       fix/v4-unique-fuzzy-name-recovery-20260906 / d809f4aacce0cbfb362546a65de351be2451dcf6 / MERGED
#261 cross-grader source          fix/v4-crossgrader-proxy-calibration-20260907 / c5e61d1b5377508ccf1a720959e0f7e09d570fbc / MERGED
#257 source-role foundation       fix/v4-source-role-pricecharting-20260906 / 68d8dec2880583cb40a824f48bcf3dd8c6ea4843 / MERGED
#258 recall source                tune/v4-recall-policy-20260906 / 85a72280876771feb5803df760b88fac105b591d / OPEN DRAFT / SUPERSEDED_BY_259
#256 Japan source                 v4-jp-market-providers-20260906 / 2ebf7bc07e757f2f6b3bcb1a59578fdfda927df1 / OPEN DRAFT / SUPERSEDED_BY_259
Old post-260 docs branch          docs/post-260-tcgdex-closeout-20260907 / b324ae538981eb99d6a91c15516c3db514e34b38 / HISTORICAL, DO NOT RESET/DELETE
Current consolidated closeout     docs/post-260-261-closeout-20260907 / ACTIVE DOCS ONLY
V5 expérimentale                  agent/v5-poketrace-cardmarket-market-data / #8 OPEN DRAFT
```

PR #8 reste expérimentale/draft/non mergée ; ne jamais la merger dans `main` sans autorisation explicite.

## Pourquoi deux branches de closeout le 7 septembre

`docs/post-260-tcgdex-closeout-20260907` a été créée sur le `main` post-#260. Pendant son édition, #261 a été mergée puis un closeout docs #261 a fait avancer `main`. Rebaser cette branche par reset aurait été destructif et aurait risqué d'écraser les docs #261. Elle est donc conservée comme provenance historique.

`docs/post-260-261-closeout-20260907` repart proprement du `main@22303a34...` et consolide seulement les documents de reprise. Aucune branche n'est supprimée.

## Comptage / provenance

Le dernier audit exhaustif historique connu comptait 158 branches distantes au 18 août ; ce nombre n'est plus actuel. Ne pas annoncer un total de branches sans nouvel audit exhaustif.

Toute suppression exige audit + autorisation explicite.

## Branches V4 / main récentes

- `integration/v4-recall-pricecharting-global-japan-20260906` — #259, intégration canonique des capacités #256/#257/#258, **MERGED** ;
- `fix/v4-unique-fuzzy-name-recovery-20260906` — #260, base `7cb0e067...`, head validé `d809f4aac...`, validation `34053317112` SUCCESS, merge production `db4954f5...` ;
- `fix/v4-crossgrader-proxy-calibration-20260907` — #261, base `db4954f5...`, code validé `c58aa4c...`, final head `c5e61d1...`, validation `34092254431` SUCCESS, merge runtime `24230552...` ;
- `fix/v4-source-role-pricecharting-20260906` — #257, foundation source-role/PriceCharting, **MERGED** puis incluse dans #259 ;
- `tune/v4-recall-policy-20260906` — #258, **OPEN/DRAFT/STALE_OPEN/SUPERSEDED_BY_259** ; ne pas merger ;
- `v4-jp-market-providers-20260906` — #256, **OPEN/DRAFT/STALE_OPEN/SUPERSEDED_BY_259** ; ne pas merger ;
- `docs/post-260-tcgdex-closeout-20260907` — ancienne branche docs-only post-#260, devenue provenance après merge concurrent #261 ; ne pas reset/delete sans autorisation ;
- `docs/post-260-261-closeout-20260907` — branche docs-only courante, basée sur `main@22303a34...`.

## Lignée eBay récente

- #250→#254 : diagnostics/résilience body/navigation/structured salvage, mergés sur main ;
- `diag/v4-ebay-navigation-salvage-reasons-20260904` — #248 OPEN/DRAFT mais superseded par la lignée #250→#254 ;
- anciennes branches #226/#228/#233 : superseded par #238/#239 puis les correctifs ultérieurs ;
- `validate/v4-ebay-bulk-live-benchmark-20260902` — #234 validation-only/inconclusive ; ne pas merger.

## Auction / TCGdex production provenance

- `fix/v4-poketrace-aggregate-quality-20260903` — #247, provenance historique ; politique agrégat ensuite modifiée par #259 ;
- `fix/v4-auction-pagination-default-preservation-20260903` — #245 MERGED ;
- #243/#244 — future-start runtime + closeout MERGED ;
- `fix/v4-auction-recovery-capacity-20260901` — #229 MERGED via #231 ;
- `merge/v4-auction-recovery-capacity-20260901` — #231 MERGED ;
- `validate/v4-auction-recovery-capacity-20260901` — #230 OPEN/DRAFT/DO NOT MERGE ;
- `fix/v4-tcgdex-source-outage-fallback-20260901` — #222 MERGED via #224 ;
- `merge/v4-tcgdex-source-outage-fallback-20260901` — #224 MERGED ;
- `fix/v4-tcgdex-transport-resilience-20260901` — #216 MERGED via #217 ;
- `merge/v4-tcgdex-transport-resilience-20260901` — #217 MERGED ;
- `fix/v4-upcoming-auction-start-guard-current-main-20260901` — #220 MERGED ;
- `fix/v4-external-pending-throughput-20260831` — #214 MERGED ;
- `fix/v4-auction-order-exhaustive-coverage-20260831` — #211 MERGED ;
- `merge/v4-auction-order-hardening-20260831` — #212 MERGED.

## Robot KB / P3 / Cardova

- `feat/robot-kb-print-run-rarity-symbol-20260831` — #207, mergée uniquement dans `agent/p3-postgres-durable-shadow`; aucune migration durable utilisateur exécutée ;
- `agent/p3-postgres-durable-shadow` — P3 durable/shadow séparé de `main` ;
- Cardova stack #199/#204/#205/#206/#208/#209/#210 — principalement OPEN/DRAFT ; aucun write durable par housekeeping ;
- #210 prépare un chemin durable avec backup/locks/autorisation explicite ; aucune exécution autorisée par défaut.

## V5

- `agent/v5-poketrace-cardmarket-market-data` — PR #8, OPEN/DRAFT/NON-MERGED ; head historiquement vérifié `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f` ;
- V5 et ses child/shadow ne sont pas des branches de production V4.

## Global / historique

- `feat/v4-global-marketplace-discovery-20260820` — provenance #147 ;
- `ops/v4-global-marketplace-cutover-20260820` — provenance #148 ;
- `ops/v4-global-run-registry-20260820` — provenance #151 ;
- `shadow/v4-global-current-main-reintegration-20260819` — #138 superseded par #139 ;
- #108/#109/#110/#113/#114/#115 — stack historique absorbé par #139 ;
- PR #126 : superseded par #127→#135 ;
- #159 superseded fonctionnellement par #177 ;
- anciens one-shots/temp/diagnostics = provenance uniquement.

## Règle cleanup branches

1. inventaire distant exhaustif ;
2. PR/supersession ;
3. atteignabilité du SHA utile ;
4. références workflow ;
5. fichiers/tests/docs uniques ;
6. autorisation explicite ;
7. jamais de suppression V5/P3/branche active par simple housekeeping ;
8. jamais de reset/force-push pour « remettre à jour » une branche de provenance.

Aucune branche n'est supprimée par ce closeout.
