# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel vérifié le **18 août 2026**.

Ce fichier sert d'index anti-réimplémentation. Avant tout changement non trivial, vérifier si la capacité existe déjà sur V4, V5, Robot KB ou une branche shadow/deferred.

## Autorité courante

```text
V4 production / main : a52398685629e4baf4c8ac036851e2ae1a49b037
V5 expérimentale     : PR #8 / agent/v5-poketrace-cardmarket-market-data
V5 head validé       : bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
TCGdex source pin    : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Statuts utilisés :

- `PROD_V4` : actif sur `main` dans le watcher production ;
- `MAIN_SUPPORT` : support/ops/docs sur `main` ;
- `ROBOT_KB` : historique durable séparé ;
- `V5_ONLY` : seulement dans la branche expérimentale V5 ;
- `SHADOW` : mesure/recherche sans décision production ;
- `DEFERRED` : capacité utile mais non activée ;
- `DISABLED` : code/historique conservé mais comportement volontairement coupé ;
- `SUPERSEDED` : ne pas merger/réimplémenter tel quel.

---

# V4 production

## Discovery GCC item-level — `PROD_V4`

Capacités déjà construites :

- auction discovery via `/on-sale-items`, `sellingTypeGroup=AUCTION`, `sortType=ENDING_SOON`, `status=ON_SALE`, `endTime` individuel ;
- horizon local ≤60 min ;
- safety-net legacy private/weekly ;
- fallback legacy complet si l'ordre/completude API n'est pas prouvé ;
- couverture explicite `COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS` ;
- discovery fixed complète avant caps économiques.

PRs structurantes : #9, #50, #52, #104. Ne pas reconstruire un deuxième collector auction parallèle.

## Fast Lane finale — `PROD_V4`

PR #45 + #55.

- recheck ciblé des auctions déjà armées ;
- aucun nouveau discovery/provider externe ;
- `max_recommended` persisté et immuable ;
- alerte finale seulement si prix courant reste sous ce plafond ;
- identité carte correcte dans la notification.

## Arbitrage multi-marché canonique — `PROD_V4`

PR #33 + #35 et durcissements ultérieurs.

Architecture :

```text
GCC listing
  -> identité déterministe TCGdex
  -> GCC SOLD
  -> PokeTrace graded exact
  -> PSA APR / eBay SOLD exact
  -> arbitrage evidence-strength
```

Chemins : `GCC_ONLY`, `GCC_EXTERNAL_CONFIRMED`, `EXTERNAL_RESCUE`, `EXTERNAL_PENDING`, `MARKET_CONFLICT_BLOCKED`.

RAW Cardmarket/TCGplayer ne devient jamais fair value de slab.

## TCGdex / PokeTrace recovery #119→#135 — `PROD_V4`, AUTORITÉ COURANTE

Cette lignée est la référence actuelle. Ne pas repartir d'anciennes branches pour corriger l'identité.

- #119 : exact-coordinate registry pour blockers mesurés ;
- #120/#121 : récupération déterministe set/localId et aliases set-level revus ;
- #122/#123 : unicité catalogue / récupération `2 coordonnées sur 3` intégrée à V4 ;
- #124 : retrieval PokeTrace structuré après identité TCGdex ;
- #127 : padding provider collector number préservé ;
- #128 : bridges provider exacts ;
- #129 : JA canonical-search corrigé ;
- #130 : final-gate diagnostics + alias source-pinné Night Wanderer/SV6a ;
- #131→#133 : finish source-pinné puis généralisé ;
- #134→#135 : réconciliation de set quand REST TCGdex est stale/conflictuel ; #135 utilise le fichier carte du catalogue immuable comme fallback exact.

Production finale :

```text
PR #135 merge : a52398685629e4baf4c8ac036851e2ae1a49b037
run prod       : 32160680888 / SUCCESS
```

Preuve live #135 : Houndoom `100/098`, Meowth `109/098` et Moltres ex `112/098` récupérés vers `SV10` depuis le pin TCGdex. Crobat `117/098` n'a pas été échantillonné ; ne pas inventer cette preuve spécifique.

Règle future : **pas de treadmill d'alias carte-par-carte**. Une nouvelle correction d'identité doit correspondre à une classe répétée, déterministe et prouvée.

## PR #126 — `SUPERSEDED`

`fix/v4-poketrace-exact-provider-bridges-20260818`, PR ouverte/draft.

Sa logique utile a été réintégrée proprement par #127/#128 puis durcie par #129→#135. **Ne pas merger #126.**

## Queue / couverture externe — `PROD_V4`

PRs #43, #47, #77, #116.

- anti-starvation fixed ;
- refresh adaptatif proche seuil ;
- priorité smart des appels externes ;
- eBay budget borné à 8 cartes/run avec réserve fixed ;
- `PENDING_BUDGET` = scheduling pressure, pas clean negative ;
- erreurs provider gardent backoff/fail-closed.

État du run #135 : backlog externe ~2031 / ~204 runs, couverture externe `INCOMPLETE`. Priorité actuelle : drainage/mesure, pas relaxation identité.

## Exact active ASK — `PROD_V4`

PR #78/#79.

- eBay BIN exact seulement comme contexte d'offre actuellement achetable ;
- ASK reste ASK ;
- ne crée jamais une opportunité ;
- ne modifie jamais fair value / `max_recommended`.

## Structural Edge Hunter V2 — `PROD_V4`

PR #80.

Signaux existants : cross-market lag, grader lag, stale seller repricing, liquidity breakout, relative-grade anomaly, same-card inventory anomaly, Expected Profit informatif.

Ces signaux ne remplacent jamais les gates de preuve ni l'économie V4.

## Notification quality / illiquide — `PROD_V4`

PR #84 et durcissements associés.

- manual-review dédupée par URL stable ;
- illiquid auction silencieuse avant ≤5 min ;
- external absence != negative evidence ;
- technical backlog attendu n'entraîne pas de faux spam.

PR #87 reste une décision produit séparée/non production sur le seuil GCC-only 30 % exact. Revalider sur le `main` courant avant toute intégration.

## Cert / OCR / Mislisted Slab — `DISABLED` en production

Historique riche : #57, #63→#73.

Les vérificateurs cert-first, OCR ciblé et diagnostics existent, mais la lane Mislisted Slab a été **hard-disabled** en production par #103/#104 après faux positifs. Ne pas la réactiver sans phase dédiée et validation live read-only.

## Japan Edge Hunter — `PROD_V4` lane séparée

PR #89, #94, #101.

- ASK japonais exact, PSA10 ;
- GCC SOLD exact + contexte externe exact lorsque prouvable ;
- ASK jamais introduit dans fair value ;
- `MULTIMARKET_CONFIRMED`, `GCC_EDGE_NOT_GLOBAL`, `MARKET_CONFLICT_BLOCKED`, `GCC_ONLY_UNCONFIRMED` ;
- aucun achat automatique.

---

# Robot KB / Neon — `ROBOT_KB`

Historique durable séparé de V4/V5. Ne jamais utiliser sa présence comme autorisation de mélanger preuve marché et décision production.

## Fondation / ingestion

P0/P1/P3 et PRs #51/#59/#60 :

- observations append-only ;
- provenance + raw payload ;
- mirror passif de discovery V4 ;
- SOLD GCC uniquement quand `status=SOLD + soldAt + prix final` est explicite.

## SOLD lossless et backfill

PR #68/#72/#76.

- watermark durable ;
- lane SOLD fraîche 30 min ;
- backfill historique séparé ;
- max débit par run, jamais limite de couverture ;
- cursor n'avance qu'après ingestion réussie ;
- aucun ENDED/ASK/current auction transformé en SOLD.

## Fixed coverage hybride

PR #62/#75.

- recent + rotation durable + ciblage sous-échantillonné ;
- déduplication listing ;
- état avancé uniquement après succès Neon.

## TCGdex identity cache

Migration/cache construit pour le fallback V5 : seules des identités TCGdex exactes prouvées peuvent remplir le cache. Le cache ne prouve jamais seul une microvariante sensible.

## KB-first — `DEFERRED`

Le hard gate KB-first reste interdit tant que la profondeur exacte carte/langue/grader/grade n'est pas suffisante. Les analytics read-only peuvent mesurer la readiness mais ne doivent pas supprimer les providers externes prématurément.

---

# V5 expérimentale — `V5_ONLY`

PR #8 reste **OPEN / DRAFT / NON MERGED** dans `main`.

Head validé :

```text
bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

## Identité normale

TCGdex + unicité déterministe, microvariant gates fail-closed. PokeTrace n'est pas un resolver de routine.

## PokeTrace market-only / emergency

PR #85/#86/#88.

Chemin emergency seulement après vraie panne technique TCGdex :

```text
TCGdex technical failure
 -> Robot KB proven cache
 -> Pokemon TCG API
 -> PokeTrace emergency-only
 -> fail-closed
```

Éligible : transport, invalid JSON, 408/425/429/5xx. Clean no-match, 404, autres 4xx ne déclenchent pas l'emergency.

Runtime/cache PokeTrace emergency isolé ; budget borné ; aucune metadata provider ne fabrique finish/édition.

## Post-macro applicability / promo semantics

PR #93, mergée uniquement dans V5.

- retry exact TCGdex d'applicabilité microvariante ;
- mapping promo borné ;
- `wPromo` = W-stamp, pas statut promo générique ;
- exact TCGdex uniquement pour lever l'inconnu.

## V5 shadows/deferred

- #92 : PokemonPriceTracker identity shadow ;
- #96 : Pocket digital rejection + curated catalog gap, draft/non mergée dans V5 ;
- aucune de ces PR n'est une autorisation de merge #8 vers `main`.

---

# PPT / Global Multi-Vault / Source Scout

## PokemonPriceTracker — `SHADOW/DEFERRED`

PR #106/#107 sont les clean shadows courants.

- agrégats eBay graded = `SOLD_AGGREGATED`, jamais item-level SOLD ;
- PPT/PokeTrace/eBay peuvent être corrélés ; ne pas les compter naïvement comme marchés indépendants ;
- EN/JA utiles ; FR cross-language reste anchor, pas comparable exact sans calibration.

## Global Multi-Vault — `SHADOW/DEFERRED`

Stack #108→#115 : GCC/Cardova/magi/Fanatics/COMC, fair value commune et adapters stricts.

- #108 foundation ;
- #109 live shadow ;
- #110 rejection diagnostics ;
- #113 retrieval hardening ;
- #114 Magi SOLD filter ;
- #115 COMC Groudon retrieval.

Les child PRs sont stacked. **Ne pas merger directement #113/#114/#115 dans `main`** ; une future intégration doit rebaser/réintégrer sur le `main` courant et revalider.

## Source Scout — `BENCHMARK/DEFERRED`

Branche historique `agent/source-scout-benchmark-20260814` et probes associés. Réutiliser ces benchmarks/policies pour toute nouvelle source au lieu de reconstruire des probes de zéro.

Aucun benchmark vérifié ne prouve un TCGdex `500/500`.

---

# Supersessions importantes

- #54 : `STALE_OPEN/SUPERSEDED`, dépendance déjà absorbée ;
- #111 : ancien snapshot docs, superseded par README/inventaires courants ;
- #126 : ancienne lignée PokeTrace, **DO NOT MERGE** ;
- anciennes PR PPT/Japan shadow remplacées par #106/#107 ;
- anciennes branches temp/diagnostics ne doivent jamais être interprétées comme production.

---

# Phase courante / prochaine action

Phase #123→#135 : **terminée et prouvée en production**.

Le prochain travail fonctionnel doit partir des métriques réelles :

1. laisser le backlog externe se drainer ;
2. mesurer les `NO_MATCH/AMBIGUOUS` qui se répètent ;
3. identifier une classe déterministe nouvelle ;
4. seulement alors coder un correctif fail-closed dédié.

La PR docs #136 ferme cette phase documentaire. Elle ne contient aucun code runtime et ne doit être mergée qu'après revue/validation + autorisation utilisateur explicite.

## Invariants finaux

- V4/main canonique ;
- PR #8 jamais mergée sans autorisation explicite ;
- PokeTrace marché/prix après identité ;
- ASK/live auction != SOLD ;
- RAW != valeur slab ;
- aucune identité/langue/grader/grade/microvariante incompatible mélangée ;
- aucun achat, bid, checkout ou paiement automatique ;
- aucun secret dans repo/logs.
