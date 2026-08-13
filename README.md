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

### Réduction du bottleneck BLOCKED_VARIANT

Résolution déterministe de l'édition et des variantes structurées/titre :

- parser `extract_title_edition` par span-masking multilingue strict (English, French, German, Italian, Spanish) ;
- extraction sécurisée de `1st Edition` / `Shadowless` / `Unlimited` depuis les titres eBay explicites ;
- réconciliation déterministe avec les aspects structurés (priorité structurée, fail-closed en cas de contradiction) ;
- extension des alias d'aspects structurés eBay (`Auflage`, `Druck`, `Edition / Print`, `Card Finish`, `Caratteristiche`) ;
- unblocking automatique et fail-closed préservé dans `LocalMicrovariantValidator` pour les cartes vintage/modernes disposant d'une preuve d'édition ou de finish unique ;
- **P0/P1 Red Team Hardening** :
  - rejet strict des hallucinations visuelles 1ère édition sur les cartes avec catalogue `MICROVARIANT_NOT_APPLICABLE` (fail-closed `EDITION_CONFLICT`) ;
  - isolation stricte de l'observabilité : interdiction absolue d'inférer `SINGLE_COMPATIBLE` ou `unnecessary=true` depuis les métadonnées provider seules sans preuve catalogue exacte ;
  - échec immédiat (`EDITION_CONFLICT`) en cas de finish provider incompatible avec un finish unique prouvé au catalogue ;
  - validation déterministe des promos et finitions spéciales exclusives au catalogue pour éviter les faux blocages tout en maintenant le fail-closed.

PR #8 reste draft et non mergée.

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