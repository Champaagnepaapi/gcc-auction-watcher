# Robot Pokémon / GCC Auction Watcher — inventaire des branches

État pertinent vérifié le **20 août 2026** après merge #140.

## Autorités

```text
production canonique  main = c012284c423e9526fd2712001fdbce3a5cfafda3
V5 expérimentale      agent/v5-poketrace-cardmarket-market-data / PR #8
phase docs courante   docs/v4-global-economic-confirmation-close-20260820
```

PR #8 reste expérimentale/draft/non mergée ; ne jamais la merger dans `main` sans autorisation explicite.

## Fraîcheur du comptage

Le dernier **audit exhaustif** des branches, le 18 août 2026, comptait 158 branches distantes. Depuis, plusieurs branches Global/diagnostic/docs ont été créées. Cette phase de fermeture n'a **pas** refait un décompte exhaustif 1:1 de toutes les branches distantes ; ne pas continuer à présenter `158` comme nombre courant.

Toute action destructive de suppression de branche exige un nouvel audit exhaustif + autorisation explicite.

## Branches de la phase Global récente

Branches fonctionnelles/provenance vérifiées :

- `shadow/v4-global-current-main-reintegration-20260819` — PR #138, superseded par #139 ;
- `feat/v4-global-multivault-reintegration-20260819` — réintégration #139 vers main ;
- `feat/v4-global-economic-confirmation-20260819` — PR #140, mergée vers main ;
- `diag/v4-global-provider-coverage-20260820` — PR #141, diagnostic superseded par #142 ;
- `diag/v4-global-provider-coverage-20260820-check` — diagnostic intermédiaire ;
- `diag/v4-global-provider-coverage-20260820-final` — diagnostic intermédiaire ;
- `diag/v4-global-provider-coverage-20260820-impl` — diagnostic/impl intermédiaire ;
- `diag/v4-global-provider-coverage-20260820-run` — run helper historique ;
- `diag/v4-global-provider-coverage-20260820-work` — travail intermédiaire ;
- `fix/v4-global-external-exact-bridge-20260820` — PR #142, mergée dans #140 ;
- `docs/v4-global-economic-confirmation-close-20260820` — fermeture documentaire courante.

Ces branches historiques ne deviennent pas des branches de production. `main` reste l'unique autorité V4 production.

## Branches historiques à ne pas rejouer

- anciennes branches Global #108→#115 : capacités absorbées par #139 ;
- `fix/v4-poketrace-exact-provider-bridges-20260818` / PR #126 : superseded par #127→#135 ;
- branches one-shot/temp/diagnostic : mémoire de validation, pas code à réintroduire automatiquement.

## Règle de gouvernance

Avant toute suppression/cleanup de branches :

1. refaire l'inventaire distant exhaustif ;
2. vérifier PR associée et supersession ;
3. vérifier que le SHA utile est atteignable depuis main ou une branche conservée ;
4. vérifier les workflows qui peuvent référencer la branche ;
5. obtenir l'autorisation explicite utilisateur ;
6. ne jamais supprimer la branche V5 #8 ou une branche active par simple housekeeping.

Aucune branche n'a été supprimée pendant la phase #139→#142.
