# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **1 septembre 2026** pendant la validation de PR #216. Le code/Git/GitHub live reste l'autorité ; re-vérifier le HEAD avant toute action importante.

## Autorité

```text
main GitHub / docs               1911ba5cdfd60d4dbc57dbb8ba07c42d3f22aea9
V4 runtime production            c2bb3890fcf6e98e29d3ccf937b42ae2fddbae09 / PR #214 MERGED
TCGdex outage resilience         PR #216 OPEN / DRAFT / NON MERGED
#216 runtime validé              53a7fd0a47d100d851c347c3fadb79e4f754d07b
#216 docs head                   df943b52057a68bd7bf15207706250e2208876b5
V5                               PR #8 / OPEN / DRAFT / NON MERGED
Robot KB                         séparé de V4 / aucun changement dans #216
Neon                             aucun changement dans #216
```

Aucun merge ou déploiement de #216 n'a été effectué.

## Constat production après #214

Le drain fixed `EXTERNAL_PENDING` fonctionne réellement :

```text
2241 -> 2187 -> 2162 -> 2115 -> 2099 -> 2065 -> 2045 -> 2029
```

Le run naturel le plus récent examiné (`33484902370`, `main@1911ba5...`) a terminé normalement mais confirme que la santé provider reste le plafond :

```text
TCGdex                           18 attempted / 0 exact / 18 errors
cause TCGdex                     ConnectionError
PokeTrace                        0 (identité TCGdex non résolue)
PSA APR                          2 attempted / 2 unavailable / 403 breaker
eBay                             16 attempted / 0 sufficient / 6 insufficient / 10 unavailable
EXTERNAL_PENDING                 2029 / ETA 127 runs
scanner total_seconds            397.7 s
```

Le résultat reste fail-closed : aucune erreur provider n'est transformée en no-match ou en comparable exact.

## PR #216 — TCGdex transport/run outage resilience — CANDIDATE

Reuse audit :

- PR #145 fournit déjà la résilience transport TCGdex : 2 tentatives max, timeout effectif minimum 10 s, backoff 0,25 s, retry seulement `Timeout` / `ConnectionError` / HTTP 502/503/504 ;
- PR #189 fournit déjà le pattern V4 de circuit-breaker process-local pour les pannes provider ; nouvel essai au run suivant, sans reclassifier une panne comme no-match.

#216 réutilise ces patterns sans modifier les règles d'identité ou l'économie :

```text
appel TCGdex logique             max 2 tentatives
Main-only breaker threshold      2 appels épuisés consécutifs
après ouverture                  appels réseau TCGdex restants sautés ce run
sémantique après ouverture       ERROR / fail-closed
réponse provider réelle          remet le streak à zéro
nouveau scanner process          circuit fermé / provider retenté
```

Le bootstrap `run_watcher_multimarket_resilient.py` installe cette couche puis exécute le runner canonique `run_watcher_multimarket` inchangé. Si #216 était mergée, `watcher.yml` utiliserait ce bootstrap avec `V4_TCGDEX_RUN_BREAKER_THRESHOLD=2`.

Aucun fallback d'identité, aucune hausse de cap #214, aucun changement fair value/décote/notification/eBay/PSA/PokeTrace, aucune transaction.

## Validation #216

Runtime validé : `53a7fd0a47d100d851c347c3fadb79e4f754d07b`.

```text
V4 runtime CI                    33484132586 SUCCESS
V4 tests                         845 PASS / 2 skipped
compile / YAML / diff-check      PASS
live auction compare             94 effective / 91 legacy / legacy_only=0
Global runtime                   33484132557 SUCCESS
Global marketplace-live-once     SUCCESS / read-only / safety PASS / no mutation PASS

docs head                        df943b52057a68bd7bf15207706250e2208876b5
delta depuis runtime             README + docs seulement / aucun code
V4 docs-head tests               845 PASS / 2 skipped
Robot KB docs-head               33487523595 SUCCESS
Global offline docs-head         33487523606 / validate SUCCESS
V4 live compare docs-head        en cours au dernier contrôle
Global live docs-head            en cours au dernier contrôle (redondant avec runtime live SUCCESS)
```

Le live Global du runtime a rencontré des erreurs TCGdex intermittentes mais a terminé avec le contrat read-only intact : aucune notification, aucune mutation, aucune relaxation d'identité, aucune transaction.

## Prochaine étape

1. Laisser finir le live compare V4 du docs-head `df943b...` et enregistrer son résultat dans la PR sans nouveau commit documentaire si possible.
2. Garder #216 **DRAFT / NON MERGED** jusqu'à autorisation explicite utilisateur.
3. Après autorisation seulement : merger avec SHA attendu, vérifier le nouveau `main`, puis observer un vrai run production pour confirmer que le circuit borne la panne TCGdex sans relâcher l'identité.
4. Garder PR #8 / V5 et Robot KB/Neon séparés.

Aucun achat, bid, checkout ou paiement automatique.
