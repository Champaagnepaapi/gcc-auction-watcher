# GCC Auction Watcher

> **Source de reprise technique canonique.** Lire ce fichier avant tout changement important.
> Le README décrit l’état courant ; l’historique détaillé reste dans Git, les PR et les runs GitHub Actions.

## État canonique — 16 août 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production = main
main HEAD = 87d050e3c0d530786baa9c3e4d9395b99a4f8929
V5 expérimentale = PR #8
V5 head = bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

Le HEAD `main` correspond au merge de la PR #104 : discovery auctions durcie et Mislisted Slab/OCR désactivé en production.

**PR #8 ne doit jamais être mergée dans `main` sans autorisation explicite utilisateur.**

## Règles non négociables

- Pokémon cartes individuelles uniquement.
- Aucun achat, bid, checkout, paiement ou grading payant automatique.
- V4, V5 et Robot KB / Neon restent séparés.
- Identité incertaine ou microvariante non prouvée = fail-closed / revue manuelle.
- Un ASK ou une enchère en cours n’est jamais une vente.
- Une absence de données marché n’est jamais une preuve de faible valeur.
- Un changement important passe par une branche/PR dédiée, un SHA précis, des tests ciblés et une validation avant merge.

## Hiérarchie des preuves prix

1. SOLD exacts et récents ;
2. SOLD exacts anciens avec ajustement temporel défendable ;
3. asks fixes compatibles, étiquetés ASK ;
4. snapshot d’enchère observé à `≤5 min` si aucun SOLD n’est disponible ;
5. enchère en cours = signal faible uniquement.

## Identité commerciale

Toujours garder séparés : carte, set, numéro/localId, langue, édition, finish, microvariante, grader et grade.

- `004/102` peut être normalisé vers `4/102`, mais `4/102` ≠ `4/130`.
- Fuzzy/substr/Levenshtein peut aider la récupération mais ne constitue jamais une preuve exacte.
- First Edition, Shadowless, Holo/Reverse, stamp, Master Ball, texture error et autres variantes sensibles restent fail-closed lorsqu’applicables.
- `AMBIGUOUS` reste bloquant.

L’objectif est d’améliorer la **récupération et l’extraction**, pas de relâcher le gate d’identité pour augmenter artificiellement le taux de match.

---

# V4 production

## Main Scanner

```text
Cron-job.org ~toutes les 10 min
  -> workflow_dispatch
  -> .github/workflows/watcher.yml
  -> run_watcher_multimarket.py
```

État courant :

- fixed GCC via `/on-sale-items` ;
- auctions `ENDING_SOON` avec fallback legacy complet si l’ordre/completude API n’est pas prouvé ;
- pages `private` + `weekly` comme safety-net ;
- TCGdex déterministe pour l’identité ;
- GCC SOLD, PokeTrace, PSA APR et eBay SOLD exacts selon disponibilité ;
- RAW Cardmarket/TCGplayer ne devient jamais automatiquement la valeur d’un slab gradé ;
- Mislisted Slab/OCR forcé OFF en production.

## Fast Lane

```text
Cron-job.org toutes les 3 min
  -> .github/workflows/v4-final-auction-check.yml
```

Elle ne redécouvre pas les cartes, ne relance pas les providers marché et réutilise le `max_recommended` déjà calculé.

## Arbitrage

États principaux :

- `GCC_ONLY`
- `GCC_EXTERNAL_CONFIRMED`
- `EXTERNAL_RESCUE`
- `EXTERNAL_PENDING`
- `MARKET_CONFLICT_BLOCKED`

Deux marchés forts contradictoires => blocage prudent, pas moyenne forcée.

---

# Japan Edge production

Merges structurants :

```text
PR #89   asks Japon                         c2309e6d6f0c19bd07479b73498dae8445366238
PR #94   corroboration SOLD externe         2a405ff9bdf5aa62bf3c2a074ce1b2a9ab210b2e
PR #101  format comparatif notifications   cf652027a767626829d6c3b6d115fb62f64f140c
```

Marchés ASK : Mercari Japan, magi et Yahoo! Flea Market / PayPay Fleamarket.

Scope actuel : cartes japonaises individuelles PSA 10 exactes.

Verdicts :

- `MULTIMARKET_CONFIRMED`
- `GCC_EDGE_NOT_GLOBAL`
- `MARKET_CONFLICT_BLOCKED`
- `GCC_ONLY_UNCONFIRMED`

Les notifications gardent séparés GCC, marché externe exact et fair multi-marché. Une absence d’externe reste `non confirmé`.

---

# Robot KB / Neon

Robot KB reste séparé de V4/V5 et vise un historique append-only multi-années.

Priorité :

1. final SOLD prouvé ;
2. fixed baseline puis changements utiles ;
3. auction final SOLD ;
4. snapshot `≤5 min` seulement comme fallback clairement identifié.

Contrat SOLD GCC :

```text
status=SOLD + soldAt timezone-aware + prix final valide
= SALE_TRANSACTION prouvée
```

Merges récents importants :

```text
PR #75  fixed coverage hybride      caebf0e5865e6851c5240b80c8ba55e3cfa7f5d5
PR #76  backfill historique SOLD    fda196283e3522de7c1eadca3c706c9c350dec8d
```

KB-first reste une readiness, pas un hard gate V4 tant que la profondeur exacte n’est pas suffisante.

---

# V4 Global Multi-Vault — développement shadow

Objectif :

```text
identité exacte
  -> fair value SOLD
  -> GCC / Cardova / magi / Fanatics / COMC
  -> prix achetable / frais / vault
  -> meilleure décote comparable
```

## PR actives

### PR #106 — PPT V4 shadow

Branche `agent/v4-ppt-clean-20260816`.

Provider PokemonPriceTracker V4 propre, shadow uniquement. Les données PPT restent `SOLD_AGGREGATED`, jamais des ventes item-level. Cette PR reste la source canonique du provider PPT V4.

### PR #107 — Japan Edge GCC + PPT séparés

Branche `agent/japan-edge-ppt-clean-20260816`.

PPT est affiché après la décision Japan Edge existante ; GCC et PPT restent séparés et PPT ne crée/supprime pas l’opportunité.

### PR #108 — Global Multi-Vault foundation

Branche `feat/v4-global-multivault-edge-foundation`.

Common valuation layer + adapters GCC/Cardova/magi/Fanatics/COMC/PPT/PokeTrace. ASK/current auction exclus de la fair value. `FINISHED_UNPROVEN` n’est jamais SOLD.

Validation connue : 27/27 tests global-market + 51/51 régressions V4 multimarket PASS.

### PR #109 — wiring live shadow

Branche `feat/v4-global-live-shadow`, stackée sur #108.

Run live read-only `31954247131`, job `95182311878` : SUCCESS.

| Marché | Recherches | Candidats inspectés | Exact retenu |
|---|---:|---:|---:|
| GCC | 16 | 1600 | 6 |
| magi | 5 | 35 | 0 |
| Fanatics | 5 | 24 | 0 |
| COMC | 5 | 2 | 0 |
| Cardova | 0 | 0 | session navigateur requise |

`0 exact` ne signifie pas `0 stock` : une annonce peut être trouvée puis rejetée parce que numéro, langue, set, PSA10 ou microvariante ne sont pas prouvés dans les données extraites.

### PR #110 — diagnostics de rejets exacts

Branche `feat/v4-global-rejection-diagnostics`, stackée sur #109.

Cette phase ajoute des diagnostics expliquant les rejets avant toute modification du matcher :

- `RETRIEVAL_GAP` : aucune annonce candidate trouvée ;
- `METADATA_OR_IDENTITY_PROOF_GAP` : annonce trouvée mais identité insuffisamment prouvée ;
- `TRUE_INCOMPATIBLE_OR_NON_ACTIONABLE` : auction, lot, sold-out, prix non prouvable ;
- `TECHNICAL_ERROR` : navigation/parsing/provider.

Raisons détaillées suivies :

```text
search_no_candidates
collector_number_unproven
psa10_unproven
language_unproven
card_name_unproven
set_unproven
card_or_set_unproven
edition_unproven
microvariant_unproven
sensitive_variant_unproven:...
ongoing_auction
multi_item_listing
unavailable_or_sold
price_unproven
search_error / page_error / detail_error
```

Sur cette branche, le workflow manuel `V4 Global Market Live Shadow` peut lancer ce diagnostic à la place du shadow normal. Il faut d’abord mesurer ces causes, puis améliorer retrieval/parsing/provenance sans affaiblir l’identité exacte.

## Cardova

Cardova dépend d’une session navigateur pour le flux observé. GitHub Actions ne doit donc pas simuler cette session. Le shadow accepte un snapshot JSON assaini récupéré localement. Fixed single direct uniquement ; bundles exclus ; premium buyer inconnu => all-in non prouvé ; `finished=1` reste `FINISHED_UNPROVEN`.

---

# V5 expérimentale

PR #8 reste expérimentale, draft et non mergée.

- TCGdex reste le resolver principal ;
- PokeTrace reste principalement marché/prix ;
- microvariantes restent fail-closed ;
- PR #96 `agent/v5-catalog-gap-hardening` reste une PR enfant V5 draft/offline-validée ;
- aucun travail V4 Global ne doit être mélangé automatiquement dans V5.

---

# Repo hygiene

Audit du 16 août 2026 : le repo contient **plus de 120 branches**, avec beaucoup de branches historiques de test, diagnostic, one-shot et anciennes features.

Nettoyage déjà effectué :

- PR #30 fermée : ancien prototype last-chance remplacé par la Fast Lane PR #45 ;
- PR #90 fermée : ancienne ligne PPT V4 remplacée par #106 ;
- PR #95 fermée : ancienne ligne Japan Edge PPT ;
- PR #105 fermée : remplacée par #107.

Aucune branche active de PR #8/#87/#96/#106/#107/#108/#109/#110 n’a été supprimée.

Politique dorénavant :

**Conserver** `main`, la branche V5 de PR #8, les branches de PR actives, les branches Robot KB réellement opérationnelles et les branches requises par un workflow actif.

**Candidats au nettoyage après audit** : `*-temp`, `*-check`, one-shot terminés, diagnostics terminés, branches de PR fermées/supersédées et anciennes features déjà mergées.

Avant toute suppression de branche : vérifier PR, ancestry/diff et dépendances workflow. Ne jamais force-push une branche active simplement pour faire du ménage.

---

# Workflows à conserver

Production / opérationnel :

1. `GCC Auction Watcher` ;
2. `GCC Final Auction Check` ;
3. `V4 Auction Discovery Validation` ;
4. `V4 GCC Coverage Audit` ;
5. `Robot KB cloud shadow` ;
6. `Robot KB SOLD shadow`.

Développement / diagnostics :

7. `PSA Public API Diagnostic` ;
8. `V5 Offline Validation` ;
9. diagnostics V5 manuels utiles ;
10. `V4 Global Market Offline Validation` ;
11. `V4 Global Market Live Shadow` manuel.

Éviter les nouveaux workflows temporaires lorsqu’un workflow manuel existant peut porter le diagnostic via un input.

---

# Procédure avant un changement important

1. lire ce README ;
2. lire `.agents/rules/gcc-project-governance.md` ;
3. vérifier branche, HEAD, Git et PR concurrentes ;
4. travailler dans une branche/PR dédiée ;
5. ajouter des tests ciblés ;
6. exécuter suite pertinente + compile/YAML + `git diff --check` ;
7. lancer un live read-only seulement lorsque nécessaire et autorisé ;
8. documenter SHA/run exacts ;
9. ne jamais merger automatiquement le travail d’un autre agent ;
10. mettre à jour ce README après une phase importante validée.

## Handoff minimum attendu

Toujours laisser : branche, base SHA, final SHA, fichiers modifiés, tests, runs live réellement exécutés, risques restants et confirmation :

```text
achat automatique : NON
bid automatique : NON
checkout/paiement : NON
merge PR #8 : NON
```
