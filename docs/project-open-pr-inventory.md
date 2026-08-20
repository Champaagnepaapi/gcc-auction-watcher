# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot GitHub vérifié le **20 août 2026**, après merge des PR #142 puis #140.

- `main` : `c012284c423e9526fd2712001fdbce3a5cfafda3`
- PR ouvertes vérifiées : **17**
- PR #8 : expérimentale V5, draft, non mergée ; aucune autorisation de merge vers `main`.

## PR ouvertes

| PR | Draft | Branche | Classification / instruction |
|---|---:|---|---|
| #8 | oui | `agent/v5-poketrace-cardmarket-market-data` | **V5 canonique expérimentale. Ne jamais merger dans `main` sans autorisation explicite.** |
| #54 | non | `agent/v4-kb-filter-stdlib-hotfix` | `STALE_OPEN/SUPERSEDED` : dépendance déjà absorbée. Ne pas merger telle quelle. |
| #87 | non | `fix/v4-gcc-only-30pct-notify` | Décision produit V4 séparée/non déployée. Revalider sur main avant toute décision. |
| #92 | oui | `agent/v5-ppt-identity-shadow` | V5 PPT shadow uniquement. |
| #96 | oui | `agent/v5-catalog-gap-hardening` | V5 child/deferred. Aucun merge de #8 implicite. |
| #106 | oui | `agent/v4-ppt-clean-20260816` | Ancien V4 PPT shadow propre. La capacité PPT Global actuelle est intégrée séparément par #140 ; ne pas merger automatiquement. |
| #107 | oui | `agent/japan-edge-ppt-clean-20260816` | Japan PPT display-only historique, non autorisé automatiquement. |
| #108 | oui | `feat/v4-global-multivault-edge-foundation` | `SUPERSEDED_BY_139` : fondation Global historique. Ne pas merger directement. |
| #109 | oui | `feat/v4-global-live-shadow` | `SUPERSEDED_BY_139` : live shadow historique. |
| #110 | oui | `feat/v4-global-rejection-diagnostics` | `SUPERSEDED_BY_139` : diagnostic historique. |
| #111 | oui | `docs/repo-hygiene-readme-20260816` | `STALE_OPEN/SUPERSEDED` docs. |
| #113 | oui | `feat/v4-global-retrieval-hardening` | `SUPERSEDED_BY_139` : hardening absorbé par la réintégration. |
| #114 | oui | `fix/v4-global-magi-sold-filter` | `SUPERSEDED_BY_139` : Magi SOLD guard absorbé. |
| #115 | oui | `fix/v4-global-comc-groudon-resolution` | `SUPERSEDED_BY_139` : COMC fallback absorbé. |
| #126 | oui | `fix/v4-poketrace-exact-provider-bridges-20260818` | **SUPERSEDED** par #127→#135. **Ne pas merger.** |
| #138 | oui | `shadow/v4-global-current-main-reintegration-20260819` | `SUPERSEDED_BY_139` : branche préparatoire de réintégration. |
| #141 | oui | `diag/v4-global-provider-coverage-20260820` | `SUPERSEDED_DIAGNOSTIC` : preuve ayant conduit à #142, maintenant absorbée dans #140/main. Ne pas merger comme fonctionnalité. |

Contrôle : **17 lignes / 17 PR ouvertes**.

## PR de la phase Global désormais fermées/mergées

- #139 : merge de la réintégration Global read-only vers main ;
- #140 : merge de la confirmation économique Global vers main, merge SHA `c012284c423e9526fd2712001fdbce3a5cfafda3` ;
- #142 : bridge exact provider, mergé d'abord dans la branche #140 puis absorbé par son merge vers main.

## Règle

Une PR ouverte n'est pas automatiquement une tâche à merger. Toujours re-vérifier base/head, supersession, tests et code courant. Les PR historiques Global ci-dessus restent utiles comme provenance mais ne doivent pas être rejouées sur main.

Aucune PR V5 n'a été mergée pendant cette phase.
