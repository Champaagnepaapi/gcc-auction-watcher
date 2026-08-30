# GCC Auction Watcher

> **Source de reprise technique canonique.** Lire ce fichier avant tout changement important.
>
> Le code/Git/GitHub live reste l'autorité. Les historiques et supersessions détaillés sont dans `docs/`.

## État canonique — 30 août 2026

```text
Repo                              Champaagnepaapi/gcc-auction-watcher
V4 production                     main @ 1a4b18e98937769bb6924a79aca7dcd36729d25a
V4 auction priority/cap           #188 MERGED / 52deb7f50e194b04552800bfe328df5be9e1d3a2
PSA/eBay breakers                 #189 MERGED / a4db237cfea1bc916cc6ebbd2b137f754f93afc5
eBay completed shadow             #191 MERGED / main actuel
Robot KB                          PostgreSQL local Mac ACTIF
Robot KB runtime P3               1d06fe33b6fc640657255e15a8d17251aa02b6ce
Cardova paid SOLD                 #199 OPEN / DRAFT / NON MERGED
Cardova recurring activation      head 31378bd04e44c60fa1259605b67d2aabc4a89129
Cardova recurring runtime pin     a2f1878186a8850d5a4c4763518a10ecfd16f2fc
Cardova proven SOLD stored        90 au total
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

## Identité

TCGdex ne résout pas proprement certaines anciennes promos JP `XY-P/BW-P/L-P`. Aucun alias manuel n'a été ajouté.

Fallback officiel Pokémon Japon : 7/7 macro-identités exactes sur le sous-ensemble promo structuré testé, 0/7 microvariantes totalement exactes, 1/7 holo corroboré. Les claims Cardova `Holo`, `Holo Shiny`, `FA`, `SR` restent provider-level tant qu'ils ne sont pas corroborés.

PSA HTML et API officielle restent bloqués par 403 ; aucun bypass anti-bot/WAF.

## Preuves live locales

```text
one-shot initial                   20 SOLD stockés
recurring pages 1-4               +15 SOLD
recurring pages 5-8               +55 SOLD
TOTAL Cardova SOLD                 90
canonical links                    0
identités unresolved               90
V4_USE                             false
```

Le collecteur récurrent utilise une stratégie **front pages + rotation historique**, sans supposer l'ordre de tri Cardova. Cursor après le dernier live : page 9.

Activation locale :

```text
code/CI head                       31378bd04e44c60fa1259605b67d2aabc4a89129
runtime pin                        a2f1878186a8850d5a4c4763518a10ecfd16f2fc
LaunchAgent                        com.robotpokemon.kb.cardova-sold
cadence                            02:23 / 08:23 / 14:23 / 20:23
readiness retry                    5000 -> 6500 -> 8000 ms
DB                                 loopback robot_pokemon_kb uniquement
```

Le premier runner post-install a terminé `committed=true`, 55 ventes nouvelles, 0 lien canonique, cursor 5→9, `successful_cycles=2`, `error=null`. Le LaunchAgent est installé/configuré ; un déclenchement à son heure planifiée n'a pas encore été observé séparément.

Validation du head 31378bd : Robot KB CI SUCCESS ; tests V4 complets PASS ; compile/YAML/diff-check PASS. Les comparaisons live V4 restent indépendantes de cette lane Robot KB.

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
Cardova / Robot KB
  -> laisser le LaunchAgent récurrent accumuler l'historique
  -> vérifier un premier déclenchement réellement planifié
  -> continuer la rotation historique jusqu'à boundary puis recommencer
  -> résoudre ultérieurement les identités/microvariantes de façon déterministe
  -> V4_USE=false tant que l'identité exacte n'est pas suffisante

Robot KB
  -> privilégier diversité de cartes + ventes finales prouvées
  -> préparer ensuite courbes 30j/90j/1an/multi-années, liquidité et tendance

V4
  -> #188/#189/#191 restent production
  -> traiter séparément toute anomalie GCC ENDING_SOON

V5
  -> PR #8 reste isolée/draft/non mergée
```

Aucun achat, bid, offer, checkout ou paiement automatique.
