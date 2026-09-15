# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

## État vérifié — 15 septembre 2026

Autorité production : `main@3c596370ee7fcde93c969139541bc003e7012b6e` après merge de #268.

PR #8/V5 reste **OPEN / DRAFT / NON MERGED**, head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f`, protégée. Robot KB/P3/Neon restent séparés de V4.

Ce document n'est pas un compteur exhaustif de toutes les PR historiques. Il classe les PR encore pertinentes pour une décision ou une supersession. GitHub live reste prioritaire.

## PR courantes à connaître

| PR | État / instruction |
|---|---|
| #274 | **OPEN / DRAFT / DOCS_ONLY / EXPLICIT_AUTH_REQUIRED**. Closeout documentaire post-#268, branche `docs/post-268-closeout-20260914`. Aucun runtime modifié ; ne pas merger sans autorisation explicite. |
| #273 | **OPEN / DRAFT / DIAGNOSTIC_ONLY / DO_NOT_MERGE**. Diagnostic Fanatics read-only, head `c31882e8adacff8c291a43e78eb8ab6712ff2359`. Workflow `34886340368` SUCCESS. Le plancher PPT a correctement bloqué un appel lorsque `daily_remaining=55`; aucune raison de relâcher cette protection. |
| #271 | **OPEN / DRAFT / DRAFT_VALIDATION / EXPLICIT_AUTH_REQUIRED**. Correction PokeTrace FREE production, head `75eb09768bf55d002466c5e3d50b038c3884ceb5`. Global `34879803090`, Auction `34879802895`, Cardova `34879802823` SUCCESS. Prête techniquement, non déployée. |
| #270 | **OPEN / DRAFT / ROBOT_KB_ONLY / EXPLICIT_AUTH_REQUIRED**. Snapshots Magi marqués SOLD, sans les transformer en ventes prouvées. Séparée de V4. |
| #269 | **OPEN / DRAFT / STALE_REVIEW_REQUIRED**. Branche d'identité exact-coordinate basée avant #268 et très large ; ne pas merger telle quelle sans nouveau reuse audit contre `main`. |
| #258 | **OPEN / DRAFT / STALE_OPEN / SUPERSEDED_BY_259**. Recall intégré par #259. Ne pas merger. |
| #256 | **OPEN / DRAFT / STALE_OPEN / SUPERSEDED_BY_259**. Capacités Japan Mercari/SNKRDUNK pertinentes intégrées par #259. Ne pas merger. |
| #248 | **OPEN / DRAFT / STALE_OPEN / SUPERSEDED_DIAGNOSTIC**. Ancien diagnostic eBay, superseded par #250→#254. |
| #246 | **OPEN / DOCS_ONLY / STALE_OPEN**. Ancien closeout dépassé par les phases ultérieures. |
| #234 | **OPEN / DRAFT / VALIDATION_ONLY / DO_NOT_MERGE**. Benchmark eBay public borné/inconclusif. |
| #233 | **OPEN / STALE_OPEN / SUPERSEDED** par #238/#239. |
| #230 | **OPEN / DRAFT / VALIDATION_ONLY / DO_NOT_MERGE**. Capacité historique déjà en production. |
| #226/#228 | **OPEN / STALE_OPEN / SUPERSEDED** par la lignée eBay ultérieure. |
| #210 | **OPEN / DRAFT / ROBOT_KB_DURABLE_WRITE_GUARD / EXPLICIT_AUTH_REQUIRED**. Aucun durable write Cardova autorisé par défaut. |
| #209 | **OPEN / ROBOT_KB_ROLLBACK_REHEARSAL**. Preuve rollback seulement. |
| #208 | **OPEN / ROBOT_KB_MEMORY_ONLY / P3_STACKED**. |
| #206 | **OPEN / ROBOT_KB_PRE_207_FAIL_CLOSED_PROOF**. |
| #205 | **OPEN / ROBOT_KB_MEMORY_ONLY_SOLD_CANDIDATES**. |
| #204 | **OPEN / ROBOT_KB_CARDOVA_MICROVARIANT_PROOF**. |
| #199 | **OPEN / ROBOT_KB_CARDOVA_SOLD_STACK_ROOT**. |
| #198 | **OPEN / ROBOT_KB_COMC_PUBLIC_HISTORY_DIAGNOSTIC**. HTTP 403 public history observé ; aucun bypass. |
| #197 | **OPEN / ROBOT_KB_FANATICS_PAID_HISTORY_DIAGNOSTIC**. |
| #196 | **OPEN / ROBOT_KB_LOCAL_PSA_CORROBORATION**. |
| #195 | **OPEN / ROBOT_KB_BATCH_STACKED**. |
| #194 | **OPEN / ROBOT_KB_CANONICAL_BOOTSTRAP / STACKED**. |
| #193 | **OPEN / ROBOT_KB_MANUAL_WRITE_PATH / STACKED**. |
| #192 | **OPEN / ROBOT_KB_EBAY_BENCHMARK**. |
| #190 | **OPEN / STALE_OPEN / DOCS_DIAGNOSTIC**. |
| #187 | **OPEN / ROBOT_KB_PUBLIC_MARKET_RECOVERY**. |
| #176 | **OPEN / STALE_OPEN / DOCS**. |
| #159 | **OPEN / STALE_OPEN / SUPERSEDED** fonctionnellement par #177. |
| #141 | **OPEN / SUPERSEDED_DIAGNOSTIC** par #142/#140. |
| #138 | **OPEN / SUPERSEDED_BY_139**. |
| #126 | **OPEN / STALE_OPEN / SUPERSEDED** par #127→#135. |
| #115/#114/#113/#110/#109/#108 | **OPEN / SUPERSEDED_BY_139**. |
| #111 | **OPEN / STALE_OPEN / SUPERSEDED_DOCS**. |
| #107 | **OPEN / STALE_OPEN / SUPERSEDED** Japan Edge PPT shadow. |
| #106 | **OPEN / STALE_OPEN / SUPERSEDED** V4 PPT shadow. |
| #96 | **OPEN / V5 child/deferred**. Ne pas merger dans `main`. |
| #92 | **OPEN / V5 child/shadow/deferred**. Ne pas merger dans `main`. |
| #87 | **OPEN / décision produit V4 séparée/non déployée**. |
| #54 | **OPEN / STALE_OPEN / SUPERSEDED**. |
| #8 | **OPEN / DRAFT / V5_ONLY / PROTECTED**. Ne jamais merger dans `main` sans autorisation explicite utilisateur. |

## PR récentes fermées/mergées qui changent l'interprétation

- #272 : **CLOSED / NON MERGED** ; récupération PPT English redondante, capacité déjà présente dans `main` ;
- #268 : **MERGED / PROD_V4** via `3c596370...` ; hardening multi-market canonique ;
- #266 : **MERGED / PROD_V4** ; Rainbow microvariant ;
- #263 : **MERGED / PROD_V4** ; tuning CA→PSA 35 % ;
- #261 : **MERGED / PROD_V4** ; cross-grader calibration ;
- #260 : **MERGED / PROD_V4** ; constrained TCGdex name recovery ;
- #259 : **MERGED / PROD_V4** ; recall/source roles/Global/Japan ;
- #257 : **MERGED**, puis intégrée à #259 ;
- #255 : **MERGED / PROD_V4** ; external fair-value authority ;
- #254/#253/#252/#251/#250 : lignée eBay **MERGED** ;
- #247 : PokeTrace aggregate quality historique **MERGED**, politique ensuite modifiée par #259 ;
- #245 : auction pagination preservation **MERGED / PROD_V4** ;
- #243/#244 : future-start runtime + closeout **MERGED** ;
- #238/#239/#242 : lignée eBay worker **MERGED** ;
- #229/#231 : auction recovery capacity **MERGED** ;
- #222/#224 : TCGdex outage fallback **MERGED** ;
- #216/#217 : TCGdex transport resilience **MERGED** ;
- #214 : external pending throughput **MERGED** ;
- #211/#212 : auction order hardening **MERGED** ;
- #178/#179/#180 : **MERGED**.

## Statut provider lié aux PR actuelles

Le closeout #268 reste le classement canonique actuel :

```text
GCC       OPERATIONAL
Fanatics  PROVIDER_BLOCKED
COMC      PROVIDER_BLOCKED
Magi      PROVIDER_BLOCKED
Cardova   PROVIDER_BLOCKED
Mercari   PROVIDER_BLOCKED
SNKRDUNK  PROVIDER_BLOCKED
```

#271 ne change pas ce classement : elle corrige uniquement l'application du plan PokeTrace FREE en production. #273 ne change pas ce classement : elle est diagnostique. #274 ne change pas ce classement : elle est documentation uniquement.

## Règles

- `open` ne signifie jamais `à merger` ;
- draft/non-draft ne vaut pas autorisation ;
- vérifier patch + ancestry + supersession avant décision ;
- ne jamais merger une branche stackée/superseded simplement parce qu'elle reste ouverte ;
- ne jamais exécuter une migration/écriture durable Robot KB par simple merge de code préparatoire ;
- aucune fermeture housekeeping destructive ni suppression de branche sans autorisation ;
- #8 reste protégée ;
- #271 exige une autorisation explicite avant merge ;
- #273 n'est pas destinée au merge production ;
- #274 exige une autorisation explicite avant merge.