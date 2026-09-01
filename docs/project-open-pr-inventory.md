# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot GitHub pertinent re-vérifié le **1 septembre 2026** après #227 et #229/#231. Le contrôle GitHub live reste l'autorité ; **ne pas utiliser le nombre de lignes comme compteur exhaustif GitHub** et ne pas utiliser ce document comme compteur exhaustif sans nouveau search live.

> V4 runtime production : `main@b6a7c834264c062ea81b64c714e6916aa8bfe9f2`. #227 et #229/#231 sont **MERGED** et ne font plus partie de la surface PR ouverte.

```text
V4 runtime                     b6a7c834264c062ea81b64c714e6916aa8bfe9f2
PR #229/#231                  MERGED / auction recovery capacity / b6a7c834264c062ea81b64c714e6916aa8bfe9f2
PR #227                       MERGED / protected docs marker / 4323822fa324f6f9a089a1e1447b41f611ea8b95
PR #230                       OPEN / DRAFT / VALIDATION ONLY / DO NOT MERGE
PR #226                       OPEN / V4 eBay worker optimization / separate phase
PR #228                       OPEN / validation mirror of #226 / no merge authorization
PR #8                         OPEN / DRAFT / NON MERGED
PR #210                       OPEN / DRAFT / durable write guard / NO EXECUTION AUTHORIZATION
```

## PR ouvertes **pertinentes pour la gouvernance courante**

### V4 courant / validation

| PR | Classification / instruction |
|---|---|
| #230 | `VALIDATION_ONLY / OPEN_DRAFT / DO_NOT_MERGE`. Miroir temporaire utilisé avant #227 pour valider #229 avec le marqueur docs protégé. La capacité auction est déjà en production via #231 ; ne pas merger #230. |
| #226 | `V4_EBAY_WORKER_BULK_TEXT / OPEN`. Optimisation worker-only visant les hard timeouts eBay 30 s observés en production ; queries, matching, SOLD semantics, économie, budgets et breakers annoncés inchangés. Revalider sur current `main` avant toute décision de merge. |
| #228 | `V4_EBAY_VALIDATION_MIRROR / OPEN`. Miroir de validation de #226 ; aucune autorisation de merge implicite. |
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
| #197 | `ROBOT_KB_FANATICS_PAID_HISTORY_DIAGNOSTIC`. PAID explicite requis ; currency encore non prouvée dans la phase documentée. |
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
| #115 | `SUPERSEDED_BY_139` / stack Global historique. |
| #114 | `SUPERSEDED_BY_139` / stack Global historique. |
| #113 | `SUPERSEDED_BY_139` / stack Global historique. |
| #110 | `SUPERSEDED_BY_139` / stack Global historique. |
| #109 | `SUPERSEDED_BY_139` / stack Global historique. |
| #108 | `SUPERSEDED_BY_139` / stack Global historique. |
| #111 | `STALE_OPEN/SUPERSEDED` docs. |
| #107 | `STALE_OPEN/SUPERSEDED` Japan Edge PPT display shadow ; OPEN/DRAFT, ne pas merger automatiquement sur current main. |
| #106 | `STALE_OPEN/SUPERSEDED` V4 PPT shadow ; OPEN/DRAFT, ne pas merger automatiquement sur current main. |
| #54 | `STALE_OPEN/SUPERSEDED`. |

## Merges récents retirés de la surface ouverte

- #229 / #231 : capacité de recovery auction adaptative après dérive d'ordre **MERGED / PROD_V4** ; même head/tree validé, production `b6a7c834...` ;
- #227 : restauration docs du marqueur de gouvernance protégé **MERGED / DOCS_ONLY** ;
- #222 / #224 : fallback TCGdex source-pinné sur panne transport **MERGED / PROD_V4** ;
- #223 : restauration docs des marqueurs de gouvernance **MERGED / DOCS_ONLY** ;
- #216 / #217 : résilience transport TCGdex Main-only **MERGED / PROD_V4** ;
- #219 : configurateur Robot KB mode exécutable **MERGED / MAIN_SUPPORT** ;
- #220 : future-start GCC auction guard **MERGED / PROD_V4** ;
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
