# GCC Auction Watcher

> **Source de reprise canonique — à lire en premier dans toute nouvelle conversation.**
> Après tout changement important de production, d’architecture V5, de provider, de benchmark ou de workflow, mettre ce README à jour avant de considérer la phase terminée.

## État canonique — 15 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

### Principes non négociables

- **V4 sur `main` = production canonique.**
- **V5 = expérimental, PR #8. Ne jamais merger PR #8 sans autorisation explicite.**
- **Robot KB durable shadow = actif sur Neon PostgreSQL `main`, strictement GET-only, aucun impact V4.**
- Pokémon **cartes individuelles uniquement** ; sealed/lots restent hors scope actuel.
- Discovery V4 : **0–100 €** pour capter les anomalies extrêmes ; `MAX_PRICE=100`.
- Décote minimale utilisateur : **30 %**, avec seuil adaptatif plus exigeant lorsque les preuves sont faibles.
- Fixed + auctions ; une auction n’est économiquement pertinente que si elle finit dans **≤60 min**.
- Aucun achat, bid, checkout ou grading payant automatique.
- `AMBIGUOUS` / conflit matériel = fail-closed. Ne jamais relâcher le matching pour améliorer artificiellement la couverture.
- Une absence de valorisation n’est **pas** un signal négatif : distinguer `pas de marché confirmé` de `mauvaise offre`.

---

# P0 — Card Knowledge Base Foundation (expérimental, hors production)

La branche `agent/p0-card-knowledge-base-foundation` contient le socle isolé `robot_kb/`, gelé GREEN au SHA `946f4b7511f966c00b215a34178b183d01712c3e`. Il n’est importé ni par le watcher V4 ni par ses entrypoints : **aucune décision, valorisation, notification, Fast Lane ou feature flag V4 ne change**.

Principes du socle :

- identité canonique interne (`canonical_set` → `card_family` → `localized_card` → `canonical_card`) ; les IDs TCGdex/GCC/eBay/Cardmarket/TCGplayer/PokeTrace/PSA restent des alias externes ;
- identité inconnue laissée nullable, avec candidats finis, dimensions non résolues, preuves et conflits conservés ;
- provenance par claim et par champ, séparant source, méthode de preuve, directness et état de résolution ; une cible de requête n’est pas une preuve et le silence provider ne crée aucun défaut (`Unlimited`, non-promo, finish standard, etc.) ;
- microvariantes génériques par dimensions/valeurs/profils/assignments et combinaisons autorisées ; Base Set sépare notamment `edition_stamp` de `shadow_treatment` ;
- grader, grade, qualifier, subgrades et certification portés par l’instance/segment gradé, jamais par l’identité du print commercial ;
- ledger marché append-only : ventes, snapshots de listings, agrégats providers, populations et taux FX restent des faits distincts ; une correction insère une nouvelle observation reliée par `REVISION_OF`, sans écraser l’historique ;
- foreign keys, index uniques partiels et triggers imposent l’append-only, la transition unique `DRAFT` → `SEALED`, le fait typé complet, la cohérence sujet/résolution, la clôture des variantes, les relations revision/cancel/void, les normalisations FX exactes et l’absence de faits orphelins.

---

# P1 — Shadow Observation Sidecar (GREEN, durable shadow autorisé)

Le sidecar `robot_kb.sidecar` permet l’ingestion asynchrone et déterministe d’observations de marché réelles (GCC et TCGdex) vers le repository `robot_kb`.

Contrats P1 :

- historique : chaque snapshot/fait est scellé et immuable ; un changement 30 € → 25 € crée deux observations. Une vente économique utilise une identité stable fondée sur la source, le listing, le timestamp de finalisation et le prix/devise final : plusieurs retrievals gardent leur lineage mais ne créent qu’un `SALE_TRANSACTION`. Une finalisation contradictoire du même listing échoue explicitement au lieu de créer une seconde vente silencieuse ;
- preuve brute : la migration forward `0004_sidecar_raw_payload.sql` conserve les octets canoniques reconstructibles dans `source_payload`, adressés par SHA-256 et dédupliqués, puis relie immuablement chaque nouveau `source_record` via `source_record_payload`. Les occurrences de retrieval restent séparées ;
- atomicité : chaque source record et tous ses faits dérivés sont écrits sous un unique transaction/savepoint couvrant source, objet externe, payload, retrieval, observation typée, prix, sujet, claims, résolution et lien d’identité. Toute erreur annule cette unité sans annuler les unités déjà commitées d’autres jobs ;
- identité : une absence provider ne crée jamais `Unlimited`, non-promo, finish normal, sans stamp, édition, shadow ou langue. `SINGLE_CARD` exige positivement soit une cardinalité générique structurée égale à 1, soit le contrat GCC `GCC_SINGLE_COLLECTIBLE_OBJECT` observé dans les payloads réels ;
- ventes : un `SALE_TRANSACTION` GCC exige une preuve finale explicite. Le contrat générique accepte `SOLD` + `soldPrice`/`acceptedOfferPrice` + `soldAt`/`saleOccurredAt`. Le contrat GCC live validé du 14/08/2026 accepte aussi **uniquement dans le scope API explicite `status=SOLD`**, avec un `soldAt` timezone-aware, le couple `priceInCents`/`price` comme prix final. `ENDED`, `COMPLETED`, `SUCCESSFUL`, une simple fin d’enchère, une disparition, un ask ou un `price` sans `SOLD + soldAt` restent des snapshots non vendus ;
- métriques et devises : les alias TCGdex d’une même métrique/segment sont dédupliqués s’ils concordent et la seule métrique conflictuelle est rejetée sinon, sans perdre les métriques indépendantes ;
- diagnostics : les compteurs reflètent les rejets et comportements réels (`sale_candidates_rejected`, `ambiguous_sale_records`, `duplicate_sale_replays`, `metric_alias_conflicts`, `monetary_facts_rejected`, `crawl_batches_truncated`) ;
- isolation : aucun fichier/entrypoint V4 n’importe le sidecar. Une panne collector/normalizer est arrêtée à la frontière de sa source et n’a aucun chemin synchrone vers scoring, alertes, Fast Lane, achat, bid, checkout, grading ou état V4.

---

# P3 — Cloud PostgreSQL Durable Shadow Backend & Neon Production

Le backend PostgreSQL durable permet la persistance cloud continue des observations shadow sans dépendre d'une machine locale.

## Validation P3 & Idempotence

- Socle PostgreSQL initial validé : `agent/p3-postgres-durable-shadow` au SHA **`35f550c2006fd8a143b92151e1c7c5dea5f7b86d`**.
- Head Robot KB après ajout du collecteur GCC SOLD prouvé : **`1d06fe33b6fc640657255e15a8d17251aa02b6ce`**.
- Migrations natives PostgreSQL :
  * `0001_durable_shadow.sql` (checksum `c5357dc1dcfa99121c993c4d4567aae886990bf52ddcfb7ca93fe9266c04dffd`)
  * `0002_trigger_alias_safety.sql` (checksum `9e7cb1d05ec6be333267434109bb07f0ff5dad73a70863b22eb858ed5f45599e`) : remplace trois fonctions trigger pour supprimer tout risque de collision avec les records PL/pgSQL `OLD`/`NEW`, sans altérer les tables ni les données.
- Branche de validation Neon : projet `robot-pokemon-kb` (`square-waterfall-62275912`), branche `p3-migration-validation` (`br-noisy-grass-axr6inqe`), base `neondb`.
- Migration du pilote SQLite historique (`shadow-pilot-2026-08-14.sqlite`, SHA-256 `15f8d165219f2995ec593c7c6a7aeaf42f3fe2029a75c566f8828b56e06ac80a`) : **PASS**.
- Micro-check d'idempotence indépendant : **PASS** (`rows_inserted = 0` lors de la réexécution réelle, counts et fingerprints rigoureusement identiques, ledger inchangé). La branche de validation est conservée pour audit.

## Promotion Neon Production (`main`)

- Projet : `robot-pokemon-kb` (`square-waterfall-62275912`)
- Branche Neon de production : `main` (`br-blue-pond-ax68g15k`), base `neondb`.
- Promotion initiale du pilote : **PASS**, `rows_inserted = 1099`.
- Seconde migration pilote (contrôle d'idempotence immédiat) : **PASS**, `rows_inserted = 0`.
- Intégrité vérifiée :
  * 34/34 payloads bruts du pilote original préservés (octets, longueur et SHA-256 identiques) ;
  * 0 vente fabriquée lors de la promotion initiale ;
  * 0 fait orphelin ;
  * 0 observation non scellée ;
  * 0 foreign key invalide ;
  * 45 `provider_metric_observation` ;
  * Ledger de migration PostgreSQL valide (`0001` + `0002`).

## Collecte Cloud & Secret GitHub Actions

- Secret GitHub repository configuré : `ROBOT_KB_DATABASE_URL` (ne jamais enregistrer, afficher ou commiter sa valeur).
- Workflow cloud shadow : `.github/workflows/robot-kb-cloud-shadow.yml`.
- Le workflow pinne désormais le checkout Robot KB validé au SHA **`1d06fe33b6fc640657255e15a8d17251aa02b6ce`**.
- Premier run cloud manuel réel : Run ID **`31817898878`** — **SUCCESS**.
- Bilan du premier run cloud historique : 50 records GCC collectés (25 fixed + 25 auction), 50 observations acceptées, 0 échec source, 0 `sale_transaction`.
- Validation live du nouveau scope SOLD : run **`31832063222`**, 5 records `status=SOLD` échantillonnés → **5/5 `SALE_TRANSACTION`**, 0 rejet, 0 échec source. Le payload source brut reste immuable/auditable.

## État Neon historique après premier run cloud

Les anciens compteurs ci-dessous décrivent le premier run historique et ne doivent plus être lus comme l’état courant après activation SOLD :

| Table | Lignes |
|---|---:|
| `source_payload` | 84 |
| `source_record` | 84 |
| `source_record_retrieval` | 103 |
| `external_object` | 75 |
| `market_observation` | 145 |
| `listing_snapshot` | 100 |
| `sale_transaction` | 0 |
| `provider_metric_observation` | 45 |
| `field_claim` | 1180 |
| `identity_resolution` | 90 |
| `observation_identity_link` | 145 |

## Collecte Shadow Automatique Schedulée — ACTIVE

- **Statut : ENABLED**
- Déploiement du collecteur SOLD sur `main` : **`78dd3cb72d42647dc996a9fcbe1e8afe21f10348`** (PR #60).
- Pin Robot KB shadow : **`1d06fe33b6fc640657255e15a8d17251aa02b6ce`**.
- Cron GitHub Actions actuel : **`17 * * * *`**, donc toutes les heures à `:17` UTC.
- Biais et bornes de chaque exécution :
  * Rotation durable fixed (`v4_kb_fixed_rotation.py`) : 4 pages de 100 annonces par run (400 annonces fixed/run) avec filtres `sellingTypes=FIXED_PRICE`, `categories=Pokemon`, `itemTypes=CARDS` ;
  * Curseur indépendant persisté (`v4_kb_fixed_rotation_state.json`), avancé uniquement après succès confirmé de l'ingestion Neon ;
  * Wrap sécurisé à la page 1 lorsque l'inventaire est épuisé ;
  * Backup auction (`--live-gcc auction`) : démarre systématiquement à la page 1 `ENDING_SOON` ;
  * Moissonneur de ventes réelles (`--live-gcc sold`) : conserve le contrat validé `SOLD + soldAt` -> `SALE_TRANSACTION` ;
  * requêtes réseau HTTP GET uniquement (`--allow-live-read-only`) ;
  * aucun input automatique de cartes TCGdex en cron (réservé aux déclenchements manuels) ;
  * concurrency sérialisée (`group: robot-kb-cloud-shadow`, `cancel-in-progress: false`) ;
  * timeout borné à 15 minutes ;
  * strictement passif : aucun achat, bid, checkout ou interaction avec la production V4.

---

# V4 — production canonique

## Scheduler / état

Deux cronjobs externes distincts sont utilisés sur Cron-job.org :

```text
GCC Auction Watcher — Main Scanner
    ↓ workflow_dispatch ~toutes les 10 min
.github/workflows/watcher.yml
    ↓
GCC Auction Watcher V4

GCC Auction Watcher — Fast Lane
    ↓ workflow_dispatch toutes les 3 min
.github/workflows/v4-final-auction-check.yml
    ↓
recheck ciblé des auctions déjà armées et arrivant à ≤5 min
```

Règles :

- Ne pas ajouter de `schedule:` GitHub parallèle pour ces deux lanes : cela doublerait les scans.
- `state.json` est restauré/sauvegardé par le Main Scanner via cache GitHub Actions.
- La Fast Lane restaure `state.json` en **lecture seule** et ne possède pas l’état principal.
- La Fast Lane écrit uniquement son namespace de déduplication `final_alerts.json`.
- Concurrency Main Scanner sérialisée, `cancel-in-progress: false`.
- La Fast Lane possède un groupe de concurrency séparé afin de ne pas bloquer le Main Scanner.
- Les runs V4 principaux sont journalisés dans l’issue #1.

### Fast Lane — production active

La Fast Lane a été introduite par PR #45 et est maintenant activée en production.

Feature flag :

```text
V4_FAST_LANE_FINAL_CHECK_ENABLED=true
```

Kill switch immédiat : passer cette variable de repository à `false`.

Comportement :

- ne découvre aucun nouveau listing ;
- ne relance aucun provider marché externe ;
- ne considère que les auctions déjà armées/notifiées dans `state.json` ;
- ne traite que celles arrivant dans la fenêtre finale `≤5 min` ;
- rafraîchit le prix et le timer du lot GCC exact ;
- compare le prix courant au `max_recommended` persistant déjà calculé ;
- affiche l’identité carte relue sur la fiche (nom/personnage, référence, set/série, année/langue/variante si disponibles, grader/grade), et non un heading UI GCC parasite ;
- envoie au maximum une alerte finale dédupliquée si le lot reste sous le plafond ;
- aucune mutation de `state.json` ;
- aucun achat, bid ou checkout.

Le Main Scanner restaure `final_alerts.json` en lecture seule et supprime son propre doublon synchrone de dernière minute lorsque la Fast Lane est activée, ce qui garde une propriété d’alerte finale **exact-once** entre les deux lanes.

### Cron externe / token GitHub

Le cron Fast Lane appelle :

```text
POST https://api.github.com/repos/Champaagnepaapi/gcc-auction-watcher/actions/workflows/v4-final-auction-check.yml/dispatches
Body: {"ref":"main"}
Cadence: */3 * * * *
```

Authentification : fine-grained GitHub PAT limité au repository `Champaagnepaapi/gcc-auction-watcher`, avec permission `Actions: Read and write` et Metadata read-only automatique.

- Le PAT a été créé avec expiration **90 jours** : le renouveler avant expiration.
- Ne jamais stocker le token dans le repo, le README, une issue ou un log.
- Réponse attendue du dispatch GitHub : **HTTP 204 No Content**.

Activation initiale confirmée le 13 août 2026 :

- dispatch authentifié `workflow_dispatch` réussi ;
- run GitHub `31662123261` : success ;
- premier cycle cron automatique confirmé à 04:54 : HTTP 204 ;
- run GitHub `31662233558` : success.

Un suivi multi-cycle est à conserver comme contrôle opérationnel ; aucun faux positif, achat, bid ou checkout n’est autorisé même en cas d’erreur de scheduler.

## Discovery fixed

- Source : API publique GCC `/on-sale-items`.
- File économique : `NEW → CHANGED → NEVER_EVALUATED → STALE`.
- Budget : 120 évaluations/run.
- TTL fixed : 24 h par défaut, avec refresh externe adaptatif décrit plus bas pour les annonces proches du seuil.
- Discovery et couverture économique sont comptabilisées séparément.
- Un prix bas ne crée jamais à lui seul une opportunité.

## Discovery auctions

Source primaire item-level :

```text
/on-sale-items
sellingTypeGroup=AUCTION
sortType=ENDING_SOON
status=ON_SALE
        ↓
endTime individuel
        ↓
Pokémon + carte + 0–100 € + ≤60 min
```

- Le watcher s’arrête lorsque l’ordre `ENDING_SOON` prouve que l’horizon 60 min est franchi ou lorsque l’inventaire est épuisé.
- Statut nominal : `COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS`.
- Le total GCC `ON_SALE` global n’est pas utilisé comme dénominateur de cette fenêtre lorsque son scope est différent (`DIFFERENT_SCOPE_DIAGNOSTIC`).
- L’ancien collector auction reste fallback uniquement si API/pagination/ordre/endTime ne permettent plus de prouver la couverture.
- L’ancien prototype long-wait PR #30 est **supersédé** par la Fast Lane zéro-sleep de PR #45 ; ne pas réintroduire de `sleep` long dans le Main Scanner.

---

# V4 — identité canonique et valorisation multi-marché

Architecture de production introduite par PR #33 :

```text
GCC listing
  ↓
identité canonique TCGdex déterministe
  ├→ GCC history
  ├→ PokeTrace exact card + grader + grade
  ├→ PSA Auction Prices Realized exact grade
  ├→ eBay sold exact grader + exact grade
  └→ TCGdex Cardmarket / TCGplayer RAW
  ↓
arbitrage par force de preuve
  ↓
opportunity / conflict / pending / manual review
```

**Principe central : les sources externes sont évaluées pour toute carte économiquement évaluée, même si GCC possède déjà un historique.** GCC n’est plus un préalable obligatoire à la validation externe.

## TCGdex = identité canonique V4

TCGdex est utilisé comme resolver déterministe avant le marché externe :

- langue localisée conservée ;
- nom exact + `localId` exact ;
- dénominateur `x/y` vérifié contre le set ;
- fallback `set exact + localId exact` ;
- plusieurs candidats exacts sans preuve discriminante → `AMBIGUOUS` ;
- `004/102` et `4/102` peuvent être normalisés numériquement ; `4/102` et `4/130` restent incompatibles ;
- aucun Levenshtein, substring, containment ou fuzzy ratio comme preuve d’identité.

Le titre/identité listing n’est jamais silencieusement remplacé ; les IDs TCGdex sont attachés comme provenance structurée.

## Scope PSA V4

Production PSA volontairement limitée à :

```text
PSA 8
PSA 8.5
PSA 9
PSA 10
```

- PSA <8 : exclu du pipeline économique production.
- PSA 9.5 : ne pas fabriquer/accepter cette note comme grade PSA de production, même si certains providers exposent des tiers génériques de demi-grade.
- Les autres graders gardent leurs échelles valides existantes.

Objectif : concentrer les budgets sur les slabs ayant le plus de valeur/liquidité et éviter les grades bas avec marché externe très pauvre.

## PokeTrace = marché gradé externe

- Auth : `X-API-Key` uniquement.
- Preflight : `/auth/info`.
- Plans acceptés pour graded : Pro / Growth / Scale.
- Budget V4 : max 40 requêtes PokeTrace/run.
- Pacing : 0.40 s.
- `/cards` fournit l’agrégat de prix ; le endpoint Scale listing-level n’est pas requis par cette V4.

Une preuve PokeTrace automatique forte exige notamment :

- identité macro TCGdex exacte ;
- même grader ;
- même grade exact ;
- dimensions commerciales compatibles ;
- au moins 3 ventes agrégées ;
- dispersion non élevée ;
- provenance langue/marché prouvable.

### Sécurité microvariantes

La metadata candidate PokeTrace **ne devient jamais une preuve du variant du listing**.

- First Edition provider sans preuve listing → bloque ;
- si TCGdex indique que First Edition est applicable mais que l’édition listing est inconnue → bloque ;
- plusieurs finishes possibles dans le catalogue + finish listing inconnu → bloque ;
- un finish provider peut être accepté automatiquement uniquement si le catalogue exact prouve qu’il n’existe qu’un seul finish possible compatible ;
- édition, Shadowless, promo/stamp, Cosmos/Galaxy/Cracked Ice/Poké Ball/Master Ball et autres dimensions sensibles restent fail-closed.

## PSA APR / eBay

PSA APR et eBay restent des providers indépendants :

- PSA : APR exact grade en priorité, puis eBay exact en fallback ;
- non-PSA : eBay même grader + même grade ;
- langue/édition/finish/variant sensibles doivent être prouvés, pas seulement non contradits.

### PSA APR web hydration et diagnostics anti-bot

PR #32 a corrigé le race condition de la page publique APR :

- attente bornée du champ de recherche client-rendered ;
- attente bornée du bouton Search ;
- puis délégation au scraper strict existant ;
- timeout/anti-bot/erreur restent fail-closed.

PR #46 améliore ensuite le **diagnostic** de cette voie :

- inspecte HTTP 403 / 429 / 4xx / 5xx avant le contrôle du formulaire ;
- reconnaît les pages de challenge anti-bot (Cloudflare, PerimeterX, Datadome, CAPTCHA, etc.) ;
- évite de masquer un vrai blocage WAF sous le message générique `formulaire APR indisponible` ;
- conserve le fail-closed et les fallbacks.

Important : **PR #46 ne rend pas PSA APR “disponible” lorsqu’un WAF bloque GitHub Actions.** Elle corrige la classification et l’observabilité. En cas de 403/challenge réel, APR reste transitoirement indisponible et eBay/fallbacks continuent selon les règles existantes.

Cette voie utilise la **page web publique APR**, pas l’ancienne API Collectors publique.

## RAW multi-provider : consensus robuste, microvariantes et observabilité (Backport V5 → V4)

V4 intègre un moteur de consensus multi-marché RAW (`v4_raw_consensus.py`) couvrant **Cardmarket**, **JustTCG**, **TCGplayer**, **PriceCharting** et **eBay RAW**. En production, seuls **Cardmarket** et **TCGplayer**, attachés à l'identité carte TCGdex déterministe, alimentent le consensus ; JustTCG, PriceCharting et eBay RAW restent des adaptateurs diagnostiques/hors-ligne.

Règle absolue :

```text
RAW market ≠ valeur du slab gradé
```

Le RAW :

- ne crée jamais une estimation PSA/PCA/BGS/CGC ;
- ne crée jamais `max_recommended` ni d'achat/enchère automatique ;
- sert exclusivement de **signal d'alerte pour revue manuelle humaine**.

### Pipeline de validation & Backport sélectif V5 → V4
Le pipeline RAW de V4 s'articule autour des composants matures backportés de V5 :
1. **Fournisseurs de production live vs adaptateurs spécialisés** :
   - **Production live** : Cardmarket et TCGplayer via les données de prix rattachées à une résolution exacte TCGdex.
   - **Adaptateurs spécialisés** : JustTCG, PriceCharting et eBay RAW sont conservés pour les tests et diagnostics hors-ligne. Une réponse incomplète reste observable, mais ne peut pas entrer dans le quorum.
2. **Parser multilingue déterministe** : Extraction stricte des éditions (1ère Édition, 1. Edition, Prima Edizione, Unlimited), finitions (Holo, Reverse Holo, Nicht-Holo, Olografica) et finitions spéciales (Poke Ball, Master Ball, Cosmos, Galaxy, Cracked Ice). Les contradictions de titre échouent immédiatement en `__conflict__` fail-closed.
3. **Validateur de microvariantes (*Microvariant Gate*) & Normalisation sémantique** :
   - Blocage systématique des comparables incompatibles (`FINISH_MISMATCH`, `EDITION_MISMATCH`, `PROMO_MISMATCH`, `LANGUAGE_MISMATCH`, `SET_MISMATCH`, `NUMBER_MISMATCH`).
   - Validation symétrique des promos (rejet listing promo vs provider régulier ET listing régulier vs provider promo).
   - Normalisation multi-tokens robuste des éditions (espaces, tirets, camelCase, compact, ordinaux multilingues : *1ère Édition, 1. Edition, 1a Edición, Prima Edizione, Unlimited, Shadowless*).
   - Décomposition des labels composés (*1stEditionHolofoil, 1steditionreverseholo, unlimitedholofoil*) avec vérification indépendante de chaque dimension.
4. **Provenance explicite des dimensions d'identité** :
   - Chaque dimension requise et applicable est classée `PROVIDER_PROVEN`, `CATALOG_PROVEN` ou `UNKNOWN`. La valeur demandée par le listing ou la requête est une cible de comparaison, jamais une preuve.
   - Un fournisseur ne peut compter vers un consensus RAW `STRONG` / éligible à notification que si **toutes** ses dimensions requises et applicables sont `PROVIDER_PROVEN` ou `CATALOG_PROVEN`.
   - Une dimension requise `UNKNOWN` laisse la donnée fournisseur visible dans les diagnostics, mais exclut ce fournisseur de `providers_used` et du quorum indépendant. Deux fournisseurs incomplets ne peuvent donc jamais se combiner en `STRONG`.
   - Cette règle est appliquée dans la couche commune d'arbitrage, y compris lorsque les adaptateurs sont appelés directement ou hors-ligne.
5. **Preuve catalogue déterministe (*Catalog Proof*)** :
   - La preuve catalogue n'est pas limitée au finish. Une identité carte exacte et déterministe TCGdex peut prouver une dimension applicable uniquement lorsque l'invariant catalogue établit réellement cette dimension ; elle peut notamment porter le set, le numéro de collection, un finish unique ou une édition explicitement déterminée.
   - Exemple de finish prouvé : une seule variante existe (`variants = {"normal": False, "holo": True, "reverse": False}`). La simple présence de `firstEdition: true` indique que l'édition est applicable ; elle ne prouve pas, à elle seule, l'édition exacte du lot.
   - Pour une carte où First Edition / Unlimited est applicable, l'édition doit être prouvée par le fournisseur ou par un invariant catalogue déterministe valide. Le silence d'un fournisseur n'implique jamais Unlimited. Une édition explicitement contradictoire est rejetée.
   - Lorsque l'édition est réellement non applicable au produit, son omission par le fournisseur est admise.
6. **Rejet des anomalies statistiques (*Anti-Outlier Engine*)** :
   - Déconnexion du plancher (*Floor Disconnect*) : détection des écarts anormaux entre trend/avg30 et `low`.
   - Rupture inter-périodes (*Period Divergence*) : détection des effondrements récents (`avg7 < 0.45 * avg30`).
   - Rejet de contamination (`OUTLIER_CONTAMINATION`) lorsque les fournisseurs indépendants concordent.
7. **Observabilité, Filtrage des paliers & Consensus multi-sources** :
   - Traçabilité complète du statut de chaque fournisseur (`ACCEPTED`, `DOWNWEIGHTED`, `REJECTED`) avec reason codes standardisés (`EXACT_COMPATIBLE`, `OUTLIER_CONTAMINATION`, `LANGUAGE_MISMATCH`, `FINISH_MISMATCH`, `PROVIDER_DISAGREEMENT`, etc.).
   - Filtrage strict de compatibilité dimensionnelle sur chaque palier avant inclusion dans l'enveloppe de variantes ambiguës.
   - En production V4, le consensus RAW s'appuie exclusivement sur Cardmarket et TCGplayer via TCGdex ; les adaptateurs JustTCG/PriceCharting/eBay RAW restent isolés pour les tests et diagnostics hors-ligne.
   - Les opportunités de notification RAW exigent un consensus $\ge 2$ fournisseurs indépendants, compatibles et entièrement prouvés. Une source unique complète reste diagnostique / `WEAK` ; une source incomplète reste `DIAGNOSTIC_ONLY` et ne compte jamais vers ce seuil.
   - Les conflits ou désaccords inter-fournisseurs (`disagreement_ratio > 1.30`) bloquent strictement l'utilisation de l'ancre RAW dans le price-discovery.

### Observabilité du Backlog Externe & ETA Réaliste
La couverture économique sépare strictement :
- `FIRST_EVALUATION_COVERAGE` : achèvement du premier passage d'évaluation interne (lots `P0_NEW`, `P1_CHANGED`, `P2_NEVER_EVALUATED`) ;
- `EXTERNAL_MARKET_COVERAGE` : achèvement de la file externe `P4_EXTERNAL_PENDING` ;
- `EXTERNAL_PENDING_BACKLOG` : nombre exact de lots en attente de validation externe ;
- `realistic backlog ETA` : simulation exacte du drainage de file tenant compte de la priorité stricte des lots urgents (P0/P1) préemptant la capacité et du plafond dédié P4 (10 lots/run max), garantissant l'absence de sous-estimation de l'ETA.

Un run ne peut plus déclarer une couverture globale complète ni un résultat digne de confiance (`economic result trustworthy = YES`) tant qu'un backlog P4 subsiste.

### Écart de Grader & Découverte de Prix Asymétrique (*Grader Spread & Price Discovery*)
Le module `v4_price_discovery.py` permet d'exploiter la valeur asymétrique de slabs secondaires ou peu liquides :
1. `CROSSGRADE_OPPORTUNITY` : Slabs secondaires de très haut grade (PCA 10 / BGS 9.5 / CGC 10) bénéficiant d'un spread face au benchmark PSA [DIAGNOSTIC / NON-LIVE en production V4 tant qu'aucun flux crossgrade réel n'est injecté].
2. `SECONDARY_GRADER_DISCOUNT` : Marché secondaire liquide mais décoté significativement par rapport à la valeur équitable.
3. `SAME_GRADER_MARKET_DISCOUNT` : décote soutenue par des ventes SOLD même grader + même grade ; ne doit pas être étiquetée comme spread inter-grader.
4. `ILLIQUID_PRICE_DISCOVERY` : Liquidité exacte faible sur le slab considéré, mais multiples ancres adjacentes solides (PSA 10 vendu récent, consensus RAW, ventes historiques GCC) prouvant une décote asymétrique majeure.

### Ajustement Temporel Multi-Grader (*Temporal Cross-Grader Adjustment*)
Pour éviter qu'une vente ancienne sur un grader secondaire (ex: SGS 8 vendu 18 € il y a un an) n'ancre artificiellement à la baisse l'estimation actuelle lorsque le marché global (PSA 8) a fortement progressé :
- **Calcul du ratio historique** : $\text{ratio} = \frac{\text{prix historique grader cible}}{\text{prix historique référence PSA}}$.
- **Rebasement actuel** : $\text{estimation ajustée} = \text{valeur robuste PSA actuelle récente} \times \text{ratio historique}$.
- **Filtrage robuste des anomalies** : Médiane robuste sur les ratios historiques observés pour neutraliser tout outlier isolé.
- **Préservation de la décote spécifique** : Aucun postulat d'égalité naïve SGS = PSA ; le spread de grader est préservé de manière explicite.
- **Fail-closed sans extrapolation aveugle** : Si aucune référence récente de même grade n'existe, le pipeline bascule en revue manuelle sans inventer d'estimation chiffrée (`MANUAL_REVIEW_NO_ESTIMATE`).
- **Hiérarchie stricte des preuves** :
  $$\text{EXACT\_RECENT\_COMP} > \text{EXACT\_OLD\_COMP\_TEMPORALLY\_ADJUSTED} > \text{CROSS\_GRADER\_ESTIMATE\_ONLY} > \text{MANUAL\_REVIEW\_NO\_ESTIMATE}$$
- **Surfaçage exclusif en Revue Manuelle** : Aucune décision d'achat, d'enchère ou de paiement automatique.

**Principes de sécurité :**
- `LOW_LIQUIDITY` est une caractéristique d'incertitude (`uncertainty = HIGH`), jamais un rejet automatique.
- La probabilité de crossgrade est facultative (`crossgrade_required = false`) et purement diagnostique.
- Les annonces actives seules (*active asks*) ne créent jamais d'opportunité.
- Les ancres trans-linguistiques (ex. PSA 10 anglais vs slab français) sont explicitement décotées et augmentent l'incertitude.
- Les slabs de bas grade (ex. note $\le 7$) ne peuvent pas utiliser d'ancre PSA 10 sans échelon intermédiaire.

---

# V4 — arbitrage économique

Forces : `STRONG`, `WEAK`, `UNAVAILABLE`.

Chemins principaux :

- `GCC_ONLY`
- `GCC_EXTERNAL_CONFIRMED`
- `EXTERNAL_RESCUE`
- `EXTERNAL_PENDING`
- `MARKET_CONFLICT_BLOCKED`

Règles :

- GCC fort + externe fort concordant → confirmation prudente ;
- GCC faible/indisponible + externe fort → `EXTERNAL_RESCUE` possible ;
- deux marchés forts contradictoires → blocage ;
- provider indisponible ≠ no-match ;
- budget épuisé → pending/requeue, jamais faux no-match ;
- une panne PokeTrace n’empêche pas APR/eBay d’être tentés ;
- une réponse APR/eBay faible/propre ne masque pas un transient/rate-limit PokeTrace dans un cache 24 h.

Concordance forte GCC/externe :

- intervalles prudents `low/high` qui se chevauchent ;
- ratio des centres dans `0.80–1.25`.

### Sémantique des titres de notification

Depuis PR #56 :

- `GCC_EXTERNAL_CONFIRMED` → **`FORTE OPPORTUNITÉ CONFIRMÉE`** ;
- `EXTERNAL_PENDING` → **`OPPORTUNITÉ GCC — EXTERNE EN ATTENTE`** ;
- `GCC_ONLY` → **`OPPORTUNITÉ GCC — EXTERNE NON CONFIRMÉ`**.

Une alerte ne doit donc plus laisser croire qu’un marché externe a confirmé la fair value lorsqu’il est encore pending ou absent.

## Cache externe et rafraîchissement adaptatif

PR #47 active le rafraîchissement adaptatif des **fixed listings uniquement** :

- clé hashée d’identité commerciale stricte ;
- TTL par défaut 24 h ;
- rafraîchissement adaptatif (TTL 1–6 h) pour les annonces proches du seuil d’opportunité :
  - gap ≤ 3 % du seuil requis → TTL 1 h ;
  - gap ≤ 6 % du seuil requis → TTL 2 h ;
  - gap ≤ 10 % du seuil requis → TTL 3 h ;
  - gap ≤ 15 % du seuil requis → TTL 6 h ;
  - gap > 15 % ou sans estimation → TTL standard 24 h ;
- les auctions conservent le cache externe standard 24 h et s’appuient sur leur boucle ending-soon dédiée ;
- réévaluation prioritaire dans la file fixed `P3_STALE` sans famine des files `P0_NEW`, `P1_CHANGED`, `P2_NEVER_EVALUATED` ;
- après refresh, l’économie est recalculée **depuis les nouvelles preuves**, jamais promue depuis une valeur stale ;
- schéma versionné ;
- `MATCHED`, `CLEAN_NO_MATCH`, `CLEAN_INSUFFICIENT` cachables ;
- `PROVIDER_ERROR`, `TRANSIENT_UNAVAILABLE`, `RATE_LIMIT` jamais cachés comme résultat propre ;
- budget pending reste requeue ;
- les budgets providers restent bornés.

Le schéma est bumpé lors de l’activation PokeTrace afin d’éviter de réutiliser comme vérité des entrées antérieures à la couche multi-marché.

---

# V4 — enchères / notifications

`max_recommended` reste le plafond prudent de référence.

Pour une opportunity auction :

- prix courant > `max_recommended` → pas de notification ;
- la notification affiche `Prix max conseillé` ;
- `EXTERNAL_RESCUE` calcule le plafond depuis l’estimation externe retenue ;
- `GCC_EXTERNAL_CONFIRMED` le calcule depuis l’estimation prudente combinée ;
- rappels temporels réutilisent le même plafond ;
- la Fast Lane de dernière minute réutilise **le même `max_recommended` persistant** et ne le recalcule pas avec des providers externes.

Anti-spam opportunity : renotifier principalement si :

- prix baisse ≥10 % ;
- décote s’améliore ≥5 points ;
- franchissement d’un seuil temporel.

Aucun code ne place une enchère automatiquement.

---

# Validation V4 multi-marché

PR #33 source head validé :

```text
05c0e638678a698269e4fd89a7b49fb356eb87b5
```

GitHub Actions :

```text
run 31579694767
job 94059724327
```

Résultat :

- **304/304 tests V4** ;
- compilation des nouveaux/anciens entrypoints V4 : OK ;
- `git diff --check` : OK ;
- auction comparison live read-only : primary 16 / legacy 16 ;
- primary-only 0 ; legacy-only 0 ; unresolved 0 ; PASS ;
- aucune action économique/ntfy/bid/purchase/checkout/state mutation dans cette comparaison.

Régressions spécifiques : identité TCGdex exacte/ambiguë, dénominateurs, scope PSA, PokeTrace grade exact, non-héritage premium, edition/finish unknown fail-closed, transient/rate-limit non cachés, fallback APR/eBay indépendant, RAW manual-review, encodage ntfy et wiring production.

## Déploiements V4 du 13 août 2026

### PR #45 — Fast Lane finale

Merge production :

```text
0978aa50309fc850f6c8b9e18743ea8011bd2444
```

- architecture zéro-sleep ;
- workflow séparé `v4-final-auction-check.yml` ;
- safe-off par défaut tant que le flag n’est pas activé ;
- état principal lecture seule ;
- `final_alerts.json` séparé ;
- simulations des deux ordres de concurrence : une seule alerte finale totale ;
- aucun provider externe dans la lane finale ;
- aucune action d’achat/bid/checkout.

### PR #46 — diagnostics PSA APR

Merge production :

```text
fdf2c273b732e1c91dfc8a40f8540f31a9a92f02
```

Classification explicite des 403/429/5xx/challenges avant le test de présence du formulaire ; aucune tentative de contournement anti-bot.

### PR #47 — refresh marché adaptatif

Merge production :

```text
0df59c2140af22410a082fea9a673dc0f6f599a4
```

Validation PR :

- **364 tests passés** ;
- `compileall` : OK ;
- `git diff --check` : clean ;
- budgets providers inchangés et bornés ;
- refresh 1–6 h réservé aux fixed listings proches du seuil.

---

# V5 — expérimental, PR #8, NE PAS MERGER

PR : **#8**  
Branche : `agent/v5-poketrace-cardmarket-market-data`

Head V5 canonique actuellement vérifié :

```text
df4df3da2ae90bc8083ccfcfa108e4010a2c4d05
```

État :

- open ;
- draft ;
- non mergée ;
- base `main` a encore avancé depuis la dernière synchronisation V5 ;
- ne pas resynchroniser/merger aveuglément : auditer les changements V4 d’abord.

Architecture V5 :

```text
eBay metadata
  ↓
TCGdex exact multilingual
  ↓
PokeTrace fallback identité / marché
  ↓
Pokémon TCG API fallback
  ↓
visual matcher local + OCR
  ↓
local deterministic microvariant detector
```

Principes V5 :

- TCGdex principal ;
- PokeTrace fallback identité + provider marché ;
- bridge set TCGdex ↔ PokeTrace déterministe uniquement ;
- candidate provider premium ≠ preuve listing ;
- détecteur microvariante local par références différentielles ;
- First/Unlimited/finish sensibles fail-closed ;
- pas de listing/image/OCR eBay persisté ;
- aucun achat/bid/checkout/CardGrader automatique.

### Bridge set V5

Le bridge ne peut prouver le set d’un candidat PokeTrace que si nom + numéro sont déjà exacts et qu’une relation déterministe existe :

- nom officiel exact ;
- jumeau anglais TCGdex exact (`card.id + set.id + localId`) ;
- observation exacte en mémoire ;
- mapping versionné minimal et explicite.

Aucun fuzzy/substr/Levenshtein/containment comme preuve.

### PR V5 enfant #31

Branche : `agent/v5-deterministic-catalog-uniqueness`.

Objectif : autoriser une résolution macro `2 champs sur 3` uniquement lorsque TCGdex prouve l’unicité :

- nom exact + numéro complet → set récupérable si résultat unique ;
- set exact + nom exact → numéro récupérable si résultat unique ;
- numéro seul / set seul → jamais suffisant ;
- ambiguïté → bloque.

PR #31 reste séparée tant qu’elle n’est pas explicitement intégrée à la branche V5 canonique.

### PR V5 enfant #44 — parser finish eBay

PR #44 a été mergée **dans la branche V5 canonique uniquement**, jamais dans `main` :

```text
head source: 136dcc6fca27c4cf39abfaacae9de237304484a6
merge V5:    df4df3da2ae90bc8083ccfcfa108e4010a2c4d05
```

Elle durcit la résolution déterministe des finishes explicitement présents dans le titre eBay :

- parser par span-masking des phrases finish explicites ;
- conservation d’un finish spécial explicite compatible lorsque la metadata structurée reste générique ;
- prévention des faux conflits provoqués par des tokens `holo` résiduels ;
- pattern Poké Ball resserré ;
- aucune relaxation fuzzy de l’identité.

PR #8 reste draft et non mergée après cette intégration.

---

# Workflows GitHub Actions à conserver

1. `GCC Auction Watcher` — V4 production Main Scanner.
2. `GCC Final Auction Check` — V4 Fast Lane finale, déclenchée extérieurement toutes les 3 min.
3. `V4 Auction Discovery Validation` — CI + comparaison discovery read-only.
4. `V4 GCC Coverage Audit` — audit couverture V4.
5. `PSA Public API Diagnostic` — diagnostic PSA/APR historique.
6. `Robot KB cloud shadow` — Sidecar shadow durable PostgreSQL schedulé **chaque heure à :17 UTC** et manuel.
7. `V5 Live Raw Pipeline Diagnostic` — live V5 manuel.
8. `V5 Catalog Identity Benchmark` — benchmark identité.
9. `V5 GCC Catalog Refresh` — catalogue cumulatif GCC.

Éviter les workflows temporaires/redondants lorsqu’un workflow existant suffit.

---

# Gouvernance avant tout merge futur

## V4

Avant merge vers `main` :

- full V4 tests verts ;
- compile ;
- YAML ;
- `git diff --check` ;
- discovery/coverage inchangée sauf changement explicitement voulu ;
- aucune action d’achat/bid/checkout ;
- auditer les providers/caches et les effets prod ;
- pour tout changement Fast Lane, vérifier explicitement ownership de `state.json`, déduplication cross-lane et comportement safe-off.

## V5

Avant toute intégration de PR #8 :

- autorisation explicite utilisateur obligatoire ;
- auditer base/head/ancestry ;
- V4 production ne doit pas régresser ;
- vérifier gates microvariantes et provenance langue/set ;
- live contrôlé manuel avant toute décision de merge.

**PR #8 reste expérimentale et non mergée par défaut.**

---

# Déploiements du 14 août 2026 — Edge Hunter / notifications / Robot KB SOLD

## PR #53 — Edge Hunter P0

Merge production :

```text
1d29cbfaa7b17c5a08e6450813f956573cf9ec12
```

- canonicalisation multilingue avant raisonnement Edge Hunter : FR/EN/JP et principales autres langues convergent vers un code canonique ;
- `EXACT_*` interdit si l’identité canonique minimale n’est pas résolue ;
- `SAME_GRADER_MARKET_DISCOUNT` séparé de `SECONDARY_GRADER_DISCOUNT` ;
- discovery GCC non plafonnée par les budgets de valorisation/providers ;
- coverage discovery vs économique explicitement séparée.

Validation : **449/449 tests V4 PASS**, compile/diff PASS. Contrôle production `31826408879 / 94851490641` : auction discovery complète sur son scope, `pages_failed=0`, `incomplete_reasons=NONE`.

## PR #55 — identité dans la Fast Lane ≤5 min

Merge production :

```text
9281c7fdfbda1e680904afec77d623dd2ff86e38
```

La notification finale n’utilise plus un heading UI GCC parasite comme `Aucune note plus élevée #...` : elle relit et affiche l’identité réelle disponible de la carte. Économie, prix/timer, état et `max_recommended` inchangés.

## PR #56 — marché externe explicite dans les titres

Merge production :

```text
93842e061a77b9f1af095b9190a7d14a04832cb0
```

`FORTE OPPORTUNITÉ CONFIRMÉE` est réservé au chemin réellement confirmé par marché externe ; `EXTERNAL_PENDING` et `GCC_ONLY` sont annoncés comme tels. Aucun changement de valorisation.

## PR #57 — Mislisted Slab Hunter PSA, SAFE-OFF

Merge production du code :

```text
003f2ec079e13dc6110b05cceb36e5b58191e481
```

Le module conserve le `serialNumber` GCC et sait classifier un conflit metadata ↔ certificat officiel :

- certificat > metadata → `POSITIVE_GRADE_MISMATCH` / revue manuelle ;
- certificat < metadata → `NEGATIVE_GRADE_MISMATCH` / blocage fail-closed de la valorisation au grade supérieur ;
- scénarios FV séparés lorsque des comps GCC sont disponibles ;
- aucun achat/bid/checkout.

**État production : SAFE-OFF** via `V4_MISLISTED_SLAB_HUNTER_ENABLED=false`. Le test live direct du certificat PSA depuis GitHub Actions (`31832260643`) a retourné un HTTP error/WAF : ne pas contourner l’anti-bot et ne pas activer cette lane tant qu’une source officielle/robuste n’est pas validée. La comparaison **image réelle du slab ↔ metadata** reste la prochaine extension ; le code actuel ne prétend pas faire de vision/OCR live.

## Robot KB — PR #59 + PR #60 : ventes GCC finales prouvées

Merge Robot KB P3 :

```text
1d06fe33b6fc640657255e15a8d17251aa02b6ce
```

Déploiement workflow cloud shadow sur `main` :

```text
78dd3cb72d42647dc996a9fcbe1e8afe21f10348
```

- collecteur GET-only `sellingTypeGroup=AUCTION&status=SOLD` ;
- contrat live validé : `status=SOLD` + `soldAt` + `priceInCents/price` = vente finale prouvée GCC ;
- `ENDED` ou absence de `soldAt` reste un snapshot ;
- validation live `31832063222` : **5/5** rows SOLD stockées en `SALE_TRANSACTION`, 0 source failure ;
- le cloud shadow Neon collecte désormais `fixed + auction + sold` toutes les heures à `:17` UTC ;
- aucune modification de V4/V5, aucun achat/bid/checkout.

**V5 PR #8 reste expérimentale, draft et non mergée.**

---

# PR #63 — Mislisted Slab Hunter cert-first + OCR fallback

État candidat V4 validé au SHA **`c59ddc09bc4913c045b2112bd74931478a88fa89`**.

Ordre de preuve :

1. lire grader + numéro de certificat GCC ;
2. interroger le vérificateur officiel du grader lorsqu’un adaptateur robuste existe (**PSA + CCC** dans ce batch) ;
3. comparer grade officiel ↔ grade metadata GCC ;
4. seulement si le certificat est indisponible/non lisible, tenter l’OCR de l’étiquette du slab ;
5. une preuve OCR seule reste `IMAGE_ONLY`, non confirmée et **MANUAL REVIEW**.

Règles :

- certificat officiel > OCR image ;
- `POSITIVE_GRADE_MISMATCH` : alerte manuelle, mais la valorisation V4 normale reste basée sur la metadata tant qu’un humain n’a pas confirmé ;
- `NEGATIVE_GRADE_MISMATCH` : alerte manuelle + blocage de l’opportunité économique normale afin de ne jamais valoriser au grade GCC surestimé ;
- OCR ambigu (ex. note globale + subgrades différents) → aucune conclusion automatique ;
- grader sans vérificateur officiel supporté → fallback OCR uniquement ;
- aucun achat, bid, checkout, paiement ou grading automatique.

Runtime production proposé : `V4_MISLISTED_SLAB_HUNTER_ENABLED=true`, `V4_MISLISTED_IMAGE_OCR_ENABLED=true`, Tesseract installé par le workflow si absent.

Validation PR #63 : run **`31836557339`**, job **`94884024784`** — **466/466 tests V4 PASS**, compilation PASS, `git diff --check` PASS, comparaison discovery live PASS (`legacy_only=0`, `private safety-net failures=0`).

---

# PR #64 — extension des vérificateurs officiels de certificats

Le Mislisted Slab Hunter conserve l'ordre **certificat officiel d'abord, OCR en fallback** et étend les adaptateurs de vérification à : **PCA, CGC, Beckett BGS/BVG/BCCG, SGC, SGS, CollectAura/CA, ACE, GRAAD, AP Grading et GEM**, en plus de **PSA + CCC** déjà présents.

Règles inchangées :

- grade officiel trouvé → comparaison directe avec le grade GCC ;
- certificat introuvable, bloqué ou grade non lisible → fallback OCR du slab ;
- grader sans adaptateur officiel robuste → fallback OCR ;
- OCR seul = preuve non confirmée, `IMAGE_ONLY` / revue manuelle ;
- mismatch positif = piste de mislisting en revue manuelle ;
- mismatch négatif = blocage de l'alerte économique au grade GCC surestimé ;
- parser officiel strict : un subgrade, une population ou un autre nombre ne peut pas devenir silencieusement la note globale ;
- aucun achat, bid, checkout ou paiement automatique.

Validation PR #64 : run **`31838778755`**, job **`94890915083`** — **482/482 tests V4 PASS**, compilation PASS, `git diff --check` PASS, comparaison discovery live PASS (`legacy_only=0`, `private safety-net failures=0`).

---

# PR #65 — PSA/PCA/CCC cert-first + OCR ciblé conservateur

- Branche : `agent/v4-psa-pca-ccc-ocr-hardening`.
- Priorité runtime : **PSA / PCA / CCC** pour les incohérences de slab ; les autres vérificateurs officiels déjà supportés restent disponibles.
- Ordre : **certificat officiel du grader → comparaison grade GCC ↔ grade officiel → OCR ciblé uniquement si le certificat est indisponible/non lisible**.
- CCC : validation live depuis GitHub Actions sur le certificat `544340143` → **grade officiel 9**, alors que des subgrades incluent notamment 9.5 ; le parser ne promeut pas les subgrades.
- PSA : lookup officiel conservé, mais le smoke test GitHub Actions courant retourne `CERT_UNAVAILABLE`; aucun contournement WAF/anti-bot.
- PCA : le site renvoie actuellement une vérification anti-bot à GitHub Actions ; `CERT_UNAVAILABLE`, aucun contournement.
- OCR fallback **uniquement PSA/PCA/CCC** :
  * ROI top-label spécifique par grader (zone droite/haute) ;
  * exclusion explicite `CENTERING/CENTRAGE`, `EDGES/CÔTÉS`, `CORNERS/COINS`, `SURFACE` ;
  * Pillow upscale/contraste/netteté ;
  * trois vues Tesseract et **au moins deux lectures concordantes**.
- Sécurité :
  * `NEGATIVE_GRADE_MISMATCH + OFFICIAL_CERT` = safety gate, opportunité économique bloquée ;
  * `IMAGE_ONLY` positif ou négatif = **manual review seulement**, jamais de changement/blocage de valorisation ;
  * OCR ambigu/illisible = aucune conclusion fabriquée.
- Benchmark OCR read-only `31868591602` / job `94973448924` : 24 slabs (8 PSA, 8 PCA, 8 CCC) → **4 exacts, 0 faux, 12 ambigus, 8 indisponibles** ; précision des lectures acceptées **100 %**, couverture volontairement prudente.
- Diagnostic cert live `31869307027` / job `94975334499` : CCC `544340143` = 9 confirmé ; PSA indisponible depuis Actions ; PCA challenge anti-bot.
- Validation PR #65 initiale : run `31869485436`, job `94975774681` → **490/490 tests PASS**, compile PASS, `git diff --check` PASS, discovery live 49/49 vs legacy, `primary_only=0`, `legacy_only=0`, private failures 0.
- Aucun achat, bid, checkout ou paiement automatique.
- V5 PR #8 reste **inchangée et non mergée**. Pour une future transposition V5, concentrer d’abord le slab mismatch sur PSA/PCA/CCC sauf instruction contraire.

---

# PR #66 — Manual slab review sur cert + OCR non résolus

- Branche : `agent/v4-unresolved-slab-manual-review`.
- Scope : **PSA / PCA / CCC uniquement** pour ce nouveau signal de revue ; les autres graders gardent leur comportement existant.
- Ordre inchangé : **certificat officiel du grader → OCR ciblé du label en haut à droite si le certificat ne résout pas le grade → arbitrage économique V4 normal**.
- Si le certificat officiel reste indisponible/non lisible **et** que l'OCR ciblé reste `IMAGE_GRADE_AMBIGUOUS` ou `IMAGE_GRADE_UNAVAILABLE`, le lot reçoit un marqueur `CERT_AND_OCR_UNRESOLVED` ; ce marqueur ne change ni la fair value, ni le prix max, ni la décision économique.
- Une notification dédiée **`MANUAL SLAB GRADE REVIEW`** n'est envoyée que si le lot marqué devient ensuite une **opportunité économique finale V4**. Elle contient identité, grader/grade GCC, numéro/statut cert, statut OCR, prix, fourchette/centrale V4, prix max conseillé, décote et URL.
- Anti-spam : l'alerte de revue est persistée et envoyée une seule fois pour l'opportunité concernée ; une carte non retenue économiquement ne génère pas cette notification.
- Interprétation : un échec du lookup certificat peut être technique (anti-bot, indisponibilité, parsing) et **n'est jamais traité seul comme preuve de mislisting**. La notification exige une vérification manuelle du cert officiel et de la photo du slab avant décision.
- Sécurité inchangée : un mismatch négatif confirmé par **OFFICIAL_CERT** reste le seul safety gate de grade ; un signal OCR seul reste `IMAGE_ONLY` / manual review et ne réécrit jamais la valorisation.
- Validation code au head **`a1f9409dba53d0b3c831cc3bead0bb581d241c5a`** : run **`31872649742`**, job **`94983553903`** → **498/498 tests PASS**, compile PASS, `git diff --check` PASS ; discovery live primaire **73** vs legacy **72**, `primary_only=1`, `legacy_only=0`, timers non résolus 0/0, safety-net private failures 0, PASS superset à horizon commun.
- Aucun achat, bid, checkout ou paiement automatique.
- V5 PR #8 reste **inchangée et non mergée**.

---

# PR #67 — alertes immédiates sur tout problème de certificat PSA/PCA/CCC

- Scope : **PSA / PCA / CCC** uniquement pour cette nouvelle notification immédiate.
- Les numéros de certificat présents dans l'API GCC fixed sont maintenant conservés directement dans `commercial_dimensions.cert_number` avant l'ouverture de la fiche ; le benchmark read-only préalable sur 100 cartes fixed actives avait trouvé **100/100 numéros présents directement dans l'API GCC**.
- **Numéro de certificat absent** après les données structurées + inspection de fiche → notification immédiate `CERT NUMBER MISSING — MANUAL REVIEW`, sans attendre qu'une opportunité économique V4 soit calculée.
- **Numéro présent mais lookup officiel réellement tenté et non résolu** → notification immédiate `CERT LOOKUP FAILED — MANUAL REVIEW` ; si le vérificateur répond mais que la note globale reste illisible → `CERT GRADE UNREADABLE — MANUAL REVIEW`.
- L'épuisement du budget `V4_MISLISTED_CERT_MAX_PER_RUN` n'est **pas** étiqueté comme problème de certificat : aucune fausse alerte n'est créée lorsque le lookup n'a simplement pas été tenté.
- Déduplication persistante par `listing URL + grader + cert + type/statut du problème` ; un même problème n'est pas renotifié à chaque run.
- La logique existante reste ensuite inchangée : certificat officiel d'abord, OCR ciblé PSA/PCA/CCC en fallback, mismatch officiel autoritaire, OCR seul manual-review, puis arbitrage V4 normal.
- Une panne de lookup peut être purement technique (anti-bot, timeout, parsing) : **l'alerte n'est jamais une preuve de mislisting** et ne modifie ni fair value, ni prix max, ni décision économique.
- Aucun achat, bid, checkout, paiement ou grading automatique.
- **V5 PR #8 reste inchangée et non mergée.**

---

# PR #71 — correction des faux `CERT NUMBER MISSING` + réactivation des alertes cert

- Cause racine confirmée : `watcher.inspect_item()` mute le `Lot` en place et remplaçait `commercial_dimensions` avec la fiche GCC repliée ; le `cert_number` structuré provenant de l'API était donc perdu avant le contrôle cert.
- Correctif : snapshot du cert **avant** inspection puis restauration si la fiche repliée l'efface. Si aucun cert structuré n'existe réellement, V4 ouvre explicitement **Description → Gradation** et relit le numéro avant d'autoriser `CERT NUMBER MISSING`.
- Retest live read-only sur **100 cartes PSA/PCA/CCC** : run **`31880785302`**, job **`95002943132`** :
  * API cert présent **100/100** ;
  * après inspection brute non protégée : **0/100** (reproduction exacte de l'ancien bug) ;
  * après preservation : **100/100 présents, 100/100 identiques à l'API** ;
  * Description → Gradation : **100/100 présents, 100/100 identiques à l'API** ;
  * conflits API/Gradation **0** ; absences malgré API **0**.
- Régressions ciblées : mutation in-place, preservation cert API, fallback Gradation, parser label/value séparés, vrai missing seulement après double échec, lookup failure, grade officiel illisible, budget non tenté et déduplication.
- Validation propre finale après retrait du script diagnostic temporaire : run **`31881107036`**, job **`95003680246`** → **520/520 tests PASS**, compile PASS, `git diff --check` PASS, discovery live PASS (`legacy_only=0`, safety-net private sans échec).
- Production demandée : `V4_CERT_PROBLEM_NOTIFICATIONS_ENABLED=true` pour **PSA/PCA/CCC**. Notifications immédiates sur vrai `CERT_NUMBER_MISSING`, `CERT_LOOKUP_FAILED` après tentative réelle, ou `CERT_GRADE_UNREADABLE`; déduplication persistante. L'épuisement du budget sans tentative n'est pas une alerte cert.
- Budget officiel reste borné à `V4_MISLISTED_CERT_MAX_PER_RUN=5` ; aucun contournement anti-bot/WAF.
- Aucun achat, bid, checkout, paiement ou grading automatique.
- **V5 PR #8 reste inchangée et non mergée.**
