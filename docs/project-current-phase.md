# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **4 septembre 2026** après les merges production #245 et #247 et leurs premières preuves naturelles Main Scanner. Le code/Git/GitHub live reste l'autorité ; re-vérifier le HEAD avant toute action importante.

## Autorité

```text
V4 production branch             main
V4 production HEAD               a7666faf4b0ef2fab74295a45ebcf75d9832f284 / #247 MERGED
#247 validated head              03ce93ae08eedf3301813f030b67f120b7abd4a4
#247 validation run              33799908680 SUCCESS
#247 Main Scanner post-merge      33844655319 SUCCESS / exact a7666faf...
#245 production merge            a39c693d629b003f69f66ba20753303b197737af
#245 validated head              c553796d8829e5f6dd615acfc7177ddb60f4bf91
#245 validation run              33796972288 SUCCESS / 898 PASS / 2 skipped
#245 Main Scanner post-merge      33799767652 SUCCESS / exact a39c693d...
V4 run registry                  issue #235 ACTIVE / issue #1 archive / #237 MERGED
PokeTrace aggregate guard        #247 MERGED / degenerate STRONG -> WEAK/INSUFFICIENT
Auction pagination preservation  #245 MERGED / stable default 100 rows/page preserved
Auction recovery capacity        #229/#231 MERGED / adaptive sizing / hard cap 250
Auction order hardening          #211/#212 MERGED
Future-start auction guard       #220 + #243 MERGED / validated head 20e1a12e35464840952cdb9079e6063f014e3bef
eBay bulk text                   #238/#239 MERGED / validated head 90741ac0eaca42f90a6bc7fca816d347aaccafeb
eBay result before teardown      #242 MERGED / validated head 7c97d73a9caf93871d918a8dabc5a7be72375697
TCGdex transport resilience      #216/#217 MERGED / 03824158ac899cf142199c42d4525386a573bc15
TCGdex outage fallback           #222/#224 MERGED / 0be4dca95513e36f4e407ef7bac361fe488c1d36
V5                               PR #8 / OPEN / DRAFT / NON MERGED
Robot KB durable                 PostgreSQL local Mac / séparé de V4 / V4_USE=false
Neon                             writers automatiques OFF / rollback manuel
```

## Phase runtime #247 — qualité des agrégats PokeTrace

### Problème

Une surface PokeTrace eBay gradée agrégée pouvait produire une enveloppe sans dispersion informative, par exemple `124.83–124.83 EUR / PSA 9 / 29 ventes`. Une telle forme ne prouve pas une distribution de marché et ne doit pas devenir seule une ancre `STRONG` / `EXTERNAL_RESCUE`.

### Correctif

#247 installe un guard dans le bootstrap V4 avant le runner canonique. Pour une preuve PokeTrace `MATCHED + STRONG` :

```text
prix invalide / non positif      -> CLEAN_INSUFFICIENT / WEAK
range total <= 0.01 EUR          -> CLEAN_INSUFFICIENT / WEAK
estimate économique              -> retiré
suite                             -> fallback PSA APR / eBay requis
range réellement informatif      -> comportement historique conservé
```

Aucune définition SOLD, identité, langue, grader, grade, microvariante, discovery GCC, seuil de décote, cap ou budget n'est relâché.

Validation exacte :

```text
base                             a39c693d629b003f69f66ba20753303b197737af
validated head                   03ce93ae08eedf3301813f030b67f120b7abd4a4
validation run                   33799908680 SUCCESS
suite V4                         PASS
compile / YAML / diff-check      PASS
focused aggregate guard tests    PASS
read-only auction compare        PASS
production merge                 a7666faf4b0ef2fab74295a45ebcf75d9832f284
```

### Preuve naturelle post-merge

Premier Main Scanner exact :

```text
run                              33844655319
head                             a7666faf4b0ef2fab74295a45ebcf75d9832f284
workflow                         SUCCESS
scan_exit_code                   0
duration                         175 s
final opportunities              0
fixed discovery                  3259 / 33 pages / COMPLETE
auction scope                    COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
auction rows / timers            100 / 100
auction fallback                 false
PokeTrace attempted              1
PokeTrace strong / weak / errors 0 / 0 / 0
```

**Limite de preuve :** ce run n'a pas rencontré un nouvel agrégat PokeTrace dégénéré STRONG. Il prouve le déploiement et la non-régression du runtime ; le déclenchement positif du guard est prouvé par les tests ciblés #247. Plusieurs Main Scanner naturels suivants sur `a7666...` sont également SUCCESS, discovery auction complète et fallback `false`.

Ledger : `docs/v4-poketrace-aggregate-quality-guard-20260904.md`.

## Phase runtime #245 — préserver le default de pagination durci

### Incident naturel pré-fix

Run `33795854886` sur `main@a93cd862...` :

```text
ENDING_SOON order drift          YES
provider count hint              16264
recovery capacity                100 -> 250 pages
failure                          auction API safety limit 250 pages reached
result                           fail-closed vers legacy fallback
```

### Cause exacte

Le wrapper future-start introduit par la lignée #220/#243 transmettait implicitement `page_size=24` même lorsque son caller n'avait demandé aucun override. La couche `v4_auction_pagination_stability` est volontairement durcie avec un default de **100 rows/page**.

Pour ~16.2k rows, `100/page` nécessite environ 163 pages alors que `24/page` en nécessite environ 678. Le plafond 250 était donc atteint artificiellement.

### Correctif et validation

#245 rend le wrapper transparent quand `page_size` / `max_pages` ne sont pas explicitement fournis. Les overrides explicites restent respectés. **Le hard ceiling 250 pages n'est pas augmenté.**

```text
base                             a93cd8628b7ff8648d88b84f86a87406fb3ba7fd
validated head                   c553796d8829e5f6dd615acfc7177ddb60f4bf91
validation run                   33796972288 SUCCESS
V4 suite                         898 PASS / 2 skipped
compile / YAML / diff-check      PASS
focused pagination tests         PASS
read-only live auction compare   PASS
effective / legacy               36 / 32
legacy_only / unresolved         0 / 0
production merge                 a39c693d629b003f69f66ba20753303b197737af
```

Premier Main Scanner exact post-merge `33799767652` : SUCCESS, `100/100` auction rows/timers, scope COMPLETE, fallback false, API page size 100. Ce run prouve le fast path normal ; la preuve du chemin pathologique reste la reproduction pré-fix `33795854886` + le test ciblé #245.

Ledger : `docs/v4-auction-pagination-default-preservation-20260903.md`.

## Future-start #243

#243 ferme le bypass où une row API avec `minutes_to_end` pouvait éviter la vérification de la fiche GCC rendue. Sans preuve structurée de démarrage, la fiche est vérifiée avant toute économie : upcoming explicite => exclusion ; page ambiguë/erreur => fail-closed ; live rendu exige sémantique de bid + fin explicite.

Incident déclencheur : Braixen #069/068 PSA 9 et Altaria #194/172 PSA 10 interprétées auparavant comme live alors que GCC affichait un starting price et un countdown-to-start. Validation `33794118816` SUCCESS, `896 PASS / 2 skipped`, merge runtime `3ada7785d3fbef8050a7712bc773a52fd569716d`.

## eBay / PSA — état actuel

#238/#239 réduit la lecture DOM via `all_inner_texts()` ; #242 conserve un résultat validé avant teardown Chromium bloqué. Les logs #247 montrent toujours des erreurs eBay et PSA APR HTTP 403 : ces problèmes provider restent séparés du guard PokeTrace et ne doivent pas être masqués par une hausse de caps.

Le prochain travail eBay reste un diagnostic borné/read-only des phases worker. Aucun contournement anti-bot/WAF et aucune relaxation matching/SOLD/économie.

## Invariants inchangés

- #247 ne transforme aucune ASK/enchère courante en SOLD ;
- #211/#212 + #229/#231 + #245 restent l'autorité discovery/recovery auction ;
- hard ceiling recovery = `250`, pas de hausse opportuniste ;
- cap économique auction `360` et priorité `≤5m` → `≤12m` → `≤60m` inchangés ;
- #220/#243 future-start reste actif ;
- TCGdex #216/#217 + #222/#224 restent stricts/fail-closed ;
- eBay/PSA/provider errors restent fail-visible ;
- `EXTERNAL_PENDING` ne doit pas être forcé par hausse opportuniste de caps ;
- identité/grade/langue/microvariante incompatibles ne sont jamais mélangés ;
- Robot KB reste séparé ; aucun durable write Cardova sans autorisation explicite ;
- PR #8 / V5 reste expérimentale et non mergée ;
- aucun achat, bid, checkout ou paiement automatique.

## Prochaine étape

1. Fermer le closeout docs #246 après nouvelle validation docs-only sur l'état `main@a7666...` et autorisation explicite de merge.
2. Continuer d'observer naturellement le premier cas où le guard PokeTrace #247 se déclenche ; ne pas fabriquer un live positif par dispatch manuel.
3. Continuer d'observer la pagination auction ; si `250 pages reached` réapparaît, inspecter avant toute modification et ne pas relever le hard cap par réflexe.
4. Reprendre séparément l'investigation eBay stage-timed/read-only.
5. Garder Robot KB/Cardova durable et V5 strictement séparés.
