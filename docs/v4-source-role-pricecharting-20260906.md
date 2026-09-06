# V4 source roles / PriceCharting — 2026-09-06

## Scope

PR #257, branch `fix/v4-source-role-pricecharting-20260906` — `DRAFT_VALIDATION`, non mergée.

Cette phase sépare **où le robot peut acheter** de **comment le robot valorise une carte**.

## Opportunity sources

Adapters Global actuels : GCC, Fanatics, COMC, Magi, Cardova.

Leur prix est uniquement un coût d'acquisition potentiel. `FIXED_ASK` et `AUCTION_SNAPSHOT_LE5` peuvent être évalués comme offres ; aucun ne devient un SOLD. Un listing marketplace ne peut créer, ancrer, confirmer, plafonner ou conflict-block la fair value.

Mercari/SNKRDUNK restent dans la PR #256 séparée. eBay actif n'est pas implémenté dans #257 et devra être un adapter d'opportunités indépendant.

## Valuation sources

Politique #257 :

1. SOLD exacts/récents et preuves SOLD-derived compatibles gardent la priorité économique lorsqu'ils existent ;
2. PSA APR / PokeTrace / PokemonPriceTracker restent utilisables selon leurs preuves et gates ;
3. **PriceCharting est consulté systématiquement comme guide de référence** pour toute identité PSA compatible évaluée ;
4. un guide PriceCharting compatible peut suffire seul si une meilleure preuve SOLD-derived n'est pas disponible.

Le direct eBay SOLD page scraper perd son autorité de fair value dans #257. Son ancien code transport peut rester pour compatibilité/provenance, mais il n'est pas une source économique dans cette phase.

## GCC history

PR #255 est déjà mergée sur `main`. Les ventes historiques GCC sont contexte diagnostic/Robot KB uniquement pour l'économie. Elles ne peuvent créer, ancrer, confirmer ou plafonner la fair value.

Global #257 applique explicitement la même règle : `gcc_fair_eur` peut rester dans les payloads diagnostiques mais n'intervient pas dans la décision marketplace.

## PriceCharting semantics

PriceCharting reste un **price guide**, jamais une preuve SOLD item-level.

- aucune `ComparableSale` synthétique ;
- aucun faux nombre de ventes ;
- `PSA 10` PriceCharting -> guide PSA 10 ;
- `Grade 9` PriceCharting -> accepté comme **guide PSA 9** lorsque le listing est déjà prouvé PSA 9 exact ;
- `Grade 8` PriceCharting -> accepté comme **guide PSA 8** lorsque le listing est déjà prouvé PSA 8 exact ;
- PSA 8.5 reste distinct et n'est pas automatiquement ramené à Grade 8 ;
- PriceCharting est recherché même si une preuve SOLD-derived forte existe déjà, afin de conserver une référence systématique ;
- la preuve SOLD-derived forte garde cependant la priorité économique et le guide ne peut pas réparer un conflit matériel entre providers SOLD ;
- **aucune marge spéciale de 40 %** : le seuil économique normal V4 s'applique, actuellement 30 % ;
- une panne PriceCharting reste visible mais ne supprime pas une preuve SOLD forte déjà établie ;
- fallback public read-only, sans secret ; API officielle facultative si un token est fourni uniquement par l'environnement.

Exemple : guide PriceCharting `100 EUR`, pas de meilleure preuve externe, seuil V4 `30 %` -> une offre all-in `<=70 EUR` peut passer le gate économique si tous les autres gates sont satisfaits. L'ancien floor spécial à `40 %` (`<=60 EUR`) est supprimé.

## Architecture decision

Conserver **un orchestrateur Global avec adapters marketplace indépendants**, plutôt qu'un bot complet par vault.

Les adapters restent isolés au niveau retrieval/normalisation, tandis que l'identité stricte, les providers de valorisation, FX, déduplication, économie et notifications restent single-source-of-truth. Plusieurs bots complets dupliqueraient ces règles critiques et créeraient de la dérive.

## Safety

Inchangé :

- Pokémon cartes individuelles uniquement ;
- identité commerciale / microvariante stricte et fail-closed ;
- ASK/current auction/disparition != SOLD ;
- aucun achat, bid, checkout ou paiement automatique ;
- aucun secret dans repo/logs ;
- PR #8/V5 reste expérimentale et non mergée.

## Validation gate

Avant merge : suite V4 complète, suite Global, tests ciblés PriceCharting/source-role, compile Python, workflow YAML, `git diff --check`, bootstrap Global live read-only avec notifications/transactions désactivées, et assertions explicites `marketplace_listing_is_valuation=false` / `gcc_history_economic_authority=false`.

Le head exact et les run IDs de validation finale sont ajoutés seulement après CI verte. Ne pas merger PR #257 sans autorisation explicite utilisateur.
