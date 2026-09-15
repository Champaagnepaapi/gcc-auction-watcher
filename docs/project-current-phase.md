# Robot Pokémon / GCC Auction Watcher — phase courante

## État canonique — 15 septembre 2026

Production V4 : `main@3c596370ee7fcde93c969139541bc003e7012b6e`, merge de la PR #268.

Runtime multi-market de référence avant merge : `29f448a7441e82267fc9d84c2b0f9a52168e77cb`.
Premier cycle naturel post-merge confirmé : Main Scanner `34886292095` **SUCCESS** sur `main@3c596370...`.
Rapport multi-market détaillé : [`v4-multimarket-readiness-20260914.md`](v4-multimarket-readiness-20260914.md).

PR #8/V5 reste **OPEN / DRAFT / NON MERGED**, head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f`, séparée de V4. Robot KB reste séparé de la décision commerciale V4 (`V4_USE=false`). Neon reste hors du chemin de production automatique.

## Classement multi-market actuel

| Marketplace | État | Résiduel principal |
|---|---|---|
| GCC | **OPERATIONAL** | Chemin vault observé : découverte → identité exacte → valorisation indépendante → coût → décision. |
| Fanatics | **PROVIDER_BLOCKED** | Coût acheteur final non prouvé ; Shining Mewtwo reste matériellement ambigu côté valorisation. Litten peut avoir une preuve variante plus forte, mais cela ne lève pas le blocage coût. |
| COMC | **PROVIDER_BLOCKED** | Historique SOLD public anonyme bloqué par HTTP 403 ; coût Store Credits/taxe/détention-livraison non prouvé. |
| Magi | **PROVIDER_BLOCKED** | Route/coût acheteur non prouvés ; certaines valeurs gradées exactes restent absentes. |
| Cardova | **PROVIDER_BLOCKED** | Financement/paiement et premium Auction applicables non prouvés ; aucune valeur indépendante exacte dans la sélection validée. |
| Mercari | **PROVIDER_BLOCKED** | Preuves item langue/numéro/grade/matériau insuffisantes ou contradictoires ; route et coût acheteur absents. |
| SNKRDUNK | **PROVIDER_BLOCKED** | Les pages publiques répondent, mais les fiches observées ne prouvent pas ensemble catégorie item, langue, grade PSA et offre individuelle exploitable ; route/coût acheteur absents. |

`PROVIDER_BLOCKED` décrit le chemin économique autonome dans les conditions publiques auditées. Cela ne signifie pas que le site est inaccessible. Pagination partielle, caps volontaires et budgets bornés restent des limites logicielles séparées.

## #268 en production

#268 a mis en production le hardening Global multi-market :

- gates d'identité TCGdex/microvariantes fail-closed ;
- PriceCharting/PPT derrière une identité canonique stricte ;
- wrappers Fanatics idempotents ;
- pagination Cardova liée à la bonne lane/enveloppe/page ;
- discovery COMC autonome ;
- Mercari/SNKRDUNK read-only intégrés à Global ;
- coûts inconnus conservés inconnus ;
- panne/budget/403 provider jamais converti en `NO_MATCH` propre ;
- états Auction `RESOLVED`, `ENDED`, `UNKNOWN`, `INSPECTION_ERROR`, `OUT_OF_SCOPE` séparés de SOLD.

Validation de référence #268 : Global `34812934273`, Auction `34812934319`, Cardova `34812934329` **SUCCESS** ; suites de tests, compilation, YAML et diff-check PASS ; zéro achat/bid/checkout/paiement.

## Post-merge réellement observé

Main Scanner `34886292095` sur `main@3c596370...` : **SUCCESS**.

- découverte GCC complète dans le scope production filtré ;
- TCGdex sans erreur transport sur ce run ;
- `EXTERNAL_PENDING_BACKLOG=2320`, first-evaluation coverage complète mais couverture marché externe incomplète ;
- PSA APR : HTTP 403, breaker run-local ;
- PriceCharting public : HTTP 403 / indisponible ;
- eBay SOLD : 0 tentative sur ce run ;
- aucun vrai cas future-start prouvé observé ;
- PokeTrace se déclare encore `effective_plan=PRO` sur les entrypoints production.

Ce dernier point est un défaut réel post-#268 : la validation #268 imposait le plafond FREE, mais pas les deux entrypoints de production.

## PR #271 — correction PokeTrace FREE — prête, NON MERGÉE

PR #271 : `fix/v4-poketrace-free-ceiling-production-20260914`, head `75eb09768bf55d002466c5e3d50b038c3884ceb5`.

Elle impose le plafond FREE dans Main Scanner et Global avant import provider, tout en conservant la possibilité d'un futur opt-in explicite. Elle ne modifie ni identité, ni budget, ni seuil économique, ni sémantique SOLD/ASK.

Validations du head #271 :

- Global `34879803090` : **SUCCESS** ;
- Auction `34879802895` : **SUCCESS** ;
- Cardova `34879802823` : **SUCCESS**.

#271 reste **OPEN / DRAFT / NON MERGÉE** et nécessite une autorisation explicite avant merge.

## PR #273 — diagnostic Fanatics — terminé, NON DESTINÉE AU MERGE

PR #273 : `diag/v4-fanatics-ppt-variant-proof-20260914`, head `c31882e8adacff8c291a43e78eb8ab6712ff2359`.

- tests ciblés, compilation et diff-check : PASS ;
- workflow diagnostic `34886340368` : **SUCCESS**, lecture seule et aucune mutation runtime ;
- le probe cible n'a pas forcé PPT : `daily_remaining=55` était sous le plancher de sécurité `15000`, donc le budget s'est arrêté proprement ;
- aucun abaissement de ce plancher n'est recommandé.

Les preuves #268 restent suffisantes pour le classement : Shining Mewtwo est EXACT mais expose deux variantes matérielles applicables et doit rester bloqué ; Litten est EXACT avec une variante TCGdex applicable, mais Fanatics reste de toute façon bloqué par l'absence de coût acheteur final prouvé.

Conclusion : **Fanatics reste PROVIDER_BLOCKED** ; aucune relaxation d'identité et aucun changement V4 supplémentaire ne sont justifiés sur cette base.

## Invariants

- SOLD exact récent > SOLD exact ancien ajusté > fixed ASK compatible > snapshot auction ≤5 min si aucun SOLD ;
- ASK / annonce active / enchère live / disparition / ENDED / OUT_OF_SCOPE ≠ SOLD ;
- une marketplace où la carte est achetable ne prouve jamais seule sa fair value ;
- panne provider ≠ preuve négative de marché ;
- aucune relaxation langue/grader/grade/set/numéro/microvariante ;
- identité ambiguë = blocage ou revue manuelle ;
- aucun achat, bid, checkout, paiement ou grading automatique ;
- aucun contournement WAF/anti-bot ;
- ne pas relever les caps uniquement pour vider un backlog ;
- PR #8/V5, Robot KB/P3 et Neon restent séparés de V4.

## Prochaine action canonique

1. ne pas investir dans des corrections de parsing provider qui ne lèvent pas le blocage économique réel ;
2. conserver GCC **OPERATIONAL** et les six autres providers **PROVIDER_BLOCKED** jusqu'à preuve externe propre de déblocage ;
3. priorité production immédiate : décider explicitement du merge de #271 ;
4. après tout merge production autorisé, observer un run naturel avant nouveau closeout ;
5. fermer/archiver les diagnostics seulement avec housekeeping explicite, sans suppression de branche.
