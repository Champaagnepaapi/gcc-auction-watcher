# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **26 août 2026** après merge de #178, #179 et #180.

## Autorité

```text
V4 runtime production           main @ 9365f5cd9f8949580c4e48f00ba8c4e419c22145
Magi production                 #174 + #177 + #178 MERGED
Global schedule watchdog        #179 MERGED
Global discovery                marketplace-first
Global scale                    50 listings/run
Global cadence                  20 min (`1,21,41`)
Global schedule registry        issue #150 / PROUVÉ LIVE
Robot KB storage                PostgreSQL local Mac ACTIF
Robot KB cutover                #166 MERGED
Robot KB multisource            #180 MERGED / Mac install PENDING
Neon writers                    AUTOMATIQUES OFF / rollback manuel conservé
V5                              PR #8 / OPEN / DRAFT / NON MERGED
```

Toujours re-vérifier le HEAD GitHub live ; les commits docs-only peuvent suivre le SHA runtime.

## Magi / Global

#178 est en production. Le plafond recovery reste **36**, avec broad/nonpriority **28** et réserve **8** pour les preuves strictes `card_search + card_detail`. Validation read-only : run `32943536626` SUCCESS, `TCGDEX_BUDGET_EXHAUSTED=0`, identité non relâchée, aucune transaction.

#179 ajoute le rattrapage borné des schedules Global manqués depuis le heartbeat Main Scanner sans créer de seconde lane économique.

## Robot KB — #180 mergée

PR #180 `Robot KB: harvest multi-vault and paid market history locally` est mergée.

```text
feature head                    4194730490efbf879188069de4cc4d17642aad46
merge main                      9365f5cd9f8949580c4e48f00ba8c4e419c22145
Robot KB CI                     32999776457 SUCCESS
V4 validation                   32999776492 SUCCESS
Mac physical install            PENDING
```

Le code ajoute : Fanatics/COMC/Magi/Cardova publics, PokeTrace US/EU EN/JP single-card et PokemonPriceTracker EN/JP. ASK reste ASK ; `SOLD_AGGREGATED` reste agrégé et n'est jamais transformé en vente item-level.

Après installation réelle sur le Mac :

```text
public multi-vault              toutes les 2 h à :05
PokeTrace/PPT                   01:08 / 07:08 / 13:08 / 19:08
PPT reserve                     15000
PokeTrace reserve               5000
V4_USE                          false
```

Les clés PokeTrace/PPT restent uniquement dans le Trousseau macOS. Le merge ne prouve pas encore que les nouveaux LaunchAgents sont installés/chargés : c'est la prochaine vérification.

## Prochaine phase

1. Exécuter l'installateur #180 sur le Mac depuis le `main` courant.
2. Vérifier les quatre LaunchAgents historiques/nouveaux, les logs et les premiers catch-ups.
3. Vérifier les nouvelles observations PostgreSQL et l'absence de secret hors Trousseau.
4. Garder `V4_USE=false` ; Robot KB reste séparé du gate économique.
5. Garder PR #8 V5 isolée et non mergée.

Aucun achat, bid, checkout ou paiement automatique.
