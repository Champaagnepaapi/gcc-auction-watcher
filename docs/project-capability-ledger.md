# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel : **15 septembre 2026**. Git/GitHub réel reste prioritaire sur ce document.

Statuts utilisés : `PROD_V4`, `MAIN_SUPPORT`, `ROBOT_KB`, `P3_ONLY`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`, `STALE_OPEN`, `DRAFT_VALIDATION`, `PROVIDER_BLOCKED`.

## Autorité courante

```text
V4 production branch             : main
V4 main HEAD                     : 3c596370ee7fcde93c969139541bc003e7012b6e
Global provider hardening        : #268 / PROD_V4 / MERGED
External fair-value authority    : #255 / PROD_V4
Integrated recall/source roles   : #259 / PROD_V4
TCGdex constrained name recovery : #260 / PROD_V4
Cross-grader calibration         : #261 / PROD_V4
CA -> PSA recall tuning          : #263 / haircut 35 %
TCGdex Rainbow microvariant      : #266 / PROD_V4
PokeTrace FREE production fix    : #271 / DRAFT_VALIDATION / NON MERGED
Fanatics diagnostic              : #273 / DIAGNOSTIC_ONLY / NON MERGED
Auction pagination preservation  : #245 / PROD_V4
Auction recovery capacity        : #229/#231 / PROD_V4 / hard cap 250
Auction order hardening          : #211/#212 / PROD_V4
Future-start auction guard       : #220 + #243 / PROD_V4
External pending throughput      : #214 / PROD_V4 / P4 max 16/run
TCGdex transport resilience      : #216/#217 / PROD_V4
TCGdex outage fallback           : #222/#224 / PROD_V4
Magi native identity             : #174/#177/#178 / PROD_V4
Robot KB local cutover           : #166 / PostgreSQL Mac / V4_USE=false
Robot KB multisource             : #180 / ROBOT_KB
P3 rarity-symbol print_run       : #207 / P3_ONLY
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

---

# Production V4 actuelle

## #268 — multi-market hardening — `PROD_V4`

PR #268 a été mergée dans `main` via `3c596370ee7fcde93c969139541bc003e7012b6e`.

Runtime de référence avant merge : `29f448a7441e82267fc9d84c2b0f9a52168e77cb`.
Rapport détaillé : [`v4-multimarket-readiness-20260914.md`](v4-multimarket-readiness-20260914.md).

Capacités mises en production :

- gates PriceCharting/PPT derrière identité canonique stricte ;
- `variants_detailed` et preuves déterministes pour microvariantes sensibles ;
- wrappers Fanatics idempotents ;
- pagination Cardova rattachée à la bonne lane/enveloppe/page ;
- discovery COMC autonome ;
- Mercari/SNKRDUNK read-only dans Global ;
- coûts inconnus conservés inconnus ;
- TCGdex indisponible/budget/403 jamais transformé en clean `NO_MATCH` ;
- Auction distingue les états terminaux de SOLD.

Validation #268 : Global `34812934273`, Auction `34812934319`, Cardova `34812934329` **SUCCESS** ; tests/compile/YAML/diff-check PASS ; aucune transaction.

## Classement provider validé

`OPERATIONAL` exige qu'un chemin réel `annonce → identité exacte → valeur indépendante → coût réel → décision` ait été observé.

| Provider | État | Preuve / blocage principal |
|---|---|---|
| GCC | **OPERATIONAL** | Chemin vault complet observé. |
| Fanatics | **PROVIDER_BLOCKED** | Deux identités EXACT observées mais coût acheteur final non prouvé ; Shining Mewtwo reste matériellement ambigu côté valorisation. |
| COMC | **PROVIDER_BLOCKED** | SOLD public anonyme HTTP 403 ; coût Store Credits/taxe/détention-livraison non prouvé. |
| Magi | **PROVIDER_BLOCKED** | Route/coût acheteur non prouvés ; certaines valeurs gradées exactes absentes. |
| Cardova | **PROVIDER_BLOCKED** | Financement/paiement et premium applicables non prouvés ; pas de valeur indépendante exacte dans la sélection validée. |
| Mercari | **PROVIDER_BLOCKED** | Identité item-level incomplète/contradictoire et coût acheteur non prouvé. |
| SNKRDUNK | **PROVIDER_BLOCKED** | Les pages répondent mais ne prouvent pas ensemble identité commerciale, grade/langue et offre individuelle exploitable ; coût acheteur absent. |

Un site accessible peut rester `PROVIDER_BLOCKED`. Pagination partielle, caps volontaires ou budget borné ne suffisent pas à eux seuls pour ce statut.

## Premier run naturel post-#268

Main Scanner `34886292095` : **SUCCESS** sur `main@3c596370...`.

Observé :

- découverte GCC complète dans le scope filtré ;
- TCGdex sans erreur transport sur ce run ;
- `EXTERNAL_PENDING_BACKLOG=2320` ;
- PSA APR HTTP 403 ;
- PriceCharting public HTTP 403 ;
- eBay SOLD 0 tentative ;
- aucun cas future-start réellement prouvé ;
- PokeTrace encore `effective_plan=PRO` dans les entrypoints production.

Le backlog ne justifie pas une hausse des caps. P4 reste borné à 16/run.

---

# #271 — PokeTrace FREE production — `DRAFT_VALIDATION`

Branche `fix/v4-poketrace-free-ceiling-production-20260914`, head `75eb09768bf55d002466c5e3d50b038c3884ceb5`.

Objet : imposer par défaut `V4_POKETRACE_PLAN_CEILING=FREE` dans Main Scanner et Global avant import provider, sans changer identité, budgets, seuils ou SOLD/ASK. Les données gradées Pro ne deviennent pas utilisables simplement parce que l'API continue à annoncer PRO.

Validations du head :

- Global `34879803090` SUCCESS ;
- Auction `34879802895` SUCCESS ;
- Cardova `34879802823` SUCCESS.

#271 reste **OPEN / DRAFT / NON MERGÉE**. Aucun déploiement sans autorisation explicite.

---

# #273 — diagnostic Fanatics — `DIAGNOSTIC_ONLY`

Branche `diag/v4-fanatics-ppt-variant-proof-20260914`, head `c31882e8adacff8c291a43e78eb8ab6712ff2359`.

Workflow `34886340368` : **SUCCESS**, read-only, aucune mutation runtime. Le diagnostic a respecté le plancher PPT : `daily_remaining=55 < 15000`, donc aucune baisse de protection pour forcer un résultat.

Preuves conservées :

- Shining Mewtwo `neo4-109` : EXACT, deux variantes matérielles applicables → doit rester bloqué ;
- Litten `mep-044` : EXACT, une variante TCGdex applicable, mais même une amélioration du matcher ne prouverait pas le coût acheteur final Fanatics.

Conclusion : Fanatics reste `PROVIDER_BLOCKED`; pas de relaxation d'identité ni de correctif carte-par-carte.

#273 n'est pas destinée au merge production.

---

# Fair value / source roles — `PROD_V4`

## #255

GCC reste source de listing/identité/prix/timing, mais son historique ne peut pas créer ou confirmer seul une fair value. Une panne provider ou une preuve externe faible ne devient jamais une preuve négative de marché.

## #259

Intégration canonique des capacités recall/source-role/Global/Japan :

- `MAX_PRICE_EUR=250` ;
- plancher économique adaptatif 20 % ;
- PSA numérique 1–10, aucune synthèse PSA 9.5 ;
- opportunity sources et valuation providers séparés ;
- PriceCharting = `GUIDE`, jamais item-level SOLD ;
- PokeTrace = agrégat marché après identité ;
- ASK eBay exact = contexte secondaire, jamais SOLD ;
- Mercari/SNKRDUNK = offres read-only ;
- historique GCC sans autorité économique.

Priorité prix canonique : **SOLD exact récent > SOLD exact ancien ajusté > fixed ASK compatible > snapshot auction ≤5 min si aucun SOLD > enchère en cours signal faible**.

---

# TCGdex / identité — `PROD_V4`

Fondations à réutiliser avant tout nouveau resolver :

- exact-coordinate / reviewed bridges #119→#135 ;
- generalized coordinate recovery ;
- two-of-three backport ;
- unique-coordinate fallback ;
- source-pinned finish ;
- #216/#217 transport retry/breaker ;
- #222/#224 outage fallback immuable source-pinné ;
- #260 constrained name-filtered coordinate recovery ;
- #266 Rainbow source-proven via `variants_detailed`.

`AMBIGUOUS` reste bloquant. Aucun substring, fuzzy global, traduction supposée, name-only ou number-only ne fabrique une identité exacte.

Ne jamais mélanger langue, set, numéro, édition, printing, finish, microvariante, grader ou grade incompatibles.

---

# Fixed queue / external coverage — `PROD_V4`

File persistante :

```text
P0_NEW
P1_CHANGED
P2_NEVER_EVALUATED
P3_STALE
P4_EXTERNAL_PENDING
FRESH_ALREADY_EVALUATED
```

`MAX_FIXED_CANDIDATES=120` est un plafond global, pas un quota à remplir.

`V4_EXTERNAL_PENDING_MAX_PER_RUN=16`, hard ceiling code 20. Le P4 ne doit pas monopoliser les providers ni affamer P0/P1/P3. Le run naturel actuel montre 2320 `EXTERNAL_PENDING`, mais ce volume n'autorise pas une hausse automatique des caps.

---

# Auction discovery — `PROD_V4`

- #211/#212 : `AUCTION + ON_SALE + ENDING_SOON`, pagination durcie ;
- #220 + #243 : future-start prouvé exclu avant interprétation du prix/countdown ;
- #229/#231 + #245 : recovery order-drift adaptatif, page size 100, hard ceiling 250, economic cap 360 ; priorité `<=5 min → <=12 min → <=60 min`.

`ACTIVE_AUCTION`, `ENDED`, `OUT_OF_SCOPE`, disparition ou statut fournisseur ne deviennent jamais automatiquement SOLD.

---

# eBay / PSA / PriceCharting — provenance production

- #137 : salvage DOM seulement avec preuve suffisante ;
- #175 : worker eBay jetable avec hard deadline ;
- #189 : breakers run-local ;
- #238/#239/#242/#253 : résilience/navigation eBay ;
- PSA APR HTTP 403 reste provider unavailable, sans bypass ;
- PriceCharting HTTP 403 reste provider unavailable, jamais faux no-match ;
- direct eBay SOLD n'est plus l'autorité unique de fair value après #259.

Ne pas créer une nouvelle couche timeout/breaker avant de prouver l'insuffisance de celles-ci.

---

# Magi — `PROD_V4`

#174/#177 : identité native déterministe. #178 : recovery historique. #268 a ensuite validé des budgets bornés 50 total / 35 broad / 15 réserve exact search/detail sur sa lane Global.

Les lignes explicitement SOLD de Magi ne deviennent pas des ventes finales prouvées sans prix final/date de vente prouvés.

---

# Robot KB / P3 — séparés de V4

Robot KB local : PostgreSQL Mac, `V4_USE=false`, observations append-only datées, SOLD final prouvé prioritaire. Fixed = ASK/baseline ; auction final SOLD prioritaire, snapshot ≤5 min seulement fallback identifié.

#180 = `ROBOT_KB`. #207 = `P3_ONLY`. #210 prépare Cardova durable mais reste OPEN/DRAFT ; aucun write durable sans autorisation explicite + backup + locks + preflight.

PR #270 (`feat/robot-kb-magi-sold-marked-snapshots-20260907`) reste Robot KB seulement : un marqueur SOLD Magi est conservé comme snapshot, avec `genuine_sale_evidence=False`, jamais comme vente finale inventée.

---

# V5 — non-production

PR #8 = **`V5_ONLY / PROTECTED`**, OPEN/DRAFT/NON-MERGED, branche `agent/v5-poketrace-cardmarket-market-data`, head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f`.

Ne jamais merger PR #8 dans `main` sans autorisation explicite utilisateur.

---

# Supersessions / provenance utile

- #126 : `SUPERSEDED` par #127→#135 ;
- #108/#109/#110/#113/#114/#115/#138 : absorbées par #139 ;
- #159 : superseded fonctionnellement par #177 ;
- #211/#212, #216/#217, #222/#224, #229/#231 : paires d'une même capacité runtime ;
- #243 complète #220 ; #245 complète #229/#231 et #243 ;
- #247 : provenance PokeTrace, politique recall ensuite modifiée par #259 ;
- #256 et #258 : `STALE_OPEN/SUPERSEDED_BY_259` ;
- #257 : MERGED puis intégré dans #259 ;
- #259/#260/#261/#263/#266/#268 : production canonique V4 ;
- #272 : CLOSED / NON MERGED / redondante, car le support PPT English PSA 8/8.5/9/10 existe déjà dans `main` ;
- #271 : correction production validée mais non mergée ;
- #273 : diagnostic uniquement, non destiné au merge.

## Règle de reprise

Avant toute nouvelle capacité : vérifier `main`, PR mergées, V5, Robot KB/P3 et branches historiques. Préférer une règle générique déterministe ; ne jamais recréer une capacité déjà absorbée par une supersession documentée.
