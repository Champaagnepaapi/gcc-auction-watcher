-- PostgreSQL parity for SQLite migration 0005_print_run_rarity_symbol.sql.
--
-- These are proof-preserving values on the existing generic print_run axis.
-- They are intentionally independent from edition_stamp:
--   NO_RARITY_SYMBOL      != First Edition
--   RARITY_SYMBOL_PRESENT != Unlimited / standard-by-default
--
-- Forward-only and additive; existing profiles/cards are not rewritten.

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
