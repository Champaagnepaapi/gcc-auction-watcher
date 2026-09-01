-- Extend the existing generic print_run axis with proof-preserving Japanese
-- rarity-symbol states. These values are deliberately orthogonal to
-- edition_stamp: NO_RARITY_SYMBOL never means First Edition, and
-- RARITY_SYMBOL_PRESENT never means Unlimited or a synthetic standard run.
--
-- This is a forward-only additive registry migration. Existing profiles and
-- canonical cards are unchanged.

INSERT INTO variant_value(id, dimension_id, code, label, created_at) VALUES
    (
        'vval_print_run_no_rarity_symbol',
        'vdim_print_run',
        'NO_RARITY_SYMBOL',
        'No rarity symbol',
        '1970-01-01T00:00:00Z'
    ),
    (
        'vval_print_run_rarity_symbol_present',
        'vdim_print_run',
        'RARITY_SYMBOL_PRESENT',
        'Rarity symbol present',
        '1970-01-01T00:00:00Z'
    );
