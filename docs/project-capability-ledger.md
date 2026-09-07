# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel re-vérifié le **7 septembre 2026**. Le code/Git/GitHub réel reste prioritaire sur ce document.

Statuts : `PROD_V4`, `MAIN_SUPPORT`, `ROBOT_KB`, `P3_ONLY`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`, `STALE_OPEN`, `DRAFT_VALIDATION`.

## Autorité courante

```text
V4 production branch             : main
V4 main HEAD docs                : 22303a34f7414769a04f4c587338def005b8a5c6
V4 production code HEAD #261     : 24230552d52574e2769c21dcfa84ba11320da2cf
External fair-value authority    : #255 / PROD_V4
Integrated recall/source roles   : #259 / PROD_V4
TCGdex constrained name recovery : #260 / PROD_V4
Cross-grader calibration         : #261 / PROD_V4
Auction pagination preservation  : #245 / PROD_V4
Auction recovery capacity        : #229/#231 / PROD_V4 / adaptive sizing / hard cap 250
Auction order hardening          : #211/#212 / PROD_V4
Future-start auction guard       : #220 + #243 / PROD_V4
V4 run registry                  : issue #235 ACTIVE / issue #1 archive
External pending throughput      : #214 / PROD_V4 / P4 bounded
TCGdex transport resilience      : #216/#217 / PROD_V4
TCGdex outage fallback           : #222/#224 / PROD_V4
Magi native identity             : #174/#177/#178 / PROD_V4
Global schedule watchdog         : #179 / PROD_V4
Robot KB local cutover           : #166 / PostgreSQL Mac ACTIF
Robot KB multisource             : #180 / ROBOT_KB
P3 rarity-symbol print_run       : #207 / P3_ONLY
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

---

# Production actuelle — #255 + #259 + #260 + #261

## #255 — external fair-value authority — `PROD_V4`

GCC reste une source de listing/identité/prix/timing. Son historique est observationnel pour l'économie : il ne peut pas créer, ancrer, confirmer, plafonner ou conflict-block une fair value. Une panne provider ou une preuve externe faible/indisponible ne devient jamais une preuve de marché négative.

## #259 — integrated recall/source-role/Global/Japan — `PROD_V4`

#259 est l'intégration canonique des capacités précédemment réparties dans #256/#257/#258.

Production :

- `MAX_PRICE_EUR=250` ;
- plancher économique adaptatif 20 % ;
- PSA numérique 1–10, aucune synthèse PSA 9.5 ;
- opportunity sources et valuation providers séparés ;
- PriceCharting = `GUIDE`, jamais item-level SOLD ;
- PokeTrace reste agrégé ;
- ASK eBay exact = revue secondaire seulement, jamais SOLD ;
- Mercari/SNKRDUNK = ASK/opportunités read-only ;
- historique GCC toujours sans autorité économique.

La lignée #247 reste une provenance importante de qualité PokeTrace, mais #259 a modifié la politique recall autour des agrégats ; ne pas réintroduire automatiquement l'ancien downgrade `low==avg==high` sans relire #259 et le runtime courant.

## #260 — constrained TCGdex name recovery — `PROD_V4`

Base `7cb0e067...`, head validé `d809f4aacce0cbfb362546a65de351be2451dcf6`, merge production `db4954f5b223817fe14ccfeb9dcac80c960d5dd9`.

Le recovery n'est pas un fuzzy global. Il intervient uniquement après la lignée exacte TCGdex lorsqu'une coordonnée imprimée bornée reste ambiguë. Conditions : langue/coordonnée exactes, nom seulement très légèrement différent, tokens numériques inchangés, unique candidat compatible. Plusieurs candidats ou différence matérielle => `AMBIGUOUS`.

Validation : workflow `34053317112`, job `101541221319`, suite V4 958 PASS / 2 skipped, compile/YAML/diff-check PASS, comparaison live read-only PASS. Premier Main naturel post-merge `34091885754` SUCCESS sur le SHA exact.

## #261 — cross-grader review calibration — `PROD_V4`

Merge runtime `24230552d52574e2769c21dcfa84ba11320da2cf` ; closeout docs main `22303a34...`.

- non-PSA fractionnaire : proxy secondaire **même grade numérique** CGC/BGS, pas de rabattement PCA9.5→PSA9 ;
- non-PSA entier : CGC même grade préféré ; PSA même grade fallback conservateur ;
- haircuts spécifiques au grader cible ;
- tuning #263 : fallback CA→PSA ramené de 45 % à **35 %**, sans modifier le floor cross-grader de 30 % ;
- PriceCharting compatible peut plafonner la référence brute mais reste `GUIDE` ;
- revue cross-grader seulement si décote >=30 % après haircut ;
- déduplication cross-market v2.

Validation #261 code `c58aa4c...`, run `34092254431` SUCCESS, tests ciblés + suite V4 + compile/YAML/diff-check + comparaison live read-only PASS. Le tuning #263 possède ses propres régressions ciblées et doit conserver une CI verte avant merge.

---

# Fixed queue / external coverage — `PROD_V4`

## #214 — external pending throughput

La file fixed est persistante et sépare :

```text
P0_NEW
P1_CHANGED
P2_NEVER_EVALUATED
P3_STALE
P4_EXTERNAL_PENDING
FRESH_ALREADY_EVALUATED
```

`MAX_FIXED_CANDIDATES=120` est un plafond global de traitement, pas un quota à remplir.

Le module `v4_external_coverage_drain.py` garde :

```text
V4_EXTERNAL_PENDING_MAX_PER_RUN       configurable
production actuelle                  16
hard ceiling code                    20
budget-pending cooldown              5 min
provider-error backoff               inchangé / séparé
```

Le hard ceiling 20 est volontaire : le P4 ne doit pas monopoliser les budgets provider ni affamer P0/P1/P3. Une hausse à 100 serait un changement d'architecture/budgets, pas un simple tuning d'environnement.

Preuve naturelle post-#260 `34091885754` : `processed 27 = new 1 + changed 1 + stale 9 + pending 16`, `pending backlog 1496`, `first-evaluation backlog 0`. Le backlog doit être audité par flux net et cause avant relèvement des bornes.

---

# TCGdex — `PROD_V4`

## Discovery / identity lineage

Fondations à réutiliser avant tout nouveau resolver :

- exact-coordinate / reviewed bridges #119→#135 ;
- generalized coordinate recovery ;
- two-of-three backport ;
- unique-coordinate fallback ;
- source-pinned finish metadata ;
- #216/#217 transport retry/breaker ;
- #222/#224 outage fallback immuable source-pinné ;
- #260 constrained name-filtered coordinate recovery.

`AMBIGUOUS` reste bloquant. Aucun substring, traduction supposée ou fuzzy global ne peut fabriquer une identité.

Résiduel live post-#260 : plusieurs ambiguïtés portent des suffixes de présentation GCC (`Reverse`, `Rainbow`, `Gold`, `Holo`). Le code #260 impose actuellement le même nombre de tokens entre nom listing et nom TCGdex ; toute évolution doit donc distinguer explicitement **qualifier de variante** et **nom canonique** sans jeter un token au hasard.

---

# Auction discovery — `PROD_V4`

## #211/#212

Discovery `AUCTION + ON_SALE + ENDING_SOON`, pagination durcie, safety-net legacy si couverture non prouvée.

## #220 + #243

Future-start prouvé => exclusion avant interprétation prix/countdown. Ambiguïté => fail-closed.

## #229/#231 + #245

Recovery order-drift : sizing adaptatif `ceil(api_total/page_size)+2`, page size 100, hard ceiling 250, economic cap 360, priorité `<=5 min -> <=12 min -> <=60 min`. `api_total` ne prouve jamais la complétude à lui seul.

---

# eBay / PSA / PriceCharting — provenance production

- #238/#239 + #242 + #253 : résilience eBay historique, worker jetable/bornes/salvage ;
- #175 : isolation eBay hard deadline ;
- #189 : breaker run-local ;
- #137 : salvage DOM après timeout seulement avec preuve suffisante ;
- PSA APR : erreurs/403 restent visibles, aucun contournement WAF ;
- PriceCharting : guide compatible, jamais faux SOLD ;
- direct eBay SOLD n'est plus l'autorité de fair value dans la phase #259.

Ne pas créer une nouvelle couche timeout/breaker avant de prouver l'insuffisance de ces protections.

---

# Global Multi-Vault / Japan — `PROD_V4`

#139 a réintégré la pile historique #108/#109/#110/#113/#114/#115/#138. #259 est désormais l'intégration canonique récente des rôles de sources, du recall et des providers Japan.

Architecture : GCC/Fanatics/COMC/Magi/Cardova/Mercari/SNKRDUNK découvrent des offres ; TCGdex prouve l'identité ; les providers externes établissent la valorisation ; une marketplace ne devient jamais sa propre fair value.

`ACTIVE_AUCTION` reste non actionnable hors règle explicitement bornée de snapshot final. Disparition != SOLD. Aucune transaction.

---

# Magi — `PROD_V4`

#174 + #177 = identité native déterministe ; #178 = recovery total 36, broad/nonpriority max 28, réserve exact search/detail 8. Pas de name-only/alias carte-par-carte.

---

# Robot KB — `ROBOT_KB`

PostgreSQL local Mac actif, `V4_USE=false`, Neon writers automatiques OFF. Observations append-only datées ; SOLD final prouvé prioritaire ; ASK/live/disparition/`WAITING_FOR_PAYMENT` != vente.

#180 collecte Fanatics/COMC/Magi/Cardova + PokeTrace/PPT en conservant les sémantiques. `SOLD_AGGREGATED` != item-level SOLD et `FIXED_ASK_AGGREGATED` reste ASK.

#207 est `P3_ONLY`. #210 reste OPEN/DRAFT ; aucun durable write Cardova sans autorisation explicite + backup + locks + preflight.

---

# V5 / non-production

PR #8 = **`V5_ONLY`**, OPEN/DRAFT/NON-MERGED, head vérifié historiquement `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f`. Ne jamais merger PR #8 dans `main` sans autorisation explicite.

---

# Recovery markers historiques conservés

Ces libellés restent volontairement explicites pour préserver la provenance auditée et éviter qu'une simplification documentaire efface des capacités récupérables. Ils ne redéfinissent pas l'autorité production actuelle.

- `TCGdex / PokeTrace #119→#135` — lignée historique de recovery/bridges à relire avant tout nouveau resolver ;
- `fallback générique catalogue immuable` — provenance du fallback catalogue fail-closed, à ne pas remplacer par une panne transformée en clean no-match ;
- `#139 a réintégré/revalidé le stack historique` #108/#109/#110/#113/#114/#115/#138 avant les intégrations plus récentes ;
- `GCC/Cardova/Magi/Fanatics/COMC` — provenance des sources marketplace/vault, aujourd'hui étendue mais toujours séparée des providers de valorisation ;
- `PPT = `SOLD_AGGREGATED`` — agrégat SOLD-derived, jamais item-level SOLD ;
- `PR #126 = `SUPERSEDED`` par #127→#135 ;
- `Capacités structurantes : #9, #50, #52, #104` — provenance historique `SHADOW`/recovery, pas une déclaration de production courante.

---

# Supersessions / provenance

- #126 : `SUPERSEDED` par #127→#135 ;
- #108/#109/#110/#113/#114/#115/#138 : absorbées par #139 ;
- #159 : superseded fonctionnellement par #177 ;
- #211/#212 : une capacité runtime ;
- #216/#217 : une capacité runtime ;
- #222/#224 : une capacité runtime ;
- #229/#231 : une capacité runtime ;
- #238/#239 : une capacité eBay runtime ;
- #243 complète #220 ;
- #245 complète #229/#231 et #243 ;
- #247 : provenance qualité PokeTrace, politique agrégat ensuite modifiée par #259 ;
- #255 : historique GCC observationnel économiquement ;
- #256 : `STALE_OPEN/SUPERSEDED_BY_259` pour les capacités Japan intégrées ;
- #257 : MERGED, puis intégré avec la pile recall/Global/Japan dans #259 ;
- #258 : `STALE_OPEN/SUPERSEDED_BY_259` pour le runtime recall intégré ;
- #259 : intégration production canonique recall/source-role/Global/Japan ;
- #260 : recovery TCGdex contraint production ;
- #261 : calibration cross-grader production.

---

# Invariants de reprise

- V4/main canonique ;
- PR #8 protégée ;
- aucun achat/bid/checkout/paiement ;
- Robot KB local séparé de V4 ;
- aucune écriture durable Cardova sans autorisation explicite ;
- identité ambiguë/microvariante incertaine = fail-closed ;
- ASK, enchère live et disparition != SOLD ;
- marketplace/opportunity source != valuation source ;
- panne provider != clean no-match ;
- avant nouveau code, REUSE AUDIT sur README + ledger + inventaires + branches/PR historiques.
