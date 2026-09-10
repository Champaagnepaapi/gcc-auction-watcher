# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel re-vérifié le **10 septembre 2026**. Le code/Git/GitHub réel reste prioritaire sur ce document.

Statuts : `PROD_V4`, `MAIN_SUPPORT`, `ROBOT_KB`, `P3_ONLY`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`, `STALE_OPEN`, `DRAFT_VALIDATION`.

## Autorité courante

```text
V4 production branch             : main
V4 main HEAD                     : b43dec6084f341b2b52301a4f0542d6f616cf1e2
V4 production code HEAD #266     : 761b5e980aeaf63833f574127fbe1ff4728f86b4
External fair-value authority    : #255 / PROD_V4
Integrated recall/source roles   : #259 / PROD_V4
TCGdex constrained name recovery : #260 / PROD_V4
Cross-grader calibration         : #261 / PROD_V4
CA -> PSA recall tuning          : #263 / haircut 35 %
TCGdex Rainbow microvariant      : #266 / PROD_V4
Global provider hardening        : #268 / DRAFT_VALIDATION / NON MERGED
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

# Production actuelle — #255 + #259 + #260 + #261 + #263 + #266

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

## #261 + #263 — cross-grader review calibration — `PROD_V4`

Merge runtime #261 `24230552d52574e2769c21dcfa84ba11320da2cf` ; closeout docs main `22303a34...` puis consolidation #262 `85f429e2...`.

- non-PSA fractionnaire : proxy secondaire **même grade numérique** CGC/BGS, pas de rabattement PCA9.5→PSA9 ;
- non-PSA entier : CGC même grade préféré ; PSA même grade fallback conservateur ;
- haircuts spécifiques au grader cible ;
- #263 ramène uniquement le fallback `CA -> PSA_FALLBACK_CONSERVATIVE` de 45 % à **35 %** ;
- PriceCharting compatible peut plafonner la référence brute mais reste `GUIDE` ;
- revue cross-grader seulement si décote >=30 % après haircut ;
- déduplication cross-market v2.

Validation #261 code `c58aa4c...`, run `34092254431` SUCCESS, tests ciblés + suite V4 + compile/YAML/diff-check + comparaison live read-only PASS. #263 conserve des régressions dédiées Glaceon/Riolu et un cas de recall à la frontière ; le head exact doit rester CI-vert avant merge.

## #266 — TCGdex Rainbow microvariant — `PROD_V4`

Rainbow reste une microvariante matérielle, jamais un simple alias Holo. Set/langue/localId/dénominateur/nom doivent être exacts et `variants_detailed` doit prouver `type=holo + foil=rainbow`; toute absence, autre foil ou contradiction reste fail-closed. Merge production : `761b5e980aeaf63833f574127fbe1ff4728f86b4`; closeout `main` : `b43dec6084f341b2b52301a4f0542d6f616cf1e2`.

---

# #268 — Global provider coverage hardening — `DRAFT_VALIDATION`

PR #268 reste **OPEN / DRAFT / NON MERGED**, branche `fix/v4-global-coverage-losses-20260907`, base `main@b43dec6084f341b2b52301a4f0542d6f616cf1e2`. Le runtime validé avant closeout docs est `e51de1e924ef9090190dba1107924d6b345ea06d`.

Capacités validées sur cette branche :

- Fanatics : aliases TCGdex japonais reviewés strictement provider-only ; aucun nom de listing ne peut remplacer le nom catalogue pour fabriquer un `EXACT` ;
- Master Ball/Poke Ball : preuve source immuable obligatoire, échec/contradiction terminal, représentation commune `finish=reverse` + `variant=master_ball|poke_ball` ;
- le cas historique Pikachu `SV2a-025` est couvert par un test runtime V2+V3 avec pin `af33c9ac882e2acfadffaf19e8083aa976d12983`, mais l'annonce n'était plus dans le dernier échantillon live ;
- Fanatics collection : zéro URL non prouvé ne devient plus `complete=true`; états et diagnostics HTTP/DOM/observations restent bornés ;
- Magi : manifeste final borné à 200 lignes sans requête supplémentaire. Les bornes de recovery de #268 sont `50 total / 35 broad / 15 réserve exacte` ; **elles sont candidate-only et ne remplacent pas les bornes production #178 tant que #268 n'est pas mergée** ;
- Auction compare : états `RESOLVED`, `ENDED`, `UNKNOWN`, `INSPECTION_ERROR` séparés ; `ENDED` nécessite une preuve structurée propre à l'item et ne constitue jamais une vente SOLD ;
- Cardova : la pagination publique reste fail-closed sur la complétude ;
- PriceCharting : les erreurs HTTP 403 restent `PROVIDER_ERROR`; aucun bypass/WAF workaround.

Validation automatique du head runtime `e51de1e924ef9090190dba1107924d6b345ea06d` :

- Global `34471762196` SUCCESS : Global offline `506` PASS ; live Fanatics `24/0` avec HTTP 200/`RESULTS_STABLE`, Magi `32/93` avec manifeste `93/93`, recovery `48/50`, broad `35`, réserve `15`, PriceCharting `24/0` avec HTTP 403, notifications `0`, safety contract PASS ;
- Fanatics avant/après : par rapport au run `34276645596` à `2/24`, les anciens exacts Gengar Web 1st Edition et Rocket's Moltres ex sont absents ; 20 URL sorties, 20 nouvelles, 4 communes inchangées en `NO_MATCH / explicit_language_unproven`. Aucun `EXACT -> rejet` observé ;
- Auction `34471762199` SUCCESS : `1002` tests, `2` skipped, compile/YAML/diff-check PASS, live `310 effectifs / 294 legacy`, `legacy missing=0`, unresolved timers `0` ;
- Cardova `34471762219` SUCCESS, complétude non prouvée conservée `false`.

Limitations connues / suite séparée :

- le Pikachu historique n'est pas live-revalidé parce qu'il a quitté l'échantillon Fanatics ;
- PriceCharting reste inaccessible en live public (HTTP 403), sans contournement autorisé ;
- audit P5 : durcir l'admissibilité identité PriceCharting avant tout `MATCHED` ;
- audit P6 : faire passer le chemin PPT reviewed-set par le même gate canonique strict ;
- audit P7 : rendre la chaîne d'installers Fanatics idempotente/acyclique ;
- audit P8 : lier toute preuve de fin de pagination Cardova à la bonne enveloppe/lane.

Aucun de P5–P8 n'est revendiqué corrigé par ce closeout. PR #8/V5, Robot KB/Neon et les sémantiques SOLD/ASK restent séparés.

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

## Fondations historiques récupérées — provenance à conserver

Ces marqueurs restent volontairement explicites : ils sont des points d'entrée de réutilisation et empêchent qu'un closeout récent efface la provenance d'anciennes capacités validées.

**Capacités structurantes : #9, #50, #52, #104**, puis #211/#212, #220, #229/#231, #243 et #245.

**TCGdex / PokeTrace #119→#135** : exact-coordinate, catalogue uniqueness, source-pinned finish/set et PokeTrace market-only après identité TCGdex. Le **fallback générique catalogue immuable** reste une fondation récupérée ; aucun alias treadmill. **PR #126 = `SUPERSEDED`** par #127→#135.

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

#139 a réintégré/revalidé le stack historique #108/#109/#110/#113/#114/#115/#138. #259 est désormais l'intégration canonique récente des rôles de sources, du recall et des providers Japan.

Production actuelle : **GCC/Cardova/Magi/Fanatics/COMC** → identité commerciale exacte → TCGdex exact + microvariante → preuves externes → décision. `PPT = `SOLD_AGGREGATED`` est conservé comme sémantique historique : agrégé SOLD, jamais item-level SOLD.

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

PR #8 = **`V5_ONLY`**, OPEN/DRAFT/NON-MERGED, head vérifié `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f` le 10 septembre 2026. Ne jamais merger PR #8 dans `main` sans autorisation explicite.

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
- #261 : calibration cross-grader production ;
- #263 : tuning CA→PSA 35 % de la lane de revue cross-grader, sans changement du floor 30 % ni des règles d'identité ;
- #266 : Rainbow source-proven en production ;
- #268 : `DRAFT_VALIDATION`, provider coverage/hardening validé sur branche mais non mergé.

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