# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **21 août 2026** après le merge #154.

## Autorité

```text
V4 production                  main @ c3e3da39b79eb71cfdfc864bb865c4a4e7154e0c
Global discovery               marketplace-first
Global notification workflow   marketplace-first / cadence 10 min
Global schedule registry       issue #150 / PROUVÉ LIVE
TCGdex microvariantes          variants_detailed / #154
V5                             PR #8 / draft / non mergée
Robot KB / Neon                séparé
```

Toujours re-vérifier le HEAD GitHub live ; des commits docs-only peuvent suivre le SHA runtime.

## Global marketplace-first

```text
GCC / Fanatics / COMC / magi / Cardova
 -> inventaire courant
 -> identité exacte
 -> TCGdex exact + microvariante déterministe
 -> GCC SOLD exact si disponible
 -> PPT + PokeTrace
 -> décision économique
 -> notification si gate complet
```

Bootstrap : tout l'inventaire découvert est mis en file. Ensuite : nouvelles annonces, changements économiques et retryables. Disparition != SOLD.

Gate : `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5`, all-in prouvé, TCGdex exact, externe gradé exact >=3 ventes, décote >=30 %, conflit matériel bloquant. `ACTIVE_AUCTION` non actionnable. PPT/PokeTrace/eBay = une famille corrélée.

## Cadence production #153

Le workflow `.github/workflows/v4-global-notify.yml` reste l'unique cron Global.

```text
schedule      1,11,21,31,41,51 * * * *
manual        toujours dry-run
state         .global-marketplace-state
batch         10 pending/run
kill switch   vars.GLOBAL_NOTIFY_ENABLED=false
```

Aucun second schedule n'a été ajouté et les budgets/run sont inchangés.

## Registre #150 / #151 — preuve réelle obtenue

Chaque vrai `schedule` Global poste des métadonnées agrégées minimales dans **issue #150** : run_id/SHA/activation/outcome, inventory/selected/pending, TCGdex/PPT/PokeTrace, confirmed/sent et flags transaction.

Première preuve post-#151 :

```text
run                     32411433425
trigger                 schedule
commit                  c9539ca521f69b43b3d93e621fb21447a69f3fe7
activation              true
mode                    GLOBAL_MARKETPLACE_NOTIFICATION_ACTIVE
status                  success
selected/pending        10 / 1166
confirmed/sent          0 / 0
identity relaxed        false
transactions            false
```

La cadence #153 est également prouvée par plusieurs vrais schedules. Dernier observé avant merge #154 : run `32443663511` sur `e79e939c...`, success, activation true, inventory 1196, selected 10, pending 1137, 0 notification, transactions false.

## TCGdex detailed variants #154

`variants_detailed` est maintenant consommé **après** identité TCGdex exacte pour prouver les axes commerciaux : finish, édition/shadow et special foils supportés.

Règles :

- source-pinned japonais reste prioritaire ;
- plusieurs variantes compatibles restantes => blocage ;
- champ inconnu/malformed => blocage ;
- contradiction dans une même entrée (`Unlimited + 1st Edition`, `Poké Ball + Master Ball`) => blocage ;
- `pricing` / `thirdParty` TCGdex n'entre jamais dans la fair value slab ;
- aucun fuzzy.

Validation : run `32444255909` SUCCESS, **221/221 Global + 51/51 V4 multimarket**, full V4 validation SUCCESS, live read-only SUCCESS, artifact `9433579221`, transactions false.

Un vrai schedule exécutant spécifiquement le commit #154 n'avait pas encore été observé dans #150 au moment de cette fermeture ; ne pas le revendiquer avant une ligne explicite sur `c3e3da39...` ou un SHA ultérieur contenant #154.

## Cardova

`AUTH_SESSION_INPUT_REQUIRED` reste fail-closed. Aucun cookie/token/session ne doit être stocké dans le repo.

## Prochaine direction

1. Observer le premier schedule #150 contenant #154.
2. Laisser le backlog se drainer à 10 évaluations/run sous cadence 10 min.
3. Mesurer débit/coût/conflits avant scale-up >10/run.
4. Exploiter `variants_detailed` comme preuve lorsque présent, sans fabriquer les microvariantes absentes/ambiguës.
5. En cas d'anomalie Global : `vars.GLOBAL_NOTIFY_ENABLED=false` coupe la lane.

## Invariants

- PR #8 non mergée sans autorisation explicite ;
- aucun fuzzy comme preuve exacte ;
- ASK/auction/disparition != SOLD ;
- RAW != valeur slab ;
- aucun achat, bid, checkout ou paiement automatique ;
- Robot KB/Neon séparé.