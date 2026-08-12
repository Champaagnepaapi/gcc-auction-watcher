# GCC Auction Watcher

> **Source de reprise canonique — à lire en premier dans toute nouvelle conversation.**
> Après tout changement important de production, d’architecture V5, de provider, de benchmark ou de workflow, mettre ce README à jour avant de considérer la phase terminée.

## État canonique — 12 août 2026

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

# V4 — production canonique

## Scheduler / état

```text
Cron-job.org
    ↓ workflow_dispatch ~toutes les 10 min
GitHub Actions
    ↓
GCC Auction Watcher V4
```

- Ne pas ajouter un `schedule:` GitHub parallèle : cela doublerait les scans.
- `state.json` est restauré/sauvegardé via cache GitHub Actions.
- Concurrency V4 sérialisée, `cancel-in-progress: false`.
- Les runs V4 sont journalisés dans l’issue #1.

## Discovery fixed

- Source : API publique GCC `/on-sale-items`.
- File économique : `NEW → CHANGED → NEVER_EVALUATED → STALE`.
- Budget : 120 évaluations/run.
- TTL fixed : 24 h.
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
- Une PR séparée #30 (`agent/v4-targeted-final-auction-check`) contient un recheck ciblé T−4 pour fiabiliser l’alerte finale ; elle n’est pas incluse implicitement dans la prod tant qu’elle n’est pas mergée.

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

### PSA APR web hydration

PR #32 a corrigé le race condition de la page publique APR :

- attente bornée du champ de recherche client-rendered ;
- attente bornée du bouton Search ;
- puis délégation au scraper strict existant ;
- timeout/anti-bot/erreur restent fail-closed.

Cette voie utilise la **page web publique APR**, pas l’ancienne API Collectors publique.

## RAW TCGdex : signal secondaire uniquement

TCGdex peut fournir des prix Cardmarket / TCGplayer RAW.

Règle absolue :

```text
RAW market ≠ valeur du slab gradé
```

Le RAW :

- ne crée jamais une estimation PSA/BGS/CGC ;
- ne crée jamais `max_recommended` ;
- ne crée jamais une opportunity automatique ;
- peut servir de **signal de revue manuelle**.

Si le marché gradé exact reste indisponible mais qu’un slab est au moins ~30 % sous une enveloppe RAW externe prudente, V4 peut envoyer :

```text
GCC MANUAL REVIEW — GRADED MARKET PENDING
```

La notification :

- montre identité TCGdex, grade, prix GCC, plage RAW et sources ;
- explique explicitement que RAW ≠ valeur du slab ;
- n’affiche aucun prix max d’achat dérivé du RAW ;
- est dédupliquée 24 h ;
- peut renotifier après baisse de prix significative ou amélioration matérielle du gap.

Ainsi une carte potentiellement anormalement bon marché ne disparaît plus silencieusement uniquement parce que PSA APR/eBay n’ont pas fourni de prix gradé.

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

## Cache externe

- clé hashée d’identité commerciale stricte ;
- TTL 24 h ;
- schéma versionné ;
- `MATCHED`, `CLEAN_NO_MATCH`, `CLEAN_INSUFFICIENT` cachables ;
- `PROVIDER_ERROR`, `TRANSIENT_UNAVAILABLE`, `RATE_LIMIT` jamais cachés comme résultat propre ;
- budget pending reste requeue.

Le schéma est bumpé lors de l’activation PokeTrace afin d’éviter de réutiliser comme vérité des entrées antérieures à la couche multi-marché.

---

# V4 — enchères / notifications

`max_recommended` reste le plafond prudent de référence.

Pour une opportunity auction :

- prix courant > `max_recommended` → pas de notification ;
- la notification affiche `Prix max conseillé` ;
- `EXTERNAL_RESCUE` calcule le plafond depuis l’estimation externe retenue ;
- `GCC_EXTERNAL_CONFIRMED` le calcule depuis l’estimation prudente combinée ;
- rappels temporels réutilisent le même plafond.

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

---

# V5 — expérimental, PR #8, NE PAS MERGER

PR : **#8**  
Branche : `agent/v5-poketrace-cardmarket-market-data`

Dernier head canonique V5 vérifié avant resync :

```text
abc5fa8e45ff2832d36c6e78c4ecb3e287973ba4
```

État :

- open ;
- draft ;
- non mergée ;
- base `main` a avancé depuis sa dernière synchronisation V5 ;
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

---

# Workflows GitHub Actions à conserver

1. `GCC Auction Watcher` — V4 production.
2. `V4 Auction Discovery Validation` — CI + comparaison discovery read-only.
3. `V4 GCC Coverage Audit` — audit couverture V4.
4. `PSA Public API Diagnostic` — diagnostic PSA/APR historique.
5. `V5 Live Raw Pipeline Diagnostic` — live V5 manuel.
6. `V5 Catalog Identity Benchmark` — benchmark identité.
7. `V5 GCC Catalog Refresh` — catalogue cumulatif GCC.

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
- auditer les providers/caches et les effets prod.

## V5

Avant toute intégration de PR #8 :

- autorisation explicite utilisateur obligatoire ;
- auditer base/head/ancestry ;
- V4 production ne doit pas régresser ;
- vérifier gates microvariantes et provenance langue/set ;
- live contrôlé manuel avant toute décision de merge.

**PR #8 reste expérimentale et non mergée par défaut.**
