# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **7 septembre 2026**. Le code/Git/GitHub live reste l'autorité ; re-vérifier le HEAD avant toute action importante.

## Autorité

```text
V4 production branch             main
V4 production logic HEAD         db4954f5b223817fe14ccfeb9dcac80c960d5dd9
#255 external FV authority       MERGED / PROD_V4
#259 integrated recall stack     MERGED / PROD_V4
#260 TCGdex constrained recovery MERGED / PROD_V4
#261 cross-grader calibration    OPEN / DRAFT / base pré-#260
V5                               PR #8 / OPEN / DRAFT / NON MERGED
Robot KB durable                 PostgreSQL local Mac / séparé de V4 / V4_USE=false
Neon                             writers automatiques OFF / rollback manuel
```

Le SHA ci-dessus est l'autorité **runtime logique** post-#260. Un closeout docs-only peut faire avancer `main` sans modifier le runtime.

## Phase active — closeout #259/#260 puis couverture externe

#259 a intégré en production les capacités de recall/source-role/PriceCharting/Global/Japan précédemment réparties dans #256/#257/#258 :

- `MAX_PRICE_EUR=250` ;
- plancher de décote adaptatif 20 % ;
- PSA numérique 1–10, aucune synthèse PSA 9.5 ;
- historique GCC sans autorité économique ;
- PriceCharting = `GUIDE`, jamais item-level SOLD ;
- PokeTrace agrégé utilisable seulement après identité/langue/grader/grade exacts ;
- ASK eBay actif exact = revue secondaire, toujours ASK ;
- opportunity adapters et providers de valorisation séparés ;
- capacités Japan intégrées sans transformer Mercari/SNKRDUNK en sources SOLD.

#260 complète l'identité TCGdex : un nom légèrement différent peut être récupéré uniquement après preuve exacte de set+numéro+dénominateur et seulement s'il reste un unique candidat compatible. Une différence matérielle ou plusieurs candidats restent `AMBIGUOUS`.

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

Le natural Main post-merge a exécuté exactement `db4954f5...`, TCGdex `errors=0`, et a conservé des cas ambigus fail-closed. Le chemin spécifique fuzzy unique n'a pas été rencontré naturellement dans cet échantillon : smoke production prouvé, branche spécifique validée par CI mais pas encore live-observée.

## Clarification queue fixed

`processing budget: 120` = plafond global, pas objectif de 120 traitements.

`V4_EXTERNAL_PENDING_MAX_PER_RUN=16` = plafond distinct des vieux pending retries.

Preuves :

```text
34085196093 (#4027)  processed 17 = stale 1 + pending 16
34085768066 (#4028)  processed 27 = stale 11 + pending 16
                     External queue selected 21
```

Le « 21/120 » mélangeait donc `External queue selected 21` avec le budget de traitement 120. Ne pas augmenter les caps pour forcer le compteur vers 120.

## Bottleneck courant

La discovery GCC est saine sur les runs audités ; le principal résiduel est la **couverture économique externe incomplète** et le backlog `EXTERNAL_PENDING`.

Approche : améliorer la qualité/utilité/efficacité des providers et la résolution déterministe avant d'augmenter les caps. Provider outage/403/timeout reste fail-visible, jamais market-negative.

## PR à ne pas reprendre aveuglément

- #261 : OPEN/DRAFT, base `7cb0e067...` pré-#260 ; rebase/port + REUSE AUDIT + revalidation obligatoire avant toute décision ;
- #258 : capability intégrée par #259 ; traiter comme `STALE/SUPERSEDED_BY_259` ;
- #256 : contenu pertinent intégré par #259 ; traiter comme `STALE/SUPERSEDED_BY_259` ;
- #210 : durable Robot KB, autorisation explicite + backup/locks/preflight ;
- PR #8 : V5 protégée, non mergée.

## Invariants

- ASK/current auction/disparition != SOLD ;
- aucun mélange langue/grader/grade/microvariante ;
- aucune identité ambiguë promue automatiquement ;
- aucun achat, bid, checkout ou paiement automatique ;
- Robot KB/Neon séparés de V4 ;
- aucun durable write Cardova sans autorisation explicite ;
- ne pas créer de cron GitHub parallèle au Main Scanner externe.

## Prochaine étape

Après ce closeout docs-only : observer les runs naturels et traiter le prochain bottleneck **prouvé**. Ne pas reprendre automatiquement une ancienne « prochaine étape » ni merger des PR stale/draft par lot.
