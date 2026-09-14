# V4 multi-market — preuves et limites, 14 septembre 2026

Branche candidate uniquement : PR [#268](https://github.com/Champaagnepaapi/gcc-auction-watcher/pull/268), `fix/v4-global-coverage-losses-20260907`, OPEN/DRAFT/NON MERGED.

Base production vérifiée : `main@b43dec6084f341b2b52301a4f0542d6f616cf1e2`. Début de cette mission multi-market : `eb62e78463235effbb267aa9f71f5c3a49a3b407`. Les corrections décrites ici ne sont pas déployées sur `main`.

## Lecture des résultats

Une identité commerciale parsée par un adaptateur n'est pas nécessairement un `EXACT` canonique TCGdex. Les compteurs distinguent candidats découverts, identités commerciales, échantillon économique sélectionné, `EXACT` canoniques et valorisations indépendantes. Le budget de sélection reste 50 par run ; un échantillon de 50 n'est pas une évaluation exhaustive du stock.

`OPERATIONAL` signifie qu'un chemin réel découverte → identité exacte → valeur indépendante → coût prouvé → décision a été observé. Une décision négative faute de décote valide ce chemin ; elle n'autorise aucune notification artificielle.

`PROVIDER_BLOCKED` doit préciser la donnée ou l'accès externe manquant dans la configuration courante. Ce statut ne signifie pas nécessairement que le site est inaccessible. Une erreur de parseur, une pagination seulement partielle ou une panne réseau de l'environnement d'audit ne suffisent pas à le justifier.

## Classement final dans la configuration observée

Global automatique [**34812934273 — SUCCESS**](https://github.com/Champaagnepaapi/gcc-auction-watcher/actions/runs/34812934273), runtime `29f448a7441e82267fc9d84c2b0f9a52168e77cb`. Les sept marketplaces ont été interrogées réellement en lecture seule par le même runner. **GCC est opérationnel dans le scope vault ; les six autres restent bloqués pour une décision économique autonome avec les données/conditions acheteur actuellement disponibles.** Cela ne prétend pas que leurs sites sont inaccessibles, ni qu'aucun travail d'extraction futur n'est possible.

`EXACT` dans la colonne canonique est mesuré sur la sélection économique, pas sur tout l'inventaire. La colonne commerciale conserve le compteur historique `scan_status.exact` des adaptateurs ; elle n'est pas rebaptisée EXACT canonique. Les pages Fanatics sont des observations bornées, pas une garantie de 15 pages distinctes.

| Marketplace | Classement | Candidats bruts | Identités commerciales | Sélection | EXACT canoniques | Offres avec valeur indépendante | Opportunités | Pagination / compteur |
|---|---|---:|---:|---:|---:|---:|---:|---|
| GCC | OPERATIONAL | 13409 | 1188 | 12 | 2 | 2 | 0 | complète (135) |
| FANATICS | PROVIDER_BLOCKED | 120 | 2 | 2 | 2 | 0 | 0 | partielle/non prouvée (15) |
| COMC | PROVIDER_BLOCKED | 328 | 81 | 12 | 0 | 0 | 0 | partielle/non prouvée (4) |
| MAGI | PROVIDER_BLOCKED | 93 | 46 | 12 | 1 | 0 | 0 | partielle/non prouvée (1) |
| CARDOVA | PROVIDER_BLOCKED | 115 | 23 | 12 | 0 | 0 | 0 | partielle/non prouvée (24) |
| MERCARI | PROVIDER_BLOCKED | 15 | 0 | 0 | 0 | 0 | 0 | partielle/non prouvée (1) |
| SNKRDUNK | PROVIDER_BLOCKED | 21 | 0 | 0 | 0 | 0 | 0 | partielle/non prouvée (1) |

| Marketplace | Motif et portée du classement |
|---|---|
| GCC | Chemin confirmé pour achat conservé au vault ; livraison domicile non incluse. Découverte complète, évaluation économique échantillonnée. |
| FANATICS | Coût acheteur final non prouvé ; valorisation indépendante compatible avec la microvariante absente des réponses observées. |
| COMC | Coût Store Credits/taxe/mode de détention ou livraison non prouvé. Aucun EXACT canonique dans la sélection actuelle ; les libellés commerciaux ne remplacent pas une preuve catalogue. |
| MAGI | Coût acheteur/route/paiement non prouvé. Projection catalogue Classic et certaines valeurs gradées exactes absentes des sources accessibles. |
| CARDOVA | Financement/paiement et premium Auction applicables non prouvés. Aucune valeur exacte indépendante dans la sélection actuelle. |
| MERCARI | Preuves item de langue/numéro/grade/matériau manquantes ou contradictoires dans les annonces inspectées ; route acheteur et coût complet non établis. |
| SNKRDUNK | Langue de carte et offre individuelle compatibles non prouvées ; le JSON-LD observé vise un catalogue AggregateOffer. Route acheteur/coût complet non établis. |

Un `PROVIDER_BLOCKED` porte ici sur le chemin économique et le contexte public anonyme audités. Les coûts absents sont un blocage indépendant de la couverture du parseur : inventer un financement, une taxe, une livraison ou un rang acheteur pour obtenir zéro frais serait incorrect. Le déblocage nécessite les données listées plus bas, puis leur intégration générique et une nouvelle validation live. Ce classement ne garantit pas qu'il suffit d'ajouter une clé pour tout rendre opérationnel.

La pagination partielle, le plafond de détail Fanatics, le budget de langue et l'échantillon de 50 sont des limites logicielles volontaires, **pas des blocages fournisseurs**. Aucun catalogue complet ni maximum théorique de couverture n'est revendiqué. Pour SNKRDUNK, `POKEMON_CATEGORY_UNPROVEN` décrit le gate du payload actuellement extrait : le DOM réel contient une marque Pokémon. Le blocage externe démontré ne repose donc pas sur une prétendue absence de catégorie, mais sur les preuves item/langue/offre et conditions économiques manquantes.

### Rejets et erreurs dans ce live

- **GCC** — état adaptateur `OK` ; public on-sale inventory
- **FANATICS** — état adaptateur `OK` ; broad Pokemon marketplace retrieval; explicit provider language+PSA+collector coordinate -> exact TCGdex; GCC identity catalog not required; rejects={'explicit_language_unproven': 18, 'supported_psa_grade_unproven': 8, 'tcgdex_aucune identité tcgdex exacte': 16, 'fanatics_language_probe_budget_exhausted': 51, 'tcgdex_card_name_conflict': 1, 'collector_number_unproven': 4}; collection=RESULTS; http=200; observations=15; stop=OBSERVATION_LIMIT; container_present=True; navigation_labels=('See More', 'See More', 'Go to previous page', 'Go to next page'); scroll_regions=0; pagination=NEXT_CLICKED
- **MAGI** — état adaptateur `OK` ; broad Pokemon PSA10 inventory query; Magi native full-number+set-code -> exact Japanese TCGdex -> deterministic Latin same-card alias when available, otherwise TCGdex-proven Japanese native identity; no per-card searches; GCC identity catalog not required; tcgdex_ja_requests=9; tcgdex_alias_requests=6; rejects={'reviewed_classic_coordinate_absent': 1, 'sensitive_variant_unproven': 10, 'japanese_set_name_unproven': 12, 'multi_item_listing': 7, 'target_japanese_card_name_unproven': 2, 'target_catalog_unproven:TCGDEX_NO_SET_WITH_OFFICIAL_DENOMINATOR': 1, 'target_catalog_unproven:TCGDEX_NO_ALPHANUMERIC_LOCALID': 1, 'collector_number_ambiguous': 1, 'target_catalog_unproven:TCGDEX_EXACT_NAME_RARITY_NOT_FOUND': 3, 'magi_rarity_unproven': 1, 'target_catalog_unproven:TCGDEX_MULTIPLE_CARDS_FOR_FULL_NUMBER': 1, 'sold_listing': 3, 'target_catalog_unproven:TCGDEX_NO_CARD_FOR_FULL_NUMBER': 1, 'single_quantity_unproven': 3}; manifest_rows=93; manifest_truncated=0; PAGINATION_UNPROVEN; one observed search page; tcgdex_recovery_requests=46; tcgdex_recovery_card_identity_reserve=15; tcgdex_recovery_nonpriority_requests=33; tcgdex_recovery_breakdown=card_detail:5,card_search:8,set_coordinate:22,set_detail:2,sets_catalog:1,sets_filtered:8; tcgdex_recovery_cache_hits=set_coordinate:14,sets_catalog:20,sets_filtered:7
- **COMC** — état adaptateur `OK` ; native public PSA10 Pokemon rows; no GCC catalog dependency; rejects={'POKEMON_SET_UNPROVEN': 27, 'LANGUAGE_UNPROVEN': 205, 'SET_CODE_LABEL_PROOF_UNAVAILABLE': 15}; pagination total unproven
- **MERCARI** — état adaptateur `UNAVAILABLE` ; public_state=RESULTS; http=200; inspected=15; catalogs=0; rejects={'CONTENT_UNPROVEN': 1, 'LANGUAGE_UNPROVEN': 6, 'GRADE_UNPROVEN': 1, 'NUMBER_UNPROVEN': 1, 'MATERIAL_METADATA_UNPROVEN': 4, 'IDENTITY_FIELDS_UNPROVEN': 2}; detail_cap_reached=False; pagination unproven; costs require buyer route
- **SNKRDUNK** — état adaptateur `UNAVAILABLE` ; public_state=RESULTS; http=200; inspected=20; catalogs=0; rejects={'POKEMON_CATEGORY_UNPROVEN': 20}; detail_cap_reached=True; pagination unproven; costs require buyer route
- **CARDOVA** — état adaptateur `OK` ; public anonymous GET-only browser capture; no login/session/cookies; json=144; raw=115; scope=37; rejects={'non_pokemon_or_unproven_category': 43, 'unsupported_grader': 16, 'missing_card_number': 17, 'unsupported_grade': 1, 'unsupported_language': 1}; provider_pagination_complete=False; fixed payment/funding charges unproven; auction buyer premium unproven

`UNAVAILABLE` pour Mercari/SNKRDUNK dans le rapport adaptateur signifie ici zéro listing admis après inspection ; leurs recherches publiques ont répondu HTTP 200 avec des URL. Ce n’est pas une preuve de 403 ou de fermeture du site.

### Budgets observés, sans augmentation

Le snapshot TCGdex source suivant ne déclenche aucun appel :

```json
{
  "after_discovery": {
    "cached_proofs": 1,
    "cached_unavailable": 0,
    "limit": 12,
    "outcomes": {
      "PROVEN": 1
    },
    "remaining": 11,
    "requests": 1,
    "retryable_misses": 0
  },
  "after_valuation": {
    "cached_proofs": 7,
    "cached_unavailable": 3,
    "limit": 60,
    "outcomes": {
      "HTTP_404": 2,
      "INVALID_PROOF": 1,
      "PROVEN": 7
    },
    "remaining": 50,
    "requests": 10,
    "retryable_misses": 0
  },
  "before_discovery": {
    "cached_proofs": 0,
    "cached_unavailable": 0,
    "limit": 12,
    "outcomes": {},
    "remaining": 12,
    "requests": 0,
    "retryable_misses": 0
  }
}
```

Plafonds inchangés : sélection Global 50 ; Magi recovery 50 total / 35 broad / 15 réserve ; TCGdex natif japonais 60 ; preuve source 60 ; PokeTrace 60. Les requêtes et résultats économiques détaillés restent dans le log/artifact du run cité. Aucun budget de ce tableau ne constitue une autorisation de notifier sans identité, valeur et coût prouvés.



### Comparaison des derniers runs et interprétation des compteurs

Les 50 URL sélectionnées du Global `34811825409` (`39fcf5a...`) sont toutes présentes dans `34812934273` (`29f448...`). **Aucun changement de statut canonique, de statut de valorisation ou de décision** sur ces 50 URL. Le dernier correctif de cache n'a donc pas provoqué de régression observée dans cet échantillon. Le brut GCC varie de 13 411 à 13 409, sans changement de sélection économique ; les autres compteurs de discovery sont identiques.

GCC confirme les deux offres Charmander SV2a-168/165 japonais PSA10, `017d9a28-9eec-42d6-91b9-f339dea881da` (120 EUR) et `ff7796c9-c432-4e4d-beba-3cec9dfdc07e` (133 EUR). Même identité canonique, une valorisation PPT indépendante unique, deux offres et deux décisions `NO_GLOBAL_EDGE` : ne pas compter cela comme deux cartes catalogue distinctes ou deux sources économiques indépendantes.

Fanatics conserve Shining Mewtwo Neo Destiny `neo4-109` (`3f773c19-33b5-4b78-ab98-5055f436256d`) et Litten MEP `mep-044` (`db444e5e-83c6-4145-8de2-fb93e248d5a8`), tous deux EXACT mais `PPT:MICROVARIANT_UNPROVEN` et coût all-in absent. Le passage antérieur de 24 à 120 URL est un gain réel de collecte après correction des contrôles Next ; le passage de zéro à deux exacts dans les derniers runs s'est produit sans nouveau code d'identité entre ces heads. Le renouvellement d'inventaire reste distinct des corrections logicielles.

Magi est stable à 93 candidats / 46 identités commerciales dans les deux derniers runs. Le dernier manifeste couvre les 93 candidats sans troncature ; le détail expose trois `sold_listing` exclus. Les 49 identités commerciales d'un run antérieur ne sont pas 49 EXACT canoniques. Sans manifeste par URL dans certains vieux runs, ne pas inventer l'identité des deux pertes historiques `33/93 → 31/93`. Sur le dernier échantillon économique, Lugia V S-P-324 (`52952939`) est EXACT ; les 11 autres sont principalement Classic sans projection canonique prouvée.

Budgets réellement consommés : Magi recovery **46/50**, broad **33/35**, réserve **15** conservée ; natif japonais **9** requêtes et aliases latins **6**. Source TCGdex : **1/12** après discovery, **10/60** après installation de la capacité Global et valuation, dont sept preuves, deux HTTP 404 et un payload sans preuve valide. **Zéro échec réessayable et aucun épuisement** dans ce live ; l'hypothèse d'un affamement actuel par ce budget est écartée pour cet échantillon.

PPT : **5 appels HTTP / 23 crédits**, une identité MATCHED, 19 705 crédits quotidiens restants dans la réponse observée. PokeTrace : **2 appels**, plafond effectif FREE, **7 tiers raw avec prix**, **24 tiers gradés ignorés**, zéro usage gradé. PriceCharting : **35 tentatives / 0 matched**, HTTP 403 publics. Ces derniers sont des erreurs provider, pas des ventes absentes. Opportunités signalables **0**, notifications envoyées **0**.

La couverture COMC 328 lignes / 81 identités commerciales, Cardova 115 / 23, Mercari 15 URL et SNKRDUNK 21 URL est stable entre ces deux runs. Les changements d'inventaire par rapport aux runs plus anciens ne sont pas imputés aux correctifs sur la seule différence d'un total. Les anciens tests DOM qui échouaient sur l'encodage des fixtures ont été corrigés et les quatre contrats Chromium passent avant les appels fournisseurs.

## Corrections génériques livrées

- **Identité** : P5 PriceCharting et P6 PPT reviewed-set passent par les gates canoniques avant `MATCHED`. Nom, set, numéro, langue et dimensions matérielles contradictoires restent bloquants. La copie d'un nom fournisseur dans une identité catalogue ne peut plus fabriquer la concordance, y compris dans les recoveries partagés REST/source. Les noms multilingues ne sont acceptés que lorsque la même carte du pin TCGdex les prouve. Aucun alias durable carte par carte n'a été ajouté pour masquer une absence de preuve.
- **Installers / pagination** : P7 Fanatics capture ses fonctions originales après le garde d'idempotence ; P8 Cardova lie les preuves de pagination à la requête, à la lane et à l'enveloppe correspondantes. Les collecteurs attendent un contenu explicite dans des bornes fixes. Fanatics accepte plusieurs contrôles Next uniquement s'ils prouvent tous la même destination autorisée ; une liste stable n'est pas une preuve d'exhaustivité.
- **Indépendance des marchés** : COMC découvre maintenant ses propres lignes publiques, sans précondition d'identité GCC. Mercari et SNKRDUNK sont raccordés à la vraie chaîne Global avec des contextes anonymes séparés. Les recherches publiques ne constituent pas une preuve d'identité ou de vente.
- **Mercari** : les champs de l'item sont liés au H1 unique et aux sections publiques « 商品の特徴 » / « 商品の情報 ». Recommandations, vendeur et catalogue « même produit » ne prouvent pas la carte proposée. Les contradictions JSON-LD/DOM persistent. Les tests exécutent le JavaScript réel dans Chromium sur des fixtures HTTP UTF-8.
- **SNKRDUNK** : la découverte reconnaît la route publique actuelle `/en/trading-cards/used/listings/<ULID>` et attend de façon bornée l'hydratation du contenu. Une fiche catalogue et ses AggregateOffer ne deviennent pas une annonce individuelle ; aucune langue n'est déduite de la langue du site.
- **Coûts** : Fanatics et Cardova ne déclarent plus par défaut zéro frais de paiement. Sans route acheteur prouvée, `all_in_eur` reste absent et la décision reste `NO_ACTIONABLE_ALL_IN_OFFER`. Les prix de listing ne deviennent jamais une fair value.
- **Observabilité / budgets** : sélection équitable entre marketplaces dans le même plafond de 50 ; manifeste final Magi et manifeste économique par URL à partir des données déjà calculées. Magi HTTP non-2xx/collecte vide non prouvée reste indisponible/incomplet. Recovery Magi inchangé : 50 total, 35 broad, 15 réserve exacte. Aucun diagnostic ne déclenche de requête TCGdex supplémentaire.

## PokeTrace : droits d'accès et absence de données

L'utilisateur a signalé l'expiration de Pro le 11 septembre. L'API `/auth/info` observée dans les validations continuait à annoncer PRO actif. Le runtime ne prétend donc pas avoir observé une authentification réellement Free : le live a appliqué un **plafond effectif FREE** explicite.

Dans le run [34743590249](https://github.com/Champaagnepaapi/gcc-auction-watcher/actions/runs/34743590249), deux appels bornés ont observé huit tiers raw utilisables, tandis que 21 tiers gradés ont été ignorés par la politique Free ; zéro requête gradée utilisée. Le plafond global de 60 n'a pas été augmenté. Le rythme Free documenté est conservé.

Une donnée gradée non accessible avec le plan effectif reste `ACCESS_RESTRICTED` / `TRANSIENT_UNAVAILABLE`, non cacheable comme absence. Seule une réponse accessible et réellement vide peut constituer `CLEAN_NO_MATCH`. Données insuffisantes, payload malformé, 401/403 et 429 gardent leurs états distincts.

Sources : [authentification et droits](https://poketrace.com/docs/authentication), [erreurs](https://poketrace.com/docs/errors), [plans](https://poketrace.com/pricing). Aucun secret n'est copié dans ce document.

## GCC : découverte, économie et résiduel Auction

Le run [34743590249](https://github.com/Champaagnepaapi/gcc-auction-watcher/actions/runs/34743590249), head `12e6bf21f42b9c392171a19bd9a7321a80ae5d9c`, a découvert 15 246 lignes GCC, 1 445 identités commerciales, sur 153 pages complètes. Parmi 13 offres sélectionnées : deux identités canoniques exactes, deux valorisations PPT indépendantes et deux décisions `NO_GLOBAL_EDGE` avec coûts de 100 et 110 EUR. Les items étaient Ivysaur SV2a-167/165 (`d84b91a6-1bff-49e5-8124-f8c01947d27b`) et Wartortle SV2a-171 (`03a9458f-fd71-4815-8cd8-23d4634931ea`).

Le scope de coût GCC existant est la conservation au vault, pas une expédition domicile supposée gratuite. Une alerte `GCC SCAN INCOMPLETE` combinée peut venir du backlog économique externe malgré une découverte complète. Aucun budget n'a été relevé pour faire disparaître cette alerte.

Le run Auction [34775550636](https://github.com/Champaagnepaapi/gcc-auction-watcher/actions/runs/34775550636), head `bb519bd279f25bee485e2b46d94e6cb7a9d79b0e`, a échoué avec 239 candidats effectifs, 227 legacy, zéro legacy manquant, zéro échec de page et neuf timers `UNKNOWN`. Les neuf items provenaient de la vente privée `2535c2f93c6e`.

Le 13 septembre à 18:55 UTC, neuf GET publics item par item ont tous répondu HTTP 200, avec l'ID demandé exact, `sellingType=FIXED_PRICE`, `status=ON_SALE`, `endTime=null`. Ce contrôle postérieur prouve leur état à cet instant ; il n'est pas une reconstitution fictive de leurs réponses au moment du run.

IDs vérifiés : `16986797-9298-412f-8784-27379e86e7d3`, `382542c3-6eff-4e8d-9c39-4e26d91041f8`, `5a39386c-989b-4d55-b3a7-a9841a4c8a38`, `6b466a2f-3546-4b87-a3da-443d0d58c18a`, `6df5c551-7fc2-4979-b075-a9afabaa2b1e`, `7126e2f5-1268-4aa6-9b43-7998651ea54c`, `8fd40fd8-f9ee-47cf-b214-01554b7ac3f9`, `a5541ac3-2541-4090-81ed-696ac343ffb1`, `f77c9ec9-64a5-46c1-ad22-fc51cda0364c`.

Le commit `a2aefbba67a82608d991a8070edb8a795bfa62e0` ajoute `OUT_OF_SCOPE` à `compare_auction_discovery._inspect_legacy_timer` et `resolve_legacy_ids`. Il observe uniquement la réponse déjà chargée par l'inspection existante ; aucun GET supplémentaire en runtime. L'exclusion exige le même item, un prix fixe actif, une date de fin explicitement nulle et aucune preuve contradictoire. Réponse manquante, autre item, statut inconnu, endTime absent/illisible, redirection ou countdown contradictoire restent bloquants. `OUT_OF_SCOPE` n'est ni `ENDED` ni `SOLD`.

Tests d'abord : deux échecs reproduits avant correction, puis 12 tests ciblés PASS ; suite V4 1 007 tests PASS, deux ignorés ; compilation et `git diff --check` PASS. La différence effective/legacy reste une inclusion, jamais une égalité forcée.

## Auction : observation sans événement navigateur et validation suivante

Le premier correctif `a2aefbba67a82608d991a8070edb8a795bfa62e0` ne suffisait pas quand le détail était rendu sans événement de réponse observable : le run [34776219069](https://github.com/Champaagnepaapi/gcc-auction-watcher/actions/runs/34776219069) gardait neuf `UNKNOWN` malgré zéro legacy manquant.

`39fcf5a51f1961f9598d3cd3c3e4633992a257bc` ajoute alors un GET public de preuve item, uniquement pour `UNKNOWN` sans réponse item déjà observée. Une seule lecture par item, au plus 20 par comparaison, timeout 10 secondes, aucune redirection ; une réponse déjà observée, même HTTP 403, interdit ce fallback. Le même gate item/statut/date s'applique. Aucun achat ni interrogation d'une API privée.

Tests d'abord : deux échecs reproduits, puis 16 tests de comparaison PASS. Auction [34811825366](https://github.com/Champaagnepaapi/gcc-auction-watcher/actions/runs/34811825366) SUCCESS : 16 effectifs / 13 legacy, zéro manquant, zéro inconnu. Auction [34812934319](https://github.com/Champaagnepaapi/gcc-auction-watcher/actions/runs/34812934319), head `29f448a7441e82267fc9d84c2b0f9a52168e77cb`, SUCCESS : 48 effectifs / 46 legacy, zéro manquant, zéro inconnu, 79 états `RESOLVED`. Les neuf anciens items ne sont pas dans cet échantillon : leur passage runtime à `OUT_OF_SCOPE` est couvert par les tests réels aux frontières HTTP/browser, pas revendiqué comme observé dans ces deux derniers lives.

## Dernier défaut corrigé : indisponibilité TCGdex et caches négatifs

Une preuve de nom source pouvait échouer sur HTTP 403, timeout ou budget nul et laisser un `NO_MATCH` définitif. Le premier appel corrigé devenait `ERROR`, mais le deuxième pouvait redevenir `NO_MATCH` à cause du cache négatif de `v4_tcgdex_unique_coordinate_fallback`.

Le commit `29f448a7441e82267fc9d84c2b0f9a52168e77cb` distingue absence propre et indisponibilité dans `v4_tcgdex_source_pinned_finish`, puis protège les recoveries generalized-coordinate, unique-coordinate et l'enveloppe Global source-alias. Une absence de preuve reste bloquante pour l'identité ; une erreur réessayable ne devient plus une absence définitive. Les preuves contradictoires et `AMBIGUOUS` restent bloquantes.

Exemple de régression reproduite avec le vrai assemblage runner : Charmeleon SV2a-169 japonais + source HTTP 403 → auparavant `NO_MATCH` ; désormais `ERROR / TCGDEX_SOURCE_PROOF_UNAVAILABLE`, y compris au deuxième appel sans nouvelle requête. Au run suivant, après réinitialisation et réponse source valide, la même identité devient `EXACT`. Une source réellement absente ne bénéficie pas de cette promotion.

Les quatre scénarios HTTP 403, 403 caché, timeout et budget nul passent avec mocks uniquement à la frontière source/HTTP. Le snapshot avant/après discovery/valuation lit les compteurs existants, sans requête ni écriture de cache. Aucun plafond n'est augmenté. Les 632 tests Global (4 DOM ignorés localement), 1 011 tests V4 (2 ignorés) et 51 tests multimarket passent ; compilation et diff-check PASS. Les quatre tests DOM utilisent Chromium dans le job CI live.

Le Charmander SV2a-168 GCC était `NO_MATCH` dans des runs antérieurs et redevient `EXACT` dans le run `34811825409`, sans modification du resolver entre ces deux versions (seul Auction avait changé). Le défaut de cache est reproduit ; il ne prouve pas rétrospectivement que cette fluctuation précise venait du budget plutôt que de la réponse fournisseur. Ne pas inventer cette causalité.

## Données externes nécessaires à une décision économique

Les barèmes publics prouvent des composantes de coût ; ils ne prouvent pas automatiquement la route de paiement, le financement, la taxe, le pays ou l'expédition d'un acheteur particulier. Les minimums de frais ne sont pas des coûts all-in. Aucun checkout n'a été ouvert pour obtenir une estimation.

| Marketplace | Données à fournir ou à rendre accessibles pour lever le blocage économique |
|---|---|
| Fanatics | Route de paiement et fiscalité/vault applicables ; [carte/Apple Pay à 2,9 %](https://support.fanaticscollect.com/en_us/payment-methods-Bkinm0X6lg) ne signifie pas frais universellement nuls. Sur les annonces sans langue explicite, preuve propre à la carte ; valorisation indépendante compatible avec sa microvariante. |
| COMC | Mode buy-and-ship / buy-and-store, origine des Store Credits et taxe applicable, handling et livraison. [Crédits et taxe](https://comc.zendesk.com/hc/en-us/articles/360058313873-Does-COMC-Store-Credit-cost-anything-to-purchase-Why-am-I-being-charged-sales-tax), [modes de livraison](https://comc.zendesk.com/hc/en-us/articles/4410671400987-Simplified-Shipping-Mode-vs-Advanced-Reselling-Mode). Les libellés de set incomplets ne suffisent pas à inventer une coordonnée TCGdex. |
| Magi | Paiement, livraison/route autorisée et éventuels services : [frais acheteur 3 % et anshin conditionnel](https://magi.camp/guides/262). Certaines cartes Classic du catalogue commercial reviewé n'ont pas de projection TCGdex prouvée. Une autre source catalogue primaire exacte serait nécessaire avant leur promotion canonique. |
| Cardova | Financement/paiement applicable et, pour Auction, rang et minimum de premium ; [fixed](https://www.cardova.co.jp/en/about/trade), [auction](https://www.cardova.co.jp/en/about/auction), [barème](https://www.cardova.co.jp/images/footer/en/fee_schedule.pdf). La preuve de pagination doit rester liée à sa lane ; aucune fin de stock n'est inventée. |
| Mercari | Champs item compatibles et complets, notamment matériau/langue/numéro/set ; route acheteur et livraison autorisées. [Frais par paiement](https://help.jp.mercari.com/guide/articles/65/). Une caractéristique vendeur ambiguë reste bloquante, même quand son extraction DOM fonctionne. |
| SNKRDUNK | Langue explicite de la carte, quantité individuelle et offre item compatible ; route de livraison prise en charge et coût final. Le site public fonctionne et ne doit pas être déclaré « app-only ». [Frais internationaux](https://snkrdunk-faqs-en.relationfaq.jp/pages/166), [destinations](https://snkrdunk-faqs-en.relationfaq.jp/pages/199), [restrictions de réexpédition](https://snkrdunk-faqs-en.relationfaq.jp/pages/1156). Ni inscription ni contournement d'une destination non autorisée n'ont été tentés. |

PriceCharting a répondu HTTP 403 dans les derniers lives analysés : indisponibilité provider, pas vrai `NO_MATCH`. Le gate strict reste nécessaire même si le 403 masque actuellement les anciens faux `MATCHED`. Un accès autorisé non bloqué serait nécessaire ; aucun bypass n'est prévu. PokeTrace Free ne remplace pas des ventes gradées inaccessibles par des prix raw. PPT reste utilisable uniquement sur une identité canonique strictement compatible et une preuve suffisamment forte.

## Protections et limites

- SOLD récents exacts prioritaires ; anciennes ventes exactes seulement avec leur traitement temporel ; asks compatibles et snapshots ≤5 minutes gardent leur rôle propre ; enchère active signal faible.
- ASK, catalogue, disparition, `ENDED`, `WAITING_FOR_PAYMENT` et `OUT_OF_SCOPE` ne constituent jamais SOLD.
- Aucun marketplace n'a autorité sur sa propre fair value. Les agrégats indépendants restent des agrégats, les guides restent des guides, jamais des transactions item-level inventées.
- Aucune langue supposée à partir du pays, du site ou du nom ; aucune microvariante effacée pour augmenter la couverture.
- Pagination partielle conservée comme telle ; échantillonnage et plafonds explicités. Une nouvelle page sans preuve de fin n'établit pas l'exhaustivité.
- Aucun achat, bid, checkout, paiement ou notification de test ; aucun WAF contourné ; aucun secret stocké. PR #8/V5 et Robot KB/Neon séparés et non modifiés. Aucun merge.

## Historique exact des commits de cette mission

Les 32 commits ci-dessous sont déjà poussés sur #268. Les essais de navigation supersédés restent traçables ; ne pas installer une seconde fois leurs wrappers. Les tests ont précédé les corrections ; les échecs intermédiaires et leurs correctifs de fixtures ne sont pas présentés comme des validations vertes.

| SHA exact | Changement |
|---|---|
| `1f3d96b3eed2ff651cce5098d1396af0812599d9` | fix(v4): bind Cardova completeness and make Fanatics installers acyclic |
| `6967ad880fe43c5a91dc820294067e663434a1b8` | test(v4): bootstrap runtime subprocess without inherited PYTHONPATH |
| `ff8587c49e169c1b311cfa687ac4962f622dcfb3` | fix(v4): require strict identity before PriceCharting and PPT valuation |
| `9f490051497ae6343674da1072b28d0a43afd4a5` | fix(v4): share evaluation turns across marketplaces and expose pipeline stages |
| `ac30b7625bd88ea710233fa013de4be8c81e5ac9` | diag(v4): expose bounded selected identity and public item evidence |
| `eb92baa9c608d25ed79d35732806aac1b11345bd` | fix(v4): reject contradictory provider sets variants and detail coordinates |
| `36b49d944a20de951fb2c84300de1aaec304d654` | fix(v4): keep unproven pagination partial and await public product content |
| `c10be34bdef33062c0c4a8d54737fb20ef2f1dfb` | fix(v4): require proven catalog names in shared coordinate recovery |
| `f3a8acfb4799a273a99734b70d249a63a09db38e` | test(v4): align legacy recovery fixtures with proven source names |
| `4553153f650671f9c1b7924006177a09f7ee2bfa` | fix(v4): await item-bound Cardova inventory before changing pages |
| `97c6b494b2f51d3000bfbc46639c98ef8926e35a` | fix(v4): recover only source-proven same-card multilingual names |
| `9a8f8c90a92c5d5d33786a311c73355c7a32722f` | fix(v4): enforce Unicode provider names and proven SV8a set labels |
| `7f20afc0e3a27071cee9cd5ac7e59f1f18b50821` | fix(v4): recognize item-bound listing envelopes and expose bounded content diagnostics |
| `acace11c4a61460b6f5f832d87eb4f5b02216406` | fix(v4): distinguish PokeTrace plan restrictions from absent price data |
| `d19fb1491d9e19298dce0eae5c83ba5edc4a3352` | fix(v4): follow the public Fanatics next-page control within collection bounds |
| `a2d4b0852664c4646a0af8dc3f5425de005fab37` | fix(v4): retain Cardova material axes and validate provider series labels |
| `fb88a0bcfddf9b8c7287300f86a68eb3146499fb` | fix(v4): allow a Free access ceiling without assuming provider plan expiration |
| `8b24427041cda585c2c04af301698b5d4c231159` | fix(v4): discover COMC identities directly from public inventory rows |
| `1e18eb04814ecc3a1ecaee9ca807a9c6d5e8ab60` | fix(v4): observe and follow uniquely labeled Fanatics pagination outside main |
| `183aa01b9934df1a627b14e55df2083184686001` | fix(v4): require proven Cardova payment charges in the public runtime |
| `dec1ff63386040a141d000297817e76f4a38ea9b` | feat(v4): connect public Japan inventory to strict Global gates |
| `f82dd9d8e0ba7c2d9b55fee5837abb91ff3320a2` | fix(v4): follow the labeled public Fanatics navigation anchor |
| `43e37e4c35d5f9bb86d7e3a0bb90d18104f000c0` | fix(v4): preserve inline COMC sets and separate material name suffixes |
| `12e6bf21f42b9c392171a19bd9a7321a80ae5d9c` | fix(v4): keep Fanatics payment charges unproven in every collector |
| `68bb937468edd4657be8fd538cf48fff7a300718` | fix(v4): never infer Magi pagination completeness from detail capacity |
| `7dea977a61a4ac5b4b5517e050fd123adb7f729c` | fix(v4): follow duplicate Fanatics navigation only for one proven destination |
| `168eb58009160b65e6fb8052739ce8f6cca2315c` | fix(v4): read item-scoped Mercari metadata and current SNKRDUNK offer links |
| `0dd0b02ced528960c526d40d1ad19d0d8be5c1f7` | test(v4): declare UTF-8 in real Mercari DOM fixtures |
| `bb519bd279f25bee485e2b46d94e6cb7a9d79b0e` | fix(v4): link Cardova fixed offers using the public card route |
| `a2aefbba67a82608d991a8070edb8a795bfa62e0` | fix(v4): exclude proven fixed-price items from auction timer comparison |
| `39fcf5a51f1961f9598d3cd3c3e4633992a257bc` | fix(v4): read bounded public item proof when auction detail has no response event |
| `29f448a7441e82267fc9d84c2b0f9a52168e77cb` | fix(v4): keep unavailable source proofs out of negative identity caches |


## Fichiers runtime/tests/workflows modifiés depuis le début de la mission

Le diff multi-market porte sur 55 fichiers avant ce closeout documentaire. Aucun fichier V5 ou Robot KB/Neon dans ce diff.

```text
.github/workflows/v4-cardova-public-validation.yml
.github/workflows/v4-global-market-offline-validation.yml
compare_auction_discovery.py
tests/test_compare_auction_terminal_state.py
tests/test_v4_tcgdex_generalized_coordinate_recovery.py
tests/test_v4_tcgdex_japanese_set_aliases.py
tests/test_v4_tcgdex_name_filtered_coordinate_recovery.py
tests/test_v4_tcgdex_run1054_set_aliases.py
tests/test_v4_tcgdex_source_pinned_outage_fallback.py
tests/test_v4_tcgdex_source_pinned_set_reconciliation.py
tests/test_v4_tcgdex_unique_coordinate_fallback.py
tests_global/test_v4_comc_native_discovery.py
tests_global/test_v4_fanatics_collection_completeness.py
tests_global/test_v4_global_economic_confirmation.py
tests_global/test_v4_global_marketplace_cardova_exhaustive_capture.py
tests_global/test_v4_global_marketplace_fanatics_runtime_contract.py
tests_global/test_v4_global_marketplace_notify.py
tests_global/test_v4_global_marketplace_queue.py
tests_global/test_v4_japan_public_inventory.py
tests_global/test_v4_market_cardova.py
tests_global/test_v4_marketplace_pipeline_report.py
tests_global/test_v4_marketplace_public_probe.py
tests_global/test_v4_mercari_dom_contract.py
tests_global/test_v4_provider_runtime_boundaries.py
tests_global/test_v4_valuation_identity_runtime.py
v4_canonical_multimarket.py
v4_cardova_public_inventory.py
v4_global_cardova_public_install.py
v4_global_fanatics_native_identity.py
v4_global_marketplace_cardova_exhaustive_capture.py
v4_global_marketplace_discovery.py
v4_global_marketplace_fanatics_cross_locale.py
v4_global_marketplace_fanatics_language_proof.py
v4_global_marketplace_fanatics_native_v2.py
v4_global_marketplace_fanatics_native_v3.py
v4_global_marketplace_fanatics_provider_language.py
v4_global_marketplace_hardening.py
v4_global_marketplace_japan_public.py
v4_global_marketplace_magi_native_identity.py
v4_global_marketplace_notify.py
v4_global_marketplace_pricecharting_public_recovery.py
v4_global_marketplace_public_probe.py
v4_global_marketplace_queue.py
v4_global_marketplace_scan.py
v4_global_marketplace_tcgdex_source_alias_recovery.py
v4_global_ppt_confirmation.py
v4_global_provider_exact_bridge.py
v4_market_cardova.py
v4_pricecharting_identity.py
v4_pricecharting_valuation.py
v4_tcgdex_generalized_coordinate_recovery.py
v4_tcgdex_japanese_set_registry.py
v4_tcgdex_source_pinned_finish.py
v4_tcgdex_source_pinned_set_reconciliation.py
v4_tcgdex_unique_coordinate_fallback.py
```

## Validation finale et portée de clôture

- Runtime : `29f448a7441e82267fc9d84c2b0f9a52168e77cb` ; Global [34812934273](https://github.com/Champaagnepaapi/gcc-auction-watcher/actions/runs/34812934273) SUCCESS, offline + Chromium réel + bootstrap live + safety contract + absence de mutation.
- Auction [34812934319](https://github.com/Champaagnepaapi/gcc-auction-watcher/actions/runs/34812934319) SUCCESS : 1 011 tests, 2 ignorés ; 48 effectifs / 46 legacy, zéro manquant, zéro timer inconnu ; compile/YAML/diff-check PASS.
- Cardova [34812934329](https://github.com/Champaagnepaapi/gcc-auction-watcher/actions/runs/34812934329) SUCCESS : 62 raw / 27 scope / 19 parsés, 6 pages observées, pagination non prouvée conservée `false`.
- Local déjà validé avant le push runtime : 632 tests Global, 4 tests DOM ignorés localement puis exécutés dans Chromium en CI ; 1 011 V4, 2 ignorés ; 51 multimarket. Aucun rerun local identique effectué uniquement pour cette documentation.
- Les workflows PR sont automatiques. Aucun dispatch manuel, aucun merge, aucun achat/bid/checkout/paiement, aucune notification envoyée pendant les validations. Les jobs Robot KB locaux automatiques ont tourné normalement ; aucun code Robot KB, service local utilisateur ou base Neon n'a été modifié.
- `main` reste `b43dec6084f341b2b52301a4f0542d6f616cf1e2` ; PR #8 reste OPEN/DRAFT/NON MERGED à `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f`. Le présent classement concerne le candidat #268, pas un déploiement production.

Cette passe se clôt sur le classement et les blockers documentés. V4 ne doit pas être annoncée opérationnelle sur les sept marchés. Ne pas merger pour masquer ces limites ; la prochaine action utile est d'obtenir les preuves externes/conditions acheteur manquantes, puis de revalider les providers concernés sans relâcher les gates.
