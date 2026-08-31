# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot GitHub pertinent re-vérifié le **31 août 2026**. Le contrôle GitHub live reste l'autorité et il ne faut pas utiliser le nombre de lignes comme compteur exhaustif GitHub.

```text
main runtime                   b98756c449718845fc1944560fcf61c02586079f
PR #199                        OPEN / DRAFT / NON MERGED
PR #204                        OPEN / DRAFT / NON MERGED / stacked on #199
PR #205                        OPEN / DRAFT / NON MERGED / stacked on #204
PR #206                        OPEN / DRAFT / NON MERGED / stacked on #205
PR #8                          OPEN / DRAFT / NON MERGED
```

## PR ouvertes **pertinentes pour la gouvernance courante**

| PR | Classification / instruction |
|---|---|
| #206 | `ROBOT_KB / MEMORY_ONLY / STACKED_ON_205`. Canonical-card + exact-sale persistence dry-run. Le schéma P3 printing non représentable reste fail-closed. Ne pas merger indépendamment. |
| #205 | `ROBOT_KB / MEMORY_ONLY / STACKED_ON_204`. Exact-card Cardova SOLD candidate dry-run. Live 31 août : 38 exact SOLD candidates, 0 sale blocker, 5 identity blockers. Ne pas merger indépendamment. |
| #204 | `ROBOT_KB / BOUNDED_READ_ONLY / STACKED_ON_199`. Cardova printing/microvariant proof. Baseline 37/38 exact. Ne pas merger indépendamment. |
| #199 | `ROBOT_KB / DRAFT`. Cardova paid/completed SOLD collector + P3 persistence unresolved identity. Local collector actif. Aucun merge sans décision explicite. |
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

## Stack Cardova courant

```text
#199 diag/robot-kb-cardova-paid-history-probe-20260829
  -> #204 diag/cardova-public-title-printing-proof-20260830
      -> #205 diag/cardova-exact-sale-dry-run-20260831
          -> #206 diag/cardova-canonical-sale-persistence-dry-run-20260831
```

Ne pas merger un child indépendamment du parent. Aucune de ces PR n'est autorisée au merge par la phase actuelle.

## Phases production récentes

- #156 : Global scale 50 listings/run ;
- #166 : Robot KB local PostgreSQL cutover ;
- #168 : Cardova public anonymous read-only ;
- #169 : Global cadence 20 min + timeout recovery ;
- #174 + #177 : Magi deterministic exact identity ;
- #178 : protection du budget recovery Magi ;
- #179 : watchdog/rattrapage Global ;
- #180 : Robot KB multisource local ;
- #188 : priorité/cap enchères V4 ;
- #189 : breakers PSA/eBay ;
- #191 : eBay completed shadow ;
- #201 : auction safety-net ledger ;
- #203 : weekly stability budget.

## Règles

- `open` ne veut pas dire `à merger` ;
- vérifier patch + ancestry + supersession avant toute décision ;
- ne jamais rejouer les PRs historiques absorbées par #139 ;
- aucune fermeture housekeeping destructive sans autorisation utilisateur ;
- **PR #8 reste explicitement protégée** et non mergée.
