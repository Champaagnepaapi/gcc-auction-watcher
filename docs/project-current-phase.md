# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **1 septembre 2026** après les merges #216/#217, #219, #220, #223 et #222/#224. Le code/Git/GitHub live reste l'autorité ; re-vérifier le HEAD avant toute action importante.

## Autorité

```text
V4 production branch             main
V4 runtime production            0be4dca95513e36f4e407ef7bac361fe488c1d36 / PR #224 MERGED
TCGdex transport resilience      #216/#217 MERGED / runtime 03824158ac899cf142199c42d4525386a573bc15
TCGdex outage fallback           #222/#224 MERGED / runtime 0be4dca95513e36f4e407ef7bac361fe488c1d36
#222 validated head              4cd3b215267dfc504b535831d70637e42adfb247
#222 exact tested tree           8ae11e351add5e78b3765bfe410ab884ac649586
#224 first Main prod proof       run 33500303400 SUCCESS / 269 s
Robot KB API configurator        #219 MERGED / 2aef339135df8b4a183ad4ba030b9e603ea9e696
Future-start auction guard       #220 MERGED / 6a33ac33faa324f0fc1c6124fbb49bd736382b75
V5                               PR #8 / OPEN / DRAFT / NON MERGED
Robot KB durable                 PostgreSQL local Mac / séparé de V4
Neon                             writers automatiques OFF / rollback manuel
```

## #216/#217 — résilience transport TCGdex

Le Main Scanner conserve : max 2 tentatives par appel logique, retry seulement sur `Timeout` / `ConnectionError` / HTTP 502/503/504, breaker après 2 appels logiques épuisés consécutifs, puis `ERROR` fail-closed pour le reste du run. Une vraie réponse provider remet le streak à zéro et un nouveau process repart circuit fermé.

Première preuve production de panne : run `33489103277` SUCCESS, 16/16 TCGdex en `ERROR`, breaker ouvert exactement après 2 appels épuisés, scanner 274 s, backlog `2029 -> 2010`. Aucune panne n'a été transformée en clean no-match.

## #222/#224 — fallback source-pinné pendant panne transport

#222 a ajouté un fallback **étroit** après la résilience #216/#217. Il ne peut agir que si le resolver normal termine en `ERROR` d'une classe transport retryable, puis exige simultanément :

1. langue japonaise ;
2. alias de set déjà reviewé ;
3. numéro/denominator exact compatible ;
4. source TCGdex immuable `af33c9ac882e2acfadffaf19e8083aa976d12983` ;
5. exact `set/localId` + import exact du set ;
6. finish uniquement dans le vocabulaire déjà admis.

`NO_MATCH`, `AMBIGUOUS`, autre langue, set non reviewé ou preuve incomplète restent inchangés/fail-closed. Aucun changement fair value, seuil, cap, notification, eBay, PSA, PokeTrace, Robot KB ou V5.

Validation exacte après #223 :

```text
validated head                   4cd3b215267dfc504b535831d70637e42adfb247
exact tested merge tree          8ae11e351add5e78b3765bfe410ab884ac649586
V4 validation                    run 33498301361 SUCCESS / 867 PASS
compile / YAML / diff-check      PASS
read-only live compare           effective=93 / legacy=91 / legacy_only=0
Robot KB validation              run 33498301360 SUCCESS
merge vehicle                    #224 (mirror non-draft, Ready toggle GitHub cassé)
production merge                 0be4dca95513e36f4e407ef7bac361fe488c1d36
```

## Première preuve production post-#224

Le premier Main Scanner post-merge `33500303400` a chargé exactement `main@0be4dca95513e36f4e407ef7bac361fe488c1d36` et terminé **SUCCESS**.

```text
scanner duration                 269 s
final opportunities              0
TCGdex                           exact 17 / no-match 1 / ambiguous 0 / errors 0
PokeTrace                        3 exact / 1 strong / 2 weak / 0 error
PokeTrace strong example         Erika's Invitation PSA 10 / 81 ventes agrégées
auction discovery                COMPLETE
auction rows / timers            24 / 24
auction <=60 min                 0
legacy fallback used             false
PSA APR                          HTTP 403 -> breaker fail-closed
external pending backlog         1966
first-evaluation coverage        COMPLETE
external-market coverage         INCOMPLETE
```

TCGdex était déjà revenu en ligne sur le baseline pré-merge `33498609995` (`11 EXACT / 2 NO_MATCH / 3 AMBIGUOUS / 0 ERROR`). Le run post-merge prouve donc la **non-régression en production** et le fait que le fallback n'interfère pas avec le provider sain. Il **ne constitue pas une preuve positive d'activation du fallback outage**, puisqu'aucune erreur transport TCGdex n'a eu lieu pendant ce snapshot.

## #220 — enchères GCC à début futur

Le guard future-start reste en production sous le runtime courant. Une enchère prouvée comme n'ayant pas commencé est exclue avant interprétation du prix/countdown ; aucun timestamp absent/malformé n'est deviné. Le hardening #211/#212 reste l'autorité de découverte/pagination.

Les snapshots post-#220 et post-#224 observés avaient 0 enchère Pokémon 0–100 € à ≤60 min, donc le premier cas future-start positif reste à observer naturellement.

## Robot KB / P3

PR #207 a été mergée **uniquement dans la branche P3** (`agent/p3-postgres-durable-shadow`) au merge `df32a19c237a75e4a1c3bb9dba938fd59fc09665`. Elle ajoute `NO_RARITY_SYMBOL` / `RARITY_SYMBOL_PRESENT` sur `print_run`. **Aucune migration PostgreSQL durable utilisateur n'a été exécutée.**

Le stack Cardova durable #199/#204–#210 reste séparé ; aucun commit durable ne doit être exécuté sans autorisation explicite opérateur.

## Prochaine étape

1. Continuer à observer naturellement TCGdex ; si une panne transport réapparaît, vérifier la première activation positive du fallback #222/#224 et inspecter les identités récupérées.
2. Continuer d'observer les snapshots auction jusqu'au premier cas future-start réellement exclu.
3. Continuer le drain `EXTERNAL_PENDING` sans augmenter les caps uniquement pour forcer le drainage.
4. Garder Robot KB/Cardova durable séparé et sans write non autorisé.
5. Garder PR #8 / V5 expérimentale, draft et non mergée.
6. Aucun achat, bid, checkout ou paiement automatique.
