# Robot Pokémon / GCC Auction Watcher — snapshot topologique du dépôt

Snapshot GitHub vérifié le **17 août 2026** après l'audit de récupération complet.

## Topologie

```text
Repository: Champaagnepaapi/gcc-auction-watcher
Visibility: public
Default branch: main
main HEAD: c8a495226f9e9800e5e1e2ac6a730ea21b1c3383
main branch protection: disabled
required status checks on main: none enforced server-side
Remote branches: 145
Pull requests total: 120
Pull requests open: 16
Issues hors PR: 3
Current workflow YAML files on main: 14
GitHub Actions workflow registry records: 80
Tags: 0
Releases: 0
```

## Risque important : `main` n'est pas protégé côté GitHub

L'API GitHub rapporte pour `main` :

```text
protected=false
protection.enabled=false
required_status_checks.enforcement_level=off
```

Conséquence : **GitHub ne fournit actuellement pas de barrière serveur empêchant un push/merge direct non validé sur `main`.** La gouvernance projet et la discipline de PR/CI constituent donc la protection effective.

Règles obligatoires tant que cette configuration reste vraie :

- aucune modification directe de `main` pour un changement non trivial ;
- branche/PR dédiée ;
- CI ciblée/full pertinente verte ;
- compile/YAML/diff check selon scope ;
- live read-only seulement lorsqu'il est réellement nécessaire et autorisé ;
- re-vérifier le SHA de `main` et le head de la PR immédiatement avant merge ;
- merge uniquement après autorisation utilisateur explicite quand la gouvernance du projet l'exige ;
- PR #8 ne doit jamais être mergée dans `main` sans autorisation explicite.

**Ne pas activer/modifier la branch protection pendant cet audit** : c'est un changement de configuration du dépôt qui doit être décidé séparément par l'utilisateur.

## Repo public

Le dépôt est `public`. Cela renforce une règle déjà non négociable :

- ne jamais commiter clé API, token, mot de passe, cookie/session ou secret ;
- conserver les secrets uniquement dans les mécanismes GitHub Secrets/variables appropriés ;
- ne pas copier des logs complets contenant potentiellement des secrets dans Issues/README/docs ;
- Issue #1 doit continuer à ne stocker que les métadonnées minimales de runs.

Aucun secret n'a été lu, copié ou écrit pendant cet audit.

## Où trouver le détail

```text
README.md
  -> état canonique / architecture courante

docs/project-capability-ledger.md
  -> capacités, statuts, supersessions, instructions de réutilisation

docs/project-branch-inventory.md
  -> 145/145 branches distantes

docs/project-open-pr-inventory.md
  -> 16/16 PR ouvertes + stale/pending/stack classifications

docs/project-workflow-inventory.md
  -> 14 workflows courants vs 80 records Actions historiques

docs/project-issue-inventory.md
  -> 3/3 issues et leur rôle réel
```

## Règle de fraîcheur

Les nombres de branches/PRs/workflows et la branch protection peuvent changer. Avant toute action destructive, merge ou changement de configuration, re-vérifier l'état GitHub live. Ce snapshot est une mémoire de reprise, pas un substitut à l'état réel du dépôt.
