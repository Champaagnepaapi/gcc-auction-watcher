# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot pertinent re-vérifié le **6 septembre 2026**. Le contrôle GitHub live reste l'autorité ; ne pas utiliser ce document comme compteur exhaustif sans nouveau search live.

> V4 production : `main@dfc548021c561479cc8758e2949d2c4629388d9d`. PR #255 est MERGED. PR #257 est OPEN/DRAFT/NON-MERGED et porte la phase active de séparation des rôles/PriceCharting. PR #256 reste Japan Edge séparée. PR #8 reste protégée.

## PR ouvertes pertinentes pour la gouvernance courante

| PR | Classification / instruction |
|---|---|
| #257 | `V4_SOURCE_ROLE_PRICECHARTING / OPEN_DRAFT / DO_NOT_MERGE_WITHOUT_AUTH`. Un orchestrateur, adapters opportunity indépendants, GCC history sans autorité économique, PriceCharting guide systématique PSA 8/9/10 compatibles, seuil normal V4 30 %, aucune transaction. Validation en cours. |
| #256 | `JAPAN_EDGE_EXTERNAL_FIRST / OPEN_DRAFT / SEPARATE`. Mercari + SNKRDUNK opportunity adapters. Reste séparée de #257 ; revalider sa base après évolution de #257/#255 avant toute décision. |
| #246 | `DOCS_ONLY / OPEN_DRAFT`. Ancien closeout #245/#247 ; revalider supersession avant tout merge. |
| #234 | `VALIDATION_ONLY / OPEN_DRAFT / DO_NOT_MERGE`. Benchmark eBay public borné/inconclusif. |
| #233 | `STALE_OPEN/SUPERSEDED` par #238/#239. Ne pas merger. |
| #230 | `VALIDATION_ONLY / OPEN_DRAFT / DO_NOT_MERGE`. Capacité historique déjà en production. |
| #226/#228 | `STALE_OPEN/SUPERSEDED` par #238/#239. |
| #210 | `ROBOT_KB_DURABLE_WRITE_GUARD / EXPLICIT_AUTH_REQUIRED`. Aucun durable write exécuté. |
| #209 | `ROBOT_KB_ROLLBACK_REHEARSAL`. Preuve rollback uniquement. |
| #208 | `ROBOT_KB_MEMORY_ONLY / P3_STACKED`. |
| #206 | `ROBOT_KB_PRE_207_FAIL_CLOSED_PROOF`. |
| #205 | `ROBOT_KB_MEMORY_ONLY_SOLD_CANDIDATES`. |
| #204 | `ROBOT_KB_CARDOVA_MICROVARIANT_PROOF`. |
| #199 | `ROBOT_KB_CARDOVA_SOLD_STACK_ROOT`. |
| #198 | `ROBOT_KB_COMC_PUBLIC_HISTORY_DIAGNOSTIC`. |
| #197 | `ROBOT_KB_FANATICS_PAID_HISTORY_DIAGNOSTIC`. |
| #196 | `ROBOT_KB_LOCAL_PSA_CORROBORATION`. |
| #195 | `ROBOT_KB_BATCH_STACKED`. |
| #194 | `ROBOT_KB_CANONICAL_BOOTSTRAP / STACKED`. |
| #193 | `ROBOT_KB_MANUAL_WRITE_PATH / STACKED`. |
| #192 | `ROBOT_KB_EBAY_BENCHMARK`. |
| #190 | `STALE_OPEN / DOCS_DIAGNOSTIC`. |
| #187 | `ROBOT_KB_PUBLIC_MARKET_RECOVERY`. |
| #176 | `STALE_OPEN / DOCS`. |
| #159 | `STALE_OPEN/SUPERSEDED` fonctionnellement par #177. |
| #141 | `SUPERSEDED_DIAGNOSTIC` par #142/#140. |
| #138 | `SUPERSEDED_BY_139`. |
| #126 | `STALE_OPEN/SUPERSEDED` par #127→#135. |
| #115/#114/#113/#110/#109/#108 | `SUPERSEDED_BY_139`. |
| #111 | `STALE_OPEN/SUPERSEDED` docs. |
| #107 | `STALE_OPEN/SUPERSEDED` Japan Edge PPT display shadow. |
| #106 | `STALE_OPEN/SUPERSEDED` V4 PPT shadow. |
| #96 | `V5 child/deferred`; ne pas merger dans main. |
| #92 | `V5 child/shadow/deferred`; ne pas merger dans main. |
| #87 | Décision produit V4 séparée/non déployée. |
| #54 | `STALE_OPEN/SUPERSEDED`. |
| #8 | **`V5_ONLY / PROTECTED`**. OPEN/DRAFT/NON-MERGED. Ne jamais merger dans `main` sans autorisation explicite utilisateur. |

## Merges récents pertinents

- #255 : external fair-value authority **MERGED / PROD_V4** ; historique GCC observationnel économiquement ;
- #253 : eBay worker resilience **MERGED** ;
- #247 : PokeTrace aggregate quality guard **MERGED / PROD_V4** ;
- #245 : auction pagination default preservation **MERGED / PROD_V4** ;
- #243/#244 : future-start runtime + docs closeout **MERGED** ;
- #238/#239/#242 : eBay worker lineage **MERGED** ;
- #237 : Main Scanner registry rollover **MERGED** ;
- #229/#231 : auction recovery capacity **MERGED** ;
- #222/#224 : TCGdex outage fallback **MERGED** ;
- #216/#217 : TCGdex transport resilience **MERGED** ;
- #214 : external pending throughput **MERGED** ;
- #211/#212 : auction order-drift hardening **MERGED** ;
- #178/#179/#180 : **MERGED**.

## Règles

- `open` ne veut pas dire `à merger` ;
- draft/non-draft ne vaut pas autorisation ;
- vérifier patch + ancestry + supersession avant toute décision ;
- ne jamais merger un child stacké directement si son parent n'est pas résolu ;
- ne jamais exécuter une migration/écriture durable Robot KB par simple merge de code préparatoire ;
- aucune fermeture housekeeping destructive sans autorisation utilisateur ;
- **PR #8 reste explicitement protégée** et non mergée.
