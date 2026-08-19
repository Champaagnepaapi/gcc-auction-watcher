# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **18 août 2026**.

## Production canonique

- V4 production : `main`
- `main` : `a52398685629e4baf4c8ac036851e2ae1a49b037`
- dernier changement fonctionnel : PR #135, `V4: recover source-pinned set conflicts when TCGdex REST is stale`
- V5 : PR #8, expérimentale/draft/non mergée dans `main`
- PR #126 : ancienne lignée PokeTrace, ouverte/draft mais **superseded** par #127/#128 et la suite ; ne pas merger.

## Phase #123 → #135 : terminée et validée en production

La séquence a remplacé les corrections ponctuelles par des preuves déterministes et bornées :

1. #123 : récupération V4 des capacités TCGdex déjà construites, dont unicité déterministe ;
2. #124 : retrieval PokeTrace structuré (`card_number` + `game`) après identité TCGdex ;
3. #127/#128/#129 : padding collector number, bridges provider exacts, recherche JA canonique ;
4. #130 : diagnostic final-gate et correction source-pinnée `Night Wanderer -> SV6a` ;
5. #131/#132/#133 : preuve finish TCGdex source-pinnée, généralisée puis compatible avec imports TypeScript sans point-virgule ;
6. #134/#135 : réconciliation des namespaces de set lorsque le REST TCGdex est stale, #135 devenant l'autorité générique de cette classe.

Pin catalogue TCGdex immuable :
`af33c9ac882e2acfadffaf19e8083aa976d12983`.

## Preuve production #135

Run naturel V4 `32160680888` sur le SHA exact `a52398685629e4baf4c8ac036851e2ae1a49b037` : **SUCCESS**.

Preuves runtime :

- `Team Rocket's Houndoom 100/098` : correction source-pinnée vers `SV10` ;
- `Team Rocket's Meowth 109/098` : correction source-pinnée vers `SV10` ;
- `Team Rocket's Moltres Ex 112/098` : correction source-pinnée vers `SV10` ;
- TCGdex : `31 attempted | 18 exact | 4 no-match | 9 ambiguous | 0 errors` ;
- PokeTrace : `2 attempted | 1 exact | 0 strong | 1 weak | 1 no-match | 0 ambiguous | 0 errors` ;
- discovery : COMPLETE ;
- final opportunities : `0` ;
- aucun achat, bid, checkout ou paiement.

Crobat `117/098` n'était pas sélectionné dans ce run : ne pas revendiquer une preuve live spécifique Crobat. La classe générique `S12 -> SV10` est toutefois prouvée live sur trois cartes du même set.

## État économique restant

Le run `32160680888` avait encore :

- external-market coverage : **INCOMPLETE** ;
- external pending backlog : environ `2031` ;
- ETA diagnostique : environ `204` runs ;
- PSA APR encore indisponible sur ce run ;
- eBay partiellement en timeout/indisponible.

Donc `0 opportunité` n'est pas présenté comme un résultat économique globalement trustworthy tant que cette couverture externe reste incomplète.

## Prochaine direction

Ne plus ajouter d'alias carte-par-carte pour un simple `NO_MATCH/AMBIGUOUS`. La prochaine modification d'identité doit partir d'une **classe de blocker répétée et déterministe**, avec preuve source/catalogue et fail-closed.

Priorité opérationnelle : laisser V4 drainer le backlog externe et mesurer les blockers récurrents. Aucun changement risqué de V4 n'est justifié pendant une enchère active sans nouvelle preuve mesurée.

## Invariants

- PokeTrace reste marché/prix après identité TCGdex ; il ne choisit pas l'identité normale.
- aucun fuzzy/substr/Levenshtein/traduction comme preuve exacte ;
- ASK et enchère active ne sont jamais des SOLD ;
- RAW ne devient jamais valeur d'un slab ;
- identité/langue/grader/grade/microvariante incompatibles ne sont jamais mélangés ;
- aucun achat, bid, checkout ou paiement automatique ;
- PR #8 ne doit jamais être mergée dans `main` sans autorisation explicite.
