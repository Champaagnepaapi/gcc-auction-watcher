-- Targeted Red Team integrity remediation.
-- 0001 remains immutable; this migration upgrades both fresh and existing P0
-- databases without treating incomplete legacy facts as completed facts.

DROP TRIGGER variant_profile_update_guard;
DROP TRIGGER canonical_card_update_guard;
DROP TRIGGER market_observation_update_guard;
DROP TRIGGER fx_normalization_update_guard;
DROP TRIGGER field_resolution_evidence_guard;
DROP TRIGGER field_resolution_claim_subject_guard;

ALTER TABLE variant_profile ADD COLUMN semantic_key TEXT;
ALTER TABLE market_observation ADD COLUMN lifecycle_state TEXT NOT NULL
    DEFAULT 'DRAFT' CHECK (lifecycle_state IN ('DRAFT', 'SEALED'));
ALTER TABLE market_observation ADD COLUMN sealed_at TEXT;
ALTER TABLE fx_normalization ADD COLUMN price_component_id TEXT
    REFERENCES price_component(id);

CREATE TABLE source_record_retrieval (
    id TEXT PRIMARY KEY CHECK (id LIKE 'sretrieval_%'),
    source_record_id TEXT NOT NULL REFERENCES source_record(id),
    external_object_id TEXT REFERENCES external_object(id),
    retrieved_at TEXT NOT NULL,
    source_updated_at TEXT,
    lineage_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

-- Preserve the original 0001 retrieval as the first explicit occurrence.
INSERT INTO source_record_retrieval(
    id, source_record_id, external_object_id, retrieved_at,
    source_updated_at, lineage_key, created_at
)
SELECT
    'sretrieval_' || substr(id, 9), id, external_object_id, retrieved_at,
    source_updated_at, 'legacy:' || id, created_at
FROM source_record;

-- Canonical semantic identity is derived from the immutable assignments, not
-- from a caller-provided fingerprint.
UPDATE variant_profile
SET semantic_key = (
    SELECT group_concat(pair, '|')
    FROM (
        SELECT d.code || '=' || v.code AS pair
        FROM variant_assignment AS a
        JOIN variant_dimension AS d ON d.id = a.dimension_id
        JOIN variant_value AS v ON v.id = a.value_id
        WHERE a.profile_id = variant_profile.id
        ORDER BY d.code
    )
);

CREATE UNIQUE INDEX variant_profile_semantic_key_unique
    ON variant_profile(semantic_key)
    WHERE semantic_key IS NOT NULL;

-- Bind every exact comparison identity to the localized card and canonical
-- semantic variant representation.
UPDATE canonical_card
SET exact_comparison_key = (
    SELECT 'cardcmp|' || canonical_card.localized_card_id || '|' || p.semantic_key
    FROM variant_profile AS p
    WHERE p.id = canonical_card.variant_profile_id
);

-- Link legacy FX normalization rows to the exact original price component.
UPDATE fx_normalization
SET price_component_id = (
    SELECT pc.id
    FROM price_component AS pc
    WHERE pc.observation_id = fx_normalization.observation_id
      AND pc.component_type = fx_normalization.component_type
);

-- Forward constraints do not retroactively inspect 0001 rows. Refuse the
-- upgrade atomically if legacy data already violates a hardened invariant;
-- never silently bless or overwrite corrupt historical facts.
CREATE TABLE kb_integrity_migration_assertion (
    invariant_name TEXT PRIMARY KEY,
    violation_count INTEGER NOT NULL CHECK (violation_count = 0)
);

INSERT INTO kb_integrity_migration_assertion
SELECT 'field resolution evidence', COUNT(*)
FROM field_resolution AS r
WHERE (
    r.resolution_state IN ('PROVEN', 'SUPPORTED')
    AND NOT EXISTS (
        SELECT 1 FROM field_claim AS c
        WHERE c.id = r.based_on_claim_id
          AND c.claim_role = 'EVIDENCE'
          AND c.claimed_value_json IS NOT NULL
          AND c.identity_subject_id = r.identity_subject_id
          AND c.field_name = r.field_name
          AND c.claimed_value_json = r.resolved_value_json
          AND (
              (r.resolution_state = 'PROVEN' AND c.resolution_state = 'PROVEN')
              OR
              (r.resolution_state = 'SUPPORTED'
               AND c.resolution_state IN ('PROVEN', 'SUPPORTED'))
          )
    )
) OR (
    r.resolution_state IN ('UNKNOWN', 'CONFLICT')
    AND r.resolved_value_json IS NOT NULL
);

INSERT INTO kb_integrity_migration_assertion
SELECT 'field resolution supersession', COUNT(*)
FROM field_resolution AS r
WHERE r.supersedes_resolution_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM field_resolution AS old
      WHERE old.id = r.supersedes_resolution_id
        AND old.identity_subject_id = r.identity_subject_id
        AND old.field_name = r.field_name
  );

INSERT INTO kb_integrity_migration_assertion
WITH RECURSIVE field_reach(from_id, to_id) AS (
    SELECT id, supersedes_resolution_id
    FROM field_resolution
    WHERE supersedes_resolution_id IS NOT NULL
    UNION
    SELECT reach.from_id, resolution.supersedes_resolution_id
    FROM field_reach AS reach
    JOIN field_resolution AS resolution ON resolution.id = reach.to_id
    WHERE resolution.supersedes_resolution_id IS NOT NULL
)
SELECT 'field resolution supersession cycle', COUNT(*)
FROM field_reach
WHERE from_id = to_id;

INSERT INTO kb_integrity_migration_assertion
SELECT 'identifier mapping state', COUNT(*)
FROM identifier_link
WHERE (resolution_state = 'PROVEN' AND canonical_card_id IS NULL)
   OR (resolution_state IN ('UNKNOWN', 'CONFLICT')
       AND canonical_card_id IS NOT NULL);

INSERT INTO kb_integrity_migration_assertion
SELECT 'identity resolution state', COUNT(*)
FROM identity_resolution
WHERE resolution_state IN ('UNKNOWN', 'CONFLICT')
  AND canonical_card_id IS NOT NULL;

INSERT INTO kb_integrity_migration_assertion
SELECT 'observation identity link', COUNT(*)
FROM observation_identity_link AS link
WHERE (link.link_role = 'SUBJECT' AND link.canonical_card_id IS NOT NULL)
   OR (
       link.link_role = 'RESOLVED_AS'
       AND NOT EXISTS (
           SELECT 1
           FROM identity_resolution AS r
           JOIN market_observation AS o ON o.id = link.observation_id
           WHERE r.id = link.identity_resolution_id
             AND r.resolution_state IN ('PROVEN', 'SUPPORTED')
             AND r.canonical_card_id IS NOT NULL
             AND r.canonical_card_id = link.canonical_card_id
             AND o.canonical_card_id IS NOT NULL
             AND o.canonical_card_id = link.canonical_card_id
       )
   );

INSERT INTO kb_integrity_migration_assertion
SELECT 'canonical variant integrity', COUNT(*)
FROM canonical_card AS c
JOIN localized_card AS l ON l.id = c.localized_card_id
JOIN variant_profile AS p ON p.id = c.variant_profile_id
WHERE p.locked_at IS NULL
   OR p.semantic_key IS NULL
   OR NOT EXISTS (
       SELECT 1 FROM allowed_variant_combination AS allowed
       WHERE allowed.card_family_id = l.card_family_id
         AND allowed.variant_profile_id = c.variant_profile_id
   )
   OR EXISTS (
       SELECT 1 FROM family_variant_applicability AS applicable
       WHERE applicable.card_family_id = l.card_family_id
         AND applicable.applicability_state = 'APPLICABLE'
         AND NOT EXISTS (
             SELECT 1 FROM variant_assignment AS assignment
             WHERE assignment.profile_id = c.variant_profile_id
               AND assignment.dimension_id = applicable.dimension_id
         )
   )
   OR EXISTS (
       SELECT 1
       FROM family_variant_applicability AS not_applicable
       JOIN variant_assignment AS assignment
         ON assignment.profile_id = c.variant_profile_id
        AND assignment.dimension_id = not_applicable.dimension_id
       WHERE not_applicable.card_family_id = l.card_family_id
         AND not_applicable.applicability_state = 'NOT_APPLICABLE'
   );

INSERT INTO kb_integrity_migration_assertion
SELECT 'upstream marketplace lineage', COUNT(*)
FROM market_observation AS o
WHERE o.upstream_event_object_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM external_object AS e
      JOIN source_system AS s ON s.id = e.source_system_id
      WHERE e.id = o.upstream_event_object_id
        AND e.source_system_id = o.upstream_market_system_id
        AND s.system_role IN ('MARKET', 'LISTING_PLATFORM')
  );

INSERT INTO kb_integrity_migration_assertion
SELECT 'price component state', COUNT(*)
FROM price_component AS pc
JOIN market_observation AS o ON o.id = pc.observation_id
WHERE o.observation_type NOT IN (
          'SALE_TRANSACTION', 'LISTING_SNAPSHOT',
          'PROVIDER_METRIC_OBSERVATION'
      )
   OR NOT (
       (
           pc.knowledge_state = 'KNOWN'
           AND pc.amount_minor IS NOT NULL
           AND pc.amount_minor >= 0
           AND pc.currency IS NOT NULL
           AND length(pc.currency) = 3
           AND pc.inclusion_state IN ('INCLUDED', 'EXCLUDED', 'UNKNOWN')
       )
       OR (
           pc.knowledge_state = 'UNKNOWN'
           AND pc.amount_minor IS NULL
           AND pc.currency IS NULL
           AND pc.inclusion_state = 'UNKNOWN'
       )
       OR (
           pc.knowledge_state = 'NOT_APPLICABLE'
           AND pc.amount_minor IS NULL
           AND pc.currency IS NULL
           AND pc.inclusion_state = 'NOT_APPLICABLE'
       )
   );

INSERT INTO kb_integrity_migration_assertion
SELECT 'FX component lineage', COUNT(*)
FROM fx_normalization AS fx
WHERE NOT EXISTS (
    SELECT 1 FROM price_component AS pc
    WHERE pc.id = fx.price_component_id
      AND pc.observation_id = fx.observation_id
      AND pc.component_type = fx.component_type
      AND pc.knowledge_state = 'KNOWN'
      AND pc.amount_minor = fx.original_amount_minor
      AND pc.currency = fx.original_currency
      AND fx.original_amount_minor >= 0
      AND fx.target_amount_minor >= 0
      AND length(fx.original_currency) = 3
      AND length(fx.target_currency) = 3
)
OR (
    fx.rate_observation_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM fx_rate_observation AS rate
        WHERE rate.observation_id = fx.rate_observation_id
          AND rate.base_currency = fx.original_currency
          AND rate.quote_currency = fx.target_currency
          AND rate.rate_decimal = fx.fx_rate_decimal
          AND rate.effective_date = fx.rate_effective_date
          AND rate.rate_source = fx.rate_source
    )
);

INSERT INTO kb_integrity_migration_assertion
SELECT 'revision projection', COUNT(*)
FROM market_observation AS current
WHERE (
    current.revision_of_observation_id IS NULL
    AND EXISTS (
        SELECT 1 FROM observation_relationship AS edge
        WHERE edge.from_observation_id = current.id
          AND edge.relationship_type = 'REVISION_OF'
    )
) OR (
    current.revision_of_observation_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1
        FROM market_observation AS old
        JOIN observation_relationship AS edge
          ON edge.from_observation_id = current.id
         AND edge.to_observation_id = old.id
         AND edge.relationship_type = 'REVISION_OF'
        WHERE old.id = current.revision_of_observation_id
          AND old.observation_type = current.observation_type
          AND old.source_system_id = current.source_system_id
          AND old.source_native_record_id = current.source_native_record_id
          AND old.upstream_market_system_id IS current.upstream_market_system_id
          AND old.upstream_event_object_id IS current.upstream_event_object_id
          AND (
              (old.observation_type = 'SALE_TRANSACTION' AND EXISTS (
                  SELECT 1 FROM sale_transaction
                  WHERE observation_id = old.id
              ))
              OR (old.observation_type = 'LISTING_SNAPSHOT' AND EXISTS (
                  SELECT 1 FROM listing_snapshot
                  WHERE observation_id = old.id
              ))
              OR (old.observation_type = 'PROVIDER_METRIC_OBSERVATION' AND EXISTS (
                  SELECT 1 FROM provider_metric_observation
                  WHERE observation_id = old.id
              ))
              OR (old.observation_type = 'POPULATION_OBSERVATION' AND EXISTS (
                  SELECT 1 FROM population_observation
                  WHERE observation_id = old.id
              ))
              OR (old.observation_type = 'FX_RATE_OBSERVATION' AND EXISTS (
                  SELECT 1 FROM fx_rate_observation
                  WHERE observation_id = old.id
              ))
          )
    )
) OR (
    SELECT COUNT(*) FROM observation_relationship AS edge
    WHERE edge.from_observation_id = current.id
      AND edge.relationship_type = 'REVISION_OF'
) > 1;

INSERT INTO kb_integrity_migration_assertion
WITH RECURSIVE revision_reach(from_id, to_id) AS (
    SELECT from_observation_id, to_observation_id
    FROM observation_relationship
    WHERE relationship_type = 'REVISION_OF'
    UNION
    SELECT reach.from_id, edge.to_observation_id
    FROM revision_reach AS reach
    JOIN observation_relationship AS edge
      ON edge.from_observation_id = reach.to_id
    WHERE edge.relationship_type = 'REVISION_OF'
)
SELECT 'revision cycle', COUNT(*)
FROM revision_reach
WHERE from_id = to_id;

INSERT INTO kb_integrity_migration_assertion
SELECT 'cancel or void compatibility', COUNT(*)
FROM observation_relationship AS edge
JOIN market_observation AS action ON action.id = edge.from_observation_id
JOIN market_observation AS target ON target.id = edge.to_observation_id
WHERE edge.relationship_type IN ('CANCELS', 'VOIDS')
  AND NOT (
      action.observation_type = target.observation_type
      AND action.source_system_id = target.source_system_id
      AND action.source_native_record_id = target.source_native_record_id
      AND action.upstream_market_system_id IS target.upstream_market_system_id
      AND action.upstream_event_object_id IS target.upstream_event_object_id
      AND action.canonical_card_id IS target.canonical_card_id
  );

INSERT INTO kb_integrity_migration_assertion
WITH RECURSIVE action_reach(from_id, to_id) AS (
    SELECT from_observation_id, to_observation_id
    FROM observation_relationship
    WHERE relationship_type IN ('CANCELS', 'VOIDS')
    UNION
    SELECT reach.from_id, edge.to_observation_id
    FROM action_reach AS reach
    JOIN observation_relationship AS edge
      ON edge.from_observation_id = reach.to_id
    WHERE edge.relationship_type IN ('CANCELS', 'VOIDS')
)
SELECT 'cancel or void cycle', COUNT(*)
FROM action_reach
WHERE from_id = to_id;

DROP TABLE kb_integrity_migration_assertion;

-- Existing complete 0001 observations become sealed. Any incomplete or
-- internally inconsistent legacy observation remains visibly DRAFT.
UPDATE market_observation
SET lifecycle_state = 'SEALED', sealed_at = created_at
WHERE (
       (observation_type = 'SALE_TRANSACTION' AND EXISTS (
            SELECT 1 FROM sale_transaction AS s WHERE s.observation_id = market_observation.id
        ))
    OR (observation_type = 'LISTING_SNAPSHOT' AND EXISTS (
            SELECT 1 FROM listing_snapshot AS l WHERE l.observation_id = market_observation.id
        ))
    OR (observation_type = 'PROVIDER_METRIC_OBSERVATION' AND EXISTS (
            SELECT 1 FROM provider_metric_observation AS p WHERE p.observation_id = market_observation.id
        ))
    OR (observation_type = 'POPULATION_OBSERVATION' AND EXISTS (
            SELECT 1 FROM population_observation AS p WHERE p.observation_id = market_observation.id
        ))
    OR (observation_type = 'FX_RATE_OBSERVATION' AND EXISTS (
            SELECT 1 FROM fx_rate_observation AS f WHERE f.observation_id = market_observation.id
        ))
)
AND (
    (
        revision_of_observation_id IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM observation_relationship AS r
            WHERE r.from_observation_id = market_observation.id
              AND r.relationship_type = 'REVISION_OF'
        )
    )
    OR
    (
        revision_of_observation_id IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM observation_relationship AS r
            WHERE r.from_observation_id = market_observation.id
              AND r.to_observation_id = market_observation.revision_of_observation_id
              AND r.relationship_type = 'REVISION_OF'
        )
        AND NOT EXISTS (
            SELECT 1 FROM observation_relationship AS r
            WHERE r.from_observation_id = market_observation.id
              AND r.relationship_type = 'REVISION_OF'
              AND r.to_observation_id <> market_observation.revision_of_observation_id
        )
    )
)
AND NOT EXISTS (
    SELECT 1 FROM price_component AS pc
    WHERE pc.observation_id = market_observation.id
      AND (
          market_observation.observation_type NOT IN (
              'SALE_TRANSACTION', 'LISTING_SNAPSHOT',
              'PROVIDER_METRIC_OBSERVATION'
          )
          OR NOT (
              (
                  pc.knowledge_state = 'KNOWN'
                  AND pc.amount_minor IS NOT NULL
                  AND pc.amount_minor >= 0
                  AND pc.currency IS NOT NULL
                  AND length(pc.currency) = 3
                  AND pc.inclusion_state IN ('INCLUDED', 'EXCLUDED', 'UNKNOWN')
              )
              OR (
                  pc.knowledge_state = 'UNKNOWN'
                  AND pc.amount_minor IS NULL
                  AND pc.currency IS NULL
                  AND pc.inclusion_state = 'UNKNOWN'
              )
              OR (
                  pc.knowledge_state = 'NOT_APPLICABLE'
                  AND pc.amount_minor IS NULL
                  AND pc.currency IS NULL
                  AND pc.inclusion_state = 'NOT_APPLICABLE'
              )
          )
      )
)
AND NOT EXISTS (
    SELECT 1 FROM fx_normalization AS fx
    WHERE fx.observation_id = market_observation.id
      AND NOT EXISTS (
          SELECT 1 FROM price_component AS pc
          WHERE pc.id = fx.price_component_id
            AND pc.observation_id = fx.observation_id
            AND pc.component_type = fx.component_type
            AND pc.knowledge_state = 'KNOWN'
            AND pc.amount_minor = fx.original_amount_minor
            AND pc.currency = fx.original_currency
      )
)
AND (
    upstream_event_object_id IS NULL
    OR EXISTS (
        SELECT 1
        FROM external_object AS e
        JOIN source_system AS s ON s.id = e.source_system_id
        WHERE e.id = market_observation.upstream_event_object_id
          AND e.source_system_id = market_observation.upstream_market_system_id
          AND s.system_role IN ('MARKET', 'LISTING_PLATFORM')
    )
);

CREATE UNIQUE INDEX observation_one_revision_target
    ON observation_relationship(from_observation_id)
    WHERE relationship_type = 'REVISION_OF';

CREATE UNIQUE INDEX identifier_one_proven_mapping
    ON identifier_link(external_identifier_id)
    WHERE resolution_state = 'PROVEN';

CREATE UNIQUE INDEX collectible_instance_certification_unique
    ON collectible_instance(certification_identifier_id)
    WHERE certification_identifier_id IS NOT NULL;

CREATE INDEX source_record_retrieval_record_idx
    ON source_record_retrieval(source_record_id, retrieved_at);

-- Variant profiles always begin as mutable drafts. Locking derives and fixes
-- their semantic assignment key exactly once.
CREATE TRIGGER variant_profile_insert_state_guard
BEFORE INSERT ON variant_profile
WHEN NEW.locked_at IS NOT NULL OR NEW.semantic_key IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'variant profiles must begin unlocked without a semantic key');
END;

CREATE TRIGGER variant_profile_lock_integrity_guard
BEFORE UPDATE ON variant_profile
WHEN OLD.locked_at IS NULL AND NEW.locked_at IS NOT NULL
BEGIN
    SELECT CASE WHEN NEW.semantic_key IS NULL THEN
        RAISE(ABORT, 'locked variant profile requires a semantic key')
    END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM variant_assignment AS a WHERE a.profile_id = NEW.id
    ) THEN RAISE(ABORT, 'locked variant profile requires assignments') END;
    SELECT CASE WHEN NEW.semantic_key IS NOT (
        SELECT group_concat(pair, '|')
        FROM (
            SELECT d.code || '=' || v.code AS pair
            FROM variant_assignment AS a
            JOIN variant_dimension AS d ON d.id = a.dimension_id
            JOIN variant_value AS v ON v.id = a.value_id
            WHERE a.profile_id = NEW.id
            ORDER BY d.code
        )
    ) THEN RAISE(ABORT, 'variant semantic key does not match assignments') END;
END;

CREATE TRIGGER variant_profile_update_guard
BEFORE UPDATE ON variant_profile
WHEN NOT (
    OLD.locked_at IS NULL
    AND NEW.locked_at IS NOT NULL
    AND OLD.semantic_key IS NULL
    AND NEW.semantic_key IS NOT NULL
    AND NEW.id = OLD.id
    AND NEW.fingerprint_sha256 = OLD.fingerprint_sha256
    AND NEW.label IS OLD.label
    AND NEW.created_at = OLD.created_at
)
BEGIN
    SELECT RAISE(ABORT, 'variant profiles are immutable after creation');
END;

CREATE TRIGGER variant_dimension_update_guard BEFORE UPDATE ON variant_dimension
BEGIN SELECT RAISE(ABORT, 'variant dimensions are immutable'); END;
CREATE TRIGGER variant_dimension_delete_guard BEFORE DELETE ON variant_dimension
BEGIN SELECT RAISE(ABORT, 'variant dimensions are append-only'); END;
CREATE TRIGGER variant_value_update_guard BEFORE UPDATE ON variant_value
BEGIN SELECT RAISE(ABORT, 'variant values are immutable'); END;
CREATE TRIGGER variant_value_delete_guard BEFORE DELETE ON variant_value
BEGIN SELECT RAISE(ABORT, 'variant values are append-only'); END;

CREATE TRIGGER canonical_card_insert_integrity_guard
BEFORE INSERT ON canonical_card
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM variant_profile AS p
        WHERE p.id = NEW.variant_profile_id
          AND p.locked_at IS NOT NULL
          AND p.semantic_key IS NOT NULL
    ) THEN RAISE(ABORT, 'canonical card requires a locked semantic variant profile') END;

    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM localized_card AS l
        JOIN allowed_variant_combination AS c
          ON c.card_family_id = l.card_family_id
        WHERE l.id = NEW.localized_card_id
          AND c.variant_profile_id = NEW.variant_profile_id
    ) THEN RAISE(ABORT, 'variant profile is not allowed for the card family') END;

    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM localized_card AS l
        JOIN family_variant_applicability AS a
          ON a.card_family_id = l.card_family_id
         AND a.applicability_state = 'APPLICABLE'
        WHERE l.id = NEW.localized_card_id
          AND NOT EXISTS (
              SELECT 1 FROM variant_assignment AS va
              WHERE va.profile_id = NEW.variant_profile_id
                AND va.dimension_id = a.dimension_id
          )
    ) THEN RAISE(ABORT, 'canonical variant is missing an applicable dimension') END;

    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM localized_card AS l
        JOIN family_variant_applicability AS a
          ON a.card_family_id = l.card_family_id
         AND a.applicability_state = 'NOT_APPLICABLE'
        JOIN variant_assignment AS va
          ON va.profile_id = NEW.variant_profile_id
         AND va.dimension_id = a.dimension_id
        WHERE l.id = NEW.localized_card_id
    ) THEN RAISE(ABORT, 'canonical variant assigns a non-applicable dimension') END;

    SELECT CASE WHEN NEW.exact_comparison_key IS NOT (
        SELECT 'cardcmp|' || NEW.localized_card_id || '|' || p.semantic_key
        FROM variant_profile AS p WHERE p.id = NEW.variant_profile_id
    ) THEN RAISE(ABORT, 'exact comparison key is not bound to semantic identity') END;
END;

CREATE TRIGGER canonical_card_update_guard
BEFORE UPDATE ON canonical_card
BEGIN
    SELECT RAISE(ABORT, 'canonical cards are immutable');
END;

-- Applicability and allow-list rules form part of commercial identity. They
-- are append-only, and a newly declared rule may not invalidate an existing
-- canonical card.
CREATE TRIGGER family_variant_applicability_insert_guard
BEFORE INSERT ON family_variant_applicability
WHEN (
    NEW.applicability_state = 'APPLICABLE'
    AND EXISTS (
        SELECT 1
        FROM localized_card AS l
        JOIN canonical_card AS c ON c.localized_card_id = l.id
        WHERE l.card_family_id = NEW.card_family_id
          AND NOT EXISTS (
              SELECT 1 FROM variant_assignment AS a
              WHERE a.profile_id = c.variant_profile_id
                AND a.dimension_id = NEW.dimension_id
          )
    )
) OR (
    NEW.applicability_state = 'NOT_APPLICABLE'
    AND EXISTS (
        SELECT 1
        FROM localized_card AS l
        JOIN canonical_card AS c ON c.localized_card_id = l.id
        JOIN variant_assignment AS a
          ON a.profile_id = c.variant_profile_id
         AND a.dimension_id = NEW.dimension_id
        WHERE l.card_family_id = NEW.card_family_id
    )
)
BEGIN
    SELECT RAISE(ABORT, 'variant applicability would invalidate a canonical card');
END;

CREATE TRIGGER family_variant_applicability_update_guard
BEFORE UPDATE ON family_variant_applicability
BEGIN SELECT RAISE(ABORT, 'family variant applicability is append-only'); END;
CREATE TRIGGER family_variant_applicability_delete_guard
BEFORE DELETE ON family_variant_applicability
BEGIN SELECT RAISE(ABORT, 'family variant applicability is append-only'); END;
CREATE TRIGGER allowed_variant_combination_update_guard
BEFORE UPDATE ON allowed_variant_combination
BEGIN SELECT RAISE(ABORT, 'allowed variant combinations are append-only'); END;
CREATE TRIGGER allowed_variant_combination_delete_guard
BEFORE DELETE ON allowed_variant_combination
BEGIN SELECT RAISE(ABORT, 'allowed variant combinations are append-only'); END;

-- Positive field resolutions must be exactly supported by positive evidence.
CREATE TRIGGER field_resolution_positive_evidence_guard
BEFORE INSERT ON field_resolution
WHEN NEW.resolution_state IN ('PROVEN', 'SUPPORTED')
 AND NOT EXISTS (
    SELECT 1 FROM field_claim AS c
    WHERE c.id = NEW.based_on_claim_id
      AND c.claim_role = 'EVIDENCE'
      AND c.claimed_value_json IS NOT NULL
      AND c.identity_subject_id = NEW.identity_subject_id
      AND c.field_name = NEW.field_name
      AND c.claimed_value_json = NEW.resolved_value_json
      AND (
          (NEW.resolution_state = 'PROVEN' AND c.resolution_state = 'PROVEN')
          OR
          (NEW.resolution_state = 'SUPPORTED' AND c.resolution_state IN ('PROVEN', 'SUPPORTED'))
      )
 )
BEGIN
    SELECT RAISE(ABORT, 'positive field resolution lacks matching positive evidence');
END;

CREATE TRIGGER field_resolution_nonpositive_value_guard
BEFORE INSERT ON field_resolution
WHEN NEW.resolution_state IN ('UNKNOWN', 'CONFLICT')
 AND NEW.resolved_value_json IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'unknown or conflicting field cannot select a truth value');
END;

CREATE TRIGGER field_resolution_supersession_guard
BEFORE INSERT ON field_resolution
WHEN NEW.supersedes_resolution_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM field_resolution AS old
        WHERE old.id = NEW.supersedes_resolution_id
          AND old.identity_subject_id = NEW.identity_subject_id
          AND old.field_name = NEW.field_name
    ) THEN RAISE(ABORT, 'field supersession must stay within subject and field') END;
    WITH RECURSIVE chain(id) AS (
        SELECT NEW.supersedes_resolution_id
        UNION ALL
        SELECT f.supersedes_resolution_id
        FROM field_resolution AS f
        JOIN chain ON f.id = chain.id
        WHERE f.supersedes_resolution_id IS NOT NULL
    )
    SELECT CASE WHEN EXISTS (SELECT 1 FROM chain WHERE id = NEW.id) THEN
        RAISE(ABORT, 'field supersession cycle')
    END;
END;

-- External exact identity mappings cannot contradict each other.
CREATE TRIGGER identifier_link_state_guard
BEFORE INSERT ON identifier_link
WHEN (
       NEW.resolution_state = 'PROVEN' AND NEW.canonical_card_id IS NULL
     )
  OR (
       NEW.resolution_state IN ('UNKNOWN', 'CONFLICT')
       AND NEW.canonical_card_id IS NOT NULL
     )
BEGIN
    SELECT RAISE(ABORT, 'identifier mapping state contradicts selected identity');
END;

CREATE TRIGGER identifier_link_update_guard BEFORE UPDATE ON identifier_link
BEGIN SELECT RAISE(ABORT, 'identifier links are append-only'); END;
CREATE TRIGGER identifier_link_delete_guard BEFORE DELETE ON identifier_link
BEGIN SELECT RAISE(ABORT, 'identifier links are append-only'); END;
CREATE TRIGGER external_object_update_guard BEFORE UPDATE ON external_object
BEGIN SELECT RAISE(ABORT, 'external objects are append-only'); END;
CREATE TRIGGER external_object_delete_guard BEFORE DELETE ON external_object
BEGIN SELECT RAISE(ABORT, 'external objects are append-only'); END;
CREATE TRIGGER external_identifier_update_guard BEFORE UPDATE ON external_identifier
BEGIN SELECT RAISE(ABORT, 'external identifiers are append-only'); END;
CREATE TRIGGER external_identifier_delete_guard BEFORE DELETE ON external_identifier
BEGIN SELECT RAISE(ABORT, 'external identifiers are append-only'); END;
CREATE TRIGGER source_system_update_guard BEFORE UPDATE ON source_system
BEGIN SELECT RAISE(ABORT, 'source systems are append-only'); END;
CREATE TRIGGER source_system_delete_guard BEFORE DELETE ON source_system
BEGIN SELECT RAISE(ABORT, 'source systems are append-only'); END;

CREATE TRIGGER collectible_instance_update_guard BEFORE UPDATE ON collectible_instance
BEGIN SELECT RAISE(ABORT, 'collectible instances are append-only'); END;
CREATE TRIGGER collectible_instance_delete_guard BEFORE DELETE ON collectible_instance
BEGIN SELECT RAISE(ABORT, 'collectible instances are append-only'); END;

CREATE TRIGGER identity_resolution_state_guard
BEFORE INSERT ON identity_resolution
WHEN NEW.resolution_state IN ('UNKNOWN', 'CONFLICT')
 AND NEW.canonical_card_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'unresolved identity cannot select a canonical card');
END;

CREATE TRIGGER observation_identity_link_integrity_guard
BEFORE INSERT ON observation_identity_link
BEGIN
    SELECT CASE WHEN NEW.link_role = 'SUBJECT' AND NEW.canonical_card_id IS NOT NULL THEN
        RAISE(ABORT, 'subject identity link cannot select a canonical card')
    END;
    SELECT CASE WHEN NEW.link_role = 'RESOLVED_AS' AND NOT EXISTS (
        SELECT 1
        FROM identity_resolution AS r
        JOIN market_observation AS o ON o.id = NEW.observation_id
        WHERE r.id = NEW.identity_resolution_id
          AND r.resolution_state IN ('PROVEN', 'SUPPORTED')
          AND r.canonical_card_id IS NOT NULL
          AND r.canonical_card_id = NEW.canonical_card_id
          AND o.canonical_card_id IS NOT NULL
          AND o.canonical_card_id = NEW.canonical_card_id
    ) THEN RAISE(ABORT, 'resolved observation identity is inconsistent') END;
END;

CREATE TRIGGER observation_identity_link_update_guard BEFORE UPDATE ON observation_identity_link
BEGIN SELECT RAISE(ABORT, 'observation identity links are append-only'); END;
CREATE TRIGGER observation_identity_link_delete_guard BEFORE DELETE ON observation_identity_link
BEGIN SELECT RAISE(ABORT, 'observation identity links are append-only'); END;

-- Upstream event IDs are explicitly scoped to their owning marketplace.
CREATE TRIGGER market_observation_upstream_lineage_guard
BEFORE INSERT ON market_observation
WHEN NEW.upstream_event_object_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM external_object AS e
    JOIN source_system AS s ON s.id = e.source_system_id
    WHERE e.id = NEW.upstream_event_object_id
      AND e.source_system_id = NEW.upstream_market_system_id
      AND s.system_role IN ('MARKET', 'LISTING_PLATFORM')
 )
BEGIN
    SELECT RAISE(ABORT, 'upstream event object does not belong to upstream marketplace');
END;

CREATE TRIGGER market_observation_revision_target_guard
BEFORE INSERT ON market_observation
WHEN NEW.revision_of_observation_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM market_observation AS old
    WHERE old.id = NEW.revision_of_observation_id
      AND old.lifecycle_state = 'SEALED'
      AND old.observation_type = NEW.observation_type
      AND old.source_system_id = NEW.source_system_id
      AND old.source_native_record_id = NEW.source_native_record_id
      AND old.upstream_market_system_id IS NEW.upstream_market_system_id
      AND old.upstream_event_object_id IS NEW.upstream_event_object_id
 )
BEGIN
    SELECT RAISE(ABORT, 'revision target is incompatible or incomplete');
END;

CREATE TRIGGER market_observation_insert_state_guard
BEFORE INSERT ON market_observation
WHEN NEW.lifecycle_state <> 'DRAFT' OR NEW.sealed_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'market observations must begin as unsealed drafts');
END;

CREATE TRIGGER market_observation_update_guard
BEFORE UPDATE ON market_observation
WHEN NOT (
    OLD.lifecycle_state = 'DRAFT'
    AND NEW.lifecycle_state = 'SEALED'
    AND OLD.sealed_at IS NULL
    AND NEW.sealed_at IS NOT NULL
    AND NEW.id = OLD.id
    AND NEW.observation_type = OLD.observation_type
    AND NEW.source_system_id = OLD.source_system_id
    AND NEW.upstream_market_system_id IS OLD.upstream_market_system_id
    AND NEW.source_record_id IS OLD.source_record_id
    AND NEW.source_native_record_id = OLD.source_native_record_id
    AND NEW.upstream_event_object_id IS OLD.upstream_event_object_id
    AND NEW.canonical_card_id IS OLD.canonical_card_id
    AND NEW.idempotency_key = OLD.idempotency_key
    AND NEW.content_sha256 = OLD.content_sha256
    AND NEW.event_at IS OLD.event_at
    AND NEW.event_time_precision = OLD.event_time_precision
    AND NEW.observed_at = OLD.observed_at
    AND NEW.ingested_at = OLD.ingested_at
    AND NEW.source_updated_at IS OLD.source_updated_at
    AND NEW.revision_of_observation_id IS OLD.revision_of_observation_id
    AND NEW.created_at = OLD.created_at
 )
BEGIN
    SELECT RAISE(ABORT, 'market observations are immutable except for sealing');
END;

CREATE TRIGGER market_observation_seal_completeness_guard
BEFORE UPDATE OF lifecycle_state ON market_observation
WHEN OLD.lifecycle_state = 'DRAFT' AND NEW.lifecycle_state = 'SEALED'
BEGIN
    SELECT CASE
        WHEN NEW.observation_type = 'SALE_TRANSACTION' AND NOT EXISTS (
            SELECT 1 FROM sale_transaction WHERE observation_id = NEW.id
        ) THEN RAISE(ABORT, 'sale observation cannot seal without sale facts')
        WHEN NEW.observation_type = 'LISTING_SNAPSHOT' AND NOT EXISTS (
            SELECT 1 FROM listing_snapshot WHERE observation_id = NEW.id
        ) THEN RAISE(ABORT, 'listing observation cannot seal without listing facts')
        WHEN NEW.observation_type = 'PROVIDER_METRIC_OBSERVATION' AND NOT EXISTS (
            SELECT 1 FROM provider_metric_observation WHERE observation_id = NEW.id
        ) THEN RAISE(ABORT, 'metric observation cannot seal without metric facts')
        WHEN NEW.observation_type = 'POPULATION_OBSERVATION' AND NOT EXISTS (
            SELECT 1 FROM population_observation WHERE observation_id = NEW.id
        ) THEN RAISE(ABORT, 'population observation cannot seal without population facts')
        WHEN NEW.observation_type = 'FX_RATE_OBSERVATION' AND NOT EXISTS (
            SELECT 1 FROM fx_rate_observation WHERE observation_id = NEW.id
        ) THEN RAISE(ABORT, 'FX observation cannot seal without FX facts')
    END;
    SELECT CASE WHEN (
        NEW.revision_of_observation_id IS NULL
        AND EXISTS (
            SELECT 1 FROM observation_relationship
            WHERE from_observation_id = NEW.id AND relationship_type = 'REVISION_OF'
        )
    ) OR (
        NEW.revision_of_observation_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM observation_relationship
            WHERE from_observation_id = NEW.id
              AND to_observation_id = NEW.revision_of_observation_id
              AND relationship_type = 'REVISION_OF'
        )
    ) THEN RAISE(ABORT, 'revision column and relationship projection disagree') END;
END;

-- Children can be populated only while the envelope is a draft.
CREATE TRIGGER sale_transaction_draft_guard BEFORE INSERT ON sale_transaction
WHEN (SELECT lifecycle_state FROM market_observation WHERE id = NEW.observation_id) IS NOT 'DRAFT'
BEGIN SELECT RAISE(ABORT, 'sale facts require a draft observation'); END;
CREATE TRIGGER listing_snapshot_draft_guard BEFORE INSERT ON listing_snapshot
WHEN (SELECT lifecycle_state FROM market_observation WHERE id = NEW.observation_id) IS NOT 'DRAFT'
BEGIN SELECT RAISE(ABORT, 'listing facts require a draft observation'); END;
CREATE TRIGGER provider_metric_draft_guard BEFORE INSERT ON provider_metric_observation
WHEN (SELECT lifecycle_state FROM market_observation WHERE id = NEW.observation_id) IS NOT 'DRAFT'
BEGIN SELECT RAISE(ABORT, 'metric facts require a draft observation'); END;
CREATE TRIGGER population_observation_draft_guard BEFORE INSERT ON population_observation
WHEN (SELECT lifecycle_state FROM market_observation WHERE id = NEW.observation_id) IS NOT 'DRAFT'
BEGIN SELECT RAISE(ABORT, 'population facts require a draft observation'); END;
CREATE TRIGGER fx_rate_observation_draft_guard BEFORE INSERT ON fx_rate_observation
WHEN (SELECT lifecycle_state FROM market_observation WHERE id = NEW.observation_id) IS NOT 'DRAFT'
BEGIN SELECT RAISE(ABORT, 'FX facts require a draft observation'); END;

CREATE TRIGGER price_component_integrity_guard
BEFORE INSERT ON price_component
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM market_observation AS o
        WHERE o.id = NEW.observation_id
          AND o.lifecycle_state = 'DRAFT'
          AND o.observation_type IN (
              'SALE_TRANSACTION', 'LISTING_SNAPSHOT', 'PROVIDER_METRIC_OBSERVATION'
          )
    ) THEN RAISE(ABORT, 'price component requires a price-bearing draft observation') END;
    SELECT CASE WHEN NOT (
        (
            NEW.knowledge_state = 'KNOWN'
            AND NEW.amount_minor IS NOT NULL
            AND NEW.amount_minor >= 0
            AND NEW.currency IS NOT NULL
            AND length(NEW.currency) = 3
            AND NEW.inclusion_state IN ('INCLUDED', 'EXCLUDED', 'UNKNOWN')
        )
        OR
        (
            NEW.knowledge_state = 'UNKNOWN'
            AND NEW.amount_minor IS NULL
            AND NEW.currency IS NULL
            AND NEW.inclusion_state = 'UNKNOWN'
        )
        OR
        (
            NEW.knowledge_state = 'NOT_APPLICABLE'
            AND NEW.amount_minor IS NULL
            AND NEW.currency IS NULL
            AND NEW.inclusion_state = 'NOT_APPLICABLE'
        )
    ) THEN RAISE(ABORT, 'illegal price knowledge/inclusion state') END;
END;

CREATE TRIGGER fx_normalization_integrity_guard
BEFORE INSERT ON fx_normalization
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM price_component AS pc
        JOIN market_observation AS o ON o.id = pc.observation_id
        WHERE pc.id = NEW.price_component_id
          AND pc.observation_id = NEW.observation_id
          AND pc.component_type = NEW.component_type
          AND pc.knowledge_state = 'KNOWN'
          AND pc.amount_minor = NEW.original_amount_minor
          AND pc.currency = NEW.original_currency
          AND NEW.original_amount_minor >= 0
          AND NEW.target_amount_minor >= 0
          AND length(NEW.original_currency) = 3
          AND length(NEW.target_currency) = 3
          AND o.lifecycle_state = 'DRAFT'
    ) THEN RAISE(ABORT, 'FX normalization does not match its exact price component') END;
    SELECT CASE WHEN NEW.rate_observation_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM market_observation AS rate_envelope
        JOIN fx_rate_observation AS rate ON rate.observation_id = rate_envelope.id
        WHERE rate_envelope.id = NEW.rate_observation_id
          AND rate_envelope.lifecycle_state = 'SEALED'
          AND rate.base_currency = NEW.original_currency
          AND rate.quote_currency = NEW.target_currency
          AND rate.rate_decimal = NEW.fx_rate_decimal
          AND rate.effective_date = NEW.rate_effective_date
          AND rate.rate_source = NEW.rate_source
    ) THEN RAISE(ABORT, 'FX rate observation does not match normalization lineage') END;
END;

CREATE TRIGGER fx_normalization_update_guard BEFORE UPDATE ON fx_normalization
BEGIN SELECT RAISE(ABORT, 'FX normalizations are append-only'); END;

-- REVISION_OF is a projection of revision_of_observation_id and must form a
-- compatible acyclic chain.
CREATE TRIGGER observation_revision_relationship_guard
BEFORE INSERT ON observation_relationship
WHEN NEW.relationship_type = 'REVISION_OF'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM market_observation AS current
        JOIN market_observation AS old ON old.id = NEW.to_observation_id
        WHERE current.id = NEW.from_observation_id
          AND current.lifecycle_state = 'DRAFT'
          AND old.lifecycle_state = 'SEALED'
          AND current.revision_of_observation_id = NEW.to_observation_id
          AND current.observation_type = old.observation_type
          AND current.source_system_id = old.source_system_id
          AND current.source_native_record_id = old.source_native_record_id
          AND current.upstream_market_system_id IS old.upstream_market_system_id
          AND current.upstream_event_object_id IS old.upstream_event_object_id
    ) THEN RAISE(ABORT, 'revision relationship disagrees with compatible revision target') END;
    WITH RECURSIVE ancestors(id) AS (
        SELECT NEW.to_observation_id
        UNION ALL
        SELECT r.to_observation_id
        FROM observation_relationship AS r
        JOIN ancestors ON r.from_observation_id = ancestors.id
        WHERE r.relationship_type = 'REVISION_OF'
    )
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM ancestors WHERE id = NEW.from_observation_id
    ) THEN RAISE(ABORT, 'revision cycle') END;
END;

CREATE TRIGGER observation_cancel_void_relationship_guard
BEFORE INSERT ON observation_relationship
WHEN NEW.relationship_type IN ('CANCELS', 'VOIDS')
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM market_observation AS action
        JOIN market_observation AS target ON target.id = NEW.to_observation_id
        WHERE action.id = NEW.from_observation_id
          AND action.lifecycle_state = 'SEALED'
          AND target.lifecycle_state = 'SEALED'
          AND action.observation_type = target.observation_type
          AND action.source_system_id = target.source_system_id
          AND action.source_native_record_id = target.source_native_record_id
          AND action.upstream_market_system_id IS target.upstream_market_system_id
          AND action.upstream_event_object_id IS target.upstream_event_object_id
          AND action.canonical_card_id IS target.canonical_card_id
    ) THEN RAISE(ABORT, 'cancel/void relationship targets an unrelated market event') END;
    WITH RECURSIVE targets(id) AS (
        SELECT NEW.to_observation_id
        UNION ALL
        SELECT r.to_observation_id
        FROM observation_relationship AS r
        JOIN targets ON r.from_observation_id = targets.id
        WHERE r.relationship_type IN ('CANCELS', 'VOIDS')
    )
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM targets WHERE id = NEW.from_observation_id
    ) THEN RAISE(ABORT, 'cancel/void relationship cycle') END;
END;

CREATE TRIGGER source_record_retrieval_update_guard BEFORE UPDATE ON source_record_retrieval
BEGIN SELECT RAISE(ABORT, 'source retrievals are append-only'); END;
CREATE TRIGGER source_record_retrieval_delete_guard BEFORE DELETE ON source_record_retrieval
BEGIN SELECT RAISE(ABORT, 'source retrievals are append-only'); END;

-- The migration ledger itself is immutable after a version is recorded.
CREATE TRIGGER schema_migration_update_guard BEFORE UPDATE ON schema_migration
BEGIN SELECT RAISE(ABORT, 'migration ledger is immutable'); END;
CREATE TRIGGER schema_migration_delete_guard BEFORE DELETE ON schema_migration
BEGIN SELECT RAISE(ABORT, 'migration ledger is immutable'); END;
