# Robot Pokémon / GCC Auction Watcher — snapshot topologique du dépôt

Snapshot GitHub vérifié le **18 août 2026** pendant PR #129.

## Topologie

```text
Repository: Champaagnepaapi/gcc-auction-watcher
Visibility: public
Default branch: main
main HEAD: 4737604a1685f344ced65ede1ed49b4a1b9b7f6d
Remote branches: 151
Pull requests total: 126
Pull requests open: 16
Issues hors PR: 3
Current workflow YAML files on main: 14
GitHub Actions workflow registry records: 80 at last exhaustive workflow audit
Tags: 0 at last exhaustive topology audit
Releases: 0 at last exhaustive topology audit
```

## Changements depuis le snapshot précédent

- #124, #125, #127 et #128 ont été mergées dans `main` dans la lignée PokeTrace V4.
- `main` courant = `4737604a1685f344ced65ede1ed49b4a1b9b7f6d` (merge #128).
- PR #126 reste une ancienne lignée draft pré-#127/#128 et ne doit pas être mergée telle quelle.
- branche `fix/v4-poketrace-ja-search-regression-20260818` créée depuis le `main` courant; PR #129 ouverte.
- branches distantes vérifiées : **151/151**.
- PR ouvertes vérifiées : **16/16**.

## Phase #129

Le run production post-#128 `32119349938` est SUCCESS mais PokeTrace reste `5 attempted | 0 exact | 5 no-match`; les cinq probes JA ont `provider_candidates=0`.

Le run post-#127 avait auparavant prouvé que PokeTrace retrouvait des candidats JA avec le nom canonique/romanisé, le numéro imprimé paddé et `game=pokemon-japanese`. #129 restaure ce contrat de retrieval et conserve le nom TCGdex localisé uniquement comme alias d'acceptation du même `card_id + set_id + localId` exact.

## Sécurité

- aucun fuzzy ou traduction comme preuve;
- aucun changement fair value / `max_recommended` / seuil économique;
- aucun achat, bid, checkout, paiement ou grading payant;
- ASK/enchère live jamais transformé en SOLD;
- PR #8 reste V5 expérimentale, intacte et non mergée.

## Où trouver le détail

```text
README.md
  -> handoff canonique de production

docs/project-current-phase.md
  -> phase active #129

docs/project-capability-ledger.md
  -> capacités et supersessions

docs/project-branch-inventory.md
  -> 151/151 branches distantes

docs/project-open-pr-inventory.md
  -> 16/16 PR ouvertes

docs/project-workflow-inventory.md
  -> 14 workflows courants vs 80 records au dernier audit exhaustif

docs/project-issue-inventory.md
  -> 3/3 issues

docs/v4-poketrace-run32119349938-regression.md
  -> preuve et root cause de la régression post-#128
```

## Règle de fraîcheur

Les nombres de branches/PRs/workflows et la branch protection peuvent changer. Avant toute action destructive, merge ou changement de configuration, re-vérifier GitHub live.