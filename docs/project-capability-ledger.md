# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot re-vérifié le **31 août 2026**. Le code/Git/GitHub live reste prioritaire. Ce ledger sert d'index anti-réimplémentation et de registre des capacités/supersessions.

## Autorité courante

```text
V4 production                    main @ b98756c449718845fc1944560fcf61c02586079f
V4 auction priority/cap          #188 MERGED
PSA/eBay breakers                #189 MERGED
eBay completed shadow            #191 MERGED
Auction safety-net ledger        #201 MERGED
Weekly stability budget          #203 MERGED
Global marketplace-first         #139/#145/#146/#147/#148
Global scale/cadence             #156/#169/#179
Robot KB local cutover           #166 / PostgreSQL Mac ACTIF
Robot KB multisource             #180 MERGED / LaunchAgents installés
Cardova paid SOLD                #199 OPEN/DRAFT / local ACTIF / NON MERGED
Cardova identity proof           #204 OPEN/DRAFT / NON MERGED
Cardova exact SOLD dry-run       #205 OPEN/DRAFT / NON MERGED
Cardova collector runtime pin    a2f1878186a8850d5a4c4763518a10ecfd16f2fc
Cardova identity baseline        37 / 38 exact sur cohort du 30 août
Cardova SALES unresolved         291 au live du 31 août
Cardova exact SOLD candidates    38 au live du 31 août
Cardova identity blockers        5 au live du 31 août
Cardova canonical links          0
Neon automatic writers           OFF / rollback manuel
V5                               PR #8 OPEN / DRAFT / NON MERGED
```

Statuts : `PROD_V4`, `GLOBAL_NOTIFY_ACTIVE`, `ROBOT_KB`, `SHADOW`, `V5_ONLY`, `DEFERRED`, `DISABLED`, `SUPERSEDED`, `STALE_OPEN`.

---

# V4 — `PROD_V4`

## GCC discovery / auctions

- fixed `/on-sale-items` ; auctions `AUCTION/ENDING_SOON/ON_SALE` ;
- horizon principal ≤60 min + safety-net legacy ;
- #188 : priorité ≤5, puis ≤12, puis reste ≤60 ; cap 360 ;
- #201 : safety-net ledger sans statuts terminaux contradictoires/dupliqués ;
- #203 : budget de stabilisation hebdomadaire borné 5 passes, fail-closed inchangé ;
- Main Scanner et Fast Lane gardent leurs cadences externes ; pas de cron GitHub parallèle.

Capacités structurantes : #9, #50, #52, #104. Elles restent la fondation historique de discovery/couverture et ne doivent pas être réimplémentées parallèlement.

## Arbitrage multi-marché

- identité exacte avant valorisation ;
- GCC SOLD exact si disponible ;
- PokeTrace/PPT graded aggregate ;
- PSA APR/eBay exact seulement quand prouvés ;
- RAW Cardmarket/TCGplayer secondaire/manual-review ;
- #189 : breakers PSA 403/429 et eBay hard-timeout ;
- #191 : eBay completed-item shadow = candidate, jamais item-level SOLD prouvé automatiquement.

## TCGdex / PokeTrace #119→#135

Lignée #119→#135 : coordinate, padding, set/localId, unicité catalogue, bridges provider exacts, source-pin et fallback générique catalogue immuable. PokeTrace reste marché/prix après identité TCGdex exacte. #154 ajoute `variants_detailed` après identité exacte. Aucun fuzzy comme preuve exacte.

PR #126 = `SUPERSEDED` par #127→#135.

---

# Global Multi-Vault — `GLOBAL_NOTIFY_ACTIVE`

Surface canonique : **GCC/Cardova/magi/Fanatics/COMC**.

## #139 — réintégration

#139 réintègre le stack historique #108→#115 ; #145/#146 ajoutent notification + activation ; #147/#148 basculent en marketplace-first ; #151 ajoute le registre issue #150 ; #156 fournit le batch 50 ; #169 protège cadence/timeout ; #179 ajoute le watchdog schedule.

Gate : identité exacte + listing actionnable + externe gradé suffisamment fort + conflit matériel bloquant. ASK/current auction/disappearance != SOLD. Aucune transaction.

Ancien stack #108/#109/#110/#113/#114/#115/#138 = superseded/absorbé par #139.

---

# Magi native identity — `PROD_V4`

#174 + #177 : récupération déterministe native JP. #178 protège le budget sans augmenter le plafond : total 36, broad/nonpriority 28, réserve stricte 8. Cas non prouvés restent bloqués ; pas d'alias carte-par-carte.

---

# Robot KB — `ROBOT_KB`

Contrat : append-only, provenance + payload brut, observations datées, final SOLD prioritaire, fixed baseline/changements, snapshot auction ≤5 min uniquement fallback clairement identifié.

Cutover #166 : PostgreSQL local Mac actif ; migration Neon vérifiée 1,087,015 lignes / 35 tables / `MIGRATION_VERIFIED`. Neon automatic writers retirés ; rollback manuel seulement.

**Robot KB mirror/collectors séparés** : les collectors historiques GCC, multisource et Cardova restent des lanes de stockage distinctes de la décision économique V4/Global. `V4_USE=false` tant qu'une activation explicite et suffisamment prouvée n'a pas été décidée.

Collectors locaux :

```text
fixed/auction                     :32
GCC SOLD fresh/backfill           :17 / :47
backup                            03:10
multisource public #180           toutes les 2 h à :05
PokeTrace/PPT #180                01:08 / 07:08 / 13:08 / 19:08
Cardova paid SOLD #199            02:23 / 08:23 / 14:23 / 20:23
```

#180 : Fanatics/COMC/Magi/Cardova public baseline+changes ; PokeTrace/PPT historiques agrégés. **PPT = `SOLD_AGGREGATED`**, jamais item-level SOLD ; `cardmarket_unsold` reste ASK.

## Cardova paid/completed SOLD — #199 `ROBOT_KB / DRAFT`

Provider gate : status paiement 5 + finished + non cancelled/relisted + JPY + final winning bid positif.

P3 semantics :

- `SALE_TRANSACTION` ;
- `sale_occurred_at = auction_end_at_utc` ;
- `HAMMER_PRICE` JPY ;
- payment completion timestamp/all-in non fabriqués ;
- unresolved identity conservée ;
- exact identity/V4 eligibility = false tant que la microvariante commerciale complète n'est pas prouvée.

Baseline read-only du 30 août : **244 `SALE_TRANSACTION` Cardova unresolved**. Live du 31 août : **291** ; le LaunchAgent continue donc de faire croître le dataset pendant les phases de preuve.

### Macro identity compose — `ROBOT_KB / READ_ONLY`

`robot_kb_cardova_bounded_macro_identity_probe.py` compose les capacités existantes au lieu de créer un nouveau resolver :

1. cohorte Cardova name↔dexId exact-gated ;
2. set Cardova indépendamment corroboré ;
3. une seule carte TCGdex pour le dexId dans ce set ;
4. source TCGdex Asian immuable pinnée `af33c9ac882e2acfadffaf19e8083aa976d12983`.

Baseline 30 août :

```text
Basic / PMCG1                    17
neo1                             10
Jungle / PMCG2                    6
Rocket / PMCG4                    5
TOTAL macro exact                38
provider numeric global claim    false
```

La preuve est row-scoped. **Ne jamais réimplémenter cela comme une règle globale `Cardova number = dexId`.**

### Finish compose — `ROBOT_KB / READ_ONLY`

`robot_kb_cardova_legacy_macro_finish_probe.py` reste la capacité canonique pour le finish. Baseline : **38/38 finish exact**.

`FA`, `SR`, `Holo Shiny` et tokens opaques ne deviennent jamais finish ou microvariante exacts par eux-mêmes.

### No Rarity reviewed + exact public title — `ROBOT_KB / BOUNDED_READ_ONLY`

PSA direct HTML/API/cert = 403 ; aucun bypass.

`robot_kb_cardova_no_rarity_reviewed_fallback.py` reste strictement borné aux cinq coordonnées Basic revues : Sandshrew #027, Nidorino #033, Arcanine #059, Machop #066, Gastly #092.

`robot_kb_cardova_public_title_printing_proof.py` ajoute une preuve positive exacte pour le Ninetales PSA 10 cert `141683514`, source `01KFFRJ8B4X9FG8YK90K4BNS1T`, dont le titre public porte exactement `No Rarity Original Print` sans suffixe matériel.

Le Charizard PSA 8 cert `156405344`, source `01KQHACBX20NBMGD9VZAPA6Z64`, porte `No Rarity Original Print Error(Strength)` et reste bloqué : `Error(Strength)` est une microvariante matérielle non résolue.

Total `printing_exact=no_rarity_symbol` : **6**. No Rarity n'implique jamais First Edition.

### Reviewed visible rarity symbol — #204 `ROBOT_KB / BOUNDED_READ_ONLY`

`robot_kb_cardova_reviewed_rarity_symbol_proof.py` contient un manifest de **10 lignes exactes**. Chaque entrée lie : source ULID + cert PSA + PMCG1/localId + carte/grade/finish + `image_a` + SHA-256 + symbole visible.

Source des images : la page Cardova expose `image_a`; son frontend construit `https://card-image.cardova.co.jp/<image_a>`. Les scans eux-mêmes ne sont pas stockés dans le repo.

Revue manuelle :

- rare/holo : `★` visible ;
- common/non-holo : `●` visible ;
- contrôle Ninetales No Rarity : aucun symbole à cet emplacement.

Cette preuve **exclut positivement** `printing=no_rarity_symbol`. Elle ne transforme jamais l'absence de texte Cardova en preuve et ne crée pas un champ synthétique `printing=standard`.

`robot_kb_cardova_rarity_symbol_microvariant_closure.py` ne promeut une ligne que lorsque la source TCGdex pinnée présente exactement deux variantes compatibles et identiques sauf l'axe No Rarity. Toute troisième variante, printing différent, token opaque ou divergence au-delà de printing reste fail-closed.

### Closure microvariant #204 — `ROBOT_KB / READ_ONLY`

Head code validé : `dcd64575e0fee27f0e9c9b99cdf49c9703c0394e`.

Tests ciblés : **25/25 PASS** (`7 + 7 + 11`).

Baseline Mac read-only du 30 août :

```text
initial microvariant exact        26
title No Rarity added              1
visible rarity symbol added       10
final microvariant exact          37 / 38
remaining unresolved               1
expected_37_of_38                 true
```

Unique blocker du cohort baseline : Charizard PSA 8 cert `156405344`, `Error(Strength)`, reason `CARDOVA_PUBLIC_TITLE_MATERIAL_TAIL_UNRESOLVED`.

Les 37 sont des **exact identity link candidates**, pas des writes : `canonical_links_written=0`, `robot_kb_write=false`, `sale_transaction_ready=false` dans cette phase, `V4_USE=false`.

### Exact SOLD candidate compose #205 — `ROBOT_KB / MEMORY_ONLY`

#205 réutilise deux capacités existantes au lieu de créer une seconde lane :

1. les identités commerciales exactes produites par #204 ;
2. `robot_kb_cardova_sale_transaction_dry_run.build_p3_sale` de #199 pour les sémantiques SOLD.

Le join est strict sur le même `source_native_record_id` et revalide carte/numéro/grader/grade ainsi que la langue lorsqu'elle est présente. Une identité non exacte, un duplicate source id ou tout rejet du contrat P3 reste bloqué.

Head code live : `f575a3444477cf81b0564e832f477bb2a64863b6`.

Validation :

```text
Robot KB CI                      33339319304 SUCCESS
V4 Auction Discovery             33339319292 SUCCESS
Cardova P3 dry-run tests         7/7 PASS
compile/YAML/diff-check          PASS
```

Live Mac read-only du 31 août sur les **291** SALES unresolved :

```text
exact identity rows               38
exact-card SOLD candidates        38
sale candidate blocked             0
distinct candidate source ids     38
HAMMER_PRICE JPY rows             38
all candidates memory-only       true
identity blockers                  5
```

Blockers visibles :

- Charizard `01KQHACBX20NBMGD9VZAPA6Z64` — `CARDOVA_PUBLIC_TITLE_MATERIAL_TAIL_UNRESOLVED`, `Error(Strength)` ;
- Rattata `01M07F9T9NKG76DFXGNY0NXWAY` — `PROVIDER_MATERIAL_TOKEN_UNRESOLVED` ;
- Machoke `01M07F9T93G9V1BVZ3X8NTGV89` — `PROVIDER_MATERIAL_TOKEN_UNRESOLVED` ;
- Machoke `01M07F9T4K90S1X1XCVHVRRKNH` — `PROVIDER_MATERIAL_TOKEN_UNRESOLVED` ;
- Magnemite `01M07F9T80P8EVTY9D0S1X132J` — `PROVIDER_MATERIAL_TOKEN_UNRESOLVED`.

Le Charizard est le blocker historique du cohort 38 ; les quatre autres sont apparus après le snapshot 244. Une identité exacte supplémentaire est aussi entrée dans le dataset, ce qui explique **38 exact SOLD candidates** au lieu du compteur historique 37.

Invariant durable :

```text
exact_card_sale_candidate_count == exact_identity_rows
sale_candidate_blocked == {}
distinct_candidate_source_ids == exact_card_sale_candidate_count
HAMMER_PRICE JPY rows == exact_card_sale_candidate_count
all candidates memory-only == true
```

Ne jamais hardcoder `expected_count == 37` sur le dataset global : la collecte est continue.

Cette phase ne fait **aucun** canonical link, Robot KB write exact, V4 economic use ou notification.

### Collecteur #199

Architecture récurrente inchangée : front pages + rotation historique, idempotence P3, state only after commit, DB loopback, readiness retry 5000→6500→8000 ms, lock séparé. Runtime collector pin `a2f1878186a8850d5a4c4763518a10ecfd16f2fc`.

Le dernier cursor collector documenté était page 13 mais n'a pas été re-audité pendant cette phase ; ne pas l'inférer à partir du total 291.

#199, #204 et #205 restent OPEN/DRAFT/NON MERGED. Ne pas merger sans décision explicite.

---

# V5 — `V5_ONLY`

PR #8 `agent/v5-poketrace-cardmarket-market-data`, head `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f` : expérimentale, draft, non mergée. TCGdex reste resolver principal ; PokeTrace marché/prix. **Ne jamais merger #8 sans autorisation explicite.**

#92/#96 = V5 child/shadow/deferred.

---

# Supersessions / historique

Les branches/PRs **historiques/superseded** restent de la provenance ; elles ne doivent pas être rejouées automatiquement.

- #54 stale/superseded ;
- #108/#109/#110/#113/#114/#115/#138 absorbées par #139 ;
- #111 ancien snapshot docs ;
- #126 superseded par #127→#135 ;
- #141 diagnostic superseded par #142/#140 ;
- #159 superseded fonctionnellement par #177 ;
- #174/#177/#178/#179/#180/#188/#189/#191/#201/#203 déjà mergées ;
- #87 décision produit V4 séparée, ne pas mélanger à un autre changement ;
- #199 actif/draft Robot KB, non mergé ;
- #204 actif/draft identity proof, non mergé ;
- #205 actif/draft exact SOLD dry-run, non mergé ;
- #8 protégé V5, non mergé.

`SHADOW`, `DEFERRED`, `DISABLED`, `V5_ONLY` et `SUPERSEDED` ne signifient jamais production active par eux-mêmes.

Issues particulières : #1 registre V4 vivant ; #150 registre Global vivant ; #28 spec historique livrée ; #58 planning Robot KB historique largement livré, ne pas traiter comme backlog neuf.

---

# Règles de reprise

Avant implémentation non triviale : lire README + gouvernance + ce ledger + inventaires, rechercher une capacité antérieure, suivre les supersessions, isoler V4/V5/Robot KB, utiliser SHA précis, tests ciblés + suite pertinente, compile/YAML/diff-check, live read-only lorsque pertinent, puis documenter la phase.

Prochaine capacité Cardova : **dry-run canonical-card link + exact-sale persistence**, en réutilisant les primitives Robot KB existantes, memory-only/rollback d'abord. Les cinq blockers identité du snapshot courant restent exclus. Aucun V4_USE pendant cette phase.

Aucun achat, bid, offer, checkout ou paiement automatique.
