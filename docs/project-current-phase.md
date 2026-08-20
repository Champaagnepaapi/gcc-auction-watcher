# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **20 août 2026**.

## Autorité

- V4 production : `main`
- dernier **merge fonctionnel/runtime** : `c012284c423e9526fd2712001fdbce3a5cfafda3` (PR #140)
- des commits docs-only suivent ce SHA sur `main` ; toujours re-vérifier le HEAD GitHub live avant une nouvelle action
- V5 : PR #8, expérimentale/draft/non mergée dans `main`
- Robot KB/Neon : historique durable séparé

## Phase Global #139 → #142 : fermée en read-only

#139 a réintégré le stack Global strict. #140 ajoute la confirmation économique externe. #142 ajoute le bridge exact de nomenclature provider et a été absorbée dans #140 avant son merge vers main.

### Gate économique

- fixed ASK exact ou snapshot auction ≤5m avec all-in prouvé ;
- PPT/PokeTrace/eBay = une seule famille corrélée ;
- minimum 3 ventes agrégées pour un centre externe utilisable ;
- conflit GCC/externe >1.25 bloque ;
- fair confirmé = `min(GCC, externe)` ;
- ASK/current auction ne devient jamais SOLD.

### Bridge #142

Seulement après full collector number, set/préfixe TCGdex et langue exacts : nomenclature mécanique bornée `V/VSTAR/VMAX/ex/GX` ou `Mega <nom> ex`. `Unlimited` non matériel uniquement si TCGdex exact prouve `firstEdition=false`. Aucun fuzzy.

## Validation

Head fonctionnel #140 : `b10adebc1f6866ae4ec37e9ea01eeddd2a240c60`.

```text
Offline Validation   32351952230  SUCCESS
Dispatcher CI        32351952209  SUCCESS
Global               146/146 PASS
V4 multimarket        51/51 PASS
compile/YAML/diff     PASS
```

Live final read-only `32344120993` : TCGdex 5/5, PPT 4/5, PokeTrace 4/5, `would_notify=0`, 1 conflit bloqué. Mewtwo `183/165` : GCC ~€155 vs externe ~€103.40, Fanatics ASK ~€99.10 -> `MARKET_CONFLICT_BLOCKED`.

Pikachu M-P reste `CLEAN_NO_MATCH` externe ; aucune correction ponctuelle sans classe déterministe répétée.

## Statut opérationnel Global

**READ-ONLY uniquement.**

- `v4-global-live-shadow.yml` reste manuel `workflow_dispatch` ;
- `economic_confirmation` ne produit que `would_notify` diagnostique ;
- aucune notification automatique ;
- aucun schedule Global ;
- aucun achat, bid, checkout, paiement ou grading ;
- one-shot #142 supprimé avant merge.

## Prochaine direction

1. V4 production : continuer à drainer/mesurer la couverture externe et ne corriger que des classes prouvées.
2. Global : seulement si décidé, phase séparée d'activation notification avec feature flag default-off, déduplication persistante, cadence explicite et nouveau live de validation.

L'activation Global n'est **pas** implicite dans le merge #140.

## Invariants

- PokeTrace marché/prix après identité TCGdex ;
- aucun fuzzy/substr/Levenshtein/traduction comme preuve exacte ;
- ASK et enchère active ne sont jamais des SOLD ;
- RAW ne devient jamais valeur d'un slab ;
- aucune identité/langue/grader/grade/microvariante incompatible mélangée ;
- aucun achat, bid, checkout ou paiement automatique ;
- PR #8 ne doit jamais être mergée dans `main` sans autorisation explicite.
