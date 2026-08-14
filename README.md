# GCC Auction Watcher

> **Source de reprise canonique — à lire en premier dans toute nouvelle conversation.**
> Après tout changement important de production, d’architecture V5, de provider, de benchmark ou de workflow, mettre ce README à jour avant de considérer la phase terminée.

## État canonique — 13 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

### Principes non négociables

- **V4 sur `main` = production canonique.**
- **V5 = expérimental, PR #8. Ne jamais merger PR #8 sans autorisation explicite.**
- Pokémon **cartes individuelles uniquement** ; sealed/lots restent hors scope actuel.
- Discovery V4 : **0–100 €** pour capter les anomalies extrêmes ; `MAX_PRICE=100`.
- Décote minimale utilisateur : **30 %**, avec seuil adaptatif plus exigeant lorsque les preuves sont faibles.
- Fixed + auctions ; une auction n’est économiquement pertinente que si elle finit dans **≤60 min**.
- Aucun achat, bid, checkout ou grading payant automatique.
- `AMBIGUOUS` / conflit matériel = fail-closed. Ne jamais relâcher le matching pour améliorer artificiellement la couverture.
- Une absence de valorisation n’est **pas** un signal négatif : distinguer `pas de marché confirmé` de `mauvaise offre`.

---

# P0 — Card Knowledge Base Foundation (expérimental, hors production)

La branche `agent/p0-card-knowledge-base-foundation` contient le socle isolé `robot_kb/`, désormais gelé GREEN au SHA `946f4b7511f966c00b215a34178b183d01712c3e`. Il n’est importé ni par le watcher V4 ni par ses entrypoints : **aucune décision, valorisation, notification, Fast Lane ou feature flag V4 ne change**. Ce P0 reste expérimental ; SQLite est utilisé uniquement en local, en test ou pour un futur mode shadow, sans service de base de données déployé.

Principes du socle :

- identité canonique interne (`canonical_set` → `card_family` → `localized_card` → `canonical_card`) ; les IDs TCGdex/GCC/eBay/Cardmarket/TCGplayer/PokeTrace/PSA restent des alias externes ;
- identité inconnue laissée nullable, avec candidats finis, dimensions non résolues, preuves et conflits conservés ;
- provenance par claim et par champ, séparant source, méthode de preuve, directness et état de résolution ; une cible de requête n’est pas une preuve et le silence provider ne crée aucun défaut (`Unlimited`, non-promo, finish standard, etc.) ;
- microvariantes génériques par dimensions/valeurs/profils/assignments et combinaisons autorisées ; Base Set sépare notamment `edition_stamp` de `shadow_treatment` ;
- grader, grade, qualifier, subgrades et certification portés par l’instance/segment gradé, jamais par l’identité du print commercial ;
- ledger marché append-only : ventes, snapshots de listings, agrégats providers, populations et taux FX restent des faits distincts ; une correction insère une nouvelle observation reliée par `REVISION_OF`, sans écraser l’historique ;
- lineage séparant le système source du marché upstream afin de pouvoir relier plusieurs observations provider au même événement sans les compter comme ventes indépendantes ;
- montants originaux conservés par composant (item/hammer/accepted offer/premium/shipping/tax/total), avec état connu/inclus/inconnu et normalisation FX traçable.

Le hardening Red Team est appliqué par la migration forward `0002_integrity_hardening.sql` (sans réécrire `0001`) : une observation passe explicitement de `DRAFT` à `SEALED` seulement lorsque son fait typé est complet, puis son enveloppe, ses prix et ses normalisations FX deviennent immuables. La migration rend aussi le ledger de migrations tamper-evident, impose les foreign keys sur chaque chemin de connexion, lie les normalisations FX à leur composant exact, conserve chaque occurrence de retrieval d’un même payload, verrouille les profils par clé sémantique dérivée et interdit les résolutions positives sans claim `EVIDENCE` positif, non nul et exactement concordant.

La migration forward `0003_final_integrity_closure.sql` ferme les derniers écarts P0 sans modifier `0001`/`0002` : `CANCELS` et `VOIDS` exigent un fait de statut cohérent, les systèmes upstream et leurs IDs restent marketplace-scoped, un lien observation/résolution doit retracer le même sujet source, l’applicabilité des dimensions enregistrées doit être fermée avant toute identité canonique exacte, et les taux/normalisations FX utilisent une représentation rationnelle entière avec calcul exact et arrondi `ROUND_HALF_UP`. Une base 0002 incompatible échoue atomiquement au lieu de réinterpréter silencieusement ses faits historiques.

Compatibilité sidecar future : les agrégats Cardmarket et TCGplayer embarqués dans une réponse carte TCGdex sont représentables comme `PROVIDER_METRIC_OBSERVATION` distinctes, avec TCGdex comme source, le marché concerné comme upstream, l’identité exacte du segment commercial, les timestamps provider/observation/ingestion séparés et les fenêtres 1/7/30 jours conservées. Ce socle n’ingère encore aucune réponse TCGdex et ne dépend pas de `variants_detailed`, toujours considéré comme non stable.

Le contrat de scénarios valorise chaque variante plausible indépendamment, sans mélanger les comparables incompatibles, puis expose : `EXACT_VARIANT_OPPORTUNITY`, `ROBUST_VARIANT_OPPORTUNITY`, `MICROVARIANT_DEPENDENT_OPPORTUNITY`, `SCENARIO_DATA_INCOMPLETE_REVIEW`, `NO_OPPORTUNITY`, `IDENTITY_CONFLICT`, `IDENTITY_UNBOUNDED` et `MARKET_UNCONFIRMED`.

Le socle P0 ne migre pas `state.json`, ne s’intègre pas au watcher et ne produit ni prévision ni notification. **PR #8 reste V5 expérimentale et non mergée.**

---

# P1 — Shadow Observation Sidecar (remédiation ciblée, live non activé)

Branche : `agent/p1-shadow-observation-sidecar`, créée exactement depuis le P0 GREEN `946f4b7511f966c00b215a34178b183d01712c3e`.

Le package isolé `robot_kb.sidecar` suit la chaîne suivante :

```text
collector read-only
  → payload source brut immuable
  → normalizer typé et conservateur
  → repository P0 append-only
  → diagnostics shadow uniquement
```

Couverture implémentée :

- GCC Marketplace : inventaire public fixed-price et auction, avec listing ID/URL, timestamps d’observation et de mise à jour réellement exposés, statut et mode, prix courant/final explicite, devise, shipping explicite, seller ID, texte/titre source, grader/grade, langue, set, numéro, édition/finish/variant/stamp/shadow uniquement lorsqu’ils sont présents, certification, fin d’auction et bid count ;
- TCGdex : métriques Cardmarket `avg`, `low`, `trend`, `avg1`, `avg7`, `avg30` et buckets réellement retournés, plus métriques TCGplayer `low`, `mid`, `high`, `market`, `direct low` par segment retourné ; chaque mesure est une `PROVIDER_METRIC_OBSERVATION`, avec TCGdex comme source et Cardmarket/TCGplayer comme upstream ;
- historique : chaque snapshot/fait est scellé et immuable ; un changement 30 € → 25 € crée deux observations. Une vente économique utilise une identité stable fondée sur la source, le listing, le timestamp de finalisation et le prix/devise final : plusieurs retrievals gardent leur lineage mais ne créent qu’un `SALE_TRANSACTION`. Une finalisation contradictoire du même listing échoue explicitement au lieu de créer une seconde vente silencieuse ;
- preuve brute : la migration forward `0004_sidecar_raw_payload.sql`, sans réécrire `0001`/`0002`/`0003`, conserve les octets canoniques reconstructibles dans `source_payload`, adressés par SHA-256 et dédupliqués, puis relie immuablement chaque nouveau `source_record` via `source_record_payload`. Les occurrences de retrieval restent séparées. Les records historiques antérieurs à 0004 ne peuvent être rétro-remplis sans les octets source d’origine ; un nouveau retrieval du même payload peut créer leur référence ;
- atomicité : chaque source record et tous ses faits dérivés sont écrits sous un unique transaction/savepoint couvrant source, objet externe, payload, retrieval, observation typée, prix, sujet, claims, résolution et lien d’identité. Toute erreur annule cette unité sans annuler les unités déjà commitées d’autres jobs ;
- identité : une absence provider ne crée jamais `Unlimited`, non-promo, finish normal, sans stamp, édition, shadow ou langue. Un bucket marché TCGdex est conservé comme preuve `market_segment`, pas comme finish exact. Sans lien d’identifiant externe déjà `PROVEN` dans le P0, le record, les claims et la résolution `UNKNOWN` sont conservés sans forcer de `canonical_card`. `SINGLE_CARD` exige positivement soit une cardinalité générique structurée égale à 1, soit le contrat GCC `GCC_SINGLE_COLLECTIBLE_OBJECT` observé dans les payloads réels : objets singuliers `item` et `item.collectible` de type carte/catégorie Pokémon, listing ID égal à l'ID natif, item ID distinct, serial numérique de 8–9 chiffres, grader, grade et images recto/verso distinctes, sans champ concurrent `items`/`collectibles`/`components`. Le titre doit être présent et toute preuve structurée ou textuelle bundle/menu/sealed/multi-item conserve un scope non exact. Aucune quantité 1 n'est inventée lorsque le champ est absent, et une annonce ambiguë n'hérite jamais d'un mapping exact préexistant ;
- ventes : un `SALE_TRANSACTION` GCC exige le statut univoque `SOLD`, un champ `soldPrice`/`acceptedOfferPrice`, un champ `soldAt`/`saleOccurredAt` et une chronologie `sale <= source_updated <= observed` lorsque la mise à jour source existe. `COMPLETED`, `SUCCESSFUL`, une fin d’enchère, `finalPrice`, `completedAt`, une disparition ou un ask restent des snapshots non vendus ;
- métriques et devises : les alias TCGdex d’une même métrique/segment sont dédupliqués s’ils concordent et la seule métrique conflictuelle est rejetée sinon, sans perdre les métriques indépendantes. Les devises explicites sont limitées à `EUR`, `USD` et `CHF` après normalisation casse/espaces ; une devise explicite invalide rejette le fait monétaire, et l’inférence par absence est limitée aux contrats GCC/TCGdex documentés ;
- diagnostics : les compteurs reflètent les rejets et comportements réels (`sale_candidates_rejected`, `ambiguous_sale_records`, `duplicate_sale_replays`, `metric_alias_conflicts`, `monetary_facts_rejected`, `crawl_batches_truncated`) ; l’ancien pseudo-compteur constant `fabricated_sales` a été supprimé ;
- isolation : aucun fichier/entrypoint V4 n’importe le sidecar. Une panne collector/normalizer est arrêtée à la frontière de sa source et n’a aucun chemin synchrone vers scoring, alertes, Fast Lane, achat, bid, checkout, grading ou état V4.

Entrée manuelle :

```text
python -m robot_kb.sidecar --database /chemin/local.sqlite --gcc-fixture replay.json
python -m robot_kb.sidecar --database /chemin/local.sqlite --tcgdex-fixture replay.json
```

Les GET live existent uniquement derrière une intention explicite `--allow-live-read-only` combinée à `--live-gcc ...` ou `--live-tcgdex-card ...`. Le crawl GCC utilise des défauts conservateurs de 50 rows/page, 10 pages et 500 records, avec plafonds stricts de 100/20/2 000, timeout maximal 30 s, intervalle minimal 0,25 s et au plus deux retries sur erreurs transitoires sûres ; un `429 Retry-After` est respecté dans une attente bornée à 30 s. Les valeurs CLI nulles, négatives ou démesurées sont rejetées avant tout réseau. Aucun workflow, cron, scheduler ou dispatch live n’est ajouté. La base pilote réelle `~/robot-pokemon-data/shadow-pilot-2026-08-14.sqlite` reste hors du repository et n'est utilisée qu'en lecture seule pour le replay hors ligne. Les fichiers SQLite runtime (`.db`, `.sqlite`, `.sqlite3` et journaux associés) sont ignorés par Git. SQLite reste local/test/replay ; le chemin de base est configurable via `--database`/`ROBOT_KB_DATABASE`, et un backend durable PostgreSQL devra être autorisé et ajouté à la frontière repository avant déploiement durable.

**Statut remédiation : NOT GREEN — en attente d’une nouvelle décision Red Team. Statut live : NOT ENABLED.** Aucun appel provider live ni collecte automatique n’a été lancé pendant P1. Prochaine étape obligatoire : nouvelle revue Red Team, corrections supplémentaires si demandées, déclaration GREEN externe, puis autorisation utilisateur explicite avant tout déploiement shadow durable ou activation read-only.

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
3. `ILLIQUID_PRICE_DISCOVERY` : Liquidité exacte faible sur le slab considéré, mais multiples ancres adjacentes solides (PSA 10 vendu récent, consensus RAW, ventes historiques GCC) prouvant une décote asymétrique majeure.

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
6. `V5 Live Raw Pipeline Diagnostic` — live V5 manuel.
7. `V5 Catalog Identity Benchmark` — benchmark identité.
8. `V5 GCC Catalog Refresh` — catalogue cumulatif GCC.

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
