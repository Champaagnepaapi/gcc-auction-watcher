# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **6 septembre 2026** après les merges production #253, #254 et #255 et le premier Main Scanner exact post-#255. Le code/Git/GitHub live reste l'autorité ; re-vérifier `main` avant toute action importante.

## Autorité

```text
V4 production branch                 main
V4 live GitHub HEAD                  dfc548021c561479cc8758e2949d2c4629388d9d
V4 runtime tree baseline             9d3bb1b84d22c1534c24d7c58c5897ecce4b817f / #255
#255 validated head                  e886c649eea8633d39585aabca8fff0b58be4324
#255 CI                              34036063564 / 34036063610 / 34036063594 SUCCESS
#254 production merge                00e5502fb15c9a89d67a55b70cd566099911bcdb
#254 validated head                  fbb7041f9fc44c338b102ec7325a6d6316f1e529
#254 validation                      34031695933 attempt 2 SUCCESS / 920 PASS / 2 skipped
#253 production merge                23e8e9904072d986e24d2a8fbccaa87568851f69
Fast Lane exact post-#255            34037049703 SUCCESS
First Main Scanner exact post-#255   34037313029 / #3936 / SUCCESS
V4 run registry                      issue #235 ACTIVE
V5                                   PR #8 OPEN / DRAFT / NON MERGED
Robot KB durable                     PostgreSQL local Mac / V4_USE=false
Neon                                 writers automatiques OFF / recovery manuel
```

`main` a avancé après #255 par deux commits placeholder/revert jusqu'à `dfc548...`, mais GitHub compare `9d3bb1... → dfc548...` avec **0 fichier modifié**. Le contenu runtime reste donc identique au tree de #255.

## #254 — eBay salvage borné : live-proven

Le premier Main Scanner post-#255 `34037313029` a rencontré le chemin pathologique réel :

```text
body_inner_text                   ~2500 ms timeout
body_text_content                 ~700 ms timeout/error
items_item_text                   4 probes bornés / ~600 ms max chacun
worker result                     préservé vers ~7.6–7.9 s
new 30 s salvage hard-timeout     non observé
```

#254 remplace donc bien l'ancien `all_inner_texts()` non borné du salvage #253 par des lectures same-DOM strictement bornées. Aucun nouveau réseau/retry/budget/WAF bypass.

## #255 — external fair-value authority : live fail-closed proven

Run naturel exact :

```text
run                               34037313029 / #3936 / SUCCESS
head                              9d3bb1b84d22c1534c24d7c58c5897ecce4b817f
fixed discovery                   3259 / 33 pages / COMPLETE
auction rows / timers             100 / 100
auction scope                     COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
external deterministic candidates 9
external usable strong            0 / 9
PokeTrace                         0 STRONG / 9 WEAK
PSA APR                           HTTP 403 -> breaker fail-closed
eBay                              16 attempted / 0 sufficient / 11 insufficient / 5 unavailable / 5 errors
final opportunities               0
```

Le label interne `GCC_ONLY` peut encore apparaître dans les compteurs, mais il **ne crée plus de fair value ni d'opportunité**. Sans preuve externe STRONG, le run est resté fail-closed. Le chemin positif `EXTERNAL_RESCUE` n'a pas été rencontré dans ce sample ; sa preuve reste les tests ciblés #255.

Le run suivant `34037829669` a été CANCELLED et ne doit pas être utilisé comme preuve.

## Phase courante : External SOLD Coverage

Le scanner GCC/discovery est désormais suffisamment durci pour que le principal rendement marginal vienne de la **qualité et couverture des preuves marché externes**.

Priorité canonique :

1. SOLD exacts récents item-level ;
2. SOLD exacts anciens ajustés temporellement si défendable ;
3. ASK fixes compatibles ;
4. auction snapshot ≤5 min seulement si aucun SOLD ;
5. active auction = signal faible.

### Reuse audit du 6 septembre

- **eBay V4** : source SOLD immédiate la plus utile ; conserver #137/#175/#189/#238/#239/#241/#242/#250/#251/#252/#253/#254. Les erreurs restantes sont provider/navigation ; ne pas augmenter les caps pour les masquer.
- **eBay RapidAPI Robot KB** : shadow existant. Les rows restent non-SOLD sans preuve indépendante de finalité/prix exacts.
- **Fanatics #197** : `PAID + isComplete=true` prouvé pour cartes individuelles PSA ; `purchasePrice` item-level présent ; devise non prouvée dans le contrat validé. C'est le meilleur port read-only current-main suivant.
- **COMC #198** : anonymous headless HTTP 403 ; aucun bypass.
- **Cardova** : chemin strict de ventes finales prouvées dans le stack Robot KB/P3 ; durable write séparé et explicitement gardé par #210.
- **PriceCharting V5** : guide values, pas item-level SOLD ; ne pas substituer à des ventes exactes.

Matrice détaillée : `docs/external-sold-coverage-phase-20260906.md`.

## Gate de promotion exact SOLD

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

Une seule dimension inconnue/ambiguë bloque `SALE_TRANSACTION` et tout usage économique V4.

## Invariants

- ASK, active auction, disparition et provider outage ne deviennent jamais SOLD ;
- identité incertaine ou microvariante non prouvée reste bloquée ;
- V4 et Robot KB restent séparés (`V4_USE=false`) ;
- aucun durable Cardova write sans autorisation explicite ;
- PR #8 ne doit pas être mergée sans autorisation explicite ;
- aucun achat, bid, checkout ou paiement automatique.

## Prochaine étape technique

1. Finaliser/merger le closeout docs #253/#254/#255 après CI verte.
2. Sur une **branche séparée créée depuis current main**, porter proprement les capacités Fanatics #197, read-only/Robot-KB-only.
3. Revalider focused tests + Robot KB suite + V4 regression + compile/YAML/diff-check.
4. Live Fanatics seulement public/anonyme/read-only ; mesurer `PAID+complete`, identité/microvariante exactes, et surtout présence ou absence d'une devise ISO explicite.
5. Tant que currency n'est pas prouvée : `robot_kb_sale_ready=false`, aucune `SALE_TRANSACTION`, aucun V4 economic use.
6. Réévaluer la source suivante à partir des blockers réellement observés.
