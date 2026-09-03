# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **3 septembre 2026** après le merge production #245. Le code/Git/GitHub live reste l'autorité ; re-vérifier le HEAD avant toute action importante.

## Autorité

```text
V4 production branch             main
V4 production HEAD               a39c693d629b003f69f66ba20753303b197737af / #245 MERGED
#245 validated head              c553796d8829e5f6dd615acfc7177ddb60f4bf91
#245 validation run              33796972288 SUCCESS / 898 PASS / 2 skipped
V4 run registry                  issue #235 ACTIVE / issue #1 archive / #237 MERGED
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

### Correctif

#245 rend le wrapper transparent quand `page_size` / `max_pages` ne sont pas explicitement fournis. Les overrides explicites restent respectés. **Le hard ceiling 250 pages n'est pas augmenté.**

Validation exacte :

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

### Post-merge

```text
Fast Lane                        33798827669 SUCCESS / a39c693d...
Fast Lane                        33799115189 SUCCESS / a39c693d...
Main Scanner 33798768727         SUCCESS mais ancien SHA a93cd862... / NE COMPTE PAS
Main Scanner exact a39c693d...   PENDING au dernier contrôle
```

Ne jamais présenter `33798768727` comme preuve post-#245 : il avait démarré avant le merge.

## Phase précédente #243 — guard future-start

#243 ferme le bypass où une row API avec `minutes_to_end` pouvait éviter la vérification de la fiche GCC rendue. Une auction sans preuve structurée de démarrage est désormais vérifiée avant toute économie : upcoming explicite => exclusion ; page ambiguë/erreur => fail-closed ; live rendu exige une sémantique de bid + fin explicite.

Incident déclencheur : Braixen #069/068 PSA 9 et Altaria #194/172 PSA 10 avaient été interprétées comme enchères live alors que GCC affichait un starting price et un countdown-to-start.

Validation #243 : `33794118816` SUCCESS, `896 PASS / 2 skipped`, compile/YAML/diff/live compare PASS, merge runtime `3ada7785d3fbef8050a7712bc773a52fd569716d`.

## eBay — état actuel

#238/#239 a réduit la lecture DOM à un bulk `all_inner_texts()` avec fallback historique ; #242 conserve un résultat validé avant teardown Chromium bloqué. Ces changements sont non-régressifs mais **ne prouvent pas la disparition des hard timeouts eBay**.

Le prochain travail eBay reste un diagnostic borné/read-only des phases worker : navigation, challenge/provider page, row count, extraction, parsing et teardown. Aucun contournement anti-bot/WAF et aucune relaxation matching/SOLD/économie.

## Invariants inchangés

- #211/#212 + #229/#231 + #245 restent l'autorité discovery/recovery auction ;
- hard ceiling recovery = `250`, pas de hausse opportuniste ;
- cap économique auction `360` et priorité `≤5m` → `≤12m` → `≤60m` inchangés ;
- #220/#243 future-start reste actif ;
- TCGdex #216/#217 + #222/#224 restent stricts/fail-closed ;
- eBay/PSA/provider errors restent fail-visible ;
- `EXTERNAL_PENDING` ne doit pas être forcé par hausse opportuniste de caps ;
- identité/grade/langue/microvariante incompatibles ne sont jamais mélangés ;
- ASK/current auction/disappearance != SOLD ;
- Robot KB reste séparé ; aucun durable write Cardova sans autorisation explicite ;
- PR #8 / V5 reste expérimentale et non mergée ;
- aucun achat, bid, checkout ou paiement automatique.

## Prochaine étape

1. Attendre le premier **Main Scanner naturel exact `a39c693d...`** ; aucun dispatch manuel uniquement pour fabriquer une preuve.
2. Vérifier dans issue #235 : `scan_exit_code=0`, scope auction, rows/timers, `auction_fallback_used` et, si order drift, absence de nouveau hit artificiel du plafond 250.
3. Si le même échec `250 pages reached` réapparaît sur `a39c693d...`, inspecter les logs avant toute autre modification ; ne pas augmenter le hard cap par réflexe.
4. Fermer ensuite le handoff docs #245 avec la preuve naturelle exacte.
5. Reprendre séparément l'investigation eBay stage-timed.
6. Garder Robot KB/Cardova durable et V5 strictement séparés.
