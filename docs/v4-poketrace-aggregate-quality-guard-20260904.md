# V4 — PokeTrace aggregate quality guard (#247)

Date : 4 septembre 2026

## Incident et risque

PokeTrace peut exposer une surface eBay gradée agrégée sans bornes de dispersion informatives. Dans le cas observé, V4 avait reçu une enveloppe `low == central == high` :

```text
124.83–124.83 EUR
PSA 9
29 ventes agrégées
```

Cette forme ne prouve pas une distribution de prix. Elle pouvait auparavant devenir à elle seule une preuve `STRONG`, ancrer une fair value et permettre un `EXTERNAL_RESCUE` artificiel.

## Correctif #247

Branche runtime : `fix/v4-poketrace-aggregate-quality-20260903`

```text
base                         a39c693d629b003f69f66ba20753303b197737af
validated head               03ce93ae08eedf3301813f030b67f120b7abd4a4
validation run               33799908680 SUCCESS
production merge             a7666faf4b0ef2fab74295a45ebcf75d9832f284
```

Le guard s'applique uniquement à une preuve PokeTrace déjà classée `MATCHED + STRONG` avec estimate présent. Si `low`, `central` ou `high` est invalide/non positif, ou si l'enveloppe totale est `<= 0.01 EUR`, la preuve devient :

```text
status                       CLEAN_INSUFFICIENT
strength                     WEAK
estimate                     absent du chemin économique
fallback                     PSA APR / eBay requis
```

Une vraie plage de prix informative reste inchangée et peut conserver sa classification `STRONG` selon les règles existantes.

## Validation pré-merge

Workflow `33799908680`, job `100796592649` :

- suite V4 complète : PASS ;
- tests ciblés du guard : PASS ;
- `py_compile` : PASS ;
- YAML : PASS ;
- `git diff --check` : PASS ;
- comparaison auction read-only : PASS ;
- 100 rows API observées ;
- aucune divergence effective/legacy dans ce snapshot ;
- aucune notification, mutation économique, enchère, achat, checkout ou paiement.

Les tests couvrent explicitement :

- agrégat zéro-width STRONG => `CLEAN_INSUFFICIENT / WEAK`, `estimate=None` ;
- plage réelle non dégénérée => comportement inchangé ;
- preuve déjà faible => inchangée ;
- installation idempotente ;
- installation avant le runner canonique.

## Preuve production post-merge

Premier Main Scanner naturel exact sur le nouveau runtime :

```text
run                          33844655319
head                         a7666faf4b0ef2fab74295a45ebcf75d9832f284
workflow                     SUCCESS
scan_exit_code               0
duration                     175 s
final opportunities          0
auction rows / timers        100 / 100
auction scope                COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
auction fallback             false
```

Le log confirme aussi fixed discovery `3259/3259`, 33 pages, page size 100, coverage COMPLETE. PokeTrace sur ce run : `attempted=1`, `strong=0`, `weak=0`, `errors=0`.

**Limite de preuve :** ce run naturel n'a pas rencontré un nouvel agrégat PokeTrace dégénéré STRONG. Il prouve le déploiement et la non-régression du runtime, pas un déclenchement positif naturel du guard. Le contrat positif est établi par les tests ciblés #247. Plusieurs runs naturels suivants sur `a7666...` sont également SUCCESS avec discovery auction complète et sans fallback.

## Invariants inchangés

- aucune modification discovery GCC ;
- aucun relâchement TCGdex, langue, grader, grade ou microvariante ;
- aucune modification des seuils de décote, fair value générale, caps ou budgets ;
- une ASK ou enchère active ne devient jamais SOLD ;
- PSA APR/eBay restent des fallbacks fail-visible ;
- Robot KB / Neon inchangés ;
- V5 / PR #8 inchangée et non mergée ;
- aucun achat, bid, checkout, paiement ou grading purchase automatique.
