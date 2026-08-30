# Robot Pokémon / GCC Auction Watcher — capability ledger

Snapshot re-vérifié le **30 août 2026**. Le code/Git/GitHub live reste prioritaire. Ce ledger sert d'index anti-réimplémentation et de registre des capacités/supersessions.

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
Cardova collector runtime pin    a2f1878186a8850d5a4c4763518a10ecfd16f2fc
Cardova identity research head   59d006fc7259198f13d957b412bc48e4911c067f
Cardova SALES unresolved         244 disponibles
Cardova macro exact              38 read-only
Cardova finish exact             38
Cardova printing exact           5 No Rarity Symbol
Cardova microvariant exact       0
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

Live DB read-only au 30 août : **244 `SALE_TRANSACTION` Cardova unresolved disponibles**.

### Macro identity compose — `ROBOT_KB / READ_ONLY`

`robot_kb_cardova_bounded_macro_identity_probe.py` compose les capacités existantes au lieu de créer un nouveau resolver :

1. cohorte Cardova name↔dexId exact-gated ;
2. set Cardova indépendamment corroboré ;
3. une seule carte TCGdex pour le dexId dans ce set ;
4. source TCGdex Asian immuable pinnée `af33c9ac882e2acfadffaf19e8083aa976d12983`.

Live :

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

`robot_kb_cardova_legacy_macro_finish_probe.py` est la capacité canonique réutilisée pour ce sous-ensemble : source finish unique et/ou claim Holo corroboré. Live : **38/38 finish exact**.

`FA`, `SR`, `Holo Shiny` et tokens opaques ne deviennent jamais finish ou microvariante exacts par eux-mêmes.

### No Rarity reviewed fallback — `ROBOT_KB / BOUNDED_READ_ONLY`

PSA direct HTML/API/cert = 403 ; aucun bypass.

`robot_kb_cardova_no_rarity_reviewed_fallback.py` est strictement borné à cinq coordonnées Basic dont Cardova porte le token exact `no rarity original print` et dont une preuve publique PSA a été revue :

```text
Sandshrew #027
Nidorino  #033
Arcanine  #059
Machop    #066
Gastly    #092
```

Live : 5/5 `printing=no_rarity_symbol`, finish `normal`, mais `edition_exact=false`, `no_rarity_is_first_edition=false`, `microvariant_exact=0`, links=0. Le cert Cardova n'a pas été lu : `reviewed_no_rarity_cardova_cert_read=false`.

**Ne jamais étendre automatiquement ce manifest à une autre coordonnée.** Une nouvelle coordonnée exige une nouvelle preuve revue.

### Validation #199 identity phase

Head fonctionnel/research : `59d006fc7259198f13d957b412bc48e4911c067f`.

```text
Robot KB CI                      33333404769 SUCCESS
V4 Auction Discovery             33333404817 SUCCESS
V4 Global Market Offline         33333404767 encore en cours au handoff
bounded macro tests              5/5 PASS
legacy macro/finish tests        18/18 PASS
No Rarity fallback tests         7/7 PASS
compile/YAML/diff-check          PASS dans Robot KB CI
live Mac read-only               SUCCESS
```

Live Mac : `unresolved=244`, `selected=244`, `macro_exact=38`, `finish_exact=38`, `printing_exact=5`, `micro_exact=0`, `links=0`, `blocked={}`, `error=null`.

Recurring collector architecture reste séparée : front pages + rotation historique, idempotence P3, state only after commit, DB loopback, readiness retry 5000→6500→8000 ms, lock séparé. Runtime collector pin `a2f1878186a8850d5a4c4763518a10ecfd16f2fc`.

Le dernier cursor collector documenté était page 13 mais n'a pas été re-audité pendant la phase identity ; ne pas l'inférer à partir du total 244.

#199 reste OPEN/DRAFT/NON MERGED. Ne pas merger sans décision explicite.

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
- #8 protégé V5, non mergé.

`SHADOW`, `DEFERRED`, `DISABLED`, `V5_ONLY` et `SUPERSEDED` ne signifient jamais production active par eux-mêmes.

Issues particulières : #1 registre V4 vivant ; #150 registre Global vivant ; #28 spec historique livrée ; #58 planning Robot KB historique largement livré, ne pas traiter comme backlog neuf.

---

# Règles de reprise

Avant implémentation non triviale : lire README + gouvernance + ce ledger + inventaires, rechercher une capacité antérieure, suivre les supersessions, isoler V4/V5/Robot KB, utiliser SHA précis, tests ciblés + suite pertinente, compile/YAML/diff-check, live read-only lorsque pertinent, puis documenter la phase.

Prochaine capacité à travailler sur #199 : **fermeture déterministe des axes `edition`, `special_finish`, `variant` réellement applicables aux 38 macros**, en réutilisant `variant_surface_probe` et `variant_corroboration_probe`. Pas de canonical link tant que la fermeture microvariante n'est pas complète.

Aucun achat, bid, offer, checkout ou paiement automatique.
