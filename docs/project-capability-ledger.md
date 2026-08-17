# Robot Pokémon / GCC Auction Watcher — registre durable des capacités

> **But : empêcher qu'une fonctionnalité déjà construite soit réécrite faute de mémoire.**
>
> `README.md` reste le handoff canonique de l'état courant. Ce registre conserve la cartographie durable des capacités, y compris lorsqu'elles vivent uniquement dans V5, une branche shadow, une PR fermée/superseded ou un ancien benchmark.
>
> Avant toute nouvelle implémentation : lire le README, puis ce registre, puis inspecter les PR/branches/modules cités. **Réutiliser ou backporter le travail validé avant d'en écrire un équivalent.**

Dernier audit global : **17 août 2026**.

## 1. Statuts

| Statut | Sens |
|---|---|
| `PROD_V4` | présent dans `main` et utilisé par la production V4 |
| `MAIN_SUPPORT` | présent dans `main`, mais support/diagnostic/shadow, pas décision économique production |
| `V5_ONLY` | présent dans la ligne V5 expérimentale / PR #8, pas dans V4 production |
| `SHADOW` | implémenté et validé, volontairement non production |
| `DEFERRED` | travail valide conservé, intégration volontairement reportée |
| `BENCHMARK` | outil/résultat de comparaison à réutiliser, pas une source production |
| `SUPERSEDED` | ne pas reprendre comme base ; une implémentation ultérieure fait autorité |
| `DISABLED` | code éventuellement conservé, comportement volontairement désactivé en production |

## 2. Règle anti-réimplémentation

Pour toute mission non triviale :

1. rechercher la capacité et ses synonymes dans `README.md` et ce registre ;
2. rechercher les PR, branches et commits GitHub qui ont traité le même besoin ;
3. inspecter `main`, V5, Robot KB/Neon et les branches `SHADOW/DEFERRED/BENCHMARK` pertinentes ;
4. suivre les chaînes de supersession ;
5. partir de la version compatible la plus récente et déjà validée ;
6. préférer réutilisation/backport/adaptation à une seconde implémentation indépendante ;
7. si une réécriture reste nécessaire, documenter pourquoi l'ancienne version est incompatible ou insuffisamment sûre ;
8. après validation, enregistrer ici PR, SHA, tests/runs, statut, déploiement et successeur éventuel.

Une PR fermée ou non mergée n'est pas automatiquement du travail perdu. Une branche `SHADOW`, `DEFERRED`, `BENCHMARK` ou `V5_ONLY` peut contenir l'implémentation de référence à reprendre plus tard.

---

# 3. Identité canonique, TCGdex et microvariantes

## 3.1 V5 : architecture d'identité déjà construite

### TCGdex multilingue primaire

**Statut : `V5_ONLY`.**

Origine : PR #7, puis durcissements #31, #36, #38-#44, #81, #85-#88 et #93.

Modules actuels à inspecter avant toute nouvelle logique d'identité :

- `v5/card_identity_catalog.py`
- `v5/card_identity_uniqueness.py`
- `v5/microvariant_detector.py`
- `v5/microvariants.py`
- `v5/variant_semantics.py`
- `v5/detailed_identity_observability.py`
- `v5/emergency_identity_fallback.py`
- `v5/robot_kb_identity_cache.py`

Principe durable : **TCGdex est l'autorité normale d'identité catalogue en V5. PokeTrace n'est pas l'autorité normale d'identité.**

### PR #31 — unicité déterministe « two-of-three »

**Statut : `V5_ONLY`, capacité à backporter lorsque V4 en a besoin.**

Validation historique : run `31542551507` ; V5 `463/463`, V4 `169/169`, compile/YAML/diff PASS, aucun live.

Règles déjà prouvées :

- nom exact + numéro imprimé complet `x/y` -> récupérer le set seulement si un seul macro-card TCGdex compatible subsiste ;
- set exact + nom exact -> récupérer le numéro seulement si ce set contient une seule carte de ce nom exact ;
- une seule coordonnée ne suffit jamais ;
- numéro sans dénominateur ne récupère pas un set par cette voie ;
- deuxième candidat, overflow, conflit de dénominateur, collision de set ou variante impossible -> fail-closed ;
- preuve macro uniquement : elle ne prouve pas First Edition, Unlimited, Shadowless, holo/reverse, promo, stamp ou special finish.

Leçon historique : V4 a ensuite réparé plusieurs `CLEAN_NO_MATCH` par #119-#121 alors qu'une partie de l'architecture générique existait déjà dans V5.

### PR #36 — premium variant evidence

**Statut : `V5_ONLY`; principe également présent dans les gates V4 actuelles.**

Une metadata provider/candidate ne peut jamais fabriquer une variante premium du listing. Absence de preuve de la dimension cible = ambigu/blocking, pas `STRONG_MATCH`.

### PR #38 / #39 — extraction déterministe des coordonnées

**Statut : `V5_ONLY`.**

Réutiliser ces parsers/tests avant d'en recréer :

- rejet précoce des lots/multi-cartes ;
- codes `sv2a`, `SVP`, `CS4.1C`, `Journey Together` ;
- formes inversées comme `169/165 SV2a` ;
- un code `SV*` explicite ne peut raffiner qu'un parent structuré Scarlet & Violet générique, jamais écraser un set spécifique ;
- PR #39 : `509` tests PASS.

### PR #40 / #41 / #44 — post-macro et finish exact

**Statut : `V5_ONLY`; plusieurs principes ont déjà un équivalent V4.**

Déjà construit :

- `Features` eBay traité comme dimensions additives ;
- retry post-macro TCGdex par nom exact + numéro complet unique ;
- cohérence obligatoire avec le macro-set déjà résolu ;
- provenance provider insuffisante pour débloquer une microvariante ;
- finish exact catalogue utilisable uniquement si TCGdex prouve une variante détaillée simple et unique ;
- multi-finish/stamped/language-specific reste fail-closed ;
- parser finish eBay par span-masking pour éviter les faux conflits de tokens résiduels.

Validation historique : #40 `519` tests ; #41 `523` tests.

Avant tout port V4, inspecter `v4_multimarket_safety.py` : certaines gates y existent déjà.

### V5 visual identity / OCR / forensic microvariants

**Statut : `V5_ONLY/BENCHMARK`; actif historique à conserver.**

Des modules et tests dédiés existent sur la ligne V5/source-scout :

- `v5/visual_identity.py`
- `v5/card_number_ocr.py`
- `tests_v5/test_visual_identity.py`
- `tests_v5/test_card_number_ocr.py`
- `tests_v5/test_forensic_microvariants.py`
- `tests_v5/test_local_microvariant_detector.py`

Ne pas recréer une nouvelle couche OCR/visuelle V5 sans d'abord auditer ces actifs. Toute preuve visuelle doit rester secondaire/fail-closed et ne doit jamais remplacer les coordonnées catalogue déterministes lorsqu'elles existent.

### PR #81 — observabilité détaillée identité

**Statut : `V5_ONLY`, passif.**

Validation : run `31898349431`, `569/569` V5 PASS, compile/diff PASS, aucun secret/live.

Déjà disponible : diagnostics par record TCGdex/fallback, stratégies PokeTrace, raisons bornées de rejet, diagnostic visuel passif, catégories `AMBIGUOUS` / `INSUFFICIENT` / `BLOCKED_VARIANT`.

### PR #85 / #86 / #88 — politique de fallback V5

**Statut : `V5_ONLY`, autorité actuelle pour la politique normale/urgence.**

- #85 : PokeTrace devient market-only en régime normal ; validation `572/572`.
- #86 : identité PokeTrace seulement après vraie panne technique TCGdex ; validation `579/579`.
- #88 : cache TCGdex prouvé Robot KB/Neon avant Pokémon TCG API, puis PokeTrace emergency-only ; validation `585/585`.

Déclencheurs d'urgence TCGdex autorisés : transport, JSON invalide, HTTP `408/425/429/5xx`.

Ne déclenchent pas l'urgence : `CLEAN_NO_MATCH`, `404`, autres `4xx` non transients.

Ordre d'urgence canonique :

```text
TCGdex live
-> cache TCGdex prouvé Robot KB/Neon
-> Pokémon TCG API
-> PokeTrace emergency-only
-> fail closed
```

Le cache seul ne prouve jamais First Edition/Unlimited/Shadowless/finish/stamp/promo. Plusieurs IDs actuels pour la même clé = `AMBIGUOUS`.

### PR #93 — applicabilité exacte / promos / `wPromo`

**Statut : `V5_ONLY`, mergée dans V5.**

Head V5 contenant cette ligne : `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f`.

Validation offline `600/600`. Live contrôlé `31916052221` SUCCESS : 17 requêtes TCGdex, 2 hits, 0 variant-impossible, Robot KB 1 insert + 1 idempotent, aucune transaction.

À conserver :

- retry exact post-macro réellement câblé ;
- mappings versionnés de namespaces promo ;
- normalisation leading-zero seulement dans namespaces prouvés ;
- `wPromo` TCGdex signifie **W stamp**, pas « promo générique » ;
- `dpp-DP45` / Charizard G est un cas end-to-end prouvé.

### PR #96 — trous catalogue physiques / Pocket digital

**Statut : `DEFERRED`, draft V5, non mergée.**

Validation offline `611/611`.

Travail déjà construit : rejet déterministe de Pokémon TCG Pocket digital dans le pipeline physique et petit registre versionné de trous catalogue physiques, dont Magikarp coréen `040/M-P` 2026. Aucune règle blanket « TCGdex miss => accept ».

Ne pas recréer ce registre ailleurs avant décision explicite sur #96.

## 3.2 V4 : chaîne TCGdex réelle

### PR #33 — canonical TCGdex + multi-market

**Statut : `PROD_V4`.** Validation historique `304/304`.

Base V4 : nom localisé + localId, dénominateur, exact-set fallback, puis providers de marché indépendants.

### PR #35 — cache / normalisation / erreurs

**Statut : `PROD_V4`.** Validation `313` tests.

Déjà fait :

- `004/102 == 4/102` pour la coordonnée numérique ;
- dénominateur conservé dans la clé de cache ;
- `429/5xx` != clean no-match ;
- pas de cache poisoning par transient ;
- réduction des doubles appels réseau.

### PR #117 / #118 — observabilité TCGdex V4

**Statut : `PROD_V4`; #118 fait autorité.**

Validation #118 : `607/607`, compile/YAML/diff/discovery PASS.

Root cause déjà résolue : un installer downstream remplaçait `watcher.process_external_market_candidates` et supprimait le wrapper diagnostics. L'observabilité doit être installée après les wrappers susceptibles de remplacer ce processeur.

### PR #119 — coordonnées exactes run 1037

**Statut : `PROD_V4`.**

Pin source : `tcgdex/cards-database@af33c9ac882e2acfadffaf19e8083aa976d12983`.

10 cas versionnés : 8 labels japonais romanisés/localisés + Trainer Gallery FR + Celebrations Classic Collection FR. Registre exact borné, jamais fuzzy.

### PR #120 — récupération généralisée set/localId

**Statut : `PROD_V4`.** Validation `627/627`, compile/YAML/diff + discovery read-only PASS.

Déjà fait : alias de set exact GCC -> ID TCGdex, namespaces promo exacts, suffixes d'affichage bornés `Holo` / `Gold`, preuve set ID + localId + cardCount/dénominateur, transient -> `ERROR`.

### PR #121 — aliases run 1054

**Statut : `PROD_V4`, mergée sur main le 17/08/2026.**

Sept aliases exacts supplémentaires, sans fuzzy. À conserver comme fast paths/versioned compatibility, mais pas comme modèle de maintenance run-après-run.

### PR #122 — fallback par coordonnée unique

**Statut : `DEFERRED`, PR ouverte/non mergée lors de l'audit.**

Head audité `e8f00ef1cd36059ba08e8c7a27a18eb8183cdd18`.

CI `32032879591` : `650/650`, compile/YAML/diff + discovery read-only PASS.

Apports :

- dénominateur numérique -> index complet des sets puis exact cardCount + exact localId, unicité globale obligatoire ;
- namespace non numérique -> set ID exact + localId exact ;
- localId alphanumérique sans dénominateur -> unicité globale obligatoire ;
- bridge script JA/KO/ZH/TH seulement après coordonnée globalement unique ;
- réponse provider incomplète nécessaire à la preuve -> `ERROR` ; plusieurs candidats -> `AMBIGUOUS`.

Limite auditée : #122 ne récupérait pas tout #31, surtout `set exact + nom exact -> numéro manquant`.

### PR #123 — récupération historique + registre durable

**Statut : `DEFERRED` jusqu'à CI/revue/autorisation de merge.**

Branche : `fix/v4-recover-existing-capabilities-20260817`.

Objectif : conserver #119/#120/#121 comme fast paths, backporter #31 « two-of-three », puis laisser le fallback #122 en dernière position. Aucun relâchement microvariante/économie.

---

# 4. RAW consensus et price discovery multi-grader

### Merge production `8a61a6a5ec8740b9b8413cc82de26f11db064c43`

**Statut : `PROD_V4`.**

Commit de merge : `merge(v4): promote robust raw consensus to production`.

C'est un actif majeur qui existait déjà avant cet audit. Ne pas recréer un second moteur RAW/secondary-grader parallèle.

Modules actuels :

- `v4_raw_consensus.py`
- `v4_price_discovery.py`

Historique de durcissement avant merge : implémentation du consensus, wiring manual-review-only, durcissement pricing/evidence, rebase des ventes stale de grader secondaire, ratios historiques date-matched et red-team hardening.

## 4.1 `v4_raw_consensus.py`

Le moteur couvre conceptuellement Cardmarket, JustTCG, TCGplayer, PriceCharting et eBay RAW. En production, Cardmarket/TCGplayer attachés à l'identité TCGdex alimentent le consensus ; JustTCG/PriceCharting/eBay RAW restent adaptateurs diagnostics/offline sauf câblage ultérieur explicitement validé.

Règles déjà implémentées :

- RAW != valeur d'un slab gradé ;
- RAW ne crée pas `max_recommended` ;
- RAW est revue manuelle/price-discovery, pas achat/bid automatique ;
- parsers multilingues d'édition/finish/special finish ;
- dimensions `PROVIDER_PROVEN`, `CATALOG_PROVEN`, `UNKNOWN` ;
- une dimension requise `UNKNOWN` exclut la source du quorum fort ;
- reason codes standardisés dont `EXACT_COMPATIBLE`, `LANGUAGE_MISMATCH`, `SET_MISMATCH`, `NUMBER_MISMATCH`, `FINISH_MISMATCH`, `EDITION_MISMATCH`, `PROMO_MISMATCH`, `OUTLIER_CONTAMINATION`, `PROVIDER_DISAGREEMENT`, `INSUFFICIENT_IDENTITY` ;
- anti-outlier et disagreement inter-provider ;
- deux fournisseurs incomplets ne peuvent pas fabriquer un consensus `STRONG`.

## 4.2 `v4_price_discovery.py`

**Statut : `PROD_V4` pour le moteur ; certains signaux restent diagnostic/manual-review selon le flux.**

Déjà construit :

- `CROSSGRADE_OPPORTUNITY` ;
- `SECONDARY_GRADER_DISCOUNT` ;
- `ILLIQUID_PRICE_DISCOVERY` ;
- ancres adjacentes structurées ;
- incertitude explicite ;
- active asks seules ne créent jamais d'opportunité ;
- ancre trans-linguistique downweightée et incertitude accrue ;
- low grade ne peut pas utiliser naïvement PSA10 sans échelon intermédiaire.

### Ajustement temporel cross-grader

Cette logique résout précisément le cas « ancienne vente SGS/secondary grader alors que le marché PSA a depuis bougé ».

Le moteur ne compare pas naïvement une vieille vente secondaire au PSA actuel. Il :

1. cherche une vente historique du grader cible ;
2. l'associe à une référence historique du grader de référence au même grade et proche dans le temps ;
3. calcule le ratio historique cible/référence ;
4. applique ce ratio historique à la valeur robuste récente du marché de référence ;
5. conserve le spread propre au grader et l'incertitude ;
6. fail-closed en l'absence de ratio historique défendable.

`pair_date_matched_historical_ratios` impose un appariement temporel borné ; `evaluate_temporal_cross_grader_adjustment` réalise le rebase actuel.

Hiérarchie documentée :

```text
EXACT_RECENT_COMP
> EXACT_OLD_COMP_TEMPORALLY_ADJUSTED
> CROSS_GRADER_ESTIMATE_ONLY
> MANUAL_REVIEW_NO_ESTIMATE
```

Ne pas réimplémenter cette logique dans Edge Hunter, Robot KB ou un provider adapter séparé.

---

# 5. PokeTrace et providers de marché

## PokeTrace V4 multi-market

**Statut : `PROD_V4` via #33 + durcissements ultérieurs.**

Invariants : identité commerciale exacte, grader/grade exacts, provider unavailable/pending/rate-limit distincts, absence de provider != faible valeur, premium metadata provider ne crée pas variante listing, RAW ne devient jamais valeur slab.

PokeTrace n'écrase pas APR/eBay ; les providers doivent rester indépendants lorsqu'ils peuvent l'être.

## PokeTrace V5 normal/emergency

**Statut : `V5_ONLY`, autorité = #85/#86/#88.**

Ne pas recréer une autre politique de fallback concurrente.

---

# 6. PokemonPriceTracker (PPT)

PPT a plusieurs lignes déjà construites. Ne jamais repartir de zéro.

### PR #92 — identité shadow V5

**Statut : `V5_ONLY/SHADOW`.**

Validation `592/592`; live shadow `31914845846` : 12 appels / 120 crédits, 5 candidats set uniques diagnostiques, aucune modification identité/microvariante/valorisation.

Conclusion : bon retrieval/helper potentiel, pas autorité automatique d'identité.

### PR #90 -> PR #106

**Statut : #90 `SUPERSEDED`; #106 = `SHADOW/DEFERRED` et implémentation PPT V4 à reprendre.**

#106 est le remplacement propre basé sur un `main` plus récent. Scope graders supportés : PSA/BGS/CGC/SGC. Aucun effet production automatique. Si PPT doit être intégré économiquement, repartir de #106, pas #90.

### Japan Edge PPT : #95 -> #105 -> #107

**Statut : #95 `SUPERSEDED`, #105 `SUPERSEDED`, #107 = `SHADOW/DEFERRED`.**

#107 conserve GCC et PPT séparés dans la présentation après la décision Japan Edge existante. PPT ne crée/supprime pas l'opportunité et n'est pas silencieusement blended avec GCC.

---

# 7. Source Scout / benchmark des APIs et marchés

### Branche `agent/source-scout-benchmark-20260814`

**Statut : `BENCHMARK/DEFERRED`, ne pas recréer.**

Head vérifié : `46f5cc3e1f0b1e041815497d432be62a16a42e31`.

Cette branche contient une quantité importante de travail de benchmark qui n'est pas visible sur `main` :

- `.github/workflows/source-scout-provider-benchmark.yml`
- `v5/source_scout_benchmark.py`
- `v5/source_scout_entrypoint.py`
- `v5/source_scout_language_entrypoint.py`
- `v5/source_scout_opportunity_benchmark*.py`
- `v5/source_scout_opportunity_ppt_validation*.py`
- `v5/source_scout_paid*_entrypoint.py`
- `v5/source_scout_cmapi*_entrypoint.py`
- `v5/source_scout_cmapi_liquid_sentinel.py`
- `v5/source_scout_pokemon_tcg_rapidapi_probe.py`
- `v5/source_scout_ebay_asp_rapidapi_probe.py`
- `v5/source_scout_ebay_asp_search_probe.py`
- `v5/ebay_asp_basic_policy.py`
- `v5/neon_source_scout_ingest*.py`
- tests `tests_v5/test_source_scout_*`
- `docs/source_scout_ebay_asp_basic.md`
- `docs/ebay_marketplace_insights_support_ticket_draft.md`

Historique de commits : probes RapidAPI Pokémon TCG, corrections de quota/validation PPT, rescues d'unicité Cardmarket API, eBay ASP sold/search, policy Basic quota-aware et draft d'accès Marketplace Insights.

### JustTCG

**Statut : `BENCHMARK`, pas autorité.**

Ancien benchmark exact set-aware : **0/20 exacts**. Certaines cartes étaient retrouvables mais dimensions d'identité insuffisantes/ambiguës. Il existe aussi `v5/justtcg_identity.py` et des tests sur la branche historique.

Ne pas promouvoir JustTCG comme identité exacte sans nouveau benchmark qui démontre les dimensions nécessaires.

### eBay ASP / RapidAPI

**Statut : `BENCHMARK/SAFE-OFF`.**

Les probes et policy Basic existent déjà. Le search live testé a notamment renvoyé `404` dans le chemin étudié ; cela a été traité safe-off, pas comme une source SOLD production fonctionnelle.

### Marketplace Insights

**Statut : `DEFERRED` accès externe.**

Le draft de ticket d'accès est déjà dans la branche source-scout. Ne pas réécrire la demande de zéro ; reprendre le document et l'état d'éligibilité actuel.

---

# 8. V4 multi-market / arbitrage externe / queue

### PR #29 -> #33

#29 est le précurseur de l'external-market-before-terminal-reject. #33 absorbe la ligne production.

**#33 Statut : `PROD_V4`.**

Pipeline : GCC listing -> identité TCGdex -> PokeTrace exact graded / PSA APR / eBay SOLD / RAW -> arbitrage par force de preuve.

Chemins historiques à conserver : `GCC_ONLY`, `GCC_EXTERNAL_CONFIRMED`, `EXTERNAL_RESCUE`, `EXTERNAL_PENDING`, `MARKET_CONFLICT_BLOCKED`.

### PR #32 / #46 — PSA APR web

**Statut : `PROD_V4`.**

#32 gère l'hydration client-rendered avec attentes bornées. #46 distingue HTTP 403/429/5xx et challenges anti-bot avant de conclure « formulaire absent ». Aucun contournement WAF/CAPTCHA.

### PR #43 / #47 / #77 / #116 — budgets et file externe

**Statut : `PROD_V4`.**

Déjà résolu :

- fixed ne doit pas être affamé par les auctions ;
- refresh adaptatif fixed proche du seuil ;
- priorité intelligente lorsque le budget provider est rare ;
- `PENDING_BUDGET` = pression de scheduling, pas panne provider ;
- backoff long réservé aux vrais transients/errors ;
- ordering auction ending-soon préservé.

Modules actuels à auditer avant une nouvelle queue : `v4_external_coverage_drain.py`, `v4_smart_external_priority.py` et la queue/state du watcher.

---

# 9. GCC discovery / auctions / Fast Lane

### PR #9 — discovery item-level

**Statut : `PROD_V4`.**

API `/on-sale-items`, `sellingTypeGroup=AUCTION`, `ENDING_SOON`, `endTime` individuel ; fallback legacy quand la couverture ne peut pas être prouvée. `COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS` ne signifie pas couverture absolue de tout GCC.

### PR #50 / #52 — private safety net

**Statut : `PROD_V4`.**

Le safety net private-auction existe déjà et son accounting est isolé du ledger API primaire.

### PR #103 -> #104 — pagination live

**Statut : #103 `SUPERSEDED`; #104 `PROD_V4`.**

#104 stabilise le drift `ENDING_SOON` par snapshots ancrés/répétés, union bornée, puis fail-closed vers legacy si non stabilisé.

### PR #30 -> #45 — Fast Lane finale

**Statut : #30 `SUPERSEDED`; #45 `PROD_V4`.**

Architecture zéro-sleep avec workflow final séparé. Ne pas réintroduire le long `sleep` du prototype #30.

### PR #55 — identité du lot final

**Statut : `PROD_V4`.**

Le recheck final doit conserver l'identité commerciale exacte ; un URL déjà connu ne suffit pas à relâcher les gates.

---

# 10. ASK / SOLD / Structural Edge Hunter

### PR #78 — eBay BIN active ASK

**Statut : `PROD_V4`.**

ASK uniquement comme contexte pour une opportunity déjà retenue ; ASK ne crée jamais l'opportunity, n'entre jamais dans SOLD/comps/FV/max, et doit rester explicitement `ASK, PAS UNE VENTE`.

### PR #79 — stale listing / momentum / KB analytics

**Statut : `PROD_V4` pour les signaux câblés.**

Information/priorité seulement, ne crée pas une opportunity et ne modifie pas FV/max.

### PR #80 — Structural Edge Hunter V2

**Statut : `PROD_V4`.** Validation `571/571`, compile + discovery read-only PASS.

Détecteurs déjà existants :

- cross-market lag sur SOLD gradés exacts récents ;
- grader lag avec spread historique prouvé ;
- stale seller repricing si vendeur explicite ;
- liquidity breakout ;
- relative-grade anomaly même grader ;
- same-card inventory anomaly via asks exacts + SOLD ;
- Expected Profit secondaire/ranking-only, jamais suppressif.

Ne pas créer un deuxième Edge Hunter parallèle avant d'auditer `v4_structural_edge_hunter.py` et `v4_price_discovery.py`.

### PR #84 / #87

#84 `PROD_V4` : garde de qualité des notifications, notamment RAW seul ne crée pas une opportunity slab.

#87 : travail fermé/draft autour du seuil illiquid GCC-only. Ne pas le présenter comme prod sans vérifier le code courant.

---

# 11. Japan Edge

### PR #89 — Japan Edge Hunter

**Statut : `PROD_V4`, lane séparée.**

Japanese Pokémon individual cards, PSA10, asks Mercari/magi/Yahoo-Flea comparés à des GCC SOLD exacts. Les asks ne deviennent jamais fair value.

Live historique `31914421575` : 2 000 GCC SOLD, 341 éligibles, 59 groupes exacts, 328 asks observés, 1 lead exact, 0 provider error.

### PR #94 — contexte global exact SOLD

**Statut : `PROD_V4`.**

PokeTrace exact JP PSA10 + eBay SOLD exact + PSA APR si langue prouvée ; PokeTrace et eBay restent la même famille corrélée quand ils représentent le même marché eBay. Absence externe != preuve négative.

### PR #101 — présentation comparative

**Statut : `PROD_V4`, mergée.**

Notification sépare coût rendu Japon, GCC exact JP PSA10, marché externe exact, fair multi-marché et verdict. Présentation seulement.

### PPT Japan Edge

Voir chaîne #95 -> #105 -> #107. Reprendre #107 si cette couche est réactivée.

---

# 12. Global multi-vault : GCC / Cardova / magi / Fanatics / COMC

Cette architecture a déjà été construite. Ne pas repartir d'une feuille blanche.

### PR #108 — fondation globale

**Statut : `SHADOW/DEFERRED`.**

Validation `31953479268` : `27/27` global-market + `51/51` V4 multimarket, compile/YAML/diff PASS.

Actifs à reprendre depuis la stack :

- `v4_global_market_core.py`
- bridges PPT/PokeTrace agrégés
- `v4_market_cardova.py`
- `v4_market_gcc_bridge.py`
- `v4_market_magi_bridge.py`
- `v4_market_fanatics_bridge.py`
- `v4_market_comc_bridge.py`
- `v4_market_verified_offer.py`

Contrat déjà conçu : identité commerciale stricte ; EN + JAP prioritaires ; FR collectable mais non notif tant que profondeur SOLD insuffisante ; `SOLD_EXACT` distinct de `SOLD_AGGREGATED` ; PPT/PokeTrace corrélés ; ASK/current auction hors fair value ; snapshot <=5m reste snapshot, jamais SOLD ; frais/all-in inconnus -> fail-closed.

### PR #109 — live shadow multi-vault

**Statut : `SHADOW/DEFERRED`.**

Live `31954247131` SUCCESS : 5 identités JP PSA10 ; GCC 1 600 candidats / 6 exacts ; magi 35/0 ; Fanatics 24/0 ; COMC 2/0 ; Cardova = `AUTH_SESSION_INPUT_REQUIRED`. Aucun ntfy/Neon/transaction. Offline `34/34 + 51/51`.

### PR #110 / #113 / #114 / #115

**Statut : `SHADOW/DEFERRED`, chaîne de durcissement.**

- #110 : diagnostics de rejet par provider ;
- #113 : retrieval hardening magi/Fanatics/COMC ;
- #114 : pages magi explicitement SOLD rejetées de la lane ASK ;
- #115 : route COMC exact set facet / exact set+localId.

Toujours repartir de la dernière version compatible de cette stack.

### PR #112 — dispatcher manuel sur main

**Statut : `MAIN_SUPPORT`, mergée.**

`main` expose le workflow manuel `V4 Global Market Live Shadow`, mais n'embarque volontairement pas tous les scanners globaux. L'absence d'un module global sur `main` ne signifie donc pas que le travail n'a jamais existé.

---

# 13. Robot KB / Neon

Robot KB est l'architecture durable séparée de collecte historique. Ne pas recréer un historique ad hoc dans V4/V5.

### PR #49 / #51 — miroir passif discovery

**Statut : architecture historique de séparation.**

V4 observe les réponses GCC déjà fetchées, sans appels commerciaux supplémentaires ; artifact court ; writer Neon séparé ; V4 ne reçoit pas le secret Neon ; auction near-final = `LISTING_SNAPSHOT`, jamais SALE.

### PR #59 / #60 — GCC SOLD explicite

**Statut : déployé.**

`SALE_TRANSACTION` seulement si top-level `status=SOLD`, `soldAt` timezone-aware valide et prix final positif. `ENDED` ou absence `soldAt` reste snapshot.

### PR #61 -> #62 — fixed rotation

**Statut : #61 `SUPERSEDED`; #62 autorité.**

Rotation durable fixed, curseur avance seulement après fetch complet + ingest Neon réussi, safe wrap. #62 : `468` tests.

### PR #68 — SOLD lossless watermark

**Statut : déployé.**

Watermark `soldAt` + IDs frontière, backlog durable, plafond 400 = débit et non couverture, état avance seulement après ingest réussi, contrat/HTTP/état corrompu fail-closed.

### PR #72 — lane SOLD 30 min

**Statut : déployé.**

SOLD séparé toutes les 30 min ; fixed/auction horaire ; concurrency Neon commune avec `cancel-in-progress:false`.

### PR #75 — fixed hybrid coverage

**Statut : déployé.**

Jusqu'à 100 recent + 200 rotation + 100 ciblées/run, paramètres GCC GET-only vérifiés, dedupe avant ingest, état avance après succès Neon.

### PR #76 — backfill historique SOLD

**Statut : déployé/actif selon workflow courant.**

Backfill durable séparé de la fresh lane, page search borné, <=400/run, gestion des ventes partageant le même `soldAt`, contrat SOLD strict.

### Analytics

`robot_kb_roi_analytics.py` existe en read-only. Les ratios appris ne doivent pas devenir heuristiques automatiques sans phase dédiée et validation.

---

# 14. Certificats, Mislisted Slab et OCR

Cette zone a déjà eu plusieurs faux positifs. Ne pas réactiver/réécrire sans relire toute la chaîne.

### PR #64 / #65

Adapters cert-first étendus puis durcissement PSA/PCA/CCC. Official cert > OCR. Subgrades exclus. OCR par consensus. `IMAGE_ONLY` = revue manuelle, jamais preuve économique automatique.

Benchmark #65 : 24 slabs, 4 exact, 0 wrong, 12 ambiguous, 8 unavailable = 100 % parmi les lectures OCR acceptées, pas 100 % des slabs.

### PR #66 / #67 / #69 / #71 / #73

Historique :

- #66 : revue manuelle seulement si vraie opportunity ;
- #67 : mode cert-problem haute sensibilité ;
- #69 : hotfix safe-off après spam faux `CERT NUMBER MISSING` ;
- #71 : cert GCC structuré préservé ; diagnostic 100 cartes = API cert 100/100, collapsed inspection le perdait 100/100, Description->Gradation récupérait 100/100 ;
- #73 : failures techniques cert lookup = log-only, pas ntfy.

### PR #103 -> #104

**Statut final production : `DISABLED` pour Mislisted Slab/OCR.**

#104 garde la lane hard-disabled en V4 après faux positifs. Le code historique reste diagnostic, pas une fonctionnalité à réactiver implicitement.

---

# 15. Workflows, scheduling et observabilité

### Scheduler V4

La production utilise l'ordonnancement externe existant vers `workflow_dispatch`. Ne pas ajouter un `schedule:` GitHub parallèle qui doublerait les scans.

### PR #13 — cache Playwright

**Statut : `PROD_V4/MAIN_SUPPORT`.**

Optimisation déjà faite. Ne pas recréer une seconde installation/cache Chromium parallèle sans audit.

### Issue #1

Journal durable des runs V4. Conserver discovery mode/scope/timers/fallback séparés de la couverture économique.

### V5 workflows

`V5 Live Raw Pipeline Diagnostic` est manuel uniquement. `V5 Offline Validation` existe pour tests sans secrets/providers live. PR #24 avait déjà supprimé des diagnostics redondants couverts par les outils consolidés.

---

# 16. Chaînes de supersession connues

| Ancien | Autorité / successeur | Instruction |
|---|---|---|
| PR #30 final-auction long-wait | PR #45 Fast Lane | ne pas reprendre #30 |
| PR #61 Robot KB mélange fixed/SOLD | #62 puis #68/#72/#75/#76 | reprendre la chaîne durable |
| PR #67 cert high-sensitivity | #69/#71/#73 puis #104 disabled | ne pas réactiver #67 |
| PR #90 PPT V4 | PR #106 | reprendre #106 |
| PR #95 Japan PPT | #105 puis #107 | reprendre #107 |
| PR #105 Japan PPT | PR #107 | #105 obsolète |
| PR #103 pagination/mislisted | PR #104 | reprendre #104 |
| anciens workflows V5 redondants | PR #24 + V5 Live RAW/Offline | ne pas les recréer |
| seuls aliases TCGdex #119-#121 | #31 V5 + #122 + PR #123 | préférer architecture générique, garder aliases prouvés en fast paths |

---

# 17. Séparation des architectures

Ne jamais fusionner implicitement :

- **V4 production** : décisions/notifications GCC canonique ;
- **V5 / PR #8** : expérimental ; jamais merger dans main sans autorisation explicite ;
- **Robot KB/Neon** : historique durable, séparé de la décision commerciale V4 ;
- **Global multi-vault #108-#115** : shadow ;
- **PPT #92/#106/#107** : shadow/helper selon lane, pas autorité automatique ;
- **Source Scout** : benchmark provider ;
- **Mislisted Slab/OCR** : code historique, production hard-disabled.

---

# 18. Benchmarks à ne pas mal interpréter

- Aucun benchmark vérifié retrouvé prouvant **TCGdex 500/500**.
- Cert visibility #71 : **100/100** concernait les certificats GCC et le fallback Description->Gradation, pas TCGdex.
- OCR #65 : **100 % parmi lectures acceptées** = 4 exact / 0 wrong, mais 12 ambiguous + 8 unavailable sur 24.
- Les suites `509`, `519`, `523`, `569`, `600`, `650`, etc. sont des **tests logiciels**, pas des panels live de centaines de cartes TCGdex.
- JustTCG : ancien benchmark set-aware **0/20 exacts** ; ne pas le confondre avec une couverture catalogue.

Toute future revendication « 100 % de couverture » doit enregistrer : population exacte, source, méthode de sélection, langues, définition de `EXACT`, exclusions, ambiguïtés, errors, run ID et SHA.

---

# 19. Format obligatoire pour toute nouvelle capacité

Après une phase importante validée, enregistrer au minimum :

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
Live run(s): none | run IDs + scope exact
Production deployment: yes/no + merge SHA
Supersedes:
Superseded by:
Reuse instruction:
```

Une phase n'est pas complètement archivée tant que `README.md` + ce registre permettent à un nouvel agent de savoir immédiatement si le travail existe déjà, où il se trouve, s'il est production/shadow/V5-only/superseded et quelle version doit être réutilisée.
