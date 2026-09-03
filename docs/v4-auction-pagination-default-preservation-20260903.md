# V4 — auction pagination default preservation (#245)

Date : 3 septembre 2026

## Incident

Après le déploiement du guard future-start #243, le Main Scanner a reproduit une dégradation de discovery sur un snapshot GCC avec dérive de l'ordre `ENDING_SOON`.

Preuve production pré-fix :

```text
run                         33795854886
main                        a93cd8628b7ff8648d88b84f86a87406fb3ba7fd
runtime avant fix           3ada7785d3fbef8050a7712bc773a52fd569716d (#243)
order drift                 YES
provider count hint         16264
recovery capacity           100 -> 250 pages
failure                     auction API safety limit 250 pages reached
fallback                    legacy / fail-closed
```

## Cause exacte

Le wrapper future-start transmettait par défaut `page_size=24` au collector qu'il enveloppait. La couche de stabilité durcie utilise volontairement `STABLE_AUCTION_API_PAGE_SIZE=100` lorsqu'aucun override explicite n'est fourni.

Pour environ 16.2k rows :

```text
100 rows/page   -> ~163 pages + marge, sous le hard ceiling 250
24 rows/page    -> ~678 pages + marge, au-dessus du hard ceiling 250
```

Le défaut était donc la perte du default de la couche sous-jacente, pas un hard ceiling trop bas.

## Correctif #245

Branche : `fix/v4-auction-pagination-default-preservation-20260903`

```text
base                        a93cd8628b7ff8648d88b84f86a87406fb3ba7fd
validated head              c553796d8829e5f6dd615acfc7177ddb60f4bf91
validation run              33796972288 SUCCESS
production merge            a39c693d629b003f69f66ba20753303b197737af
```

Le wrapper devient transparent pour `page_size` / `max_pages` lorsqu'aucun override explicite n'est fourni. Les overrides explicites restent transmis. Le hard ceiling de recovery reste **250 pages**.

## Validation pré-merge

```text
V4 suite                     898 PASS / 2 skipped
changed Python compile       PASS
YAML parse                   PASS
git diff --check             PASS
focused pagination tests     PASS
live auction compare         PASS
effective / legacy           36 / 32
legacy_only                  0
unresolved                   0
safety-net failures          0
```

Le live compare avait un ordre GCC normal : preuve de non-régression/superset, pas reproduction du snapshot pathologique. La reproduction naturelle `33795854886` + le test ciblé établissent la cause et le contrat du fix.

## Preuve post-merge

Fast Lane sur le nouveau `main` :

```text
run                         33798827669 SUCCESS
head                        a39c693d629b003f69f66ba20753303b197737af
```

Un second Fast Lane naturel `33799115189` est également SUCCESS sur le même SHA.

Main Scanner naturel exact `a39c693d...` : **PENDING au moment de la création de ce ledger**. Le run `33798768727` ne compte pas : il avait démarré avant le merge et exécute l'ancien SHA `a93cd862...`.

## Invariants inchangés

- cap économique auction `360` inchangé ;
- priorité `<=5m`, puis `<=12m`, puis `<=60m` inchangée ;
- fair value, seuils et max recommendation inchangés ;
- identité carte/langue/grader/grade/microvariante inchangée ;
- eBay/PSA/PokeTrace/TCGdex inchangés ;
- notifications inchangées ;
- Robot KB / Neon inchangés ;
- V5 / PR #8 inchangée et non mergée ;
- aucun achat, bid, checkout, paiement ou grading purchase automatique.

La discovery reste fail-closed si une récupération réelle ne peut pas prouver l'épuisement API ou dépasse réellement le hard ceiling 250.
