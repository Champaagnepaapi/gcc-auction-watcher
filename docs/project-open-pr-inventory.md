# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot GitHub vérifié le **18 août 2026**, après ouverture de la PR docs #136.

- `main` : `a52398685629e4baf4c8ac036851e2ae1a49b037`
- PR totales : **133**
- PR ouvertes : **16**
- PR #8 : expérimentale V5, draft, non mergée ; aucune autorisation de merge vers `main`.

## PR ouvertes

| PR | Draft | Branche | Classification / instruction |
|---|---:|---|---|
| #8 | oui | `agent/v5-poketrace-cardmarket-market-data` | **V5 canonique expérimentale**. Ne jamais merger dans `main` sans autorisation explicite. |
| #54 | non | `agent/v4-kb-filter-stdlib-hotfix` | `STALE_OPEN/SUPERSEDED` : fix déjà absorbé dans la stack Robot KB/main. Ne pas merger telle quelle. |
| #87 | non | `fix/v4-gcc-only-30pct-notify` | décision produit V4 non déployée : seuil GCC-only illiquide. Revalider sur le `main` courant avant toute décision. |
| #92 | oui | `agent/v5-ppt-identity-shadow` | V5 PPT shadow uniquement. |
| #96 | oui | `agent/v5-catalog-gap-hardening` | V5 Pocket/catalog gaps, deferred. |
| #106 | oui | `agent/v4-ppt-clean-20260816` | V4 PPT shadow propre, non production. |
| #107 | oui | `agent/japan-edge-ppt-clean-20260816` | Japan PPT display-only, non production. |
| #108 | oui | `feat/v4-global-multivault-edge-foundation` | Global Multi-Vault foundation shadow. |
| #109 | oui | `feat/v4-global-live-shadow` | Global live shadow, stacked. |
| #110 | oui | `feat/v4-global-rejection-diagnostics` | Global diagnostics, stacked. |
| #111 | oui | `docs/repo-hygiene-readme-20260816` | ancien snapshot docs, superseded par les inventaires/README courants. |
| #113 | oui | `feat/v4-global-retrieval-hardening` | Global retrieval hardening, stacked ; ne pas merger directement dans `main`. |
| #114 | oui | `fix/v4-global-magi-sold-filter` | child stacked : Magi SOLD guard ; ne pas merger directement dans `main`. |
| #115 | oui | `fix/v4-global-comc-groudon-resolution` | child stacked : COMC retrieval ; ne pas merger directement dans `main`. |
| #126 | oui | `fix/v4-poketrace-exact-provider-bridges-20260818` | **SUPERSEDED/STALE_OPEN** par #127/#128/#129 puis #130-#135. **Ne pas merger.** |
| #136 | oui | `docs/v4-tcgdex-poketrace-phase-close-20260818` | docs-only phase close après validation prod #135. Merge uniquement après revue + autorisation utilisateur explicite. |

Contrôle : **16 lignes / 16 PR ouvertes**.

## Changements depuis le snapshot précédent

- #129 à #135 ont été mergées/fermées ;
- #126 est restée ouverte mais est désormais explicitement superseded ;
- #136 est la PR docs de fermeture de phase ;
- aucun changement de statut de PR #8.

## Règle

Une PR ouverte n'est pas automatiquement une tâche à merger. Toujours re-vérifier base/head, supersession, tests et code courant. Les stacks V5/PPT/Global restent séparées de la production V4.
