# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **20 août 2026**.

## Production canonique

- V4 production : `main`
- `main` : `c012284c423e9526fd2712001fdbce3a5cfafda3`
- dernier changement intégré : PR #140, Global economic confirmation gate, avec PR #142 absorbée
- V5 : PR #8, expérimentale/draft/non mergée dans `main`
- Robot KB/Neon : historique durable séparé

## Phase Global #139 → #142 : fermée en read-only

### #139 — réintégration

Le stack Global historique a été réintégré sur le main courant : GCC, Cardova, magi, Fanatics, COMC, identité commerciale stricte, diagnostics et hardenings.

### #140 — confirmation économique

Le Global peut désormais comparer une offre actionnable à une preuve gradée externe stricte :

- fixed ASK exact ou snapshot auction ≤5m avec all-in prouvé ;
- PPT/PokeTrace/eBay comptent comme une seule famille corrélée ;
- minimum 3 ventes agrégées pour un centre utilisable ;
- conflit GCC/externe >1.25 bloque ;
- fair confirmé = minimum entre GCC et externe ;
- ASK/current auction ne devient jamais SOLD.

### #142 — bridge exact provider

La classe de rejet observée live était une différence bornée de nomenclature provider après preuve macro exacte. Le bridge accepte uniquement les mécaniques `V/VSTAR/VMAX/ex/GX` ou `Mega <nom> ex` avec full collector number, set/préfixe TCGdex et langue exacts. Aucun fuzzy ni relaxation d'identité.

## Validation

Head combiné avant merge : `b10adebc1f6866ae4ec37e9ea01eeddd2a240c60`.

```text
Offline Validation   32351952230  SUCCESS
Dispatcher CI        32351952209  SUCCESS
Global               146/146 PASS
V4 multimarket        51/51 PASS
compile/YAML/diff     PASS
```

Live final read-only `32344120993` :

```text
TCGdex exact       5/5
PPT matched        4/5
PokeTrace matched  4/5
would_notify       0
conflicts blocked  1
```

Mewtwo `183/165` : GCC ~€155, externe ~€103.40, Fanatics ASK ~€99.10 -> ratio 1.499 -> `MARKET_CONFLICT_BLOCKED`.

Pikachu M-P reste `CLEAN_NO_MATCH` externe ; aucune correction ponctuelle n'est autorisée sans classe déterministe répétée.

## Statut opérationnel Global

**READ-ONLY uniquement.**

- `v4-global-live-shadow.yml` reste manuel `workflow_dispatch` ;
- `economic_confirmation` ne produit que `would_notify` diagnostique ;
- aucune notification automatique ;
- aucun schedule Global ;
- aucun achat, bid, checkout, paiement ou grading ;
- one-shot #142 supprimé avant merge.

## V4 principale

La lignée TCGdex/PokeTrace #123→#135 reste l'autorité d'identité production. Le backlog externe de la V4 normale continue à être drainé/mesuré séparément de Global.

Ne pas reprendre une ancienne PR/branche pour corriger un `NO_MATCH` sans d'abord démontrer une nouvelle classe répétée et déterministe.

## Prochaine direction

Deux axes distincts :

1. **V4 production** : continuer la couverture externe, mesurer les blockers récurrents, corriger uniquement des classes prouvées.
2. **Global Multi-Vault** : si l'utilisateur veut l'activer, ouvrir une phase séparée pour les notifications avec feature flag default-off, déduplication persistante, cadence explicite et live read-only de validation avant toute activation.

L'activation Global n'est **pas** implicite dans le merge #140.

## Invariants

- PokeTrace reste marché/prix après identité TCGdex ;
- aucun fuzzy/substr/Levenshtein/traduction comme preuve exacte ;
- ASK et enchère active ne sont jamais des SOLD ;
- RAW ne devient jamais valeur d'un slab ;
- identité/langue/grader/grade/microvariante incompatibles ne sont jamais mélangés ;
- aucun achat, bid, checkout ou paiement automatique ;
- PR #8 ne doit jamais être mergée dans `main` sans autorisation explicite.
