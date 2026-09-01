# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **1 septembre 2026** après les merges #216/#217, #219 et #220. Le code/Git/GitHub live reste l'autorité ; re-vérifier le HEAD avant toute action importante.

## Autorité

```text
V4 production branch             main
V4 runtime production            6a33ac33faa324f0fc1c6124fbb49bd736382b75 / PR #220 MERGED
TCGdex outage resilience         #216/#217 MERGED / runtime 03824158ac899cf142199c42d4525386a573bc15
#216 runtime validé              53a7fd0a47d100d851c347c3fadb79e4f754d07b
Robot KB API configurator        #219 MERGED / 2aef339135df8b4a183ad4ba030b9e603ea9e696
Future-start auction guard       #220 MERGED / 6a33ac33faa324f0fc1c6124fbb49bd736382b75
V5                               PR #8 / OPEN / DRAFT / NON MERGED
Robot KB durable                 PostgreSQL local Mac / séparé de V4
Neon                             writers automatiques OFF / rollback manuel
```

## #216/#217 — résilience TCGdex en production

#216 a été mergée via le miroir non-draft #217, sans changement d'identité, fair value, seuil, notification, PokeTrace, PSA ou eBay.

```text
appel TCGdex logique             max 2 tentatives
Main-only breaker threshold      2 appels épuisés consécutifs
après ouverture                  appels réseau TCGdex restants sautés ce run
sémantique après ouverture       ERROR / fail-closed
réponse provider réelle          remet le streak à zéro
nouveau scanner process          circuit fermé / provider retenté
```

Validation pré-merge :

```text
runtime validé                   53a7fd0a47d100d851c347c3fadb79e4f754d07b
V4 current-head                  run 33487708113 SUCCESS / 845 PASS / 2 skipped
Robot KB                         run 33487708197 SUCCESS
Global offline                   run 33487708135 SUCCESS
Global live read-only            SUCCESS / safety + no-mutation PASS
```

Première preuve production naturelle post-merge :

```text
run                              33489103277 SUCCESS
main                             03824158ac899cf142199c42d4525386a573bc15
TCGdex                           16 attempted / 0 exact / 0 no-match / 16 errors
breaker                          ouvert après 2 appels logiques consécutifs épuisés
scanner                          274 s
baseline pré-fix comparable      ~397 s
EXTERNAL_PENDING                 2029 -> 2010
```

La panne provider reste une erreur technique ; aucun clean no-match n'est fabriqué.

## #219 — correctif exécutable Robot KB

PR #219 a porté proprement l'ancien correctif #182 sur le `main` courant :

- `mac/robot-kb-local/Configurer APIs Robot KB.command` passe de mode Git `100644` à `100755` ;
- blob/contenu inchangé ;
- aucun runtime commercial, secret, provider ou comportement économique modifié.

Merge : `2aef339135df8b4a183ad4ba030b9e603ea9e696`.

## #220 — enchères GCC à début futur

PR #220 est en production sur `main@6a33ac33faa324f0fc1c6124fbb49bd736382b75`.

But : une enchère qui n'a pas encore commencé ne doit jamais entrer dans l'économie V4 comme si son prix de départ était un bid courant ou son countdown-to-start un temps avant fin.

Le guard exige une preuve structurée/stable du début futur ou une preuve UI forte ; les timestamps absents/malformés ne sont pas devinés. Le hardening #211/#212 reste l'autorité de découverte/pagination.

Aucun changement fair value, seuil, identité, provider budget ou notification.

## Robot KB / P3

PR #207 a été mergée **uniquement dans la branche P3** (`agent/p3-postgres-durable-shadow`) au merge `df32a19c237a75e4a1c3bb9dba938fd59fc09665`.

Elle ajoute les valeurs proof-preserving `NO_RARITY_SYMBOL` / `RARITY_SYMBOL_PRESENT` sur l'axe `print_run`. **Aucune migration PostgreSQL durable utilisateur n'a été exécutée.**

Le stack Cardova durable #199/#204–#210 reste séparé. En particulier #210 prépare un chemin de commit durable mais exige une autorisation opérateur explicite et ne doit pas être exécuté automatiquement.

## Run naturel post-#220

Au dernier contrôle, le registre V4 ne contenait **pas encore** de run naturel sur `6a33ac33...`. Le dernier run enregistré était `33490000741` à `09:05:40 UTC` sur `2aef3391...`, soit avant le merge #220 à `09:07:01 UTC`.

Ne pas revendiquer une preuve production naturelle #220 avant qu'un run `watcher.yml` sur `6a33ac33...` soit réellement terminé et vérifié.

## Prochaine étape

1. Observer le premier vrai run naturel V4 sur `6a33ac33...` et vérifier que le guard future-start ne dégrade pas discovery/coverage.
2. Continuer d'observer le drain `EXTERNAL_PENDING` et la santé TCGdex/eBay/PSA avant toute nouvelle hausse de cap.
3. Garder le stack Cardova durable non exécuté tant qu'aucune autorisation explicite n'est donnée.
4. Garder PR #8 / V5 expérimentale, draft et non mergée.
5. Aucun achat, bid, checkout ou paiement automatique.
