# Robot Pokémon / GCC Auction Watcher — snapshot topologique du dépôt

Snapshot vérifié le **20 août 2026** après la phase Global #139→#142.

## Autorité

```text
Repository: Champaagnepaapi/gcc-auction-watcher
Default branch: main
Last functional/runtime merge: c012284c423e9526fd2712001fdbce3a5cfafda3
main protected: false
Open pull requests after docs closeout: 17
Current workflow YAML files on main: 15
```

Des commits docs-only suivent le merge fonctionnel `c012284c...`. **Toujours re-vérifier le HEAD `main` GitHub live** avant une nouvelle modification ; ne pas interpréter un SHA docs-only comme un nouveau runtime.

Le dernier audit exhaustif des branches comptait 158 le 18 août ; plusieurs branches Global/diagnostic/docs ont été créées depuis. Le nombre distant courant n'a pas été ré-audité exhaustivement dans cette phase.

## Phase Global

- #139 : réintégration Global stricte ;
- #140 : confirmation économique externe PPT/PokeTrace ;
- #142 : bridge exact provider, absorbé dans #140 ;
- dernier merge fonctionnel/runtime : `c012284c423e9526fd2712001fdbce3a5cfafda3`.

Global reste **read-only** : aucune notification automatique, aucun schedule Global, aucune transaction.

## Validation

```text
head fonctionnel #140  b10adebc1f6866ae4ec37e9ea01eeddd2a240c60
Offline CI              32351952230 SUCCESS
Dispatcher CI           32351952209 SUCCESS
Global tests            146/146 PASS
V4 multimarket           51/51 PASS
Live read-only           32344120993 SUCCESS
TCGdex external exact    5/5
PPT matched              4/5
PokeTrace matched        4/5
would_notify             0
market conflict blocked  1
```

## PR importantes

- #8 : **OPEN / DRAFT / V5 EXPERIMENTAL / NON MERGED** ;
- #126 : **OPEN / DRAFT / SUPERSEDED** ;
- #138 : superseded par #139 ;
- #141 : diagnostic superseded par #142 ;
- #140 et #142 : mergées ;
- les PR ouvertes sont détaillées dans `docs/project-open-pr-inventory.md`.

## Workflows

15 YAML sont présents sur main. `v4-global-live-shadow.yml` reste manual-only et peut exécuter le mode read-only `economic_confirmation`. Le one-shot exact-bridge de #142 a été supprimé avant merge.

## Documents d'autorité

- `README.md` : handoff canonique ;
- `docs/project-current-phase.md` : phase fonctionnelle ;
- `docs/project-capability-ledger.md` : capacités/supersessions ;
- `docs/project-open-pr-inventory.md` : PR ouvertes ;
- `docs/project-workflow-inventory.md` : workflows présents ;
- `docs/project-branch-inventory.md` : branches pertinentes et règle d'audit ;
- `docs/project-issue-inventory.md` : issues hors PR.

## Invariants

- V4/main canonique ;
- PR #8 jamais mergée sans autorisation explicite ;
- ASK/enchère live != SOLD ;
- aucun fuzzy comme preuve exacte ;
- aucun achat, bid, checkout ou paiement automatique ;
- Robot KB/Neon séparé ;
- Global read-only != activation notification.
