# Robot Pokémon / GCC Auction Watcher — inventaire des branches

## État vérifié — 15 septembre 2026

Autorité production :

```text
V4 production main                 main / 3c596370ee7fcde93c969139541bc003e7012b6e
#268 source                         fix/v4-global-coverage-losses-20260907 / MERGED
#271 PokeTrace FREE                 fix/v4-poketrace-free-ceiling-production-20260914 / 75eb09768bf55d002466c5e3d50b038c3884ceb5 / OPEN DRAFT
#273 Fanatics diagnostic            diag/v4-fanatics-ppt-variant-proof-20260914 / c31882e8adacff8c291a43e78eb8ab6712ff2359 / OPEN DRAFT / DIAGNOSTIC_ONLY
post-#268 docs closeout             docs/post-268-closeout-20260914 / ACTIVE DOCS-ONLY
#270 Robot KB Magi snapshots        feat/robot-kb-magi-sold-marked-snapshots-20260907 / 9232931fbbc2cc6c970850e0f8c4d7eac69a46e8 / OPEN DRAFT / ROBOT_KB_ONLY
#269 exact-coordinate branch        fix/v4-coordinate-authoritative-card-identity-20260907 / a94d5009f556969e242fa16babb6aea14f3f8a31 / OPEN DRAFT / RE-AUDIT REQUIRED
V5 expérimentale                   agent/v5-poketrace-cardmarket-market-data / #8 OPEN DRAFT / PROTECTED
P3 durable shadow                  agent/p3-postgres-durable-shadow / SEPARATE FROM MAIN
```

Le worktree local historique `/Users/dylanduarte/.codex/.chatgpt-projects/g-p-6a7a34b31aa081919bbc38dfbb210097/work/gcc-auction-watcher` n'est pas supposé accessible ni synchronisé. GitHub réel reste l'autorité pour cet inventaire.

## Branche production

`main@3c596370ee7fcde93c969139541bc003e7012b6e` contient #268 et constitue V4 production canonique.

Premier Main Scanner naturel post-#268 vérifié : `34886292095` **SUCCESS** sur ce SHA.

Le classement provider actuel est : GCC `OPERATIONAL`; Fanatics, COMC, Magi, Cardova, Mercari et SNKRDUNK `PROVIDER_BLOCKED`.

## Branche #271 — PokeTrace FREE

`fix/v4-poketrace-free-ceiling-production-20260914`

- head `75eb09768bf55d002466c5e3d50b038c3884ceb5` ;
- base `main@3c596370...` ;
- PR #271 OPEN/DRAFT/NON MERGED ;
- validations Global `34879803090`, Auction `34879802895`, Cardova `34879802823` : SUCCESS ;
- corrige uniquement le plafond PokeTrace FREE des entrypoints production ;
- aucun merge sans autorisation explicite.

## Branche #273 — Fanatics diagnostic

`diag/v4-fanatics-ppt-variant-proof-20260914`

- head `c31882e8adacff8c291a43e78eb8ab6712ff2359` ;
- PR #273 OPEN/DRAFT ;
- workflow diagnostic `34886340368` SUCCESS ;
- lecture seule, aucune mutation runtime ;
- le plancher PPT a empêché un appel lorsque le budget restant était trop bas ;
- branche diagnostique, **non destinée au merge production**.

Ne pas baisser le plancher PPT ou relâcher l'identité pour forcer un diagnostic. Shining Mewtwo reste matériellement ambigu ; Fanatics reste `PROVIDER_BLOCKED` indépendamment du cas Litten à cause du coût acheteur final non prouvé.

## Branche de closeout docs post-#268

`docs/post-268-closeout-20260914`

Cette branche part du `main@3c596370...` et ne doit contenir que de la documentation. Elle met à jour README/phase courante/ledger/inventaires après le merge #268 et les observations post-merge #271/#273.

Aucune PR de merge n'était ouverte pour cette branche au contrôle du 15 septembre 2026. Aucun merge n'est implicite.

## Branches V4 récentes / supersessions

- `integration/v4-recall-pricecharting-global-japan-20260906` — #259, **MERGED**, intégration canonique de #256/#257/#258 ;
- `fix/v4-unique-fuzzy-name-recovery-20260906` — #260, **MERGED**, constrained TCGdex recovery ;
- `fix/v4-crossgrader-proxy-calibration-20260907` — #261, **MERGED** ;
- `fix/v4-source-role-pricecharting-20260906` — #257, **MERGED** puis absorbée dans #259 ;
- `tune/v4-recall-policy-20260906` — #258, **OPEN/DRAFT/STALE_OPEN/SUPERSEDED_BY_259** ;
- `v4-jp-market-providers-20260906` — #256, **OPEN/DRAFT/STALE_OPEN/SUPERSEDED_BY_259** ;
- `fix/v4-global-coverage-losses-20260907` — #268, **MERGED** dans main ;
- `fix/v4-coordinate-authoritative-card-identity-20260907` — #269, OPEN/DRAFT, branche large basée avant #268 ; ne pas merger sans nouveau reuse audit ;
- `fix/v4-poketrace-free-ceiling-production-20260914` — #271, OPEN/DRAFT, validation verte, autorisation explicite requise ;
- `diag/v4-fanatics-ppt-variant-proof-20260914` — #273, OPEN/DRAFT diagnostic-only ;
- `docs/post-268-closeout-20260914` — docs-only active ;
- `docs/post-260-tcgdex-closeout-20260907` — provenance historique, ne pas reset/delete ;
- `docs/post-260-261-closeout-20260907` — #262, **MERGED**.

## eBay / Auction / TCGdex provenance

- #250→#254 : diagnostics/résilience eBay, mergés ;
- `diag/v4-ebay-navigation-salvage-reasons-20260904` — #248 OPEN/DRAFT mais superseded ;
- `validate/v4-ebay-bulk-live-benchmark-20260902` — #234 validation-only/inconclusive ;
- `fix/v4-auction-pagination-default-preservation-20260903` — #245 MERGED ;
- #243/#244 — future-start runtime + closeout MERGED ;
- `fix/v4-auction-recovery-capacity-20260901` + `merge/v4-auction-recovery-capacity-20260901` — #229/#231 MERGED ;
- `validate/v4-auction-recovery-capacity-20260901` — #230 OPEN/DRAFT/DO NOT MERGE ;
- #222/#224 — TCGdex outage fallback MERGED ;
- #216/#217 — TCGdex transport resilience MERGED ;
- #220 — future-start guard MERGED ;
- #214 — external pending throughput MERGED ;
- #211/#212 — auction order hardening MERGED.

## Robot KB / P3 / Cardova

- `feat/robot-kb-magi-sold-marked-snapshots-20260907` — #270 OPEN/DRAFT, Robot KB seulement ; un SOLD-marked n'est pas une vente finale prouvée ;
- `feat/robot-kb-print-run-rarity-symbol-20260831` — #207 mergée uniquement dans P3 ;
- `agent/p3-postgres-durable-shadow` — P3 séparé de `main` ;
- Cardova stack #199/#204/#205/#206/#208/#209/#210 — durable/shadow ;
- #210 exige autorisation explicite + backup + locks + preflight avant toute écriture durable.

Aucune action V4 ne doit déclencher une écriture Neon/Robot KB durable par défaut.

## V5

`agent/v5-poketrace-cardmarket-market-data`

- PR #8 OPEN/DRAFT/NON MERGED ;
- head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f` ;
- V5 et ses child/shadow ne sont pas des branches V4 production ;
- ne jamais merger #8 dans `main` sans autorisation explicite utilisateur.

## Nettoyage / suppression

Le dernier audit exhaustif historique connu n'est pas un compteur actuel. Ne pas annoncer un nombre courant de branches sans nouvel audit exhaustif.

Toute suppression de branche exige :

1. inventaire distant ;
2. PR/supersession ;
3. atteignabilité du SHA utile ;
4. références workflow ;
5. fichiers/tests/docs uniques ;
6. autorisation explicite ;
7. aucun reset/force-push pour remettre une branche de provenance « à jour ».

Aucune branche n'a été supprimée par ce closeout.
