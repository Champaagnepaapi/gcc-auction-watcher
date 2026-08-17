# GCC Auction Watcher

> **Source de reprise technique canonique — à lire en premier dans toute nouvelle conversation.**
> Ce README décrit l’état courant. L’historique détaillé antérieur reste disponible dans Git/GitHub ; ne pas réintroduire un comportement ancien simplement parce qu’il apparaît dans un vieux commit.
> Le registre durable `docs/project-capability-ledger.md` doit ensuite être consulté avant toute nouvelle implémentation importante afin de récupérer les capacités déjà construites sur V4, V5, Robot KB ou les branches shadow/deferred.

## État canonique — 17 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

Head production `main` vérifié au début de l’audit de récupération :

```text
c8a495226f9e9800e5e1e2ac6a730ea21b1c3383
```

### Audit global anti-réimplémentation — 17 août 2026

- Un registre durable des capacités existe désormais dans `docs/project-capability-ledger.md`. Il classe explicitement les travaux `PROD_V4`, `MAIN_SUPPORT`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `BENCHMARK`, `SUPERSEDED` ou `DISABLED`, avec PR/branches/modules et instructions de réutilisation.
- La gouvernance impose maintenant un **capability-recovery check** avant tout travail non trivial : README + ledger + PR/branches GitHub + code V4/V5/Robot KB/shadow doivent être inspectés avant d’écrire un nouvel équivalent.
- L’audit TCGdex a confirmé que PR #31 avait déjà construit en V5 une résolution déterministe `2 coordonnées sur 3`. PR #123, encore draft/non mergée, backporte cette capacité en V4 au-dessus des fast paths #119/#120/#121 et avant le fallback plus large de #122.
- PR #122 reste non mergée et n’est pas production ; PR #123 la remplace/étend pour revue mais **aucun merge n’est autorisé implicitement**.
- L’audit global a aussi retrouvé des capacités majeures déjà faites : consensus RAW robuste + price discovery temporel multi-grader déjà en production au merge `8a61a6a5ec8740b9b8413cc82de26f11db064c43`, stack global multi-vault #108-#115 en shadow, PPT #92/#106/#107, Source Scout historique, Robot KB durable, Fast Lane, Structural Edge Hunter et l’historique cert/OCR désormais hard-disabled en production.
- La branche Source Scout historique `agent/source-scout-benchmark-20260814` est un actif `BENCHMARK/DEFERRED` à réutiliser pour toute future comparaison provider ; ne pas reconstruire ses probes/policies de zéro.
- Aucun benchmark vérifié ne prouve un TCGdex `500/500`. Les anciens `100/100` retrouvés concernent notamment la visibilité des certificats GCC, et les nombres `500+` sont souvent des suites de tests logiciels.
- Aucun live production, achat, bid, checkout, paiement ou merge de PR #8 n’est introduit par cet audit.

### Mise à jour V4 — external coverage drain / FR — 16 août 2026

- PR #116 prête pour production après benchmark live read-only.
- eBay SOLD/Completed reste un fallback de validation externe, pas une source de discovery d’annonces à acheter.
- budget eBay borné à **8 cartes/run**, avec **4 slots réservés aux fixed** lorsque les auctions consomment du budget ; timeout navigation eBay porté à `10s` après benchmark live.
- `PENDING_BUDGET` est désormais traité comme pression de scheduling avec retry court (`5 min`) au lieu d’un backoff exponentiel de plusieurs heures ; les vraies erreurs provider (403/429/transient/provider failure) gardent le backoff exponentiel.
- `TRUSTWORTHY:NO` reste inchangé tant qu’une vraie couverture externe reste incomplète.
- les cartes **FR sur GCC restent éligibles** aux opportunités si l’historique SOLD exact FR compatible est suffisant ; EN/JA ne servent que d’ancres secondaires downweightées et ne remplacent jamais les ventes FR exactes.
- validation finale head `60d6183286aed1f2df9a1473bbc2a66ab6b7a65f` : run `31973305164` — **602/602 tests PASS**, compile PASS, YAML PASS, `git diff --check` PASS, comparaison discovery live read-only PASS.
- benchmark live read-only eBay 8 : run `31973040904`, 8 cartes tentées, 5 clean/insufficient, 3 timeouts, 0 eBay 403/429/challenge ; backlog P4 local 2261→2258 sans sauvegarde production.
- aucun changement de fair value, `max_recommended`, seuil économique, identité/microvariante, achat, bid, checkout ou paiement.

### Mise à jour V4 — discovery auctions + Mislisted Slab — 16 août 2026

- **Mislisted Slab Hunter / image OCR désactivé en production V4** : `run_watcher_multimarket.py` force la lane à OFF, aucun override workflow ne peut la réactiver, le runtime Tesseract dédié a été retiré du workflow principal. Les anciennes sections historiques décrivant cette lane restent de l'historique, pas l'état production courant.
- Discovery auctions durcie contre les omissions live : snapshots API `ENDING_SOON` ancrés et répétés ; si l'ordre/completude API n'est pas prouvé, V4 **fail-closed** vers le fallback legacy complet.
- Safety-net legacy : pages `private` + `weekly`; les pages weekly dynamiques sont relues jusqu'à stabilisation de l'union des URLs. Ce safety-net s'applique aussi après le fallback legacy complet.
- Validation code head `72172a07f0430da39a3231932de64f165baa28bc` : run `31948079857`, job `95167175133` — **575/575 tests PASS**, compile PASS, `git diff --check` PASS.
- Validation live read-only : API publique non fiable sur ce run (`auction API ending-soon order invalid`), donc mode effectif `LEGACY_LIVE_SALES_FALLBACK_PLUS_STABLE_WEEKLY`; fallback failures `0`, supplemental failures `0`, `legacy_only=0`, timers legacy non résolus `0`.
- Aucun changement de matching économique, fair value, `max_recommended`, seuils de décote, achat, bid, checkout ou paiement.

### Principes non négociables

- **V4 sur `main` = production canonique.**
- **V5 = expérimentale, PR #8. Ne jamais merger PR #8 sans autorisation explicite.**
- Robot KB / Neon est un historique durable séparé de V4/V5.
- Pokémon **cartes individuelles uniquement** ; sealed/lots hors scope.
- Aucun achat, bid, checkout, paiement ou grading payant automatique.
- Ne jamais exposer/commiter de clé API, token, mot de passe ou secret.
- Discovery V4 : **ne jamais capper la découverte**. Les caps ne s’appliquent qu’aux traitements/enrichissements aval.
- Identité incertaine, conflit matériel ou microvariante non prouvée = incertitude accrue / revue manuelle / fail-closed ; jamais de comparable exact fabriqué.
- Une absence de marché confirmé n’est pas une preuve de mauvaise offre.

## Hiérarchie canonique des preuves prix

1. ventes **SOLD exactes et récentes** ;
2. ventes SOLD exactes anciennes, ajustées temporellement lorsque la méthode est défendable ;
3. asks fixes compatibles, explicitement étiquetés **ASK** ;
4. snapshot d’enchère observé à `≤5 min` si aucun SOLD n’est disponible ;
5. enchère en cours = signal faible.

**Un ask ou une enchère en cours n’est jamais une vente.**

---

# V4 — production canonique

## Entrypoint et scheduler

Main Scanner :

```text
Cron-job.org ~toutes les 10 min
  -> workflow_dispatch
  -> .github/workflows/watcher.yml
  -> run_watcher_multimarket.py
```

Fast Lane :

```text
Cron-job.org toutes les 3 min
  -> .github/workflows/v4-final-auction-check.yml
  -> recheck ciblé des auctions déjà armées à ≤5 min
```

Règles :

- pas de `schedule:` GitHub parallèle pour le Main Scanner/Fast Lane ;
- concurrency séparée, `cancel-in-progress: false` ;
- Fast Lane ne découvre aucune nouvelle carte et ne relance aucun provider externe ;
- Fast Lane réutilise le `max_recommended` déjà calculé ;
- `state.json` reste propriété du Main Scanner ; `final_alerts.json` sert à la déduplication finale ;
- aucune transaction automatique.

## Discovery fixed

- API GCC publique `/on-sale-items` ;
- scope Pokémon cartes individuelles ;
- prix discovery `0–100 €` ;
- file économique : `NEW -> CHANGED -> NEVER_EVALUATED -> STALE` ;
- budget d’évaluation borné en aval, jamais au niveau discovery ;
- TTL fixed standard 24 h, avec refresh adaptatif 1–6 h près du seuil.

## Discovery auctions

Source primaire :

```text
/on-sale-items
sellingTypeGroup=AUCTION
sortType=ENDING_SOON
status=ON_SALE
  -> endTime individuel
  -> Pokémon + carte + 0–100 € + ≤60 min
```

- arrêt uniquement lorsque l’ordre `ENDING_SOON` prouve que l’horizon 60 min est dépassé ou que l’inventaire est épuisé ;
- statut nominal : `COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS` ;
- safety-net private auction conservé ;
- total GCC `ON_SALE` global = autre scope, jamais faux dénominateur de la fenêtre ending-soon ;
- Fast Lane finale à ≤5 min, sans second scan marché externe.

---

# V4 — identité et valorisation multi-marché

Architecture :

```text
GCC listing
  -> identité canonique TCGdex déterministe
     -> GCC SOLD history
     -> PokeTrace graded exact
     -> PSA APR exact grade
     -> eBay SOLD exact grader + grade
  -> arbitrage par force de preuve
  -> opportunity / pending / conflict / manual review
```

## Identité

- nom + set + numéro/langue/variant selon disponibilité et applicabilité ;
- `004/102` peut correspondre numériquement à `4/102`, mais `4/102` ≠ `4/130` ;
- aucun fuzzy/substr/Levenshtein comme preuve exacte ;
- provider candidate ≠ preuve du listing ;
- langue, First Edition/Unlimited, finish, promo/stamp et microvariantes sensibles restent fail-closed.

## Scope PSA économique

```text
PSA 8
PSA 8.5
PSA 9
PSA 10
```

PSA <8 hors scope économique production ; ne pas fabriquer PSA 9.5.

## Marchés

- PokeTrace : marché gradé externe, max 40 requêtes/run, exact card + grader + grade requis pour preuve forte ;
- PSA : APR exact grade, eBay SOLD exact en fallback ;
- non-PSA : eBay SOLD même grader + même grade ;
- depuis PR #84, Cardmarket/TCGplayer RAW est **exclu de la génération d’opportunités slabs V4 production** ;
- RAW ne crée jamais `max_recommended`, fair value gradée ni opportunité slab V4.

## Arbitrage

Chemins principaux :

- `GCC_ONLY`
- `GCC_EXTERNAL_CONFIRMED`
- `EXTERNAL_RESCUE`
- `EXTERNAL_PENDING`
- `MARKET_CONFLICT_BLOCKED`

Règles :

- GCC fort + externe fort concordant -> confirmation prudente ;
- GCC faible/indisponible + externe fort -> rescue possible ;
- deux marchés forts contradictoires -> blocage ;
- provider indisponible ≠ no-match ;
- budget épuisé -> pending/requeue ;
- seuil utilisateur de base 30 %, renforcé quand preuve/liquidité sont faibles.

Titres ntfy :

- `GCC_EXTERNAL_CONFIRMED` -> **FORTE OPPORTUNITÉ CONFIRMÉE** ;
- `EXTERNAL_PENDING` -> **OPPORTUNITÉ GCC — EXTERNE EN ATTENTE** ;
- `GCC_ONLY` -> **OPPORTUNITÉ GCC — EXTERNE NON CONFIRMÉ**.

---

# V4 — priorité intelligente des budgets externes — PR #77

Merge :

```text
f192623e6e286eac05daf45fa70b0c20824c57b2
```

Module : `v4_smart_external_priority.py`.

Objectif : envoyer les requêtes externes rares d’abord vers les cartes à forte valeur d’information, **sans changer l’économie**.

- Auctions : ordre canonique `ending-soon` conservé bit-for-bit.
- Fixed : le rang de file existant reste prioritaire ; à rang égal, bonus pour baisse de prix GCC réelle, historique exact rare, grader secondaire/non-PSA, prix GCC bas et branche GCC faible/récupérable.
- Aucun changement de discovery, matching, fair value, `max_recommended`, seuils ntfy ou budgets providers.

Validation PR #77 : run `31889180022` — SUCCESS.

---

# V4 — position de marché actuellement achetable — PR #78 + cache PR #79

PR #78 merge :

```text
1eefc84b9015d8d57ef976166b24a56d8d9a791d
```

Module : `v4_exact_active_ask_position.py`.

Pour une **opportunité fixed déjà retenue**, V4 peut vérifier le plus bas slab exact actuellement achetable ailleurs.

Production actuelle :

- source graded listing-level : **eBay Buy-It-Now** ;
- max 2 nouvelles recherches réseau/run par défaut ;
- même carte + grader + grade + dimensions sensibles via le gate externe strict ;
- résultat affichable : `GCC est X % sous l'ASK eBay exact` ;
- texte obligatoire : **`ASK, PAS UNE VENTE`**.

Depuis PR #79 :

- un ask positif est caché brièvement par **identité commerciale stricte**, pas par URL de listing GCC ;
- TTL par défaut 30 min ;
- deux annonces GCC exactement identiques peuvent donc réutiliser une seule recherche eBay ;
- le gap est recalculé avec le prix GCC propre à chaque annonce ;
- les `no-match` ne sont pas cachés ;
- grader, grade, langue et dimensions sensibles restent séparés.

Sécurité : un ask actif ne crée jamais une opportunité, ne devient jamais un SOLD, et ne modifie jamais fair value ou `max_recommended`.

Validation PR #78 : run `31889490939`, job `95023537547` : **540/540 PASS**.

---

# V4 / Robot KB — ROI efficiency — PR #79

Merge production :

```text
0f0304635d131828d1d22d9f3ca7514ca33fe7dd
```

Feature head validé :

```text
3eb069894ef29174d9d8b88cf43540e2d1c40d89
```

## Stale listing + momentum SOLD exact

Module : `v4_roi_efficiency.py`.

- V4 conserve le `createdAt` structuré de l’annonce fixed GCC ;
- momentum calculé uniquement sur **SOLD exacts même carte + même grader + même grade**, datés, sans qualifier ;
- fenêtre récente par défaut : 90 j ; baseline : jusqu’à 365 j ;
- au moins 2 SOLD dans chaque fenêtre ;
- signal par défaut si annonce ≥14 j, momentum ≥15 % et prix GCC ≥15 % sous la médiane récente ;
- le signal sert uniquement à mieux ordonner les appels externes fixed **à rang de file égal** et à annoter une opportunité déjà retenue ;
- il ne crée jamais une opportunité et ne change ni fair value, ni seuil, ni `max_recommended` ;
- auctions/Fast Lane inchangées.

## KB-first : readiness seulement, aucun hard gate

Le Robot KB est encore trop jeune pour devenir la source obligatoire avant les APIs externes.

Audit Neon read-only effectué pendant PR #79 :

- `337` `sale_transaction` au total ;
- `100` ventes GCC finales prouvées dans l’échantillon alors présent ;
- `85` tiers stricts carte + langue + édition + grader + grade ;
- **0 tier avec ≥2 SOLD** ;
- **0 tier KB-first-ready** selon la règle prudente `≥3 SOLD exacts dont ≥2 <90j` ;
- **0 spread PSA ↔ grader secondaire** suffisamment profond pour apprentissage automatique à ce moment-là.

Conclusion : **aucun hard gate KB-first en V4 pour l’instant**. Les providers externes continuent normalement. La readiness est mesurée en shadow pendant que le backfill grossit.

## Analytics Robot KB read-only

Module : `robot_kb_roi_analytics.py`.

- transaction Neon explicitement `READ ONLY` ;
- lit uniquement des ventes GCC `COMPLETED` prouvées ;
- identité stricte issue des claims explicites, sans fuzzy ni valeur par défaut ;
- mesure profondeur par tier exact et readiness KB-first ;
- apprend éventuellement des ratios PSA ↔ grader secondaire uniquement si : même carte stricte, même grade, EUR, ≥2 SOLD de chaque côté et fenêtre combinée ≤365 j ;
- aucune conversion FX inventée ;
- output shadow `robot_kb_roi_snapshot.json` ;
- champs explicites `v4_economic_use=false`.

Le workflow SOLD lance cette analytics **après** ingestion, commit et sauvegarde des curseurs. Elle est `continue-on-error`, donc elle ne peut pas bloquer/falsifier la collecte SOLD ou le backfill.

## Validation PR #79

GitHub Actions :

```text
run 31891447216
job 95028201210
```

Résultat :

- **557/557 tests PASS** ;
- compile PASS ;
- `git diff --check` PASS ;
- live discovery read-only : primary complete, rows/timers `336/336`, private failures `0`, `primary_only=34`, `legacy_only=0`, unresolved `0` ;
- API + private safety-net = superset de legacy à horizon commun ;
- comparaison : 0 achat, bid, checkout, ntfy économique ou mutation d’état.

---

# V4 — Structural Edge Hunter V2 — PR #80

Merge production :

```text
89bff3ae114a42a5e716032717c5bbeeb8ca7d09
```

Feature head validé :

```text
f9516bb1e27ec8c30fe4a334b82e6be13bc44cc8
```

Module : `v4_structural_edge_hunter.py`.

Objectif : détecter des inefficacités structurelles qui peuvent créer une vraie décote exploitable sans modifier les gates économiques V4.

Signaux ajoutés :

- **Cross-market lag** : GCC n’a pas encore suivi une hausse récente de SOLD gradés externes exacts ;
- **Grader lag** : PCA/CCC reste en retard sur PSA même grade avec spread historique suffisamment prouvé ;
- **Stale seller repricing** : plusieurs anciennes annonces fixed d’un vendeur explicitement identifié restent immobiles pendant que les SOLD exacts montent ;
- **Liquidity breakout** : accélération récente du nombre de SOLD exacts sur un marché auparavant peu liquide ;
- **Relative-grade anomaly** : inversion anormale au sein du même grader, par exemple 9.5 moins cher qu’un grade inférieur comparable ;
- **Same-card inventory anomaly** : une annonce fixed exacte très sous les autres asks exacts, avec confirmation par SOLD récents.

Le **grade/metadata mislisting** reste géré par le Mislisted Slab Hunter cert-first existant ; PR #80 ne duplique pas cette logique.

## Expected Profit : information secondaire uniquement

PR #80 introduit un calcul Expected Profit **informatif / de classement seulement**. Il est explicitement interdit de l’utiliser comme gate de suppression :

- une forte décote reste notifiée même si l'Expected Profit est faible/incertain ;
- il ne change jamais fair value, `max_recommended`, seuil de décote ou décision V4 ;
- il ne peut jamais créer ni supprimer une opportunité ;
- il sert uniquement à contextualiser/prioriser les opportunités déjà admissibles.

## Sécurité des preuves

- Cross-market lag exige des **SOLD gradés exacts et datés** ;
- Cardmarket RAW n’est jamais traité comme SOLD gradé ;
- active asks restent **ASK, PAS UNE VENTE** ;
- same-card inventory exige identité commerciale stricte + confirmation SOLD ;
- seller repricing exige une identité vendeur explicite, jamais inférée depuis un titre/URL ;
- auctions gardent la priorité canonique ending-soon et ne reçoivent pas de bonus structural.

## Validation PR #80

GitHub Actions :

```text
run 31894158431
job 95034745917
```

Résultat :

- **571/571 tests PASS** ;
- compilation explicite de `v4_structural_edge_hunter.py` PASS ;
- `git diff --check` PASS ;
- live discovery read-only : primary `160`, legacy `159`, `primary_only=1`, `legacy_only=0`, unresolved `0`, private failures `0` ;
- API + private safety-net reste un superset de legacy à horizon commun ;
- comparaison : 0 achat, bid, checkout, ntfy économique ou mutation d’état.

---

# V4 — qualité des notifications et signaux illiquides — PR #84

Merge production :

```text
0d62e9cfa3d32e5d832fd4cbb75fbcd3102f0fff
```

Feature head validé :

```text
30cef835406956c7565b1f25c404975862ce7970
```

Module : `v4_notification_signal_quality_guard.py`.

Objectif : réduire le bruit téléphone sans relâcher le matching ni supprimer les vraies anomalies de prix.

- déduplication des manual reviews par **URL GCC stable**, avec migration de l’ancien état fondé sur l’identité enrichie ;
- `ILLIQUID_PRICE_DISCOVERY` auction : aucun ntfy avant `≤5 min` ;
- `ILLIQUID` fixed avec **GCC SOLD uniquement** : ntfy seulement si dislocation forte, par défaut `≥1.75x`, `≥10 €` d’upside absolu et `≥2` ancres GCC SOLD exactes ;
- un signal illiquide modéré soutenu par une **vente externe gradée SOLD exacte** peut toujours notifier selon les seuils économiques existants ;
- backlog aval attendu dû à un cap économique borné = diagnostic/log-only ; une vraie perte de discovery, un backlog urgent P0/P1, une panne ou un invariant comptable cassé restent alertables ;
- Cardmarket/TCGplayer RAW ne participe plus à la génération d’opportunités slabs V4 production ;
- l’Edge Hunter fail-closed reste installé sous ce guard : aucune relaxation d’identité, de microvariante ou de valorisation.

Validation PR #84 :

```text
run 31900251729
job 95049772805
```

Résultat :

- **581/581 tests PASS** ;
- compile des fichiers V4 modifiés PASS ;
- `git diff --check` PASS ;
- discovery live read-only : primary complete, `115` augmentées vs `114` legacy, `primary_only=1`, `legacy_only=0`, unresolved `0` ;
- comparaison : 0 achat, bid, checkout, ntfy ou mutation d’état.

---

# Mislisted Slab Hunter — état production courant

Scope prioritaire : **PSA / PCA / CCC**.

Ordre de preuve :

```text
cert GCC
  -> vérificateur officiel du grader
  -> comparaison grade GCC / grade officiel
  -> si officiel indisponible/non lisible : OCR ciblé slab
  -> revue manuelle si nécessaire
```

## Certificat GCC

- préserver le cert API avant inspection ;
- si réellement absent, ouvrir explicitement `Description -> Gradation` ;
- benchmark live : **100/100 certs présents et identiques API/Gradation**, 0 conflit.

## Politique notification cert actuelle — PR #73

- vrai `CERT_NUMBER_MISSING` après API + fallback Gradation absents -> **ntfy** ;
- `CERT_GRADE_UNREADABLE` après réponse officielle -> **ntfy** ;
- `CERT_UNAVAILABLE` purement technique / anti-bot / timeout -> **log uniquement** ;
- `POSITIVE_GRADE_MISMATCH` officiel -> alerte manuelle ;
- `NEGATIVE_GRADE_MISMATCH` officiel -> alerte + safety gate économique ;
- budget de lookup épuisé sans tentative ≠ problème cert.

Merge PR #73 :

```text
8f584e0d72afed5c6afc06a4e2d25d9d6787a44e
```

## OCR ciblé

OCR fallback uniquement PSA/PCA/CCC :

- PSA ROI top-right : `(0.38, 0.00, 0.62, 0.28)` ;
- PCA : `(0.48, 0.00, 0.52, 0.27)` ;
- CCC : `(0.48, 0.00, 0.52, 0.25)` ;
- Pillow upscale/contraste/netteté ;
- plusieurs passes Tesseract ;
- au moins 2 lectures concordantes ;
- exclusion explicite des subgrades.

Benchmark 50 cartes : 8 lisibles, 7 concordantes metadata, 1 conflit PSA suspect, 19 ambiguës, 23 indisponibles. Un mismatch `IMAGE_ONLY` reste **manual review**, jamais une preuve officielle et jamais une réécriture de la valorisation.

CCC cert live connu : `544340143` -> grade officiel global **9** ; les subgrades 9.5 ne doivent jamais être promus en grade global.

---

# Robot KB / Neon — historique durable
Robot KB est séparé de V4/V5 et reste passif/GET-only côté GCC.

Projet Neon : `robot-pokemon-kb`, branche production `main`, base `neondb`.

Pin sidecar validé :

```text
1d06fe33b6fc640657255e15a8d17251aa02b6ce
```

Principes :

- observations append-only, datées, immuables ;
- payload brut et provenance conservés ;
- final SOLD prouvé prioritaire ;
- fixed : baseline puis changements utiles ;
- auction : final SOLD prioritaire, snapshot ≤5 min seulement comme fallback clairement identifié ;
- aucune disparition/ask/live auction transformée en vente ;
- objectif : courbes 30j/90j/1an/multi-années, liquidité, tendance et valorisation.

## Fixed coverage hybride — PR #75

Merge :

```text
caebf0e5865e6851c5240b80c8ba55e3cfa7f5d5
```

Chaque run hourly peut couvrir :

- jusqu’à 100 fixed les plus récents ;
- 200 via rotation séquentielle durable ;
- jusqu’à 100 ciblés vers segments sous-échantillonnés ;
- déduplication listing avant ingestion ;
- état/cursor n’avance qu’après succès Neon.

Validation live post-merge : run `31888162893`, job `95020369028` — SUCCESS ; 400 source records, 400 observations acceptées, 0 source failure.

## SOLD frais lossless

Workflow : `.github/workflows/robot-kb-sold-shadow.yml`, cadence `17,47 * * * *`.

- fresh watermark séparé ;
- jusqu’à 400 SOLD frais/run + overlap live borné ;
- contrat : `status=SOLD` + `soldAt` timezone-aware + prix final ;
- état avancé seulement après succès d’ingestion Neon.

## Backfill historique SOLD — PR #76

Merge :

```text
fda196283e3522de7c1eadca3c706c9c350dec8d
```

Source : **API publique GCC**, requêtes GET-only sur le scope SOLD. Le robot remonte progressivement les pages historiques ; il ne scrape pas des asks et ne déduit jamais une vente depuis une enchère terminée.

Contrat :

```text
status=SOLD
+ soldAt timezone-aware
+ prix final valide
= SALE_TRANSACTION prouvée
```

Le backfill :

- remplit rétroactivement l’historique avant le bootstrap du 15/08/2026 ;
- cursor historique séparé de la lane fraîche ;
- recherche de la zone historique par sondage exponentiel/binaire borné ;
- max 400 ventes historiques/run ;
- `cursor_seen_ids` protège les frontières partageant le même `soldAt` ;
- commit du cursor seulement après ingestion Neon réussie ;
- s’arrête à la vraie fin de l’API historique.

Validation PR #76 : run `31889075054`, job `95022529447` : **529 tests PASS**, compile/diff/discovery live PASS.

---

# V5 — EXPÉRIMENTALE, PR #8 — NE PAS MERGER

PR : **#8**
Branche : `agent/v5-poketrace-cardmarket-market-data`

Head V5 expérimental actuellement validé :

```text
bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

Ce SHA est le merge **V5-only** de la PR #93. PR #8 reste ouverte/draft et **non mergée dans `main`**.

Règles :

- aucune intégration dans `main` sans autorisation explicite utilisateur ;
- identité normale : TCGdex exact / unicité déterministe ;
- PokeTrace reste principalement provider marché/prix ; les recherches PokeTrace de routine pour fabriquer l’identité sont désactivées ;
- bridge set déterministe seulement ;
- microvariantes/First Edition/finish fail-closed ;
- pas d’achat/bid/checkout/CardGrader automatique ;
- V4, V5 et Robot KB restent techniquement séparés.

## Observabilité identité détaillée — PR #81 + CI offline PR #82

PR #82 a ajouté à la branche V5 un workflow `V5 Offline Validation` sans secrets/providers, destiné aux PR enfants V5. Il exécute la suite `tests_v5`, `compileall v5` et `git diff --check` sans live.

PR #81 a porté la partie utile de l’ancien patch local d’observabilité sur la V5 actuelle, **sans réintroduire son ancienne logique de microvariantes** :

- diagnostics TCGdex/Pokémon TCG par identité ;
- diagnostics PokeTrace par stratégie, compteurs de candidats et exemples bornés de raisons de rejet ;
- diagnostic visuel passif avec score/marge/seuils ;
- JSON structuré par annonce unresolved / blocked ;
- le `VariantDiagnostic` courant est sérialisé tel quel : l’overlay ne décide pas à la place des gates actuels ;
- les wrappers appellent les resolvers courants via `super()` et ne changent ni matching, ni seuils, ni valuation ;
- metadata provider seule ne devient jamais une preuve listing ni un motif de `SINGLE_COMPATIBLE`.

Validation offline PR #81 : run `31898349431`, job `95045035673` — **569/569 tests V5 PASS**, compile/diff PASS, 0 secret commercial/provider injecté.

## PokeTrace market-only + emergency TCGdex — PR #85 / PR #88

PR #85 a supprimé PokeTrace du chemin normal de reconnaissance : TCGdex/catalogue reste l’autorité d’identité, et PokeTrace reste utilisé pour le marché/prix.

PR #88 a ensuite ajouté un secours strict **uniquement après vraie panne technique TCGdex** et le cache Robot KB/Neon :

```text
TCGdex live
  -> si panne technique seulement : Robot KB / Neon, identité TCGdex déjà prouvée
  -> si cache miss/indisponible : Pokémon TCG API catalogue
  -> si toujours non résolu et panne TCGdex éligible : PokeTrace emergency-only
  -> sinon fail-closed
```

Règles emergency :

- panne éligible : transport, JSON invalide, HTTP 408/425/429/5xx ;
- `CLEAN_NO_MATCH`, 404 et autres 4xx non transitoires n’ouvrent **jamais** Robot KB/PokeTrace emergency ;
- PokeTrace emergency garde le matching strict existant, ambiguïté = blocage ;
- budget par défaut : max 5 identités/run, clamp dur 0..10 ;
- runtime PokeTrace emergency isolé : aucune réponse identité ne prime/alias les caches marché ;
- Robot KB cache sur langue + nom exact + set exact + numéro local, dénominateur vérifié lorsqu’il est fourni ;
- plusieurs identités courantes compatibles => `AMBIGUOUS` ;
- metadata variants du cache ne prouve jamais édition/finish/microvariante ;
- erreur DB/cache => fallback Pokémon TCG API, jamais crash/faux match ;
- un succès TCGdex exact peut alimenter le cache ; un échec d’écriture cache n’invalide jamais le succès live.

Robot KB / Neon principal : migration cache appliquée le **16 août 2026**, migration ID `4603e681-2d97-4441-b248-103c7dd3c93a`. Le cache part vide et se remplit uniquement avec des identités TCGdex exactes prouvées.

Validation PR #88 :

```text
run 31913172878
job 95081167254
```

Résultat :

- **585/585 tests V5 PASS** ;
- `compileall v5` PASS ;
- `git diff --check` PASS ;
- secrets commerciaux/providers injectés : **0** ;
- aucun live V5 lancé pendant la phase ;
- aucun achat, bid, checkout ou paiement.

## Finish / microvariante post-macro — PR #93

PR #93 a été mergée **uniquement dans la branche V5 expérimentale** :

```text
bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

Feature head validé :

```text
129799cbafdc6ff2306a4370c97f4aa030673e84
```

Changements :

- le retry exact TCGdex d’applicabilité microvariante est maintenant réellement appelé après résolution macro lorsque la preuve catalogue initiale reste inconnue ;
- seule une preuve `TCGDEX_EXACT` peut remplacer l’inconnu sur ce chemin ;
- mapping promo versionné et borné pour les préfixes officiels (`DP/HGSS/BW/XY/SM/SWSH`) avec préfixe également exigé dans le numéro ;
- normalisation déterministe limitée aux familles mappées, par exemple `DP045 -> DP45` ;
- correction sémantique : TCGdex `wPromo` signifie **W-stamp**, pas appartenance générique à une série Promo ; ce champ ne prouve donc ni le statut promo général ni le finish à lui seul ;
- aucun seuil économique, matching fuzzy ou gate de sécurité n’a été relâché.

Validation offline : run `31915971540`, job `95087685592` — **600/600 tests V5 PASS**, compile/diff PASS, 0 secret commercial/provider injecté.

Validation live contrôlée : run `31916052221`, job `95087872111` — SUCCESS ; 17 requêtes TCGdex, 2 hits, 0 `variant-impossible`, 2 écritures Robot KB (1 insert + 1 idempotente), 0 achat/bid/checkout/CardGrader. Neon contient désormais exactement une identité `dpp-DP45` / Charizard G / DP Black Star Promos / `DP45` / EN, sans collision langue/set/numéro.

## Catalog gaps physiques récents — PR #96 en draft

La PR #96 est **offline-validée mais non mergée dans V5**. Elle traite deux catégories qui ne doivent pas être confondues :

- Pokémon TCG Pocket est un produit numérique et doit être rejeté avant le pipeline de cartes physiques ;
- une vraie carte physique récente absente de TCGdex peut être ajoutée à un registre exact, versionné et sourcé, jamais via une règle générique `TCGdex no-match => accept`.

Premier gap exact documenté dans la PR : Magikarp coréen `040/M-P`, `M-P Promotional cards`, 2026, Holo Promo. L’entrée exige nom + numéro imprimé + langue + set/alias borné exact, et toute contradiction ou ambiguïté restante bloque.

PR #96 : head `360ae33a67987e0a981b348e636bd7e2f964667e`, base V5 `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f`. Validation offline run `31937817636`, job `95142423068` : **611/611 tests V5 PASS**, compile/diff PASS, 0 secret injecté. **Aucune validation live n’est revendiquée pour #96 à ce stade.**

Benchmarks fallback identité :

- PokemonPriceTracker : **16/18** macro exactes sur le panel, 2 vintage laissées ambiguës ;
- tcgapi.dev : **3/18** macro exactes, langue non prouvée ;
- JustTCG : **0/20** exact sur le benchmark corrigé set-aware.

PokemonPriceTracker reste le meilleur candidat de fallback macro supplémentaire à ce stade. Le test shadow live borné a confirmé une bonne capacité de récupération de set mais aussi des catégories trop génériques : il reste donc **shadow-only** et ne peut pas contourner les gates microvariantes.

Les PR #75/#76/#77/#78/#79/#80/#84 n’ont pas mergé PR #8. Les PR #81/#82/#85/#88/#93 ont été mergées **dans la branche V5 expérimentale uniquement**, jamais dans `main`. PR #96 reste draft/non mergée.

---

# Workflows à conserver

1. `GCC Auction Watcher` — V4 Main Scanner.
2. `GCC Final Auction Check` — Fast Lane ≤5 min.
3. `V4 Auction Discovery Validation` — CI + comparaison read-only.
4. `V4 GCC Coverage Audit`.
5. `PSA Public API Diagnostic` — diagnostic historique.
6. `Robot KB cloud shadow` — fixed/auction shadow.
7. `Robot KB SOLD shadow` — fresh SOLD + backfill historique + snapshot ROI/readiness **read-only**.
8. `V5 Offline Validation` — CI offline sans secrets/providers pour les PR enfants ciblant la branche V5.
9. workflows V5 diagnostics/benchmarks — expérimentaux uniquement ; les lives restent manuels.

Éviter les workflows temporaires/redondants quand un workflow existant suffit.

---

# Index des merges importants actuels

```text
PR #45  Fast Lane                         0978aa50309fc850f6c8b9e18743ea8011bd2444
PR #46  PSA APR diagnostics               fdf2c273b732e1c91dfc8a40f8540f31a9a92f02
PR #47  adaptive refresh                  0df59c2140af22410a082fea9a673dc0f6f599a4
PR #53  Edge Hunter safety                1d29cbfaa7b17c5a08e6450813f956573cf9ec12
PR #55  final alert identity              9281c7fdfbda1e680904afec77d623dd2ff86e38
PR #56  notification semantics            93842e061a77b9f1af095b9190a7d14a04832cb0
PR #60  Robot KB SOLD deploy              78dd3cb72d42647dc996a9fcbe1e8afe21f10348
PR #65  cert-first + focused OCR          28a0b7f8154225ead775e50f02bdf29afa658240
PR #66  unresolved cert+OCR review        (voir historique Git/PR #66)
PR #71  cert preservation/Gradation       90ca444147e65f40a8c53b939ab5da55e406fdb1
PR #73  technical cert failure log-only   8f584e0d72afed5c6afc06a4e2d25d9d6787a44e
PR #75  KB fixed hybrid                   caebf0e5865e6851c5240b80c8ba55e3cfa7f5d5
PR #76  KB historical SOLD backfill       fda196283e3522de7c1eadca3c706c9c350dec8d
PR #77  smart external priority           f192623e6e286eac05daf45fa70b0c20824c57b2
PR #78  exact active eBay ASK position    1eefc84b9015d8d57ef976166b24a56d8d9a791d
PR #79  ROI efficiency / KB readiness     0f0304635d131828d1d22d9f3ca7514ca33fe7dd
PR #80  Structural Edge Hunter V2         89bff3ae114a42a5e716032717c5bbeeb8ca7d09
PR #84  notification signal quality       0d62e9cfa3d32e5d832fd4cbb75fbcd3102f0fff
```

---

# Gouvernance avant tout changement futur

## V4

Un changement important exige :

1. branche/PR dédiée ;
2. SHA précis ;
3. tests ciblés + full suite pertinente ;
4. compile / `git diff --check` ;
5. comparaison discovery live read-only lorsque pertinente ;
6. vérification qu’aucune logique achat/bid/checkout n’a été introduite ;
7. merge vers `main` seulement après validation ;
8. mise à jour de ce README après la phase.

Pendant des enchères actives, éviter toute modification risquée du cœur V4 ; préférer des changements isolés, fail-closed et réversibles.

## Robot KB

- GET-only côté collecte GCC ;
- jamais mélanger ask/live auction et SOLD ;
- state cursor durable n’avance qu’après ingestion réussie ;
- privilégier large couverture de cartes différentes + final SOLD prouvé ;
- conserver l’historique immuable ;
- **ne pas activer un hard gate KB-first tant que la profondeur exacte par tier n’est pas suffisante**.

## V5

Avant toute intégration de PR #8 : **autorisation explicite utilisateur obligatoire**, puis audit base/head/ancestry et validation V4 complète.

**PR #8 reste expérimentale et non mergée par défaut.**

---

# Addendum canonique — 16 août 2026 — Japan Edge Hunter / PR #89

Merge production :

```text
c2309e6d6f0c19bd07479b73498dae8445366238
```

Le **Japan Edge Hunter** est désormais une lane production séparée du cœur V4 et de V5. Il scanne en lecture seule les **ASK fixes** de Mercari Japan, Magi et Yahoo! Flea Market / PayPay Fleamarket pour des cartes Pokémon japonaises individuelles PSA 10, puis compare uniquement les identités exactes à des **GCC SOLD exacts**.

Règles économiques / sécurité :

- cadence GitHub Actions : `23 */6 * * *` ;
- fair value de cette première version : GCC SOLD exacts uniquement ;
- au moins 2 SOLD exacts récents, ou 3 SOLD exacts ≤365 j lorsque la fenêtre récente est insuffisante ;
- seuil ntfy : **≥30 % de décote après buffer logistique** ;
- coût proxy : `¥500` + buffer additionnel `12 %` ;
- un prix Mercari/Magi/Yahoo reste **ASK, PAS UNE VENTE** ;
- enchères en cours exclues ;
- identité ambiguë, lot/multi-item, langue/set/numéro/grade/microvariante non prouvés => fail-closed / log-only ;
- aucun achat, bid, checkout, paiement ou grading automatique.

Le faux blocage Magi du premier live a été corrigé dans `japan_edge_hunter_v2.py` : les gates `auction` / `multi-item` n’utilisent plus le texte parasite des recommandations/footer de la page détail ; l’identité complète continue en revanche d’utiliser les preuves pertinentes de la fiche.

Validation V2 read-only :

```text
run 31914421575
job 95084109952
```

Résultat : 2 000 lignes GCC SOLD inspectées, 341 SOLD japonais PSA 10 éligibles, 59 références exactes, 36 recherches provider, 328 ASK observés, 170 candidats potentiellement ≥30 % avant preuve stricte, 10 enchères rejetées, 159 identités rejetées, **1 lead exact retenu**, 0 erreur provider.

Premier lead de validation : Bulbasaur / 151 / `166/165` / Japanese / PSA 10, Yahoo Flea, ASK `¥10,500`, coût rendu conservateur estimé `CHF 62.90`, référence GCC SOLD `€100`, décote ~33 %, 3 GCC SOLD exacts <90 j. Ce signal est une décote **vs GCC**, pas une preuve que le marché mondial vaut €100.

Validation finale offline du head fonctionnel : 15/15 tests ciblés PASS, compile PASS, YAML PASS et `git diff --check` PASS. Les commits ultérieurs sans diff de fichiers n’ont pas changé le tree validé.

## Source officielle de microvariante — MEGA Dream ex

Le Robot KB / Neon contient désormais l’avis officiel Pokémon `005318` comme preuve immuable :

```text
source_system.code = pokemon_card_official
source_record = srecord_76532e18ea31ceecae3c27aeebb17dea
payload_sha256 = b83378e9ee0e86f5d33d17fcdf193571041890bbf0bd764e7894468a426f9ce2
```

L’avis officiel établit qu’une erreur de **traitement de surface** existe sur certains lots de cartes MA de `MEGA Dream ex`, tout en précisant que des exemplaires correctement traités existent aussi. Conséquence d’identité : l’avis prouve l’existence de la microvariante, **pas** qu’un exemplaire individuel est `INCORRECT TEXTURE`. Pour les familles concernées, une référence GCC non qualifiée ne peut donc pas être promue comme comparable exact d’une variante texture spécifique ; `MA-INCORRECT TEXTURE` doit être explicitement prouvé.

## Notifications Japan

Le workflow `.github/workflows/japan-edge-hunter.yml` a les notifications `JAPAN EDGE >=30%` activées par défaut après la validation live V2. Il utilise le canal ntfy existant si `NTFY_TOPIC` est disponible ; une variable repo explicite `JAPAN_EDGE_NOTIFY_ENABLED=false` peut servir de coupe-circuit fail-safe.

PR #8 reste expérimentale et non mergée. PR #87 reste séparée du Japan Edge Hunter et n’est pas mergée par PR #89.

---

# Addendum canonique — 16 août 2026 — Japan Edge multi-marché / PR #94

Merge production :

```text
2a405ff9bdf5aa62bf3c2a074ce1b2a9ab210b2e
```

Le Japan Edge Hunter compare désormais chaque ASK japonais exact retenu à deux niveaux de marché :

1. **GCC SOLD exacts de la même carte japonaise PSA 10** ;
2. **marché externe gradé SOLD exact** lorsque prouvable, via PokeTrace/eBay SOLD et PSA Auction Prices Realized.

Identité : la référence GCC exige toujours même carte, `language=Japanese`, `grader=PSA`, `grade=10`, avec set/numéro/édition/attribut/variante/microvariante compatibles. Le nom Pokémon peut être affiché en anglais parce que GCC expose `character.englishName`, mais la langue commerciale de la carte de référence reste japonaise.

Règles externes :

- PokeTrace doit produire un match exact japonais PSA 10 ;
- eBay direct n'est admis que si le comparable SOLD prouve explicitement Japanese + PSA 10 + carte exacte ;
- PSA APR n'est admis que si la provenance de la Spec prouve explicitement `language:japanese` + PSA 10 exact ;
- PokeTrace et eBay direct sont regroupés en une seule famille eBay afin d'éviter le double comptage ; PSA APR reste une famille indépendante ;
- le centre externe est la médiane des familles indépendantes disponibles ; le fair multi-marché combine GCC et ce centre externe ;
- un ask japonais n'entre jamais dans la fair value et reste **ASK, PAS UNE VENTE**.

Sémantique notifications :

- `MULTIMARKET_CONFIRMED` : décote ≥30 % versus marché externe exact **et** fair multi-marché -> notification haute priorité ;
- `GCC_EDGE_NOT_GLOBAL` : GCC montre ≥30 %, mais le marché externe exact ne confirme pas -> pas de notification ;
- `MARKET_CONFLICT_BLOCKED` : divergence GCC/externe >1.35x -> fail-closed ;
- `GCC_ONLY_UNCONFIRMED` : aucun SOLD externe exact prouvable -> la décote GCC peut encore notifier, mais l'absence de confirmation externe est explicitement indiquée. Une absence de données externes n'est jamais traitée comme preuve négative.

Validation :

```text
Offline CI : run 31937493250 / job 95141590710
22/22 tests PASS + compile PASS + YAML PASS + git diff --check PASS

Live read-only : run 31937491360 / job 95141585970
SUCCESS
```

Live : 2 000 GCC SOLD, 361 ventes japonaises PSA 10 éligibles, 64 groupes de références exactes, 12 seeds, 36 recherches Japon, 503 ASK observés, 232 candidats potentiellement ≥30 % avant preuve stricte, 5 candidats exacts retenus, 227 rejets identité. Dans ce run, PSA APR a répondu HTTP 403, eBay direct n'a exposé aucun SOLD structuré exact et PokeTrace n'a pas produit de match japonais PSA 10 fort : les 5 leads sont donc restés `GCC_ONLY_UNCONFIRMED`, sans fabrication d'une fair value mondiale.

Sécurité inchangée : aucun achat, bid, checkout, paiement ou grading automatique. PR #8 reste expérimentale/non mergée. PR #87 reste séparée.

---

# Addendum canonique — 16 août 2026 — format comparatif notifications Japan Edge / PR #101

Merge production :

```text
cf652027a767626829d6c3b6d115fb62f64f140c
```

Le contenu économique du Japan Edge n'a pas changé. La notification ntfy affiche désormais les éléments séparément pour lecture immédiate :

```text
Prix Japon: ¥... | rendu estimé ... CHF

GCC exact JP PSA10: €...
→ décote vs GCC: -...%

Marché externe exact: €... | source(s) | n SOLD
→ décote vs externe: -...%

Fair multi-marché: €...
→ décote globale: -...%

VERDICT: ...
ASK, PAS UNE VENTE
```

Si aucun marché externe exact n'est prouvable, la notification indique explicitement `Marché externe exact: non confirmé` et `Fair multi-marché: non confirmé — référence GCC seule`; elle ne fabrique pas de prix mondial.

Validation PR #101 : run `31942800314`, job `95154297972` — tests Japan Edge PASS, compilation PASS, YAML PASS et `git diff --check` PASS.

Aucun changement de discovery, identité, fair value, seuil économique, provider, achat, bid, checkout ou paiement. PR #8 reste expérimentale/non mergée.
