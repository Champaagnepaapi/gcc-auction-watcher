# Robot Pokémon / GCC Auction Watcher — snapshot topologique du dépôt

Snapshot GitHub vérifié le **17 août 2026** après merge #123 et création de PR #124.

## Topologie

```text
Repository: Champaagnepaapi/gcc-auction-watcher
Visibility: public
Default branch: main
main HEAD: a2878cae20987e3ff16c8aedf6f67d07957f039f
main branch protection: disabled at latest live check
required status checks on main: none enforced server-side at latest live check
Remote branches: 146
Pull requests total: 121
Pull requests open: 15
Issues hors PR: 3
Current workflow YAML files on main: 14
GitHub Actions workflow registry records: 80 at last exhaustive workflow audit
Tags: 0 at last exhaustive topology audit
Releases: 0 at last exhaustive topology audit
```

## Changements depuis le snapshot précédent

- PR #123 a été mergée dans `main` -> `a2878cae20987e3ff16c8aedf6f67d07957f039f`.
- PR #122 a été fermée/supersedée après intégration de son travail via #123.
- branche `fix/v4-poketrace-deterministic-market-retrieval-20260817` créée depuis ce `main`.
- PR #124 ouverte draft pour récupérer le contrat structured PokeTrace market retrieval déjà prouvé en V5.
- branches : 145 -> **146** ; PR ouvertes : 16 -> **15** ; PR total : 120 -> **121**.
- workflow tree, Issues, tags et releases n’ont pas été modifiés par cette phase.

## Risque important : `main` non protégé

Au dernier contrôle live, GitHub rapportait `protected=false` et aucun required status check imposé côté serveur. La discipline projet est donc la barrière effective : branche/PR dédiée, CI verte, checks de sécurité, re-vérification du SHA juste avant merge et autorisation explicite utilisateur.

PR #8 reste V5 expérimentale et ne doit jamais être mergée dans `main` sans autorisation explicite.

## Dépôt public / secrets

Ne jamais commiter clé API, token, mot de passe, cookie/session ou secret. Issue #1 reste limitée aux métadonnées minimales de runs. Aucun secret n’a été ajouté ou exposé par la phase #124.

## Où trouver le détail

```text
README.md
  -> handoff canonique de l'architecture courante

docs/project-capability-ledger.md
  -> capacités, statuts, supersessions, réutilisation

docs/project-branch-inventory.md
  -> 146/146 branches distantes

docs/project-open-pr-inventory.md
  -> 15/15 PR ouvertes

docs/project-workflow-inventory.md
  -> 14 workflows courants vs 80 records Actions au dernier audit exhaustif

docs/project-issue-inventory.md
  -> 3/3 issues et leur rôle réel

docs/v4-poketrace-run1076-audit.md
  -> root cause PokeTrace 0/8 et récupération V5 -> V4 dans #124
```

## Règle de fraîcheur

Les nombres de branches/PRs/workflows et la branch protection peuvent changer. Avant toute action destructive, merge ou changement de configuration, re-vérifier l’état GitHub live.