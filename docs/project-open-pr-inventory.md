# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

> **Source dynamique de reprise pour les PR encore ouvertes.**
>
> Ce fichier complète `README.md`, `docs/project-capability-ledger.md` et `docs/project-branch-inventory.md`. L’état GitHub live reste l’autorité ultime.

Snapshot vérifié : **17 août 2026, après merge #123 et création #124**.

## Résultat exhaustif

GitHub contient désormais **121 pull requests au total** et exactement **15 PR ouvertes**. PR #122 et #123 ne sont plus ouvertes : #123 a été mergée dans `main` au SHA `a2878cae20987e3ff16c8aedf6f67d07957f039f`; #122 a été fermée/supersedée après que son travail soit entré dans `main` via #123.

| PR | Draft | Head / lignée vérifiée | Classification projet | Instruction |
|---|---:|---|---|---|
| #8 | oui | V5 `agent/v5-poketrace-cardmarket-market-data` | `V5_ONLY` | V5 expérimentale canonique. **Ne jamais merger dans main sans autorisation explicite.** |
| #54 | non | `agent/v4-kb-filter-stdlib-hotfix` | `SUPERSEDED / STALE_OPEN` | Son fix dépendances existe déjà sur `main`. Ne pas merger tel quel. |
| #87 | non | `fix/v4-gcc-only-30pct-notify` | `DEFERRED / BEHAVIOR_CHANGE` | Vrai changement produit encore non production : GCC-only illiquide dès 30 %, >=2 GCC SOLD, floor 0 €. Décision explicite requise. |
| #92 | oui | `agent/v5-ppt-identity-shadow` | `V5_ONLY / SHADOW` | PPT identity shadow V5, helper uniquement. |
| #96 | oui | `agent/v5-catalog-gap-hardening` | `V5_ONLY / DEFERRED` | Pocket digital + curated physical catalog gaps. |
| #106 | oui | `agent/v4-ppt-clean-20260816` | `SHADOW / DEFERRED` | Clean PPT V4 shadow, successeur de #90. |
| #107 | oui | `agent/japan-edge-ppt-clean-20260816` | `SHADOW / DEFERRED` | PPT Japan display-only. |
| #108 | oui | `feat/v4-global-multivault-edge-foundation` | `SHADOW / DEFERRED` | Fondation Global Multi-Vault. Utiliser la stack complète, pas cette PR seule. |
| #109 | oui | `feat/v4-global-live-shadow` | `SHADOW / DEFERRED` | Live shadow multi-vault. |
| #110 | oui | `feat/v4-global-rejection-diagnostics` | `SHADOW / DEFERRED` | Diagnostics de rejet multi-vault. |
| #111 | oui | `docs/repo-hygiene-readme-20260816` | `SUPERSEDED / STALE_OPEN` | Snapshot docs ancien, superseded par #123 + inventaires actuels. |
| #113 | oui | `feat/v4-global-retrieval-hardening` | `SHADOW / DEFERRED` | Retrieval hardening magi/Fanatics/COMC. |
| #114 | oui | `fix/v4-global-magi-sold-filter` | `SHADOW / DEFERRED` | Rejet des pages Magi explicitement SOLD dans la lane ASK. |
| #115 | oui | `fix/v4-global-comc-groudon-resolution` | `SHADOW / DEFERRED` | Route COMC exact-set facet, dernier child de la stack globale auditée. |
| #124 | oui | `aed8088d2368f4b72bc19cebc129cce66979dd1b` au snapshot initial CI | `CURRENT_RECOVERY / V4` | Récupère le contrat structuré PokeTrace V5 (`card_number` + `game`) dans V4 après TCGdex exact. Draft jusqu’à validation/docs finales; aucun merge implicite. |

Aucune PR de cette table n’est autorisée au merge par le seul fait d’être ouverte ou mergeable.

---

## PR #124 — récupération PokeTrace structurée

Root cause du run production #1076 (`32041486642`) : TCGdex résout **8/11** identités exactes, puis PokeTrace retourne **0/8** parce que V4 utilisait encore une recherche libre `name + number`, sans les champs structurés déjà utilisés par V5.

Contrat récupéré dans #124 :

- EN -> `game=pokemon` ;
- JA -> `game=pokemon-japanese` ;
- collector number canonique -> `card_number` ;
- PokeTrace reste **market-only après identité TCGdex** ;
- les gates V4 carte/set/numéro/langue/variant/grader/grade restent autoritaires ;
- aucune traduction/fuzzy comme preuve ;
- FR/DE/etc. ne gaspillent plus un appel PokeTrace qu’un gate langue V4 rejetterait ensuite ; APR/eBay restent les fallbacks.

Validation actuelle de la branche : run `32043115154`, job `95425820955` — **SUCCESS**, **676/676 tests PASS**, YAML PASS, `git diff --check` PASS, discovery read-only `80/80`, `effective_only=0`, `legacy_only=0`, actions économiques/notifications `0`.

Aucun live PokeTrace production n’a été lancé pour #124 et aucune amélioration live n’est revendiquée avant cette mesure.

---

## PR #54 — ouverte mais absorbée par `main`

Le workflow `v4-kb-shadow-ingest.yml` courant installe déjà `requirements.txt` avant les helpers V4. #54 reste donc `STALE_OPEN/SUPERSEDED`.

## PR #87 — vraie décision produit encore séparée

Le `main` courant conserve :

```text
V4_ILLIQUID_GCC_ONLY_MIN_UPSIDE_RATIO = 1.75
V4_ILLIQUID_GCC_ONLY_MIN_ABSOLUTE_UPSIDE_EUR = 10
```

#87 propose 30 % de décote, >=2 GCC SOLD exacts et floor 0 €. Ne pas l’absorber dans un travail provider/identité.

## Stack Global Multi-Vault

```text
#108 foundation
 -> #109 live shadow
 -> #110 rejection diagnostics
 -> #113 retrieval hardening
 -> #114 Magi SOLD filter
 -> #115 COMC exact-set route
```

Réutilisation future : repartir de la dernière stack compatible et la reporter proprement sur le `main` courant. Ne pas merger un child directement sur `main`.

---

## Règle de fraîcheur

Mettre à jour ce fichier lorsqu’une PR est créée, mergée, fermée, change de statut fonctionnel ou de chaîne de supersession. Pour toute décision de merge, **re-vérifier GitHub live**.