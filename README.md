# GCC Auction Watcher

> **Source de reprise canonique — à lire en premier dans toute nouvelle conversation.**
> Ce README doit rester la source de vérité du projet. Après tout changement important de production, d’architecture V5, de provider, de benchmark ou de workflow, le mettre à jour avant de considérer la phase terminée.

## État canonique — 11 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

### Principes non négociables

- **V4 sur `main` = production canonique.** V5 ne la remplace jamais implicitement.
- Pokémon **cartes individuelles uniquement**. Exclure boosters, packs, displays, boxes, ETB, coffrets, blisters, bundles, decks, tins, cases et autres produits scellés/non-cartes.
- Découverte économique historique cible ~10–100 €, mais discovery volontairement élargie à **0–100 €** pour capter les anomalies extrêmes ; `MAX_PRICE=100`.
- Décote minimale utilisateur : **30 %**, avec seuil adaptatif plus exigeant si les comparables sont faibles.
- Fixed + auctions ; une auction n’est pertinente que si elle finit dans **≤60 min**.
- Aucun achat, bid, checkout ou grading payant automatique.
- Les données listing-level eBay/PokeTrace/JustTCG restent **memory-only** dans les diagnostics V5 : pas de persistance d’itemId, titre, URL, prix ou image.
- `AMBIGUOUS` reste bloquant. La cible `15+/20` n’est qu’un objectif de couverture si les preuves permettent de l’atteindre ; ne jamais relâcher le matching pour atteindre un chiffre.
- Le README est le **handoff canonique** entre conversations ChatGPT/Codex.

---

# V4 — production GCC

## Scheduler et persistance

Production :

```text
Cron-job.org
    ↓ workflow_dispatch ~toutes les 10 min
GitHub Actions
    ↓
V4 GCC watcher
```

- Ne pas réintroduire de `schedule:` GitHub en parallèle : cela doublerait les scans.
- `state.json` est restauré/sauvegardé via cache GitHub Actions.
- Chaque run V4 est journalisé dans l’**issue #1** avec trigger, durée, opportunités, mode/scope auction, timers et fallback.

## Découverte fixed

- API publique GCC `/on-sale-items`.
- File de priorité : `NEW → CHANGED → NEVER_EVALUATED → STALE`.
- TTL : 24 h.
- Budget de traitement fixe : 120.
- Couverture économique comptabilisée séparément de la simple discovery.
- Un prix très bas ne crée jamais à lui seul une opportunité.

## Découverte auctions

Discovery primaire item-level :

```text
/on-sale-items
sellingTypeGroup=AUCTION
sortType=ENDING_SOON
status=ON_SALE
        ↓
lots individuels
        ↓
endTime individuel
        ↓
Pokémon + carte + 0–100 € + ≤60 min
        ↓
analyse économique V4
```

Le watcher s’arrête lorsque l’ordre `ENDING_SOON` prouve que l’horizon de 60 min est franchi ou lorsque l’inventaire est épuisé. Statut attendu :

```text
COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
```

L’ancien collector auction reste fallback uniquement si l’API/pagination/ordre/endTime ne permet plus de prouver la couverture.

Validation historique item-level : API primaire au moins égale au collector legacy sur horizon commun, sans action économique pendant le test.

## Valorisation V4

- même grader + même grade = comparables prioritaires ;
- médiane pondérée par récence ;
- filtrage robuste MAD/IQR ;
- fourchette prudente ;
- PSA Auction Prices Realized en premier pour PSA exact lorsque possible ;
- eBay public en fallback si APR insuffisant.

### Arbitrage indépendant avant rejet terminal

Implémentation isolée de l’issue #28 :

```text
branche: agent/v4-independent-external-market-valuation
base origin/main: 510a174ae4bd7edfaa8ea4b9cf01a34522e98d2d
PR V4: séparée, draft, vers main
PR #8 / branche V5: séparées et inchangées
validation offline V4: 221/221 tests
```

Le résultat GCC est désormais une preuve structurée (`STRONG`, `WEAK` ou
`UNAVAILABLE`), pas nécessairement une décision terminale. Les cas suivants
restent terminaux avant toute recherche externe : grader/grade illisible,
qualifier spécial, identité commerciale exacte insuffisante, produit non-carte
ou non supporté, et prix hors périmètre de discovery. En revanche, historique
vide, comparables insuffisants, décote GCC insuffisante et borne prudente GCC
non achetable peuvent entrer dans la file de preuve externe.

Arbitrage déterministe :

- GCC fort positif + marché externe fort concordant :
  `GCC_EXTERNAL_CONFIRMED`, avec les bornes source par source les plus prudentes ;
- GCC faible/indisponible + marché externe fort positif : `EXTERNAL_RESCUE` ;
  la faiblesse GCC n’est pas utilisée comme plafond dur ;
- deux marchés forts matériellement contradictoires, ou un marché fort positif
  contre l’autre fort négatif : `MARKET_CONFLICT_BLOCKED` ;
- source externe indisponible : une opportunité GCC déjà valide est conservée
  sous `GCC_ONLY` ;
- budget externe épuisé : `EXTERNAL_PENDING`, jamais converti en faux
  « aucun comparable ».

La preuve externe est strictement limitée à la même identité commerciale, au
même grader et au même grade. Les conflits de référence, langue, édition ou
finish/variant sont bloquants. PSA utilise APR au grade exact en premier puis
eBay en fallback ; les autres graders utilisent eBay au même grader/grade.
PokeTrace et les proxys inter-graders ne participent pas à cette V4.

Le cache `state.json` utilise une clé hashée de l’identité commerciale stricte,
un schéma versionné et une TTL de 24 h. Une preuve fraîche ne consomme aucun
budget. Les misses/stales sont dédupliqués puis priorisés : enchères finissant
le plus tôt, fixed `NEW/CHANGED`, rejets GCC récupérables, puis refresh stale.
Les budgets restent bornés séparément par provider.

Les diagnostics de run exposent les forces et décisions GCC/externe, hits/miss/
stale du cache, profondeur et déduplication de file, tentatives APR/eBay,
rescues, conflits, différés et chemins finaux. Les notifications et l’état
anti-spam conservent également le chemin de valorisation et la provenance.

### Grade arbitrage

Une carte de grade supérieur peut être intéressante si son prix est autour du marché robuste d’un grade inférieur du **même grader**.

Cette voie :

- ne doit jamais inventer la valeur du grade supérieur ;
- exige une preuve externe exacte suffisante avant notification ;
- garde les autres graders comme comparables secondaires ;
- interdit qu’un proxy cross-grader crée seul une valeur achetable sans ratio empirique documenté.

## ntfy / anti-spam

Renotifier une opportunité déjà signalée uniquement si :

- prix baisse ≥10 % ;
- décote s’améliore ≥5 points ;
- franchissement d’un seuil temporel ;
- une alerte haute priorité unique peut partir à ≤5 min si le prix reste sous le max prudent.

### Alertes techniques

Les petits drifts fixed issus d’un inventaire qui bouge pendant une pagination saine restent dans les logs mais ne notifient pas le téléphone.

Tolérance actuellement déployée :

```text
max(3 lignes, ceil(expected_total × 0.2 %))
```

Toujours actionnable par ntfy :

- page API échouée ;
- pagination structurelle incohérente ;
- écart matériel au-delà de la tolérance ;
- couverture auction ou économique incomplète ;
- NEW/CHANGED urgent non traité ;
- état/cache incohérent ;
- invariant comptable cassé.

## Runtime Playwright / P3

Production V4 utilise :

- cache pip ;
- cache `~/.cache/ms-playwright` ;
- installation Chromium seulement sur cache miss ;
- launch probe ;
- fallback `playwright install --with-deps chromium` seulement si le probe échoue.

Validation réelle :

- premier run P3 : cache miss attendu, cache Playwright créé ~279 MB ;
- run `31480316615` : pip hit + Playwright hit, aucun gros téléchargement Chromium/FFmpeg/Headless Shell ;
- runner self-hosted : pas justifié actuellement.

---

# Workflows GitHub Actions à conserver

Après le cleanup des workflows redondants :

1. **GCC Auction Watcher** — production V4.
2. **V4 Auction Discovery Validation** — validation spécialisée auction.
3. **V4 GCC Coverage Audit** — audit de couverture V4.
4. **PSA Public API Diagnostic** — diagnostic APR/PSA.
5. **V5 Live Raw Pipeline Diagnostic** — diagnostic live eBay → identité → marché.
6. **V5 Catalog Identity Benchmark** — benchmark manuel TCGdex ↔ JustTCG.
7. **V5 GCC Catalog Refresh** — entretien du catalogue cumulatif GCC.

Ne plus créer de workflows `Temp`, `one-shot`, `repair`, `handoff` ou reporters dédiés pour chaque micro-opération. Préférer :

```text
Codex/tests locaux
    ↓
validation offline complète
    ↓
un seul workflow manuel existant si un live est réellement nécessaire
```

---

# V5 — expérimental, PR #8, NE PAS MERGER

PR : `#8`

Branche exacte :

```text
agent/v5-poketrace-cardmarket-market-data
```

État vérifié avant cette mise à jour documentaire :

- PR **draft** ;
- ouverte ;
- non mergée ;
- mergeable ;
- head : `34b28b95eaec6553ec8248db87e97efbd9f66a3e` ;
- avant le présent commit README sur `main`, branche V5 : `behind main = 0` ;
- le présent commit documentaire sur `main` devra être resynchronisé dans V5 avant la prochaine validation complète.

V5 est un diagnostic RAW eBay séparé de la V4 graded GCC. Aucun achat/bid/checkout/CardGrader automatique.

---

# V5 — architecture d’identité retenue

Ordre canonique :

```text
eBay structured metadata
        ↓
TCGdex exact multilingual
        ↓ si unresolved
PokeTrace identity fallback
        ↓ si unresolved et autorisé
Pokémon TCG API
        ↓ si toujours AMBIGUOUS/INSUFFICIENT
visual matcher local + OCR ciblé
        ↓ si ambiguïté persistante et économiquement pertinente
Scrydex Vision (futur fallback payant ciblé)
```

Rôles :

1. **TCGdex = resolver principal multilingue**.
2. **PokeTrace = fallback identité + provider marché**.
3. Pokémon TCG API = fallback anglais/unknown.
4. Visual local + OCR = arbitres conservateurs seulement pour `AMBIGUOUS/INSUFFICIENT`.
5. **JustTCG = second avis / benchmark expérimental**, pas principal.
6. **Scrydex Vision** = fallback photo ciblé pour les ambiguïtés persistantes ; ne pas analyser toutes les annonces systématiquement.

## TCGdex : contrat principal

- catalogues de sets chargés/cachés par langue ;
- résolution déterministe par set/localId et ID canonique ;
- `cardCount.official` peut compléter prudemment un numéro numerator-only ;
- un conflit de dénominateur complet reste bloquant ;
- aucun fuzzy dangereux pour fabriquer une identité ;
- langue conservée comme discriminant de premier ordre.

### Alias fournisseur multilingues déterministes

Pour une identité TCGdex exacte localisée, V5 peut récupérer le même ID sur l’endpoint TCGdex anglais.

Un alias PokeTrace n’est permis que si le jumeau anglais possède exactement :

```text
same card id
+ same set.id
+ same localId
```

Exemple :

```text
Léviator FR
TCGdex exact base1-6
        ↓ même ID en anglais
Gyarados EN
        ↓
alias de recherche PokeTrace uniquement
```

Le `CardIdentity` réel reste français ; l’alias anglais ne sert qu’à la recherche provider. Aucun nom/set/numéro/variant utilisateur n’est silencieusement remplacé.

Langues déjà routées par TCGdex V5 : `fr`, `de`, `es`, `it`, `ja`, familles `pt`, familles `zh`, `ko`, `nl`, `pl`, `ru`, `id`, `th`, lorsqu’un jumeau exact existe.

---

# V5 — état eBay actuel et extension EU

## Ce qui est implémenté aujourd’hui

Le composant `EbayLiveDiagnostic` ne supporte actuellement que :

```text
EBAY_US
EBAY_CH
```

et `LiveRawPipelineConfig` utilise par défaut :

```text
V5_LIVE_INCLUDE_EBAY_CH=false
```

Donc le **V5 Live Raw Pipeline Diagnostic contrôlé tourne actuellement sur eBay US uniquement**, sauf activation explicite de CH.

## eBay EU : à ajouter

Le passage PokeTrace Pro **n’active pas automatiquement eBay Europe**. Ce sont deux sujets différents :

- PokeTrace Pro apporte US + EU/Cardmarket côté identité/market data ;
- eBay EU demande d’étendre la discovery Browse API à plusieurs `X-EBAY-C-MARKETPLACE-ID`.

Objectif prochain : généraliser proprement la liste de marketplaces eBay sans dupliquer le pipeline. Priorité pratique initiale :

```text
EBAY_DE
EBAY_FR
EBAY_IT
EBAY_ES
```

puis évaluer `EBAY_AT`, `EBAY_BE`, `EBAY_NL`, `EBAY_PL`, `EBAY_IE`, `EBAY_GB` selon inventaire, devise, expédition et qualité des aspects.

Contraintes de l’extension :

- taxonomy/category résolue par marketplace ;
- langue locale conservée ;
- devise jamais mélangée silencieusement ;
- déduplication cross-marketplace ;
- shipping vers Suisse pris en compte avant décision économique ;
- mêmes règles Pokémon-only / single-card / RAW / identité exacte ;
- diagnostics agrégés uniquement ;
- aucun achat/bid/checkout.

---

# PokeTrace — historique Free et transition Pro en cours

## Free historique

Contrat utilisé pendant les benchmarks :

- `X-API-Key` ;
- Free : US + RAW ;
- pacing local ≥2.25 s ;
- `market=US` volontaire ;
- aucun `set=` envoyé tant qu’un slug PokeTrace vérifié n’est pas disponible ;
- circuit-breaker partagé après 429 terminal ;
- caches isolés par identité complète/variante/provenance.

Dernier live Free significatif : run `31504468613`, job `93822427440`.

- eBay search/getItem/RAW : 20/20/20 ;
- usable 11 ; ambiguous 3 ; insufficient 6 ;
- TCGdex requests 7 ; hits 0 ;
- PokeTrace identities 13 ; HTTP attempts 38 ;
- exact PokeTrace 0 ;
- 429 : 15 ;
- market values 0/11 ;
- visual rescues 0 ;
- achats/bids/checkout/CardGrader : 0/0/0/0.

Ce run est censuré par le rate-limit et ne doit pas être interprété comme un benchmark complet de qualité.

## Transition Free → Pro demandée

Le passage Free→Pro a été demandé et un lot Codex unique a été déposé dans la conversation de la PR #8 : commentaire GitHub `5256474902`.

**À cet instant, la transition Pro n’est pas encore implémentée dans le workflow live.** Le YAML de V5 contient encore :

```text
POKETRACE_PLAN=free
POKETRACE_MIN_REQUEST_INTERVAL_SECONDS=2.25
```

Donc : **ne pas lancer V5 Live Raw Pipeline Diagnostic avant que le lot Free→Pro soit implémenté, resynchronisé et validé offline.**

## Contrat attendu après migration Pro

Préflight :

```text
/auth/info
    ↓
plan Pro ou supérieur confirmé
quota/rate-limit observables sans afficher secret/email/token
```

Identité :

```text
TCGdex
  ↓ unresolved
PokeTrace US
  ├─ EXACT → stop
  ├─ AMBIGUOUS → stop
  ├─ ERROR/429 → stop / circuit-breaker
  └─ clean NO_MATCH
          ↓
      PokeTrace EU
```

Ne jamais utiliser EU pour écraser une ambiguïté US.

Marché :

```text
US
├─ RAW eBay/TCGPlayer
├─ PSA8
├─ PSA9
└─ PSA10

EU
├─ Cardmarket aggregate/trend
└─ active asking inventory
```

Règles :

- IDs/caches US et EU qualifiés par marché ;
- USD et EUR séparés ;
- conversion FX seulement dans la couche économique explicite ;
- Cardmarket aggregate/unsold n’est pas une listing-level seller URL et ne doit jamais être présenté comme une annonce directement achetable ;
- RAW→RAW reste la voie économique prioritaire ; le grading est une comparaison optionnelle.

---

# V5 — RAW→RAW MVP économique

La revente RAW est une voie autonome et prioritaire.

Elle exige :

- identité exacte/non ambiguë ;
- valeur RAW fiable et non conflictuelle ;
- devise cohérente ;
- tous les coûts RAW matériels connus.

Formule conservatrice :

```text
valeur RAW prudente = borne basse des valeurs RAW agrégées fiables
coûts RAW fixes = achat + frais acheteur + transports d’acquisition + autres coûts non-grading
frais de vente = valeur prudente × (selling fee % + buffer FX %) + frais fixes de vente
base totale RAW = coûts RAW fixes + frais de vente
profit net RAW = valeur RAW prudente - base totale RAW
ROI RAW = profit net RAW / base totale RAW × 100
```

`grading_fee`, `grading_shipping` et `vault_fee` ne doivent pas contaminer la base RAW.

Le grading n’est évalué que si les valeurs par grade et l’état visuel supportent réellement le scénario. Sans preuve, aucun avantage grading n’est inventé.

---

# V5 — dernière validation offline connue

HEAD V5 vérifié avant mise à jour documentaire de `main` :

```text
34b28b95eaec6553ec8248db87e97efbd9f66a3e
```

Validation rapportée pour ce HEAD :

- V5 : **333/333** ;
- V4 : **167/167** ;
- V4 identique à `origin/main` au moment du test ;
- compilation V5 : OK ;
- YAML : **7/7** ;
- `git diff --check` : OK ;
- aucun appel PokeTrace/JustTCG/eBay live pendant cette phase ;
- aucun secret consulté ;
- aucun CardGrader/achat/bid/checkout.

Cette phase ajoute notamment :

- TCGdex exact localisé ;
- récupération du même ID en anglais ;
- alias provider autorisé seulement si `id + set.id + localId` sont identiques ;
- alias conservé séparément du `CardIdentity` ;
- nom/set anglais utilisés seulement pour PokeTrace ;
- numéro et variante stricts ;
- caches séparés par identité, variante et provenance ;
- compteurs d’identités localisées, alias trouvés/absents, alias utilisés et appels évités via TCGdex exact.

---

# Benchmark TCGdex ↔ JustTCG

Run de référence : `31489148268`, job `93771289624`.

TCGdex :

- exact 5/20 ;
- ambiguous 3 ;
- unresolved 12 ;
- requests 28 ; failures 0 ;
- canonical changes name/set/number 3/4/1 ;
- denominator conflicts 2 ;
- set aliases unique/ambiguous 8/1 ;
- localId alternate attempts/hits 4/2.

JustTCG :

- exact 0/20 ;
- ambiguous 3 ;
- unresolved 17 ;
- request failures/429 0/0.

Conclusion : **TCGdex reste le resolver principal.** JustTCG reste un second avis expérimental uniquement.

---

# Visual / OCR / Scrydex

V5 possède déjà un fallback visuel local/OCR ciblé :

- uniquement `AMBIGUOUS/INSUFFICIENT` ;
- images eBay gardées en mémoire ;
- matching contre candidats canoniques ;
- OCR ciblé de la zone numéro ;
- seuils de confiance + marge ;
- un conflit ne doit jamais être écrasé silencieusement.

Résultat live historique : 0 rescue pour le moment, notamment parce que PokeTrace Free a été censuré par 429 pendant le dernier diagnostic.

**Scrydex Vision** reste une option payante ciblée pour les ambiguïtés persistantes après la chaîne structurée/gratuite. Ne pas l’appeler sur toutes les annonces.

---

# Prochaines actions V5 — ordre canonique

**Ne pas merger PR #8.**

1. Resynchroniser ce nouveau `main` documentaire dans la branche V5 avant toute validation finale.
2. Faire exécuter par Codex le dernier lot **Free→Pro** de la PR #8, **offline uniquement**, sans live et sans merge.
3. Exiger ensuite : V4 ≥167/167, V5 ≥333/333, compileall V5, YAML, `git diff --check`, et `behind main = 0`.
4. Vérifier que le workflow n’est plus en mode Free et qu’un preflight `/auth/info` safe existe.
5. Ajouter ensuite l’extension **eBay EU** proprement ; ne pas confondre marketplace eBay et market PokeTrace.
6. Après tout cela seulement : un unique `V5 Live Raw Pipeline Diagnostic` contrôlé sur 20 listings.
7. Mesurer : eBay par marketplace, identité TCGdex/PokeTrace, aliases, US/EU, RAW/graded, Cardmarket, 429, visual/OCR, economics ; toujours 0 achat/bid/checkout/CardGrader payant.
8. Mettre ce README à jour avec le nouveau HEAD, résultats et prochaine étape.
9. Ne merger V5 qu’après décision explicite utilisateur.

---

# Gouvernance et sécurité

- **Ne jamais merger silencieusement PR #8.**
- V4 `main` reste production jusqu’à décision explicite.
- `AMBIGUOUS` reste bloquant.
- Ne jamais assouplir le matching pour atteindre `15+/20`.
- Une source externe ne peut pas inventer une valeur achetable.
- Même grader/même grade reste la preuve principale pour le graded.
- Aucune valeur higher-grade ne doit être inventée à partir d’un lower-grade.
- Données eBay/PokeTrace/JustTCG listing-level : memory-only.
- Aucun secret dans logs/README/PR comments.
- Aucun achat, bid ou checkout automatique.
- Aucun CardGrader payant dans les diagnostics sans autorisation explicite.
- Après chaque changement important : **mettre ce README à jour**.

---

# Référence cloud

La production recommandée reste la **V4 cloud GitHub Actions** : aucun Mac ne doit rester allumé. Voir [`README_CLOUD.md`](README_CLOUD.md) pour l’installation et le fonctionnement détaillé.
