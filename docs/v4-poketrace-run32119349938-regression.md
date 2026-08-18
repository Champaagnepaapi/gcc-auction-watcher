# V4 PokeTrace — regression post-PR #128

Base production auditée : `4737604a1685f344ced65ede1ed49b4a1b9b7f6d` (merge PR #128).

## Preuve live

Le run production `32116746065`, après PR #127 mais avant PR #128, retrouvait des candidats PokeTrace japonais avec :

- `search` canonique/romanisé ;
- `card_number` imprimé avec padding ;
- `game=pokemon-japanese`.

Exemples observés : `Galarian Zapdos (Japanese)`, `Arbok ex (Japanese)`, `Zeraora VSTAR (Japanese)` et `Team Rocket's Orbeetle (Japanese)` avec numéro exact et set provider préfixé.

PR #128 a ensuite utilisé le nom TCGdex localisé japonais comme `search_name`. Au premier run production post-merge `32119349938`, les 5 probes PokeTrace japonais ont tous retourné `provider_candidates=0` : Ceruledge Ex, Sylveon, Mewtwo & Mew GX, Kieran et Charizard V.

## Root cause

La récupération et l'acceptation provider ont été confondues : le nom japonais TCGdex exact est une preuve/alias provider bornée au même `card_id + set_id + localId`, mais PokeTrace recherche son catalogue `pokemon-japanese` avec les noms provider romanisés/anglais observés live.

## Correction

- conserver `search_name` canonique/romanisé pour la requête `/cards` ;
- conserver `card_number` imprimé/paddé et `game=pokemon-japanese` ;
- garder le nom TCGdex localisé uniquement dans `provider_name_aliases` pour l'acceptation déterministe ;
- ne pas ajouter de deuxième requête PokeTrace ;
- ne modifier aucun gate numéro/set/langue/édition/finish/stamp/promo/grader/grade.

Les bridges `(Japanese)`, `(Secret)` et préfixe exact de set restent inchangés. Milotic `013/068` avec variantes First Edition/Unlimited reste fail-closed sans preuve d'édition.

## Validation attendue

CI complète + compile/YAML/diff + comparaison discovery read-only. Aucun gain live PokeTrace n'est revendiqué avant un run production sur le futur merge SHA.

Aucun achat, bid, checkout, paiement ou merge de PR #8.