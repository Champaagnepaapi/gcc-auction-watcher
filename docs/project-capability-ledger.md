# Robot Pokémon / GCC Auction Watcher — registre durable des capacités

> **But : empêcher qu'une fonctionnalité déjà construite soit réécrite faute de mémoire.**
>
> `README.md` reste le handoff canonique de l'état courant. Ce registre décrit les capacités, leurs successeurs et leur statut. `docs/project-branch-inventory.md` contient l'inventaire exhaustif des branches distantes.
>
> Avant toute nouvelle implémentation : **README -> capability ledger -> branch inventory -> PR/branche/code/tests réels**. Réutiliser ou backporter le travail validé avant d'en écrire un équivalent.

Dernier audit global : **17 août 2026**.

## 1. Résultat du deep audit

- `main` vérifié au début de l'audit : `c8a495226f9e9800e5e1e2ac6a730ea21b1c3383`.
- **145/145 branches distantes** inventoriées, 145 noms uniques.
- historique des PR existantes parcouru jusqu'à **PR #123** ; le numéro `#1` n'est pas une pull request accessible dans le dépôt.
- PR ouvertes importantes re-vérifiées : #8, #92, #96, #106, #107, #108, #109, #110, #113, #114, #115, #122, #123.
- plusieurs actifs historiques non visibles sur `main` ont été retrouvés explicitement : première génération catalogue GCC, fondations Robot KB P0/P1/P3, cache macro TCGdex PostgreSQL, branches Source Scout PPT/tcgapi.dev, stack Global Multi-Vault complète, diagnostics V5 et anciennes branches de sécurité/observabilité.
- aucune branche supprimée, aucun live production déclenché, aucun achat/bid/checkout/paiement, aucun merge de PR #8.

## 2. Statuts

| Statut | Sens |
|---|---|
| `PROD_V4` | présent dans `main` et utilisé par la production V4 |
| `MAIN_SUPPORT` | présent dans `main`, support/diagnostic/shadow mais pas décision économique production |
| `V5_ONLY` | ligne V5 expérimentale / PR #8, hors production V4 |
| `SHADOW` | implémenté/validé volontairement hors production |
| `DEFERRED` | travail valide conservé, intégration reportée |
| `BENCHMARK` | outil/résultat de comparaison, pas source production |
| `SUPERSEDED` | ne pas reprendre comme base ; un successeur fait autorité |
| `DISABLED` | code historique éventuellement conservé, comportement volontairement désactivé |

## 3. Règle anti-réimplémentation

Pour toute mission non triviale :

1. chercher la capacité et ses synonymes dans README + ce registre + l'inventaire des branches ;
2. chercher les PR/commits historiques, y compris closed/unmerged ;
3. inspecter V4, V5, Robot KB, Source Scout, Japan Edge et les stacks shadow pertinentes ;
4. suivre la chaîne de supersession ;
5. partir du dernier travail compatible et validé ;
6. préférer port/adaptation/backport à une implémentation indépendante ;
7. si une réécriture est réellement nécessaire, documenter pourquoi l'ancienne architecture ne convient pas ;
8. ne jamais réactiver une capacité `DISABLED` ou `SUPERSEDED` sans relire le root cause et le successeur.

Une branche absente de `main` n'est **jamais** une preuve que la fonctionnalité n'a pas été construite.

---

# 4. Première génération identité GCC -> transition TCGdex

Cette lignée explique plusieurs fonctions présentes aujourd'hui et doit être conservée comme histoire de root cause.

## PR #2 — grading GCC structuré / representative matching

**Statut : `PROD_V4` pour les éléments mergés ; historique V5 superseded par l'architecture actuelle.**

Branche : `chatgpt-v4-v5-live-fix-20260810`. Merge `98c59d35d76829643efe57a9d40a3b41cb588e1b`.

Déjà construit :
- préserver `gradingCompany` / `grade` structurés GCC ;
- distinguer SFG, SGS, SCA, TCC et graders existants ;
- V5 representative lookup indépendant de la fenêtre économique V4 0-100 EUR ;
- unique `STRONG_MATCH` sûr accepté, conflit/ambiguïté bloquant ;
- compteurs exact/strong/ambiguous/no-representative.

**Réutilisation :** pour parsing graders GCC, inspecter d'abord le code V4 courant + cette lignée ; ne recréer aucun mapping grader parallèle.

## PR #3 / #4 / #5 / #6 — catalogue GCC cumulatif historique

**Statut : `SUPERSEDED` comme autorité d'identité primaire, mais actifs historiques utiles.**

Branches :
- `chatgpt-gcc-catalog-resolver-20260810` ;
- `chatgpt-gcc-search-fix-20260810` ;
- `chatgpt-gcc-cumulative-index-20260810` ;
- `chatgpt-v5-oauth-cache-fix-20260810` ;
- diagnostic `chatgpt-gcc-conflict-diagnostics-20260810`.

Déjà construit :
- Explore/Completed Sales GCC comme fallback catalogue quand aucun représentant actuel n'existe ;
- correction du sélecteur de recherche Explore pour éviter le header/global search ;
- index cumulatif persistant enrichi par ventes courantes + Completed Sales ;
- provenance de conflits par champ d'identité ;
- persistance du catalogue/cache même si un diagnostic V5 échoue.

**Autorité actuelle :** TCGdex-first V5 et TCGdex canonical V4. Ne pas réintroduire l'ancien index GCC comme source primaire sans justification.

## PR #7 — origine TCGdex-first V5 + garde d'arbitrage V4

**Statut : `V5_ONLY` pour la partie identité V5 ; garde V4 absorbée dans la production actuelle.**

Branche : `chatgpt-tcgdex-identity-and-v4-arbitrage-guard-20260810`.

Déjà construit :
- TCGdex multilingue devient resolver principal V5 ;
- langue comme dimension first-class ;
- fallback catalogue Pokémon TCG API pour les cas autorisés à cette époque ;
- **garde V4 grade-arbitrage** : validation externe forte exige des comparables exact-card, même grader, grade cible exact ; éviter les arbitrages fabriqués par grade/grader incompatible.

Cette PR est l'origine historique de la lignée TCGdex moderne.

---

# 5. V5 — identité TCGdex / microvariantes / fallback

**Statut global : `V5_ONLY`. PR #8 reste draft, ouverte, non mergée.**

PR #8 actuelle re-vérifiée : head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f`, 246 commits, 74 fichiers changés. Ne jamais merger dans `main` sans autorisation explicite.

Modules à inspecter avant toute nouvelle logique d'identité :
- `v5/card_identity_catalog.py`
- `v5/card_identity_uniqueness.py`
- `v5/microvariant_detector.py`
- `v5/microvariants.py`
- `v5/variant_semantics.py`
- `v5/detailed_identity_observability.py`
- `v5/emergency_identity_fallback.py`
- `v5/robot_kb_identity_cache.py`

## PR #31 — unicité déterministe « two-of-three »

**Statut : `V5_ONLY`; backport partiel/propre dans PR #123.**

Branche `agent/v5-deterministic-catalog-uniqueness`. Validation historique run `31542551507` : V5 `463/463`, V4 `169/169`, compile/YAML/diff PASS.

Contrat :
- nom exact + numéro imprimé complet `x/y` -> set récupérable seulement si un seul macro-card compatible ;
- set exact + nom exact -> numéro récupérable seulement si une seule carte de ce nom existe dans ce set ;
- une coordonnée seule ne suffit jamais ;
- numerator-only ne récupère pas un set par cette voie ;
- collision/overflow/dénominateur incompatible -> fail-closed ;
- preuve macro ne prouve jamais First Edition/Unlimited/Shadowless/finish/stamp/promo.

## PR #36 — premium variant evidence

**Statut : `V5_ONLY`, principe repris dans les gates V4 actuels.**

Metadata provider/candidate ne fabrique jamais une variante premium du listing. Inconnu reste inconnu/ambiguous.

## PR #38 / #39 — parser de coordonnées / multi-card

**Statut : `V5_ONLY`.**

Branche #39 `agent/v5-identity-coverage-expansion`.

Déjà fait : codes `sv2a`, `SVP`, `CS4.1C`, `Journey Together`, forme inversée `169/165 SV2a`, rejet précoce multi-card, règle qu'un code `SV*` explicite ne remplace pas un set spécifique déjà prouvé. #39 : `509` tests.

## PR #40 / #41 / #44 — ambiguity, post-macro, finish exact

**Statut : `V5_ONLY`; certaines règles ont déjà des équivalents V4.**

PR #40 branche `agent/v5-ambiguity-reconciliation`, head `127e1536a46412327c2b0b7d8bd0429ed9f5ec1f`, mergée dans V5.

Déjà fait :
- eBay `Features` = dimensions additives ;
- exact post-macro TCGdex retry nom + numéro complet unique ;
- macro-set existant doit rester cohérent avec l'exact set TCGdex ;
- seller ambiguity reste bloquante ;
- provider metadata non probante pour microvariant ;
- finish catalogue exact ne débloque que les variantes détaillées simples/uniques ;
- title finish parser avec span masking (#44).

Validations historiques : #40 `519`, #41 `523` tests.

## V5 visual identity / OCR / forensic microvariants

**Statut : `V5_ONLY/BENCHMARK`.**

Actifs existants :
- `v5/visual_identity.py`
- `v5/card_number_ocr.py`
- `tests_v5/test_visual_identity.py`
- `tests_v5/test_card_number_ocr.py`
- `tests_v5/test_forensic_microvariants.py`
- `tests_v5/test_local_microvariant_detector.py`

Ne pas recréer une couche visuelle/OCR V5 sans audit de ces fichiers. La preuve visuelle reste secondaire/fail-closed.

## PR #81 / #82 — observabilité + CI offline

**Statut : `V5_ONLY`.**

- #81 branche `agent/v5-identity-observability-clean` : diagnostics passifs identity/fallback/rejections/visual ; run `31898349431`, `569/569`.
- #82 branche `agent/v5-offline-ci` : workflow V5 Offline Validation sans secrets/providers live.

## PR #85 / #86 / #88 — politique normale + outage

**Statut : `V5_ONLY`, autorité actuelle.**

- #85 `agent/v5-poketrace-market-only`: PokeTrace n'est plus resolver normal, `572/572` ;
- #86 `agent/v5-emergency-identity-fallback`: PokeTrace identité uniquement sur vraie panne technique TCGdex, `579/579` ;
- #88 `agent/v5-robot-kb-identity-cache`: cache TCGdex prouvé Robot KB/Neon avant Pokémon TCG API, `585/585`.

Ordre canonique outage :

```text
TCGdex live
-> cache TCGdex prouvé Robot KB/Neon
-> Pokémon TCG API
-> PokeTrace emergency-only
-> fail closed
```

Urgence éligible : transport, JSON invalide, HTTP `408/425/429/5xx`. `CLEAN_NO_MATCH`, `404`, autres 4xx non transients n'ouvrent pas l'emergency.

`diag/v5-neon-cache-probe-20260816` est un probe live de ce cache après #88, **pas une architecture distincte**.

## PR #93 — applicabilité exacte / promo namespaces / `wPromo`

**Statut : `V5_ONLY`, mergée dans V5 head `bc641dfe...`.**

Offline `600/600`. Live `31916052221`: 17 TCGdex requests, 2 hits, 0 variant-impossible, Robot KB 1 insert + 1 idempotent, aucune transaction.

Conserver :
- exact post-macro retry réellement câblé ;
- mappings promo versionnés/bornés ;
- leading-zero uniquement dans namespaces prouvés ;
- `wPromo` = W stamp, pas « promo générique » ;
- `dpp-DP45` / Charizard G cas end-to-end prouvé.

`diag/v5-tcgdex-blockers-20260816` appartient à cette lignée : diagnostic finish blockers + expérimentation du post-macro retry, pas nouvelle source d'autorité.

## PR #96 — Pocket digital + curated catalog gaps

**Statut : `DEFERRED`, open draft, non mergée.**

Head `360ae33a67987e0a981b348e636bd7e2f964667e`, `611/611` offline.

Déjà construit : rejet Pokémon TCG Pocket digital + registre exact versionné de cartes physiques absentes du catalogue, seed Magikarp coréen `040/M-P` 2026. Jamais de règle globale `TCGdex miss => accept`.

---

# 6. V4 TCGdex — chaîne réelle et récupération PR #123

## PR #33 — canonical multimarket

**Statut : `PROD_V4`.** Validation historique `304/304`.

TCGdex canonical, puis GCC/PokeTrace/APR/eBay/RAW comme sources séparées.

## PR #35 — cache / normalisation / transient

**Statut : `PROD_V4`.** `313` tests.

Déjà fait : `004/102 == 4/102`, denominator dans clé cache, 429/5xx != no-match, pas de poisoning transient, réduction doubles appels.

## PR #117 / #118 — observabilité

**Statut : `PROD_V4`; #118 autorité.** `607/607` + compile/YAML/diff/discovery PASS.

Root cause : un installer downstream écrasait `process_external_market_candidates`. L'observabilité doit être finalisée après les wrappers remplaçants.

## PR #119 / #120 / #121

**Statut : `PROD_V4`.**

- #119 : registre exact de coordonnées run 1037, pin `tcgdex/cards-database@af33c9ac882e2acfadffaf19e8083aa976d12983` ;
- #120 : récupération généralisée exact set/localId, namespaces promo, suffixes Holo/Gold bornés ; `627/627` ;
- #121 : 7 aliases exacts run 1054 ; production main `c8a495...`.

Ces fast paths restent utiles mais ne doivent plus devenir un treadmill run-by-run.

## PR #122 — unique-coordinate fallback

**Statut : `DEFERRED`, open, non mergée, non-draft.**

Head `e8f00ef1cd36059ba08e8c7a27a18eb8183cdd18`; run `32032879591`, `650/650`, compile/YAML/diff/discovery PASS.

Contrat : numeric denominator -> complete set index/cardCount + exact localId + unicité globale ; namespace non numérique -> exact set ID/localId ; alphanumeric localId -> unicité globale ; numeric localId sans denominator reste unresolved ; provider incomplet nécessaire à la preuve -> ERROR ; multiple -> AMBIGUOUS.

Limite : ne récupère pas toute PR #31, notamment exact set + exact name -> missing number.

## PR #123 — récupération complète + mémoire durable

**Statut : `DEFERRED`, open draft, non mergée.**

Branche `fix/v4-recover-existing-capabilities-20260817`, base main `c8a495...`.

Elle étend #122 et ajoute `v4_tcgdex_two_of_three_backport.py` :
1. canonical ;
2. #119 exact coordinates ;
3. #121 reviewed aliases ;
4. #120 generalized set/localId ;
5. V5 #31 two-of-three backport ;
6. #122 global unique-coordinate fallback ;
7. downstream microvariant/economic gates inchangés.

Validation précédente avant le deep branch audit : run `32037717124`, **662/662**, compile/YAML/diff + discovery 86/86 PASS. Un nouveau run doit valider les docs/tests ajoutés par le deep audit avant toute décision de merge.

---

# 7. RAW consensus et price discovery multi-grader

## `agent/v4-robust-raw-consensus` -> merge production `8a61a6a5...`

**Statut : `PROD_V4`.**

Branche tip vérifié `7541f504b30a5e57023d1af471914ada75611886`; ce tip est ancêtre de `main`. Merge production `8a61a6a5ec8740b9b8413cc82de26f11db064c43`, message `merge(v4): promote robust raw consensus to production`.

Modules :
- `v4_raw_consensus.py`
- `v4_price_discovery.py`

### RAW consensus déjà construit

- Cardmarket / TCGplayer / JustTCG / PriceCharting / eBay RAW adapters conceptuels ;
- RAW != valeur d'un slab ;
- RAW ne crée jamais `max_recommended` ;
- édition/finish/special finish multilingues ;
- `PROVIDER_PROVEN`, `CATALOG_PROVEN`, `UNKNOWN` ;
- unknown requis exclut source d'un quorum fort ;
- anti-outlier/provider disagreement ;
- deux providers incomplets ne fabriquent pas un consensus STRONG.

### Price discovery déjà construit

- `CROSSGRADE_OPPORTUNITY` ;
- `SECONDARY_GRADER_DISCOUNT` ;
- `ILLIQUID_PRICE_DISCOVERY` ;
- adjacent-grade anchors ;
- uncertainty explicite ;
- ask seul ne crée pas opportunity ;
- cross-language downweight ;
- low-grade ne s'ancre pas naïvement sur PSA10.

### Ajustement temporel cross-grader

C'est le moteur à réutiliser pour « vieille vente SGS/PCA/etc. + marché PSA qui a bougé depuis » :

1. vente historique grader cible ;
2. référence historique grader de référence, même grade, proche en temps ;
3. ratio historique target/reference ;
4. application de ce ratio à la valeur récente du marché de référence ;
5. spread/incertitude conservés ;
6. fail-closed sans ratio défendable.

Ne pas réimplémenter ce calcul dans Structural Edge Hunter, Robot KB ou un adapter provider parallèle.

---

# 8. PokeTrace

## V4

**Statut : `PROD_V4`.**

Marché gradé externe exact ; grader/grade/identité compatibles ; n'écrase pas APR/eBay ; absence provider != faible valeur ; RAW ne devient pas slab value.

## V5

**Statut : `V5_ONLY`; autorité #85/#86/#88.**

PokeTrace market-only en normal, identity seulement emergency technique TCGdex après cache/catalog fallback. Ne pas créer une deuxième politique concurrente.

---

# 9. PokemonPriceTracker (PPT)

## PR #92 — V5 identity shadow

**Statut : `V5_ONLY/SHADOW`, open draft, non mergée.**

Head `772353311abac836afbc618047a5e2b146806e36`; offline `592/592`; live `31914845846`: 12 HTTP/120 credits, 5 unique missing-set candidates, 0 ambiguous, 7 no-match, 0 provider errors, aucune mutation identité/variant/value.

Conclusion : retrieval/helper prometteur, pas autorité automatique.

## Source Scout PPT cardinality

**Statut : `BENCHMARK`.**

Branche `agent/source-scout-ppt-cardinality-20260815`, tip `b65180550455d3e51fd9a847c2568d42f020a777`.

Contient le benchmark PPT evidence/cardinality borné. Conclusion enregistrée : **16/18 macro exactes**, 2 vintage ambiguës sur le panel concerné.

## V4 PPT : #90 -> #106

**#90 `SUPERSEDED`; #106 `SHADOW/DEFERRED`.**

PR #106 open draft, head `b2372ceed1591075466df9334255d353534d8b1d`, `622/622` offline. Scope PSA/BGS/CGC/SGC, `SOLD_AGGREGATED`, aucun effet FV/max/opportunity/ntfy. Reprendre #106 si cette couche doit être intégrée.

## Japan PPT : #95 -> #105 -> #107

**#95/#105 `SUPERSEDED`; #107 `SHADOW/DEFERRED`.**

PR #107 open draft, head `7d70844b5511c13f809c7686e2a64c3f705802c4`, `41/41`. Affichage GCC et PPT séparé après décision Japan existante ; PPT display-only, pas blended automatiquement.

---

# 10. Source Scout / benchmarks providers

## Base `agent/source-scout-benchmark-20260814`

**Statut : `BENCHMARK/DEFERRED`.** Head `46f5cc3e1f0b1e041815497d432be62a16a42e31`.

Actifs à réutiliser : workflows et modules `v5/source_scout_*`, policies/probes RapidAPI, PPT, Cardmarket, eBay ASP, Neon ingest, tests et draft Marketplace Insights.

## `agent/source-scout-tcgapi-identity-20260815`

**Statut : `BENCHMARK`.** Tip `15ec52e7de43afe132600a274b3e344fa2a60e2a`.

Benchmark borné tcgapi.dev ; conclusion enregistrée : **3/18 macro exactes**, langue non prouvée.

## JustTCG

**Statut : `BENCHMARK`, pas autorité.**

Benchmark corrigé set-aware : **0/20 exacts**. Ne pas promouvoir sans nouveau benchmark prouvant toutes les dimensions nécessaires.

## eBay ASP / RapidAPI

**Statut : `BENCHMARK/SAFE-OFF`.**

Probes/policy Basic déjà faits ; les routes testées qui échouaient ou renvoyaient 404 ont été laissées safe-off, pas déclarées source SOLD production.

## Marketplace Insights

**Statut : `DEFERRED` accès externe.**

Draft de support déjà présent dans Source Scout. Reprendre le document/état courant, ne pas réécrire la demande de zéro.

---

# 11. V4 multi-market / provider queues / observabilité

## PR #29 -> #33

#29 précurseur external-market-before-terminal-reject ; #33 est l'architecture canonical production.

Chemins conservés : `GCC_ONLY`, `GCC_EXTERNAL_CONFIRMED`, `EXTERNAL_RESCUE`, `EXTERNAL_PENDING`, `MARKET_CONFLICT_BLOCKED`.

## PR #32 / #46 — PSA APR

**Statut : `PROD_V4`.**

Hydration client-rendered bornée ; distinction 403/429/5xx/challenge avant « formulaire absent » ; aucun bypass WAF/CAPTCHA.

## PR #17 — technical alert noise

**Statut : `PROD_V4`/observabilité.** Branche `ops/v4-technical-alert-noise`.

Déjà résolu : ne pas spammer ntfy pour drift de count fixed structurellement sûr ; vraie perte discovery/failure/invariant cassé reste alertable.

## PR #27 — stale backlog diagnostics

**Statut : `PROD_V4`/observabilité.** Branche `agent/v4-fix-stale-backlog-diagnostic`.

Compte correctement STALE/backlog sans redéfinir la couverture discovery.

## PR #47 — adaptive refresh

**Statut : `PROD_V4`.** Branche `adaptive_v4_market_refresh`.

Refresh fixed externe 1-6h selon proximité du seuil, recomputation complète, budgets bornés, auctions inchangées.

## PR #43 / #77 / #116 — budgets/queue

**Statut : `PROD_V4`.**

Déjà fait : fixed non affamé par auctions, smart priority, external coverage drain, `PENDING_BUDGET` = scheduling pressure/retry court, vrai transient garde backoff, auction ending-soon preserved.

Inspecter `v4_external_coverage_drain.py`, `v4_smart_external_priority.py` et queue/state actuelle avant toute nouvelle file.

## PR #53 — Edge Hunter safety hotfix

**Statut : `PROD_V4`.** Branche `agent/v4-edge-hunter-safety-hotfix`.

Déjà fait : canonicalisation langue, EXACT interdit sur identité incomplète, distinction same-grader/secondary-grader, séparation discovery/global coverage.

## PR #56 — notification semantics

**Statut : `PROD_V4`.** Branche `agent/v4-external-confirmation-labels`.

Titres/labels user-facing externes déjà centralisés ; ne pas recréer des wrappers concurrents.

---

# 12. Auctions / discovery / Fast Lane

## PR #9 — auction item-level discovery

**Statut : `PROD_V4`.**

`/on-sale-items`, AUCTION, ENDING_SOON, endTime individuel ; fallback legacy si coverage non prouvée. `COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS` != tout GCC.

## PR #50 / #52 — private safety net

**Statut : `PROD_V4`.**

Safety-net private + accounting isolé du ledger API primaire.

## PR #103 -> #104 — pagination drift

**#103 `SUPERSEDED`; #104 `PROD_V4`.**

Snapshots ancrés/répétés, union bornée, fallback legacy si instable. #104 est aussi l'autorité production pour Mislisted hard-disabled.

## PR #30 -> #45 / #55 — final auction

**#30 `SUPERSEDED`; #45/#55 `PROD_V4`.**

Fast Lane zéro-sleep, recheck ciblé ≤5m, même persisted `max_recommended`, identity lock final. Jamais d'auto-bid.

---

# 13. ASK / SOLD / Structural Edge / notification quality

## PR #78 — exact eBay BIN ASK

**Statut : `PROD_V4`.**

ASK context uniquement après opportunity ; ne crée jamais opportunity/FV/max/SOLD ; texte `ASK, PAS UNE VENTE`.

## PR #79 — stale listing / momentum / KB analytics

**Statut : `PROD_V4`.**

Signal information/ranking only ; aucun hard gate KB-first tant que profondeur insuffisante ; analytics Robot KB read-only.

## PR #80 — Structural Edge Hunter V2

**Statut : `PROD_V4`.** `571/571`.

Déjà fait : cross-market lag, grader lag, stale seller repricing, liquidity breakout, relative-grade anomaly, same-card inventory anomaly, Expected Profit secondaire/ranking-only.

## PR #84

**Statut : `PROD_V4`.**

Notification quality guard : RAW seul ne crée pas slab opportunity, illiquid guard, duplicate manual review filtering. Ne pas confondre avec PR #87 draft/fermée sur un seuil GCC-only.

---

# 14. Japan Edge

## PR #89

**Statut : `PROD_V4`, lane séparée.**

Japanese individual PSA10 asks Mercari/magi/Yahoo-Flea vs GCC exact SOLD. Live `31914421575`: 2000 GCC SOLD, 341 éligibles, 59 groupes exacts, 328 asks, 1 lead exact, 0 provider error.

## PR #94

**Statut : `PROD_V4`.**

Ajoute contexte externe exact JP PSA10 PokeTrace/eBay/APR lorsque langue prouvée ; PokeTrace/eBay corrélés comme même famille ; absence externe != négatif.

## PR #101

**Statut : `PROD_V4`.**

Présentation séparée coût Japon / GCC / external / fair / verdict, sans changement économique.

PPT Japan reste séparé via #107 shadow.

---

# 15. Global Multi-Vault — stack déjà construite

**Statut global : `SHADOW/DEFERRED`, jamais production V4.**

Ne jamais repartir d'une feuille blanche.

## PR #108 — fondation

Open draft, head `e2a6fafeaa4a607010f0bd7378bc70caa708f306`. `27/27` global + `51/51` multimarket, run `31953479268`.

Actifs : `v4_global_market_core.py`, bridges PPT/PokeTrace, Cardova/GCC/magi/Fanatics/COMC, verified offer.

Contrat : strict identity ; EN/JAP opportunities ; FR collectable non-actionable tant que profondeur insuffisante ; `SOLD_EXACT` vs `SOLD_AGGREGATED`; ASK/current auction hors FV ; ≤5m snapshot != SOLD ; frais inconnus -> fail-closed.

## PR #109 — live shadow

Open draft, head `f3f94c4436b60e307f6ea8e5d97b92d3347d5db2`.

Live `31954247131`: 5 JP PSA10 ; GCC 1600 candidates/6 exacts ; magi 35/0 ; Fanatics 24/0 ; COMC 2/0 ; Cardova `AUTH_SESSION_INPUT_REQUIRED`; no ntfy/Neon/transaction.

## PR #110 — rejection diagnostics

Open draft, head `fa98713591f002eb0238e4535b718a037f90f86f`, run `31957019952`.

Trouva : magi retrieval noise/multi-item ; Fanatics collector-number unproven ; COMC no player/card-number candidates ou PSA10 unproven.

## PR #113 — retrieval hardening

Open draft, head `a771b783fbcd98c4fdb6ba1008df35fa83263b54`. `49/49` global + `51/51` regressions.

Magi exact full-number prefilter/detail-only ; Fanatics local-number + exact set/localId proof ; COMC exact set+localId/Japanese/name, PSA10 detail mandatory. Live manual encore requis selon la PR.

## PR #114 — Magi SOLD filter

Open draft, head `c40aa846ce5fdc4213afa0895e4440a04995b85a`, run `31968328368`, `105/105` global + `51/51` regressions.

Rejette explicit `SOLD`, `SOLD OUT`, `売り切れ`, `販売済み`, etc. avant création d'un ASK. Absence de marker ne fabrique jamais une vente.

## PR #115 — COMC exact set facet

Open draft, head `e9906b97ee54251fb4ff85417c5a8556da9068a1`, run `31970920861`, `109/109` global + `51/51` regressions.

Route retrieval bornée exact Raging Surf Japanese/Groudon facet ; strict identity/PSA10 reste obligatoire. Live shadow post-fix encore pending/manual.

## PR #112 — dispatcher manuel

**Statut : `MAIN_SUPPORT`, mergée.**

Expose `V4 Global Market Live Shadow`; main ne contient volontairement pas toute la stack shadow. Absence des modules sur main != travail inexistant.

**Réutilisation :** partir de la stack complète #108→#109→#110→#113→#114→#115, puis rebase/port propre sur le main courant. Ne pas merger une child PR directement sur main.

---

# 16. Robot KB / Neon — fondations et lanes durables

Robot KB reste une architecture séparée, append-only/read-only côté collecte commerciale.

## P0 — immutable knowledge base foundation

**Statut : architecture fondatrice, historique à réutiliser.**

Branche `agent/p0-card-knowledge-base-foundation`, tip `946f4b7511f966c00b215a34178b183d01712c3e`.

Commits clés : foundation immutable, integrity hardening, embedded market metric identity, final integrity gaps. P0 part du merge RAW consensus `8a61a6...`.

## P1 — shadow observation sidecar

**Statut : précurseur de la capture passive déployée.**

Branche `agent/p1-shadow-observation-sidecar`, tip `b340d61fded158feb91902a8602dba1e4b82e11d`.

Déjà fait : passive observation sidecar, ingest hardening, fail-closed single-card scope, résolution du vrai scope GCC single-card.

## P3 — PostgreSQL/Neon durable

**Statut : fondation durable déployée/continuée par les PR Robot KB suivantes.**

Branche `agent/p3-postgres-durable-shadow`, tip `1d06fe33b6fc640657255e15a8d17251aa02b6ce`, qui inclut merge PR #59 explicit GCC SOLD.

## `agent/kb-tcgdex-macro-cache`

**Statut : architecture cache identity historique / precursor direct de V5 #88.**

Tip `f89aa90178ee9dbfa3136e2310bc468927e4da3b`.

Déjà fait : PostgreSQL catalog identity cache, immutable TCGdex macro snapshots, conservation des reversion histories et des changed/reverted snapshots. Ne prouve jamais à lui seul les microvariantes sensibles.

## PR #49/#51 — mirror passif

V4 observe ses réponses déjà fetchées, artifact séparé, writer Neon séparé ; auction near-final = LISTING_SNAPSHOT, jamais SALE.

## PR #59/#60 — explicit SOLD

`SALE_TRANSACTION` seulement top-level `status=SOLD` + `soldAt` timezone-aware + prix final positif. `ENDED` ou missing soldAt = snapshot.

## PR #61 -> #62 — fixed rotation

#61 `SUPERSEDED`; #62 autorité de rotation durable de cette phase, `468` tests.

## PR #68 / #72 / #75 / #76

**Statut : déployé Robot KB.**

- #68 lossless SOLD watermark `soldAt + ids frontière`, state advance après ingest uniquement ;
- #72 SOLD 30 min séparé des fixed/auction hourly ;
- #75 fixed hybrid jusqu'à 100 recent + 200 rotation + 100 targeted ;
- #76 historical SOLD backfill, ≤400/run, cursor séparé, shared soldAt safe.

`robot_kb_roi_analytics.py` reste read-only ; ratios appris ne deviennent pas heuristiques automatiques sans phase dédiée.

---

# 17. Certificats / Mislisted Slab / OCR

**Statut final production : `DISABLED` pour la lane Mislisted Slab/OCR.**

## PR #57 / #63 — débuts de la lane

Branches `agent/v4-mislisted-slab-hunter` et ancienne image-grade mismatch/cert evolution. Ce sont des précurseurs historiques ; ne pas les réactiver directement.

## PR #64 / #65

Official cert > OCR ; adapters étendus ; PSA/PCA/CCC OCR ciblé ; subgrades exclus ; consensus OCR ; IMAGE_ONLY = manual review.

Benchmark #65 : 24 slabs, 4 exact, 0 wrong, 12 ambiguous, 8 unavailable. « 100 % » signifie seulement 4/4 lectures acceptées correctes, pas 24/24.

## PR #66 / #67 / #69 / #71 / #73

- #66 review seulement si opportunity réelle ;
- #67 high-sensitivity cert-problem ;
- #69 safe-off après faux `CERT_NUMBER_MISSING` ;
- #71 préserve cert structuré API + fallback Description→Gradation ; diagnostic 100/100 cert, **pas TCGdex** ;
- #73 pure technical cert failure = log-only.

## PR #103 -> #104

#103 `SUPERSEDED`; #104 autorité production : Mislisted/OCR hard-disabled après faux positifs. Toute future réactivation exige une phase explicite séparée et comparaison à cette root cause.

---

# 18. Workflows / ops / repo hygiene

## Scheduler V4

Production Main Scanner/Fast Lane utilise l'ordonnancement externe existant vers `workflow_dispatch`; ne pas ajouter un schedule GitHub parallèle.

## PR #13

Playwright/Chromium cache déjà optimisé. Ne pas recréer une deuxième installation/cache.

## PR #24

Anciens diagnostics V5 redondants supprimés au profit des workflows consolidés. Ne pas les ressusciter sans besoin nouveau.

## PR #111 — repo hygiene

**Statut : documentation/gouvernance historique.**

A documenté la forte surface de branches/PRs et fermé certaines lignes obsolètes/superseded (#30/#90/#95/#105). Le deep audit actuel confirme **145 branches distantes** : ne supprimer aucune branche sans ancestry/workflow/unique-file audit explicite.

Branches `ops/v5-live-dispatch-once-*`, `ops/japan-edge-run-*`, `tmp-*`, `oops-no-more` sont opérationnelles/temp/no-op ; elles restent inventoriées mais ne sont jamais des autorités fonctionnelles.

---

# 19. Chaînes de supersession à connaître

| Ancien | Autorité / successeur | Instruction |
|---|---|---|
| catalogue GCC primaire #3-#6 | TCGdex-first #7 puis V5 actuel | ancien index = historique/fallback conceptuel, pas autorité normale |
| PR #30 final-auction long wait | PR #45 Fast Lane | ne pas reprendre #30 |
| PR #61 Robot KB mixed lane | #62 puis #68/#72/#75/#76 | reprendre la chaîne durable |
| PR #67 cert high sensitivity | #69/#71/#73 puis #104 disabled | ne pas réactiver #67 |
| PR #90 PPT V4 | PR #106 | reprendre #106 |
| PR #95 Japan PPT | #105 puis #107 | reprendre #107 |
| PR #105 Japan PPT | PR #107 | #105 obsolète |
| PR #103 pagination/mislisted | PR #104 | reprendre #104 |
| anciens V5 diagnostics | #24 + V5 Offline/Live consolidated | ne pas recréer |
| aliases TCGdex #119-#121 seuls | #31 + #122 + #123 | préférer architecture générique, aliases restent fast paths |
| global foundation #108 seule | stack #108→#115 | reprendre la dernière stack compatible |

---

# 20. Séparation obligatoire des architectures

- **V4 `main`** : production decisions/notifications GCC canonique.
- **V5 / PR #8** : expérimental, jamais merge main sans autorisation explicite.
- **Robot KB/Neon** : historique durable, séparé de décision commerciale.
- **Global Multi-Vault #108-#115** : shadow/deferred.
- **PPT #92/#106/#107** : shadow/helper/display selon lane, pas autorité automatique.
- **Source Scout** : benchmark provider.
- **Mislisted Slab/OCR** : historique, production disabled.

---

# 21. Benchmarks à ne pas mal interpréter

- Aucun benchmark vérifié retrouvé prouvant **TCGdex 500/500**.
- Le `100/100` cert de #71 concerne la visibilité des certificats GCC/Gradation, pas l'identité TCGdex.
- OCR #65 : 4 lectures acceptées correctes / 0 wrong, mais 12 ambiguous + 8 unavailable sur 24.
- Les suites `509`, `519`, `523`, `569`, `600`, `611`, `650`, `662` sont des **tests logiciels**, pas des panels live TCGdex.
- PPT benchmark : 16/18 macro exactes, 2 vintage ambiguës sur son panel.
- tcgapi.dev : 3/18 macro exactes, langue non prouvée.
- JustTCG : 0/20 exact set-aware.

Toute future revendication de couverture doit enregistrer population, source, sampling, langues, définition EXACT, ambiguïtés/errors, run ID et SHA.

---

# 22. PR ouvertes importantes au 17 août 2026

| PR | Statut | Rôle |
|---|---|---|
| #8 | open draft, non mergée | V5 expérimentale canonique |
| #92 | open draft | PPT identity shadow V5 |
| #96 | open draft | Pocket reject + curated catalog gaps V5 |
| #106 | open draft | clean PPT V4 shadow |
| #107 | open draft | Japan PPT display-only |
| #108 | open draft | Global Multi-Vault foundation |
| #109 | open draft | global live shadow |
| #110 | open draft | global rejection diagnostics |
| #113 | open draft | global retrieval hardening |
| #114 | open draft | Magi SOLD availability guard |
| #115 | open draft | COMC exact-set retrieval route |
| #122 | open, non-draft | V4 unique-coordinate fallback |
| #123 | open draft | recovery architecture + durable project memory |

Aucun de ces statuts n'est une autorisation de merge.

---

# 23. Format obligatoire après toute nouvelle phase

```text
Capability:
Status: PROD_V4 | MAIN_SUPPORT | V5_ONLY | SHADOW | DEFERRED | BENCHMARK | SUPERSEDED | DISABLED
Authoritative PR / branch:
Base SHA:
Validated head SHA:
Files/modules:
Behavior contract:
Identity/evidence safety invariants:
Focused tests:
Full tests:
Compile/YAML/diff:
Live run(s): none | run IDs + exact scope
Production deployment: yes/no + merge SHA
Supersedes:
Superseded by:
Reuse instruction:
```

Une phase n'est pas complètement archivée tant que README + ce registre + l'inventaire des branches permettent à un nouvel agent de savoir immédiatement : **si le travail existe, où il vit, quelle version fait autorité, comment il a été validé et s'il est production, V5-only, shadow, benchmark, superseded ou disabled.**
