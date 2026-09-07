# V4 cross-grader proxy calibration — 2026-09-07

## But

Réduire les faux positifs de la lane `GCC REVIEW — CROSS-GRADER` sans traiter un grader de référence comme un comparable exact de la cible.

Cas opérateur ayant déclenché la phase :

- CA 10 Glaceon ex #041/187, GCC 18 EUR, ancienne référence PSA10 PokeTrace 34.37 EUR avec haircut 20 % ;
- PCA 9.5 Eevee ex #126/187, GCC 15 EUR, ancienne référence PSA9 PokeTrace 40.44 EUR ;
- CA 10 Riolu #068/063, GCC 21 EUR, ancienne référence PSA10 PokeTrace 36.14 EUR avec haircut 20 %.

Ces trois cas ont montré qu'un simple rabattement `grader secondaire -> PSA` avec haircut générique était trop permissif.

## Politique implémentée — PR #261

- grade non-PSA fractionnaire, ex. PCA 9.5 : proxy de même grade numérique CGC puis BGS ; aucun fallback automatique vers PSA 9 ;
- si plusieurs proxies secondaires exact-grade existent, retenir la référence centrale la plus basse ;
- grade non-PSA entier : préférer CGC même grade ; PSA même grade reste un dernier fallback conservateur ;
- haircuts d'incertitude PSA fallback : PCA 30 %, CCC 35 %, CA 45 %, autre grader secondaire 40 % ;
- haircuts proxy secondaire même grade : PCA 10 %, CCC 15 %, CA 20 %, défaut 20 % ;
- cross-language ajoute 20 %, avec haircut combiné plafonné à 65 % ;
- PriceCharting compatible peut uniquement plafonner la référence brute : `min(PokeTrace proxy, PriceCharting GUIDE)` ; PriceCharting reste `GUIDE`, jamais `SOLD` ;
- toute alerte cross-grader exige au moins 30 % de décote après haircut ;
- état de déduplication cross-market passé en schema v2 afin que les anciennes alertes soient réévaluées sous la nouvelle calibration.

## Invariants

- identité carte/set/numéro/langue/microvariante inchangée ;
- un proxy cross-grader n'est jamais étiqueté comparable exact ;
- ASK, enchère active ou disparition d'annonce ne deviennent jamais SOLD ;
- historique GCC sans autorité économique ;
- aucun achat, bid, checkout ou paiement automatique ;
- V5 / PR #8 inchangée et non mergée.

## Validation

Branche : `fix/v4-crossgrader-proxy-calibration-20260907`

Base après réconciliation : `main@db4954f5b223817fe14ccfeb9dcac80c960d5dd9`

Head code/tests validé avant documentation : `c58aa4c75768144946f858267a13eb493bf7a420`

GitHub Actions : `V4 Auction Discovery Validation` run `34092254431` — SUCCESS.

- 742 tests : OK ;
- tests ciblés cross-grader : PASS ;
- compile Python : PASS ;
- YAML : PASS ;
- `git diff --check` : PASS ;
- comparaison live read-only effective vs legacy : PASS ;
- aucune transaction ni notification de production pendant la validation.

La documentation peut produire un nouveau head de PR ; toujours re-vérifier le SHA et la CI du head exact avant merge.
