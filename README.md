# GCC Auction Watcher

> **Source de reprise technique canonique — à lire en premier dans toute nouvelle conversation.**
> Ce README décrit l’état courant. L’historique détaillé antérieur reste disponible dans Git/GitHub ; ne pas réintroduire un comportement ancien simplement parce qu’il apparaît dans un vieux commit.

## État canonique — 15 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

Dernier merge fonctionnel V4 / Robot KB :

```text
89bff3ae114a42a5e716032717c5bbeeb8ca7d09
```

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
     -> TCGdex Cardmarket / TCGplayer RAW
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
- Cardmarket/TCGplayer en V4 = **RAW**, pas valeur automatique du slab ;
- RAW ne crée jamais seul `max_recommended` ni opportunité gradée automatique.

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

Objectif : détecter des inefficiences structurelles qui peuvent créer une vraie décote exploitable sans modifier les gates économiques V4.

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

- une forte décote reste notifiée même si l’Expected Profit est faible/incertain ;
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

Règles :

- aucune intégration dans `main` sans autorisation explicite utilisateur ;
- TCGdex principal ; PokeTrace fallback identité/marché ;
- bridge set déterministe seulement ;
- microvariantes/First Edition/finish fail-closed ;
- pas d’achat/bid/checkout/CardGrader automatique ;
- V4, V5 et Robot KB restent techniquement séparés.

Les PR #75/#76/#77/#78/#79/#80 n’ont pas mergé PR #8 et ne doivent pas être utilisées comme prétexte pour la resynchroniser sans audit.

---

# Workflows à conserver

1. `GCC Auction Watcher` — V4 Main Scanner.
2. `GCC Final Auction Check` — Fast Lane ≤5 min.
3. `V4 Auction Discovery Validation` — CI + comparaison read-only.
4. `V4 GCC Coverage Audit`.
5. `PSA Public API Diagnostic` — diagnostic historique.
6. `Robot KB cloud shadow` — fixed/auction shadow.
7. `Robot KB SOLD shadow` — fresh SOLD + backfill historique + snapshot ROI/readiness **read-only**.
8. workflows V5 diagnostics/benchmarks — expérimentaux uniquement.

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