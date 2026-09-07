# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **7 septembre 2026**. Le code/Git/GitHub live reste l'autorité ; re-vérifier le HEAD avant toute action importante.

## Autorité

```text
V4 production branch             main
V4 production code HEAD #261     24230552d52574e2769c21dcfa84ba11320da2cf
V4 main HEAD docs closeout #261  22303a34f7414769a04f4c587338def005b8a5c6
#255 external FV authority       MERGED / PROD_V4
#259 integrated recall stack     MERGED / PROD_V4
#260 TCGdex constrained recovery MERGED / PROD_V4
#261 cross-grader calibration    MERGED / PROD_V4
V5                               PR #8 / OPEN / DRAFT / NON MERGED
Robot KB durable                 PostgreSQL local Mac / séparé de V4 / V4_USE=false
Neon                             writers automatiques OFF / rollback manuel
```

`22303a34...` est docs-only au-dessus du merge runtime #261 `24230552...`. Pour raisonner sur le comportement production, distinguer le HEAD Git courant du dernier SHA runtime.

## Production post-#259/#260/#261

#259 a intégré en production les capacités recall/source-role/PriceCharting/Global/Japan auparavant réparties dans #256/#257/#258 :

- `MAX_PRICE_EUR=250` ;
- plancher de décote adaptatif 20 % ;
- PSA numérique 1–10, aucune synthèse PSA 9.5 ;
- historique GCC sans autorité économique ;
- PriceCharting = `GUIDE`, jamais item-level SOLD ;
- PokeTrace agrégé uniquement après identité/langue/grader/grade compatibles ;
- ASK eBay actif exact = revue secondaire, toujours ASK ;
- opportunity adapters et providers de valorisation séparés ;
- Mercari/SNKRDUNK intégrés comme sources ASK/opportunités read-only.

#260 complète l'identité TCGdex : un nom légèrement différent peut être récupéré uniquement après preuve exacte de coordonnée imprimée + langue et seulement s'il reste un unique candidat compatible. Une différence matérielle ou plusieurs candidats restent `AMBIGUOUS`.

#261 calibre la lane CROSS-GRADER : demi-grades non-PSA => proxy secondaire même grade numérique seulement ; grades entiers => CGC même grade privilégié, PSA même grade fallback conservateur ; haircuts spécifiques et seuil de revue cross-grader >=30 % après haircut. PriceCharting peut plafonner une référence compatible mais reste `GUIDE`.

## Validation #260

```text
validated head                d809f4aacce0cbfb362546a65de351be2451dcf6
validation run                34053317112
validation job                101541221319
suite V4                      958 PASS / 2 skipped
compile / YAML / diff-check   PASS
read-only auction compare     PASS
merge/runtime SHA             db4954f5b223817fe14ccfeb9dcac80c960d5dd9
natural Main post-merge       34091885754 / 101646924190 / SUCCESS
```

Le natural Main post-#260 a exécuté exactement `db4954f5...`, avec TCGdex `errors=0`. Le chemin fuzzy unique #260 était déployé mais n'a pas été observé sur un cas récupéré dans cet échantillon.

## Validation #261

```text
validated code head           c58aa4c75768144946f858267a13eb493bf7a420
validation run                34092254431
full V4 + targeted            PASS
compile / YAML / diff-check   PASS
read-only compare             PASS
PR final head                 c5e61d1b5377508ccf1a720959e0f7e09d570fbc
merge runtime                 24230552d52574e2769c21dcfa84ba11320da2cf
```

## Queue fixed / EXTERNAL_PENDING

`processing budget: 120` est un plafond global, pas une cible.

`V4_EXTERNAL_PENDING_MAX_PER_RUN=16` limite séparément les anciens P4. Le code garde en plus un hard ceiling `MAX_CONFIGURED_EXTERNAL_PENDING_PER_RUN=20` : passer à 100 n'est pas un simple réglage, cela exigerait de supprimer une borne de sécurité alors que les budgets providers restent eux-mêmes bornés.

Exemple naturel post-#260 :

```text
eligible candidates        4175
new                           1
changed                       1
stale                         9
pending retry              1512
fresh already evaluated    2652
processed this run            27
  new                         1
  changed                     1
  stale                       9
  pending retry              16
pending retry backlog       1496
first-evaluation backlog       0
```

Donc `27/120` = `1 + 1 + 9 + 16`, pas une sous-utilisation mystérieuse du cap. Le backlog P4 est réel ; il faut mesurer son **flux net** et ses raisons avant tout relèvement de borne.

## Bottleneck courant

La discovery GCC est saine sur les runs audités. Les deux résiduels prioritaires sont :

1. **couverture marché externe incomplète / backlog P4** ;
2. **résolution TCGdex de certains NO_MATCH/AMBIGUOUS**.

Plusieurs ambiguïtés live restantes portent des suffixes GCC tels que `Reverse`, `Rainbow`, `Gold`, `Holo`. Le recovery #260 n'accepte pas actuellement une différence de nombre de tokens ; ces cas doivent être audités comme éventuelle séparation `nom canonique` vs `qualifier de variante`, sans jamais supprimer aveuglément un token matériel.

## PR / supersession

- #257 : MERGED, capacité intégrée dans la lignée production ;
- #259 : MERGED, intégration canonique recall/source-role/Global/Japan ;
- #260 : MERGED, recovery TCGdex contraint ;
- #261 : MERGED, calibration cross-grader ;
- #258 : OPEN/DRAFT mais contenu runtime absorbé par #259 => `STALE_OPEN/SUPERSEDED_BY_259`, ne pas merger ;
- #256 : OPEN/DRAFT mais contenu pertinent absorbé par #259 => `STALE_OPEN/SUPERSEDED_BY_259`, ne pas merger ;
- #210 : durable Robot KB, autorisation explicite + backup/locks/preflight ;
- PR #8 : V5 protégée, non mergée.

## Invariants

- ASK/current auction/disparition != SOLD ;
- aucune panne provider n'est transformée en preuve de marché négative ;
- aucun mélange langue/grader/grade/microvariante ;
- aucune identité ambiguë promue automatiquement ;
- aucun achat, bid, checkout ou paiement automatique ;
- Robot KB/Neon séparés de V4 ;
- aucun durable write Cardova sans autorisation explicite ;
- aucun cron GitHub parallèle au Main Scanner externe.

## Prochaine étape

1. mesurer plusieurs runs naturels pour le **delta net P4** et classifier les causes `PENDING_BUDGET` vs provider retry ;
2. auditer les NO_MATCH/AMBIGUOUS TCGdex réels et n'ajouter qu'un recovery déterministe réutilisant les gates existants ;
3. ne relever aucun cap provider/P4 avant preuve qu'il s'agit du vrai goulot et qu'une hausse reste compatible avec les budgets/rate limits ;
4. PR #8/V5 et Robot KB durable restent hors scope.
