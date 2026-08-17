# Robot Pokémon / GCC Auction Watcher — registre durable des capacités

> **But : empêcher qu’une fonctionnalité déjà construite soit réécrite faute de mémoire.**
>
> Ce registre complète `README.md`. Le README reste le handoff canonique de l’état courant ; ce fichier conserve la cartographie durable des capacités, des PR/branches qui les portent, de leur statut de déploiement, de leurs validations et des chaînes de supersession.
>
> Avant toute nouvelle implémentation : lire le README, puis chercher ici la capacité et ses synonymes, puis inspecter les PR/branches/modules cités. **Réutiliser ou backporter le travail validé avant d’en réécrire un équivalent.**

Dernier audit global : **17 août 2026**.

## 1. Statuts utilisés

| Statut | Sens |
|---|---|
| `PROD_V4` | présent dans `main` et utilisé par la production V4 |
| `MAIN_SUPPORT` | présent dans `main`, mais support/diagnostic/shadow, pas décision économique production |
| `V5_ONLY` | présent dans la branche V5 expérimentale / PR #8, pas dans V4 production |
| `SHADOW` | implémenté et validé, volontairement non production |
| `DEFERRED` | travail valide conservé, mais décision d’intégration reportée |
| `SUPERSEDED` | ne pas reprendre comme base : une implémentation ultérieure est l’autorité |
| `DISABLED` | code éventuellement conservé, mais comportement volontairement désactivé en production |

## 2. Règle anti-réimplémentation

Pour toute mission non triviale :

1. rechercher la capacité dans `README.md` et ce registre ;
2. rechercher les PR/branches GitHub par nom **et par synonymes fonctionnels** ;
3. inspecter le code courant de `main`, de V5 si pertinent et des branches `SHADOW/DEFERRED` citées ;
4. vérifier la chaîne de supersession ;
5. réutiliser/backporter la version la plus récente dont les invariants restent compatibles ;
6. si une réécriture est réellement nécessaire, documenter explicitement **pourquoi l’ancienne implémentation est incompatible** ;
7. après validation, mettre à jour ce registre avec PR, SHA, tests/runs, statut et successeur éventuel.

Une PR fermée ou non mergée n’est **pas** du travail perdu : si elle est marquée `SHADOW` ou `DEFERRED`, son code et ses tests sont des actifs à réutiliser.

---

# 3. Identité canonique / TCGdex / microvariantes

## 3.1 Architecture V5 déjà construite — ne pas réinventer

### TCGdex multilingue primaire

**Statut : `V5_ONLY`**  
**Origine : PR #7**, puis renforcements #31, #36, #38–#44, #81, #85–#88, #93.  
**Modules actuels V5 :**
- `v5/card_identity_catalog.py`
- `v5/card_identity_uniqueness.py`
- `v5/microvariant_detector.py`
- `v5/microvariants.py`
- `v5/variant_semantics.py`
- `v5/detailed_identity_observability.py`
- `v5/emergency_identity_fallback.py`
- `v5/robot_kb_identity_cache.py`

Principe durable : **TCGdex est l’autorité normale d’identité catalogue**. PokeTrace n’est pas une autorité normale d’identité.

### PR #31 — unicité déterministe « two-of-three »

**Statut : `V5_ONLY`, à backporter quand V4 a besoin de ce comportement.**  
Validation historique : run `31542551507` — V5 `463/463`, V4 `169/169`, compile/YAML/diff PASS, aucun live.

Règles déjà prouvées :
- nom exact + numéro imprimé complet `x/y` → récupérer le set **seulement si un seul macro-card TCGdex compatible subsiste** ;
- set exact + nom exact → récupérer le numéro **seulement si le set ne contient qu’une seule carte de ce nom exact** ;
- une seule coordonnée ne suffit jamais ;
- numéro sans dénominateur ne peut pas récupérer le set par cette voie ;
- deuxième candidat, overflow, conflit de dénominateur, collision de set ou variante impossible → fail-closed ;
- cette preuve est macro uniquement : elle ne prouve pas First Edition, Unlimited, Shadowless, holo/reverse, promo/stamp/special finish.

**Leçon :** les correctifs V4 par alias #119–#121 ont été nécessaires en partie parce que cette capacité validée était restée V5-only.

### PR #36 — premium variant evidence

**Statut : `V5_ONLY`; principe également présent matériellement dans les gates V4.**  
Une metadata candidate/provider seule ne peut pas fabriquer une variante premium. Absence de preuve cible = ambigu/blocking, pas STRONG_MATCH.

### PR #38 / #39 — extraction déterministe de coordonnées

**Statut : `V5_ONLY`; réutiliser les parsers/tests si un besoin V4 équivalent apparaît.**
- rejet précoce lots/multi-cartes ;
- codes `sv2a`, `SVP`, `CS4.1C`, `Journey Together` ;
- formes inversées `169/165 SV2a` ;
- `SV*` explicite peut raffiner uniquement un parent structuré générique Scarlet & Violet, jamais écraser un set spécifique ;
- #39 : `509` tests PASS.

### PR #40 / #41 — post-macro et finish exact

**Statut : `V5_ONLY`; une partie existe déjà sous forme équivalente dans `v4_multimarket_safety.py`.**
- `Features` eBay = dimensions additives, pas une variante scalaire ;
- retry post-macro TCGdex par nom exact + numéro complet unique ;
- cohérence obligatoire avec le macro-set déjà résolu ;
- provenance provider non probante pour débloquer microvariante ;
- finish catalogue exact ne peut débloquer que si TCGdex prouve une variante détaillée simple et unique ; multi-finish/stamped/language-specific reste fail-closed ;
- #40 : `519` tests ; #41 : `523` tests.

**Ne pas recopier mécaniquement dans V4 :** vérifier d’abord les gates déjà présentes dans `v4_multimarket_safety.py` (finish simple unique, First Edition applicability, premium provider non probant).

### PR #42 / #44

**Statut : `V5_ONLY`.**
- #42 : preuve exacte de set TCGdex + pruning des requêtes PokeTrace ;
- #44 : parsing déterministe des mentions de finish dans le titre eBay avec span masking, sans contradiction artificielle par token `holo` résiduel.

### PR #81 — observabilité identité détaillée

**Statut : `V5_ONLY`, comportement passif.**  
Validation : run `31898349431`, `569/569` V5 PASS, compile/diff PASS, aucun secret/live.

À réutiliser pour diagnostics V5 plutôt que recréer un logger d’identité :
- TCGdex / fallback par record ;
- PokeTrace par stratégie ;
- raisons bornées de rejet ;
- diagnostic visuel passif ;
- JSON structuré AMBIGUOUS / INSUFFICIENT / BLOCKED_VARIANT.

### PR #85 — PokeTrace market-only en régime normal

**Statut : `V5_ONLY`, politique canonique V5.**  
Validation : `572/572`.

Ordre normal : TCGdex + unicité déterministe → fallback catalogue autorisé. PokeTrace **ne reconnaît pas routinièrement la carte** et reste provider marché/prix.

### PR #86 — PokeTrace identité seulement en urgence technique TCGdex

**Statut : `V5_ONLY`, politique canonique V5.**  
Validation : `579/579`.

Déclencheurs autorisés : transport, JSON invalide, HTTP `408/425/429/5xx`.  
Ne déclenchent **pas** : CLEAN_NO_MATCH, `404`, autres `4xx`.  
Budget emergency borné, runtime/cache identité isolé du cache market.

### PR #88 — cache Robot KB/Neon d’identité TCGdex en outage

**Statut : `V5_ONLY`.**  
Validation finale historique : `585/585`.

Ordre d’urgence :
`TCGdex live -> cache TCGdex prouvé Robot KB/Neon -> Pokémon TCG API -> PokeTrace emergency-only`.

Le cache seul ne prouve jamais First Edition/Unlimited/Shadowless/finish/stamp/promo. Plusieurs IDs actuels pour une même clé => AMBIGUOUS.

### PR #93 — applicabilité exacte / promos / `wPromo`

**Statut : `V5_ONLY`, mergée dans V5 au head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f`.**  
Validation offline : `600/600`.  
Live contrôlé : run `31916052221` SUCCESS, 17 requêtes TCGdex, 2 hits, 0 variant-impossible, Robot KB 1 insert + 1 idempotent, aucune transaction.

À conserver :
- retry exact post-macro réellement câblé ;
- mappings versionnés de prefixes promo (DP/HGSS/BW/XY/SM/SWSH selon le module actuel) ;
- normalisation leading-zero uniquement dans ces namespaces prouvés ;
- `wPromo` TCGdex signifie **W stamp**, pas « carte promo générique » ;
- `dpp-DP45` / Charizard G est un cas end-to-end prouvé.

### PR #96 — trous catalogue physiques / TCG Pocket

**Statut : `DEFERRED`, draft V5, non mergée.**  
Validation offline : `611/611`.

Travail conservé :
- rejet déterministe de Pokémon TCG Pocket digital dans un pipeline physique ;
- petit registre versionné de trous catalogue physiques ;
- exemple sourcé : Magikarp coréen `040/M-P`, 2026, promo Holo ;
- aucune règle blanket « TCGdex miss => accept ».

Ne pas réimplémenter ce registre ailleurs avant décision explicite sur #96.

## 3.2 V4 TCGdex — chaîne réelle

### PR #33 — canonical TCGdex + multi-market

**Statut : `PROD_V4`.**  
Validation historique : `304/304`.

Base V4 : nom localisé + localId, dénominateur, exact-set fallback ; PokeTrace graded market, APR/eBay indépendants ; RAW Cardmarket/TCGplayer = signal RAW uniquement.

### PR #35 — cache et erreurs TCGdex

**Statut : `PROD_V4`.**  
Validation : `313` tests.

À ne pas refaire :
- normalisation numérique `004/102 == 4/102` ;
- clé de cache avec dénominateur ;
- `429/5xx` ≠ CLEAN_NO_MATCH ;
- pas de cache poisoning par erreur transient ;
- éviter les doubles appels réseau.

### PR #117 / #118 — observabilité TCGdex V4

**Statut : `PROD_V4`.**  
#118 est l’autorité finale. Validation #118 : `607/607`, compile/YAML/diff/discovery PASS.

Cause déjà résolue : un installer downstream remplaçait `watcher.process_external_market_candidates` et supprimait le wrapper de diagnostics. L’observabilité doit être installée **après tous les wrappers susceptibles de remplacer ce processeur**.

### PR #119 — registre exact de coordonnées run 1037

**Statut : `PROD_V4`.**  
Pin source : `tcgdex/cards-database@af33c9ac882e2acfadffaf19e8083aa976d12983`.

10 cas connus : 8 labels japonais romanisés/localisés incompatibles + Trainer Gallery FR + Celebrations Classic Collection FR. Registre exact borné, jamais fuzzy.

### PR #120 — récupération généralisée set/localId

**Statut : `PROD_V4`.**  
Validation : `627/627`, compile/YAML/diff + discovery read-only PASS.

Déjà fait :
- alias de set exact GCC → ID set TCGdex ;
- namespaces promo exacts ;
- suffixes d’affichage bornés `Holo` / `Gold` ;
- set ID + localId + dénominateur/cardCount doivent être prouvés ;
- transient → ERROR.

### PR #121 — aliases run 1054

**Statut : `PROD_V4`, mergée sur main le 17/08/2026.**

7 aliases exacts supplémentaires, toujours sans fuzzy. Ce correctif est conservé comme fast path/versioned compatibility, mais ne doit pas devenir le modèle de maintenance run-après-run.

### PR #122 — fallback par coordonnée unique

**Statut : `DEFERRED` au moment de cet audit ; PR ouverte, non mergée.**  
Head audité : `e8f00ef1cd36059ba08e8c7a27a18eb8183cdd18`.  
CI historique : run `32032879591`, `650/650`, compile/YAML/diff + discovery read-only PASS.

Apports :
- dénominateur numérique → index de sets complet puis exact cardCount + exact localId, unicité globale obligatoire ;
- namespace non numérique → set ID exact + localId exact ;
- localId alphanumérique sans denominator → unicité globale obligatoire ;
- pont script JA/KO/ZH/TH seulement **après** coordonnée globalement unique ; conflit même-script bloque ;
- réponse provider incomplète nécessaire à la preuve => ERROR ; plusieurs candidats => AMBIGUOUS.

Limite auditée : #122 ne récupérait pas toute la capacité historique de PR #31, notamment `exact set + exact name -> numéro manquant`.

### Backport de récupération historique — branche 17/08/2026

**Statut : `DEFERRED` jusqu’à CI/revue/autorisation de merge.**  
Branche : `fix/v4-recover-existing-capabilities-20260817`.

Objectif : conserver #119/#120/#121 comme fast paths, porter la logique V5 #31 « two-of-three », puis laisser le fallback #122 plus large en dernière position. Aucun relâchement microvariante/économie.

---

# 4. PokeTrace / providers de marché

## PokeTrace V4 multi-market

**Statut : `PROD_V4` via #33 + durcissements ultérieurs.**

Invariants déjà établis :
- exact commercial identity, grader/grade exacts ;
- PokeTrace n’écrase pas APR/eBay ;
- provider unavailable/pending/rate-limit gardé distinct ;
- absence provider ≠ faible valeur ;
- provider premium metadata ne crée pas la variante listing ;
- RAW ne devient jamais valeur d’un slab.

## PokeTrace V5 normal/emergency

**Statut : `V5_ONLY`, autorité = #85/#86/#88.**  
Ne pas recréer une autre politique de fallback concurrente.

---

# 5. PokemonPriceTracker (PPT)

PPT a déjà plusieurs lignes expérimentales ; **ne jamais repartir de zéro**.

### PR #92 — identité shadow V5

**Statut : `V5_ONLY/SHADOW`.**  
Validation `592/592`; live shadow `31914845846`: 12 appels / 120 crédits, 5 candidats set uniques diagnostiques, aucune modification identité/microvariante/valorisation.

Conclusion déjà prise : source de retrieval/helper prometteuse, **pas autorité automatique d’identité**.

### PR #90 → PR #106

**Statut : #90 `SUPERSEDED`; #106 = `SHADOW/DEFERRED` et implémentation PPT V4 à réutiliser.**

#106 est le remplacement propre sur `main` courant de son époque. Il garde PPT en shadow, avec contrat strict d’identité/provider et sans effet de décision production. Si PPT doit être intégré économiquement un jour, repartir de #106, pas de #90.

### Japan Edge PPT : #95 → #105 → #107

**Statut : #95 `SUPERSEDED`, #105 `SUPERSEDED`, #107 = `SHADOW/DEFERRED`.**

#107 garde l’affichage GCC et PPT séparé après la décision Japan Edge existante ; PPT ne crée/supprime pas l’opportunité et ne doit pas être blended silencieusement avec GCC.

---

# 6. V4 multi-market / valorisation externe

### PR #29 — external market avant rejet terminal

**Statut : historique précurseur, fonctionnalités absorbées ensuite par #33.**  
À consulter pour les invariants d’arbitrage : `GCC_ONLY`, `GCC_EXTERNAL_CONFIRMED`, `EXTERNAL_RESCUE`, `EXTERNAL_PENDING`, `MARKET_CONFLICT_BLOCKED`; dimensions commerciales explicites ; pas d’Unlimited/Non-Holo implicite.

### PR #33 — production canonical multi-market

**Statut : `PROD_V4`.**

Pipeline : GCC listing → identité TCGdex → PokeTrace exact graded / PSA APR / eBay SOLD / RAW TCGdex → arbitration evidence-strength.

### PR #43 / #47 / #77 / #116 — budgets externes / queue

**Statut : `PROD_V4` pour la logique actuellement câblée.**

Déjà résolu :
- ne pas affamer fixed quand auctions consomment des providers ;
- `PENDING_BUDGET` = pression de scheduling, pas erreur provider ;
- backoff long réservé aux vraies erreurs/transients ;
- priorité fixed intelligente à budget externe rare ;
- ordering auction ending-soon préservé.

Ne pas créer une nouvelle queue externe sans auditer ces modules :
- `v4_external_coverage_drain.py`
- `v4_smart_external_priority.py`
- queue/state du watcher actuel.

---

# 7. GCC discovery / auctions / Fast Lane

### PR #9 — discovery auction item-level

**Statut : `PROD_V4`.**

API publique `/on-sale-items`, `sellingTypeGroup=AUCTION`, `ENDING_SOON`, `endTime` individuel ; fallback legacy si la couverture ne peut pas être prouvée. `COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS` n’est pas « couverture absolue de tout GCC ».

### PR #50 / #52 — private-auction safety net

**Statut : `PROD_V4`.**

Le safety net privé a déjà été ajouté puis son accounting isolé pour ne pas polluer le ledger API primaire. Ne pas fusionner à nouveau les compteurs.

### PR #103 → #104

**Statut : #103 `SUPERSEDED`; #104 `PROD_V4`.**

#104 stabilise le drift de pagination `ENDING_SOON` par snapshots ancrés/répétés, union bornée puis fail-closed vers legacy si non stabilisé.

### PR #30 → #45 Fast Lane

**Statut : #30 `SUPERSEDED`; #45 = `PROD_V4`.**

Recheck final ciblé près de T−4 / fenêtre finale, sans auto-bid. Les alertes finales doivent conserver le même `max_recommended`.

### PR #55

**Statut : `PROD_V4`.**  
Verrouille l’identité exacte du lot final Fast Lane ; ne pas relâcher le final check au motif que le listing URL est déjà connu.

---

# 8. ASK / SOLD / Edge Hunter

### PR #78 — eBay BIN exact active ask

**Statut : `PROD_V4`.**

ASK uniquement sur opportunités fixed déjà retenues ; un ask ne crée jamais une opportunité ; texte `ASK, PAS UNE VENTE`; aucun ask dans les SOLD/comps/FV/max.

### PR #79 — stale listing / SOLD momentum / KB analytics

**Statut : `PROD_V4` pour les signaux câblés + analytics KB read-only.**

Signal d’information/priorité seulement ; ne crée pas l’opportunité, ne modifie pas FV/max. Expected Profit n’était explicitement **pas** implémenté dans cette PR.

### PR #80 — Structural Edge Hunter V2

**Statut : `PROD_V4`.**  
Validation : `571/571`, compile + discovery read-only PASS.

Détecteurs déjà existants :
- cross-market lag sur SOLD gradés exacts récents ;
- grader lag avec spread historique prouvé ;
- stale seller repricing si vendeur explicite ;
- liquidity breakout ;
- relative-grade anomaly même grader ;
- same-card inventory anomaly sur asks exacts + SOLD ;
- Expected Profit secondaire/ranking-only, jamais suppressif.

Ne pas recréer un deuxième « Edge Hunter » parallèle sans d’abord inspecter `v4_structural_edge_hunter.py`.

### PR #84 / #87

#84 = **garde de qualité de notifications en production** : RAW seul ne doit pas créer une opportunité slab, distinction illiquid/external evidence.  
#87 = **travail fermé/draft**, ajustement proposé de seuil illiquid GCC-only à 30 %. Ne pas le présenter comme production sans vérifier le code courant.

---

# 9. Japan Edge

### PR #89 — Japan Edge Hunter

**Statut : `PROD_V4`, lane séparée.**

Marchés ASK japonais : Mercari JP, magi, Yahoo/Flea ; japonais, carte individuelle, PSA10 ; fair value issue de GCC SOLD exacts, jamais des asks. Validation live historique `31914421575`: 2,000 GCC SOLD, 341 éligibles, 59 groupes, 328 asks, 1 lead exact ; provider errors 0.

### PR #94 — contexte global exact SOLD

**Statut : `PROD_V4`/base de la comparaison Japan Edge globale.**

PokeTrace exact JP PSA10 + eBay SOLD exact + PSA APR quand provenance langue exacte ; PokeTrace et eBay comptés comme même famille corrélée. Absence de marché externe ne devient pas preuve négative. Live `31937491360`: 5 leads GCC-only-unconfirmed, 0 valeur globale fabriquée.

### PR #101 — présentation comparative

**Statut : `PROD_V4`, mergée.**

Notification sépare prix Japon/coût rendu, GCC exact JP PSA10, marché externe exact, fair multi-marché, verdict, avec `ASK, PAS UNE VENTE`. Présentation uniquement, aucune économie changée.

### PPT Japan Edge

Voir chaîne #95 → #105 → **#107** ci-dessus. #107 reste la ligne à réutiliser si on réactive l’affichage PPT.

---

# 10. Global multi-vault / GCC + Cardova + magi + Fanatics + COMC

Cette architecture **a déjà été construite**. Ne pas repartir d’une feuille blanche.

### PR #108 — fondation globale

**Statut : `SHADOW/DEFERRED`, pas production.**  
Validation : run `31953479268`, `27/27` global-market + `51/51` V4 multimarket, compile/YAML/diff PASS.

Actifs à réutiliser depuis cette stack :
- `v4_global_market_core.py` ;
- bridges PPT / PokeTrace agrégés ;
- `v4_market_cardova.py` ;
- `v4_market_gcc_bridge.py` ;
- `v4_market_magi_bridge.py` ;
- `v4_market_fanatics_bridge.py` ;
- `v4_market_comc_bridge.py` ;
- `v4_market_verified_offer.py`.

Contrat déjà conçu :
- identité commerciale stricte ;
- opportunités EN + JAP, FR collectable mais non notif tant que profondeur SOLD insuffisante ;
- priorité item-level `SOLD_EXACT` ;
- `SOLD_AGGREGATED` explicitement distinct ;
- PPT et PokeTrace dans la même famille `EBAY_GRADED_AGGREGATE` ;
- ASK/current auction n’entre jamais dans fair value ;
- snapshot ≤5 min reste snapshot, jamais SOLD ;
- frais/all-in explicites, frais inconnus => fail-closed.

### PR #109 — live shadow multi-vault

**Statut : `SHADOW/DEFERRED`.**  
Live contrôlé `31954247131` SUCCESS : 5 identités JP PSA10 ; GCC 1600 candidats/6 exacts, magi 35/0, Fanatics 24/0, COMC 2/0, Cardova = `AUTH_SESSION_INPUT_REQUIRED`. Aucun ntfy/Neon/transaction. Offline `34/34 + 51/51`.

### PR #110 → #113 → #114 → #115

**Statut : chaîne de durcissement `SHADOW/DEFERRED`; réutiliser la dernière version de la stack.**

- #110 : diagnostics de rejet par provider ;
- #113 : retrieval hardening magi/Fanatics/COMC ;
- #114 : rejette les pages magi explicitement SOLD de la lane ASK ;
- #115 : route COMC exact set facet (Raging Surf) / exact set+localId.

### PR #112 — dispatcher manuel sur main

**Statut : `MAIN_SUPPORT`, mergée.**  
Main expose seulement le workflow manuel `V4 Global Market Live Shadow`; **main n’embarque volontairement pas les scripts scanner globaux**. Le dispatcher est read-only/manual, ntfy off, pas Neon, pas transaction, et doit fail-closed sur une branche sans scripts.

**Leçon :** absence de `v4_global_market_core.py` sur main ne signifie pas que la fonctionnalité n’a jamais été faite ; elle existe dans la stack shadow #108→#115.

---

# 11. Robot KB / Neon

Robot KB est une architecture durable séparée. Ne pas recréer un historique ad hoc dans V4/V5.

### PR #49 / #51 — miroir passif V4 discovery

**Statut : historique de la séparation discovery/ingest.**

V4 observe les réponses GCC déjà fetchées, sans appels supplémentaires ; artifact court ; writer Neon séparé ; V4 ne reçoit pas le secret Neon ; auction near-final = `LISTING_SNAPSHOT`, jamais SALE.

### PR #59 / #60 — SOLD GCC explicite

**Statut : déployé Robot KB/main workflows.**

`SALE_TRANSACTION` uniquement avec top-level `status=SOLD` + `soldAt` valide timezone-aware + prix final positif. `ENDED` ou absence soldAt = snapshot.

### PR #61 → #62

**Statut : #61 `SUPERSEDED`; #62 = implémentation fixed rotation à retenir.**

Rotation durable fixed, cursor avance seulement après fetch complet + ingest Neon réussi, safe wrap. #62 validation `468` tests.

### PR #68 — SOLD lossless watermark

**Statut : déployé.**

Watermark `soldAt` + IDs frontière ; backlog durable ; plafond 400 = débit, pas couverture ; état avance seulement après ingest réussi ; HTTP/contrat/état corrompu fail-closed.

### PR #72 — lane SOLD 30 min

**Statut : déployé.**

SOLD séparé toutes les 30 min, fixed/auction horaire, concurrency Neon commune `cancel-in-progress:false`.

### PR #75 — fixed hybrid coverage

**Statut : déployé.**

Jusqu’à 100 recent + 200 rotation + 100 ciblées/run, paramètres GCC GET-only vérifiés, dedupe avant ingest, état avance uniquement après succès Neon.

### PR #76 — backfill historique SOLD

**Statut : déployé/actif selon workflow courant.**

Backfill durable séparé de fresh lane, recherche de page bornée, ≤400/run, gestion des ventes partageant le même `soldAt`, strict SOLD contract.

### Analytics

`robot_kb_roi_analytics.py` existe en lecture seule pour mesurer profondeur et apprendre ratios seulement sur SOLD compatibles. Ne pas transformer ces ratios en heuristiques automatiques sans phase dédiée.

---

# 12. Certificats / Mislisted Slab / OCR

Cette zone a déjà eu plusieurs itérations et faux positifs. **Ne pas la réactiver ou la réécrire sans relire la chaîne.**

### PR #64 / #65

Adapters cert-first étendus, puis durcissement PSA/PCA/CCC. Official cert > OCR. Subgrades exclus. OCR par consensus. IMAGE_ONLY = revue manuelle, jamais preuve automatique d’un mismatch économique.

Benchmark #65 : 24 slabs, 4 exacts, 0 wrong, 12 ambiguous, 8 unavailable = **100 % parmi les lectures OCR acceptées**, pas 100 % de toutes les cartes.

### PR #66 / #67 / #69 / #71 / #73

Chaîne d’apprentissage :
- #66 : revue manuelle seulement si vraie opportunité ;
- #67 : mode cert-problem haute sensibilité ;
- #69 : hotfix safe-off après spam false `CERT NUMBER MISSING` ;
- #71 : cert GCC présent dans API / Description→Gradation correctement préservé ; diagnostic 100 cartes : API cert 100/100, collapsed inspection le perdait 100/100, fallback Gradation récupérait 100/100 ;
- #73 : failures techniques cert lookup = log-only, pas ntfy.

### PR #103 → #104

**Statut final production : Mislisted Slab/OCR `DISABLED`.**  
#104 garde la lane hard-disabled en V4 production après faux positifs. Le code reste un actif diagnostic, pas une fonctionnalité à réactiver implicitement.

---

# 13. Scheduling / workflows / observabilité

### Scheduler V4

Production utilise l’ordonnancement externe existant vers `workflow_dispatch`; ne pas ajouter un `schedule:` GitHub parallèle qui doublerait les scans.

### PR #13 — cache Playwright

**Statut : `PROD_V4`/workflow support.**  
Optimisation déjà faite ; ne pas recréer une seconde installation/cache Chromium parallèle sans audit.

### Issue #1

Journal durable des runs V4 ; conserver les concepts discovery mode/scope/timers/fallback séparés de la couverture économique.

### V5 workflows

`V5 Live Raw Pipeline Diagnostic` = manuel uniquement.  
`V5 Offline Validation` (#82) existe déjà pour les child PRs V5 sans secrets/providers live.  
Ne pas recréer des workflows diagnostics redondants : #24 avait déjà supprimé les anciens V5 diagnostics couverts par live RAW + tests offline.

---

# 14. Chaînes de supersession à connaître

| Ancien | Autorité / successeur | Règle |
|---|---|---|
| PR #30 final-auction long-wait | PR #45 Fast Lane | ne pas reprendre #30 |
| PR #61 Robot KB fixed+SOLD mélange | PR #62 fixed rotation + lanes SOLD ultérieures | reprendre #62/#68/#72/#75/#76 |
| PR #67 cert high-sensitivity | #69/#71/#73 puis #104 disabled | ne pas réactiver #67 |
| PR #90 PPT V4 | PR #106 | reprendre #106 |
| PR #95 Japan PPT | #105 puis #107 | reprendre #107 |
| PR #105 Japan PPT | PR #107 | #105 obsolète |
| PR #103 pagination/mislisted | PR #104 | reprendre #104 |
| anciens V5 diagnostics supprimés | PR #24 + V5 Live RAW/Offline | ne pas recréer les workflows supprimés |
| TCGdex aliases run-by-run #119–#121 seuls | #31 V5 + #122 + backport recovery | préférer architecture générique, garder aliases comme fast paths prouvés |

---

# 15. Capacités volontairement séparées — ne pas fusionner implicitement

- **V4 production** : décisions/notifications GCC canonique.
- **V5 PR #8** : expérimental ; jamais merger dans main sans autorisation explicite.
- **Robot KB/Neon** : historique durable ; ne doit pas devenir une mutation commerciale V4.
- **Global multi-vault #108–#115** : shadow ; ne pas le présenter comme prod.
- **PPT #106/#107/#92** : shadow/helper selon lane ; pas autorité automatique.
- **Mislisted Slab/OCR** : code historique, production hard-disabled.

---

# 16. Benchmarks à ne pas mal interpréter

- Aucun benchmark vérifié retrouvé prouvant **TCGdex 500/500**.
- Cert visibility #71 : **100/100** concernait les numéros de certificat GCC et le fallback Description→Gradation, pas TCGdex.
- OCR #65 : **100 % parmi lectures acceptées** = 4 exact / 0 wrong, mais 12 ambiguous + 8 unavailable sur 24 slabs.
- Les suites de tests `500+` (`509`, `519`, `523`, `569`, `600`, etc.) sont des **tests logiciels**, pas un panel live de centaines de cartes TCGdex.

Si un futur agent revendique « 100 % de couverture », il doit enregistrer : population exacte, source, sélection, langue, critère `EXACT`, exclusions, ambiguïtés, errors, run ID et SHA.

---

# 17. Format obligatoire pour toute nouvelle capacité

À la fin d’une phase validée, ajouter ici une entrée contenant au minimum :

```text
Capability:
Status: PROD_V4 | MAIN_SUPPORT | V5_ONLY | SHADOW | DEFERRED | SUPERSEDED | DISABLED
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

**Une phase n’est pas considérée complètement archivée tant que README + ce registre ne permettent pas à un nouvel agent de savoir immédiatement si le travail existe déjà, où il se trouve et s’il est production, shadow, V5-only ou superseded.**
