# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot GitHub pertinent re-vérifié le **3 septembre 2026** après le merge #245 et la création du closeout docs #246. Le contrôle GitHub live reste l'autorité ; **ne pas utiliser ce document comme compteur exhaustif sans nouveau search live**.

> V4 production : `main@a39c693d629b003f69f66ba20753303b197737af`. #245 est **MERGED**. #246 est un closeout **DOCS ONLY / DRAFT** jusqu'à la preuve du premier Main Scanner naturel exact `a39c693d...`.

```text
V4 production                  a39c693d629b003f69f66ba20753303b197737af / #245
PR #246                        OPEN / DRAFT / DOCS ONLY / closeout #245
PR #245                        MERGED / auction pagination default preservation
PR #243/#244                   MERGED / future-start runtime + docs closeout
PR #242                        MERGED / eBay result-before-teardown
PR #238/#239                   MERGED / eBay bulk visible-text
PR #237                        MERGED / V4 registry rollover to issue #235
PR #234                        OPEN / DRAFT / VALIDATION ONLY / INCONCLUSIVE / DO NOT MERGE
PR #233                        OPEN / DRAFT / SUPERSEDED BY #238/#239
PR #230                        OPEN / DRAFT / VALIDATION ONLY / DO NOT MERGE
PR #226/#228                   OPEN historical eBay lineage / SUPERSEDED BY #238/#239
PR #8                          OPEN / DRAFT / NON MERGED
PR #210                        OPEN / DRAFT / durable write guard / NO EXECUTION AUTHORIZATION
```

## PR ouvertes pertinentes pour la gouvernance courante

### V4 courant / validation

| PR | Classification / instruction |
|---|---|
| #246 | `DOCS_ONLY / OPEN_DRAFT`. Closeout canonique de #245. Aucun runtime/workflow/économie/identité/provider/Robot KB/V5 change. Ne merger qu'après preuve naturelle post-merge et autorisation requise. |
| #234 | `VALIDATION_ONLY / OPEN_DRAFT / DO_NOT_MERGE`. Benchmark eBay public borné ; inconclusif car 0 `li.s-item` visible au runner. Ne pas utiliser comme preuve de performance. |
| #233 | `STALE_OPEN/SUPERSEDED` par #238/#239. Ancien port current-main du bulk eBay ; la capacité exacte est déjà en production. Ne pas merger. |
| #230 | `VALIDATION_ONLY / OPEN_DRAFT / DO_NOT_MERGE`. Validation temporaire de l'ancienne phase auction recovery ; la capacité est déjà en production via #231 puis complétée par #245. |
| #226 | `STALE_OPEN/SUPERSEDED` par #238/#239. Ancienne implémentation eBay bulk text. Ne pas merger automatiquement. |
| #228 | `STALE_OPEN/SUPERSEDED` par #238/#239. Ancien miroir de validation eBay. Ne pas merger. |
| #87 | **Décision produit V4 séparée/non déployée** : GCC-only illiquid notification 30 %. Ne pas mélanger à un autre changement. |

### Décision explicite / risque matériel

| PR | Classification / instruction |
|---|---|
| #210 | **`ROBOT_KB_DURABLE_WRITE_GUARD / EXPLICIT_AUTH_REQUIRED`**. Prépare un commit durable Cardova exact-sale avec backup/locks/double autorisation. Aucun commit durable exécuté. Ne pas merger/exécuter automatiquement. |
| #209 | `ROBOT_KB_ROLLBACK_REHEARSAL`. Preuve PostgreSQL réelle sous rollback ; durable state restauré. Ne pas traiter comme autorisation de write. |
| #208 | `ROBOT_KB_MEMORY_ONLY / P3_STACKED`. Exact-sale persistence avec #207 `print_run`, pas de durable write. |
| #206 | `ROBOT_KB_PRE_207_FAIL_CLOSED_PROOF`. Historique memory-only montrant le gap schema avant #207. |
| #205 | `ROBOT_KB_MEMORY_ONLY_SOLD_CANDIDATES`. Exact candidates, aucune persistance durable. |
| #204 | `ROBOT_KB_CARDOVA_MICROVARIANT_PROOF`. No Rarity / visible rarity-symbol proof bornée. |
| #199 | `ROBOT_KB_CARDOVA_SOLD_STACK_ROOT`. Cardova paid/completed SOLD collection + identity work ; reste draft/non-merged. |
| #193 | `ROBOT_KB_MANUAL_WRITE_PATH / STACKED`. Écriture manuelle corroborated eBay seulement après gates strictes ; ne pas merger indépendamment. |
| #195 | `ROBOT_KB_BATCH_STACKED`. Compose #193 + #194 ; ne pas merger indépendamment. |
| #8 | **`V5_ONLY / PROTECTED`**. OPEN/DRAFT/NON-MERGED. Ne jamais merger dans `main` sans autorisation explicite utilisateur. |

## Robot KB / marché — recherche ou shadow à revalider avant intégration

| PR | Classification / instruction |
|---|---|
| #198 | `ROBOT_KB_COMC_PUBLIC_HISTORY_DIAGNOSTIC`. Read-only ; ne pas fabriquer SOLD depuis Sold Out/chart. |
| #197 | `ROBOT_KB_FANATICS_PAID_HISTORY_DIAGNOSTIC`. PAID explicite requis ; currency non prouvée dans la phase documentée. |
| #196 | `ROBOT_KB_LOCAL_PSA_CORROBORATION`. Local Mac evidence only ; ne pas revivre en V4 GitHub Actions. |
| #194 | `ROBOT_KB_CANONICAL_BOOTSTRAP / STACKED`. Exact TCGdex canonicalization ; aucune market observation créée. |
| #192 | `ROBOT_KB_EBAY_BENCHMARK`. Read-only / corroboration stricte ; provider seul ne prouve pas SOLD. |
| #190 | `STALE_OPEN / DOCS_DIAGNOSTIC`. PSA cert 403 sur GitHub Actions ; ne pas contourner WAF. |
| #187 | `ROBOT_KB_PUBLIC_MARKET_RECOVERY`. Revalider current-main/supersession avant toute intégration. |

## V5 child/shadow

| PR | Classification / instruction |
|---|---|
| #92 | `V5 child/shadow/deferred`; PokemonPriceTracker shadow uniquement. Ne pas merger dans `main`. |
| #96 | `V5 child/deferred`; digital TCG Pocket reject + curated catalog gap. Ne pas merger dans `main`. |
| #8 | `V5 root experimental`; reste l'autorité de protection de la ligne V5. |

## Stale / superseded / historique — ne pas merger automatiquement

| PR | Classification / instruction |
|---|---|
| #176 | `STALE_OPEN / DOCS`. Ancien closeout eBay ; revalider avant merge. |
| #159 | `STALE_OPEN/SUPERSEDED` fonctionnellement par #177. |
| #141 | `SUPERSEDED_DIAGNOSTIC` par #142/#140. |
| #138 | `SUPERSEDED_BY_139`. |
| #126 | `STALE_OPEN/SUPERSEDED` par #127→#135. |
| #115/#114/#113/#110/#109/#108 | `SUPERSEDED_BY_139` / stack Global historique. |
| #111 | `STALE_OPEN/SUPERSEDED` docs. |
| #107 | `STALE_OPEN/SUPERSEDED` Japan Edge PPT display shadow. |
| #106 | `STALE_OPEN/SUPERSEDED` V4 PPT shadow. |
| #87 | **Décision produit V4 séparée/non déployée** ; pas de merge automatique. |
| #54 | `STALE_OPEN/SUPERSEDED`. |

## Merges récents retirés de la surface ouverte

- #245 : préservation du default de pagination auction durci **MERGED / PROD_V4** ; head validé `c553796d...`, production `a39c693d...` ;
- #243/#244 : future-start guard Main Scanner + closeout docs **MERGED** ; runtime `3ada7785...`, docs `a93cd862...` ;
- #242 : eBay result-before-teardown **MERGED / PROD_V4** ;
- #238/#239 : bulk visible-text eBay **MERGED / PROD_V4** ;
- #237 : rollover registre Main Scanner vers issue #235 **MERGED / MAIN_SUPPORT** ;
- #229/#231 : capacité recovery auction adaptative **MERGED / PROD_V4** ;
- #222/#224 : fallback TCGdex source-pinné sur panne transport **MERGED / PROD_V4** ;
- #216/#217 : résilience transport TCGdex Main-only **MERGED / PROD_V4** ;
- #220 : future-start GCC auction guard initial **MERGED / PROD_V4** ;
- #214 : throughput `EXTERNAL_PENDING` **MERGED** ;
- #211/#212 : auction order-drift hardening **MERGED** ;
- #178/#179/#180 : **MERGED**.

## Règles

- `open` ne veut pas dire `à merger` ;
- draft/non-draft ne vaut pas autorisation ;
- vérifier patch + ancestry + supersession avant toute décision ;
- ne jamais merger un child stacké directement si son parent n'est pas résolu ;
- ne jamais exécuter une migration/écriture durable Robot KB par simple merge de code préparatoire ;
- aucune fermeture housekeeping destructive sans autorisation utilisateur ;
- **PR #8 reste explicitement protégée** et non mergée.
