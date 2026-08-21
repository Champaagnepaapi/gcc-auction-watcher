# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **21 août 2026** pendant la préparation Robot KB #157.

## Autorité

```text
V4 production                  runtime #154 / c3e3da39b79eb71cfdfc864bb865c4a4e7154e0c
main HEAD docs                 2738be454fe0323e7f1cf8d66309fa5bbff6964c
Global discovery               marketplace-first
Global notification workflow   marketplace-first / cadence 10 min
Global schedule registry       issue #150 / PROUVÉ LIVE
TCGdex microvariantes          variants_detailed / #154
Global scale expérimental      PR #156 OPEN / séparée
Robot KB storage               PR #157 PREPARED_LOCAL_MAC / NEON_CUTOVER_PENDING
V5                             PR #8 / draft / non mergée
```

Toujours re-vérifier le HEAD GitHub live ; des commits docs-only peuvent suivre le SHA runtime.

## Robot KB — phase active #157

Le quota Neon est saturé. La migration vise PostgreSQL local sur le Mac mini tout en conservant exactement le contrat Robot KB append-only/SOLD strict.

Préparation :

```text
runtime réutilisé       P3 @ 1d06fe33b6fc640657255e15a8d17251aa02b6ce
PostgreSQL local        127.0.0.1 / robot_pokemon_kb
fixed + auction         LaunchAgent :32
SOLD fresh/backfill     LaunchAgent :17 / :47
backup                  03:10, 7 dumps complets locaux
migration               pg_dump Neon -> restore -> fingerprints source/local
activation locale       uniquement après MIGRATION_VERIFIED
```

**Neon reste actif pendant #157.** Le cutover cloud sera une PR séparée après migration et health-check réels sur le Mac. Ne pas démarrer une base locale vide et ne pas supprimer Neon avant vérification.

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
kill switch   vars.GLOBAL_NOTIFY_ENABLED=false
```

PR #156 expérimente séparément le scale Global ; ne pas confondre son état avec la production tant qu'elle n'est pas mergée.

## Registre #150 / #151

Chaque vrai `schedule` Global poste des métadonnées agrégées minimales dans **issue #150**. Première preuve post-#151 : run `32411433425`, schedule, activation true, success, 0 notification, transactions false.

La cadence #153 est prouvée par le run `32443663511` sur `e79e939c...`, success, activation true, inventory 1196, selected 10, pending 1137, 0 notification, transactions false.

## TCGdex detailed variants #154

`variants_detailed` est consommé **après** identité TCGdex exacte pour prouver finish, édition/shadow et special foils supportés. Plusieurs variantes, champ inconnu/malformed ou contradiction restent bloquants. Le source-pinned japonais reste prioritaire ; `pricing` / `thirdParty` TCGdex ne devient jamais fair value slab.

Validation #154 : run `32444255909` SUCCESS, **221/221 Global + 51/51 V4 multimarket**, full V4 validation SUCCESS, live read-only SUCCESS, artifact `9433579221`, transactions false.

## Cardova

`AUTH_SESSION_INPUT_REQUIRED` reste fail-closed. Aucun cookie/token/session ne doit être stocké dans le repo.

## Prochaine direction

1. Finir CI #157 et merger la préparation locale si verte.
2. Sur le Mac : pull main puis lancer `Installer Robot KB Local.command`.
3. Obtenir `MIGRATION_VERIFIED` + health-check PostgreSQL local.
4. Créer/valider le cutover qui retire les trois writers Neon.
5. Seulement après cela, abandonner Neon.
6. Garder #156 Global séparée de cette migration.

## Invariants

- PR #8 non mergée sans autorisation explicite ;
- aucun fuzzy comme preuve exacte ;
- ASK/auction/disparition != SOLD ;
- RAW != valeur slab ;
- aucun achat, bid, checkout ou paiement automatique ;
- Robot KB séparé de V4/V5 ;
- Neon non coupé avant migration locale vérifiée.