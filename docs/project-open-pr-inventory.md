# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot GitHub pertinent re-vérifié le **26 août 2026** après merge de #180. Le contrôle GitHub live reste l'autorité et il ne faut **ne pas utiliser le nombre de lignes comme compteur exhaustif GitHub**.

```text
main runtime                   9365f5cd9f8949580c4e48f00ba8c4e419c22145
PR #178                        MERGED / 545223613ce21e6c4cf886e07201bc3c105a5e69
PR #179                        MERGED / ac5f7c734685422612a0f24690af22910eefa951
PR #180                        MERGED / 9365f5cd9f8949580c4e48f00ba8c4e419c22145
PR #8                          OPEN / DRAFT / NON MERGED
```

## PR ouvertes **pertinentes pour la gouvernance courante**

| PR | Classification / instruction |
|---|---|
| #176 | `STALE_OPEN / DOCS`. Handoff eBay ancien ; revalider avant tout merge. |
| #159 | `STALE_OPEN/SUPERSEDED` fonctionnellement par #177 Battle Partners déjà mergée. Ne pas rejouer telle quelle. |
| #141 | `SUPERSEDED_DIAGNOSTIC` par #142/#140. |
| #138 | `SUPERSEDED_BY_139`. |
| #126 | `STALE_OPEN/SUPERSEDED` par #127→#135. Ne pas merger. |
| #115 | `SUPERSEDED_BY_139` / child historique Global. |
| #114 | `SUPERSEDED_BY_139` / child historique Global. |
| #113 | `SUPERSEDED_BY_139` / child historique Global. |
| #110 | `SUPERSEDED_BY_139` / diagnostic historique. |
| #111 | `STALE_OPEN/SUPERSEDED` docs. |
| #109 | `SUPERSEDED_BY_139` / stack Global historique. |
| #108 | `SUPERSEDED_BY_139` / fondation Global historique. |
| #107 | Japan Edge PPT display-only historique ; ne pas merger automatiquement. |
| #106 | ancien V4 PPT shadow ; ne pas merger automatiquement. |
| #96 | `V5 child/deferred`; ne pas merger dans `main`. |
| #92 | `V5 shadow/deferred`; ne pas merger dans `main`. |
| #87 | **Décision produit V4 séparée/non déployée** : GCC-only illiquid notification 30 %. Ne pas mélanger à un autre changement. |
| #54 | `STALE_OPEN/SUPERSEDED`. |
| #8 | **V5 expérimentale. OPEN / DRAFT / NON MERGED. Ne jamais merger dans `main` sans autorisation explicite utilisateur.** |

## Phases production récentes

- #156 : Global scale 50 listings/run ;
- #166 : Robot KB local PostgreSQL cutover ;
- #168 : Cardova public anonymous read-only ;
- #169 : Global cadence 20 min + timeout recovery ;
- #174 + #177 : Magi deterministic exact identity ;
- #178 : protection du budget recovery Magi, merge `545223613ce21e6c4cf886e07201bc3c105a5e69` ;
- #179 : watchdog/rattrapage Global, merge `ac5f7c734685422612a0f24690af22910eefa951` ;
- #180 : Robot KB multisource local, merge `9365f5cd9f8949580c4e48f00ba8c4e419c22145` ; installation physique Mac encore à vérifier.

## Règles

- `open` ne veut pas dire `à merger` ;
- vérifier patch + ancestry + supersession avant toute décision ;
- ne jamais rejouer les PRs historiques absorbées par #139 ;
- aucune fermeture housekeeping destructive sans autorisation utilisateur ;
- **PR #8 reste explicitement protégée** et non mergée.
