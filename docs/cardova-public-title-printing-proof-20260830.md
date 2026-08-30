# Cardova public title printing proof — 2026-08-30

Scope: read-only Robot KB identity evidence stacked on PR #199. No V4 economic use and no Robot KB write.

Observed exact public Cardova pages:

- `01KFFRJ8B4X9FG8YK90K4BNS1T` / Ninetales PSA 10: exact title contains `No Rarity Original Print` with no trailing material qualifier. This can positively prove `printing=no_rarity_symbol`; it does not prove First Edition.
- `01KQHACBX20NBMGD9VZAPA6Z64` / Charizard PSA 8: exact title contains `No Rarity Original Print Error(Strength)`. The trailing `Error(Strength)` is a material microvariant token and blocks collapsing the row into plain No Rarity.
- A Cardova title that omits `No Rarity Original Print` does not prove standard/ordinary printing.

The parser in `robot_kb_cardova_public_title_printing_proof.py` is pure and fail-closed. Network acquisition remains a separate read-only diagnostic surface.
