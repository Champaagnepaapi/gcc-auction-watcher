# Cardova public title / rarity-symbol printing proof — 2026-08-30

Scope: read-only Robot KB identity evidence stacked on PR #199. No V4 economic use and no Robot KB write.

## Exact public-title proof

- `01KFFRJ8B4X9FG8YK90K4BNS1T` / Ninetales PSA 10 / cert `141683514`: exact title contains `No Rarity Original Print` with no trailing material qualifier. This positively proves `printing=no_rarity_symbol`; it does not prove First Edition.
- `01KQHACBX20NBMGD9VZAPA6Z64` / Charizard PSA 8 / cert `156405344`: exact title contains `No Rarity Original Print Error(Strength)`. The trailing `Error(Strength)` is a material microvariant token and blocks collapsing the row into plain No Rarity.
- A Cardova title that omits `No Rarity Original Print` does not prove standard/ordinary printing.

The parser in `robot_kb_cardova_public_title_printing_proof.py` is pure and fail-closed. Network acquisition remains a separate read-only diagnostic surface.

## Reviewed Cardova front-image proof

Cardova page payload exposes exact `image_a`; the frontend constructs the public scan as `https://card-image.cardova.co.jp/<image_a>`.

The 10 remaining Japanese Basic ordinary-vs-No-Rarity rows were downloaded from that exact Cardova CDN path and manually reviewed. All 10 visibly show a printed rarity symbol at the lower-right card border (`★` for rare/holo or `●` for common/non-holo). The reviewed Ninetales No Rarity control visibly has no rarity symbol there.

`robot_kb_cardova_reviewed_rarity_symbol_proof.py` binds each reviewed row to source ULID, cert, PMCG1 coordinate/card/grade/finish, exact `image_a`, exact SHA-256 and visible symbol class. Image bytes are not stored in the repo.

A visible rarity symbol positively excludes `printing=no_rarity_symbol`; it does not create a synthetic provider/source value called `standard`.

`robot_kb_cardova_rarity_symbol_microvariant_closure.py` only closes when the immutable pinned TCGdex source has exactly two compatible variants identical except for explicit `printing=no_rarity_symbol` on one. Any other source shape remains fail-closed.

## Validation

Code head validated: `dcd64575e0fee27f0e9c9b99cdf49c9703c0394e`.

Focused tests: **25/25 PASS** (`7 + 7 + 11`).

Final Mac live read-only compose:

```text
initial_microvariant_exact         26
title_no_rarity_added               1
visible_rarity_symbol_added        10
final_microvariant_exact           37
remaining_unresolved                1
expected_37_of_38                  true
```

Only unresolved row:

```text
Charizard / PSA 8 / cert 156405344
source 01KQHACBX20NBMGD9VZAPA6Z64
material_tail Error(Strength)
reason CARDOVA_PUBLIC_TITLE_MATERIAL_TAIL_UNRESOLVED
```

No canonical link, SALE_TRANSACTION exact write, V4 economic use, notification or commerce operation occurred in this phase.
