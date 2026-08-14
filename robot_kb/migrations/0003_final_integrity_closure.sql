-- Final targeted P0 integrity closure. 0001 and 0002 remain immutable.
-- This migration adds exact FX storage and closes action, lineage, identity,
-- and variant semantics at the direct-SQL boundary.

DROP TRIGGER fx_rate_observation_update_guard;
DROP TRIGGER fx_normalization_update_guard;

ALTER TABLE fx_rate_observation ADD COLUMN rate_numerator INTEGER;
ALTER TABLE fx_rate_observation ADD COLUMN rate_denominator INTEGER;
ALTER TABLE fx_normalization ADD COLUMN rate_numerator INTEGER;
ALTER TABLE fx_normalization ADD COLUMN rate_denominator INTEGER;

CREATE TABLE kb_final_integrity_assertion (
    invariant_name TEXT PRIMARY KEY,
    violation_count INTEGER NOT NULL CHECK (violation_count = 0)
);

INSERT INTO kb_final_integrity_assertion
SELECT 'external object upstream pair and role', COUNT(*)
FROM external_object AS object
WHERE (object.upstream_market_system_id IS NULL)
          <> (object.upstream_native_id IS NULL)
   OR (
       object.upstream_market_system_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM source_system AS upstream
           WHERE upstream.id = object.upstream_market_system_id
             AND upstream.system_role IN ('MARKET', 'LISTING_PLATFORM')
       )
   );

INSERT INTO kb_final_integrity_assertion
SELECT 'observation upstream role and event lineage', COUNT(*)
FROM market_observation AS observation
WHERE (
    observation.upstream_market_system_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM source_system AS upstream
        WHERE upstream.id = observation.upstream_market_system_id
          AND upstream.system_role IN ('MARKET', 'LISTING_PLATFORM')
    )
) OR (
    observation.upstream_event_object_id IS NOT NULL
    AND (
        observation.upstream_market_system_id IS NULL
        OR NOT EXISTS (
            SELECT 1 FROM external_object AS object
            WHERE object.id = observation.upstream_event_object_id
              AND (
                  object.source_system_id = observation.upstream_market_system_id
                  OR object.upstream_market_system_id =
                     observation.upstream_market_system_id
              )
        )
    )
);

INSERT INTO kb_final_integrity_assertion
SELECT 'observation identity subject traceability', COUNT(*)
FROM observation_identity_link AS link
JOIN identity_resolution AS resolution
  ON resolution.id = link.identity_resolution_id
JOIN identity_subject AS subject
  ON subject.id = resolution.identity_subject_id
JOIN market_observation AS observation ON observation.id = link.observation_id
WHERE NOT (
    (
        observation.source_record_id IS NOT NULL
        AND subject.source_record_id = observation.source_record_id
    )
    OR (
        subject.external_object_id IS NOT NULL
        AND (
            subject.external_object_id = observation.upstream_event_object_id
            OR EXISTS (
                SELECT 1 FROM source_record AS record
                WHERE record.id = observation.source_record_id
                  AND record.external_object_id = subject.external_object_id
            )
            OR EXISTS (
                SELECT 1 FROM external_object AS object
                WHERE object.id = subject.external_object_id
                  AND object.source_system_id = observation.source_system_id
                  AND object.source_native_id = observation.source_native_record_id
            )
        )
    )
);

INSERT INTO kb_final_integrity_assertion
SELECT 'canonical variant applicability closure', COUNT(*)
FROM canonical_card AS card
JOIN localized_card AS localized ON localized.id = card.localized_card_id
WHERE EXISTS (
    SELECT 1 FROM family_variant_applicability AS applicability
    WHERE applicability.card_family_id = localized.card_family_id
      AND applicability.applicability_state = 'UNKNOWN'
) OR EXISTS (
    SELECT 1 FROM family_variant_applicability AS applicability
    WHERE applicability.card_family_id = localized.card_family_id
      AND applicability.applicability_state = 'APPLICABLE'
      AND NOT EXISTS (
          SELECT 1 FROM variant_assignment AS assignment
          WHERE assignment.profile_id = card.variant_profile_id
            AND assignment.dimension_id = applicability.dimension_id
      )
) OR EXISTS (
    SELECT 1
    FROM family_variant_applicability AS applicability
    JOIN variant_assignment AS assignment
      ON assignment.profile_id = card.variant_profile_id
     AND assignment.dimension_id = applicability.dimension_id
    WHERE applicability.card_family_id = localized.card_family_id
      AND applicability.applicability_state = 'NOT_APPLICABLE'
) OR EXISTS (
    SELECT 1
    FROM family_variant_applicability AS applicability
    JOIN variant_assignment AS assignment
      ON assignment.profile_id = card.variant_profile_id
     AND assignment.dimension_id = applicability.dimension_id
    JOIN variant_value AS value ON value.id = assignment.value_id
    WHERE applicability.card_family_id = localized.card_family_id
      AND applicability.applicability_state = 'APPLICABLE'
      AND value.code = 'UNKNOWN'
);

INSERT INTO kb_final_integrity_assertion
SELECT 'cancel and void action semantics', COUNT(*)
FROM observation_relationship AS edge
JOIN market_observation AS action ON action.id = edge.from_observation_id
JOIN market_observation AS target ON target.id = edge.to_observation_id
WHERE edge.relationship_type IN ('CANCELS', 'VOIDS')
  AND NOT (
      action.lifecycle_state = 'SEALED'
      AND target.lifecycle_state = 'SEALED'
      AND action.observation_type = 'SALE_TRANSACTION'
      AND target.observation_type = 'SALE_TRANSACTION'
      AND EXISTS (
          SELECT 1 FROM sale_transaction AS sale
          WHERE sale.observation_id = action.id
            AND (
                (edge.relationship_type = 'CANCELS'
                 AND sale.transaction_status = 'CANCELLED')
                OR (edge.relationship_type = 'VOIDS'
                    AND sale.transaction_status = 'VOIDED')
            )
      )
      AND action.source_system_id = target.source_system_id
      AND action.source_native_record_id = target.source_native_record_id
      AND action.upstream_market_system_id IS target.upstream_market_system_id
      AND action.upstream_event_object_id IS target.upstream_event_object_id
      AND action.canonical_card_id IS target.canonical_card_id
  );

INSERT INTO kb_final_integrity_assertion
SELECT 'one cancellation meaning per action and target', COUNT(*)
FROM (
    SELECT from_observation_id, to_observation_id
    FROM observation_relationship
    WHERE relationship_type IN ('CANCELS', 'VOIDS')
    GROUP BY from_observation_id, to_observation_id
    HAVING COUNT(*) > 1
);

-- Only finite, positive, base-ten decimal strings with an exact signed
-- 64-bit numerator/denominator representation can enter the FX ledger.
INSERT INTO kb_final_integrity_assertion
SELECT 'FX decimal representation', COUNT(*)
FROM (
    SELECT rate_decimal FROM fx_rate_observation
    UNION ALL
    SELECT fx_rate_decimal AS rate_decimal FROM fx_normalization
)
WHERE rate_decimal = ''
   OR rate_decimal GLOB '*[^0-9.]*'
   OR substr(rate_decimal, 1, 1) = '.'
   OR substr(rate_decimal, -1, 1) = '.'
   OR length(rate_decimal) - length(replace(rate_decimal, '.', '')) > 1
   OR CASE
          WHEN instr(rate_decimal, '.') = 0 THEN 0
          ELSE length(rate_decimal) - instr(rate_decimal, '.')
      END > 18
   OR length(ltrim(replace(rate_decimal, '.', ''), '0')) NOT BETWEEN 1 AND 18;

UPDATE fx_rate_observation
SET rate_numerator = CAST(replace(rate_decimal, '.', '') AS INTEGER),
    rate_denominator = CASE
        WHEN instr(rate_decimal, '.') = 0 THEN 1
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 1 THEN 10
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 2 THEN 100
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 3 THEN 1000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 4 THEN 10000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 5 THEN 100000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 6 THEN 1000000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 7 THEN 10000000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 8 THEN 100000000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 9 THEN 1000000000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 10 THEN 10000000000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 11 THEN 100000000000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 12 THEN 1000000000000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 13 THEN 10000000000000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 14 THEN 100000000000000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 15 THEN 1000000000000000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 16 THEN 10000000000000000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 17 THEN 100000000000000000
        WHEN length(rate_decimal) - instr(rate_decimal, '.') = 18 THEN 1000000000000000000
    END;

UPDATE fx_normalization
SET rate_numerator = CAST(replace(fx_rate_decimal, '.', '') AS INTEGER),
    rate_denominator = CASE
        WHEN instr(fx_rate_decimal, '.') = 0 THEN 1
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 1 THEN 10
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 2 THEN 100
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 3 THEN 1000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 4 THEN 10000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 5 THEN 100000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 6 THEN 1000000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 7 THEN 10000000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 8 THEN 100000000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 9 THEN 1000000000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 10 THEN 10000000000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 11 THEN 100000000000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 12 THEN 1000000000000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 13 THEN 10000000000000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 14 THEN 100000000000000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 15 THEN 1000000000000000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 16 THEN 10000000000000000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 17 THEN 100000000000000000
        WHEN length(fx_rate_decimal) - instr(fx_rate_decimal, '.') = 18 THEN 1000000000000000000
    END;

INSERT INTO kb_final_integrity_assertion
SELECT 'FX exact arithmetic', COUNT(*)
FROM fx_normalization AS fx
WHERE CASE
    WHEN fx.rate_numerator IS NULL OR fx.rate_denominator IS NULL THEN 1
    WHEN fx.rate_numerator <= 0 OR fx.rate_denominator <= 0 THEN 1
    WHEN fx.original_amount_minor < 0 THEN 1
    WHEN fx.original_amount_minor
         > 9223372036854775807 / fx.rate_numerator THEN 1
    ELSE fx.target_amount_minor <> (
        (fx.original_amount_minor * fx.rate_numerator) / fx.rate_denominator
        + CASE WHEN
            (fx.original_amount_minor * fx.rate_numerator) % fx.rate_denominator
                >= fx.rate_denominator / 2 + fx.rate_denominator % 2
          THEN 1 ELSE 0 END
    )
END;

DROP TABLE kb_final_integrity_assertion;

CREATE TRIGGER external_object_upstream_integrity_guard
BEFORE INSERT ON external_object
BEGIN
    SELECT CASE WHEN
        (NEW.upstream_market_system_id IS NULL)
            <> (NEW.upstream_native_id IS NULL)
    THEN RAISE(ABORT, 'upstream marketplace system and native ID must be paired') END;
    SELECT CASE WHEN NEW.upstream_market_system_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM source_system AS upstream
        WHERE upstream.id = NEW.upstream_market_system_id
          AND upstream.system_role IN ('MARKET', 'LISTING_PLATFORM')
    ) THEN RAISE(ABORT, 'external object upstream system is not a marketplace') END;
END;

DROP TRIGGER market_observation_upstream_lineage_guard;
CREATE TRIGGER market_observation_upstream_lineage_guard
BEFORE INSERT ON market_observation
BEGIN
    SELECT CASE WHEN NEW.upstream_market_system_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM source_system AS upstream
        WHERE upstream.id = NEW.upstream_market_system_id
          AND upstream.system_role IN ('MARKET', 'LISTING_PLATFORM')
    ) THEN RAISE(ABORT, 'observation upstream system is not a marketplace') END;
    SELECT CASE WHEN NEW.upstream_event_object_id IS NOT NULL AND (
        NEW.upstream_market_system_id IS NULL
        OR NOT EXISTS (
            SELECT 1 FROM external_object AS object
            WHERE object.id = NEW.upstream_event_object_id
              AND (
                  object.source_system_id = NEW.upstream_market_system_id
                  OR object.upstream_market_system_id = NEW.upstream_market_system_id
              )
        )
    ) THEN RAISE(ABORT, 'upstream event object is incompatible with marketplace') END;
END;

DROP TRIGGER observation_identity_link_integrity_guard;
CREATE TRIGGER observation_identity_link_integrity_guard
BEFORE INSERT ON observation_identity_link
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM identity_resolution AS resolution
        JOIN identity_subject AS subject
          ON subject.id = resolution.identity_subject_id
        JOIN market_observation AS observation ON observation.id = NEW.observation_id
        WHERE resolution.id = NEW.identity_resolution_id
          AND (
              (observation.source_record_id IS NOT NULL
               AND subject.source_record_id = observation.source_record_id)
              OR (
                  subject.external_object_id IS NOT NULL
                  AND (
                      subject.external_object_id = observation.upstream_event_object_id
                      OR EXISTS (
                          SELECT 1 FROM source_record AS record
                          WHERE record.id = observation.source_record_id
                            AND record.external_object_id = subject.external_object_id
                      )
                      OR EXISTS (
                          SELECT 1 FROM external_object AS object
                          WHERE object.id = subject.external_object_id
                            AND object.source_system_id = observation.source_system_id
                            AND object.source_native_id = observation.source_native_record_id
                      )
                  )
              )
          )
    ) THEN RAISE(ABORT, 'identity subject is unrelated to observation') END;
    SELECT CASE WHEN NEW.link_role = 'SUBJECT' AND NEW.canonical_card_id IS NOT NULL THEN
        RAISE(ABORT, 'subject identity link cannot select a canonical card')
    END;
    SELECT CASE WHEN NEW.link_role = 'RESOLVED_AS' AND NOT EXISTS (
        SELECT 1
        FROM identity_resolution AS resolution
        JOIN market_observation AS observation ON observation.id = NEW.observation_id
        WHERE resolution.id = NEW.identity_resolution_id
          AND resolution.resolution_state IN ('PROVEN', 'SUPPORTED')
          AND resolution.canonical_card_id IS NOT NULL
          AND resolution.canonical_card_id = NEW.canonical_card_id
          AND observation.canonical_card_id IS NOT NULL
          AND observation.canonical_card_id = NEW.canonical_card_id
    ) THEN RAISE(ABORT, 'resolved observation identity is inconsistent') END;
END;

CREATE TRIGGER canonical_card_variant_closure_guard
BEFORE INSERT ON canonical_card
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM localized_card AS localized
        JOIN family_variant_applicability AS applicability
          ON applicability.card_family_id = localized.card_family_id
        WHERE localized.id = NEW.localized_card_id
          AND applicability.applicability_state = 'UNKNOWN'
    ) THEN RAISE(ABORT, 'canonical variant applicability is not closed') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM localized_card AS localized
        JOIN family_variant_applicability AS applicability
          ON applicability.card_family_id = localized.card_family_id
         AND applicability.applicability_state = 'APPLICABLE'
        JOIN variant_assignment AS assignment
          ON assignment.profile_id = NEW.variant_profile_id
         AND assignment.dimension_id = applicability.dimension_id
        JOIN variant_value AS value ON value.id = assignment.value_id
        WHERE localized.id = NEW.localized_card_id
          AND value.code = 'UNKNOWN'
    ) THEN RAISE(ABORT, 'exact canonical variant contains an unknown value') END;
END;

CREATE TRIGGER family_variant_applicability_unknown_insert_guard
BEFORE INSERT ON family_variant_applicability
WHEN NEW.applicability_state = 'UNKNOWN'
 AND EXISTS (
    SELECT 1
    FROM localized_card AS localized
    JOIN canonical_card AS card ON card.localized_card_id = localized.id
    WHERE localized.card_family_id = NEW.card_family_id
 )
BEGIN
    SELECT RAISE(ABORT, 'unknown applicability would invalidate a canonical card');
END;

CREATE TRIGGER family_variant_applicability_exact_value_insert_guard
BEFORE INSERT ON family_variant_applicability
WHEN NEW.applicability_state = 'APPLICABLE'
 AND EXISTS (
    SELECT 1
    FROM localized_card AS localized
    JOIN canonical_card AS card ON card.localized_card_id = localized.id
    JOIN variant_assignment AS assignment
      ON assignment.profile_id = card.variant_profile_id
     AND assignment.dimension_id = NEW.dimension_id
    JOIN variant_value AS value ON value.id = assignment.value_id
    WHERE localized.card_family_id = NEW.card_family_id
      AND value.code = 'UNKNOWN'
 )
BEGIN
    SELECT RAISE(ABORT, 'applicable unknown value would invalidate an exact card');
END;

DROP TRIGGER observation_cancel_void_relationship_guard;
CREATE UNIQUE INDEX observation_one_cancel_or_void_meaning
    ON observation_relationship(from_observation_id, to_observation_id)
    WHERE relationship_type IN ('CANCELS', 'VOIDS');

CREATE TRIGGER observation_cancel_void_relationship_guard
BEFORE INSERT ON observation_relationship
WHEN NEW.relationship_type IN ('CANCELS', 'VOIDS')
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM market_observation AS action
        JOIN market_observation AS target ON target.id = NEW.to_observation_id
        JOIN sale_transaction AS action_sale
          ON action_sale.observation_id = action.id
        WHERE action.id = NEW.from_observation_id
          AND action.lifecycle_state = 'SEALED'
          AND target.lifecycle_state = 'SEALED'
          AND action.observation_type = 'SALE_TRANSACTION'
          AND target.observation_type = 'SALE_TRANSACTION'
          AND (
              (NEW.relationship_type = 'CANCELS'
               AND action_sale.transaction_status = 'CANCELLED')
              OR (NEW.relationship_type = 'VOIDS'
                  AND action_sale.transaction_status = 'VOIDED')
          )
          AND action.source_system_id = target.source_system_id
          AND action.source_native_record_id = target.source_native_record_id
          AND action.upstream_market_system_id IS target.upstream_market_system_id
          AND action.upstream_event_object_id IS target.upstream_event_object_id
          AND action.canonical_card_id IS target.canonical_card_id
    ) THEN RAISE(ABORT, 'cancel/void action status or target is incompatible') END;
    WITH RECURSIVE targets(id) AS (
        SELECT NEW.to_observation_id
        UNION ALL
        SELECT relationship.to_observation_id
        FROM observation_relationship AS relationship
        JOIN targets ON relationship.from_observation_id = targets.id
        WHERE relationship.relationship_type IN ('CANCELS', 'VOIDS')
    )
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM targets WHERE id = NEW.from_observation_id
    ) THEN RAISE(ABORT, 'cancel/void relationship cycle') END;
END;

CREATE TRIGGER fx_rate_observation_exact_guard
BEFORE INSERT ON fx_rate_observation
BEGIN
    SELECT CASE WHEN
        NEW.rate_decimal = ''
        OR NEW.rate_decimal GLOB '*[^0-9.]*'
        OR substr(NEW.rate_decimal, 1, 1) = '.'
        OR substr(NEW.rate_decimal, -1, 1) = '.'
        OR length(NEW.rate_decimal) - length(replace(NEW.rate_decimal, '.', '')) > 1
        OR CASE
               WHEN instr(NEW.rate_decimal, '.') = 0 THEN 0
               ELSE length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.')
           END > 18
        OR length(ltrim(replace(NEW.rate_decimal, '.', ''), '0'))
             NOT BETWEEN 1 AND 18
        OR NEW.rate_numerator IS NOT
             CAST(replace(NEW.rate_decimal, '.', '') AS INTEGER)
        OR NEW.rate_denominator IS NOT CASE
            WHEN instr(NEW.rate_decimal, '.') = 0 THEN 1
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 1 THEN 10
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 2 THEN 100
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 3 THEN 1000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 4 THEN 10000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 5 THEN 100000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 6 THEN 1000000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 7 THEN 10000000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 8 THEN 100000000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 9 THEN 1000000000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 10 THEN 10000000000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 11 THEN 100000000000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 12 THEN 1000000000000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 13 THEN 10000000000000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 14 THEN 100000000000000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 15 THEN 1000000000000000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 16 THEN 10000000000000000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 17 THEN 100000000000000000
            WHEN length(NEW.rate_decimal) - instr(NEW.rate_decimal, '.') = 18 THEN 1000000000000000000
        END
    THEN RAISE(ABORT, 'FX rate must use an exact positive decimal representation') END;
END;

DROP TRIGGER fx_normalization_integrity_guard;
CREATE TRIGGER fx_normalization_integrity_guard
BEFORE INSERT ON fx_normalization
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM price_component AS component
        JOIN market_observation AS observation
          ON observation.id = component.observation_id
        WHERE component.id = NEW.price_component_id
          AND component.observation_id = NEW.observation_id
          AND component.component_type = NEW.component_type
          AND component.knowledge_state = 'KNOWN'
          AND component.amount_minor = NEW.original_amount_minor
          AND component.currency = NEW.original_currency
          AND NEW.original_amount_minor >= 0
          AND NEW.target_amount_minor >= 0
          AND length(NEW.original_currency) = 3
          AND length(NEW.target_currency) = 3
          AND observation.lifecycle_state = 'DRAFT'
    ) THEN RAISE(ABORT, 'FX normalization does not match its exact price component') END;
    SELECT CASE WHEN NEW.rate_observation_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM market_observation AS envelope
        JOIN fx_rate_observation AS rate ON rate.observation_id = envelope.id
        WHERE envelope.id = NEW.rate_observation_id
          AND envelope.lifecycle_state = 'SEALED'
          AND rate.base_currency = NEW.original_currency
          AND rate.quote_currency = NEW.target_currency
          AND rate.rate_decimal = NEW.fx_rate_decimal
          AND rate.rate_numerator = NEW.rate_numerator
          AND rate.rate_denominator = NEW.rate_denominator
          AND rate.effective_date = NEW.rate_effective_date
          AND rate.rate_source = NEW.rate_source
    ) THEN RAISE(ABORT, 'FX rate observation does not match normalization lineage') END;
    SELECT CASE WHEN
        NEW.fx_rate_decimal = ''
        OR NEW.fx_rate_decimal GLOB '*[^0-9.]*'
        OR substr(NEW.fx_rate_decimal, 1, 1) = '.'
        OR substr(NEW.fx_rate_decimal, -1, 1) = '.'
        OR length(NEW.fx_rate_decimal)
             - length(replace(NEW.fx_rate_decimal, '.', '')) > 1
        OR CASE
               WHEN instr(NEW.fx_rate_decimal, '.') = 0 THEN 0
               ELSE length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.')
           END > 18
        OR length(ltrim(replace(NEW.fx_rate_decimal, '.', ''), '0'))
             NOT BETWEEN 1 AND 18
        OR NEW.rate_numerator IS NOT
             CAST(replace(NEW.fx_rate_decimal, '.', '') AS INTEGER)
        OR NEW.rate_denominator IS NOT CASE
            WHEN instr(NEW.fx_rate_decimal, '.') = 0 THEN 1
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 1 THEN 10
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 2 THEN 100
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 3 THEN 1000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 4 THEN 10000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 5 THEN 100000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 6 THEN 1000000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 7 THEN 10000000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 8 THEN 100000000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 9 THEN 1000000000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 10 THEN 10000000000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 11 THEN 100000000000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 12 THEN 1000000000000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 13 THEN 10000000000000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 14 THEN 100000000000000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 15 THEN 1000000000000000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 16 THEN 10000000000000000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 17 THEN 100000000000000000
            WHEN length(NEW.fx_rate_decimal) - instr(NEW.fx_rate_decimal, '.') = 18 THEN 1000000000000000000
        END
        OR CASE
            WHEN NEW.rate_numerator IS NULL OR NEW.rate_denominator IS NULL THEN 1
            WHEN NEW.rate_numerator <= 0 OR NEW.rate_denominator <= 0 THEN 1
            WHEN NEW.original_amount_minor < 0 THEN 1
            WHEN NEW.original_amount_minor
                 > 9223372036854775807 / NEW.rate_numerator THEN 1
            ELSE NEW.target_amount_minor <> (
                (NEW.original_amount_minor * NEW.rate_numerator)
                    / NEW.rate_denominator
                + CASE WHEN
                    (NEW.original_amount_minor * NEW.rate_numerator)
                        % NEW.rate_denominator
                        >= NEW.rate_denominator / 2 + NEW.rate_denominator % 2
                  THEN 1 ELSE 0 END
            )
        END
    THEN RAISE(ABORT, 'FX normalization requires exact round-half-up arithmetic') END;
END;

CREATE TRIGGER fx_rate_observation_update_guard BEFORE UPDATE ON fx_rate_observation
BEGIN SELECT RAISE(ABORT, 'FX facts are append-only'); END;
CREATE TRIGGER fx_normalization_update_guard BEFORE UPDATE ON fx_normalization
BEGIN SELECT RAISE(ABORT, 'FX normalizations are append-only'); END;
