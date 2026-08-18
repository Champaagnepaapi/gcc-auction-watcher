# Robot Pokémon / GCC Auction Watcher — snapshot topologique du dépôt

Snapshot GitHub vérifié le **18 août 2026** pendant la PR docs #136.

## Topologie

```text
Repository: Champaagnepaapi/gcc-auction-watcher
Visibility: public
Default branch: main
main HEAD: a52398685629e4baf4c8ac036851e2ae1a49b037
main protected: false
Remote branches: 158
Pull requests total: 133
Pull requests open: 16
Issues hors PR: 3
Current workflow YAML files on main: 14
GitHub Actions workflow registry records: 80 at last exhaustive workflow audit
Tags: 0 at last exhaustive topology audit
Releases: 0 at last exhaustive topology audit
```

## Phase production courante

La lignée V4 TCGdex/PokeTrace #123→#135 est terminée et la dernière classe corrigée est validée en production.

PR #135 :
- feature head `1bcdccaae8997755cc6f65c44dd9770c69cabbe9` ;
- merge `a52398685629e4baf4c8ac036851e2ae1a49b037` ;
- objet : récupération fail-closed d'un set exact depuis le catalogue TCGdex immuable lorsque le REST expose un namespace stale/conflictuel.

Run production naturel `32160680888` sur le merge SHA exact : **SUCCESS**.
Il prouve la correction vers `SV10` pour Team Rocket's Houndoom `100/098`, Meowth `109/098` et Moltres ex `112/098`. Crobat `117/098` n'était pas échantillonné dans ce run ; aucune preuve live spécifique Crobat n'est revendiquée.

## Topologie PR importante

- #8 : **OPEN / DRAFT / V5 EXPERIMENTAL / NON MERGED** ; ne jamais merger dans `main` sans autorisation explicite ;
- #126 : **OPEN / DRAFT / SUPERSEDED** par #127/#128 et la suite ; ne pas merger ;
- #136 : **OPEN / DRAFT / DOCS-ONLY**, fermeture documentaire de la phase #123→#135 ;
- 16 PR ouvertes au total, détaillées dans `docs/project-open-pr-inventory.md`.

## Couverture et risque restant

Le run `32160680888` avait une discovery complète mais une couverture marché externe encore incomplète : backlog externe ~2031, ETA diagnostique ~204 runs. Le `0 opportunity` du run n'est donc pas présenté comme un verdict économique globalement trustworthy.

## Invariants

- V4 sur `main` reste production canonique ;
- PokeTrace reste marché/prix après identité TCGdex ;
- aucune preuve fuzzy/substr/traduction ;
- ASK/enchère live != SOLD ;
- aucun achat, bid, checkout ou paiement automatique ;
- Robot KB/Neon reste séparé de la décision commerciale V4 ;
- V5/PR #8 reste séparée.

## Documents d'autorité

```text
README.md
  -> handoff canonique de production

docs/project-current-phase.md
  -> phase fonctionnelle courante

docs/project-capability-ledger.md
  -> capacités et supersessions

docs/project-branch-inventory.md
  -> 158/158 branches distantes

docs/project-open-pr-inventory.md
  -> 16/16 PR ouvertes

docs/project-workflow-inventory.md
  -> 14 workflows courants vs 80 records au dernier audit exhaustif

docs/project-issue-inventory.md
  -> 3/3 issues
```

## Règle de fraîcheur

Les nombres de branches/PRs/workflows et la branch protection peuvent changer. Avant tout merge, suppression ou changement de configuration, re-vérifier GitHub live.
