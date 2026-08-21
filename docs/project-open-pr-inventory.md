# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot GitHub vérifié le **21 août 2026** après le merge #154.

- `main` vérifié : `c3e3da39b79eb71cfdfc864bb865c4a4e7154e0c` (merge #154)
- recherche live : **17 PR ouvertes** ;
- PR #8 : expérimentale V5, draft, ouverte, non mergée, head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f`.

Ce fichier recense les PR ouvertes **pertinentes pour la gouvernance courante** ; ne pas utiliser le nombre de lignes comme compteur exhaustif GitHub sans nouvel audit live.

## PR ouvertes pertinentes

| PR | Draft | Branche | Classification / instruction |
|---|---:|---|---|
| #8 | oui | `agent/v5-poketrace-cardmarket-market-data` | **V5 expérimentale. Ne jamais merger dans main sans autorisation explicite.** |
| #54 | non | `agent/v4-kb-filter-stdlib-hotfix` | `STALE_OPEN/SUPERSEDED`. |
| #87 | non | `fix/v4-gcc-only-30pct-notify` | Décision produit V4 séparée/non déployée. |
| #92 | oui | `agent/v5-ppt-identity-shadow` | V5 PPT shadow. |
| #96 | oui | `agent/v5-catalog-gap-hardening` | V5 child/deferred. |
| #106 | oui | `agent/v4-ppt-clean-20260816` | Ancien V4 PPT shadow ; ne pas merger automatiquement. |
| #107 | oui | `agent/japan-edge-ppt-clean-20260816` | Japan PPT display-only historique. |
| #108 | oui | `feat/v4-global-multivault-edge-foundation` | `SUPERSEDED_BY_139`. |
| #109 | oui | `feat/v4-global-live-shadow` | `SUPERSEDED_BY_139`. |
| #110 | oui | `feat/v4-global-rejection-diagnostics` | `SUPERSEDED_BY_139`. |
| #111 | oui | `docs/repo-hygiene-readme-20260816` | `STALE_OPEN/SUPERSEDED`. |
| #113 | oui | `feat/v4-global-retrieval-hardening` | `SUPERSEDED_BY_139`. |
| #114 | oui | `fix/v4-global-magi-sold-filter` | `SUPERSEDED_BY_139`. |
| #115 | oui | `fix/v4-global-comc-groudon-resolution` | `SUPERSEDED_BY_139`. |
| #126 | oui | `fix/v4-poketrace-exact-provider-bridges-20260818` | **SUPERSEDED** par #127→#135. **Ne pas merger.** |
| #138 | oui | `shadow/v4-global-current-main-reintegration-20260819` | `SUPERSEDED_BY_139`. |
| #141 | oui | `diag/v4-global-provider-coverage-20260820` | `SUPERSEDED_DIAGNOSTIC` par #142/#140. |

Contrôle live : **17 lignes / 17 PR ouvertes**. Aucun de ces vieux shadows/superseded n'est requis pour #153/#154.

## Phase récente mergée

- #139 : réintégration Global ;
- #140/#142 : confirmation économique + bridge exact ;
- #145/#146 : notifications + activation ;
- #147/#148 : marketplace-first + cutover production ;
- #151 : registre schedule vers issue #150 ;
- #153 : cadence Global 10 min dans le workflow existant ;
- #154 : `variants_detailed` TCGdex comme preuve microvariante déterministe.

Preuves : premier schedule registre `32411433425`, cadence #153 observée `32443663511`, CI/live #154 `32444255909` SUCCESS, 221/221 Global + 51/51 V4 multimarket.

PR #154 est mergée et n'appartient plus à la surface ouverte. Une PR ouverte n'est jamais une tâche à merger automatiquement. PR #8 reste explicitement protégée.