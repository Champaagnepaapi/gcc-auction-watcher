# GCC Auction Watcher

> **Source de reprise canonique — à lire en premier dans toute nouvelle conversation.**
> Cette section doit être mise à jour à chaque changement important afin qu'une nouvelle conversation puisse reprendre le projet sans reconstruire l'historique complet.

## Reprise du projet / état exact au 11 août 2026

### Production V4 — `main`

- La **V4 GCC** est la production canonique et ne doit pas être remplacée implicitement par V5.
- Scheduler production : **Cron-job.org → `workflow_dispatch` GitHub Actions toutes les ~10 minutes**. Le `schedule:` GitHub historique `3,13,23,33,43,53` a été supprimé car il était irrégulier et créait ensuite un double scan avec Cron-job.org.
- Univers : **cartes Pokémon individuelles uniquement**, découverte **0–100 €**, enchères **≤60 min**, décote plancher **30 %**.
- Enchères : discovery primaire **lot par lot** via `/on-sale-items?sellingTypeGroup=AUCTION&sortType=ENDING_SOON&status=ON_SALE`, avec `endTime` individuel et statut `COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS` lorsque l'horizon est prouvé. L'ancien collector reste fallback de sécurité.
- Prix fixes : API GCC `/on-sale-items`, file `NEW → CHANGED → NEVER_EVALUATED → STALE`, TTL 24 h.
- Valorisation : même grader/même grade prioritaire, médiane pondérée par récence, MAD/IQR, fourchette prudente, PSA APR en premier pour PSA exact lorsque possible, eBay public en fallback.
- Grade arbitrage autorisé uniquement avec référence robuste d'un grade inférieur du **même grader**, sans inventer la valeur du grade supérieur et avec preuve externe exacte avant notification.
- Anti-spam économique : renotification seulement si baisse de prix ≥10 %, amélioration de décote ≥5 points ou franchissement d'un seuil temporel ; une alerte haute priorité unique peut partir à ≤5 min si le prix reste sous le max prudent.
- Alertes techniques ntfy : une petite dérive du total fixed déclaré pendant une pagination saine (ex. `2953/2954`, aucune page échouée, aucun backlog/erreur) reste **dans les logs mais ne doit plus générer de notification téléphone**. Les pannes structurelles, écarts matériels, erreurs d'état/comptabilité, backlog urgent NEW/CHANGED et couverture auction incomplète restent notifiables.
- `state.json` est persistant via cache GitHub Actions.
- Chaque run est journalisé dans l'**issue #1** avec `trigger`, exit code, durée, opportunités, mode/scope auction, lignes/timers et fallback.
- **Aucun achat, bid ou checkout automatique.**

### V4 — optimisation runtime Playwright validée

- PR **#13** mergée dans `main` au commit `19942ce7cb26b2ba05bd51de8744d212933299bb`.
- GitHub-hosted runners sont des VM jetables : Python/paquets/Chromium ne peuvent pas rester installés physiquement sur la machine d'un run au suivant. La stratégie production est donc **cache pip + cache Playwright + probe de lancement**.
- Premier run post-merge `31479526838` : **cache miss attendu**, téléchargement initial puis sauvegarde d'environ 279 MB de cache Playwright ; probe Chromium OK sans fallback `--with-deps` ; scan V4 sain en ~15 s.
- Run suivant `31480316615` : **cache pip hit + cache Playwright hit**, log `Playwright browser cache hit: Chromium payload restored`, aucun téléchargement Chromium/FFmpeg/Headless Shell et aucun `playwright install --with-deps chromium`; scan V4 sain en ~14 s.
- Le cache Playwright est restauré depuis GitHub Actions (~266 MB) sur une VM neuve : ce n'est pas une installation persistante locale, mais cela supprime les téléchargements CDN/apt complets à chaque scan production.
- Si le probe Chromium échoue sur une future image runner, fallback automatique `playwright install --with-deps chromium` puis nouveau probe.
- Un runner self-hosted conserverait réellement les installations entre jobs, mais n'est **pas justifié actuellement** : le cache GitHub-hosted est suffisant et évite la maintenance/sécurité d'une machine permanente.

### V5 — expérimental, PR #8, NE PAS MERGER

- PR **#8**, branche exacte : `agent/v5-poketrace-cardmarket-market-data`.
- V5 reste un diagnostic **RAW eBay** séparé de la V4 graded GCC.
- Architecture retenue : **TCGdex principal multilingue → PokeTrace Free fallback identité + RAW US market → Pokémon TCG API fallback → arbitres locaux visuel/OCR pour `AMBIGUOUS/INSUFFICIENT`**.
- **JustTCG** reste candidat comme seconde opinion/fallback à benchmarker sur le même échantillon avant toute promotion en principal.
- **Scrydex / Vision** reste une option sérieuse pour les cas durablement ambigus après épuisement de la chaîne gratuite ; ne pas introduire le coût juste pour forcer le hit-rate.
- Le workflow live V5 doit rester **manuel (`workflow_dispatch`)** pour protéger le quota PokeTrace Free.
- PokeTrace Free : clé dans GitHub Secret `POKETRACE_API_KEY`, **250 req/j**, US + RAW uniquement, cadence effective ≥2.25 s, pas de Cardmarket EU/graded en Free.
- Données listing-level eBay/PokeTrace et images : mémoire-only ; ne pas persister/loguer itemId, titre, URL ou prix individuel.

#### Correctifs Codex/post-audit — maintenant appliqués

Les blockers identifiés après le premier audit Codex ont été corrigés et couverts par tests :

1. **PokeTrace `set=`** : aucun nom d'affichage de set n'est envoyé comme slug non vérifié ; le set reste un discriminant strict local.
2. **Numéro manquant** : Hybrid peut appeler PokeTrace avec deux champs forts, notamment `name + set`, pour récupérer le troisième champ si un gagnant unique existe.
3. **Conflit de dénominateur TCGdex** : `4/130` vs `004/102` est bloquant ; `4 → 004/102` reste autorisé lorsqu'il est déterministe.
4. Résolution TCGdex déterministe supplémentaire par `set.id` et compteurs agrégés de no-match/canonicalisation/conflits.
5. Les matchers identity/market PokeTrace partagent les mêmes règles strictes ; aucune ambiguïté n'est transformée artificiellement en exact.

#### Synchronisation et validation offline avant le dernier live

Le `main` courant a été mergé **dans V5 uniquement** avant le run live ; V5 n'a jamais été mergé dans `main`.

Validation GitHub Actions offline : **run `31482959188`**

- V4 : **167/167** ;
- V5 : **234/234** ;
- `python -m compileall -q v5` : OK ;
- tous les YAML : OK ;
- `git diff --check` : OK ;
- fichiers V4 vs `main` : **IDENTIQUES** ;
- appels PokeTrace live : 0 ;
- secrets injectés : 0 ;
- achats/bids/checkout/CardGrader : 0.

Le workflow CI temporaire utilisé pour cette preuve a été supprimé.

#### Dernier live contrôlé PokeTrace Free — référence actuelle

Un seul run Free a été déclenché après la CI puis le trigger temporaire a été retiré immédiatement. Le workflow live est revenu en **`workflow_dispatch` uniquement**.

- run : **`31483091017`** ;
- job : **`93752247632`** ;
- fingerprint : **`c48b11c284cf453b`** ;
- conclusion : success ;
- eBay OAuth : 200 ;
- search/getItem : **20/20** ;
- RAW acceptés : **19** ;
- usable identities : **11/20** ;
- ambiguous : 4 ;
- insufficient : 5 ;
- market values found : **0** ;
- achats/bids/checkout : **0/0/0**.

Le fingerprint diffère des runs précédents : **ne pas présenter `9/20 → 11/20` comme une amélioration apples-to-apples**.

##### TCGdex sur ce run

- requests : 16 ;
- hits : **2** ;
- TCGdex-only rescues : **2** ;
- appels PokeTrace évités grâce à TCGdex : **2** ;
- unique set-alias resolutions : 4 ;
- ambiguous set aliases : 1 ;
- skipped missing set/card number : 6 ;
- no-match set : 5 ;
- no-match card : 6 ;
- catalog request failures : **3** ;
- denominator conflicts : 0 sur cet échantillon ;
- numerator-only canonicalizations : 0 ;
- canonical name/set/number changes : 0/0/0.

**Diagnostic TCGdex actuel :** il reste resolver principal, mais `2/20` hits + les buckets no-match + 3 request failures doivent être audités avant de conclure que la base elle-même est insuffisante.

##### PokeTrace identity sur ce run

- identities queried : 12 ;
- HTTP search attempts : 30 ;
- exact matches : **0** ;
- no match : 12 ;
- request failures : 0 ;
- 429 : 0 ;
- unique candidates received : **189** ;
- candidates name matched : 21 ;
- set matched : 13 ;
- card number matched : 5 ;
- name+set : 2 ;
- name+number : 1 ;
- set+number : 3 ;
- **name+set+number : 1** ;
- rejected only name : 2 ;
- rejected only set : 0 ;
- rejected only card number : 3 ;
- **rejected variant : 1** ;
- champs récupérés : 0.

**Nouveau diagnostic PokeTrace prioritaire :** un candidat passe **nom + set + numéro** mais aucun exact n'est retenu, tandis qu'un rejet `variant` est compté. La prochaine analyse P0 est donc la **sémantique des variantes**. Ne pas supprimer le garde-fou : vérifier si PokeTrace et eBay/TCGdex décrivent la même variante avec des conventions différentes ou s'il s'agit d'un vrai conflit.

La récupération PokeTrace n'est plus simplement vide : 189 candidats ont été reçus. Les requêtes structurées sont souvent vides alors que les fallbacks larges trouvent des candidats ; la canonicalisation/retrieval reste donc à surveiller.

##### Visuel / OCR sur ce run

- visual attempted : 6 ;
- no visual candidates after metadata filter : 4 ;
- candidate scans considered/downloaded : 16/7 ;
- candidate image failures : **8** ;
- visual rescues : 0 ;
- OCR attempted/calls : 2/12 ;
- OCR rescues : 0.

Le visuel/OCR reste un arbitre secondaire ; la fiabilité des images canoniques candidates est encore insuffisante pour en faire la voie principale.

##### PokeTrace Free market sur ce run

- live calls : **32** ;
- cache hits : **9** ;
- US exact market matches : **0** ;
- no match : 14 ;
- ambiguous : 1 ;
- request failures : 0 ;
- rate limited : 0 ;
- EU/CardMarket requests : 0 ;
- graded values accepted : 0 ;
- market values found : **0**.

Le provider impose bien `>=2.25s`. Le workflow affiche encore une valeur de compatibilité `2.05` : à aligner à `2.25` pour clarté lors d'un prochain cleanup, même si le runtime est déjà sûr.

#### Prochaines actions V5

**Ne pas merger PR #8 pour l'instant.**

Priorités :

1. auditer le candidat PokeTrace qui passe nom+set+numéro mais échoue sur la variante, sans assouplir l'ambiguïté ;
2. auditer les faibles hits TCGdex, ses buckets `no-match set/card` et les **3 request failures** ;
3. aligner l'env affiché `POKETRACE_MIN_REQUEST_INTERVAL_SECONDS` de `2.05` vers `2.25` ;
4. si la chaîne gratuite reste insuffisante, benchmarker **JustTCG en parallèle sur exactement le même sample** avant toute décision de le rendre principal ;
5. garder Scrydex/Vision pour les cas persistants après TCGdex/PokeTrace/JustTCG/arbitres locaux.

La cible `15+/20` reste un objectif de couverture **si les preuves disponibles le permettent**, jamais une obligation justifiant des faux positifs.

### Règles de gouvernance du projet

- **Ne jamais merger silencieusement la PR #8.** Discuter du live et des métriques avant merge.
- Ne pas passer PokeTrace Pro / Cardmarket payant tant que Free n'est pas correctement exploité et mesuré.
- Ne pas assouplir le matching juste pour atteindre artificiellement `15+/20` : `AMBIGUOUS` reste bloquant.
- Une source externe ne peut pas inventer une valeur achetable ; exact same-card/same-grader/same-grade reste prioritaire.
- Les données eBay listing-level (itemId, titre, URL, images, prix) restent mémoire-only dans le diagnostic V5 et ne doivent pas être persistées/loguées individuellement.
- Scrydex doit rester dans le radar, particulièrement son modèle `number` / `printed_number` / expansion / language et Vision.
- La cible `15+/20` est un objectif de couverture **si les preuves disponibles le permettent**, jamais une obligation qui justifie des faux positifs.

---

La version de production recommandée est la **V4 cloud GitHub Actions** : aucun Mac ne doit rester allumé. Voir [`README_CLOUD.md`](README_CLOUD.md) pour l'installation et le fonctionnement détaillé.

## V4 — état de production

Le watcher scanne **GCC Marketplace** toutes les 10 minutes via un déclencheur externe **Cron-job.org → `workflow_dispatch` GitHub Actions** et ne considère que les **cartes Pokémon individuelles**. Les boosters, packs, displays, boxes, ETB, coffrets, blisters, bundles, decks, tins et autres produits scellés/non-cartes sont exclus.

### Univers économique

- découverte : **0 à 100 €** ;
- enchères : timer individuel **≤ 60 minutes** ;
- décote minimale : **30 %**, relevée automatiquement lorsque les comparables sont faibles ;
- aucun achat, aucune enchère et aucun checkout automatique.

La découverte a été volontairement élargie sous 10 € afin de ne pas rater une anomalie extrême. Un prix très bas ne suffit jamais à créer une opportunité : les mêmes contrôles d'identité, de grade, de comparables et de valorisation restent obligatoires.

## Découverte GCC

### Prix fixes

Les prix fixes utilisent l'API publique GCC `/on-sale-items`, avec pagination complète et filtres Pokémon/cartes/prix appliqués par GCC puis défendus localement.

### Enchères

La découverte primaire reproduit la logique de `/filtres/auctions` au **niveau des lots**, via l'API publique GCC :

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

Le watcher s'arrête lorsque l'ordre `ENDING_SOON` permet de prouver que l'horizon de 60 minutes a été franchi, ou lorsque l'inventaire est épuisé. Lorsque cette preuve est obtenue, le statut spécifique est :

```text
COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
```

Si l'API, la pagination, l'ordre ou les `endTime` deviennent incohérents, l'ancien collector auction reste disponible comme **fallback de sécurité**.

## Valorisation

La valorisation utilise une médiane pondérée par récence, un filtre robuste MAD/IQR, une fourchette prudente et un seuil de décote adaptatif.

Pour les cartes PSA suffisamment identifiées, **PSA Auction Prices Realized** est interrogé en premier comme source indépendante de validation, puis eBay public sert de fallback lorsque les données PSA sont insuffisantes ou indisponibles. Les prix fixes comme les enchères doivent rester sous le prix maximal conseillé.

Une carte de grade supérieur proposée autour du marché robuste d'un grade inférieur de la **même société de grading** peut être signalée comme **ARBITRAGE GRADE**, sans inventer la valeur du grade supérieur. Cette voie exige une preuve externe exacte suffisante avant notification. Les comparables d'autres graders restent secondaires et ne créent pas seuls une valeur achetable sans ratio empirique suffisamment documenté.

## État, anti-spam et observabilité

`state.json` est restauré/sauvegardé via le cache GitHub Actions. La file fixed priorise `NEW → CHANGED → NEVER_EVALUATED → STALE`, avec une réévaluation à 24 h par défaut.

Une opportunité déjà signalée n'est renotifiée que si le prix baisse d'au moins 10 %, si la décote gagne au moins 5 points, ou si une enchère franchit un seuil temporel important. Une alerte haute priorité unique peut être envoyée à cinq minutes ou moins si le prix reste sous le prix maximal conseillé.

### Notifications techniques ntfy

Les notifications techniques sont séparées des alertes d'opportunité. Une couverture marquée `INCOMPLETE` dans les logs ne signifie pas automatiquement qu'une carte intéressante a été trouvée ou ratée.

Un **petit drift dynamique du total fixed déclaré** pendant une pagination par ailleurs saine — par exemple `2953/2954` avec 30/30 pages réussies, 0 page échouée, 0 erreur de parsing/interne, 0 listing non comptabilisé, 0 backlog urgent et état cohérent — reste visible dans les diagnostics mais est **silencieux sur ntfy**.

La notification technique reste active pour les cas actionnables, notamment :

- page API réellement échouée ou réponse/pagination structurellement incohérente ;
- écart fixed matériel au-delà de la petite tolérance de dérive ;
- couverture auction ou économique incomplète ;
- `NEW`/`CHANGED` urgent non traité à cause du budget ;
- échec d'évaluation, état/cache incompatible ou invariant comptable cassé.

Chaque run V4 est aussi journalisé dans l'**issue #1** avec notamment :

- `trigger=workflow_dispatch` pour la cadence production externe Cron-job.org ;
- statut/exit code/durée ;
- nombre d'opportunités finales ;
- mode de découverte auction ;
- statut de couverture auction ;
- lots auction découverts ;
- timers parsés ;
- enchères dans l'horizon ;
- utilisation éventuelle du fallback legacy.

## V5 — expérimental, pas en production

La V5 reste séparée de la V4 et travaille actuellement sur les **listings RAW eBay** et leur identité canonique.

- **TCGdex** reste le resolver catalogue multilingue principal ;
- **PokeTrace Free** est authentifié et testé en live pour les données RAW US, mais aucun exact market match n'est encore obtenu ;
- la PR V5 correspondante reste en **draft** et ne remplace pas le watcher V4 ;
- **JustTCG** reste candidat à un benchmark parallèle / seconde opinion ;
- **Scrydex** reste dans le radar comme éventuel bridge d'identité canonique/Vision si la chaîne gratuite ne suffit pas ;
- aucune dépendance payante ni passage à PokeTrace Pro n'est justifié tant que le matching exact n'est pas démontré.

La règle de sécurité reste la même pour toutes les versions : **le projet ne passe jamais d'achat, d'enchère ou de checkout automatiquement**.
