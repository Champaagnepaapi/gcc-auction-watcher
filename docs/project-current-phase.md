# Robot Pokémon / GCC Auction Watcher — phase courante

## État canonique — 14 septembre 2026

Production V4 : `main@3c596370ee7fcde93c969139541bc003e7012b6e` après merge de la PR #268.

Runtime multi-market validé avant merge : `29f448a7441e82267fc9d84c2b0f9a52168e77cb`.
Closeout documentaire pré-merge : `c846aa6067d7aea0e8aa0812cdeec02cf3524bb5`.
Rapport de référence : [`v4-multimarket-readiness-20260914.md`](v4-multimarket-readiness-20260914.md).

PR #8/V5 reste OPEN/DRAFT/NON-MERGED et séparée de V4. Robot KB reste séparé de la décision commerciale V4 (`V4_USE=false`). Neon reste hors du chemin de production.

## Classement multi-market actuel

| Marketplace | État | Résiduel principal |
|---|---|---|
| GCC | **OPERATIONAL** | Chemin vault validé : discovery → identité exacte → valorisation indépendante → coût → décision. Livraison domicile hors de la preuve de coût validée. |
| Fanatics | **PROVIDER_BLOCKED** | Coût acheteur final et valorisation indépendante compatible avec la microvariante non prouvés. |
| COMC | **PROVIDER_BLOCKED** | Financement/taxe/mode de détention-livraison non prouvés ; aucune valeur canonique exploitable dans la sélection validée. |
| Magi | **PROVIDER_BLOCKED** | Route/coût acheteur non prouvés ; certaines projections catalogue/valeurs gradées exactes absentes. |
| Cardova | **PROVIDER_BLOCKED** | Financement/paiement et premium applicables non prouvés ; aucune valeur indépendante exacte dans la sélection validée. |
| Mercari | **PROVIDER_BLOCKED** | Preuves item de langue/numéro/grade/matériau insuffisantes ou contradictoires ; coût acheteur absent. |
| SNKRDUNK | **PROVIDER_BLOCKED** | Langue de carte et offre individuelle non prouvées ; données observées de type catalogue/AggregateOffer ; route/coût acheteur absents. |

`PROVIDER_BLOCKED` décrit ici le chemin économique autonome dans les conditions publiques auditées. Cela ne signifie pas que le site est inaccessible. Pagination partielle, caps volontaires et budgets bornés restent des limites logicielles séparées, pas des preuves de blocage fournisseur.

## Ce que #268 a mis en production

- P1–P4 conservés : aucun nom canonique fabriqué ; Master/Poke Ball fail-closed avec preuve source exacte ; vraies dimensions V2+V3 ; aliases Fanatics bornés au provider.
- P5/P6 : PriceCharting et PPT reviewed-set passent par un gate canonique strict ; contradictions nom/set/numéro/langue/grade/matériau restent bloquantes.
- P7 : wrappers/installers Fanatics idempotents et sans récursion.
- P8 : pagination Cardova rattachée à la bonne lane/enveloppe/page ; aucune complétude inventée.
- COMC dispose d'une discovery autonome.
- Mercari et SNKRDUNK disposent de routes publiques read-only intégrées à Global.
- Le DOM Mercari est lié à l'item et couvert par contrat Chromium.
- Les coûts inconnus restent inconnus ; aucune hypothèse de taxe/frais/livraison n'est fabriquée.
- TCGdex ne propage les noms multilingues qu'avec preuve de la même carte source ; panne/budget/403 ne deviennent pas des `NO_MATCH` propres.
- Auction sépare `RESOLVED`, `ENDED`, `UNKNOWN`, `INSPECTION_ERROR` et `OUT_OF_SCOPE`. Aucun de ces états ne devient automatiquement SOLD.
- PokeTrace fonctionne avec un plafond effectif FREE lorsque requis ; donnée de plan inaccessible != `NO_MATCH`.
- PriceCharting public HTTP 403 reste `provider unavailable`, sans contournement.

## Validation de référence

Runtime `29f448a7441e82267fc9d84c2b0f9a52168e77cb` :

- Global `34812934273` : **SUCCESS** ;
- Auction `34812934319` : **SUCCESS** ;
- Cardova `34812934329` : **SUCCESS** ;
- 632 tests Global, dont 4 contrats DOM exécutés en CI ;
- 1 011 tests V4, 2 ignorés ;
- 51 tests multimarket ;
- compilation, YAML et diff-check : PASS ;
- zéro achat/bid/checkout/paiement ;
- zéro opportunité signalable et zéro notification dans le live de référence.

Closeout `c846aa6067d7aea0e8aa0812cdeec02cf3524bb5` : Global, Auction, Cardova et validation Robot KB automatiques **SUCCESS** avant merge.

Merge production #268 : `3c596370ee7fcde93c969139541bc003e7012b6e`.

## Invariants

- ASK / annonce active / enchère live / disparition / ENDED / OUT_OF_SCOPE != SOLD ;
- une marketplace où la carte est achetable ne prouve jamais seule sa fair value ;
- aucune panne provider n'est transformée en preuve négative de marché ;
- aucune relaxation langue/grader/grade/set/numéro/microvariante ;
- identité ambiguë = blocage ou revue manuelle ;
- aucun achat, bid, checkout ou paiement automatique ;
- aucun contournement WAF/anti-bot ;
- PR #8/V5 reste séparée et ne doit pas être mergée sans autorisation explicite ;
- Robot KB/Neon restent séparés de V4.

## Prochaine phase

1. observer les premiers runs naturels post-merge de `main@3c596370...` et vérifier absence de régression ;
2. traiter les providers bloqués **un par un**, uniquement si une preuve externe propre permet réellement de lever le blocage ;
3. priorité : obtenir le coût acheteur complet et les preuves d'identité/valorisation manquantes sans augmenter artificiellement les budgets ;
4. conserver la priorité des preuves de prix : SOLD exact récent → SOLD exact plus ancien ajusté → fixed ask compatible → snapshot d'enchère ≤5 min si aucun SOLD ;
5. ne jamais présenter une limite logicielle volontaire comme un blocage fournisseur, ni un `PROVIDER_BLOCKED` comme une panne du site.

### Ordre recommandé de travail

- **Fanatics** : déjà 2 identités EXACT observées ; chercher d'abord la preuve de coût acheteur final et une valorisation indépendante compatible avec la microvariante.
- **Magi** : identité commerciale déjà relativement forte ; chercher coût/route acheteur puis valeurs gradées exactes manquantes.
- **COMC / Cardova** : clarifier proprement le coût acheteur total et les conditions de détention/livraison/premium avant toute décision économique autonome.
- **Mercari / SNKRDUNK** : renforcer d'abord la preuve item-level déterministe ; aucun élargissement d'identité pour gagner du recall.

Les caps et budgets ne doivent être relevés qu'après preuve qu'ils sont le vrai goulot et que le changement respecte les limites provider.
