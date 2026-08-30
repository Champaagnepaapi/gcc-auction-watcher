# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **30 août 2026** après validation live de la lane Cardova paid/completed SOLD dans Robot KB local.

## Autorité

```text
V4 production                  main @ 1a4b18e98937769bb6924a79aca7dcd36729d25a
V4 auction priority/cap        #188 MERGED / 52deb7f50e194b04552800bfe328df5be9e1d3a2
PSA/eBay runtime breakers      #189 MERGED / a4db237cfea1bc916cc6ebbd2b137f754f93afc5
eBay completed shadow          #191 MERGED / main actuel
Robot KB storage               PostgreSQL local Mac ACTIF
Robot KB runtime P3            1d06fe33b6fc640657255e15a8d17251aa02b6ce
Cardova paid SOLD              #199 OPEN / DRAFT / NON MERGED
Cardova validated code head    42a2941a51d1674a2c49feab9b35ecf4ee380e67
V4_USE                         false
V5                             PR #8 OPEN / DRAFT / NON MERGED
```

Le code/Git/GitHub live reste prioritaire sur ce document. PR #8 ne doit jamais être mergée sans autorisation explicite.

## Cardova paid/completed SOLD — preuve live

La page publique Cardova Past Auctions et son JSON généré par la page permettent de prouver un SOLD provider-level uniquement avec le gate strict :

```text
bid_payment_status = 5
finished = 1
canceled_at = null
re_listed = 0
re_listing_count = 0
currency = JPY
final winning bid > 0
```

Le premier harvest Mac a donné **20/24** ventes qui satisfont ce gate. Les 4 autres sont restées bloquées proprement.

Sémantique stockée :

- `SALE_TRANSACTION` P3 ;
- `sale_occurred_at = auction_end_at_utc` ;
- prix = `HAMMER_PRICE` JPY ;
- aucun timestamp de paiement n'est fabriqué ;
- aucun all-in/buyer premium n'est fabriqué ;
- `genuine_sale_evidence=true` seulement après le gate paid/completed ci-dessus.

## Identité Cardova

TCGdex ne couvre pas correctement plusieurs anciennes promos japonaises sous leurs coordonnées imprimées Cardova (`XY-P`, `BW-P`, `L-P`). Aucun alias carte-par-carte n'a été ajouté.

Fallback déterministe testé : site officiel Pokémon Japon.

```text
promos JP structurées testées          7
identité macro officielle exacte       7/7
microvariante totalement exacte        0/7
holo indépendamment corroboré          1/7
```

Les attributs Cardova `Holo`, `Holo Shiny`, `FA`, `SR` restent des claims provider ; `FA`, `SR` ou `Shiny` ne sont jamais promus en microvariante exacte sans corroboration indépendante suffisante.

PSA n'est pas un fallback disponible actuellement :

- page cert HTML : 403 ;
- API publique officielle `GetByCertNumber` : HTTP 403 avec `Access to this API is limited to approved customers.` ;
- aucun contournement WAF/anti-bot ;
- accès PSA API laissé en attente d'un éventuel entitlement approuvé.

## Dry-run P3 puis écriture locale réelle

Dry-run mémoire :

```text
selected                         20
prepared SALE_TRANSACTION        20
stored in memory                 20
unresolved identity              20
canonical links                  0
HAMMER_PRICE JPY                 20
replay duplicates                20
sales after replay               20
```

Le premier essai durable a rencontré `source system 'cardova' already differs`. Le batch atomique a correctement rollback : aucune écriture partielle.

Le writer a ensuite été corrigé pour **réutiliser les métadonnées `source_system cardova` déjà présentes sans les modifier**.

Écriture réelle validée sur PostgreSQL local `robot_pokemon_kb` :

```text
committed                        true
selected                         20
prepared                         20
SALE_TRANSACTION stored          20
unresolved identities retained   20
exact identities linked          0
canonical card links             0
HAMMER_PRICE JPY                 20
source_system reused             true
source_system mutated            false
error                            null
```

Le writer refuse les DB distantes/cloud : PostgreSQL loopback uniquement, DB exactement `robot_pokemon_kb`, `--commit` explicite requis, batch atomique avec postconditions avant commit.

## Validation #199

À `42a2941a51d1674a2c49feab9b35ecf4ee380e67` :

```text
Robot KB local PostgreSQL validation   run 33302300695 SUCCESS
P3 regression                           PASS
Cardova focused tests                   PASS
compile/YAML/diff-check                 PASS
V4 complete tests                       PASS
V4 live comparison                      encore séparé du chemin Cardova au dernier check
```

#199 reste **OPEN / DRAFT / NON MERGED**. Aucun merge n'est autorisé implicitement par la réussite du live local.

## Ce qui est maintenant prouvé / non prouvé

**Prouvé :**

- Cardova peut fournir des ventes finales paid/completed provider-level ;
- le final winning bid en JPY peut être conservé comme `HAMMER_PRICE` ;
- une vente P3 peut être stockée durablement même si l'identité canonique/microvariante reste unresolved ;
- le replay est idempotent ;
- aucune identité n'a besoin d'être fabriquée pour conserver l'historique économique.

**Non prouvé / volontairement bloqué :**

- microvariante exacte de ces 20 ventes ;
- all-in payé par l'acheteur ;
- timestamp exact de completion du paiement ;
- usage économique V4 ;
- collecte Cardova SOLD récurrente installée/planifiée.

## Prochaine phase

1. Transformer le one-shot validé en **collecteur Cardova SOLD local récurrent**, append-only et idempotent, avec même gate paid/completed.
2. Faire tourner ce collecteur sur beaucoup de cartes différentes pour construire l'historique Robot KB ; identité unresolved autorisée, lien canonique seulement après preuve exacte ultérieure.
3. Conserver la récupération Pokémon Japon officielle pour les promos JP structurées, sans aliases manuels.
4. Garder `V4_USE=false` ; aucune donnée Cardova unresolved ne doit entrer dans le gate économique V4.
5. Garder #199 DRAFT jusqu'à décision explicite de merge.
6. Garder PR #8 V5 isolée et non mergée.

Aucun achat, bid, offer, checkout ou paiement automatique.
