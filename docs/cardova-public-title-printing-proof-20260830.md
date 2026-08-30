# Cardova public title + reviewed front-image printing proof — 2026-08-30

Scope: PR #204 stacked on PR #199 only. Read-only identity research; no Robot KB writes, no V4 economic use, no notification and no commerce.

## Public title proof

Cardova public auction pages expose exact titles. A title containing the exact material phrase `No Rarity Original Print` can positively prove the No Rarity Symbol printing when no additional material qualifier remains.

Observed:

- Ninetales PSA 10 / cert `141683514` / source `01KFFRJ8B4X9FG8YK90K4BNS1T` → `1996 Ninetales PSA 10 Holo No Rarity Original Print - Cardova Japan` → positive `printing=no_rarity_symbol` proof.
- Charizard PSA 8 / cert `156405344` / source `01KQHACBX20NBMGD9VZAPA6Z64` → `1996 Charizard PSA 8 Holo No Rarity Original Print Error(Strength) - Cardova Japan` → No Rarity is visible but `Error(Strength)` is a separate unresolved material microvariant, so the row remains blocked.

A plain title such as `1996 Venusaur PSA 9 Holo - Cardova Japan` does **not** prove ordinary printing. Absence of `No Rarity` text remains non-evidence.

Live Mac composition before image review: `26 -> 27` exact microvariants, 10 ordinary-vs-No-Rarity ambiguities plus the Charizard `Error(Strength)` row blocked.

## Structured Cardova payload

The exact public page embeds `__NEXT_DATA__` with card fields such as source ULID, PSA certificate number, set label, language, card number, grade, `attribute`, and exact image filenames.

Positive controls:

- Ninetales No Rarity: `attribute="Holo No Rarity Original Print"`.
- Charizard error: `attribute="Holo No Rarity Original Print Error(Strength)"`.

The 10 ordinary-title rows expose only `Holo` or an empty attribute. This remains insufficient to prove ordinary printing by itself.

## Reviewed Cardova front-image proof

The Cardova JS bundle constructs card image URLs as:

```text
https://card-image.cardova.co.jp/<image_a>
```

The exact public front scans for the 10 remaining ordinary-vs-No-Rarity rows were downloaded and manually reviewed. Each visibly contains a printed rarity symbol immediately after the card number at the lower-right card border:

- rare/holo rows: visible `star` symbol;
- common/non-holo rows: visible `circle` symbol.

The Ninetales PSA 10 No Rarity control scan (`01KFFRJ8B4X9FG8YK90K4BNS1T`) visibly has no rarity symbol at that position, confirming the distinguishing visual axis.

The reviewed positive-symbol rows are bounded to exactly 10 Cardova source ids. The repo does **not** store the images. `robot_kb_cardova_reviewed_rarity_symbol_proof.py` binds each review to:

- exact Cardova source ULID;
- exact PSA certificate;
- exact PMCG1 coordinate/card/grade/finish;
- exact public `image_a` filename;
- SHA-256 of the reviewed front image;
- reviewed visible symbol class (`star` or `circle`).

This evidence positively excludes `printing=no_rarity_symbol`; it does **not** invent a synthetic `printing=standard` value. TCGdex represents the ordinary source variant by absence of the printing dimension.

`robot_kb_cardova_rarity_symbol_microvariant_closure.py` reuses the existing legacy closure and activates only when the compatible immutable pinned source shape is exactly:

```text
ordinary variant: same dimensions, no printing axis
No Rarity variant: same dimensions + printing=no_rarity_symbol
```

Any extra compatible printing, opaque source token, or difference beyond the printing dimension remains fail-closed.

Expected live result after this bounded image proof: `37/38` exact microvariants. The only expected blocker is the Charizard `Error(Strength)` material variant.

## Safety

- absence of Cardova text never proves ordinary printing;
- visible rarity symbol is positive evidence;
- no image bytes stored in repo;
- no No Rarity => First Edition inference;
- no canonical link written by these probes;
- no Robot KB transaction written;
- no V4 economic use;
- no notification;
- no purchase, bid, offer, checkout or payment;
- PR #204 remains stacked on #199 and non-merged until explicit authorization.
