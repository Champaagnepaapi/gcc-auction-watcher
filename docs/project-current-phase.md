# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **26 août 2026** après merge de #178, #179 et #180, puis premier run physique #180 sur le Mac.

## Autorité

```text
V4 runtime production           main @ 9365f5cd9f8949580c4e48f00ba8c4e419c22145
main docs closeout              4ac5873aca02fa4d4dddf6f3e92247a29d71b03c
Magi production                 #174 + #177 + #178 MERGED
Global schedule watchdog        #179 MERGED
Global discovery                marketplace-first
Global scale                    50 listings/run
Global cadence                  20 min (`1,21,41`)
Global schedule registry        issue #150 / PROUVÉ LIVE
Robot KB storage                PostgreSQL local Mac ACTIF
Robot KB cutover                #166 MERGED
Robot KB multisource            #180 MERGED / LaunchAgents INSTALLÉS
Robot KB first-live repair      #181 OPEN / DRAFT / NON MERGED
Neon writers                    AUTOMATIQUES OFF / rollback manuel conservé
V5                              PR #8 / OPEN / DRAFT / NON MERGED
```

Toujours re-vérifier le HEAD GitHub live ; les commits docs-only peuvent suivre le SHA runtime.

## Magi / Global

#178 est en production. Le plafond recovery reste **36**, avec broad/nonpriority **28** et réserve **8** pour les preuves strictes `card_search + card_detail`. Validation read-only : run `32943536626` SUCCESS, `TCGDEX_BUDGET_EXHAUSTED=0`, identité non relâchée, aucune transaction.

#179 ajoute le rattrapage borné des schedules Global manqués depuis le heartbeat Main Scanner sans créer de seconde lane économique.

## Robot KB — #180 mergée et installée

PR #180 `Robot KB: harvest multi-vault and paid market history locally` est mergée.

```text
feature head                    4194730490efbf879188069de4cc4d17642aad46
merge main                      9365f5cd9f8949580c4e48f00ba8c4e419c22145
Robot KB CI                     32999776457 SUCCESS
V4 validation                   32999776492 SUCCESS
Mac physical install            EXÉCUTÉ
PostgreSQL health               OK / schema [1,2]
LaunchAgents                    fixed / sold / backup / markets / paid installés
```

Le premier run physique a prouvé que les lanes GCC historiques restent saines : le catch-up fixed a accepté 500 observations, puis le catch-up SOLD a stocké 7 transactions finales supplémentaires. Aucun achat/bid/checkout/paiement.

Deux problèmes bornés ont ensuite été observés sur les nouvelles lanes :

1. le sweep multi-vault a atteint le runtime P3 puis a échoué sur un champ `LISTING_SNAPSHOT` non supporté (`provider_sale_evidence`) ; l'audit du schéma P3 montre aussi que les champs provider normalisés supplémentaires de #180 auraient été rejetés après authentification ;
2. PokeTrace et PokemonPriceTracker ont tous deux répondu HTTP **401** au premier appel. Les contrats d'auth du code sont corrects (`X-API-Key` PokeTrace, `Authorization: Bearer` PPT) ; les clés actuellement stockées doivent donc être revalidées/remplacées sans les exposer.

## PR #181 — réparation first-live, CANDIDATE

PR #181 reste **OPEN / DRAFT / NON MERGED** jusqu'à validation et autorisation explicite.

Elle ajoute :

- un adaptateur étroit au schéma du runtime P3 immuable : `LISTING_SNAPSHOT` et `PROVIDER_METRIC_OBSERVATION` n'envoient que les colonnes réellement supportées ;
- conservation du payload brut/provenance et `genuine_sale_evidence=false` ; aucun ASK/agrégat n'est promu en SOLD item-level ;
- HTTP 401/403 provider rendus fail-visible via `source_failures` ;
- `Configurer APIs Robot KB.command`, qui teste les clés existantes, demande une nouvelle clé en saisie masquée si nécessaire, n'écrase le Trousseau qu'après HTTP 200, puis relance la lane `paid`.

Base #181 : `main@4ac5873aca02fa4d4dddf6f3e92247a29d71b03c`.

## Cadence locale prévue après réparation

```text
public multi-vault              toutes les 2 h à :05
PokeTrace/PPT                   01:08 / 07:08 / 13:08 / 19:08
PPT reserve                     15000
PokeTrace reserve               5000
V4_USE                          false
```

Les clés PokeTrace/PPT restent uniquement dans le Trousseau macOS.

## Prochaine phase

1. Valider #181 avec la suite Robot KB dédiée + compile/bash/YAML/diff-check.
2. Merger #181 uniquement après autorisation explicite utilisateur.
3. Sur le Mac, pull `main`, double-cliquer `Configurer APIs Robot KB.command`, valider/remplacer les deux clés puis laisser le catch-up `paid` démarrer.
4. Relancer/vérifier `markets`, puis confirmer les nouvelles observations PostgreSQL et les counts par source.
5. Garder `V4_USE=false` ; Robot KB reste séparé du gate économique.
6. Garder PR #8 V5 isolée et non mergée.

Aucun achat, bid, checkout ou paiement automatique.
