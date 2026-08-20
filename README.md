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
```

`c012284c...` est le dernier merge **fonctionnel/runtime** de cette phase. Les merges docs-only qui le suivent sur `main` ne changent pas le comportement V4/Global ; ne jamais confondre leur SHA avec un nouveau runtime déployé.

### Phase Global Multi-Vault #139 → #142 — INTÉGRÉE EN READ-ONLY

- PR #139 a réintégré sur le `main` courant le Global Multi-Vault strict : GCC, Cardova, magi, Fanatics et COMC.
- PR #140 ajoute la **confirmation économique externe** PPT/PokeTrace après identité exacte.
- PR #142 ajoute le bridge générique de nomenclature provider exact, sans fuzzy ni alias carte-par-carte ; elle a été mergée dans #140 avant le merge vers `main`.
- dernier merge fonctionnel/runtime de la phase : `c012284c423e9526fd2712001fdbce3a5cfafda3`.

**Important : cette lane reste read-only / diagnostic.** Elle calcule `would_notify`, mais n'envoie aucune notification et n'est pas schedulée automatiquement. Aucune transaction n'est possible.

### Preuve live finale Global

Run read-only :

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

Couverture externe observée sur ce panel : Raikou, Entei, Dragonite et Mewtwo ont désormais une coordonnée externe exacte ; Pikachu M-P reste `CLEAN_NO_MATCH`. Ne pas relâcher l'identité pour forcer sa couverture.

Validation finale du head #140 `b10adebc1f6866ae4ec37e9ea01eeddd2a240c60` :

```text
V4 Global Market Offline Validation  32351952230  SUCCESS
V4 Global Shadow Dispatcher CI       32351952209  SUCCESS
Global tests                          146/146 PASS
V4 multimarket regressions             51/51 PASS
py_compile / YAML / diff-check        PASS
```

Le one-shot utilisé pour la validation live de #142 a été supprimé avant merge. Le workflow permanent Global reste manuel/read-only.

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

# Global Multi-Vault — support read-only sur main

Pipeline :

```text
GCC exact SOLD seeds
  -> identité commerciale exacte
  -> offres GCC / Cardova / magi / Fanatics / COMC
  -> TCGdex exact
  -> PPT + PokeTrace graded aggregate confirmation
  -> décision read-only
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
- seuil diagnostic actuel : 30 % de décote ;
- `would_notify` est **informatif seulement** sur `main` courant.

## Bridge provider exact #142

Le bridge n'accepte que des différences de nomenclature mécaniques bornées après preuve exacte du full collector number, du set/préfixe TCGdex et de la langue : suffixes `V`, `VSTAR`, `VMAX`, `ex`, `GX`, ou forme `Mega <nom> ex`.

`Unlimited` n'est traité comme non matériel que si la carte TCGdex exacte prouve explicitement `firstEdition=false`. Un `externalCatalogId` conflictuel ne peut jamais tomber dans un fallback PPT.

Aucun fuzzy, aucune traduction supposée, aucune identité relâchée.

## Activation

**Non activée.** Le workflow `.github/workflows/v4-global-live-shadow.yml` reste `workflow_dispatch` manuel ; `economic_confirmation` est un mode read-only. `NTFY_TOPIC` reste vide dans ce diagnostic et les transactions sont absentes.

Une future activation doit être une phase séparée avec au minimum feature flag/default-off, déduplication persistante, politique de cadence et validation live dédiée. Elle ne doit jamais ajouter achat/bid/checkout.

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

Le tree `main` contient **15 workflows YAML** au 20 août 2026. Le détail est dans `docs/project-workflow-inventory.md`.

À retenir :

- Main Scanner et Fast Lane : cadence externe, pas de cron GitHub parallèle ;
- Robot KB : collecte séparée ;
- `v4-global-live-shadow.yml` : manuel/read-only ;
- `v4-global-market-offline-validation.yml` : CI Global ;
- le one-shot #142 a été supprimé avant merge ;
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

La phase Global #139→#142 est fermée **en read-only**. Le prochain changement ne doit pas réinventer le matching déjà validé.

Deux axes restent distincts :

```text
V4 production existante
  -> continuer à drainer/mesurer la couverture externe

Global Multi-Vault read-only
  -> seulement si décidé : concevoir une activation notification séparée
     avec déduplication + cadence + feature flag + nouveau live de validation
```

Pikachu M-P reste un no-match externe propre sur le dernier panel ; ne pas créer un alias ponctuel sans classe déterministe répétée.

Aucun benchmark vérifié ne prouve un TCGdex `500/500` ; ne pas reprendre cette affirmation sans nouvelle preuve.
