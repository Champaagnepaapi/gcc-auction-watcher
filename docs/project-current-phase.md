# Robot Pokémon / GCC Auction Watcher — current phase

## Phase active — 31 août 2026

Cardova paid/completed SOLD est actuellement porté par le stack draft :

```text
#199  paid SOLD provider/P3 + collector local
#204  identity/microvariant proof
#205  exact-card SOLD candidate dry-run
```

Les trois PR restent **OPEN / DRAFT / NON MERGED**. `main` V4 reste séparé. `V4_USE=false`.

## Dernier résultat live Cardova

Le collector local continue de faire croître l'historique. Le snapshot read-only du 31 août contient :

```text
Cardova SALE_TRANSACTION unresolved  291
exact identity rows                   38
exact-card SOLD candidates            38
sale candidate blocked                 0
identity blockers                      5
canonical links                        0
Robot KB exact writes                  0
V4_USE                              false
```

Le baseline historique #204 du 30 août reste **37/38 microvariantes exactes** sur son cohort de 38. Il ne faut pas remplacer ce fait historique par le compteur courant.

Le dataset courant a ajouté des lignes depuis le baseline 244. Les blockers visibles sont :

```text
Charizard  01KQHACBX20NBMGD9VZAPA6Z64  Error(Strength)
Rattata    01M07F9T9NKG76DFXGNY0NXWAY  provider material token unresolved
Machoke    01M07F9T93G9V1BVZ3X8NTGV89  provider material token unresolved
Machoke    01M07F9T4K90S1X1XCVHVRRKNH  provider material token unresolved
Magnemite  01M07F9T80P8EVTY9D0S1X132J  provider material token unresolved
```

Le Charizard est le blocker historique du cohort #204. Les quatre autres sont de nouvelles lignes apparues après le snapshot 244.

## #205 — capacité validée

Code head validé : `f575a3444477cf81b0564e832f477bb2a64863b6`.

#205 compose :

1. identité commerciale exacte #204 ;
2. même source native Cardova ;
3. carte/numéro/grader/grade (+ langue si présente) cohérents ;
4. contrat SOLD P3 existant #199 ;
5. `HAMMER_PRICE` JPY et `sale_occurred_at = auction_end_at_utc`.

Invariant durable :

```text
exact_card_sale_candidate_count == exact_identity_rows
sale_candidate_blocked == {}
distinct candidate ids == exact candidate count
HAMMER_PRICE JPY rows == exact candidate count
memory-only == true
```

Ne pas hardcoder 37 comme compteur global : la collecte Cardova est continue.

Validation :

```text
Robot KB CI       33339319304 SUCCESS
V4 validation     33339319292 SUCCESS
Cardova dry-run   7/7 PASS
compile/YAML/diff PASS
Mac live          38 exact SOLD candidates / 0 sale blocker
```

## Prochaine étape

Construire un **dry-run canonical-card link + exact-sale persistence**, en réutilisant les primitives Robot KB existantes :

- memory-only / rollback d'abord ;
- aucun write durable au premier passage ;
- blockers identité exclus ;
- exact SHA + tests ciblés + live read-only ;
- aucun V4_USE sans activation séparée explicite.

## Safety

- aucun achat ;
- aucun bid ;
- aucun offer ;
- aucun checkout ;
- aucun paiement ;
- aucune notification ;
- aucun merge autorisé par cette phase ;
- PR #8 V5 untouched.
