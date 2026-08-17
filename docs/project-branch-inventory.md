# Robot Pokémon / GCC Auction Watcher — inventaire exhaustif des branches

> Audit GitHub effectué le **17 août 2026** pour empêcher la perte de travail historique et les réimplémentations inutiles.
>
> Ce fichier complète `README.md` et `docs/project-capability-ledger.md`. Il inventorie **toutes les branches distantes visibles** au moment de l'audit, y compris les branches mergées, expérimentales, shadow, diagnostics, documentation et temporaires.

## Résultat de l'audit

- **145 branches distantes trouvées**.
- **145 noms uniques**.
- `main` vérifié au début de l'audit : `c8a495226f9e9800e5e1e2ac6a730ea21b1c3383`.
- historique des PR existantes parcouru jusqu'à **PR #123** ; le numéro `#1` n'est pas une pull request accessible dans ce dépôt.
- les PR ouvertes importantes ont été re-vérifiées individuellement : #8, #96, #106, #107, #108, #109, #110, #113, #114, #115, #122 et #123.
- aucune branche n'a été supprimée pendant cet audit.

## Règle d'utilisation

Avant de créer une nouvelle capacité :

1. chercher son nom et ses synonymes dans cet inventaire ;
2. suivre la branche vers le `project-capability-ledger.md` et la PR correspondante ;
3. inspecter le dernier successeur compatible avant de réécrire quoi que ce soit ;
4. ne jamais interpréter « absent de `main` » comme « jamais construit » ;
5. ne jamais supprimer une branche historique sans audit explicite de son ancestry, de ses PR, workflows et éventuels actifs uniques.

Les catégories ci-dessous décrivent la **famille de récupération**, pas nécessairement l'état de merge de chaque tip. Le statut fonctionnel autoritaire se trouve dans `docs/project-capability-ledger.md` et dans GitHub.

---

# 1. Production / V4 / architecture économique et discovery

| Branche | Famille / instruction de récupération |
|---|---|
| `adaptive_v4_market_refresh` | V4 adaptive provider refresh ; lineage PR #47. |
| `agent/v4-all-cert-problem-alerts` | Cert-alert expérimental ; lire #67→#69→#71→#73→#104 avant toute réutilisation. |
| `agent/v4-auction-item-discovery` | Discovery auction item-level ; lineage PR #9. |
| `agent/v4-canonical-multimarket-valuation` | TCGdex canonical + multimarket ; lineage PR #33. |
| `agent/v4-edge-hunter-safety-hotfix` | Edge Hunter fail-closed ; lineage PR #53. |
| `agent/v4-exact-active-ask-position` | eBay BIN ASK context ; lineage PR #78. |
| `agent/v4-external-confirmation-labels` | Sémantique des notifications externes ; lineage PR #56. |
| `agent/v4-final-alert-card-identity` | Fast Lane final identity lock ; lineage PR #55. |
| `agent/v4-final-auction-fast-lane` | Fast Lane zéro-sleep ; successeur du prototype PR #30, autorité PR #45. |
| `agent/v4-fix-stale-backlog-diagnostic` | Diagnostic backlog STALE ; lineage PR #27. |
| `agent/v4-fixed-queue-starvation-fix` | Protection budget fixed vs auctions ; lineage provider queue. |
| `agent/v4-image-grade-mismatch-fallback` | Ancienne évolution cert/image ; ne pas réactiver sans chaîne Mislisted complète. |
| `agent/v4-independent-external-market-valuation` | Précurseur arbitrage externe ; absorbé par canonical multimarket. |
| `agent/v4-kb-discovery-mirror` | Précurseur shadow Robot KB ; suivre la ligne P0/P1/P3/#49+. |
| `agent/v4-kb-discovery-mirror-v2` | Successeur de mirror initial ; suivre la ligne Robot KB durable. |
| `agent/v4-kb-filter-stdlib-hotfix` | Hotfix dépendance/filter Robot KB ; historique infrastructure. |
| `agent/v4-mislisted-slab-hunter` | Mislisted Slab initial ; production finale hard-disabled via #104. |
| `agent/v4-more-cert-verifiers` | Extension cert adapters ; precursor #64/#65. |
| `agent/v4-multimarket-audit-fixes` | Durcissements audit multimarket ; vérifier code actuel avant port. |
| `agent/v4-ocr-live-benchmark` | Benchmark OCR ; diagnostic seulement. |
| `agent/v4-ocr-live-benchmark-50` | Benchmark OCR 50 ; diagnostic seulement. |
| `agent/v4-private-auction-coverage` | Safety-net private auction ; lineage #50. |
| `agent/v4-private-auction-coverage-accounting` | Accounting isolé safety-net ; lineage #52. |
| `agent/v4-psa-apr-diagnostics-fix` | Diagnostic PSA APR / anti-bot ; lineage #46. |
| `agent/v4-psa-apr-web-hydration-resilience` | Hydration APR client-rendered ; lineage #32. |
| `agent/v4-psa-pca-ccc-ocr-hardening` | Cert-first + OCR ciblé ; lineage #65, production OCR ensuite disabled. |
| `agent/v4-robust-raw-consensus` | RAW consensus/price discovery validé ; tip `7541f504...`, mergé en production via `8a61a6a5...`. |
| `agent/v4-roi-efficiency-no-profit-score` | ROI/stale/momentum/KB readiness ; lineage #79. |
| `agent/v4-smart-external-priority` | Priorité provider fixed ; lineage #77. |
| `agent/v4-structural-edge-hunter-v2` | Structural Edge Hunter ; lineage #80. |
| `agent/v4-targeted-final-auction-check` | Prototype/fondation final-auction ; suivre #45/#55. |
| `agent/v4-unresolved-slab-manual-review` | Revue manuelle cert/OCR ; lineage #66. |
| `fix/v4-auction-pagination-drift-mislisted-off` | Autorité production #104 pour pagination stabilisée + Mislisted hard-disabled. |
| `fix/v4-cert-lookup-failure-log-only` | Cert lookup technique log-only ; lineage #73. |
| `fix/v4-cert-preserve-gradation-fallback` | Préservation cert API + Gradation fallback ; lineage #71. |
| `fix/v4-disable-mislisted-slab-notifications` | Hotfix safe-off cert/mislisted ; lire #69/#104. |
| `fix/v4-external-coverage-drain-fr-20260816` | External coverage drain + politique FR ; lineage #116. |
| `fix/v4-external-pending-backlog-drain` | `PENDING_BUDGET` scheduling/backlog ; provider queue lineage. |
| `fix/v4-gcc-only-30pct-notify` | Expérimentation seuil GCC-only ; vérifier PR #87/code actuel avant réutilisation. |
| `fix/v4-notification-signal-quality` | Notification quality guard ; lineage #84. |
| `hotfix/v4-stop-cert-missing-spam` | Safe-off faux `CERT_NUMBER_MISSING` ; lineage #69. |
| `ops/v4-external-dispatch-only` | Opérationnel/workflow provider ; ne pas recopier sans audit workflow actuel. |
| `ops/v4-playwright-cache` | Cache Playwright ; lineage PR #13. |
| `ops/v4-technical-alert-noise` | Réduction du bruit technique sans masquer perte discovery ; lineage PR #17. |
| `main` | **V4 production canonique**. |

---

# 2. TCGdex V4 — récupération actuelle

| Branche | Statut / récupération |
|---|---|
| `fix/v4-tcgdex-exact-coordinate-recovery-20260817` | PR #119 ; fast paths exacts bornés. |
| `fix/v4-tcgdex-generalized-coordinate-recovery-20260817` | PR #120 ; set/localId exact généralisé. |
| `fix/v4-tcgdex-observability-20260817` | Première observabilité ; superseded par finalizer #118. |
| `fix/v4-tcgdex-observability-finalizer-20260817` | PR #118 ; autorité observabilité TCGdex V4. |
| `fix/v4-tcgdex-run1054-aliases-20260817` | PR #121 ; aliases exacts run 1054, production. |
| `fix/v4-tcgdex-unique-coordinate-fallback-20260817` | PR #122 ; fallback coordonnée unique, validé mais non mergé. |
| `fix/v4-tcgdex-unique-coordinate-fallback-check-20260817` | Branche de vérification temporaire ; ne pas prendre comme autorité. |
| `fix/v4-recover-existing-capabilities-20260817` | **PR #123 actuelle** ; extension #122 + backport V5 #31 + docs anti-réimplémentation. |
| `docs/v4-tcgdex-run1054-handoff-20260817` | Handoff documentation de la phase #121. |

---

# 3. V5 expérimentale / identité / microvariantes

> Toute cette famille reste séparée de `main`. **PR #8 ne doit jamais être mergée sans autorisation explicite.**

| Branche | Capacité / instruction |
|---|---|
| `agent/v5-ambiguity-reconciliation` | PR #40 ; ambiguity + exact post-macro microvariant proof. |
| `agent/v5-catalog-gap-hardening` | PR #96 draft ; Pocket digital reject + curated physical catalog gaps. |
| `agent/v5-detailed-identity-observability` | Observabilité détaillée ; precursor de la version propre #81. |
| `agent/v5-detailed-identity-observability-ci` | CI/support de l'observabilité ; historique. |
| `agent/v5-detailed-identity-observability-pr` | Branch de PR/port observabilité ; historique. |
| `agent/v5-deterministic-catalog-uniqueness` | PR #31 ; two-of-three deterministic uniqueness. |
| `agent/v5-emergency-identity-fallback` | PR #86 ; PokeTrace identité emergency-only après panne TCGdex. |
| `agent/v5-exact-set-poketrace-budget` | Exact set bridge / réduction budget PokeTrace ; lineage #42. |
| `agent/v5-identity-coverage-expansion` | PR #39 ; reversed set code + multi-card rejection. |
| `agent/v5-identity-observability-clean` | PR #81 ; autorité observabilité détaillée actuelle. |
| `agent/v5-live-identity-finish-proof` | Diagnostic/applicabilité finish ; comparer #40/#41/#93. |
| `agent/v5-offline-ci` | PR #82 ; V5 Offline Validation. |
| `agent/v5-poketrace-cardmarket-market-data` | **V5 canonique expérimentale / PR #8**, head `bc641dfe...`. |
| `agent/v5-poketrace-cardmarket-market-data-check` | Branche de vérification ; pas autorité. |
| `agent/v5-poketrace-cardmarket-market-data-temp2` | Temporaire ; pas autorité. |
| `agent/v5-poketrace-market-only` | PR #85 ; PokeTrace market-only en régime normal. |
| `agent/v5-post-macro-applicability-retry` | Exact applicability retry ; incorporé/durci ensuite par #93. |
| `agent/v5-ppt-identity-shadow` | PR #92 ; PPT identity shadow/helper. |
| `agent/v5-premium-variant-fix` | PR #36 ; provider metadata non-probante pour premium variant. |
| `agent/v5-robot-kb-identity-cache` | PR #88 ; cache TCGdex prouvé Robot KB/Neon en outage. |
| `agent/v5-title-finish-parser` | PR #44 ; parser déterministe finish title. |
| `diag/v5-neon-cache-probe-20260816` | Probe live cache Neon après #88 ; diagnostic, pas nouvelle architecture. |
| `diag/v5-tcgdex-blockers-20260816` | Diagnostic finish blockers ; contient le chemin menant au post-macro retry/#93. |
| `ops/v5-live-dispatch-once-20260816` | Branche one-shot opérationnelle ; ne pas traiter comme code autoritaire. |
| `ops/v5-live-dispatch-once-20260816-2` | Deuxième one-shot opérationnel ; ne pas traiter comme code autoritaire. |
| `docs/latest-v5-canonical-handoff` | Handoff V5. |
| `docs/update-readme-v4-auction-v5-status` | Handoff V4/V5 historique. |
| `docs/v5-observability-handoff-20260815` | Handoff observabilité. |
| `docs/v5-outage-cache-handoff-20260816` | Handoff #88/cache outage. |
| `docs/v5-pr93-catalog-gap-handoff-20260816` | Handoff autour de #93/#96. |
| `docs/v5-variant-tcgdex-justtcg-handoff` | Handoff variant/provider benchmark historique. |

---

# 4. Première génération catalogue GCC / transition vers TCGdex

| Branche | Capacité / succession |
|---|---|
| `chatgpt-v4-v5-live-fix-20260810` | PR #2 : grading structuré GCC, graders SFG/SGS/SCA/TCC, V5 representative matching. |
| `chatgpt-gcc-catalog-resolver-20260810` | PR #3 : catalogue GCC public Explore/Completed Sales fallback d'identité. |
| `chatgpt-gcc-search-fix-20260810` | PR #4 : sélection correcte de la recherche locale Explore. |
| `chatgpt-gcc-cumulative-index-20260810` | PR #5 : index cumulatif GCC + provenance de conflits. |
| `chatgpt-v5-oauth-cache-fix-20260810` | PR #6 : persistance cache/catalogue même après diagnostic échoué. |
| `chatgpt-tcgdex-identity-and-v4-arbitrage-guard-20260810` | PR #7 : origine TCGdex-first multilingue V5 + garde V4 external grade arbitration. |
| `chatgpt-gcc-conflict-diagnostics-20260810` | Diagnostic historique des conflits catalogue GCC ; superseded par architecture déterministe ultérieure. |

Ces branches sont importantes pour comprendre les root causes, mais la politique d'identité actuelle doit partir de TCGdex/V5 courant et des successeurs documentés, pas de l'ancien index GCC comme autorité primaire.

---

# 5. Robot KB / Neon / historique durable

| Branche | Capacité / succession |
|---|---|
| `agent/p0-card-knowledge-base-foundation` | Fondation immutable KB ; tip `946f4b75...`. |
| `agent/p1-shadow-observation-sidecar` | Sidecar passif d'observations + single-card fail-closed ; tip `b340d61f...`. |
| `agent/p3-postgres-durable-shadow` | Ligne PostgreSQL/Neon durable ; tip `1d06fe33...` inclut merge PR #59 SOLD explicite. |
| `agent/kb-deploy-gcc-sold` | Déploiement collector GCC SOLD. |
| `agent/kb-fixed-backup-rotation-v2` | Rotation fixed backup ; historique vers hybrid coverage. |
| `agent/kb-fixed-hybrid-100-200-100` | PR #75 ; recent + rotation + ciblage. |
| `agent/kb-gcc-sold-collector` | Collector SOLD explicite ; lineage #59/#60. |
| `agent/kb-sold-30m-split` | PR #72 ; SOLD 30 min séparé. |
| `agent/kb-sold-harvester-fixed-rotation` | Ligne fixed/SOLD ; suivre #62 et successeurs. |
| `agent/kb-sold-historical-backfill` | PR #76 ; backfill SOLD historique. |
| `agent/kb-sold-lossless-watermark` | Première version watermark. |
| `agent/kb-sold-lossless-watermark-v2` | PR #68 ; autorité lossless watermark. |
| `agent/kb-tcgdex-macro-cache` | PostgreSQL/immutable TCGdex macro identity cache + reversion history ; tip `f89aa901...`, precursor direct de #88. |
| `diag/kb-fixed-filter-contract-20260815` | Diagnostic contrat fixed/single-card ; ne pas utiliser comme pipeline alternatif. |

---

# 6. Source Scout / providers / benchmarks

| Branche | Capacité / instruction |
|---|---|
| `agent/source-scout-benchmark-20260814` | Base benchmark providers ; head `46f5cc3e...`. |
| `agent/source-scout-ppt-cardinality-20260815` | Benchmark PPT complet/cardinality ; tip `b6518055...`. |
| `agent/source-scout-tcgapi-identity-20260815` | Benchmark tcgapi.dev bounded ; tip `15ec52e7...`, conclusion enregistrée 3/18 macro exact, langue non prouvée. |

Ces branches contiennent les probes/policies à réutiliser pour PPT, Cardmarket/RapidAPI, eBay ASP et demandes Marketplace Insights. Elles sont `BENCHMARK/DEFERRED`, pas production.

---

# 7. PokemonPriceTracker hors Source Scout

| Branche | Capacité / succession |
|---|---|
| `agent/v4-ppt-shadow-market-20260815` | Ancienne ligne PPT V4 ; superseded par clean #106. |
| `agent/v4-ppt-shadow-market-20260815-check` | Vérification/temp de l'ancienne ligne. |
| `agent/v4-ppt-shadow-market-20260815-temp` | Temporaire. |
| `agent/v4-ppt-clean-20260816` | PR #106 draft ; clean V4 PPT shadow sur main plus récent. |
| `agent/japan-edge-ppt-jp-shadow-20260816` | Ancienne Japan PPT shadow ; superseded. |
| `agent/japan-edge-ppt-exact-set-20260816` | Raffinement exact set ; historique de la chaîne. |
| `agent/japan-edge-ppt-clean-20260816` | PR #107 draft ; affichage PPT séparé, display-only. |

---

# 8. Japan Edge

| Branche | Capacité / instruction |
|---|---|
| `feat/japan-edge-hunter-shadow` | Fondation Japan Edge ; PR #89 lineage. |
| `feat/japan-edge-global-market-context` | Contexte global exact SOLD ; PR #94. |
| `fix/japan-edge-notification-layout` | Présentation comparative ; PR #101. |
| `docs/japan-edge-global-handoff-20260816` | Handoff global market. |
| `docs/japan-edge-global-handoff-20260816-v2` | Handoff révisé. |
| `docs/japan-edge-notification-layout-handoff` | Handoff présentation. |
| `docs/fix-japan-edge-median-typo` | Docs/hotfix typo, pas logique économique. |
| `ops/japan-edge-run-20260816-0141` | Branche opérationnelle de run ; pas autorité de code. |

---

# 9. Global multi-vault shadow

| Branche | Capacité / succession |
|---|---|
| `feat/v4-global-multivault-edge-foundation` | PR #108 ; common fair-value/identity adapters. |
| `feat/v4-global-live-shadow` | PR #109 ; live shadow read-only multi-vault. |
| `feat/v4-global-rejection-diagnostics` | PR #110 ; raisons de rejet exact-match. |
| `feat/v4-global-retrieval-hardening` | PR #113 ; hardening magi/Fanatics/COMC. |
| `fix/v4-global-magi-sold-filter` | PR #114 ; rejette pages Magi explicitement SOLD de la lane ASK. |
| `fix/v4-global-comc-groudon-resolution` | PR #115 ; exact COMC set facet retrieval pour Raging Surf/Groudon. |
| `chore/expose-global-shadow-dispatch` | Workflow/manual dispatcher global shadow ; support. |
| `chore/expose-global-shadow-dispatch-pr` | Branche support de PR du dispatcher. |

**Toujours reprendre la stack complète #108→#109→#110→#113→#114→#115**, pas une branche intermédiaire isolée, puis rebaser proprement sur le `main` courant avant une future décision d'intégration.

---

# 10. Diagnostics, documentation, gouvernance et opérations

| Branche | Type / instruction |
|---|---|
| `chore/antigravity-project-governance` | Historique gouvernance ; règles actuelles dans `.agents/rules/gcc-project-governance.md`. |
| `diag/cert-number-coverage-100-20260815` | Diagnostic cert coverage 100 ; ne pas confondre avec TCGdex 100/100. |
| `diag/v4-gcc-gradation-cert-100` | Diagnostic API/Gradation cert 100/100 ; pas benchmark identité TCGdex. |
| `docs/canonical-project-handoff` | Handoff historique. |
| `docs/handoff-current-status` | Handoff historique. |
| `docs/repo-hygiene-readme-20260816` | Repo hygiene / branches/PRs historiques ; ne pas supprimer sans ancestry audit. |
| `ops/workflow-cleanup-20260811` | Nettoyage workflows temporaires/redondants. |

---

# 11. Branches temporaires / no-op connues

Ces branches ne doivent **pas** devenir des sources d'architecture. Elles sont conservées dans l'inventaire pour qu'un futur agent sache qu'elles existent.

| Branche | Classification |
|---|---|
| `oops-no-more` | temporaire/no-op accidentel |
| `tmp-do-not-use-3` | temporaire/no-op |
| `tmp-do-not-use-unique-coordinate-readme` | temporaire/no-op |
| `tmp-ignore` | temporaire/no-op |
| `tmp-ignore2` | temporaire/no-op |
| `tmp-noop-check` | temporaire/no-op |

Aucune suppression n'est effectuée automatiquement. Un nettoyage futur exige une autorisation explicite et un contrôle d'ancestry/workflow/PR avant suppression.

---

# 12. Contrôle de complétude — liste brute 145/145

La liste suivante est volontairement redondante avec les catégories ci-dessus : elle permet un contrôle mécanique qu'aucun nom de branche n'a été oublié.

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

## 13. Résultat pratique

À partir de cet audit, un futur agent ne doit plus demander « est-ce qu'on a déjà fait ça ? » en regardant uniquement `main`. La séquence correcte est :

```text
README
-> project-capability-ledger.md
-> project-branch-inventory.md
-> PR/branch autoritaire
-> code/tests/runs réels
-> seulement ensuite : nouvelle implémentation si nécessaire
```

Cette règle est particulièrement importante pour V5, Robot KB, Source Scout, PPT et la stack Global Multi-Vault, où une quantité significative de travail validé vit volontairement hors production `main`.
