# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot fonctionnel re-vérifié le **4 septembre 2026** après les merges production #245 et #247 et leurs preuves naturelles Main Scanner. Le code/Git/GitHub réel reste prioritaire sur ce document.

Statuts : `PROD_V4`, `MAIN_SUPPORT`, `ROBOT_KB`, `P3_ONLY`, `V5_ONLY`, `SHADOW`, `DEFERRED`, `DISABLED`, `SUPERSEDED`, `STALE_OPEN`.

## Autorité courante

```text
V4 production branch             : main
V4 production HEAD               : a7666faf4b0ef2fab74295a45ebcf75d9832f284 / #247
PokeTrace aggregate quality      : #247 / PROD_V4 / degenerate STRONG -> WEAK/INSUFFICIENT
Auction pagination preservation  : #245 / PROD_V4 / stable default 100 rows/page preserved
Auction recovery capacity        : #229/#231 / PROD_V4 / adaptive sizing / hard cap 250
Auction order hardening          : #211/#212 / PROD_V4
Future-start auction guard       : #220 + #243 / PROD_V4 / validated head 20e1a12e35464840952cdb9079e6063f014e3bef
V4 run registry                  : issue #235 ACTIVE / issue #1 archive / #237
eBay bulk result text            : #238/#239 / PROD_V4 / validated head 90741ac0eaca42f90a6bc7fca816d347aaccafeb
eBay result before teardown      : #242 / PROD_V4 / validated head 7c97d73a9caf93871d918a8dabc5a7be72375697
TCGdex transport resilience      : #216/#217 / PROD_V4 / 03824158ac899cf142199c42d4525386a573bc15
TCGdex outage fallback           : #222/#224 / PROD_V4 / 0be4dca95513e36f4e407ef7bac361fe488c1d36
External pending throughput      : #214 / PROD_V4 / P4 16 + eBay 16 / auction max 4
Magi native identity             : #174/#177/#178 / PROD_V4
Global schedule watchdog         : #179 / PROD_V4
Robot KB local cutover           : #166 / PostgreSQL Mac ACTIF
Robot KB multisource             : #180 / ROBOT_KB
P3 rarity-symbol print_run       : #207 / P3_ONLY
V5 expérimentale                 : PR #8 / OPEN / DRAFT / NON MERGED
TCGdex source pin                : af33c9ac882e2acfadffaf19e8083aa976d12983
```

---

# V4 production

## #247 — PokeTrace aggregate quality guard — `PROD_V4`

But : empêcher un agrégat PokeTrace eBay gradé sans dispersion informative de devenir seul une preuve `STRONG` / `EXTERNAL_RESCUE`.

Contrat :

```text
input                            PokeTrace MATCHED + STRONG + estimate
invalid / non-positive price     CLEAN_INSUFFICIENT / WEAK
price envelope <= 0.01 EUR       CLEAN_INSUFFICIENT / WEAK
estimate after downgrade         absent du chemin économique
fallback                         PSA APR / eBay requis
informative price range          comportement historique conservé
```

Le cas de régression `124.83–124.83 EUR / PSA 9 / 29 ventes` ne peut plus ancrer seul une valorisation PokeTrace à 124.83 EUR ni une décote artificielle.

Validation exacte : head `03ce93ae08eedf3301813f030b67f120b7abd4a4`, workflow `33799908680` SUCCESS, suite V4 PASS, tests ciblés du guard PASS, compile/YAML/diff PASS, live auction compare read-only PASS. Merge production `a7666faf4b0ef2fab74295a45ebcf75d9832f284`.

Preuve naturelle post-merge : Main Scanner `33844655319` SUCCESS sur exact `a7666faf...`, `scan_exit_code=0`, fixed discovery `3259/3259` COMPLETE, auctions `100/100` rows/timers, scope COMPLETE, fallback false, 0 opportunité finale. PokeTrace `attempted=1 / strong=0 / weak=0 / errors=0`.

**Limite de preuve :** ce premier run n'a pas rencontré un nouvel agrégat PokeTrace dégénéré STRONG. Il prouve le déploiement/non-régression ; le déclenchement positif du guard est établi par les tests ciblés. Plusieurs runs naturels suivants sur `a7666...` sont également SUCCESS.

Aucun changement de discovery GCC, TCGdex/identité, langue, grader, grade, microvariante, définition SOLD, seuil économique, cap, budget, notification ou transaction.

Ledger détaillé : `docs/v4-poketrace-aggregate-quality-guard-20260904.md`.

## #245 — preserve hardened auction pagination defaults — `PROD_V4`

Incident naturel pré-fix : Main Scanner `33795854886` sur `a93cd862...` détecte une dérive `ENDING_SOON`, un provider count hint `16264`, étend le recovery `100 -> 250` pages puis échoue sur `auction API safety limit 250 pages reached` et bascule fail-closed sur le fallback legacy.

Cause exacte : le wrapper future-start transmettait implicitement `page_size=24`, écrasant le default **100 rows/page** de `v4_auction_pagination_stability`. À ~16.2k rows, le sizing passait artificiellement d'environ 163 pages à ~678 pages.

Contrat #245 :

```text
omitted page_size / max_pages    non transmis au wrapped collector
stable underlying default        100 rows/page conservé
explicit overrides               conservés
recovery hard ceiling            250 pages inchangé
auction economic cap             360 inchangé
priority                         <=5m -> <=12m -> <=60m inchangée
identity / FV / providers        inchangés
transactions                     aucune
```

Validation exacte : head `c553796d8829e5f6dd615acfc7177ddb60f4bf91`, run `33796972288` SUCCESS, `898 PASS / 2 skipped`, compile/YAML/diff PASS, focused regression PASS, live auction compare read-only `effective=36 / legacy=32 / legacy_only=0 / unresolved=0`. Merge production `a39c693d629b003f69f66ba20753303b197737af`.

Preuve naturelle post-merge : Main Scanner `33799767652` SUCCESS sur exact `a39c693d...`, `scan_exit_code=0`, scope `COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS`, `100/100` rows/endTime, `fallback=false`. Le log confirme `page=1&limit=100`, `page size: 100`, `pagination end: AUCTION_HORIZON_CROSSED_IN_ENDING_SOON_ORDER`, `incomplete reasons: NONE`. C'est une preuve saine du fast path post-merge, pas une reproduction post-fix du chemin order-drift. La preuve pathologique reste `33795854886` + le test ciblé.

Ledger détaillé : `docs/v4-auction-pagination-default-preservation-20260903.md`.

## #220 + #243 — future-start auction guard — `PROD_V4`

Une enchère prouvée future-start est exclue avant que starting price/countdown-to-start puissent devenir bid courant/temps avant fin.

#243 ferme le bypass Main Scanner où une row API déjà munie de `minutes_to_end` évitait auparavant la vérification rendue. Sans preuve structurée de démarrage, la fiche GCC est vérifiée avant économie : upcoming explicite => exclusion ; page ambiguë/erreur => fail-closed ; vraie auction live => action de bid + fin explicite.

Incident déclencheur : Braixen #069/068 PSA 9 et Altaria #194/172 PSA 10. Validation #243 : head `20e1a12e35464840952cdb9079e6063f014e3bef`, run `33794118816` SUCCESS, `896 PASS / 2 skipped`, compile/YAML/diff/live compare PASS, merge `3ada7785d3fbef8050a7712bc773a52fd569716d`.

## #229/#231 — auction order-drift recovery capacity — `PROD_V4`

Après dérive d'ordre prouvée uniquement :

```text
budget = ceil(api_total / page_size) + 2
minimum = ancien bound
hard ceiling = 250 pages
```

`api_total` sert au sizing seulement ; `COMPLETE` exige l'épuisement API réel ou le franchissement correct de l'horizon dans un ordre vérifié. #245 garantit que le wrapper future-start ne remplace plus silencieusement le `page_size=100` durci par `24`.

Fast path, cap économique auctions `360`, identité, valorisation, providers, notifications et transactions restent inchangés.

## Discovery GCC #211/#212 — `PROD_V4`

- fixed : `/on-sale-items`, discovery avant caps économiques ;
- auctions : `AUCTION + ON_SALE + ENDING_SOON` avec `endTime` individuel ;
- horizon principal ≤60 min + safety-net legacy ;
- dérive d'ordre => récupération exhaustive bornée puis horizon local ;
- pagination/endTime invalides restent fail-closed ;
- Main Scanner cadencé extérieurement ; pas de cron GitHub parallèle.

Capacités structurantes : #9, #50, #52, #104, #211/#212, #220, #229/#231, #243, #245.

## #238/#239 + #242 — eBay worker resilience — `PROD_V4`

#238/#239 réduit l'overhead de lecture Playwright des `li.s-item` via une lecture bulk `all_inner_texts()` avec fallback historique. #242 conserve un résultat eBay SOLD déjà validé avant un teardown Chromium qui se bloque, avec cleanup borné et kill du process disposable si nécessaire.

Ces capacités ne changent ni matching, ni définition SOLD, ni identité, ni économie. Les logs naturels sur `a7666...` montrent toujours des erreurs/navigation timeouts eBay ; le problème provider reste séparé de #247. L'investigation eBay reste read-only et sans contournement anti-bot/WAF.

## #237 — rollover du registre Main Scanner — `MAIN_SUPPORT`

Issue #1 a atteint la limite GitHub de commentaires et reste archive. Le workflow actif écrit désormais les métadonnées minimales dans l'issue #235. Aucun comportement scanner économique n'a changé.

## #216/#217 — TCGdex transport/run resilience — `PROD_V4`

2 tentatives max ; retry Timeout/ConnectionError/502/503/504 ; breaker après 2 appels logiques épuisés ; erreurs restent `ERROR`/fail-closed ; vraie réponse reset ; nouveau process circuit fermé.

## #222/#224 — TCGdex source-pinned outage fallback — `PROD_V4`

Fallback seulement après `ERROR` transport retryable avec japonais + alias set reviewé + numéro/denominator exact + source TCGdex immuable `af33c9ac...` + exact set/localId + finish admis. `NO_MATCH`, `AMBIGUOUS`, non-Japonais ou preuve incomplète restent bloqués.

## #214 — débit `EXTERNAL_PENDING` — `PROD_V4`

```text
P4 scheduling                    16/run
P4 hard ceiling                  20/run
eBay SOLD total                  16/run
fixed eBay reserve               12/run
auction eBay max                 4/run
budget-only cooldown             5 min
PSA APR max                      2/run
provider-error backoff           inchangé
```

Provider failures restent fail-visible et ne deviennent jamais clean no-match. Ne pas augmenter les caps uniquement pour forcer le drainage.

## TCGdex / PokeTrace #119→#135 — `PROD_V4`

Exact-coordinate, set/localId, unicité catalogue, bridges exacts, finish/set source-pinnés et fallback générique catalogue immuable lorsque le REST TCGdex est stale ; PokeTrace market-only après identité TCGdex. #247 ajoute uniquement un guard de qualité sur la forme de l'agrégat de prix après cette identité exacte. Aucun alias treadmill. PR #126 = `SUPERSEDED` par #127→#135.

---

# Global Multi-Vault

#139 a réintégré/revalidé le stack historique #108/#109/#110/#113/#114/#115/#138. Surface : GCC/Cardova/Magi/Fanatics/COMC → identité commerciale exacte → TCGdex exact + microvariante → SOLD exact optionnel → PPT/PokeTrace graded aggregate → décision.

- disappearance != SOLD ;
- ACTIVE_AUCTION non actionnable ;
- PPT/PokeTrace/eBay corrélés `EBAY_GRADED_AGGREGATE` ;
- PPT = `SOLD_AGGREGATED`, jamais item-level SOLD ;
- aucune transaction.

Scale courant : 50 listings/run, PPT 35 HTTP / 180 credits / floor 15000, PokeTrace 60, cadence 20 min (`1,21,41`), inner timeout 17 min, job timeout 25 min. #179 apporte le watchdog borné sans seconde lane économique.

---

# Magi — `PROD_V4`

#174 + #177 = identité native déterministe ; #178 = recovery total 36, broad/nonpriority max 28, réserve exact search/detail 8. Pas de name-only/alias carte-par-carte.

---

# Robot KB — `ROBOT_KB`

PostgreSQL local Mac actif, `V4_USE=false`, Neon writers automatiques OFF. Append-only daté ; SOLD final prouvé prioritaire ; ASK/live/disparition/WAITING_FOR_PAYMENT != vente.

#180 collecte Fanatics/COMC/Magi/Cardova + PokeTrace/PPT en conservant les sémantiques ; `SOLD_AGGREGATED` != item-level SOLD et `FIXED_ASK_AGGREGATED` reste ASK.

#207 est `P3_ONLY` et n'a exécuté aucune migration durable utilisateur. #210 reste OPEN/DRAFT ; aucun durable write Cardova sans autorisation explicite.

---

# V5 / non-production

PR #8 = **`V5_ONLY`**, OPEN/DRAFT/NON-MERGED. Ne jamais merger PR #8 dans `main` sans autorisation explicite.

---

# Supersessions / provenance

- #54 : stale/superseded ;
- #111 : ancien snapshot docs ;
- #126 : `SUPERSEDED` par #127→#135 ;
- #108/#109/#110/#113/#114/#115/#138 : absorbées par #139 ;
- #141 : superseded par #142/#140 ;
- #159 : superseded fonctionnellement par #177 ;
- #211/#212 : une capacité runtime ;
- #216/#217 : une capacité runtime, #217 mirror ;
- #222/#224 : une capacité runtime, #224 mirror ;
- #229/#231 : une capacité runtime ;
- #238/#239 : une capacité eBay runtime, #239 mirror ;
- #243 complète #220 sur le bypass Main Scanner ;
- #245 complète #229/#231 et #243 sur la préservation du default de pagination ;
- #247 complète la lignée PokeTrace en bloquant les agrégats STRONG sans dispersion informative ;
- #234 : diagnostic benchmark read-only inconclusif, ne pas traiter comme preuve de performance.

---

# Invariants de reprise

- V4/main canonique ;
- PR #8 protégée ;
- aucun achat/bid/checkout/paiement ;
- Robot KB local séparé de V4 ;
- aucune écriture durable Cardova sans autorisation explicite ;
- identité ambiguë/microvariante incertaine = fail-closed ;
- ASK, enchère live et disparition != SOLD ;
- avant nouveau code, réutiliser d'abord les capacités recensées ici et dans le README.
