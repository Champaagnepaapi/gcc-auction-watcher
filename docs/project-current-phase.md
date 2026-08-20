# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **20 août 2026** après le merge #148.

## Autorité

```text
V4 production                  main
Dernier merge runtime          ea9a69b375434031c935de8d25fcc12acd1a1c93 (#148)
Global discovery               marketplace-first
Global notification workflow   marketplace-first
V5                             PR #8 / draft / non mergée
Robot KB / Neon                séparé
```

Toujours re-vérifier le HEAD GitHub live ; des commits docs-only peuvent suivre le SHA runtime.

## Phase Global #147 → #148

Le Global est passé de seed-first à **marketplace-first**.

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

### Bootstrap / incrémental

- bootstrap : tout l'inventaire découvert est mis en file et peut déjà produire une décote ;
- ensuite : nouvelles annonces + changements économiques + retryables ;
- annonce inchangée déjà traitée : pas de retraitement inutile ;
- disparition != SOLD.

### Gate économique

- `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` seulement ;
- `ACTIVE_AUCTION` non actionnable ;
- all-in prouvé ;
- identité TCGdex exacte ;
- externe gradé exact >=3 ventes ;
- PPT/PokeTrace/eBay = une seule famille corrélée ;
- conflit GCC/externe matériel bloque ;
- avec GCC : fair confirmé = `min(GCC, externe)` ;
- sans GCC fair : `EXTERNAL_ONLY` possible avec externe exact/fort ;
- seuil : 30 %.

ASK, auction live et disparition ne deviennent jamais SOLD.

## Correctif GCC type d'annonce

Régression marketplace-first découverte en live puis corrigée avant merge #147 : `sellingTypeGroup` n'est pas toujours renvoyé dans chaque row GCC. Le scanner propage maintenant explicitement le type de requête `FIXED_PRICE/AUCTION` au parser.

Une auction sans champ type ne peut plus tomber en `FIXED_ASK`. Tests dédiés pour auction active et snapshot `≤5 min`.

## Validation #147

```text
head                    2e65631416d0b39947de47ed4df3d37a4a87cbdc
merge                   5a1b0f050098b560e812a4dc6e64a9f8d40a8897
run                     32397363626 SUCCESS
Global                  201/201 PASS
V4                       51/51 PASS
GCC exact               1172
Fanatics exact          1
COMC exact              11
magi exact              0
inventory               1184
selected/pending        10 / 1174
```

## Validation #148 / cutover production

Le workflow existant `.github/workflows/v4-global-notify.yml` a été conservé comme **unique cron Global** et pointe maintenant sur `v4_global_marketplace_notify_resilient.py`.

```text
head                    9ff96e9cd9124944e50bb55e990289f5fd07492f
merge                   ea9a69b375434031c935de8d25fcc12acd1a1c93
run                     32398465774 SUCCESS
validate job            96520726453 SUCCESS
live read-only job      96520818899 SUCCESS
Global                  202/202 PASS
V4                       51/51 PASS
compile/YAML/diff       PASS
inventory               1184
selected/pending        10 / 1174
TCGdex exact            5
PPT                     1 match / 6 HTTP / 28 credits
PokeTrace               4 matches / 6 requests
market conflicts        4 blocked
would_notify            0
transactions            false
```

Activation #146 reste inchangée : marker versionné / repo var true ; repo var false = kill switch ; manual dispatch toujours dry-run ; `NTFY_TOPIC` absent = fail-closed.

## Preuve encore attendue

Le code/cutover est mergé. Il reste à **observer explicitement le premier vrai run `schedule` post-#148 sur `main`** pour clôturer la preuve live production du nouveau runtime. Ne pas revendiquer cette preuve sans run ID/logs.

## Cardova

`AUTH_SESSION_INPUT_REQUIRED` reste fail-closed. Aucun cookie/token/session ne doit être stocké dans le repo.

## Prochaine direction

1. Observer le premier schedule post-#148.
2. Laisser le bootstrap drainer le backlog marketplace-first par batches de 10.
3. Mesurer débit/coût/backlog avant d'augmenter ce cap.
4. Si anomalie : `vars.GLOBAL_NOTIFY_ENABLED=false` coupe la lane.
5. V4 cœur production continue normalement et reste séparé de Global.

## Invariants

- PR #8 non mergée sans autorisation explicite ;
- aucun fuzzy comme preuve exacte ;
- ASK/auction/disparition != SOLD ;
- RAW != valeur slab ;
- aucun achat, bid, checkout ou paiement automatique ;
- Robot KB/Neon séparé.