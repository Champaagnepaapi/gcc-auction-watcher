# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **30 août 2026** après activation et premier run réel du collecteur Cardova paid/completed SOLD local.

## Autorité

```text
V4 production                    main @ 1a4b18e98937769bb6924a79aca7dcd36729d25a
V4 auction priority/cap          #188 MERGED / 52deb7f50e194b04552800bfe328df5be9e1d3a2
PSA/eBay breakers                #189 MERGED / a4db237cfea1bc916cc6ebbd2b137f754f93afc5
eBay completed shadow            #191 MERGED
Robot KB                         PostgreSQL local Mac ACTIF
Robot KB P3                      1d06fe33b6fc640657255e15a8d17251aa02b6ce
Cardova #199                     OPEN / DRAFT / NON MERGED
Cardova activation head          31378bd04e44c60fa1259605b67d2aabc4a89129
Cardova runtime pin              a2f1878186a8850d5a4c4763518a10ecfd16f2fc
Cardova SOLD durable total       90
Cardova rotation cursor          page 9
V4_USE                           false
V5                               PR #8 OPEN / DRAFT / NON MERGED
```

Le code/Git/GitHub live reste prioritaire. PR #8 ne doit jamais être mergée sans autorisation explicite.

## Cardova paid/completed SOLD

Gate inchangé : `bid_payment_status=5`, `finished=1`, non annulé, non relisté, JPY prouvée, final winning bid positif.

Sémantique : `SALE_TRANSACTION`, `sale_occurred_at = auction_end_at_utc`, `HAMMER_PRICE` JPY. Aucun timestamp de paiement, all-in ou buyer premium fabriqué.

Identité : unresolved autorisée au stockage ; 0 lien canonique tant que microvariante/identité commerciale exacte non prouvée. Les claims provider `Holo`, `Holo Shiny`, `FA`, `SR` ne deviennent jamais preuve exacte seuls.

## Historique live accumulé

```text
one-shot initial                 20
recurring pages 1-4              15
recurring pages 5-8              55
TOTAL                            90 SOLD prouvés
canonical links                   0
V4_USE                            false
```

Dernier run pages 5-8 : 122 lignes vues, 55 SOLD préparés/stockés, 55 unresolved, 0 exact identity, cursor 5→9, `committed=true`, `state_advanced=true`, `successful_cycles=2`, `error=null`.

## Collecteur récurrent local

- stratégie front pages + rotation ;
- aucun ordre de tri Cardova supposé ;
- retry readiness borné uniquement quand le GET public n'est pas observé : 5000/6500/8000 ms ;
- lock séparé `cardova-sold` ;
- PostgreSQL loopback `robot_pokemon_kb` uniquement ;
- LaunchAgent `com.robotpokemon.kb.cardova-sold` ;
- cadence 02:23 / 08:23 / 14:23 / 20:23 ;
- runtime archivage/pin `a2f1878186a8850d5a4c4763518a10ecfd16f2fc` ;
- aucun secret dans plist ; credential PostgreSQL lu depuis le Trousseau au runtime.

Le LaunchAgent est installé/configuré. Le runner post-install est prouvé live ; le premier déclenchement à une heure planifiée reste à observer séparément.

## Validation

Head `31378bd04e44c60fa1259605b67d2aabc4a89129` : Robot KB local PostgreSQL CI SUCCESS, suite P3 PASS, tests Cardova PASS, scripts bash/python compile PASS, YAML PASS, diff-check PASS, tests V4 complets PASS. Les lives V4 restent indépendants de cette lane.

## Prochaine phase

1. Observer un premier déclenchement réellement planifié du LaunchAgent Cardova.
2. Laisser la rotation avancer jusqu'à boundary afin d'accumuler beaucoup de cartes différentes.
3. Résoudre les identités/microvariantes ultérieurement avec preuves déterministes ; ne jamais forcer les unresolved.
4. Commencer ensuite les vues analytiques Robot KB 30j/90j/1an/liquidité/tendance sur les ventes réellement liées à une identité exacte.
5. Garder `V4_USE=false` et #199 DRAFT jusqu'à décision explicite.
6. Garder PR #8 V5 isolée/non mergée.

Aucun achat, bid, offer, checkout ou paiement automatique.
