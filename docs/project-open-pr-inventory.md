# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot GitHub vérifié le **20 août 2026** pendant la validation de la phase notifications Global #145.

- dernier merge fonctionnel/runtime sur `main` : `c012284c423e9526fd2712001fdbce3a5cfafda3`
- des commits docs-only suivent ce SHA sur `main` ; re-vérifier le HEAD live
- PR #8 : expérimentale V5, draft, non mergée.

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
| #145 | oui | `feat/v4-global-notification-activation-20260820` | **ACTIVE / VALIDATED DEFAULT-OFF.** Notifications Global confirmées + dédup/rotation/cadence + résilience TCGdex bornée. Ne pas merger ni activer `GLOBAL_NOTIFY_ENABLED=true` sans autorisation explicite. |

## Phase Global

- #139 : mergée vers main ;
- #140 : confirmation économique mergée, dernier merge runtime `c012284c...` ;
- #142 : bridge exact provider absorbé dans #140 ;
- #143/#144 : docs de fermeture/correction, aucun runtime ;
- #145 : phase notification default-off en cours de validation ; live dry-run résilient `32359861668` SUCCESS, TCGdex 5/5, PPT 4/5, PokeTrace 4/5, `sent=0`.

Une PR ouverte n'est pas une tâche à merger. Toujours vérifier base/head/supersession/tests avant action.
