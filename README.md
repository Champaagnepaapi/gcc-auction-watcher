# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
> Ce README décrit l'état courant. L'historique détaillé reste dans Git/GitHub et dans `docs/project-capability-ledger.md` ; ne pas réintroduire une ancienne implémentation simplement parce qu'elle apparaît dans un vieux commit.

## État canonique — 20 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production canonique         : main / toujours re-vérifier le SHA GitHub live
Global marketplace-first        : PR #147 mergée / merge SHA 5a1b0f050098b560e812a4dc6e64a9f8d40a8897
Global notification activation  : PR #146 / marker versionné + override repo variable
Global production cutover       : workflow v4-global-notify.yml -> marketplace-first après merge de la phase cutover
V5 expérimentale                : PR #8 / agent/v5-poketrace-cardmarket-market-data
Robot KB / Neon                 : historique durable séparé de V4/V5
TCGdex source pin               : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Le SHA exact de `main` doit toujours être re-vérifié live. Les SHA ci-dessus servent de points de reprise fonctionnels, pas de promesse que le HEAD courant est identique après de nouveaux merges/docs.

### Phase Global Multi-Vault #139 → #142 — INTÉGRÉE

- PR #139 a réintégré sur le `main` courant le Global Multi-Vault strict : GCC, Cardova, magi, Fanatics et COMC.
- PR #140 ajoute la **confirmation économique externe** PPT/PokeTrace après identité exacte.
- PR #142 ajoute le bridge générique de nomenclature provider exact, sans fuzzy ni alias carte-par-carte ; elle a été mergée dans #140 avant le merge vers `main`.
- cette couche économique reste sans transaction automatique ; seule la lane notification séparée #145/#146 peut produire une alerte utilisateur lorsqu'elle est explicitement activée.

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

### Phase #145 — notifications Global confirmées

PR #145 construit une lane de notification séparée au-dessus du moteur économique déjà validé. Elle ne remplace ni le scanner V4 canonique ni le matching #140/#142.

Gate de notification :

```text
exact actionable offer
  + MULTIMARKET_CONFIRMED
  + would_notify=true
  + all_in_eur prouvé
  + external graded >= 3 sales
  -> déduplication persistante
  -> notification seulement si activation schedule explicite
```

Capacités #145 :

- déduplication persistante 14 jours par identité + marché + URL ;
- re-notification seulement après expiration TTL ou baisse de prix `>=5%` ;
- état corrompu = fail-closed lorsque la livraison est activée ;
- `workflow_dispatch` reste **toujours dry-run** ;
- workflow permanent `v4-global-notify.yml` avec cron `41 * * * *` ;
- aucun achat, bid, checkout ou paiement.

Le premier live de validation notification (`32357750921`) a validé la mécanique/sécurité mais a subi des `ReadTimeout` TCGdex sur 5/5 identités. #145 ajoute donc une résilience **Global-only et transport-only** : max 2 tentatives, timeout 10 s, backoff 0.25 s, uniquement Timeout/ConnectionError/HTTP 502/503/504. Un échec final reste `ERROR`/fail-closed ; aucun 404/no-match n'est transformé et aucune règle d'identité n'est relâchée. Le scanner V4 canonique n'installe pas ce wrapper.

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

Validation finale #145 :

```text
head validé                      1b20f583a31e5488acbb7e4eace488e2675ffbc0
V4 Global Market Offline         32360818382  SUCCESS
V4 Global Shadow Dispatcher CI   32360818383  SUCCESS
Global tests                     164/164 PASS
V4 multimarket                    51/51 PASS
py_compile / YAML / diff-check   PASS
merge main                       929d0d24ba959ba1ff30b2d73b1df5adc1d460e6
```

### Phase #146 — activation réelle Global

L'utilisateur a explicitement autorisé l'activation réelle après le merge #145.

Le connecteur GitHub disponible ne permet pas de modifier directement les repository variables Actions. L'activation est donc rendue **auditable et versionnée** sans affaiblir le fail-closed :

- `.github/global-notify-activation` contient littéralement `true` ;
- un run `schedule` lit ce marker après checkout ;
- `vars.GLOBAL_NOTIFY_ENABLED=true` reste supporté ;
- `vars.GLOBAL_NOTIFY_ENABLED=false` est un **override d'urgence prioritaire** qui coupe la lane même si le marker vaut `true` ;
- `workflow_dispatch` reste toujours dry-run et ne peut pas envoyer ;
- si `NTFY_TOPIC` est absent/vide, le runner lève `GLOBAL_NOTIFY_ENABLED_WITHOUT_TOPIC` avant le scan et n'envoie rien ;
- aucune règle identité/prix n'est modifiée ; aucune transaction n'est ajoutée.

Premier run planifié réel après activation :

```text
run / job              32379733361 / 96459686467
main                    3d8f6cc6c12d6cf0d438128389bce89c0df09d1f
mode                    GLOBAL_NOTIFICATION_ACTIVE
activation              true via marker versionné
cards                    5
confirmed candidates     0
sent                     0
market conflicts         1 blocked
state cursor             0 -> 5
transactions             false
identity_gate_relaxed    false
```

La lane notification a donc été prouvée active en production ; `0 sent` venait de l'absence d'opportunité confirmée, pas d'une désactivation.

### Phase #147 — discovery Global marketplace-first — MERGÉE

PR #147 remplace la logique **seed-first comme moteur de discovery** par le flux demandé :

```text
GCC / Fanatics / COMC / magi / Cardova
  -> scan de l'inventaire disponible
  -> identité exacte
  -> TCGdex exact
  -> PPT + PokeTrace
  -> calcul de décote
  -> notification si gate complet
```

Le bootstrap découvre l'inventaire existant et met immédiatement les offres en file d'évaluation économique ; les runs suivants conservent un état durable et ne remettent en file que les nouvelles annonces ou changements économiques utiles. Une disparition n'est jamais transformée en SOLD.

L'historique GCC n'est plus une liste de cartes à choisir avant de chercher les offres. Il reste un **catalogue de retrieval exact** et une ancre de fair lorsqu'elle existe. Un agrégat externe exact et suffisamment fort (`>=3` ventes) peut confirmer une offre en `EXTERNAL_ONLY` lorsque le fair GCC exact manque.

Régression découverte pendant le premier live #147 : l'API GCC n'écho pas toujours `sellingTypeGroup` dans chaque row. Le nouveau parser pouvait alors classer une enchère à faible prix de départ comme `FIXED_ASK`. Correctif final : le scanner transmet explicitement le type **de la requête GCC** (`FIXED_PRICE` ou `AUCTION`) au parser. Deux tests dédiés verrouillent row sans type + auction active et row sans type + snapshot `≤5 min`.

Validation finale après ce correctif :

```text
head #147                       2e65631416d0b39947de47ed4df3d37a4a87cbdc
merge main                      5a1b0f050098b560e812a4dc6e64a9f8d40a8897
CI / live run                   32397363626 SUCCESS
validate / live jobs            96517204490 / 96517278588
Global tests                    201/201 PASS
V4 multimarket                   51/51 PASS
py_compile / YAML / diff-check  PASS
GCC candidates / exact          14375 / 1172
Fanatics candidates / exact     24 / 1
COMC candidates / exact         11 / 11
magi candidates / exact         96 / 0
inventory queued                1184
selected / pending after        10 / 1174
TCGdex exact                    5
PPT matched                     1 ; 6 HTTP ; 28 crédits ; remaining 19310
PokeTrace matched               4 ; 6 requêtes
market conflicts                4 blocked
confirmed_would_notify          0
notifications                   false pendant validation
transactions                    false
artifact                        9417266637
artifact digest                 sha256:e15160d7bcca026ea28af116aaa8d6513cda5271f4d9a4483ef7dc666c925f6d
```

Cardova reste explicitement `AUTH_SESSION_INPUT_REQUIRED` tant qu'aucune session/auth automatisable sûre n'est fournie. Aucun secret de session n'est stocké ou commité.

### Phase cutover production marketplace-first — EN VALIDATION

Le workflow permanent `.github/workflows/v4-global-notify.yml` est modifié sur une branche dédiée pour utiliser `v4_global_marketplace_notify_resilient.py` au lieu du runner seed-rotation historique, **sans créer de second cron**.

Contrat du cutover :

- même schedule `41 * * * *` ;
- même marker d'activation et même override d'urgence `vars.GLOBAL_NOTIFY_ENABLED=false` ;
- `workflow_dispatch` reste toujours dry-run ;
- état durable séparé `.global-marketplace-state` ;
- bootstrap complet de discovery puis incrémental ;
- `10` listings pending évalués économiquement par run au démarrage, valeur déjà validée live avec les budgets PPT/PokeTrace actuels ;
- mêmes gates stricts TCGdex/PPT/PokeTrace et mêmes règles ASK/auction ;
- aucun achat, bid, checkout ou paiement.

Ne considérer ce cutover `PROD` qu'après CI + live read-only de la PR de cutover, merge autorisé, puis observation d'un vrai run `schedule` sur `main`.

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

# Global Multi-Vault — marketplace-first + notifications confirmées

Pipeline économique courant :

```text
inventaire GCC / Fanatics / COMC / magi / Cardova
  -> identité commerciale exacte
  -> TCGdex exact
  -> GCC SOLD exact si disponible
  -> PPT + PokeTrace graded aggregate confirmation
  -> décision économique
  -> notification seulement si gate complet
```

Les anciennes seeds GCC restent utilisables comme **catalogue exact de retrieval/benchmark**, jamais comme moteur qui choisit arbitrairement 5 cartes avant de chercher les offres.

## Gate économique Global

- opportunité actionnable uniquement `FIXED_ASK` ou `AUCTION_SNAPSHOT_LE5` avec `all_in_eur` prouvé ;
- `ACTIVE_AUCTION` reste signal faible ;
- confirmation externe gradée obligatoire avant `would_notify` ;
- minimum 3 ventes agrégées pour un centre externe utilisable ;
- PPT/PokeTrace/eBay partagent `EBAY_GRADED_AGGREGATE` et ne comptent qu'une fois ;
- conflit matériel au sein de la famille corrélée reste bloquant ;
- si GCC fair existe et contredit matériellement l'externe, `MARKET_CONFLICT_BLOCKED` ;
- lorsque GCC fair existe, fair confirmé conservateur = `min(GCC fair, external fair)` ;
- sans GCC fair exact, un externe exact/fort peut produire `EXTERNAL_ONLY` ;
- seuil actuel : 30 % de décote.

## Bridge provider exact #142

Le bridge n'accepte que des différences de nomenclature mécaniques bornées après preuve exacte du full collector number, du set/préfixe TCGdex et de la langue : suffixes `V`, `VSTAR`, `VMAX`, `ex`, `GX`, ou forme `Mega <nom> ex`.

`Unlimited` n'est traité comme non matériel que si la carte TCGdex exacte prouve explicitement `firstEdition=false`. Un `externalCatalogId` conflictuel ne peut jamais tomber dans un fallback PPT.

Aucun fuzzy, aucune traduction supposée, aucune identité relâchée.

## Notifications Global

La lane `.github/workflows/v4-global-notify.yml` :

- `workflow_dispatch` = dry-run uniquement ;
- schedule horaire = `41 * * * *` ;
- activation par `vars.GLOBAL_NOTIFY_ENABLED=true` ou marker versionné `.github/global-notify-activation=true` ;
- `vars.GLOBAL_NOTIFY_ENABLED=false` force l'arrêt ;
- dédup 14 jours + reprice >=5 % ;
- état marketplace persistant : baseline puis nouvelles annonces/changements utiles ;
- TCGdex transport retry borné Global-only ;
- `NTFY_TOPIC` absent = fail-closed ;
- aucun achat/bid/checkout/paiement.

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

Le tree `main` contient **16 workflows YAML**. Le détail est dans `docs/project-workflow-inventory.md`.

À retenir :

- Main Scanner et Fast Lane : cadence externe, pas de cron GitHub parallèle ;
- Robot KB : collecte séparée ;
- `v4-global-live-shadow.yml` : manuel/read-only ;
- `v4-global-market-offline-validation.yml` : CI Global + live marketplace-first read-only sur PR pertinente ;
- `v4-global-notify.yml` : manual dry-run + schedule horaire, cutover marketplace-first sans second cron ;
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

```text
V4 production existante
  -> continuer normalement ; cœur V4 inchangé par Global

Global marketplace-first
  -> valider le cutover du workflow existant v4-global-notify.yml
  -> ne créer aucun cron parallèle
  -> conserver 10 évaluations/run tant qu'un scale-up n'est pas mesuré
  -> après merge, vérifier le premier vrai run schedule sur main
  -> si anomalie : vars.GLOBAL_NOTIFY_ENABLED=false coupe immédiatement la lane

Cardova
  -> reste fail-closed AUTH_SESSION_INPUT_REQUIRED
  -> ne jamais stocker un secret/session dans le repo
```

Pikachu M-P reste un no-match externe propre sur le panel historique ; ne pas créer un alias ponctuel sans classe déterministe répétée.

Aucun benchmark vérifié ne prouve un TCGdex `500/500` ; ne pas reprendre cette affirmation sans nouvelle preuve.
