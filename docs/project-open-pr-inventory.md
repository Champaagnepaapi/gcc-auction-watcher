# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot GitHub re-vérifié le **25 août 2026** après merge de la PR #174.

```text
main runtime                  3d1589e0086c264e9f910a15fb6b037e20938970
main docs closeout            68d68ece5d9bb5d971d88748b2d852edfb3bbf5a
open pull requests            19
PR #174                       MERGED / CLOSED
PR #8                         OPEN / DRAFT / NON MERGED
```

Le contrôle GitHub live reste l'autorité. Une PR ouverte n'est jamais automatiquement autorisée au merge.

## PR ouvertes pertinentes

| PR | Classification / instruction |
|---|---|
| #176 | `STALE_OPEN / DOCS`. Closeout eBay #175 préparé avant merge #174 ; son handoff dit encore que #174 est ouverte. Ne pas merger tel quel sans refresh/revalidation. |
| #159 | `PENDING_V4_TCGDEX`. Battle Partners exact set alias ; ligne séparée de #174. Revalider contre `main` courant avant décision. |
| #141 | `SUPERSEDED_DIAGNOSTIC` par #142/#140. |
| #138 | `SUPERSEDED_BY_139`. |
| #126 | **SUPERSEDED** par #127→#135. Ne pas merger. |
| #115 | `SUPERSEDED_BY_139` / child historique du stack Global. |
| #114 | `SUPERSEDED_BY_139` / child historique du stack Global. |
| #113 | `SUPERSEDED_BY_139` / child historique du stack Global. |
| #110 | `SUPERSEDED_BY_139` / diagnostic historique. |
| #111 | `STALE_OPEN/SUPERSEDED` docs. |
| #109 | `SUPERSEDED_BY_139` / stack Global historique. |
| #108 | `SUPERSEDED_BY_139` / fondation Global historique. |
| #107 | Japan Edge PPT display-only historique ; ne pas merger automatiquement. |
| #106 | ancien V4 PPT shadow ; ne pas merger automatiquement. |
| #96 | `V5 child/deferred`; ne pas merger dans `main`. |
| #92 | `V5 shadow/deferred`; ne pas merger dans `main`. |
| #87 | décision produit V4 séparée : GCC-only illiquid notification 30 %. Ne pas mélanger à un autre changement. |
| #54 | `STALE_OPEN/SUPERSEDED`. |
| #8 | **V5 expérimentale. OPEN / DRAFT / NON MERGED. Ne jamais merger dans `main` sans autorisation explicite utilisateur.** |

## Phase récente mergée

### #174 — Magi exact identity coverage

```text
feature head                     593c417ec526aba39f7d388bb3a61d868650c15a
merge main                       3d1589e0086c264e9f910a15fb6b037e20938970
first production schedule        32893130902 SUCCESS
Magi                              31/96 EXACT
TCGdex recovery                  36/36 max
notifications sent               0
transactions                     false
```

#174 n'est plus une PR pending. Les cinq `japanese_set_name_unproven` restantes demeurent bloquées tant qu'une preuve déterministe suffisante n'existe pas.

## Autres phases production récentes

- #156 : Global scale 50 listings/run ;
- #166 : Robot KB local PostgreSQL cutover ;
- #168 : Cardova public anonymous read-only ;
- #169 : Global cadence 20 min + timeout recovery ;
- #173 : Magi native identity foundation ;
- #175 : eBay Playwright hard-hang isolation ;
- #174 : Magi deterministic coverage extension, désormais production.

## Règles

- `open` ne veut pas dire `à merger` ;
- vérifier patch + ancestry + supersession avant toute décision ;
- ne jamais rejouer les PRs historiques absorbées par #139 ;
- ne pas mélanger #159 avec #174 ;
- ne jamais merger #8 sans autorisation explicite ;
- aucune fermeture housekeeping destructive sans autorisation utilisateur.
