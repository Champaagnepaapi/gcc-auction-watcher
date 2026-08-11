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

---

# V5 — validation offline la plus récente

Baseline antérieure du circuit-breaker PokeTrace :

```text
bdd1abc7b479ed980f4f4896b17e3b184b701ed5
```

Validation offline de la transition Free → Pro, incluant les régressions
RAW→RAW et alias multilingues :

- V5 : **345/345** ;
- V4 : **167/167** ;
- V4 identique à `origin/main` ;
- `compileall v5` : OK ;
- YAML : **7/7** ;
- `git diff --check` : OK ;
- aucun appel PokeTrace/JustTCG/eBay live pendant cette phase ;
- aucun secret consulté ;
- aucun CardGrader, achat, bid ou checkout.

Le merge de synchronisation workflow-only `231b067517fc14126215532019d7f46f68d7b5d0` ne modifie pas la logique V5.

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

1. lancer manuellement **une seule validation Pro de 20 listings** via `V5 Live Raw Pipeline Diagnostic`, après revue de cette PR ;
2. vérifier d’abord le résumé du preflight Pro, puis mesurer US→EU, circuit-breaker, diagnostics near-match, rendement par stratégie et compteurs RAW ;
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
