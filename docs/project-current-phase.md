# Current phase — PokeTrace Japanese search regression

Production `main` au début de la phase : `4737604a1685f344ced65ede1ed49b4a1b9b7f6d` (merge PR #128).

Fix branch : `fix/v4-poketrace-ja-search-regression-20260818`.

## Verified live state

Premier run production post-#128 : `32119349938` — SUCCESS.

- TCGdex : `25 attempted | 14 exact | 0 no-match | 11 ambiguous | 0 errors`.
- PokeTrace : `5 attempted | 0 exact | 5 no-match | 0 errors`.
- les 5 probes japonais ont retourné `provider_candidates=0`.
- final opportunities : `0`.
- aucun achat, bid, checkout ou paiement.

## Root cause

Le run `32116746065` post-#127 avait prouvé que PokeTrace retournait des candidats japonais lorsque la requête conservait le nom canonique/romanisé avec le numéro imprimé paddé et `game=pokemon-japanese`.

PR #128 a attaché correctement le nom TCGdex localisé au même `card_id + set_id + localId`, mais l'a aussi utilisé comme `search_name`. Cette substitution a fait régresser la récupération à zéro candidat sur le run post-merge.

## Current change

La branche sépare à nouveau strictement :

1. **retrieval** : nom canonique/romanisé + numéro imprimé/paddé + game exact ;
2. **acceptance alias** : nom TCGdex localisé, uniquement pour le même card id/set id/localId déjà exact.

Aucun deuxième appel PokeTrace, aucun fuzzy, aucune traduction comme preuve, aucun changement des gates numéro/set/langue/édition/finish/stamp/promo/grader/grade ou de l'économie.

## Next gate

Créer la PR, lancer la CI complète et vérifier compile/YAML/diff + discovery read-only. Si tout est vert, la PR reste non mergée jusqu'à autorisation utilisateur. Le gain live PokeTrace devra être mesuré après merge sur un nouveau run production.

PR #126 est une ancienne lignée basée avant #127/#128 et ne doit pas être mergée telle quelle. PR #8 reste expérimentale et non mergée.