# GCC Auction Watcher

> **Source de reprise canonique — à lire en premier dans toute nouvelle conversation.**
> Ce README doit rester la source de vérité pour reprendre le projet sans reconstruire l’historique complet.

## État canonique — 11 août 2026

### Principes non négociables

- **V4 sur `main` = production canonique.** V5 ne la remplace pas implicitement.
- Pokémon **cartes individuelles uniquement**. Produits scellés/non-cartes exclus : boosters, packs, displays, boxes, ETB, coffrets, blisters, bundles, decks, tins, cases, etc.
- Découverte économique : **0–100 €** afin de ne pas rater les anomalies très basses ; `MAX_PRICE=100`.
- Décote minimale : **30 %**, éventuellement relevée lorsque les comparables sont faibles.
- Enchères pertinentes uniquement si fin **≤60 min**.
- Aucun achat, bid, checkout ou grading payant automatique.
- Les données listing-level eBay/PokeTrace/JustTCG restent **mémoire-only** dans les diagnostics V5 : pas de persistance d’itemId, titre, URL, prix ou images.
- Une ambiguïté d’identité reste bloquante. La cible `15+/20` est un objectif de couverture uniquement si les preuves le permettent.

---

# V4 — production GCC

## Scheduler et persistance

- Production : **Cron-job.org → `workflow_dispatch` GitHub Actions environ toutes les 10 minutes**.
- Ne pas réintroduire de `schedule:` GitHub en parallèle : cela doublerait les scans.
- `state.json` est restauré/sauvegardé via cache GitHub Actions.
- Chaque run V4 est journalisé dans l’**issue #1** avec trigger, durée, opportunités, mode/scope auction, timers et fallback.

## Découverte fixed

- API publique GCC `/on-sale-items`.
- File de priorité : `NEW → CHANGED → NEVER_EVALUATED → STALE`.
- TTL de réévaluation : 24 h.
- Budget de traitement fixe : 120.
- Découverte 0–100 € ; un prix très bas ne crée jamais à lui seul une opportunité.

## Découverte auctions

Discovery primaire lot par lot :

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

## Valorisation V4

- même grader + même grade = comparables prioritaires ;
- médiane pondérée par récence ;
- filtrage robuste MAD/IQR ;
- fourchette prudente ;
- PSA Auction Prices Realized en premier pour PSA exact lorsque possible ;
- eBay public en fallback si APR insuffisant.

### Grade arbitrage

Une carte de grade supérieur peut être intéressante si son prix est autour du marché robuste d’un grade inférieur du **même grader**. Cette voie :

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

Les petits drifts dynamiques fixed pendant une pagination saine restent dans les logs mais ne notifient pas le téléphone. Sont toujours actionnables : page API échouée, pagination structurelle incohérente, écart matériel, couverture auction/économique incomplète, NEW/CHANGED urgent non traité, état/cache incohérent, invariant comptable cassé.

## Runtime Playwright

- PR #13 : cache pip + cache Playwright + probe Chromium.
- Run initial `31479526838` : cache miss attendu, téléchargement initial puis cache Playwright ~279 MB.
- Run `31480316615` : pip hit + Playwright hit, aucun gros téléchargement Chromium/FFmpeg/Headless Shell.
- Les runners GitHub-hosted restent jetables ; le cache évite les gros téléchargements.
- Runner self-hosted : **pas justifié actuellement**.

---

# Workflows GitHub Actions — inventaire utile après nettoyage

Le nettoyage PR #24 a supprimé du repo les workflows redondants :

- `V5 eBay Enrichment Diagnostic` ;
- `V5 GCC History Diagnostic` ;
- `V5 Market Valuation Diagnostic`.

Le cleanup a été mergé dans `main` (`a10740cb67aa80372bb0a2dc1add89f12541b660`) puis resynchronisé dans V5 via PR #25. La branche V5 est revenue à `behind main = 0`.

Workflows à conserver :

1. **GCC Auction Watcher** — production V4.
2. **V4 Auction Discovery Validation** — validation spécialisée auction.
3. **V4 GCC Coverage Audit** — audit de couverture V4.
4. **PSA Public API Diagnostic** — diagnostic APR/PSA.
5. **V5 Live Raw Pipeline Diagnostic** — diagnostic live eBay → identité → marché.
6. **V5 Catalog Identity Benchmark** — benchmark manuel TCGdex ↔ JustTCG sur la branche V5.
7. **V5 GCC Catalog Refresh** — fonction unique : entretenir le catalogue cumulatif GCC ; conserve son refresh quotidien.

Ne plus créer de workflows `Temp`, `one-shot`, `repair`, `handoff` ou reporter dédiés pour chaque micro-opération. Pour le développement : **Codex/tests locaux → une validation finale si nécessaire → workflow manuel existant pour le live**.

Les anciens noms peuvent rester visibles dans l’historique/sidebar GitHub Actions même après suppression du YAML ; ils ne correspondent plus à des workflows actifs du repo.

---

# V5 — expérimental, PR #8, NE PAS MERGER

- PR : **#8**.
- Branche exacte : `agent/v5-poketrace-cardmarket-market-data`.
- PR reste **draft, ouverte, non mergée**.
- HEAD fonctionnel V5 validé pour l'extension eBay EU :
  `f920e647171df758adb91ad3b1bc8aca46730ff2`.
- `main` réellement synchronisé dans V5 :
  `510a174ae4bd7edfaa8ea4b9cf01a34522e98d2d`.
- V5 = diagnostic **RAW eBay** séparé de la V4 graded GCC.
- Aucun achat/bid/checkout/CardGrader.
- Le plan PokeTrace Pro est désormais activé pour **un unique diagnostic manuel de 20 listings**, précédé d’un preflight `/auth/info` fail-closed. Aucun live n’est lancé depuis le développement local.

## Architecture resolver retenue

1. **TCGdex = resolver principal multilingue**.
2. **PokeTrace = fallback identité strict + marché US**, avec Free toujours disponible comme mode de repli.
3. Pokémon TCG API = fallback anglais/unknown.
4. Matching visuel local + OCR ciblé = arbitres conservateurs pour `AMBIGUOUS/INSUFFICIENT` seulement.
5. **JustTCG = seconde opinion / benchmark expérimental**, pas principal.
6. **Scrydex / Vision** = réservé aux ambiguïtés persistantes après la chaîne gratuite.

Les workflows V5 live et benchmark restent **`workflow_dispatch` uniquement**. Aucun déclenchement automatique PokeTrace/JustTCG.

## Transition PokeTrace Free → Pro

Le provider Free et ses tests restent disponibles avec `POKETRACE_PLAN=free` :
recherche explicite `market=US`, prix RAW US uniquement et cadence minimale de
2,25 s. Le workflow manuel principal utilise maintenant `POKETRACE_PLAN=pro`.
Un preflight lit uniquement le schéma officiel `/auth/info`, accepte Pro ou un
plan documenté supérieur, et arrête le job avant le pipeline si
l’authentification est invalide, la clé inactive ou le plan inférieur à Pro.
Les logs du preflight sont limités au statut HTTP, tier normalisé, quota
journalier/usage/remaining/reset disponibles et raison technique agrégée.
Lorsque le corps authentifié ne fournit pas les champs de quota, le preflight
peut lire les headers documentés `X-Plan`, `X-RateLimit-Limit`,
`X-RateLimit-Remaining` et `X-RateLimit-Reset`. Le corps reste prioritaire, les
headers complets ne sont jamais affichés et un Pro valide n'est pas refusé
uniquement parce que les chiffres d'usage sont indisponibles.

La cadence Pro est fixée à **≥0,40 s/requête**, marge conservatrice sous le burst
documenté de 30 requêtes/10 s. Le circuit-breaker 429 et son unique retry court
restent inchangés.

Les recherches d’identité sont toujours market-explicites : **US d’abord**, puis
**EU uniquement après un clean no-match US**. Un match, une ambiguïté, une
erreur, un conflit bloquant de variante ou un rate-limit US interdit le fallback
EU. Les IDs, résultats et caches sont qualifiés par marché et par identité
complète/variante/provenance ; aucun no-match ou échec US n’empoisonne EU.

Pour la valorisation, US/USD reste la seule entrée du moteur économique RAW et
fournit aussi PSA8/PSA9/PSA10 lorsqu’ils existent, uniquement comme comparaison
grading optionnelle. EU/EUR reste un diagnostic séparé :
`cardmarket.AGGREGATED` est une tendance/référence et `cardmarket_unsold` décrit
des demandes actives, jamais des ventes réalisées. Aucun mélange USD/EUR.

## Alias fournisseur multilingues déterministes

Les noms localisés ne sont jamais traduits par fuzzy matching ni par table
manuelle. Après une résolution TCGdex exacte dans une langue non anglaise, V5
demande au catalogue TCGdex le même ID dans l’endpoint anglais. Un alias
PokeTrace n’existe que si les deux réponses ont exactement le même `id`, le
même `set.id` et le même `localId`, avec un nom et un set anglais présents.

L’alias et sa provenance `TCGDEX_EXACT_ENGLISH_TWIN` restent séparés du
`CardIdentity` réel. Le nom/set anglais servent uniquement à la requête et à la
comparaison locale PokeTrace ; le nom, le set, la langue, le numéro et la
variante affichés/économiques restent ceux de l’identité localisée. Le set et
le numéro PokeTrace doivent correspondre strictement au jumeau exact, et les
contraintes de variante restent inchangées. Sans jumeau anglais exact, aucun
alias n’est inventé et aucune nouvelle langue n’est rendue fuzzy-éligible.

Ce pont peut donc bénéficier, carte par carte, aux langues TCGdex documentées
et déjà routées par V5 (`fr`, `de`, `es`, `it`, `ja`, `pt`, `pt-br`, `pt-pt`,
`zh-tw`, `zh-cn`, `ko`, `nl`, `pl`, `ru`, `id`, `th`) uniquement lorsque cette
preuve de coordonnées identiques existe. Cela ne garantit ni qu’un record
PokeTrace US existe, ni qu’il contienne une valeur RAW.

## Discovery eBay Europe

La whitelist V5 couvre désormais `EBAY_US`, `EBAY_CH`, `EBAY_DE`, `EBAY_FR`,
`EBAY_IT`, `EBAY_ES`, `EBAY_AT`, `EBAY_BE`, `EBAY_NL`, `EBAY_PL`, `EBAY_IE` et
`EBAY_GB`. Le prochain live active seulement `EBAY_US,EBAY_DE,EBAY_FR,EBAY_IT,EBAY_ES`
via l'unique variable `V5_LIVE_EBAY_MARKETPLACES`.

`V5_LIVE_RAW_RESULT_LIMIT=20` est une limite globale. Chaque marketplace peut
fournir des summaries, puis un round-robin déterministe choisit au plus vingt
`itemId` uniques, backfill les marchés vides et déduplique les doublons
cross-market avant `getItem`. Il n'existe plus de quota de vingt `getItem` par
marketplace.

Chaque marché résout son propre default category tree et ses propres category
suggestions. Seule une catégorie explicitement reconnue comme cartes
individuelles est acceptée. Une taxonomie absente ou non sûre produit
`marketplace unavailable/incomplete` et interdit toute recherche Pokémon large
ou tout enrichissement sur ce marché. Un filtre local conservateur exclut aussi
boosters, displays, ETB, coffrets, boxes, blisters, decks, lots, bulk et sealed.

Pour tout marché non-CH, Browse reçoit `deliveryCountry:CH`. Le header
`contextualLocation` n'est envoyé que si un NPA suisse de quatre chiffres est
explicitement fourni par `V5_EBAY_DELIVERY_POSTAL_CODE`; aucun postcode ni coût
de livraison n'est inventé. Sans coût fourni par Browse, le diagnostic indique
`shipping estimate limited` et une annonce sans preuve d'éligibilité Suisse ne
peut pas entrer dans l'économie.

## Constat du premier live Pro et correctifs offline suivants

Le run manuel Pro `31525792380` / job `93893666902` a produit le baseline
agrégé suivant :

- preflight HTTP 200, plan `PRO`, accepté ; quota/usage/remaining/reset
  `UNAVAILABLE` ;
- échantillon global de 20 annonces uniques sur US/DE/FR/IT/ES, 20 appels
  `getItem` réussis et 19 RAW acceptées ;
- US : taxonomie/recherche OK, 5 sélectionnées, `USD=5` ; DE : OK, 5,
  `EUR=5` ; IT : OK, 5, `EUR=5` ; ES : OK, 5, `EUR=5` et 3 doublons
  cross-market ;
- FR : taxonomie HTTP 200/200, mais `SAFE_INDIVIDUAL_CATEGORY_MISSING` et
  Browse correctement `NOT_CALLED` ;
- éligibilité livraison Suisse et estimation de livraison disponibles pour
  les 20 annonces sélectionnées ;
- identité : 9 utilisables, 2 ambiguës, 9 insuffisantes ; TCGdex 0 hit ;
  matching visuel 14 tentatives/5 sauvetages et OCR 3 tentatives/0 sauvetage ;
- PokeTrace : 0 identité exacte, 0×429, 0 panne de requête ; 5 snapshots
  US avec RAW/PSA8/PSA9/PSA10 et 0 snapshot EU/CardMarket ;
- valeurs marché trouvées pour 5 des 9 identités utilisables, mais chemin
  économique RAW évalué 0 fois et `ECONOMICS_DEFERRED_CURRENCY_POLICY=6`.

FR a été arrêté avant Browse parce que la suggestion réaliste
`JCC : cartes à l’unité` n'était pas reconnue par la whitelist, alors que la
taxonomie répondait 200.
Le marqueur de taxonomie normalise maintenant de façon déterministe les
apostrophes ASCII/Unicode et accepte cette formulation, tout en rejetant
toujours les lots, boîtes et produits scellés. Il n'existe toujours aucun ID de
catégorie codé en dur ni fallback vers une recherche large.

Les cinq sauvetages visuels ont tous concerné des marketplaces non-US. Ils ont
amorcé cinq snapshots US/USD, mais aucun snapshot EU/EUR ; trois
identités US utilisables sont en outre restées sans valeur USD. Le diagnostic
rapporte donc désormais, par marketplace eBay, les valeurs trouvées, les sources
PokeTrace US/USD et EU/EUR acceptées, les annonces non-US avec snapshot US seul,
les annonces US avec/sans valeur USD et les annonces EUR avec/sans valeur
EU/CardMarket. Ces sorties restent uniquement agrégées.

Le chemin économique à zéro n'était donc pas un bug de calcul : aucune
annonce ne réunissait simultanément `EBAY_US`, un prix listing USD et une valeur
marché USD. Les snapshots US issus des sauvetages appartenaient aux annonces
EUR IT/ES, tandis que les trois annonces US utilisables n'avaient aucune
valeur PokeTrace.

Après un sauvetage visuel/OCR réussi sur une annonce non-US, un unique lookup
EU optionnel peut maintenant enrichir le cache CardMarket. Le cœur nom + set +
numéro doit rester exact. Une variante/finition explicitement compatible suffit ;
une métadonnée de microvariante absente ne peut plus être remplacée par une
simple ressemblance du scan complet. Un conflit explicite ou plusieurs
candidats plausibles interdisent le match. L'identité eBay/TCGdex n'est jamais
remplacée par l'enrichissement EU, les IDs/caches restent séparés par marché et
aucune valeur EUR n'entre dans l'économie RAW.

## File forensique et sécurité des microvariantes

Les annonces initialement insuffisantes ne sont plus traitées comme du bruit :
elles forment une file forensique bornée et déterministe, priorisée avant les
identités déjà propres. Le plafond
`V5_VISUAL_IDENTITY_MAX_LISTINGS_PER_RUN` borne les annonces soumises au
sauvetage local ; les seuils de preuve visuelle/OCR restent strictement
inchangés. Le diagnostic compare désormais cinq cohortes agrégées :
`STRUCTURED_USABLE`, `RESCUED_FROM_INSUFFICIENT`,
`RESCUED_FROM_AMBIGUOUS`, `STILL_INSUFFICIENT` et `STILL_AMBIGUOUS`, avec pour
chacune valeurs marché trouvées/manquantes, provenance US/EU et économie
évaluée/différée. Aucune donnée listing-level n'est rendue ou persistée.

La preuve d'identité est séparée en deux niveaux :

- identité macro : jeu, nom exact, set exact, numéro de collection exact et
  langue ;
- microvariante commerciale : édition, finition, promo, stamp ou impression
  spéciale susceptible de changer matériellement la valeur.

Le scan perceptuel complet peut sauver uniquement l'identité macro. Il ne peut
pas fabriquer une 1st Edition, une finition ou une promo depuis le candidat
fournisseur : les champs vendeur restent inchangés et le candidat premium reste
une provenance non héritée. La validation microvariante vient seulement après
la macro, via une interface locale à région/layout ou référence canonique
exacte. L'édition 1st/Unlimited n'est activée que lorsqu'un catalogue exact — en
priorité `TCGdex variants.firstEdition` — prouve que la famille possède cette
distinction. Une famille explicitement non concernée n'est pas bloquée.

`EDITION_UNKNOWN` n'est jamais assimilé à Unlimited. L'absence visuelle d'un
stamp, à elle seule, ne prouve pas Unlimited ; il faut une couverture suffisante
de la région attendue et une référence Unlimited déterministe. Si l'édition est
applicable et reste inconnue, ou si les preuves se contredisent, les prix de la
microvariante premium ne sont pas amorcés et l'économie est différée.

La prochaine étape reste une revue de ce batch offline. Seulement en l'absence
de blocker, elle pourra être suivie d'au plus un live contrôlé de 20 annonces ;
ce batch Codex ne lance aucun workflow.

Le prochain live doit rester le workflow manuel existant et ne sera justifié
qu'après revue de ces changements offline. Il devra vérifier : Browse FR via la
catégorie sûre résolue, la provenance par marketplace, les compteurs
d'enrichissement EU (tentatives/candidats/matches/ambiguïtés/rejets) et les
snapshots CardMarket récupérés, sans recommandation d'achat ni économie EUR.

La devise du listing reste inchangée. Le chemin économique existant continue
uniquement pour un listing `EBAY_US` en USD avec des valeurs marché USD. EUR,
CHF, GBP ou toute autre devise traversent discovery, identité et diagnostics
marché, puis retournent `ECONOMICS_DEFERRED_CURRENCY_POLICY`; aucun prix d'achat
non-USD n'est injecté dans le modèle de coûts USD. Les aliases eBay espagnols
ajoutés (`Juego`, `Idioma`, `Edición`, etc.) sont explicites et déterministes ;
l'identité utilisateur/localisée et le contrat du jumeau TCGdex exact restent
inchangés.

Le résumé live expose seulement, par marketplace, taxonomie/statut technique,
total et summaries, sélection globale, doublons, rejets sealed/multi-produit,
appels `getItem`, RAW, shipping CH, disponibilité de l'estimation shipping,
distribution des devises et economics différées. Aucune valeur listing-level
n'est loggée ou persistée.

---

# V5 — validation offline la plus récente

Baseline antérieure du circuit-breaker PokeTrace :

```text
bdd1abc7b479ed980f4f4896b17e3b184b701ed5
```

Validation offline après synchronisation de `main`, transition Free → Pro,
extension eBay EU, séparation macro/microvariante et détecteur local par paire
de références :

- V5 : **429/429** ;
- V4 : **169/169** ;
- V4 identique à `origin/main` ;
- `compileall v5` : OK ;
- YAML : **7/7** ;
- `git diff --check` : OK ;
- aucun appel PokeTrace/TCGdex/JustTCG/eBay/GCC live pendant le batch Codex ;
- aucun secret consulté ;
- aucun CardGrader, achat, bid ou checkout.

SHA final : commit final de la branche de la PR #8, communiqué dans le rapport
de validation (un commit ne peut pas contenir son propre hash).

Le merge post-Codex `0e3660ed330d0fc5220dfa239911d934d700398c` resynchronise `main` `510a174ae4bd7edfaa8ea4b9cf01a34522e98d2d` dans V5. Il ne modifie aucun fichier `v5/`; les deux fichiers V4 repris de `main` ont été validés à **169/169** par le workflow V4 de la PR #27.

## Durcissements déjà intégrés

- isolation des caches par variante/finition/édition/rareté ;
- suppression des alias fuzzy dangereux (`Team Rocket` ≠ `Team Rocket Returns`) ;
- finish/promo/premium missing restent bloquants ;
- requêtes PokeTrace canonisées sans `set=` non vérifié ;
- faux conflit eBay `Standard` + `Holo` corrigé ;
- reconstruction prudente du numéro complet via `cardCount.official` TCGdex ;
- langues TCGdex alignées sur les codes documentés ;
- JustTCG exige langue + printing et un set ID fiable ;
- diagnostics near-match SET/NUMBER/NAME détaillés ;
- équivalences acceptées uniquement lorsqu’elles sont déterministes : wrapper Pokémon TCG, ponctuation/espacement, zéros initiaux, casse alphanumérique, préfixes explicites de numéro ;
- parent/subset, containment, traduction, préfixes significatifs, genre, mécaniques EX/GX/V/VMAX/VSTAR et numéros contradictoires restent bloqués ;
- rendement PokeTrace mesuré par stratégie ;
- parser eBay enrichi uniquement avec aliases structurés déterministes ;
- failures TCGdex et Pokémon TCG API séparées dans les diagnostics.
- détecteur microvariante concret câblé par défaut après preuve macro :
  localisation de la carte, orientation/normalisation, alignement de deux scans
  canoniques exacts, construction locale des seules régions où ces scans
  diffèrent, puis comparaison du vendeur avec seuil absolu, marge et qualité ;
- références concurrentes limitées au même nom, set, numéro et langue
  déterministes, même produit `single`, avec cache mémoire et borne stricte ;
  aucune image, réponse fournisseur ou donnée listing-level n'est persistée ;
- une identité sauvée visuellement reçoit une seconde chance TCGdex exacte et
  cachée pour l'applicabilité microvariante, sans PokeTrace/Pokémon TCG fallback
  et sans remplacement des champs commerciaux du listing ;
- First Edition exige un aspect vendeur explicite ou une région positive sur
  une paire exacte ; Unlimited exige une vraie référence Unlimited du même
  layout et un meilleur match significatif — l'absence de stamp ne suffit
  jamais ;
- holo/reverse reste `UNKNOWN` sous éclairage vendeur arbitraire ; promo et
  special/stamped ne peuvent être confirmés que par une différence statique
  utilisable entre références exactes. Crop, glare, basse résolution,
  alignement faible, références trop proches/absentes ou dimensions multiples
  restent fail-closed ;
- le snapshot US et l'unique enrichissement EU éventuel sont amorcés seulement
  après `CONFIRMED` / `NOT_APPLICABLE` / absence de blocker. Les devises et IDs
  fournisseur restent inchangés ;
- diagnostics pré-marché dédiés : gate bloquée, snapshot non amorcé,
  enrichissement EU non tenté, dimension du blocker, applicabilité avant/après
  macro, paires présentes/absentes, normalisation, alignement, région
  discriminante et issues First/Unlimited/autre/UNKNOWN/CONFLICT ;
- l'ancien `economics_blocked_microvariant_unknown` reste présent mais signifie
  uniquement « valeurs marché trouvées, puis économie bloquée » ; il ne mesure
  pas les snapshots empêchés avant le marché ;
- diagnostics set PokeTrace enrichis sans assouplissement : nom listing/jumeau
  TCGdex vs nom PokeTrace après normalisation sûre, slug présent/absent, pont
  alias/jumeau exact présent/absent, name+number exact mais set irrésolu,
  collisions ID/slug entre sets distincts et disponibilité d'un pont TCGdex.
- alias anglais PokeTrace autorisé uniquement par un jumeau TCGdex exact
  `id + set.id + localId`, conservé en mémoire et isolé des caches par identité
  complète/variante/provenance ;
- diagnostics agrégés des identités localisées, alias trouvés/indisponibles,
  alias utilisés en recherche identité/marché, matches attribuables et appels
  identité évités grâce au hit TCGdex exact ;
- les 429 sont classés uniquement via `Retry-After` : délai ≤30 s = un
  unique retry, délai long/absent/invalide = terminal ; un second 429 ouvre
  également le circuit ;
- le circuit-breaker partagé arrête les recherches PokeTrace suivantes du run,
  évite aussi l'appel marché après identité, et compte les appels évités sans
  transformer le rate-limit en `NO_MATCH`.

## RAW→RAW MVP économique

La revente RAW est maintenant une voie économique autonome et prioritaire.
Elle exige une identité exacte/non ambiguë, une valeur RAW fiable et non
conflictuelle, une devise cohérente et tous les coûts RAW matériels connus.
L'absence de valeurs PSA ou de budget de grading ne rejette plus une
opportunité RAW rentable.

Formule conservatrice :

```text
valeur RAW prudente = borne basse des valeurs RAW agrégées fiables
coûts RAW fixes = achat + frais acheteur + transports d'acquisition + autres coûts non-grading
frais de vente = valeur prudente × (selling fee % + buffer FX %) + frais fixes de vente
base totale RAW = coûts RAW fixes + frais de vente
profit net RAW = valeur RAW prudente - base totale RAW
ROI RAW = profit net RAW / base totale RAW × 100
```

`grading_fee`, `grading_shipping` et `vault_fee` sont explicitement exclus de
la base RAW. Le grading n'est qu'une comparaison optionnelle : il faut les
valeurs par grade suffisantes, des photos compatibles, une analyse visuelle
autorisée dans le quota et une EV nette supportée. Le chemin recommandé est
alors celui dont le profit net supporté est le plus élevé ; sans cette preuve,
aucun avantage grading n'est inventé.

Le prochain diagnostic live exposera seulement des compteurs agrégés : marché
RAW suffisant, voie RAW évaluée, RAW rentable/rejetée, comparaison graded
disponible, RAW bat grading, grading bat RAW, et graded absent mais RAW
évaluable. Aucun contenu listing-level n'est ajouté aux logs.

---

# Références live PokeTrace

## Baseline propre avant diagnostics near-match — run `31498195243`

Commit : `9ec5ebf66792802ef7f4a4f20aad56ea11034bc3`.

- eBay search/getItem : **20/20** ; RAW : **20/20** ;
- identity usable : **9** ; ambiguous 4 ; insufficient 7 ;
- TCGdex : 5 requêtes, **0 hit** ;
- PokeTrace : 12 identities / **66 HTTP** / **401 candidats uniques** ;
- name matched 27 ; set 34 ; number 19 ;
- name+set 1 ; set+number 5 ;
- **all-three 0 ; exact 0** ;
- 51 near-matches à un seul champ près : 5 name-only, 25 set-only, 21 number-only ;
- PokeTrace request failures 0 ; 429 = 0 ;
- visual/OCR rescues = 0 ;
- market values found = **0**.

Ce run a motivé les nouveaux diagnostics détaillés et le rendement par stratégie.

## Dernier live complet avant le détecteur — run `31533156545`

La taxonomie **EBAY_FR a été prouvée live correcte** avec la catégorie sûre
existante. Elle n'est ni modifiée ni relâchée par ce batch offline.

- identité exploitable : **9** ; ambiguë : 1 ; insuffisante : 10 ;
- cohortes forensiques : structured usable 6, rescued from insufficient 2,
  still insufficient 10, still ambiguous 1 ;
- visual attempted : **13** ; rescued : **2** ;
- OCR attempted : 4 ; OCR rescued : 0 ;
- les **2/2** sauvetages visuels ont atteint le gate microvariante : premium
  candidate not inherited 2, visual attempts 2, confirmed 0, inconclusive 2 ;
- snapshots marché amorcés : 0 ; enrichissements EU : 0 ;
- TCGdex : 14 requêtes, 0 hit ;
- PokeTrace : 13 identités, 129 recherches, 776 candidats, 0 exact ;
- candidats name/number/set matched : 206/40/**1** ;
- 24 candidats échouaient uniquement sur le set, dont 23 sans relation
  déterministe.

Ce baseline démontre deux blocages séparés : l'ancien provider d'évidence
microvariante était absent (`None`) et les sets PokeTrace ne disposent presque
jamais d'un pont sûr. Le premier est maintenant remplacé par le détecteur local
générique décrit ci-dessus. Le second reçoit uniquement des diagnostics : le
matcher set, ses seuils et ses rejets restent strictement identiques.

Le détecteur suit deux phases explicites : listing → preuve macro → nouvelle
applicabilité exacte si nécessaire → sélection de références concurrentes
exactes → preuve locale de région → `CONFIRMED`, `NOT_APPLICABLE`, `UNKNOWN` ou
`CONFLICT` → amorçage marché seulement si le gate est ouvert. Les métadonnées
fournisseur ne servent qu'à sélectionner les références et ne constituent
jamais la preuve visuelle du listing.

Il n'y a **pas de prochain live autorisé par ce changement lui-même**. La revue
offline doit d'abord confirmer l'architecture, les fixtures synthétiques et
les diagnostics. Ensuite seulement, le propriétaire pourra déclencher
manuellement le workflow existant ; Codex ne le déclenche pas.

## Dernier live — run `31504468613`, job `93822427440`

Commit testé : `d4e445b3e450339a8ff576c36b66abd9f6da2f9d`.
Fingerprint : `031a3770c6e599d8`.

### eBay / identité

- OAuth : 200 ;
- search/getItem : **20/20** ; RAW : **20/20** ;
- identity usable : **11** ; ambiguous 3 ; insufficient 6 ;
- card_name coverage : **12/20** ;
- set coverage : **18/20** ;
- card_number coverage : **14/20** ;
- unmapped card-name-like / card-number-like aspect labels : **0/0**.

### TCGdex / Pokémon TCG API

- TCGdex requests : 7 ; hits : **0** ;
- TCGdex failures transport/HTTP/JSON/set/card : **0/0/0/0/0** ;
- no-match set/card : 10/2 ; skipped missing set/number : 6 ;
- Pokémon TCG API requests : 6 ; hits : 0 ; HTTP failures : **4** ;
- l’ancien compteur ambigu `catalog request failures` est maintenant correctement attribué : les 4 failures venaient du fallback Pokémon TCG API, pas de TCGdex.

### PokeTrace — run PARTIELLEMENT CENSURÉ PAR 429

- identities queried : **13** ;
- HTTP search attempts : **38** ; fallback searches : 18 ;
- unique candidates received : **121** ;
- exact matches : **0** ;
- **429 responses : 15** ; retries : 0 ; request failures : 0 ;
- le 429 commence pendant l’identité 5 puis affecte la majorité des identités suivantes ;
- ce run ne doit donc **pas** être utilisé comme comparaison complète de qualité contre le run `31498195243`.

Rendement observé avant/pendant le rate-limit :

| stratégie | requêtes | uniques | near-match | all-three | exact | redondants |
|---|---:|---:|---:|---:|---:|---:|
| contextual-canonical | 12 | 2 | 0 | 0 | 0 | 0 |
| contextual | 5 | 1 | 1 | 0 | 0 | 2 |
| structured | 5 | 0 | 0 | 0 | 0 | 3 |
| broad-name | 4 | 58 | 0 | 0 | 0 | 2 |
| broad-number | 4 | 40 | 1 | 0 | 0 | 2 |
| broad-set | 1 | 20 | 0 | 0 | 0 | 0 |

Signal provisoire seulement : `broad-name`/`broad-set` ramènent beaucoup de candidats mais aucun near-match/exact sur la portion observée ; `structured` a été entièrement redondant sur cette portion. **Ne pas supprimer une stratégie uniquement sur ce run censuré.**

Near-matches effectivement observés avant rate-limit : 2, tous deux échouant uniquement sur le nom :

- translation/localization : 1 ;
- différence significative : 1.

### Visual/OCR / marché

- visual attempted : 7 ; candidate searches unavailable : **6** à cause de l’indisponibilité PokeTrace ; rescues : 0 ;
- OCR attempted/calls : 0/0 sur ce run ;
- market values found : **0/11** ;
- RAW direct / PSA9 / PSA10 : 0/0/0 ;
- achats/bids/checkout/CardGrader : **0/0/0/0**.

### Interprétation du 429

Ce run historique Free imposait ≥2,25 s entre appels mais a reçu 15×429 persistants. Plusieurs runs Free avaient déjà consommé du quota le même jour ; le type exact n’était pas prouvé par les anciens logs. Cette consigne d’attente Free est désormais remplacée par le preflight Pro fail-closed et le circuit-breaker partagé.

---

# Benchmark TCGdex ↔ JustTCG — source de vérité

Run `31489148268`, job `93771289624`, fingerprint `7ef358f50c335f7d`.
PokeTrace non injecté : 0 appel.

### TCGdex

- exact : **5/20** ;
- ambiguous : 3 ; unresolved 12 ;
- requests : 28 ; failures : 0 ;
- canonical changes name/set/number : 3/4/1 ;
- denominator conflicts : 2 ;
- set aliases unique/ambiguous : 8/1 ;
- no-match set/card : 2/3 ;
- localId alternate attempts/hits : 4/2 ;
- direct-card fallbacks/hits : 9/0.

### JustTCG

- exact : **0/20** ;
- ambiguous : 3 ; unresolved 17 ;
- request failures/429 : 0/0 ;
- candidates received : 6 ;
- all-core candidate : 1, rejeté sur variante.

Conclusion : **TCGdex reste clairement principal.** JustTCG reste second avis expérimental.

---

# Prochaines actions V5

**Ne pas merger PR #8.**

Ordre recommandé :

1. après revue et seulement sans blocker, lancer manuellement **un seul** `V5 Live Raw Pipeline Diagnostic` sur au plus vingt listings uniques globaux, avec `EBAY_US,EBAY_DE,EBAY_FR,EBAY_IT,EBAY_ES` ;
2. vérifier d’abord le résumé du preflight Pro, puis les diagnostics agrégés eBay par marketplace, US→EU PokeTrace, circuit-breaker, near-match, rendement par stratégie et compteurs RAW ;
3. seulement après ce run propre, décider si `structured`, `broad-name`, `broad-set` ou d’autres fallbacks peuvent être réduits/supprimés ;
4. continuer à chercher des équivalences uniquement déterministes ; ne jamais assouplir le matching pour atteindre `15+/20` ;
5. si PokeTrace reste à 0 exact/0 market value après ce run Pro propre, réévaluer les stratégies sans relâcher le matcher ;
6. Scrydex/Vision reste différé tant que l’identité structurée et les sources marché ne sont pas mieux comprises.

---

# Gouvernance et sécurité

- **Ne jamais merger silencieusement PR #8.**
- `AMBIGUOUS` reste bloquant.
- Ne jamais assouplir le matching uniquement pour atteindre `15+/20`.
- Une source externe ne peut pas inventer une valeur achetable.
- Même grader/même grade reste la preuve principale pour le graded.
- Aucune identité higher-grade ne doit être inventée à partir d’un lower-grade.
- Données listing-level eBay/PokeTrace/JustTCG restent memory-only.
- Aucun achat, bid ou checkout automatique.
- Aucun CardGrader payant dans les diagnostics actuels.

---

# Référence cloud

La production recommandée reste la **V4 cloud GitHub Actions** : aucun Mac ne doit rester allumé. Voir [`README_CLOUD.md`](README_CLOUD.md) pour l’installation et le fonctionnement détaillé.
