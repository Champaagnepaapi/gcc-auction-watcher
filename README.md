# GCC Auction Watcher

> **Source de reprise canonique — à lire en premier dans toute nouvelle conversation.**
> Ce README doit être mis à jour après chaque changement important afin qu'un nouveau ChatGPT/Codex puisse reprendre le projet sans reconstruire l'historique complet.

## Reprise du projet — état canonique au 11 août 2026

### Principes non négociables

- **V4 sur `main` = production canonique.** V5 ne la remplace pas implicitement.
- Pokémon **cartes individuelles uniquement**. Produits scellés/non-cartes exclus : boosters, packs, displays, boxes, ETB, coffrets, blisters, bundles, decks, tins, cases, etc.
- Découverte économique : **0–100 €** afin de ne pas rater une anomalie très basse ; `MAX_PRICE=100`.
- Décote minimale : **30 %**, éventuellement relevée si les comparables sont faibles.
- Enchères pertinentes uniquement si fin **≤60 min**.
- Aucun achat, bid, checkout ou grading payant automatique.
- Les données listing-level eBay/PokeTrace/JustTCG (itemId, titre, URL, prix, images) restent **mémoire-only** dans les diagnostics V5.
- Une ambiguïté d'identité reste bloquante. La cible `15+/20` est un objectif de couverture **seulement si les preuves le permettent**.

---

# V4 — production GCC

## Scheduler et persistance

- Production cloud : **Cron-job.org → `workflow_dispatch` GitHub Actions environ toutes les 10 minutes**.
- L'ancien `schedule:` GitHub `3,13,23,33,43,53` a été supprimé pour éviter irrégularité et double scan.
- `state.json` est restauré/sauvegardé via cache GitHub Actions.
- Chaque run V4 est aussi journalisé dans l'**issue #1** avec trigger, exit code, durée, opportunités, mode/scope auction, timers et fallback.

## Découverte GCC

### Fixed price

- API publique GCC `/on-sale-items`.
- File de priorité : `NEW → CHANGED → NEVER_EVALUATED → STALE`.
- TTL de réévaluation : 24 h par défaut.
- Découverte volontairement 0–100 € ; un prix très bas **ne crée jamais à lui seul** une opportunité.

### Auctions

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

Le watcher s'arrête lorsque l'ordre `ENDING_SOON` prouve que l'horizon de 60 min a été franchi ou lorsque l'inventaire est épuisé. Statut attendu lorsque prouvé :

```text
COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
```

Si API/pagination/ordre/endTime deviennent incohérents, l'ancien collector auction reste fallback de sécurité.

## Valorisation V4

- même grader + même grade = comparables prioritaires ;
- médiane pondérée par récence ;
- filtrage robuste MAD/IQR ;
- fourchette prudente ;
- PSA Auction Prices Realized en premier pour PSA exact lorsque possible ;
- eBay public en fallback si APR insuffisant.

### Grade arbitrage

Une carte de grade supérieur peut être intéressante si son prix est autour du marché robuste d'un grade inférieur du **même grader**. Cette voie :

- ne doit jamais inventer la valeur du grade supérieur ;
- exige une preuve externe exacte suffisante avant notification ;
- garde les autres graders comme comparables secondaires seulement ;
- interdit qu'un proxy cross-grader crée seul une valeur achetable sans ratio empirique documenté.

## Anti-spam et ntfy

Renotifier une opportunité déjà signalée uniquement si :

- prix baisse ≥10 % ;
- décote s'améliore ≥5 points ;
- franchissement d'un seuil temporel ;
- une alerte haute priorité unique peut partir à ≤5 min si le prix reste sous le max prudent.

### Alertes techniques

Un petit drift dynamique fixed pendant une pagination saine, par exemple `2953/2954` avec pages réussies, aucun backlog, aucune erreur et comptabilité saine, reste **dans les logs mais ne doit pas notifier le téléphone**.

Les cas techniques réellement actionnables restent notifiables :

- page API échouée / pagination structurellement incohérente ;
- écart fixed matériel ;
- couverture auction/économique incomplète ;
- `NEW`/`CHANGED` urgent non traité à cause du budget ;
- échec d'évaluation ;
- cache/état incompatible ;
- invariant comptable cassé.

## Runtime Playwright

- PR #13 mergée dans `main` : cache pip + cache Playwright + probe Chromium.
- Run initial `31479526838` : cache miss attendu, téléchargement initial puis cache Playwright ~279 MB, scan sain ~15 s.
- Run suivant `31480316615` : pip hit + Playwright hit, aucun téléchargement Chromium/FFmpeg/Headless Shell complet, scan sain ~14 s.
- Les runners GitHub-hosted sont jetables : les installations ne persistent pas physiquement, mais le cache évite les gros téléchargements à chaque production run.
- Self-hosted : **pas justifié actuellement** ; le cache est suffisant et évite maintenance/sécurité d'une machine permanente.

---

# V5 — expérimental, PR #8, NE PAS MERGER

- PR : **#8**.
- Branche exacte : `agent/v5-poketrace-cardmarket-market-data`.
- PR reste **draft, ouverte, non mergée**.
- V5 = diagnostic **RAW eBay** séparé de la V4 graded GCC.
- Aucun achat/bid/checkout/CardGrader.
- Ne pas passer PokeTrace Pro / Cardmarket payant avant validation Free exploitable.

## Architecture resolver retenue

1. **TCGdex = resolver principal multilingue**.
2. **PokeTrace Free = fallback identité + RAW US market**.
3. Pokémon TCG API = fallback ultérieur anglais/unknown.
4. Matching visuel local + OCR ciblé = arbitres conservateurs pour `AMBIGUOUS/INSUFFICIENT` seulement.
5. **JustTCG = seconde opinion / benchmark expérimental**, pas principal.
6. **Scrydex / Vision** = option réservée aux ambiguïtés persistantes après la chaîne gratuite.

Les workflows V5 live et benchmark doivent rester **`workflow_dispatch` uniquement** hors déclencheur ponctuel explicitement contrôlé.

## PokeTrace Free — référence live précédente

Dernier live PokeTrace avant les nouveaux correctifs :

- run : **`31483091017`** ;
- job : **`93752247632`** ;
- fingerprint : **`c48b11c284cf453b`** ;
- eBay search/getItem : **20/20** ;
- RAW acceptés : 19 ;
- usable : **11/20** ; ambiguous 4 ; insufficient 5 ;
- TCGdex : 16 requêtes, **2 hits**, 3 failures ;
- PokeTrace : 12 identities / 30 HTTP / **189 candidats uniques / 0 exact** ;
- candidats avec nom compatible : 21 ; set : 13 ; numéro : 5 ;
- nom+set : 2 ; nom+numéro : 1 ; set+numéro : 3 ;
- **nom+set+numéro : 1** ;
- `rejected variant : 1` ;
- visual/OCR rescues : 0 ;
- market values found : **0** ;
- achats/bids/checkout/CardGrader : 0.

### Important

**Aucun nouveau run PokeTrace live n'a été effectué depuis les changements variant/retrieval décrits ci-dessous.** Leur gain réel sur le ratio de candidats compatibles/exacts reste donc à mesurer. Ne jamais présenter le patch offline comme une amélioration live déjà démontrée.

## Nouveau modèle de variantes

Le matcher ne compare plus simplement une chaîne brute `variant`. Les dimensions sont canonicalisées séparément :

- finish : `normal/standard`, `holo/holographic/holofoil`, `reverse holo` ;
- edition : `1st Edition`, `Unlimited`, `Shadowless` ;
- promo : preuve par variante/rareté/set lorsqu'elle existe ;
- finishes spéciaux : Cosmos, Galaxy, Cracked Ice, Stamped, Poké Ball, Master Ball, etc.

Règles :

- holo ≠ reverse ;
- 1st Edition/Unlimited/Shadowless contradictoires = rejet ;
- une édition premium absente d'un côté n'est jamais inventée ;
- une finition spéciale non corroborée reste bloquante ;
- le variant peut départager des candidats mais **ne remplace jamais** nom+set+numéro.

Nouveaux compteurs :

- `all three + variant compatible` ;
- `all three but variant blocked` ;
- finish/edition/promo matches ;
- metadata missing ;
- conflits finish/edition/promo/special-finish séparés.

## PokeTrace retrieval — nouveau patch, pas encore live-validé

Objectif : corriger le problème du précédent run (**189 candidats mais très peu compatibles**) sans assouplir l'acceptation locale.

Ordre actuel :

1. recherche textuelle **contextuelle** avec les indices disponibles, par ex. `name + set + number` ;
2. `card_number` structuré lorsqu'il existe ;
3. fallbacks bornés broad-name / broad-number / broad-set selon les champs ;
4. **jamais** de nom d'affichage envoyé comme `set=` tant qu'un slug PokeTrace vérifié n'existe pas ;
5. acceptance locale toujours stricte nom/set/numéro/variant avec gagnant unique.

Le workflow PokeTrace affiche désormais `POKETRACE_MIN_REQUEST_INTERVAL_SECONDS=2.25` et le provider impose également ≥2.25 s.

## TCGdex — renforcé et toujours principal

Améliorations déterministes :

- uniquement langues API réellement supportées ; sinon métadonnées catalogue anglaises sans changer `CardIdentity.language` ;
- résolution set par nom et `set.id` ;
- formes sûres de `localId`, ex. `004 → 4`, ou casse alphanumérique ;
- lookup set/localId puis fallback direct `setId-localId` ;
- dénominateur complet contradictoire toujours bloquant (`4/130` ≠ `004/102`) ;
- numerator-only `4 → 004/102` reste autorisé lorsqu'il est déterministe ;
- `variants.firstEdition/holo/normal/reverse/wPromo` sert seulement à détecter une variante impossible, jamais à inventer la variante du listing ;
- failures séparées transport / HTTP / JSON / set-catalog / card-lookup.

---

# Benchmark TCGdex ↔ JustTCG sur le même sample

## Benchmark final — source de vérité = run `31489148268`

- run : **`31489148268`** ;
- job : **`93771289624`** ;
- fingerprint : **`7ef358f50c335f7d`** ;
- PokeTrace : **non injecté, non instancié, 0 appel** ;
- eBay : 20/20 ; RAW : 20 ; core identity suffisante : 14.

### TCGdex

- exact : **5/20** ;
- ambiguous : **3** ;
- unresolved : **12** ;
- requests : **28** ;
- failures : **0** ;
- transport / HTTP / JSON / set-catalog / card-lookup failures : **0/0/0/0/0** ;
- canonical changes name/set/number : 3/4/1 ;
- denominator conflicts : 2 ;
- set aliases unique/ambiguous : 8/1 ;
- no-match set/card : 2/3 ;
- localId alternate attempts/hits : **4/2** ;
- direct-card fallbacks/hits : **9/0** ;
- variant-impossible : **0** ;
- unsupported-language fallback : **1**.

### JustTCG set-aware

Le premier prototype JustTCG avait un mauvais contrat de requête et aucune cadence Free correcte ; ce benchmark initial ne doit pas être utilisé pour comparer les providers. Le resolver a ensuite été corrigé :

- suppression du paramètre invalide `include_statistics=false` ;
- cadence Free conservatrice **≥6.25 s** ;
- `Retry-After` + un retry sur 429 transitoire ;
- aucun retry pour quota daily/monthly ;
- catalogue `/sets` chargé/caché par jeu ;
- résolution locale d'un unique set ID stable ;
- requête carte `q + set ID + number` ;
- validation locale stricte nom/set/numéro/language/printing ;
- aucun prix JustTCG accepté par l'économie V5.

Résultat final :

- set catalog queries : 2 ;
- sets en cache : **655** ;
- set mappings uniques/ambigus/no-match : **4/2/3** ;
- card queries : 9 ;
- exact : **0/20** ;
- ambiguous : 3 ;
- unresolved : 17 ;
- request failures : **0** ;
- 429 : **0** ;
- candidats reçus : 6 ;
- rejetés nom : 5 ;
- candidats all-core : 1 ;
- ce dernier a été rejeté sur la variante.

### Conclusion benchmark

- both exact : 0 ;
- safe exact consensus : 0 ;
- hard exact disagreement : 0 ;
- **TCGdex-only exact : 5** ;
- JustTCG-only exact : 0 ;
- neither exact : 15.

**TCGdex reste clairement le resolver principal.** JustTCG reste un second avis expérimental ; il n'est pas promu en principal et ne nourrit pas encore l'économie V5.

---

# CI finale / post-resync — source de vérité actuelle

Après le benchmark, le `main` courant a été synchronisé **dans V5 uniquement**. La validation post-resync exacte est :

- run : **`31491040536`** ;
- job : **`93777368722`** ;
- V4 : **167/167** ;
- V5 : **270/270** ;
- `python -m compileall -q v5` : OK ;
- YAML : **11/11** pendant le run, workflow temporaire de validation inclus puis supprimé ;
- `git diff --check origin/main...HEAD` : OK ;
- fichiers V4 vs `main` : **IDENTIQUES** ;
- branche V5 behind `main` : **0** au moment de la validation ;
- appels PokeTrace / JustTCG / eBay live depuis cette CI : **0/0/0** ;
- secrets injectés dans cette CI : **0** ;
- achats/bids/checkout/CardGrader : **0**.

Les workflows temporaires de validation/patch doivent être supprimés après usage. Les deux workflows permanents V5 concernés restent manuels :

- `v5-live-raw-pipeline-diagnostic.yml` → `workflow_dispatch` ;
- `v5-catalog-identity-benchmark.yml` → `workflow_dispatch`.

---

# Prochaines actions V5

**Ne pas merger PR #8 pour l'instant.**

Ordre recommandé :

1. faire un **audit offline indépendant** du nouveau modèle variant, du retrieval contextuel PokeTrace, du TCGdex renforcé et du benchmark JustTCG ;
2. chercher spécifiquement comment **augmenter fortement la proportion de candidats PokeTrace réellement compatibles parmi les candidats reçus**, par meilleure canonicalisation/retrieval, jamais en relâchant l'acceptation ;
3. ensuite seulement, **un unique prochain run PokeTrace Free de 20 listings** ;
4. mesurer surtout : candidats `all three`, `all three + variant compatible`, exacts, reasons de rejet, champs récupérés, market exacts ;
5. comparer au dernier live PokeTrace `31483091017` sans confondre des fingerprints différents ;
6. conserver TCGdex principal ; JustTCG second avis ;
7. utiliser Scrydex/Vision seulement si les ambiguïtés persistantes restent matérielles ;
8. ne pas passer PokeTrace Pro/Cardmarket avant exacts/valeurs Free réellement exploitables.

---

# Gouvernance et sécurité

- **Ne jamais merger silencieusement PR #8.**
- Ne jamais assouplir le matching uniquement pour atteindre `15+/20`.
- `AMBIGUOUS` reste bloquant.
- Une source externe ne peut pas inventer une valeur achetable.
- Même grader/même grade reste la preuve principale pour le graded.
- Aucune identité higher-grade ne doit être inventée à partir d'un lower-grade.
- Données listing-level eBay/PokeTrace/JustTCG restent memory-only.
- Aucun achat, bid ou checkout automatique.
- Aucun CardGrader payant dans les diagnostics actuels.
- PokeTrace Pro/Cardmarket : pas maintenant.

---

# Référence cloud

La version de production recommandée est la **V4 cloud GitHub Actions** : aucun Mac ne doit rester allumé. Voir [`README_CLOUD.md`](README_CLOUD.md) pour l'installation et le fonctionnement détaillé.
