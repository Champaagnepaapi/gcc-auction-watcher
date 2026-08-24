# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot GitHub vérifié le **24 août 2026** après merge #175.

- `main` vérifié : **`950694d66b04112fc1182f0b21d6008bb4560204`** (#175) ;
- recherche live GitHub : **19 PR ouvertes** ;
- PR #174 : Magi coverage, OPEN / DRAFT / NON MERGED, head `b2bb6087cd7d6122b20a9a919839334f09e773a6` avant synchronisation post-#175 ;
- PR #8 : V5 expérimentale, OPEN / DRAFT / NON MERGED ; ne jamais merger sans autorisation explicite.

Ce fichier recense les PR ouvertes pertinentes pour la gouvernance courante. Le contrôle live GitHub reste l'autorité avant tout merge.

## PR ouvertes pertinentes

| PR | Branche / ligne | Classification / instruction |
|---|---|---|
| #174 | `feat/v4-global-magi-coverage-20260823` | **ACTIVE / DRAFT.** Couverture Magi déterministe. Reprendre sur le `main` post-#175 avant nouvelle modification. Ne pas merger sans autorisation. |
| #159 | Battle Partners exact TCGdex | Correction TCGdex séparée, ouverte/non mergée. Revalider contre le `main` courant avant décision. |
| #141 | `diag/v4-global-provider-coverage-20260820` | `SUPERSEDED_DIAGNOSTIC` par #142/#140. |
| #138 | `shadow/v4-global-current-main-reintegration-20260819` | `SUPERSEDED_BY_139`. |
| #126 | `fix/v4-poketrace-exact-provider-bridges-20260818` | **SUPERSEDED** par #127→#135. Ne pas merger. |
| #115 | `fix/v4-global-comc-groudon-resolution` | `SUPERSEDED_BY_139`. |
| #114 | `fix/v4-global-magi-sold-filter` | `SUPERSEDED_BY_139`. |
| #113 | `feat/v4-global-retrieval-hardening` | `SUPERSEDED_BY_139`. |
| #111 | `docs/repo-hygiene-readme-20260816` | `STALE_OPEN/SUPERSEDED`. |
| #110 | `feat/v4-global-rejection-diagnostics` | `SUPERSEDED_BY_139`. |
| #109 | `feat/v4-global-live-shadow` | `SUPERSEDED_BY_139`. |
| #108 | `feat/v4-global-multivault-edge-foundation` | `SUPERSEDED_BY_139`. |
| #107 | `agent/japan-edge-ppt-clean-20260816` | Japan PPT display-only historique ; ne pas merger automatiquement. |
| #106 | `agent/v4-ppt-clean-20260816` | Ancien V4 PPT shadow ; ne pas merger automatiquement. |
| #96 | `agent/v5-catalog-gap-hardening` | V5 child/deferred. |
| #92 | `agent/v5-ppt-identity-shadow` | V5 PPT shadow. |
| #87 | `fix/v4-gcc-only-30pct-notify` | Décision produit V4 séparée/non déployée. |
| #54 | `agent/v4-kb-filter-stdlib-hotfix` | `STALE_OPEN/SUPERSEDED`. |
| #8 | `agent/v5-poketrace-cardmarket-market-data` | **V5 expérimentale. Ne jamais merger dans main sans autorisation explicite.** |

Contrôle live : **19 PR ouvertes** au moment de ce snapshot. Une PR ouverte n'est jamais automatiquement autorisée au merge.

## Phases récentes mergées

- #139 : réintégration Global ;
- #140/#142 : confirmation économique + bridge exact ;
- #145/#146 : notifications + activation ;
- #147/#148 : marketplace-first + cutover production ;
- #151 : registre schedule vers issue #150 ;
- #154 : `variants_detailed` TCGdex ;
- #156 : Global scale 50 ;
- #166 : cutover Robot KB PostgreSQL local / retrait writers Neon automatiques ;
- #168 : Cardova public read-only ;
- #169 : recovery schedule Global / cadence 20 min ;
- #171 : Fanatics native identity ;
- #173 : Magi native Japanese identity ;
- #175 : V4 eBay hard-hang isolation.

## Preuves récentes

- #173 : prod run `32634964197` sur `b5ddc393850303e7ca542ae68e4ed4d1145340d3`, SUCCESS, Magi 9 exact ;
- #175 : merge `950694d66b04112fc1182f0b21d6008bb4560204` ; runs post-merge `32738091183`, `32739149539`, `32740157203`, `32741180104`, `32742259467` SUCCESS ;
- aucun achat, bid, checkout ou paiement automatique.

PR #8 reste explicitement protégée. #174 est la ligne active Magi et doit rester séparée de V5 et de tout changement produit V4 indépendant.
