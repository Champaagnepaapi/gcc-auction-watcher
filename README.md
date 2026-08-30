# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/Git/GitHub live reste l'autorité. Les détails historiques, supersessions et inventaires exhaustifs sont dans `docs/`.

## État canonique — 30 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production canonique          : main @ 1a4b18e98937769bb6924a79aca7dcd36729d25a
V4 auction priority/cap          : #188 MERGED / 52deb7f50e194b04552800bfe328df5be9e1d3a2
PSA/eBay runtime breakers        : #189 MERGED / a4db237cfea1bc916cc6ebbd2b137f754f93afc5
eBay completed-item shadow       : #191 MERGED / main actuel
Robot KB durable                 : PostgreSQL local Mac ACTIF
Robot KB runtime P3              : 1d06fe33b6fc640657255e15a8d17251aa02b6ce
Cardova paid SOLD local          : #199 OPEN / DRAFT / live Mac PROUVÉ / NON MERGED
V4_USE Robot KB                  : false
Neon                             : writers automatiques OFF / rollback manuel seulement
V5 expérimentale                 : PR #8 OPEN / DRAFT / NON MERGED
V5 head                          : bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Toujours re-vérifier le HEAD `main`, les PRs et les workflows live avant une action importante. Un commit docs-only peut suivre le dernier SHA runtime ; distinguer les deux dans le handoff.

---

# Principes non négociables

- **V4 sur `main` = production canonique.**
- **PR #8 / V5 ne doit jamais être mergée dans `main` sans autorisation explicite utilisateur.**
- Pokémon **cartes individuelles uniquement** ; sealed/lots hors scope.
- Aucun achat, bid, offer, checkout, paiement ou grading payant automatique.
- Aucun secret, token, cookie, session ou mot de passe dans repo/logs/chat.
- Identité incertaine, contradictoire ou microvariante non prouvée = fail-closed / revue manuelle.
- Aucun fuzzy, substring, token overlap, traduction supposée ou Levenshtein comme preuve exacte.
- ASK, enchère live et disparition d'annonce ne deviennent jamais des ventes.
- Une vraie vente finale peut être conservée dans Robot KB avec identité `unresolved`, mais **ne devient jamais un comparable exact ni une preuve V4** tant que l'identité commerciale n'est pas prouvée.

## Hiérarchie des preuves prix

1. ventes **SOLD exactes et récentes** ;
2. ventes SOLD exactes anciennes, ajustées temporellement si défendable ;
3. asks fixes compatibles, explicitement étiquetés **ASK** ;
4. snapshot d'enchère observé à `≤5 min` si aucun SOLD n'est disponible ;
5. enchère en cours = signal faible.

---

# V4 — production canonique

## Main Scanner

```text
Cron-job.org ~toutes les 10 min
  -> workflow_dispatch
  -> .github/workflows/watcher.yml
  -> run_watcher_multimarket.py
```

## Fast Lane

```text
Cron-job.org toutes les 3 min
  -> .github/workflows/v4-final-auction-check.yml
  -> recheck ciblé des auctions déjà armées à ≤5 min
```

Ne jamais ajouter de cron GitHub parallèle à ces lanes.

## #188 — priorité enchères + cap

Le cap historique de 120 analyses/run pouvait différer une grande partie des enchères lors des vagues denses. #188 est en production :

```text
priorité 1                       enchères ≤5 min
priorité 2                       enchères ≤12 min
priorité 3                       reste des enchères ≤60 min
cap analyse                      360/run
```

Aucune règle d'identité ou d'économie n'a été relâchée.

## #189 — breakers PSA/eBay

- PSA APR : circuit ouvert pour le run sur HTTP 403/429 explicite ;
- eBay : circuit ouvert après 2 hard timeouts sans résultat utile ;
- un échec transitoire/provider ne devient jamais un clean no-match.

## #191 — eBay completed-item shadow

Provider eBay/RapidAPI ajouté en **shadow uniquement**. Les completed candidates restent :

```text
item_level_sold                 false
genuine_sale_evidence           false
exact_identity_eligible         false
final_price_semantics_proven    false
V4 economic use                 false
```

Ne jamais traiter ce provider comme un vrai item-level SOLD sans preuve supplémentaire.

---

# Global Multi-Vault — production marketplace-first

Surface marketplace canonique :

```text
GCC / Fanatics / COMC / magi / Cardova
        ↓
inventaire courant
        ↓
identité commerciale exacte
        ↓
TCGdex exact + microvariante déterministe
        ↓
GCC SOLD exact si disponible
        ↓
PPT + PokeTrace graded aggregate
        ↓
décision économique
        ↓
notification seulement si gate complet
```

- disparition != SOLD ;
- `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` seulement pour l'actionnable ;
- `ACTIVE_AUCTION` non actionnable ;
- PPT/PokeTrace/eBay = même famille corrélée `EBAY_GRADED_AGGREGATE` ;
- aucun achat/bid/checkout.

Scale/cadence :

```text
batch Global                     50 listings/run
PPT HTTP                         35 max/run
PPT credits                      180 max/run
PPT daily floor                  15000
PokeTrace                        60 requests max/run
Global cadence                   20 min (`1,21,41`)
marketplace inner timeout        17 min
scan job timeout                 25 min
```

PRs structurantes : #139, #145/#146, #147/#148, #151, #156, #169, #179.

---

# TCGdex / identité

La lignée #119→#135 reste l'autorité de récupération exacte : coordinate, padding collector, set/localId, unicité catalogue et fallback source-pinné immuable.

`variants_detailed` (#154) peut prouver après identité exacte :

- normal / holo / reverse ;
- First Edition / Unlimited / Shadowless ;
- Poké Ball / Master Ball / Cosmos / Galaxy / Cracked Ice ;
- langue exacte.

Axes inconnus, multiples, malformés ou contradictoires restent bloquants.

**Pas de treadmill d'aliases carte-par-carte.** Toute récupération nouvelle doit être une classe déterministe répétée et prouvée.

---

# Magi — identité native japonaise

#174 + #177 + #178 sont en production.

```text
baseline #174                    31/96 EXACT
recovery total                   36 max/run
broad/nonpriority #178           28 max/run
strict reserve                   8
TCGDEX_BUDGET_EXHAUSTED          supprimé dans validation #178
```

Les classes sans preuve déterministe suffisante restent volontairement bloquées. Ne pas ajouter de fallback name-only.

---

# Robot KB — PostgreSQL local Mac ACTIF

Robot KB reste séparé de la décision commerciale V4/Global. **`V4_USE=false`** tant qu'une activation économique KB-first n'est pas explicitement décidée et suffisamment prouvée.

## Contrat

- observations append-only, datées, immuables ;
- payload brut + provenance ;
- priorité aux ventes finales `SOLD` prouvées ;
- fixed : baseline puis changements utiles ;
- auctions : SOLD final prioritaire ; snapshot `≤5 min` seulement fallback identifié ;
- disparition/ask/live auction ne devient jamais vente ;
- `WAITING_FOR_PAYMENT` n'est jamais un SOLD ;
- objectif : courbes 30j/90j/1an/multi-années, liquidité, tendance, calibration.

## Stockage local

```text
database                         robot_pokemon_kb
host                             127.0.0.1
runtime P3                       1d06fe33b6fc640657255e15a8d17251aa02b6ce
schema                           [1,2]
fixed + auctions                 LaunchAgent :32
SOLD fresh/backfill              LaunchAgent :17/:47
backup                           quotidien 03:10
Neon writers                     OFF
```

La migration Neon → Mac a été vérifiée à 1,087,015 lignes et 35 tables avec marker `MIGRATION_VERIFIED`.

## #180 — multisource local

#180 est mergée et les LaunchAgents ont été installés sur le Mac.

- Fanatics / COMC / Magi / Cardova publics : baseline puis changements matériels ;
- PokeTrace : US/EU, Pokémon EN/JP, single cards, courant + historique ;
- PokemonPriceTracker : EN/JP, historique 180 jours, eBay gradé agrégé + CardMarket/TCGplayer ;
- clés uniquement dans Trousseau macOS ;
- `SOLD_AGGREGATED` reste agrégé, jamais item-level SOLD ;
- `cardmarket_unsold` reste ASK agrégé.

---

# Cardova paid/completed SOLD — #199 DRAFT

PR #199 est **OPEN / DRAFT / NON MERGED**. Elle ne doit pas être mergée sans décision explicite.

## Preuve provider-level

Le public Past Auctions permet de qualifier une vente finale paid/completed uniquement avec :

```text
bid_payment_status = 5
finished = 1
canceled_at = null
re_listed = 0
re_listing_count = 0
currency = JPY prouvée
final winning bid positif
```

Premier harvest physique : **20/24** lignes satisfaisaient ce gate.

Pour ces ventes :

- `sale_occurred_at = auction_end_at_utc` ;
- final winning bid stocké comme `HAMMER_PRICE` JPY ;
- aucun payment-completion timestamp fabriqué ;
- aucun all-in / buyer premium fabriqué.

## Identité

TCGdex présente un trou pratique sur certaines anciennes promos JP (`XY-P`, `BW-P`, `L-P`). Aucun alias manuel n'a été ajouté.

Fallback déterministe testé via **le site officiel Pokémon Japon** :

```text
promos JP structurées            7
macro identité exacte            7/7
microvariante exacte             0/7
holo corroboré                   1/7
```

Les attributs Cardova `Holo`, `Holo Shiny`, `FA`, `SR` restent des claims provider tant que leur axe matériel n'est pas indépendamment prouvé.

PSA ne fournit pas de fallback utilisable actuellement :

- cert HTML : 403 ;
- API officielle `GetByCertNumber` : 403 `Access to this API is limited to approved customers.` ;
- aucun bypass anti-bot/WAF.

## P3 dry-run + vrai commit local

Dry-run mémoire :

```text
prepared                         20/20
stored                           20/20
unresolved                       20/20
canonical links                  0
HAMMER_PRICE JPY                 20
replay duplicates                20
```

Le premier essai durable a échoué car `source_system code=cardova` existait déjà avec d'autres métadonnées. Le batch atomique a rollback intégralement.

Correctif : réutiliser les métadonnées `source_system cardova` existantes **sans mutation**.

Vrai commit local validé :

```text
code head                        42a2941a51d1674a2c49feab9b35ecf4ee380e67
committed                        true
SALE_TRANSACTION stored          20
unresolved identities            20
exact identities linked          0
canonical links                  0
HAMMER_PRICE JPY                 20
source_system reused             true
source_system mutated            false
error                            null
```

Le writer durable est fail-closed :

- `--commit` explicite obligatoire ;
- PostgreSQL uniquement ;
- host uniquement `localhost`, `127.0.0.1` ou `::1` ;
- DB exactement `robot_pokemon_kb` ;
- remote/cloud/Neon refusé ;
- batch entier dans une transaction externe avec postconditions avant commit ;
- aucune identité canonique fabriquée ;
- `V4_USE=false`.

Validation : Robot KB run `33302300695` SUCCESS ; suite P3, tests Cardova, compile/YAML/diff-check PASS. Les tests V4 complets passent également sur ce head.

**Important : la capacité prouvée est pour l'instant un one-shot manuel. La collecte récurrente Cardova SOLD n'est pas encore activée.**

---

# V5 — EXPÉRIMENTALE

```text
PR      #8 OPEN / DRAFT / NON MERGED
branch  agent/v5-poketrace-cardmarket-market-data
head    bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

TCGdex reste le resolver normal V5 ; PokeTrace sert au marché/prix après identité.

**Ne jamais merger PR #8 dans `main` sans autorisation explicite.**

---

# Gouvernance avant changement important

1. lire entièrement ce README ;
2. lire `.agents/rules/gcc-project-governance.md` ;
3. lire `AGENTS.md` s'il existe ;
4. lire capability ledger + inventaires pertinents ;
5. vérifier worktree/branch/HEAD/status/remotes/PRs/workflows live ;
6. chercher une capacité existante avant de réimplémenter ;
7. branche/PR dédiée pour changement non trivial ;
8. SHA précis ;
9. tests ciblés + suite pertinente ;
10. compile/YAML/`git diff --check` ;
11. live read-only lorsque pertinent ;
12. aucune transaction commerciale/secret ;
13. merge seulement avec autorisation requise ;
14. mettre à jour README + capability ledger après une phase importante.

Documents de reprise :

- `docs/project-current-phase.md`
- `docs/project-capability-ledger.md`
- `docs/project-open-pr-inventory.md`
- `docs/project-branch-inventory.md`
- `docs/project-workflow-inventory.md`
- `docs/project-issue-inventory.md`
- `docs/project-repository-snapshot.md`
- `.agents/rules/gcc-project-governance.md`

---

# Prochaine direction canonique

```text
Cardova SOLD / Robot KB
  -> one-shot paid/completed SOLD prouvé et 20 ventes stockées durablement
  -> prochaine étape : collecteur Cardova SOLD local récurrent
  -> même gate paid/completed strict
  -> append-only + idempotent
  -> identité unresolved autorisée au stockage
  -> lien canonique seulement après preuve exacte ultérieure
  -> conserver fallback Pokémon Japon officiel pour promos JP
  -> V4_USE=false

V4
  -> #188/#189/#191 sont en production
  -> surveiller séparément la cohérence discovery GCC ENDING_SOON
  -> ne pas toucher aux règles d'identité pendant les enchères actives

V5
  -> PR #8 reste expérimentale/draft/non mergée
  -> aucun merge sans autorisation explicite

Neon
  -> rollback manuel uniquement
```

Aucun achat, bid, offer, checkout ou paiement automatique.
