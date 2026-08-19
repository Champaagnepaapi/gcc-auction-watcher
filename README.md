# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
> Ce README décrit l'état courant. L'historique détaillé reste dans Git/GitHub et dans `docs/project-capability-ledger.md` ; ne pas réintroduire une ancienne implémentation simplement parce qu'elle apparaît dans un vieux commit.

## État canonique — 18 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production / main : a52398685629e4baf4c8ac036851e2ae1a49b037
V5 expérimentale     : PR #8 / agent/v5-poketrace-cardmarket-market-data
Robot KB / Neon      : historique durable séparé de V4/V5
```

### Phase V4 TCGdex / PokeTrace #123 → #135 — TERMINÉE

La séquence de récupération d'identité/market retrieval est maintenant validée en production.

- #123 : récupération des capacités TCGdex déterministes déjà construites, dont le `2 coordonnées sur 3` ;
- #124 : PokeTrace structuré après identité TCGdex (`card_number` + `game`) ;
- #127 : préservation du padding des collector numbers provider (`069/062`, `109/098`, etc.) ;
- #128 : bridges provider déterministes `(Japanese)`, `(Secret)` et préfixe de set exact ;
- #129 : le nom canonique/romanisé reste la recherche JA, le nom localisé TCGdex n'est qu'un alias d'acceptation lié à l'identité exacte ;
- #130 : diagnostic final-gate + correction source-pinnée `Night Wanderer -> SV6a` ;
- #131 : première correction de drift finish TCGdex source-pinnée ;
- #132 : généralisation du finish depuis le catalogue TCGdex immuable ;
- #133 : parser compatible avec les imports TypeScript avec ou sans point-virgule ;
- #134 : première réconciliation d'un conflit de namespace de set stale ;
- #135 : **fallback générique source-pinné** lorsque le REST TCGdex contredit le set exact prouvé par le catalogue.

Pin TCGdex immuable utilisé par cette lignée :

```text
af33c9ac882e2acfadffaf19e8083aa976d12983
```

### Preuve production #135

Run naturel :

```text
run_id    32160680888
commit    a52398685629e4baf4c8ac036851e2ae1a49b037
status    SUCCESS
```

Le runtime a prouvé les corrections source-pinnées suivantes :

```text
Team Rocket's Houndoom     100/098 -> SV10
Team Rocket's Meowth       109/098 -> SV10
Team Rocket's Moltres Ex   112/098 -> SV10
```

Compteurs du run :

```text
TCGdex    31 attempted | 18 exact | 4 no-match | 9 ambiguous | 0 errors
PokeTrace  2 attempted |  1 exact | 0 strong | 1 weak | 1 no-match | 0 ambiguous | 0 errors
final opportunities: 0
```

Crobat `117/098` n'était pas sélectionné dans ce run : **ne pas revendiquer une preuve live spécifique Crobat**. La classe générique de conflit stale `S12 -> SV10` est néanmoins prouvée live sur trois cartes du même set.

Le même run avait encore une couverture externe incomplète (`external pending backlog ~2031`, ETA diagnostique ~204 runs). Donc `0 opportunity` n'est pas présenté comme un verdict économique globalement trustworthy tant que ce backlog n'est pas drainé.

---

# Principes non négociables

- **V4 sur `main` = production canonique.**
- **V5 = expérimentale, PR #8. Ne jamais merger PR #8 dans `main` sans autorisation explicite utilisateur.**
- Pokémon **cartes individuelles uniquement** ; sealed/lots hors scope.
- Aucun achat, bid, checkout, paiement ou grading payant automatique.
- Ne jamais exposer, logger ou commiter une clé API, token, mot de passe ou secret.
- Identité incertaine, contradiction matérielle ou microvariante non prouvée = fail-closed / revue manuelle ; jamais de comparable exact fabriqué.
- Aucun fuzzy, substring, token overlap, traduction supposée ou Levenshtein comme preuve d'identité exacte.
- Un provider peut aider au retrieval ; il ne peut pas fabriquer l'identité du listing.
- Une absence de marché confirmé n'est pas une preuve de mauvaise offre.

## Hiérarchie des preuves prix

1. ventes **SOLD exactes et récentes** ;
2. ventes SOLD exactes anciennes, ajustées temporellement lorsque la méthode est défendable ;
3. asks fixes compatibles, explicitement étiquetés **ASK** ;
4. snapshot d'enchère observé à `≤5 min` si aucun SOLD n'est disponible ;
5. enchère en cours = signal faible.

**Un ask ou une enchère en cours n'est jamais une vente.**

---

# V4 — production canonique

## Scheduler / entrypoints

Main Scanner :

```text
Cron-job.org ~toutes les 10 min
  -> workflow_dispatch
  -> .github/workflows/watcher.yml
  -> run_watcher_multimarket.py
```

Fast Lane :

```text
Cron-job.org toutes les 3 min
  -> .github/workflows/v4-final-auction-check.yml
  -> recheck ciblé des auctions déjà armées à ≤5 min
```

Règles :

- pas de `schedule:` GitHub parallèle pour Main Scanner/Fast Lane ;
- ne pas lancer manuellement ces workflows quand la politique réserve leur cadence au scheduler externe ;
- Fast Lane ne découvre aucune nouvelle carte et ne relance aucun provider externe ;
- Fast Lane réutilise le `max_recommended` déjà calculé ;
- `state.json` reste propriété du Main Scanner ; `final_alerts.json` gère la déduplication finale ;
- aucune transaction automatique.

## Discovery fixed

- API GCC publique `/on-sale-items` ;
- Pokémon cartes individuelles ;
- prix discovery `0–100 €` ;
- discovery non cappée ; les budgets s'appliquent uniquement aux traitements/enrichissements aval ;
- file économique : `NEW -> CHANGED -> NEVER_EVALUATED -> STALE/PENDING` selon les règles courantes ;
- refresh externe adaptatif près du seuil, sans modifier l'économie.

## Discovery auctions

Source primaire :

```text
/on-sale-items
sellingTypeGroup=AUCTION
sortType=ENDING_SOON
status=ON_SALE
  -> endTime individuel
  -> Pokémon + carte + 0–100 € + ≤60 min
```

- horizon déterminé sur l'`endTime` individuel, jamais seulement sur un timer global de vente ;
- safety-net legacy private/weekly conservé ;
- fallback legacy complet si l'ordre/completude API n'est pas prouvé ;
- couverture nominale : `COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS` ;
- le total global GCC `ON_SALE` est un autre scope et ne doit pas servir de faux dénominateur.

---

# V4 — identité TCGdex puis marché PokeTrace

Architecture normale :

```text
GCC listing
  -> TCGdex exact / déterministe
     -> gates langue + set + numéro + microvariantes
     -> si identité exacte : PokeTrace marché/prix
     -> PSA APR / eBay SOLD fallback ou confirmation selon scope
  -> arbitrage économique
```

## Ordre de récupération TCGdex V4

Les fast paths et fallbacks restent déterministes : exact coordinate / aliases revus / exact set+localId / unicité catalogue. Une coordonnée seule ne suffit pas à fabriquer une identité ; les collisions restent `AMBIGUOUS`.

Pour les drifts du provider lui-même, la lignée #130-#135 peut utiliser le catalogue TCGdex au pin immuable `af33c9ac...` pour prouver :

- set/localId exact ;
- import du set exact ;
- variants `normal/holo/reverse` lorsque le REST est stale.

La preuve source :

- n'est appliquée qu'après des préconditions d'identité déterministes ;
- est bornée par timeout/budget/cache process-local ;
- ne peut jamais être déclenchée par PokeTrace ;
- ne corrige pas grader, grade, fair value, seuil ou `max_recommended` ;
- échoue sans relaxation si source absente/malformed/contradictoire.

## PokeTrace

PokeTrace est **market-only après identité TCGdex** dans le chemin V4 courant.

- EN -> `game=pokemon` ;
- JA -> `game=pokemon-japanese` ;
- numéro provider conserve sa surface imprimée/padding ;
- noms/set provider peuvent être acceptés seulement via bridges exacts et bornés ;
- langue, numéro, set, finish/édition et autres dimensions sensibles restent obligatoires ;
- PokeTrace ne transforme jamais un provider candidate en preuve d'identité du listing.

PR #126 (`fix/v4-poketrace-exact-provider-bridges-20260818`) est une ancienne lignée **SUPERSEDED**. Ne pas la merger : sa logique utile a été réintégrée proprement par #127/#128 et les PR suivantes.

## PSA scope économique

```text
PSA 8
PSA 8.5
PSA 9
PSA 10
```

PSA <8 hors scope économique production ; ne jamais synthétiser PSA 9.5.

## Arbitrage marché

Chemins principaux :

- `GCC_ONLY`
- `GCC_EXTERNAL_CONFIRMED`
- `EXTERNAL_RESCUE`
- `EXTERNAL_PENDING`
- `MARKET_CONFLICT_BLOCKED`

Règles :

- GCC fort + externe fort concordant -> confirmation prudente ;
- GCC faible/indisponible + externe fort -> rescue possible si identité exacte ;
- deux marchés forts contradictoires -> blocage ;
- provider indisponible ≠ no-match ;
- budget épuisé -> pending/requeue ;
- Cardmarket/TCGplayer RAW reste contexte RAW et ne devient jamais fair value d'un slab ;
- active asks restent `ASK, PAS UNE VENTE`.

### État opérationnel à surveiller

Le run prod #135 `32160680888` montrait encore :

```text
external-market coverage: INCOMPLETE
external pending backlog: ~2031
estimated backlog runs: ~204
PSA APR: indisponible sur le run
eBay: plusieurs timeouts/indisponibilités
```

La prochaine priorité est **le drainage/diagnostic de ce backlog externe**, pas une nouvelle relaxation d'identité.

---

# Capacités V4 déjà construites — ne pas réimplémenter

Le détail est dans `docs/project-capability-ledger.md`. Principales capacités présentes :

- discovery API auction item-level + safety-net legacy ;
- Fast Lane finale ≤5 min avec `max_recommended` immuable ;
- external-market arbitration GCC/PokeTrace/PSA APR/eBay ;
- smart external priority + queue anti-starvation ;
- exact active eBay ASK context ;
- Structural Edge Hunter V2, informatif sans remplacer les gates économiques ;
- Japan Edge Hunter production séparé, ASK-only et identité exacte ;
- Robot KB durable et backfill SOLD ;
- V5 identity/microvariant stack expérimentale ;
- PPT et Global Multi-Vault en shadow/deferred ;
- anciens cert/OCR/Mislisted Slab travaux conservés historiquement mais lane Mislisted Slab **hard-disabled en production**.

Avant d'écrire un nouveau module important : lire le ledger + inventaires GitHub et chercher si la capacité existe déjà sur `main`, V5, Robot KB ou une branche shadow.

---

# Robot KB / Neon — historique durable séparé

Robot KB n'est pas la décision commerciale V4.

Principes :

- observations append-only, datées, immuables ;
- payload brut + provenance conservés ;
- priorité aux ventes finales **SOLD prouvées** ;
- fixed : baseline puis changements utiles ;
- auctions : final SOLD prioritaire ; snapshot `≤5 min` uniquement comme fallback clairement identifié ;
- jamais transformer disparition/ask/live auction en vente ;
- conserver beaucoup de cartes différentes pour construire plusieurs années d'historique ;
- objectifs analytiques : courbes 30j/90j/1an/multi-années, liquidité, tendance, calibration inter-grader.

Collecte principale :

- SOLD frais lossless avec watermark durable ;
- backfill historique SOLD séparé ;
- fixed hybride : récent + rotation durable + ciblage sous-échantillonné ;
- état/cursor avancé uniquement après ingestion Neon réussie.

Ne pas activer un hard gate `KB-first` tant que la profondeur exacte par identité/grader/grade n'est pas démontrée suffisante.

---

# V5 — EXPÉRIMENTALE / PR #8

```text
PR #8: OPEN / DRAFT / NON MERGED
branch: agent/v5-poketrace-cardmarket-market-data
validated V5 head: bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

**Ne jamais merger PR #8 dans `main` sans autorisation explicite.**

Architecture identité V5 normale :

```text
TCGdex live
  -> exact / deterministic uniqueness
  -> microvariant gates
  -> market providers
```

Emergency uniquement après vraie panne technique TCGdex :

```text
TCGdex technical failure
  -> Robot KB/Neon cached proven TCGdex identity
  -> Pokemon TCG API
  -> PokeTrace emergency-only
  -> fail-closed
```

Panne technique éligible : transport, JSON invalide, HTTP 408/425/429/5xx. `CLEAN_NO_MATCH`, 404 et autres 4xx ne déclenchent pas l'emergency.

PokeTrace emergency a runtime/cache isolé, budget borné et ne prouve jamais les microvariantes sensibles par simple metadata provider.

PR #96 et PR #92 restent V5 shadow/deferred. Aucun merge vers V5/main n'est implicite.

---

# Japan Edge / Global / PPT

## Japan Edge production

Lane séparée pour ASK japonais exacts ; un ASK n'est jamais SOLD. Le contexte peut afficher GCC et marché externe séparément. Identité japonaise PSA10 exacte requise. Aucun achat automatique.

## PPT

PokemonPriceTracker est une source d'agrégats de ventes eBay gradées utile en shadow/price discovery. Ses agrégats sont `SOLD_AGGREGATED`, pas item-level SOLD. PPT et PokeTrace/eBay peuvent appartenir à la même famille corrélée et ne doivent pas être double-comptés comme marchés indépendants.

PR #106/#107 restent draft/shadow.

## Global Multi-Vault

Stack #108/#109/#110/#113/#114/#115 : shadow/deferred. GCC/Cardova/magi/Fanatics/COMC sont comparés via identité commerciale stricte ; les child PRs ne doivent pas être mergées directement dans `main` sans réintégration/revalidation dédiée.

---

# Workflows permanents

Le tree `main` contient **14 workflows YAML** au snapshot du 18 août 2026. Les rôles d'autorité sont documentés dans `docs/project-workflow-inventory.md`.

À retenir :

- Main Scanner et Fast Lane : external `workflow_dispatch`, pas de cron GitHub parallèle ;
- Robot KB SOLD/fixed : collecte séparée ;
- V4 validation : CI + comparaison read-only ;
- V5 lives : manuels/expérimentaux uniquement ;
- ne pas créer de one-shot/redondant si un workflow existant suffit.

---

# Topologie GitHub — snapshot 18 août 2026

Après ouverture de la PR docs #136 :

```text
remote branches: 158
pull requests total: 133
pull requests open: 16
issues hors PR: 3
workflow YAML files on main: 14
main protected: false
```

Inventaires :

- `docs/project-branch-inventory.md`
- `docs/project-open-pr-inventory.md`
- `docs/project-workflow-inventory.md`
- `docs/project-issue-inventory.md`
- `docs/project-repository-snapshot.md`
- `docs/project-current-phase.md`

Ces nombres peuvent changer : re-vérifier GitHub live avant toute suppression/merge/configuration.

---

# Gouvernance avant tout changement important

1. lire entièrement ce README ;
2. lire `.agents/rules/gcc-project-governance.md` ;
3. lire `docs/project-capability-ledger.md` et les inventaires pertinents ;
4. vérifier branche/head/status GitHub réels ;
5. chercher une capacité existante avant de réimplémenter ;
6. branche/PR dédiée ;
7. SHA précis ;
8. tests ciblés + full suite pertinente ;
9. compile/YAML/`git diff --check` ;
10. comparaison live read-only lorsque pertinente ;
11. aucune transaction/secret ;
12. merge uniquement après validation et autorisation requise ;
13. mettre à jour ce README après une phase importante.

Pendant des enchères actives, éviter les changements risqués du cœur V4. Préférer les correctifs isolés, déterministes, fail-closed et mesurés.

## Prochaine direction canonique

La classe TCGdex stale set/finish traitée par #130→#135 est **fermée**. Ne pas continuer un treadmill d'alias carte-par-carte.

Priorité :

```text
laisser V4 drainer la couverture externe
-> mesurer les NO_MATCH/AMBIGUOUS récurrents
-> corriger uniquement une nouvelle classe déterministe prouvée
```

Aucun benchmark vérifié ne prouve un TCGdex `500/500` ; ne pas reprendre cette affirmation sans nouvelle preuve.
