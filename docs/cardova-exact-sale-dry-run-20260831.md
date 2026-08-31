# Cardova exact SOLD candidate dry-run — 31 août 2026

PR : #205, empilée sur #204. Phase strictement read-only / memory-only.

## But

Composer les identités commerciales exactes Cardova déjà prouvées avec le contrat SOLD P3 existant de #199, sans créer de canonical link et sans écrire de nouvelle `SALE_TRANSACTION` exacte.

## Contrats réutilisés

- identité : probes/closures #204, source TCGdex Asian pinnée `af33c9ac882e2acfadffaf19e8083aa976d12983` ;
- vente : `robot_kb_cardova_sale_transaction_dry_run.build_p3_sale` de #199 ;
- prix : `HAMMER_PRICE` JPY ;
- événement : `sale_occurred_at = auction_end_at_utc` ;
- aucun timestamp de paiement, buyer premium ou all-in fabriqué.

## Validation CI

Head avant live : `f575a3444477cf81b0564e832f477bb2a64863b6`.

- Robot KB local PostgreSQL validation `33339319304`: SUCCESS ;
- suite Cardova P3 dry-run : 7/7 PASS, incluant exact identity -> même contrat SOLD P3 ;
- V4 Auction Discovery validation `33339319292`: SUCCESS ;
- compile / YAML / `git diff --check`: PASS.

## Live Mac read-only

Le collector a continué à tourner entre les deux phases : le nombre de `SALE_TRANSACTION` Cardova unresolved est passé de 244 à **291**. Le run live ne doit donc pas utiliser un compteur global figé à 37.

Résultat observé :

```text
unresolved Cardova SALES          291
exact identity rows                38
exact-card SOLD candidates         38
sale candidate blocked              0
distinct candidate source ids      38
HAMMER_PRICE JPY rows              38
memory-only                       true
identity blockers                   5
```

Les cinq blockers identité visibles sur le snapshot :

```text
Charizard / 01KQHACBX20NBMGD9VZAPA6Z64
  CARDOVA_PUBLIC_TITLE_MATERIAL_TAIL_UNRESOLVED
  material tail = Error(Strength)

Rattata / 01M07F9T9NKG76DFXGNY0NXWAY
  PROVIDER_MATERIAL_TOKEN_UNRESOLVED

Machoke / 01M07F9T93G9V1BVZ3X8NTGV89
  PROVIDER_MATERIAL_TOKEN_UNRESOLVED

Machoke / 01M07F9T4K90S1X1XCVHVRRKNH
  PROVIDER_MATERIAL_TOKEN_UNRESOLVED

Magnemite / 01M07F9T80P8EVTY9D0S1X132J
  PROVIDER_MATERIAL_TOKEN_UNRESOLVED
```

Le Charizard `Error(Strength)` reste le blocker du cohort historique 38. Les quatre autres blockers sont de nouvelles lignes apparues après le snapshot 244.

## Interprétation correcte

Le résultat historique #204 reste : **37/38 microvariantes exactes** sur le cohort validé du 30 août.

Le résultat #205 est snapshot-dynamique : sur les données présentes le 31 août, **38 identités exactes** satisfont aussi le contrat SOLD P3 et deviennent des `exact_card_sale_candidate_ready=true` en mémoire. Une ligne exacte supplémentaire est donc entrée dans le périmètre depuis le snapshot précédent.

Ne pas remplacer cette logique par `expected_count == 37`. L'invariant est :

```text
exact_card_sale_candidate_count == exact_identity_rows
sale_candidate_blocked == {}
distinct_candidate_source_ids == exact_card_sale_candidate_count
HAMMER_PRICE JPY rows == exact_card_sale_candidate_count
all candidates memory-only == true
```

Les blockers d'identité restent fail-closed et séparés des candidates exactes.

## Safety

- canonical link écrit : false ;
- Robot KB write : false ;
- exact `SALE_TRANSACTION` write : false ;
- V4 economic use : false ;
- notification : false ;
- achat/bid/offer/checkout/paiement : false ;
- PR #8 untouched ;
- aucune PR mergée.

## Suite

La prochaine étape n'est plus de prouver le contrat SOLD des candidates : il est validé. Avant toute persistance exacte, construire un dry-run de **canonical-card link + exact-sale persistence** qui réutilise les primitives Robot KB existantes, avec rollback/memory-only d'abord. Les cinq blockers restent exclus tant qu'une preuve matérielle déterministe n'existe pas.
