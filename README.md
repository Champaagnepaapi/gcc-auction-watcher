# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
> Ce README décrit l'état courant. L'historique détaillé reste dans Git/GitHub et dans `docs/project-capability-ledger.md` ; ne pas réintroduire une ancienne implémentation simplement parce qu'elle apparaît dans un vieux commit.

## État canonique — 20 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 functional runtime baseline : c012284c423e9526fd2712001fdbce3a5cfafda3
main HEAD                      : toujours re-vérifier GitHub live ; des commits docs-only peuvent suivre le baseline runtime
V5 expérimentale               : PR #8 / agent/v5-poketrace-cardmarket-market-data
Robot KB / Neon                : historique durable séparé de V4/V5
TCGdex source pin              : af33c9ac882e2acfadffaf19e8083aa976d12983
Global notifications candidate : PR #145 / default-off / activation réelle séparée
```

`c012284c...` est le dernier merge **fonctionnel/runtime** actuellement présent sur `main`. Les commits docs-only qui le suivent ne changent pas le comportement V4/Global ; ne jamais confondre leur SHA avec un nouveau runtime déployé.

### Phase Global Multi-Vault #139 → #142 — INTÉGRÉE EN READ-ONLY

- PR #139 a réintégré sur le `main` courant le Global Multi-Vault strict : GCC, Cardova, magi, Fanatics et COMC.
- PR #140 ajoute la **confirmation économique externe** PPT/PokeTrace après identité exacte.
- PR #142 ajoute le bridge générique de nomenclature provider exact, sans fuzzy ni alias carte-par-carte ; elle a été mergée dans #140 avant le merge vers `main`.
- dernier merge fonctionnel/runtime de cette phase : `c012284c423e9526fd2712001fdbce3a5cfafda3`.

Le runtime Global présent sur `main` reste read-only/diagnostic. Il calcule `would_notify`, n'envoie aucune notification et n'effectue aucune transaction.

### Preuve live Global #140/#142

```text
run_id                32344120993
TCGdex exact          5/5
PPT matched           4/5
PokeTrace matched     4/5
would_notify          0
market conflicts      1 blocked
PPT budget            9 HTTP / 37 crédits / daily remaining 19826
PokeTrace requests    6
```

Cas sécurité principal :

```text
Mewtwo 151 183/165 JP PSA10
GCC fair              ~155 EUR
PPT/PokeTrace center  ~103.40 EUR
Fanatics ASK          ~99.10 EUR
GCC/external ratio    1.499
result                MARKET_CONFLICT_BLOCKED
```

L'ASK Fanatics apparemment très décoté par rapport à GCC n'est donc pas promu : le marché externe contredit le fair GCC. **ASK ≠ SOLD.**

Couverture externe observée sur ce panel : Raikou, Entei, Dragonite et Mewtwo ont une coordonnée externe exacte ; Pikachu M-P reste `CLEAN_NO_MATCH`. Ne pas relâcher l'identité pour forcer sa couverture.

### Phase #145 — notifications Global confirmées, DEFAULT-OFF

PR #145 construit une lane de notification séparée au-dessus du moteur économique déjà validé. Elle ne remplace ni le scanner V4 canonique ni le matching #140/#142.

Gate de notification :

```text
exact actionable offer
  + MULTIMARKET_CONFIRMED
  + would_notify=true
  + all_in_eur prouvé
  + external graded >= 3 sales
  -> dedupe/rotation
  -> notification seulement si activation schedule explicitement autorisée
```

Capacités #145 :

- déduplication persistante 14 jours par identité + marché + URL ;
- re-notification seulement après expiration TTL ou baisse de prix `>=5%` ;
- rotation persistante des seeds ;
- état corrompu = fail-closed lorsque la livraison est activée ;
- `workflow_dispatch` reste **toujours dry-run** ;
- workflow permanent `v4-global-notify.yml` avec cron candidat `41 * * * *`, mais job scheduled **skip** tant que `vars.GLOBAL_NOTIFY_ENABLED != 'true'` ;
- aucun achat, bid, checkout ou paiement.

Le premier live de validation notification (`32357750921`) a validé la mécanique/sécurité mais a subi des `ReadTimeout` TCGdex sur 5/5 identités. #145 ajoute donc une résilience **Global-only et transport-only** : max 2 tentatives, timeout 10 s, backoff 0.25 s, uniquement Timeout/ConnectionError/HTTP 502/503/504. Un échec final reste `ERROR`/fail-closed ; aucun 404/no-match n'est transformé et aucune règle d'identité n'est relâchée. Le scanner V4 canonique n'installe pas ce wrapper.

Validation offline du correctif :

```text
head fonctionnel pré-live       3c459ac561013eaf49b5475d7d89222a8b9efdda
V4 Global Market Offline        32359793387  SUCCESS
V4 Global Shadow Dispatcher CI  32359793463  SUCCESS
Global tests                    164/164 PASS
V4 multimarket                   51/51 PASS
py_compile / YAML / diff-check  PASS
```

Live dry-run résilient :

```text
run / job              32359861668 / 96396943369
mode                   READ_ONLY_NOTIFICATION_VALIDATION
TCGdex exact           5/5
PPT matched            4/5
PokeTrace matched      4/5
confirmed_would_notify 0
market conflicts       1 blocked
sent                   0
notifications          false
transactions           false
identity_gate_relaxed  false
artifact               9403172623
artifact digest        sha256:68054acd9468b7f3e1ac5fdcb9720a9bcba38d19e7440dc96bbb59e61b1ad2b0
```

La couverture saine 5/5 TCGdex + 4/5 PPT + 4/5 PokeTrace est donc récupérée sans relâcher l'identité. Les one-shots utilisés pour lancer ces validations ont été supprimés après usage.

Validation finale du head docs/cleanup précédent `0c4a751381191e1c452dd7d63ba8195f3a42f4be` :

```text
V4 Global Market Offline        32360522416  SUCCESS
V4 Global Shadow Dispatcher CI  32360522364  SUCCESS
Global tests                    164/164 PASS
V4 multimarket                   51/51 PASS
py_compile / YAML / diff-check  PASS
```

**Important : merge #145 et activation réelle sont deux décisions distinctes.** `GLOBAL_NOTIFY_ENABLED=true` ne doit jamais être réglé sans autorisation explicite séparée. Tant que le flag reste absent/false, aucune notification scheduled ne part.

### Phase V4 TCGdex / PokeTrace #123 → #135 — TERMINÉE

La récupération d'identité/market retrieval V4 reste l'autorité production : exact coordinate, aliases revus, unicité catalogue, retrieval PokeTrace structuré, bridges provider exacts, finish/set source-pinnés et fallback générique lorsque le REST TCGdex est stale.

Preuve production de cette phase : run `32160680888` sur `a52398685629e4baf4c8ac036851e2ae1a49b037`, SUCCESS. Houndoom `100/098`, Meowth `109/098` et Moltres ex `112/098` ont été récupérés vers `SV10`. Crobat `117/098` n'était pas échantillonné : ne pas revendiquer une preuve live spécifique Crobat.

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
- Fast Lane ne découvre aucune nouvelle carte et ne relance aucun provider externe ;
- Fast Lane réutilise le `max_recommended` déjà calculé ;
- `state.json` reste propriété du Main Scanner ; `final_alerts.json` gère la déduplication finale ;
- aucune transaction automatique.

## Discovery

Fixed : API GCC publique `/on-sale-items`, Pokémon cartes individuelles, discovery non cappée avant budgets aval.

Auctions :

```text
/on-sale-items
sellingTypeGroup=AUCTION
sortType=ENDING_SOON
status=ON_SALE
  -> endTime individuel
  -> Pokémon + carte + ≤60 min
```

Le safety-net legacy reste disponible ; le total GCC global `ON_SALE` n'est pas un faux dénominateur de couverture auction.

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

La preuve source TCGdex pinnée peut corriger un drift du provider uniquement après préconditions déterministes. Elle ne corrige jamais grader, grade, fair value, seuil ou `max_recommended`.

PokeTrace reste **market-only après TCGdex** : EN `game=pokemon`, JA `game=pokemon-japanese`. Numéro, langue, set et dimensions sensibles restent obligatoires.

PR #126 est `SUPERSEDED` par la lignée #127→#135. Ne pas la merger.

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

Règles : provider indisponible ≠ no-match ; budget épuisé -> pending/requeue ; RAW Cardmarket/TCGplayer ne devient jamais fair value d'un slab ; active asks restent ASK.

---

# Global Multi-Vault — support sur main + notification candidate default-off

Pipeline économique :

```text
GCC exact SOLD seeds
  -> identité commerciale exacte
  -> offres GCC / Cardova / magi / Fanatics / COMC
  -> TCGdex exact
  -> PPT + PokeTrace graded aggregate confirmation
  -> décision économique
```

## Gate économique Global

- opportunité actionnable uniquement `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` avec `all_in_eur` prouvé ;
- `ACTIVE_AUCTION` reste signal faible ;
- confirmation externe gradée obligatoire avant `would_notify` ;
- minimum 3 ventes agrégées pour un centre externe utilisable ;
- PPT/PokeTrace/eBay partagent `EBAY_GRADED_AGGREGATE` et ne comptent qu'une fois ;
- conflit matériel au sein de la famille corrélée reste bloquant ;
- ratio GCC/externe >1.25 -> `MARKET_CONFLICT_BLOCKED` ;
- fair confirmé = `min(GCC fair, external fair)` : l'externe ne peut jamais gonfler la valeur ;
- seuil actuel : 30 % de décote.

## Bridge provider exact #142

Le bridge n'accepte que des différences de nomenclature mécaniques bornées après preuve exacte du full collector number, du set/préfixe TCGdex et de la langue : suffixes `V`, `VSTAR`, `VMAX`, `ex`, `GX`, ou forme `Mega <nom> ex`.

`Unlimited` n'est traité comme non matériel que si la carte TCGdex exacte prouve explicitement `firstEdition=false`. Un `externalCatalogId` conflictuel ne peut jamais tomber dans un fallback PPT.

Aucun fuzzy, aucune traduction supposée, aucune identité relâchée.

## Notifications #145

La lane candidate `.github/workflows/v4-global-notify.yml` est **default-off** :

- manual dispatch = dry-run uniquement ;
- schedule horaire = job skip sans `GLOBAL_NOTIFY_ENABLED=true` ;
- dédup 14 jours + reprice >=5 % + rotation ;
- TCGdex transport retry borné Global-only ;
- aucun achat/bid/checkout/paiement.

L'activation réelle reste séparée et non autorisée tant que le flag n'a pas été explicitement approuvé.

---

# Robot KB / Neon — historique durable séparé

Robot KB n'est pas la décision commerciale V4.

- observations append-only, datées, immuables ;
- payload brut + provenance conservés ;
- priorité aux ventes finales **SOLD prouvées** ;
- fixed : baseline puis changements utiles ;
- auctions : final SOLD prioritaire ; snapshot `≤5 min` uniquement comme fallback identifié ;
- jamais transformer disparition/ask/live auction en vente ;
- objectifs : courbes 30j/90j/1an/multi-années, liquidité, tendance, calibration inter-grader.

Ne pas activer un hard gate `KB-first` tant que la profondeur exacte par identité/grader/grade n'est pas démontrée suffisante.

---

# V5 — EXPÉRIMENTALE / PR #8

```text
PR #8: OPEN / DRAFT / NON MERGED
branch: agent/v5-poketrace-cardmarket-market-data
validated V5 head: bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

**Ne jamais merger PR #8 dans `main` sans autorisation explicite.**

Architecture normale : TCGdex exact -> microvariant gates -> market providers. Emergency uniquement après vraie panne technique TCGdex via cache prouvé/TCG API/PokeTrace emergency, toujours fail-closed.

---

# Workflows permanents

Le tree `main` de base contient **15 workflows YAML**. La PR #145 propose un 16e workflow permanent `v4-global-notify.yml`, default-off. Le détail est dans `docs/project-workflow-inventory.md`.

À retenir :

- Main Scanner et Fast Lane : cadence externe, pas de cron GitHub parallèle ;
- Robot KB : collecte séparée ;
- `v4-global-live-shadow.yml` : manuel/read-only ;
- `v4-global-market-offline-validation.yml` : CI Global ;
- `v4-global-notify.yml` : candidate #145, manual dry-run + schedule skip par défaut ;
- les one-shots de validation #142/#145 ont été supprimés ;
- V5 lives : manuels/expérimentaux uniquement.

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

La mécanique #145 est validée en dry-run avec couverture externe saine, mais **merge et activation sont encore séparés**.

```text
V4 production existante
  -> continuer normalement ; cœur V4 non modifié par la résilience Global-only

Global notifications #145
  -> merge seulement sur autorisation explicite
  -> après merge, rester default-off
  -> activation GLOBAL_NOTIFY_ENABLED=true seulement sur autorisation explicite séparée
```

Pikachu M-P reste un no-match externe propre sur le panel historique ; ne pas créer un alias ponctuel sans classe déterministe répétée.

Aucun benchmark vérifié ne prouve un TCGdex `500/500` ; ne pas reprendre cette affirmation sans nouvelle preuve.
