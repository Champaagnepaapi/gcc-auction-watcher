# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

Snapshot GitHub pertinent re-vérifié le **6 septembre 2026** après les merges #254 et #255. GitHub live reste l'autorité ; ce fichier classe les PR importantes, pas nécessairement chaque PR historique.

> V4 live `main@dfc548021c561479cc8758e2949d2c4629388d9d`. Le tree est identique au runtime #255 `9d3bb1b84d22c1534c24d7c58c5897ecce4b817f` après deux commits placeholder/revert net-zero. #253, #254 et #255 sont **MERGED**.

## Surface ouverte pertinente

| PR | Classification / instruction |
|---|---|
| #248 | `STALE_OPEN / DIAGNOSTIC`. Ancien diagnostic eBay navigation timeout, base très ancienne ; production #250 couvre déjà le diagnostic safe. Ne pas merger directement. |
| #234 | `VALIDATION_ONLY / OPEN_DRAFT / DO_NOT_MERGE`. Benchmark eBay public borné, inconclusif. |
| #233 | `STALE_OPEN / SUPERSEDED` par #238/#239. Ne pas merger. |
| #230 | `VALIDATION_ONLY / DO_NOT_MERGE`. Ancienne validation auction recovery. |
| #226/#228 | `STALE_OPEN / SUPERSEDED` par #238/#239. |
| #210 | **`ROBOT_KB_DURABLE_WRITE_GUARD / EXPLICIT_AUTH_REQUIRED`**. Aucun commit durable Cardova exécuté. |
| #209 | `ROBOT_KB_ROLLBACK_REHEARSAL`. Preuve réelle sous rollback, pas autorisation de write. |
| #208 | `ROBOT_KB_MEMORY_ONLY / P3_STACKED`. |
| #206 | `ROBOT_KB_PRE_207_FAIL_CLOSED_PROOF`. |
| #205 | `ROBOT_KB_MEMORY_ONLY_SOLD_CANDIDATES`. |
| #204 | `ROBOT_KB_CARDOVA_MICROVARIANT_PROOF`. |
| #199 | `ROBOT_KB_CARDOVA_SOLD_STACK_ROOT`. |
| #198 | `ROBOT_KB_COMC_PUBLIC_HISTORY_DIAGNOSTIC`. Live anonymous headless = HTTP 403 ; ne pas bypass. |
| #197 | `ROBOT_KB_FANATICS_PAID_HISTORY_DIAGNOSTIC`. `PAID + isComplete=true` prouvé ; currency non prouvée dans le contrat documenté. |
| #196 | `ROBOT_KB_LOCAL_PSA_CORROBORATION`. Mac local seulement ; PSA GitHub 403. |
| #195 | `ROBOT_KB_BATCH_STACKED`. Ne pas merger indépendamment. |
| #194 | `ROBOT_KB_CANONICAL_BOOTSTRAP / STACKED`. |
| #193 | `ROBOT_KB_MANUAL_WRITE_PATH / STACKED`. |
| #192 | `ROBOT_KB_EBAY_BENCHMARK`. Provider seul ne prouve pas SOLD. |
| #8 | **`V5_ONLY / PROTECTED`**. OPEN / DRAFT / NON-MERGED. Ne jamais merger dans `main` sans autorisation explicite utilisateur. |

## Merges production récents

```text
#255  MERGED  external market evidence sole fair-value authority
      validated head e886c649eea8633d39585aabca8fff0b58be4324
      production     9d3bb1b84d22c1534c24d7c58c5897ecce4b817f

#254  MERGED  bounded eBay structured salvage
      validated head fbb7041f9fc44c338b102ec7325a6d6316f1e529
      production     00e5502fb15c9a89d67a55b70cd566099911bcdb

#253  MERGED  structured eBay body-timeout salvage
      validated head 4ced75070cc274abf99ea59f7995d356cbb6dd77
      production     23e8e9904072d986e24d2a8fbccaa87568851f69
```

Autres autorités production à ne pas remplacer par les stale PR : #247, #245, #243, #242, #250/#251/#252, #238/#239, #237, #229/#231, #222/#224, #216/#217, #220, #214, #211/#212, #178/#179/#180.

## External SOLD coverage — réutilisation avant nouveau code

- **eBay V4** : utiliser le runtime courant, pas #226/#228/#233/#248 ;
- **eBay RapidAPI Robot KB** : shadow courant ; pas de promotion SOLD sans corroboration finalité/prix ;
- **Fanatics #197** : réutiliser les semantics `PAID + isComplete=true`, puis fermer currency + identité + microvariante avant `SALE_TRANSACTION` ;
- **COMC #198** : anonymous headless bloqué 403, aucun contournement ;
- **Cardova #199→#210** : stack strict existant, durable write explicitement gardé ;
- **PriceCharting V5/#8** : guide values seulement, pas item-level SOLD.

## PR protégées / risque matériel

### #210 — durable Cardova

Ne pas merger/exécuter comme simple housekeeping. Toute écriture durable exige : autorisation explicite opérateur, SHA exact, locks writers, backup validé, preflight, transaction gardée et vérification post-commit. `V4_USE=false` reste inchangé.

### #8 — V5

PR expérimentale, base/divergence importante, non mergeable au snapshot. Aucune partie de cette PR ne doit être mergée dans `main` sans autorisation explicite spécifique.

## Stale / superseded / historique

- #226/#228/#233 -> superseded par #238/#239 ;
- #248 -> diagnostic plus ancien que #250 ;
- #234/#230 -> validation-only, do not merge ;
- #159 -> superseded fonctionnellement par #177 ;
- #141 -> superseded par #142/#140 ;
- #138 et #108/#109/#110/#113/#114/#115 -> absorbés par #139 ;
- #126 -> superseded par #127→#135 ;
- #54 -> stale/superseded.

## Règles

- `open` ne signifie jamais `à merger` ;
- draft/non-draft ne vaut pas autorisation ;
- vérifier patch + ancestry + supersession avant toute décision ;
- ne jamais merger un child stacké directement si son parent n'est pas résolu ;
- aucune migration/écriture durable Robot KB par simple merge de code préparatoire ;
- aucune fermeture destructive housekeeping sans autorisation utilisateur ;
- **PR #8 reste explicitement protégée et non mergée**.
