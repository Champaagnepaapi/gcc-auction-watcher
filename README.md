# GCC Auction Watcher

> **Source de reprise technique canonique.** Lire ce fichier avant tout changement important.
>
> Le code/Git/GitHub live reste l'autorité. Les historiques et supersessions détaillés sont dans `docs/`.

## État canonique — 30 août 2026

```text
Repo                              Champaagnepaapi/gcc-auction-watcher
V4 production                     main @ b98756c449718845fc1944560fcf61c02586079f
Dernier merge V4                  PR #203 / weekly stability budget
V4 auction priority/cap           #188 MERGED
PSA/eBay breakers                 #189 MERGED
eBay completed shadow             #191 MERGED
Auction safety-net ledger         #201 MERGED
Robot KB                          PostgreSQL local Mac ACTIF
Robot KB runtime P3               1d06fe33b6fc640657255e15a8d17251aa02b6ce
Cardova paid SOLD                 #199 OPEN / DRAFT / NON MERGED
Cardova research head validé      59d006fc7259198f13d957b412bc48e4911c067f
Cardova SALE_TRANSACTION          244 unresolved disponibles
Cardova macro exact read-only     38
Cardova finish exact              38
Cardova printing exact            5 No Rarity Symbol
Cardova microvariant exact        0
Cardova canonical links           0
V4_USE Robot KB                   false
Neon                              automatic writers OFF / rollback manuel
V5                                PR #8 OPEN / DRAFT / NON MERGED
V5 head                           bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

Toujours re-vérifier `main`, les PRs, branches et validations live avant action. **PR #8 ne doit jamais être mergée sans autorisation explicite.**

---

# Invariants non négociables

- V4 sur `main` = production canonique.
- Pokémon cartes individuelles uniquement ; sealed/lots hors scope.
- Aucun achat, bid, offer, checkout, paiement ou grading payant automatique.
- Aucun secret, token, cookie, session ou mot de passe dans repo/logs/chat.
- Identité incertaine ou microvariante non prouvée = fail-closed / unresolved.
- Aucun fuzzy, substring, traduction supposée ou Levenshtein comme preuve exacte.
- ASK, enchère active et disparition d'annonce ne deviennent jamais des ventes.
- Une vraie vente finale peut être conservée dans Robot KB avec identité unresolved, mais ne devient jamais comparable exact/V4 tant que l'identité commerciale n'est pas prouvée.

## Hiérarchie des preuves prix

1. SOLD exact récent ;
2. SOLD exact ancien ajusté temporellement si défendable ;
3. fixed ask compatible ;
4. snapshot enchère `≤5 min` si aucun SOLD ;
5. enchère en cours = signal faible.

---

# V4 — production

## Discovery / enchères

Main Scanner : cadence externe ~10 min via `watcher.yml`.
Fast Lane : cadence externe ~3 min via `v4-final-auction-check.yml`.

#188 est en production :

```text
priorité 1                         ≤5 min
priorité 2                         ≤12 min
priorité 3                         reste ≤60 min
cap analyse                        360/run
```

#189 protège le budget provider : PSA APR circuit-breaker sur 403/429 ; eBay breaker après deux hard timeouts sans résultat utile. Les erreurs transitoires ne deviennent jamais des clean no-match.

#191 ajoute eBay completed-item en shadow uniquement : completed candidate ≠ item-level SOLD prouvé.

#201 corrige le ledger safety-net des enchères afin qu'un même item ne reçoive pas des statuts terminaux contradictoires/dupliqués.

#203 porte le budget de stabilisation hebdomadaire borné de 3 à 5 passes, sans relâcher le fail-closed.

---

# Global Multi-Vault

Surface canonique : GCC / Fanatics / COMC / magi / Cardova.

```text
inventaire courant
 -> identité commerciale exacte
 -> TCGdex exact + microvariante déterministe
 -> GCC SOLD exact si disponible
 -> PPT + PokeTrace graded aggregate
 -> arbitrage
 -> notification seulement si gate complet
```

- disparition != SOLD ;
- `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` seulement pour l'actionnable ;
- `ACTIVE_AUCTION` non actionnable ;
- PPT/PokeTrace/eBay aggregate restent une famille corrélée ;
- aucune transaction automatique.

Production : batch 50, cadence Global 20 min, PPT floor 15000, PokeTrace borné. PRs structurantes : #139, #145/#146, #147/#148, #151, #156, #169, #179.

---

# Identité TCGdex / Magi

La lignée #119→#135 reste l'autorité TCGdex : coordinate, set/localId, unicité catalogue, bridges exacts et fallback source-pinné immuable.

`variants_detailed` (#154) peut prouver après macro-identité exacte : normal/holo/reverse, First Edition/Unlimited/Shadowless, Poké Ball/Master Ball/Cosmos/Galaxy/Cracked Ice et langue exacte. Axes inconnus/multiples/contradictoires restent bloquants.

Magi : #174 + #177 + #178 en production ; plafond recovery 36, broad/nonpriority 28, réserve stricte 8. Aucun treadmill d'aliases carte-par-carte.

---

# Robot KB — PostgreSQL local Mac

Robot KB reste séparé de V4/Global. **`V4_USE=false`.**

Contrat : append-only, provenance + payload brut, ventes finales SOLD prouvées prioritaires, fixed baseline/changements utiles, auction final SOLD prioritaire, snapshot ≤5 min fallback seulement.

```text
database                           robot_pokemon_kb
host                               127.0.0.1
runtime P3                         1d06fe33b6fc640657255e15a8d17251aa02b6ce
fixed + auctions                   LaunchAgent :32
GCC SOLD fresh/backfill            LaunchAgent :17/:47
backup                             03:10
multisource public                 toutes les 2 h à :05
PokeTrace/PPT paid                 01:08 / 07:08 / 13:08 / 19:08
Cardova paid SOLD                  02:23 / 08:23 / 14:23 / 20:23
Neon automatic writers             OFF
```

Migration Neon → Mac vérifiée : 1,087,015 lignes, 35 tables, marker `MIGRATION_VERIFIED`.

#180 multisource est mergée et installée. `SOLD_AGGREGATED` reste agrégé ; `cardmarket_unsold` reste ASK agrégé.

---

# Cardova paid/completed SOLD — PR #199 DRAFT

PR #199 reste **OPEN / DRAFT / NON MERGED**.

## Gate provider-level

Une ligne Past Auctions devient une vraie vente provider-level uniquement si :

```text
bid_payment_status = 5
finished = 1
canceled_at = null
re_listed = 0
re_listing_count = 0
currency JPY prouvée
final winning bid > 0
```

Stockage : `SALE_TRANSACTION`, `sale_occurred_at = auction_end_at_utc`, prix `HAMMER_PRICE` JPY. Aucun timestamp de paiement, buyer premium ou all-in n'est fabriqué.

## Identité macro déterministe — live validée

Le snapshot local read-only du 30 août contient **244 `SALE_TRANSACTION` Cardova unresolved disponibles**. Le compose déterministe prouve **38 macro-identités** sans prétendre que la numérotation Cardova a une sémantique globale.

Chaîne de preuve obligatoire par ligne :

```text
set Cardova exact corroboré
+ nom anglais Cardova == nom anglais TCGdex exact
+ valeur numérique cohérente pour cette ligne
+ une seule carte TCGdex pour ce dexId dans le set corroboré
+ source TCGdex Asian immuable @ af33c9ac882e2acfadffaf19e8083aa976d12983
```

Couverture live :

```text
Japanese Basic / PMCG1             17 lignes
neo Gold, Silver... / neo1         10 lignes
Japanese Jungle / PMCG2             6 lignes
Japanese Rocket / PMCG4             5 lignes
TOTAL macro exact                  38
provider numeric semantics global  false
```

Cette preuve est **row-scoped**. Aucun alias global de numérotation Cardova n'est créé.

## Finish — 38/38 exact sur ce sous-ensemble

Le probe de finish compose les macro-identités avec la source TCGdex pinnée :

- finish source unique `normal` ou `holo` => exact ;
- claim Cardova `Holo` compatible + source => corroboré ;
- token opaque/non corroboré => ne devient pas finish par lui-même.

Live : **38/38 finish exact** sur les 38 macros. Cela ne ferme pas les axes edition/special-finish/variant.

## No Rarity Symbol — fallback revu et strictement borné

PSA direct HTML/API/cert reste bloqué par **HTTP 403** depuis le Mac. Aucun bypass, proxy, cookie import ou anti-bot workaround n'est utilisé.

Pour cinq lignes Basic seulement, Cardova expose le token exact `no rarity original print`. Un manifest de preuves PSA publiques déjà revues est borné à ces cinq coordonnées exactes :

```text
Sandshrew  #027
Nidorino   #033
Arcanine   #059
Machop     #066
Gastly     #092
```

Live read-only :

```text
no-rarity candidates               5
reviewed coordinates proven        5
printing exact                     5 = no_rarity_symbol
finish exact                       normal pour les 5
PSA live direct                    5 x HTTP 403
Cardova cert effectivement lu      false
edition exact                      false
No Rarity => First Edition         false
microvariant exact                 0
canonical link candidates          0
blocked                            {}
error                              null
```

La preuve revue ne remplace jamais le cert Cardova et ne généralise jamais à une 6e coordonnée non revue.

## Stockage / activation locale

Le collecteur récurrent reste indépendant de cette recherche d'identité : front pages + rotation historique, state après commit seulement, lock séparé, PostgreSQL loopback, credential Trousseau, aucun secret en plist.

```text
LaunchAgent                        com.robotpokemon.kb.cardova-sold
cadence                            02:23 / 08:23 / 14:23 / 20:23
runtime collector pin              a2f1878186a8850d5a4c4763518a10ecfd16f2fc
research/CI head validé            59d006fc7259198f13d957b412bc48e4911c067f
SALE_TRANSACTION unresolved        244 disponibles au dernier snapshot
canonical links                    0
V4_USE                             false
```

Le cursor de rotation n'a pas été ré-audité dans la phase identity du 30 août ; le dernier handoff collector documentait page 13. Ne pas déduire un cursor courant du nouveau total 244.

## Validation head 59d006f

```text
Robot KB local PostgreSQL          run 33333404769 SUCCESS
V4 Auction Discovery               run 33333404817 SUCCESS
V4 Global Market Offline           run 33333404767 en cours lors du handoff
reviewed No Rarity tests            7/7 PASS
bounded macro tests                 5/5 PASS
legacy macro/finish tests          18/18 PASS
compile/YAML/diff-check            PASS dans Robot KB CI
live Mac read-only                 SUCCESS
```

Le live Mac prouve : `unresolved=244`, `selected=244`, `macro_exact=38`, `finish_exact=38`, `printing_exact=5`, `micro_exact=0`, `links=0`, `blocked={}`, `error=null`.

---

# V5 — EXPÉRIMENTALE

```text
PR      #8 OPEN / DRAFT / NON MERGED
branch  agent/v5-poketrace-cardmarket-market-data
head    bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

Ne jamais merger PR #8 sans autorisation explicite.

---

# Procédure avant changement important

1. lire ce README ;
2. lire `.agents/rules/gcc-project-governance.md` ;
3. lire `AGENTS.md` s'il existe ;
4. lire capability ledger + inventaires pertinents ;
5. vérifier worktree/branch/HEAD/status/remotes/PRs/workflows live ;
6. auditer les capacités existantes avant de réimplémenter ;
7. branche/PR dédiée ;
8. SHA précis ;
9. tests ciblés + suite pertinente ;
10. compile/YAML/`git diff --check` ;
11. live read-only lorsque pertinent ;
12. aucune transaction commerciale/secret ;
13. merge seulement avec autorisation requise ;
14. mettre README + capability ledger à jour après phase importante.

Documents : `docs/project-current-phase.md`, `docs/project-capability-ledger.md`, inventaires PR/branches/workflows/issues/repository, et gouvernance `.agents/rules/gcc-project-governance.md`.

---

# Prochaine direction canonique

```text
Cardova / identité
  -> garder les 38 macros + 38 finishes comme preuves read-only bornées
  -> fermer seulement les axes commerciaux réellement applicables : edition, special_finish, variant
  -> conserver les 5 No Rarity avec printing exact mais edition inconnue
  -> ne créer aucun canonical link tant qu'une microvariante complète n'est pas prouvée
  -> ne plus retry PSA direct tant que le 403 persiste ; aucun bypass

Cardova / collecte
  -> laisser le LaunchAgent accumuler les SALES finales prouvées
  -> poursuivre la rotation historique ; re-auditer le cursor séparément

Robot KB
  -> privilégier diversité de cartes + ventes finales prouvées
  -> préparer ensuite courbes 30j/90j/1an/multi-années, liquidité et tendance sur identités exactes

V4
  -> reste séparée ; V4_USE=false
  -> ne jamais utiliser les 38 macros comme comparables exacts tant que microvariant=0

V5
  -> PR #8 reste isolée/draft/non mergée
```

Aucun achat, bid, offer, checkout ou paiement automatique.
