# Cardova `print_run` exact SOLD live validation — 31 août 2026

PR #208, empilée sur #206. Phase strictement read-only PostgreSQL + persistence `:memory:`.

## Runtime / CI

```text
#208 head                         78c21ea62be92878abba0bca38882a29380b63ca
P3 #207 runtime                  38288a950db8285bcbf279d91354f8a1ad3a8c2f
Robot KB CI                      33395727932 SUCCESS
V4 Auction Discovery             33395727946 SUCCESS
```

## Mapping validé

```text
printing=no_rarity_symbol
 -> print_run=NO_RARITY_SYMBOL

preuve positive de symbole visible
 -> print_run=RARITY_SYMBOL_PRESENT
```

Aucun mapping vers `edition_stamp`. `NO_RARITY_SYMBOL` n'implique pas First Edition ; `RARITY_SYMBOL_PRESENT` n'implique pas Unlimited ni un synthetic `standard`.

## Live Mac authoritative

Le collecteur a continué de croître entre #206 et #208 :

```text
unresolved Cardova SOLD           356
selected immutable sale rows      356
macro/finish rows                   44
exact identity rows                 38
identity blockers                    6
```

Blockers identité :

```text
CARDOVA_PUBLIC_TITLE_MATERIAL_TAIL_UNRESOLVED   1
PINNED_SOURCE_VARIANT_AMBIGUOUS                 1
PROVIDER_MATERIAL_TOKEN_UNRESOLVED              4
```

Résultat exact-sale/P3 :

```text
exact SOLD candidates from #205   38
#205 sale blockers                  0
P3 representable                   38
P3 schema blockers                  0
canonical cards in memory          34
PROVEN Cardova links in memory     38
exact SALE_TRANSACTION in memory   38
exact sale rows verified           38
HAMMER_PRICE JPY verified          38
exact identity links reported      38
sale transactions stored reported  38
replay duplicate-sale proofs       38 / 38
```

Le fait d'avoir 34 canonical cards pour 38 sales est attendu : plusieurs ventes exactes réutilisent la même identité canonique exacte.

## Invariant prouvé

```text
p3_schema_representable_count
== exact_sale_candidates_from_205
== exact_identity_rows
== 38

p3_schema_blocked_count == 0
exact_sale_candidate_blocked_from_205 == {}
hammer_price_jpy_rows_verified == 38
duplicate_sale_replays == 38
```

Le drift `291 -> 356` ne change donc pas le résultat sémantique : le gap P3 `printing` de #206 est fermé par le `print_run` #207.

## Safety

- PostgreSQL local : `BEGIN READ ONLY` ;
- migration durable : false ;
- Robot KB durable write : false ;
- canonical link durable : false ;
- exact SALE_TRANSACTION durable : false ;
- persistence testée uniquement dans `KnowledgeBase.open(":memory:")` ;
- V4 economic use : false ;
- notification : false ;
- achat/bid/offer/checkout/paiement : false.

## Suite sûre

La prochaine étape n'est pas un write production direct. Faire d'abord une répétition PostgreSQL transactionnelle complète : appliquer le runtime/migration #207 sur une surface isolée ou transaction rollback, exécuter la persistence exacte #208, vérifier les 38 lignes/JPY/idempotence, puis `ROLLBACK` et prouver que le durable n'a pas changé.
