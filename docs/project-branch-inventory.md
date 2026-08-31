# Robot Pokémon / GCC Auction Watcher — inventaire des branches

État pertinent re-vérifié le **31 août 2026**. Le contrôle GitHub live reste l'autorité ; cet inventaire sert surtout à préserver les branches fonctionnelles et leurs supersessions.

## Autorités / branches actives pertinentes

```text
production canonique              main @ b98756c449718845fc1944560fcf61c02586079f
Cardova paid SOLD                 diag/robot-kb-cardova-paid-history-probe-20260829 / PR #199 OPEN DRAFT
Cardova identity proof            diag/cardova-public-title-printing-proof-20260830 / PR #204 OPEN DRAFT
Cardova exact SOLD dry-run        diag/cardova-exact-sale-dry-run-20260831 / PR #205 OPEN DRAFT
Cardova canonical persistence     diag/cardova-canonical-sale-persistence-dry-run-20260831 / PR #206 OPEN DRAFT
V5 expérimentale                  agent/v5-poketrace-cardmarket-market-data / PR #8
```

Toujours re-vérifier le HEAD GitHub live avant une action.

PR #8 reste expérimentale/draft/non mergée, head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f` ; ne jamais la merger dans `main` sans autorisation explicite.

## Comptage

Le dernier audit exhaustif ancien comptait 158 branches distantes. De nombreuses branches ont été créées depuis ; **ne pas présenter `158` comme nombre actuel** sans nouvel audit exhaustif.

Toute suppression de branche exige un audit + autorisation explicite.

## Stack Cardova courant

```text
diag/robot-kb-cardova-paid-history-probe-20260829
  #199 / base main
  -> diag/cardova-public-title-printing-proof-20260830
       #204 / stacked on #199
       -> diag/cardova-exact-sale-dry-run-20260831
            #205 / stacked on #204
            -> diag/cardova-canonical-sale-persistence-dry-run-20260831
                 #206 / stacked on #205
```

- #199 : provider paid/completed SOLD + P3 unresolved persistence + collector local ;
- #204 : preuves printing/microvariant bornées, baseline 37/38 exact ;
- #205 : compose exact identity -> même contrat SOLD P3, memory-only ; live 31 août = 38 exact SOLD candidates / 0 sale blocker / 5 identity blockers ;
- #206 : canonical-card + exact-sale persistence dry-run strictement `:memory:` ; le schéma P3 printing non représentable reste fail-closed.

Les quatre branches restent actives et **ne doivent pas être mergées indépendamment**. Aucun merge n'est autorisé par la phase courante.

## Branches Global / V4 structurantes conservées

- `shadow/v4-global-current-main-reintegration-20260819` — PR #138, superseded par #139 ;
- `feat/v4-global-multivault-reintegration-20260819` — #139 ;
- `feat/v4-global-economic-confirmation-20260819` — #140, mergée ;
- `diag/v4-global-provider-coverage-20260820` — #141, diagnostic superseded ;
- branches `diag/v4-global-provider-coverage-20260820-*` — diagnostics/provenance ;
- `fix/v4-global-external-exact-bridge-20260820` — #142, absorbée dans #140 ;
- `feat/v4-global-notification-activation-20260820` — #145 mergée ;
- `ops/v4-global-notify-activate-20260820` — #146 mergée ;
- `feat/v4-global-marketplace-discovery-20260820` — #147 mergée ;
- `ops/v4-global-marketplace-cutover-20260820` — #148 mergée ;
- `docs/v4-global-marketplace-cutover-close-20260820` — #149 docs mergée ;
- `ops/v4-global-run-registry-20260820` — #151 mergée ;
- `ops/v4-global-10min-cadence-20260820` — #153 mergée ;
- `feat/v4-tcgdex-detailed-variants-20260820` — #154 mergée ;
- `docs/v4-tcgdex-detailed-variants-close-20260821` — docs #155 ;
- `feat/v4-global-scale-15-20260821` — historique de scale ;
- `feat/robot-kb-local-postgres-mac-20260821` — provenance du cutover Robot KB local, désormais livré par #166.

`main` reste l'autorité après merge explicite. Les branches fonctionnelles mergées sont conservées comme provenance ; aucune suppression n'est autorisée implicitement.

## Provenance importante conservée

Les branches suivantes restent utiles à l'audit historique, même lorsqu'elles sont superseded :

- `fix/v4-recover-existing-capabilities-20260817` ;
- `fix/v4-poketrace-deterministic-market-retrieval-20260817` ;
- `fix/v4-poketrace-exact-provider-bridges-20260818` ;
- `fix/v4-poketrace-preserve-provider-number-20260818` ;
- `fix/v4-poketrace-provider-bridges-after-127-20260818` ;
- `fix/v4-poketrace-ja-search-regression-20260818` ;
- `diag/v4-provider-rejection-observability-20260818` ;
- `agent/p0-card-knowledge-base-foundation` ;
- `agent/source-scout-benchmark-20260814` ;
- `feat/v4-global-multivault-edge-foundation` ;
- `tmp-noop-check` ;
- `oops-no-more` ;
- `main`.

## Historique à ne pas rejouer

- anciennes branches Global #108→#115 : absorbées par #139 ;
- PR #126 : superseded par #127→#135 ;
- ancien moteur Global seed-rotation : historique/benchmark après #148 ;
- one-shots/temp/diagnostics : provenance uniquement.

## Règle cleanup branches

1. inventaire distant exhaustif ;
2. PR/supersession ;
3. atteignabilité du SHA utile ;
4. références workflow ;
5. autorisation explicite ;
6. jamais de suppression V5/branche active par simple housekeeping.

Aucune branche n'a été supprimée pendant cette phase.
