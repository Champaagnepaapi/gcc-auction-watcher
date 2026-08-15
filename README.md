# GCC Auction Watcher

> **Source de reprise technique canonique — à lire en premier dans toute nouvelle conversation.**
> Ce README décrit l’état courant. L’historique détaillé antérieur reste disponible dans Git/GitHub ; ne pas réintroduire un comportement ancien simplement parce qu’il apparaît dans un vieux commit.

## État canonique — 15 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

Dernier merge fonctionnel V4/Robot KB de cette phase :

```text
1eefc84b9015d8d57ef976166b24a56d8d9a791d
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

## Discovery

### Fixed

- API GCC publique `/on-sale-items` ;
- scope Pokémon cartes individuelles ;
- prix discovery `0–100 €` ;
- file économique : `NEW -> CHANGED -> NEVER_EVALUATED -> STALE` ;
- budget d’évaluation borné en aval, jamais au niveau discovery ;
- TTL fixed standard 24 h, avec refresh adaptatif plus rapide près du seuil.

### Auctions

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

Merge production :

```text
f192623e6e286eac05daf45fa70b0c20824c57b2
```

Module : `v4_smart_external_priority.py`.

Objectif : envoyer les requêtes externes rares d’abord vers les cartes à forte valeur d’information, **sans changer l’économie**.

### Auctions

Ordre canonique `ending-soon` conservé **bit-for-bit**. Aucune heuristique fixed ne peut passer devant une auction.

### Fixed

Le rang de file existant reste prioritaire ; à rang égal, bonus pour :

- baisse de prix GCC réelle ;
- historique exact rare (`0/1/2` comps exacts) ;
- grader secondaire/non-PSA ;
- prix GCC bas ;
- branche GCC faible/indisponible donc potentiellement sauvable par marché externe.

Ce module ne change pas : discovery, matching, fair value, `max_recommended`, seuils ntfy ou budgets providers.

Validation PR #77 : run `31889180022` — SUCCESS ; tests/compile/discovery live verts.

---

# V4 — position de marché « actuellement achetable » — PR #78

Merge production :

```text
1eefc84b9015d8d57ef976166b24a56d8d9a791d
```

Module : `v4_exact_active_ask_position.py`.

But : pour une **opportunité fixed déjà retenue par V4**, vérifier si GCC est actuellement moins cher qu’un slab exact achetable ailleurs.

Production actuelle :

- première source exacte : **eBay Buy-It-Now** ;
- max 2 opportunités fixed vérifiées/run par défaut ;
- identité commerciale suffisante requise ;
- même carte + grader + grade + dimensions sensibles via le gate externe strict existant ;
- conserve le plus bas ask eBay exact trouvé ;
- notification possible : `GCC est X % sous l'ASK eBay exact` ;
- texte obligatoire : **`ASK, PAS UNE VENTE`**.

Sécurité :

- un ask actif ne crée **jamais** une opportunité ;
- un ask ne devient jamais un SOLD/comparable vendu ;
- aucun changement de fair value ou `max_recommended` ;
- Cardmarket/TCGplayer restent RAW et ne sont pas présentés comme asks exacts de slab tant qu’une source graded listing-level exacte n’est pas disponible ;
- auctions/Fast Lane inchangées.

Validation PR #78 : run `31889490939`, job `95023537547` : **540/540 tests PASS**, compile PASS, `git diff --check` PASS, discovery live PASS (`legacy_only=0`, unresolved=0, private failures=0).

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

Un bug historique effaçait le `cert_number` structuré lors de l’inspection de fiche. Correction validée :

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
- exclusion explicite des subgrades (`SURFACE`, `CORNERS/COINS`, `EDGES/CÔTÉS`, `CENTERING/CENTRAGE`).

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

Le ciblage n’utilise jamais un badge GCC « bonne affaire » comme preuve économique.

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

Module : `v4_kb_sold_backfill.py`.

Le backfill remplit **rétroactivement** l’historique avant le bootstrap du 15/08/2026 :

- cursor historique séparé de la lane fraîche ;
- strictement `SOLD + soldAt timezone-aware + prix final` ;
- recherche de la bonne zone historique par sondage exponentiel/binaire borné ;
- max 400 ventes historiques/run ;
- `cursor_seen_ids` protège contre pertes/doublons lorsque plusieurs ventes ont exactement le même `soldAt` ;
- `commit` du cursor seulement après ingestion Neon réussie ;
- s’arrête seulement après avoir atteint la vraie fin de l’API historique.

Validation PR #76 : run `31889075054`, job `95022529447` : **529 tests PASS**, compile/diff PASS, discovery live PASS (`legacy_only=0`, private failures=0).

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

Les PR #75/#76/#77/#78 n’ont pas mergé PR #8 et ne doivent pas être utilisées comme prétexte pour la resynchroniser sans audit.

---

# Workflows à conserver

1. `GCC Auction Watcher` — V4 Main Scanner.
2. `GCC Final Auction Check` — Fast Lane ≤5 min.
3. `V4 Auction Discovery Validation` — CI + comparaison read-only.
4. `V4 GCC Coverage Audit`.
5. `PSA Public API Diagnostic` — diagnostic historique.
6. `Robot KB cloud shadow` — fixed/auction shadow.
7. `Robot KB SOLD shadow` — fresh SOLD + backfill historique.
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
- conserver l’historique immuable.

## V5

Avant toute intégration de PR #8 : **autorisation explicite utilisateur obligatoire**, puis audit base/head/ancestry et validation V4 complète.

**PR #8 reste expérimentale et non mergée par défaut.**
