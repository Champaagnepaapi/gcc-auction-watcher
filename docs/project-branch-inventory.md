# Robot Pokémon / GCC Auction Watcher — inventaire exhaustif des branches

> Snapshot GitHub destiné à empêcher la perte de travail historique et les réimplémentations inutiles. GitHub live reste autoritaire.

Snapshot vérifié : **18 août 2026, PR #129 ouverte**.

## Résultat

- **151/151 branches distantes** trouvées.
- **151 noms uniques**.
- `main` production : `4737604a1685f344ced65ede1ed49b4a1b9b7f6d`.
- branche active : `fix/v4-poketrace-ja-search-regression-20260818`.
- aucune branche supprimée pendant cette phase.

## Familles de récupération prioritaires

- V4 production/historique : `agent/v4-*`, `fix/v4-*`, `adaptive_v4_market_refresh`, `ops/v4-*`.
- TCGdex/PokeTrace V4 : #119→#125 puis #127/#128; #129 corrige la régression JA de retrieval sans relâcher les gates.
- V5 : `agent/v5-*`, diagnostics/ops V5 et PR #8. V5 reste expérimentale; ne jamais merger #8 sans autorisation explicite.
- Robot KB / Neon : `agent/p0-*`, `agent/p1-*`, `agent/p3-*`, `agent/kb-*`.
- Global Multi-Vault : `feat/v4-global-*` + `fix/v4-global-*`; stack #108→#109→#110→#113→#114→#115.
- Source Scout / Japan Edge / cert-OCR / diagnostics : conserver comme preuves historiques jusqu'à audit explicite.

## Phase courante

`fix/v4-poketrace-ja-search-regression-20260818` / PR #129 sépare à nouveau :
- retrieval PokeTrace JA = nom canonique/romanisé + collector number imprimé + `game=pokemon-japanese`;
- nom TCGdex localisé = alias d'acceptation uniquement, lié au même `card_id + set_id + localId` exact.

Aucun fuzzy, aucune traduction comme preuve, aucun achat/bid/checkout/paiement.

---

# Contrôle de complétude — liste brute 151/151

```text
adaptive_v4_market_refresh
agent/japan-edge-ppt-clean-20260816
agent/japan-edge-ppt-exact-set-20260816
agent/japan-edge-ppt-jp-shadow-20260816
agent/kb-deploy-gcc-sold
agent/kb-fixed-backup-rotation-v2
agent/kb-fixed-hybrid-100-200-100
agent/kb-gcc-sold-collector
agent/kb-sold-30m-split
agent/kb-sold-harvester-fixed-rotation
agent/kb-sold-historical-backfill
agent/kb-sold-lossless-watermark
agent/kb-sold-lossless-watermark-v2
agent/kb-tcgdex-macro-cache
agent/p0-card-knowledge-base-foundation
agent/p1-shadow-observation-sidecar
agent/p3-postgres-durable-shadow
agent/source-scout-benchmark-20260814
agent/source-scout-ppt-cardinality-20260815
agent/source-scout-tcgapi-identity-20260815
agent/v4-all-cert-problem-alerts
agent/v4-auction-item-discovery
agent/v4-canonical-multimarket-valuation
agent/v4-edge-hunter-safety-hotfix
agent/v4-exact-active-ask-position
agent/v4-external-confirmation-labels
agent/v4-final-alert-card-identity
agent/v4-final-auction-fast-lane
agent/v4-fix-stale-backlog-diagnostic
agent/v4-fixed-queue-starvation-fix
agent/v4-image-grade-mismatch-fallback
agent/v4-independent-external-market-valuation
agent/v4-kb-discovery-mirror
agent/v4-kb-discovery-mirror-v2
agent/v4-kb-filter-stdlib-hotfix
agent/v4-mislisted-slab-hunter
agent/v4-more-cert-verifiers
agent/v4-multimarket-audit-fixes
agent/v4-ocr-live-benchmark
agent/v4-ocr-live-benchmark-50
agent/v4-ppt-clean-20260816
agent/v4-ppt-shadow-market-20260815-check
agent/v4-ppt-shadow-market-20260815-temp
agent/v4-ppt-shadow-market-20260815
agent/v4-private-auction-coverage
agent/v4-private-auction-coverage-accounting
agent/v4-psa-apr-diagnostics-fix
agent/v4-psa-apr-web-hydration-resilience
agent/v4-psa-pca-ccc-ocr-hardening
agent/v4-robust-raw-consensus
agent/v4-roi-efficiency-no-profit-score
agent/v4-smart-external-priority
agent/v4-structural-edge-hunter-v2
agent/v4-targeted-final-auction-check
agent/v4-unresolved-slab-manual-review
agent/v5-ambiguity-reconciliation
agent/v5-catalog-gap-hardening
agent/v5-detailed-identity-observability
agent/v5-detailed-identity-observability-ci
agent/v5-detailed-identity-observability-pr
agent/v5-deterministic-catalog-uniqueness
agent/v5-emergency-identity-fallback
agent/v5-exact-set-poketrace-budget
agent/v5-identity-coverage-expansion
agent/v5-identity-observability-clean
agent/v5-live-identity-finish-proof
agent/v5-offline-ci
agent/v5-poketrace-cardmarket-market-data
agent/v5-poketrace-cardmarket-market-data-check
agent/v5-poketrace-cardmarket-market-data-temp2
agent/v5-poketrace-market-only
agent/v5-post-macro-applicability-retry
agent/v5-ppt-identity-shadow
agent/v5-premium-variant-fix
agent/v5-robot-kb-identity-cache
agent/v5-title-finish-parser
chatgpt-gcc-catalog-resolver-20260810
chatgpt-gcc-conflict-diagnostics-20260810
chatgpt-gcc-cumulative-index-20260810
chatgpt-gcc-search-fix-20260810
chatgpt-tcgdex-identity-and-v4-arbitrage-guard-20260810
chatgpt-v4-v5-live-fix-20260810
chatgpt-v5-oauth-cache-fix-20260810
chore/antigravity-project-governance
chore/expose-global-shadow-dispatch
chore/expose-global-shadow-dispatch-pr
diag/cert-number-coverage-100-20260815
diag/kb-fixed-filter-contract-20260815
diag/v4-gcc-gradation-cert-100
diag/v4-provider-rejection-observability-20260818
diag/v5-neon-cache-probe-20260816
diag/v5-tcgdex-blockers-20260816
docs/canonical-project-handoff
docs/fix-japan-edge-median-typo
docs/handoff-current-status
docs/japan-edge-global-handoff-20260816-v2
docs/japan-edge-global-handoff-20260816
docs/japan-edge-notification-layout-handoff
docs/latest-v5-canonical-handoff
docs/repo-hygiene-readme-20260816
docs/update-readme-v4-auction-v5-status
docs/v4-tcgdex-run1054-handoff-20260817
docs/v5-observability-handoff-20260815
docs/v5-outage-cache-handoff-20260816
docs/v5-pr93-catalog-gap-handoff-20260816
docs/v5-variant-tcgdex-justtcg-handoff
feat/japan-edge-global-market-context
feat/japan-edge-hunter-shadow
feat/v4-global-live-shadow
feat/v4-global-multivault-edge-foundation
feat/v4-global-rejection-diagnostics
feat/v4-global-retrieval-hardening
fix/japan-edge-notification-layout
fix/v4-auction-pagination-drift-mislisted-off
fix/v4-cert-lookup-failure-log-only
fix/v4-cert-preserve-gradation-fallback
fix/v4-disable-mislisted-slab-notifications
fix/v4-external-coverage-drain-fr-20260816
fix/v4-external-pending-backlog-drain
fix/v4-gcc-only-30pct-notify
fix/v4-global-comc-groudon-resolution
fix/v4-global-magi-sold-filter
fix/v4-notification-signal-quality
fix/v4-poketrace-deterministic-market-retrieval-20260817
fix/v4-poketrace-exact-provider-bridges-20260818
fix/v4-poketrace-ja-search-regression-20260818
fix/v4-poketrace-preserve-provider-number-20260818
fix/v4-poketrace-provider-bridges-after-127-20260818
fix/v4-recover-existing-capabilities-20260817
fix/v4-tcgdex-exact-coordinate-recovery-20260817
fix/v4-tcgdex-generalized-coordinate-recovery-20260817
fix/v4-tcgdex-observability-20260817
fix/v4-tcgdex-observability-finalizer-20260817
fix/v4-tcgdex-run1054-aliases-20260817
fix/v4-tcgdex-unique-coordinate-fallback-20260817
fix/v4-tcgdex-unique-coordinate-fallback-check-20260817
hotfix/v4-stop-cert-missing-spam
main
oops-no-more
ops/japan-edge-run-20260816-0141
ops/v4-external-dispatch-only
ops/v4-playwright-cache
ops/v4-technical-alert-noise
ops/v5-live-dispatch-once-20260816-2
ops/v5-live-dispatch-once-20260816
ops/workflow-cleanup-20260811
tmp-do-not-use-3
tmp-do-not-use-unique-coordinate-readme
tmp-ignore
tmp-ignore2
tmp-noop-check
```

## Fraîcheur

Mettre à jour ce fichier quand une branche est créée/supprimée ou lorsqu'une lignée change d'autorité. Ne jamais supprimer une branche uniquement parce qu'elle paraît ancienne.