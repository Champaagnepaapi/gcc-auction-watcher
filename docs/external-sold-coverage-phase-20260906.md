# External SOLD Coverage — phase de reprise — 2026-09-06

## Objectif

Après #255, V4 n'utilise plus l'historique GCC comme autorité de fair value. Le principal gap devient donc la **couverture de preuves externes fortes**, en priorité des ventes item-level SOLD exactes et récentes.

Cette phase ne baisse aucun gate et ne branche pas Robot KB sur V4 : `V4_USE=false` reste obligatoire.

## Gate de promotion SOLD

Une observation ne peut devenir un comparable SOLD exact / `SALE_TRANSACTION` que si toutes les dimensions nécessaires sont prouvées indépendamment :

```text
sale finality              PROVEN
final price semantics      PROVEN
currency                   PROVEN
card identity              EXACT
language                   EXACT
 grader + grade             EXACT
commercial microvariant    EXACT / compatible
provenance                 immutable + dated
```

Une seule dimension `UNKNOWN`, `AMBIGUOUS`, `UNAVAILABLE` ou contradictoire bloque la promotion.

## Matrice de couverture actuelle

| Source | Finalité vente | Prix final | Devise | Identité / microvariante | Statut actuel | Prochaine action sûre |
|---|---|---|---|---|---|---|
| eBay V4 public SOLD | Oui lorsque le parser canonique retourne un comparable exact | Oui sur résultat accepté | Oui sur résultat accepté | Gates V4 stricts | **PROD_V4**, meilleure source immédiate mais disponibilité variable | Observer les erreurs réelles post-#254 ; ne pas augmenter les caps ni contourner anti-bot |
| eBay RapidAPI Robot KB shadow | Non prouvée par le provider seul | Best Offer/finalité parfois ambiguës | Provider-dependent | Candidats stricts mais preuve finale séparée requise | **SHADOW / non-SOLD** | Réutiliser #192/#193/#195/#196 seulement avec corroboration indépendante exacte |
| Fanatics Sales History (#197) | `paymentStatus=PAID` + `isComplete=true` prouvés nécessaires | `purchasePrice` item-level exposé | **UNPROVEN** dans le contrat validé | Resolver Fanatics v3 + TCGdex/detailed variants disponible | **PENDING EVIDENCE** | Porter read-only sur current main ; rechercher uniquement une devise ISO explicite, sinon rester bloqué |
| COMC (#198) | Non prouvée anonymement | Non prouvé item-level | Non prouvée | N/A | **BLOCKED / HTTP 403** en anonymous headless | Aucun bypass ; ne pas traiter `Sold Out`/chart comme vente |
| Cardova (#199→#210) | Stricte : paid/completed/final auction guards | HAMMER_PRICE JPY | JPY prouvée | Exact identity/microvariant stack pour cohort validé | **ROBOT_KB/P3 READY PATH**, durable séparé | Conserver #210 gardé ; aucun write durable sans autorisation explicite |
| PriceCharting V5 | Guide/aggregate, pas item-level SOLD | Guide values | Selon API | Mapping expérimental | **V5_ONLY / diagnostic** | Ne jamais substituer aux SOLD exacts récents ; PR #8 reste non mergée |
| Fixed asks compatibles | N/A | ASK | prouvée selon source | identité exacte requise | **preuve rang 3** | Conserver l'étiquette ASK ; jamais SOLD |
| Auction snapshot ≤5 min | Vente finale non prouvée | bid observé | prouvée selon source | identité exacte requise | **fallback rang 4** | Seulement si aucun SOLD ; conserver `snapshot` explicite |

## Reuse audit

### eBay

Autorités déjà production : #137, #175, #189, #238/#239, #241, #242, #250, #251, #252, #253, #254. Ne pas réimplémenter un scraper parallèle. #226/#228/#233 sont superseded ; #234 est validation-only ; #248 est un ancien diagnostic pré-#250.

### Fanatics

#197 contient déjà les primitives read-only nécessaires :
- schema probe public anonyme ;
- filtre `PAID + isComplete=true` ;
- filtre cartes Pokémon individuelles PSA 8/8.5/9/10 ;
- parsing exact du timestamp PST/PDT ;
- réutilisation du resolver `v4_global_marketplace_fanatics_native_v3` ;
- TCGdex exact + `variants_detailed` ;
- capture pending lorsque la preuve d'identité/currency n'est pas complète ;
- probe currency qui refuse d'inférer USD depuis un simple `$`.

Le bon prochain changement est un **port propre current-main read-only** de ces capacités, pas une nouvelle implémentation.

### Cardova

Le stack #199/#204/#205/#206/#208/#209/#210 a déjà fermé un chemin strict jusqu'au write durable gardé. Ne pas utiliser cette phase comme autorisation d'exécuter #210.

## Premier Main Scanner post-#255

Run naturel exact : `34037313029` / run #3936 / `main@9d3bb1b84d22c1534c24d7c58c5897ecce4b817f` / **SUCCESS**.

Preuve utile :

```text
fixed discovery                      3259 / 33 pages / COMPLETE
auction rows / timers                100 / 100
auction scope                        COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
external deterministic candidates    9
external usable                      0 / 9
PokeTrace                            0 STRONG / 9 WEAK
PSA APR                              HTTP 403 -> breaker fail-closed
eBay                                 attempted 16 / sufficient 0 / insufficient 11 / unavailable 5 / errors 5
final opportunities                  0
```

#254 est live-proven sur son chemin pathologique : body timeout (~2500 ms) puis #251 `body_text_content` timeout (~700 ms) ont été suivis de **4 lectures structurées bornées** `inner_text(timeout=600)` au lieu d'un `all_inner_texts()` non borné. Les workers concernés ont rendu/preservé leur résultat en ~7.6–7.9 s, sans nouveau hard-timeout 30 s du salvage #253.

#255 est live-proven pour le **fail-closed sans preuve externe forte** : les labels historiques `GCC_ONLY` peuvent encore apparaître dans la télémétrie/arbitrage, mais ils ne créent plus de fair value/opportunité. Ce run n'a rencontré aucune preuve externe STRONG ; il ne constitue donc pas une preuve live positive du chemin `EXTERNAL_RESCUE`, lequel reste couvert par tests.

## Plan d'exécution

1. Closeout documentation #253/#254/#255 avec ce run exact.
2. Porter #197 sur une branche current-main distincte, read-only et Robot KB-only.
3. Valider tests ciblés + suite Robot KB + V4 regression + compile/YAML/diff-check.
4. Live probe Fanatics seulement si le code reste public/anonyme/read-only ; aucune écriture durable.
5. Mesurer : rows PAID+complete, exact identity/microvariant, currency explicitly proven, blockers.
6. Tant que currency n'est pas prouvée : `robot_kb_sale_ready=false`, aucune `SALE_TRANSACTION`, aucun V4 economic use.
7. Réévaluer ensuite la prochaine source selon le gap observé, pas selon un cap à augmenter.

## Interdits

- aucun achat, bid, offer, checkout ou paiement ;
- aucun bypass WAF/403 ;
- aucune promotion ASK/live auction/disappearance en SOLD ;
- aucune écriture durable Cardova implicite ;
- aucune fusion V5/#8 ;
- aucun branchement Robot KB -> V4 pendant cette phase.
