# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **20 août 2026** après le merge #151.

## Autorité

```text
V4 production                  main
Dernier merge runtime Global   c9539ca521f69b43b3d93e621fb21447a69f3fe7 (#151)
Global discovery               marketplace-first
Global notification workflow   marketplace-first
Global schedule registry       issue #150
V5                             PR #8 / draft / non mergée
Robot KB / Neon                séparé
```

Toujours re-vérifier le HEAD GitHub live ; des commits docs-only peuvent suivre le SHA runtime.

## Global marketplace-first

```text
GCC / Fanatics / COMC / magi / Cardova
 -> inventaire courant
 -> identité exacte
 -> TCGdex exact
 -> GCC SOLD exact si disponible
 -> PPT + PokeTrace
 -> décision économique
 -> notification si gate complet
```

Bootstrap : tout l'inventaire découvert est mis en file. Ensuite : nouvelles annonces, changements économiques et retryables. Disparition != SOLD.

Gate : `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5`, all-in prouvé, TCGdex exact, externe gradé exact >=3 ventes, décote >=30 %, conflit matériel bloquant. `ACTIVE_AUCTION` non actionnable. PPT/PokeTrace/eBay = une famille corrélée.

Le correctif GCC #147 propage explicitement `FIXED_PRICE/AUCTION` depuis la requête ; une auction sans champ row type ne peut plus devenir `FIXED_ASK`.

## Cutover #148

Le workflow existant `.github/workflows/v4-global-notify.yml` est l'unique cron Global et utilise `v4_global_marketplace_notify_resilient.py`.

```text
schedule      41 * * * *
manual        toujours dry-run
state         .global-marketplace-state
batch         10 pending/run initialement
kill switch   vars.GLOBAL_NOTIFY_ENABLED=false
```

## Registre autonome #150 / PR #151

Le connecteur ChatGPT ne peut pas énumérer directement les runs GitHub Actions `schedule` sans `run_id`. #151 réutilise le pattern du registre V4 issue #1 mais garde les deux lanes séparées.

Chaque vrai `schedule` Global poste dans **issue #150** :

- timestamp, `run_id`, attempt, trigger, SHA ;
- activation + outcome marketplace ;
- inventaire/selected/pending ;
- TCGdex/PPT/PokeTrace ;
- confirmed candidates / notifications sent ;
- flags purchase/bid/checkout/payment.

Aucun log complet, secret, cookie/session ou détail listing-level n'est copié. `workflow_dispatch` n'écrit pas dans #150. Le finalizer est `always()` afin de laisser un run_id/statut même après échec provider lorsque le job peut atteindre cette étape.

Validation #151 :

```text
branch                  ops/v4-global-run-registry-20260820
head                    a424fb62cb5e0553929847d3b973411a8b61a561
merge                   c9539ca521f69b43b3d93e621fb21447a69f3fe7
run                     32410224171 SUCCESS
validate/live jobs      96558656377 / 96558728745 SUCCESS
Global                  203/203 PASS
V4                       51/51 PASS
compile/YAML/diff       PASS
inventory               1186
selected/pending        10 / 1176
TCGdex exact            5
PPT                     1 match / 6 HTTP / 28 credits
PokeTrace               4 matches / 6 requests
market conflicts        4 blocked
would_notify            0
transactions            false
artifact                9421951722
```

## Preuve encore attendue

La mécanique du registre est offline + live read-only validée et mergée. Il reste à observer **le premier commentaire automatique de l'issue #150 produit par un vrai `schedule` sur `main` post-#151**. Ce commentaire donnera le `run_id`, après quoi jobs/logs/artifacts pourront être inspectés sans intervention utilisateur.

## Cardova

`AUTH_SESSION_INPUT_REQUIRED` reste fail-closed. Aucun cookie/token/session ne doit être stocké dans le repo.

## Prochaine direction

1. Lire le prochain commentaire #150 après le prochain cron minute 41.
2. Inspecter automatiquement le run_id et confirmer le vrai mode production marketplace-first.
3. Laisser le backlog se drainer par batches de 10.
4. Mesurer débit/coût/backlog avant scale-up.
5. Si anomalie : `vars.GLOBAL_NOTIFY_ENABLED=false` coupe la lane.

## Invariants

- PR #8 non mergée sans autorisation explicite ;
- aucun fuzzy comme preuve exacte ;
- ASK/auction/disparition != SOLD ;
- RAW != valeur slab ;
- aucun achat, bid, checkout ou paiement automatique ;
- Robot KB/Neon séparé.