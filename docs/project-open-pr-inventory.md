# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot GitHub vérifié le **20 août 2026** après le merge #151.

- `main` vérifié : `c9539ca521f69b43b3d93e621fb21447a69f3fe7` (merge #151)
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

## Phase Global récente — fermée côté code

- #139 : réintégration Global mergée ;
- #140/#142 : confirmation économique + bridge exact ;
- #145/#146 : notifications + activation ;
- #147 : marketplace-first discovery, merge `5a1b0f050098b560e812a4dc6e64a9f8d40a8897` ;
- #148 : cutover production, merge `ea9a69b375434031c935de8d25fcc12acd1a1c93` ;
- #149 : fermeture documentaire #147/#148 ;
- #151 : registre autonome des schedules Global vers issue #150, merge `c9539ca521f69b43b3d93e621fb21447a69f3fe7`.

Validation #151 : run `32410224171` SUCCESS, **203/203 Global + 51/51 V4**, live read-only SUCCESS, aucune transaction.

La prochaine preuve attendue n'est pas une PR : c'est le premier commentaire automatique de l'issue #150 produit par un vrai `schedule` post-#151.

Une PR ouverte n'est jamais une tâche à merger automatiquement. PR #8 reste explicitement protégée.