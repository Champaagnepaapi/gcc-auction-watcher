# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot GitHub pertinent re-vérifié le **1 septembre 2026** après #216/#217, #219 et #220. Le contrôle GitHub live reste l'autorité ; ne pas utiliser le nombre de lignes comme compteur exhaustif GitHub et ne pas utiliser ce document comme compteur exhaustif sans nouveau search live.

> V4 runtime production : `main@6a33ac33faa324f0fc1c6124fbb49bd736382b75`. #216/#217, #219 et #220 sont **MERGED** et ne font plus partie de la surface PR ouverte.

```text
V4 runtime                     6a33ac33faa324f0fc1c6124fbb49bd736382b75
PR #216/#217                  MERGED / TCGdex resilience / 03824158ac899cf142199c42d4525386a573bc15
PR #219                       MERGED / Robot KB configurator executable / 2aef339135df8b4a183ad4ba030b9e603ea9e696
PR #220                       MERGED / future-start auction guard / 6a33ac33faa324f0fc1c6124fbb49bd736382b75
PR #8                         OPEN / DRAFT / NON MERGED
PR #210                       OPEN / DRAFT / durable write guard / NO EXECUTION AUTHORIZATION
```

## PR ouvertes **pertinentes pour la gouvernance courante**

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
| #87 | **Décision produit V4 séparée/non déployée** : GCC-only illiquid notification 30 %. Ne pas mélanger à un autre changement. |

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
| #115/#114/#113/#110/#109/#108 | `SUPERSEDED_BY_139` / stack Global historique. |
| #111 | `STALE_OPEN/SUPERSEDED` docs. |
| #107/#106 | anciennes lines PPT/Japan shadow ; ne pas merger automatiquement sur current main. |
| #54 | `STALE_OPEN/SUPERSEDED`. |

## Merges récents retirés de la surface ouverte

- #216 / #217 : résilience TCGdex Main-only **MERGED / PROD_V4** ;
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
