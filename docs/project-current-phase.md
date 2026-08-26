# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **26 août 2026** après merge de #177 et validation read-only de la correction de budget Magi #178.

## Autorité

```text
V4 production                  main @ 2114b20077605a96a3cf3211f225e1e774bbe9ea
Magi production               #174 + #177 MERGED
Magi budget candidate          #178 / OPEN / DRAFT / NON MERGED
Global discovery               marketplace-first
Global scale                   50 listings/run
Global cadence                 20 min (`1,21,41`)
Global schedule registry       issue #150 / PROUVÉ LIVE
Robot KB storage               PostgreSQL local Mac ACTIF
Robot KB cutover               PR #166
Neon writers                   AUTOMATIQUES OFF / rollback manuel conservé
V5                             PR #8 / OPEN / DRAFT / NON MERGED
```

Toujours re-vérifier le HEAD GitHub live ; des commits docs-only peuvent suivre le SHA runtime.

## Magi — saturation recovery observée puis corrigée sur #178

Baseline production prouvée après #174 : run `32893130902` SUCCESS, **31/96 EXACT**, `54 sold_listing`, budget recovery **36/36**.

Après #177, les schedules sont restés techniquement SUCCESS mais un run nocturne est descendu à **28/96 EXACT** avec `TCGDEX_BUDGET_EXHAUSTED`. Le problème était l'allocation du plafond recovery, pas un motif pour augmenter le plafond ou relâcher l'identité.

PR #178 : `V4 Global: protect Magi exact-card recovery budget`.

```text
branch                         fix/v4-global-magi-recovery-priority-20260826
validated head                 8fd51c34dd2550b4748dc790e17b74af8612b975
base main                      2114b20077605a96a3cf3211f225e1e774bbe9ea
CI/live run                    32943536626 SUCCESS
focused Global tests           409/409 PASS
V4 multimarket tests           51/51 PASS
compile/YAML/diff-check        PASS
```

Correction : le plafond total reste **36**. Les requêtes larges `sets/*` disposent d'un cap indépendant de **28** requêtes ; les **8** appels restants peuvent servir aux paires strictes `card_search + card_detail`. Cela rend la réserve indépendante de l'ordre des listings et empêche les recherches larges de consommer la preuve finale exacte.

Live read-only #178 :

```text
Magi candidates                96
Magi EXACT                     30
sold_listing                   55
japanese_set_name_unproven     5
target_catalog_unproven        4
target_japanese_card_name      2
TCGdex recovery total          36
nonpriority recovery           28
card_search                    4
card_detail                    4
set_coordinate                 19
set_detail                     1
sets_catalog                   1
sets_filtered                  7
TCGDEX_BUDGET_EXHAUSTED        0
notifications sent             0
identity gate relaxed          false
transactions                   false
```

Le `30/96` n'est pas une perte d'identité par rapport au baseline `31/96` : `sold_listing` est passé de **54 à 55** tandis que les classes de rejet non-SOLD restent exactement `4 + 5 + 2 = 11`. La couverture du sous-ensemble encore actif est donc conservée et la saturation recovery est supprimée.

#178 reste **NON MERGED** jusqu'à autorisation explicite utilisateur.

## Global marketplace-first

Production actuelle :

```text
batch                          50/run
PPT                            35 HTTP / 180 credits / floor 15000
PokeTrace                      60 requests/run
cadence                        20 min
inner timeout                  17 min
job timeout                    25 min
```

Le workflow Global production reste `.github/workflows/v4-global-notify.yml`. Le live #178 était explicitement read-only : notifications désactivées et aucun achat/bid/checkout/paiement.

## Robot KB

La migration Neon → PostgreSQL local est exécutée et vérifiée :

```text
lignes source/local            1,087,015
nombre de tables               35
marker                         MIGRATION_VERIFIED
PostgreSQL health              OK
schema versions                [1, 2]
```

Collecte locale :

```text
fixed/auction                  LaunchAgent :32
SOLD fresh + backfill          LaunchAgent :17 / :47
backup                         03:10 / 7 dumps locaux
V4_USE                         false
```

Neon reste uniquement rollback/recovery manuel. Robot KB n'est pas encore un hard gate économique V4.

## V5

PR #8 reste **OPEN / DRAFT / NON MERGED** sur `agent/v5-poketrace-cardmarket-market-data`.

Ne jamais merger #8 sans autorisation explicite utilisateur.

## Prochaine phase recommandée

1. Merger #178 seulement après autorisation explicite utilisateur.
2. Après merge, vérifier le premier schedule production : budget `<=36`, nonpriority `<=28`, aucun `TCGDEX_BUDGET_EXHAUSTED` évitable et aucune identité exacte perdue.
3. Pour les cinq set-name restantes, n'accepter qu'une nouvelle classe déterministe prouvée ; sinon laisser bloqué.
4. Laisser Robot KB accumuler les SOLD exacts et poursuivre le backfill local.
5. Garder PR #8 V5 isolée et non mergée.

Aucun achat, bid, checkout ou paiement automatique.
