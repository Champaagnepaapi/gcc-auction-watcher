# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **1 septembre 2026** pendant la validation de PR #216. Le code/Git/GitHub live reste l'autorité ; re-vérifier le HEAD avant toute action importante.

## Autorité

```text
V4 production canonique          main @ 1911ba5cdfd60d4dbc57dbb8ba07c42d3f22aea9
V4 runtime production            PR #214 MERGED
TCGdex outage resilience         PR #216 OPEN / DRAFT / NON MERGED
#216 runtime validé               53a7fd0a47d100d851c347c3fadb79e4f754d07b
V5                               PR #8 / OPEN / DRAFT / NON MERGED
Robot KB                         séparé de V4 / aucun changement dans #216
Neon                             aucun changement dans #216
```

Aucun merge ou déploiement de #216 n'a été effectué.

## Constat production après #214

Le drain fixed `EXTERNAL_PENDING` fonctionne réellement :

```text
2241 -> 2187 -> 2162 -> 2115 -> 2099 -> 2065 -> 2045
```

Le dernier run naturel examiné (`33482483020`, `main@1911ba5...`) a terminé normalement en **397 s** mais a montré que la santé provider est maintenant le plafond :

```text
TCGdex                           21 attempted / 0 exact / 21 errors
cause TCGdex                     ConnectionError
PokeTrace                        0 (identité TCGdex non résolue)
PSA APR                          2 attempted / 2 unavailable / 403 breaker
eBay                             16 attempted / 13 insufficient / 3 unavailable-error
EXTERNAL_PENDING                 2045 / ETA 128 runs
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
V4 Auction Discovery CI          33484132586 SUCCESS
V4 tests                         845 PASS / 2 skipped
compile nouveaux runtime         PASS
YAML / diff-check                PASS
live auction compare             94 effective / 91 legacy
legacy_only                      0
unresolved                       0
Global offline validate          33484132557 / validate SUCCESS
Global marketplace-live-once     encore en cours au dernier contrôle
```

Le job Global live est read-only et teste la pile Global, qui conserve exactement le comportement #145 ; le breaker ajouté par #216 est Main-only et couvert par les tests V4 déterministes.

## Prochaine étape

1. Laisser finir `marketplace-live-once` de `33484132557` et classifier son résultat comme preuve provider/read-only, sans modifier #216 pour une panne externe non liée.
2. Si aucun défaut du patch n'apparaît, finaliser le README/inventaires de handoff avec le SHA docs final.
3. Garder #216 **DRAFT / NON MERGED** jusqu'à autorisation explicite utilisateur.
4. Après autorisation seulement : merger avec SHA attendu, vérifier le nouveau `main`, puis observer un vrai run production pour confirmer que le circuit borne la panne TCGdex sans relâcher l'identité.
5. Garder PR #8 / V5 et Robot KB/Neon séparés.

Aucun achat, bid, checkout ou paiement automatique.
