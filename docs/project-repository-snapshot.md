# Robot Pokémon / GCC Auction Watcher — snapshot topologique du dépôt

Snapshot GitHub vérifié le **20 août 2026** après merge #140.

## Topologie vérifiée

```text
Repository: Champaagnepaapi/gcc-auction-watcher
Visibility: public
Default branch: main
main HEAD: c012284c423e9526fd2712001fdbce3a5cfafda3
main protected: false
Open pull requests: 17
Issues hors PR: 3 au dernier audit exhaustif
Current workflow YAML files on main: 15
Remote branch count: non ré-audité exhaustivement dans cette phase
```

Le dernier audit exhaustif des branches comptait 158 le 18 août ; plusieurs branches Global/diagnostic/docs ont été créées depuis. Ne pas réutiliser `158` comme nombre courant sans nouvel audit exhaustif.

## Phase fonctionnelle courante

Global Multi-Vault est désormais présent sur main **en read-only** :

- #139 : réintégration Global stricte ;
- #140 : confirmation économique externe PPT/PokeTrace ;
- #142 : bridge exact provider, absorbé dans #140 ;
- merge main final : `c012284c423e9526fd2712001fdbce3a5cfafda3`.

Le workflow Global reste manuel ; aucune notification automatique ni transaction n'a été activée.

## Validation Global

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

## Topologie PR importante

- #8 : **OPEN / DRAFT / V5 EXPERIMENTAL / NON MERGED** ; ne jamais merger sans autorisation explicite ;
- #126 : **OPEN / DRAFT / SUPERSEDED** ; ne pas merger ;
- #138 : ancien Global reintegration shadow, superseded par #139 ;
- #141 : diagnostic de couverture, superseded par #142 ;
- #140 et #142 : mergées ;
- 17 PR ouvertes détaillées dans `docs/project-open-pr-inventory.md`.

## Workflows

15 YAML sont réellement présents sur main. `v4-global-market-offline-validation.yml` fait partie du tree courant. `v4-global-live-shadow.yml` est manual-only et peut exécuter le mode read-only `economic_confirmation`.

Le one-shot exact-bridge utilisé pendant #142 a été supprimé avant merge.

## Invariants

- V4 sur `main` reste production canonique ;
- PokeTrace reste marché/prix après identité TCGdex ;
- aucune preuve fuzzy/substr/traduction ;
- ASK/enchère live != SOLD ;
- aucun achat, bid, checkout ou paiement automatique ;
- Robot KB/Neon reste séparé de la décision commerciale ;
- V5/PR #8 reste séparée ;
- Global read-only n'est pas une activation notification.

## Documents d'autorité

```text
README.md
  -> handoff canonique

docs/project-current-phase.md
  -> phase fonctionnelle courante

docs/project-capability-ledger.md
  -> capacités et supersessions

docs/project-branch-inventory.md
  -> autorité branches + règle d'audit exhaustif

docs/project-open-pr-inventory.md
  -> 17 PR ouvertes vérifiées
docs/project-workflow-inventory.md
  -> 15 workflows présents sur main

docs/project-issue-inventory.md
  -> issues hors PR
```

## Règle de fraîcheur

Avant tout merge, suppression ou changement de configuration, re-vérifier GitHub live. Ne jamais extrapoler un ancien nombre de branches/workflows/PRs comme état courant.
