# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **25 août 2026** après merge et première preuve production de la PR #174.

## Autorité

```text
V4 production                  main
runtime Magi                   #174 / 3d1589e0086c264e9f910a15fb6b037e20938970
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

## Magi — phase #174 fermée en production

PR #174 est mergée :

```text
feature head                   593c417ec526aba39f7d388bb3a61d868650c15a
merge                          3d1589e0086c264e9f910a15fb6b037e20938970
```

Premier schedule Global production post-merge : **run `32893130902` SUCCESS**.

```text
mode                           GLOBAL_MARKETPLACE_NOTIFICATION_ACTIVE
activation                     true
Magi candidates                96
Magi EXACT                     31
sold_listing                   54
japanese_set_name_unproven     5
target_catalog_unproven        4
target_japanese_card_name      2
TCGdex recovery requests       36
notifications sent             0
identity gate relaxed          false
transactions                   false
```

Le plafond recovery reste **36**. Les cinq `japanese_set_name_unproven` ne doivent pas être forcées par un fallback name-only ou des aliases carte-par-carte.

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

Le schedule `32893130902` a restauré l'état précédent, traité 50 listings, sauvegardé le nouvel état et enregistré le run dans issue #150.

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

## PR séparée encore pertinente

PR #159 reste ouverte pour Battle Partners TCGdex exact. Elle n'est pas incluse dans #174 et doit être revalidée sur le `main` courant avant décision.

## Prochaine phase recommandée

1. Surveiller quelques schedules Global post-#174 pour confirmer la stabilité de `31/96` Magi sans dérive du budget recovery.
2. Pour les cinq set-name restantes, n'accepter qu'une nouvelle classe déterministe prouvée ; sinon laisser bloqué.
3. Traiter #159 séparément si utile.
4. Laisser Robot KB accumuler les SOLD exacts et poursuivre le backfill local.
5. Garder PR #8 V5 isolée et non mergée.

Aucun achat, bid, checkout ou paiement automatique.
