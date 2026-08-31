-- PostgreSQL parity for SQLite migration 0005_print_run_rarity_symbol.sql.
--
-- These are proof-preserving values on the existing generic print_run axis.
-- They are intentionally independent from edition_stamp:
--   NO_RARITY_SYMBOL      != First Edition
--   RARITY_SYMBOL_PRESENT != Unlimited / standard-by-default
--
-- PostgreSQL 0001 is schema-only and does not seed the generic SQLite variant
-- registry.  This forward migration therefore bootstraps only the parent
-- print_run dimension + UNKNOWN value that it directly depends on.  It does
-- not backfill the rest of the historical registry or rewrite any profile/card.
-- Existing migrated Robot KB databases already carrying the exact seed rows are
-- accepted unchanged; conflicting pre-existing rows fail closed below.

INSERT INTO variant_dimension(id, code, name, created_at)
SELECT
    'vdim_print_run',
    'print_run',
    'Print run',
    '1970-01-01T00:00:00Z'
WHERE NOT EXISTS (
    SELECT 1
    FROM variant_dimension
    WHERE id = 'vdim_print_run' OR code = 'print_run'
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM variant_dimension
        WHERE id = 'vdim_print_run'
          AND code = 'print_run'
          AND name = 'Print run'
    ) THEN
        RAISE EXCEPTION 'conflicting print_run variant dimension';
    END IF;
END;
$$;

INSERT INTO variant_value(id, dimension_id, code, label, created_at)
SELECT
    'vval_print_run_unknown',
    'vdim_print_run',
    'UNKNOWN',
    'Unknown print run',
    '1970-01-01T00:00:00Z'
WHERE NOT EXISTS (
    SELECT 1
    FROM variant_value
    WHERE id = 'vval_print_run_unknown'
       OR (dimension_id = 'vdim_print_run' AND code = 'UNKNOWN')
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM variant_value
        WHERE id = 'vval_print_run_unknown'
          AND dimension_id = 'vdim_print_run'
          AND code = 'UNKNOWN'
          AND label = 'Unknown print run'
    ) THEN
        RAISE EXCEPTION 'conflicting UNKNOWN print_run variant value';
    END IF;
END;
$$;

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
