-- Robot KB durable PostgreSQL schema.
--
-- This is intentionally PostgreSQL-native and represents the final semantic
-- state of frozen SQLite migrations 0001-0004.  Timestamps and JSON evidence
-- remain text so import preserves the exact source representation used in
-- content hashes and idempotency keys.  Raw bytes use PostgreSQL BYTEA.

CREATE TABLE source_system (
    id TEXT PRIMARY KEY CHECK (id LIKE 'source\_%' ESCAPE '\'),
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    system_role TEXT NOT NULL CHECK (
        system_role IN ('PROVIDER', 'MARKET', 'CATALOG', 'LISTING_PLATFORM', 'HUMAN')
    ),
    created_at TEXT NOT NULL
);

CREATE TABLE variant_dimension (
    id TEXT PRIMARY KEY CHECK (id LIKE 'vdim\_%' ESCAPE '\'),
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE variant_value (
    id TEXT PRIMARY KEY CHECK (id LIKE 'vval\_%' ESCAPE '\'),
    dimension_id TEXT NOT NULL REFERENCES variant_dimension(id),
    code TEXT NOT NULL,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (dimension_id, code),
    UNIQUE (id, dimension_id)
);

CREATE TABLE variant_profile (
    id TEXT PRIMARY KEY CHECK (id LIKE 'vprofile\_%' ESCAPE '\'),
    fingerprint_sha256 TEXT NOT NULL UNIQUE,
    label TEXT,
    created_at TEXT NOT NULL,
    locked_at TEXT,
    semantic_key TEXT
);

CREATE TABLE variant_assignment (
    profile_id TEXT NOT NULL REFERENCES variant_profile(id),
    dimension_id TEXT NOT NULL REFERENCES variant_dimension(id),
    value_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, dimension_id),
    FOREIGN KEY (value_id, dimension_id)
        REFERENCES variant_value(id, dimension_id)
);

CREATE TABLE canonical_set (
    id TEXT PRIMARY KEY CHECK (id LIKE 'set\_%' ESCAPE '\'),
    canonical_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    release_date TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE card_family (
    id TEXT PRIMARY KEY CHECK (id LIKE 'family\_%' ESCAPE '\'),
    canonical_set_id TEXT NOT NULL REFERENCES canonical_set(id),
    collector_number TEXT NOT NULL,
    family_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (canonical_set_id, collector_number, family_name)
);

CREATE TABLE localized_card (
    id TEXT PRIMARY KEY CHECK (id LIKE 'localized\_%' ESCAPE '\'),
    card_family_id TEXT NOT NULL REFERENCES card_family(id),
    language_code TEXT NOT NULL,
    localized_name TEXT NOT NULL,
    localized_set_name TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (card_family_id, language_code)
);

CREATE TABLE family_variant_applicability (
    id TEXT PRIMARY KEY CHECK (id LIKE 'vapp\_%' ESCAPE '\'),
    card_family_id TEXT NOT NULL REFERENCES card_family(id),
    dimension_id TEXT NOT NULL REFERENCES variant_dimension(id),
    applicability_state TEXT NOT NULL CHECK (
        applicability_state IN ('APPLICABLE', 'NOT_APPLICABLE', 'UNKNOWN')
    ),
    created_at TEXT NOT NULL,
    UNIQUE (card_family_id, dimension_id)
);

CREATE TABLE allowed_variant_combination (
    id TEXT PRIMARY KEY CHECK (id LIKE 'vcombo\_%' ESCAPE '\'),
    card_family_id TEXT NOT NULL REFERENCES card_family(id),
    variant_profile_id TEXT NOT NULL REFERENCES variant_profile(id),
    created_at TEXT NOT NULL,
    UNIQUE (card_family_id, variant_profile_id)
);

CREATE TABLE canonical_card (
    id TEXT PRIMARY KEY CHECK (id LIKE 'card\_%' ESCAPE '\'),
    localized_card_id TEXT NOT NULL REFERENCES localized_card(id),
    variant_profile_id TEXT NOT NULL REFERENCES variant_profile(id),
    exact_comparison_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE (localized_card_id, variant_profile_id)
);

CREATE TABLE external_object (
    id TEXT PRIMARY KEY CHECK (id LIKE 'extobj\_%' ESCAPE '\'),
    source_system_id TEXT NOT NULL REFERENCES source_system(id),
    object_type TEXT NOT NULL,
    source_native_id TEXT NOT NULL,
    upstream_market_system_id TEXT REFERENCES source_system(id),
    upstream_native_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (source_system_id, object_type, source_native_id)
);

CREATE TABLE external_identifier (
    id TEXT PRIMARY KEY CHECK (id LIKE 'extid\_%' ESCAPE '\'),
    external_object_id TEXT NOT NULL REFERENCES external_object(id),
    namespace TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (external_object_id, namespace, identifier_value)
);

CREATE TABLE identifier_link (
    id TEXT PRIMARY KEY CHECK (id LIKE 'idlink\_%' ESCAPE '\'),
    external_identifier_id TEXT NOT NULL REFERENCES external_identifier(id),
    canonical_card_id TEXT REFERENCES canonical_card(id),
    resolution_state TEXT NOT NULL CHECK (
        resolution_state IN ('PROVEN', 'SUPPORTED', 'UNKNOWN', 'CONFLICT')
    ),
    created_at TEXT NOT NULL,
    CHECK (resolution_state <> 'PROVEN' OR canonical_card_id IS NOT NULL),
    CHECK (resolution_state NOT IN ('UNKNOWN', 'CONFLICT') OR canonical_card_id IS NULL)
);

CREATE TABLE card_alias (
    id TEXT PRIMARY KEY CHECK (id LIKE 'alias\_%' ESCAPE '\'),
    canonical_card_id TEXT NOT NULL REFERENCES canonical_card(id),
    source_system_id TEXT REFERENCES source_system(id),
    alias_text TEXT NOT NULL,
    language_code TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (canonical_card_id, source_system_id, alias_text, language_code)
);

CREATE TABLE source_record (
    id TEXT PRIMARY KEY CHECK (id LIKE 'srecord\_%' ESCAPE '\'),
    source_system_id TEXT NOT NULL REFERENCES source_system(id),
    external_object_id TEXT REFERENCES external_object(id),
    source_native_record_id TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    source_updated_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (source_system_id, source_native_record_id, payload_sha256)
);

CREATE TABLE identity_subject (
    id TEXT PRIMARY KEY CHECK (id LIKE 'subject\_%' ESCAPE '\'),
    subject_type TEXT NOT NULL,
    source_record_id TEXT REFERENCES source_record(id),
    external_object_id TEXT REFERENCES external_object(id),
    subject_label TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE identity_resolution (
    id TEXT PRIMARY KEY CHECK (id LIKE 'ires\_%' ESCAPE '\'),
    identity_subject_id TEXT NOT NULL REFERENCES identity_subject(id),
    resolution_state TEXT NOT NULL CHECK (
        resolution_state IN ('PROVEN', 'SUPPORTED', 'UNKNOWN', 'CONFLICT')
    ),
    canonical_card_id TEXT REFERENCES canonical_card(id),
    unresolved_dimensions_json TEXT NOT NULL DEFAULT '[]',
    conflicts_json TEXT NOT NULL DEFAULT '[]',
    supersedes_resolution_id TEXT REFERENCES identity_resolution(id),
    created_at TEXT NOT NULL,
    CHECK (resolution_state <> 'PROVEN' OR canonical_card_id IS NOT NULL),
    CHECK (resolution_state NOT IN ('UNKNOWN', 'CONFLICT') OR canonical_card_id IS NULL),
    CHECK (supersedes_resolution_id IS NULL OR supersedes_resolution_id <> id)
);

CREATE TABLE identity_candidate (
    id TEXT PRIMARY KEY CHECK (id LIKE 'candidate\_%' ESCAPE '\'),
    identity_resolution_id TEXT NOT NULL REFERENCES identity_resolution(id),
    canonical_card_id TEXT NOT NULL REFERENCES canonical_card(id),
    candidate_rank INTEGER NOT NULL CHECK (candidate_rank >= 0),
    support_score TEXT,
    evidence_summary TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (identity_resolution_id, canonical_card_id)
);

CREATE TABLE field_claim (
    id TEXT PRIMARY KEY CHECK (id LIKE 'claim\_%' ESCAPE '\'),
    source_record_id TEXT NOT NULL REFERENCES source_record(id),
    identity_subject_id TEXT NOT NULL REFERENCES identity_subject(id),
    field_name TEXT NOT NULL,
    claimed_value_json TEXT,
    source_kind TEXT NOT NULL CHECK (
        source_kind IN ('PROVIDER', 'CATALOG', 'LISTING', 'HUMAN')
    ),
    evidence_method TEXT NOT NULL CHECK (
        evidence_method IN (
            'STRUCTURED_FIELD', 'TITLE_PARSE', 'OCR', 'VISUAL_REFERENCE',
            'MANUAL', 'DERIVED_RULE'
        )
    ),
    directness TEXT NOT NULL CHECK (
        directness IN (
            'DIRECT_ASSERTION', 'DETERMINISTIC_DERIVATION',
            'STATISTICAL_INFERENCE'
        )
    ),
    resolution_state TEXT NOT NULL CHECK (
        resolution_state IN ('PROVEN', 'SUPPORTED', 'UNKNOWN', 'CONFLICT')
    ),
    claim_role TEXT NOT NULL CHECK (claim_role IN ('EVIDENCE', 'REQUEST_TARGET')),
    created_at TEXT NOT NULL,
    CHECK (claim_role <> 'REQUEST_TARGET' OR resolution_state = 'UNKNOWN')
);

CREATE TABLE field_resolution (
    id TEXT PRIMARY KEY CHECK (id LIKE 'fres\_%' ESCAPE '\'),
    identity_subject_id TEXT NOT NULL REFERENCES identity_subject(id),
    field_name TEXT NOT NULL,
    resolved_value_json TEXT,
    resolution_state TEXT NOT NULL CHECK (
        resolution_state IN ('PROVEN', 'SUPPORTED', 'UNKNOWN', 'CONFLICT')
    ),
    based_on_claim_id TEXT REFERENCES field_claim(id),
    supersedes_resolution_id TEXT REFERENCES field_resolution(id),
    created_at TEXT NOT NULL,
    CHECK (
        resolution_state NOT IN ('PROVEN', 'SUPPORTED')
        OR (resolved_value_json IS NOT NULL AND based_on_claim_id IS NOT NULL)
    ),
    CHECK (resolution_state NOT IN ('UNKNOWN', 'CONFLICT') OR resolved_value_json IS NULL),
    CHECK (supersedes_resolution_id IS NULL OR supersedes_resolution_id <> id)
);

CREATE TABLE collectible_instance (
    id TEXT PRIMARY KEY CHECK (id LIKE 'instance\_%' ESCAPE '\'),
    canonical_card_id TEXT NOT NULL REFERENCES canonical_card(id),
    grader TEXT,
    grade TEXT,
    qualifier TEXT,
    subgrades_json TEXT,
    certification_identifier_id TEXT REFERENCES external_identifier(id),
    created_at TEXT NOT NULL,
    CHECK ((grader IS NULL) = (grade IS NULL))
);

CREATE TABLE market_observation (
    id TEXT PRIMARY KEY CHECK (id LIKE 'observation\_%' ESCAPE '\'),
    observation_type TEXT NOT NULL CHECK (
        observation_type IN (
            'SALE_TRANSACTION', 'LISTING_SNAPSHOT',
            'PROVIDER_METRIC_OBSERVATION', 'POPULATION_OBSERVATION',
            'FX_RATE_OBSERVATION'
        )
    ),
    source_system_id TEXT NOT NULL REFERENCES source_system(id),
    upstream_market_system_id TEXT REFERENCES source_system(id),
    source_record_id TEXT REFERENCES source_record(id),
    source_native_record_id TEXT NOT NULL,
    upstream_event_object_id TEXT REFERENCES external_object(id),
    canonical_card_id TEXT REFERENCES canonical_card(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    content_sha256 TEXT NOT NULL,
    event_at TEXT,
    event_time_precision TEXT NOT NULL CHECK (
        event_time_precision IN ('EXACT', 'MINUTE', 'HOUR', 'DAY', 'MONTH', 'UNKNOWN')
    ),
    observed_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    source_updated_at TEXT,
    revision_of_observation_id TEXT REFERENCES market_observation(id),
    created_at TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL DEFAULT 'DRAFT' CHECK (
        lifecycle_state IN ('DRAFT', 'SEALED')
    ),
    sealed_at TEXT,
    CHECK (revision_of_observation_id IS NULL OR revision_of_observation_id <> id)
);

CREATE TABLE sale_transaction (
    observation_id TEXT PRIMARY KEY REFERENCES market_observation(id),
    listing_started_at TEXT,
    sale_occurred_at TEXT,
    transaction_status TEXT NOT NULL CHECK (
        transaction_status IN ('COMPLETED', 'CANCELLED', 'VOIDED', 'UNKNOWN')
    )
);

CREATE TABLE listing_snapshot (
    observation_id TEXT PRIMARY KEY REFERENCES market_observation(id),
    listing_started_at TEXT,
    snapshot_status TEXT NOT NULL,
    quantity BIGINT CHECK (quantity IS NULL OR quantity >= 0)
);

CREATE TABLE provider_metric_observation (
    observation_id TEXT PRIMARY KEY REFERENCES market_observation(id),
    metric_name TEXT NOT NULL,
    metric_value_minor BIGINT,
    currency TEXT,
    window_started_at TEXT,
    window_ended_at TEXT,
    sample_size BIGINT CHECK (sample_size IS NULL OR sample_size >= 0),
    CHECK ((metric_value_minor IS NULL) = (currency IS NULL))
);

CREATE TABLE population_observation (
    observation_id TEXT PRIMARY KEY REFERENCES market_observation(id),
    grader TEXT NOT NULL,
    grade TEXT NOT NULL,
    qualifier TEXT,
    population_count BIGINT NOT NULL CHECK (population_count >= 0)
);

CREATE TABLE fx_rate_observation (
    observation_id TEXT PRIMARY KEY REFERENCES market_observation(id),
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    rate_decimal TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    rate_source TEXT NOT NULL,
    rate_numerator BIGINT,
    rate_denominator BIGINT,
    CHECK (base_currency <> quote_currency)
);

CREATE TABLE price_component (
    id TEXT PRIMARY KEY CHECK (id LIKE 'price\_%' ESCAPE '\'),
    observation_id TEXT NOT NULL REFERENCES market_observation(id),
    component_type TEXT NOT NULL CHECK (
        component_type IN (
            'ITEM_PRICE', 'HAMMER_PRICE', 'ACCEPTED_OFFER', 'BUYER_PREMIUM',
            'SHIPPING', 'TAX', 'TOTAL'
        )
    ),
    amount_minor BIGINT,
    currency TEXT,
    knowledge_state TEXT NOT NULL CHECK (
        knowledge_state IN ('KNOWN', 'UNKNOWN', 'NOT_APPLICABLE')
    ),
    inclusion_state TEXT NOT NULL CHECK (
        inclusion_state IN ('INCLUDED', 'EXCLUDED', 'UNKNOWN', 'NOT_APPLICABLE')
    ),
    created_at TEXT NOT NULL,
    UNIQUE (observation_id, component_type),
    CHECK (
        (knowledge_state = 'KNOWN' AND amount_minor IS NOT NULL AND currency IS NOT NULL)
        OR (knowledge_state <> 'KNOWN' AND amount_minor IS NULL AND currency IS NULL)
    )
);

CREATE TABLE fx_normalization (
    id TEXT PRIMARY KEY CHECK (id LIKE 'fxnorm\_%' ESCAPE '\'),
    observation_id TEXT NOT NULL REFERENCES market_observation(id),
    component_type TEXT NOT NULL,
    original_amount_minor BIGINT NOT NULL,
    original_currency TEXT NOT NULL,
    fx_rate_decimal TEXT NOT NULL,
    rate_observation_id TEXT REFERENCES market_observation(id),
    rate_source TEXT NOT NULL,
    rate_effective_date TEXT NOT NULL,
    target_currency TEXT NOT NULL,
    target_amount_minor BIGINT NOT NULL,
    created_at TEXT NOT NULL,
    price_component_id TEXT REFERENCES price_component(id),
    rate_numerator BIGINT,
    rate_denominator BIGINT,
    CHECK (original_currency <> target_currency),
    UNIQUE (observation_id, component_type, target_currency)
);

CREATE TABLE observation_relationship (
    id TEXT PRIMARY KEY CHECK (id LIKE 'orel\_%' ESCAPE '\'),
    from_observation_id TEXT NOT NULL REFERENCES market_observation(id),
    to_observation_id TEXT NOT NULL REFERENCES market_observation(id),
    relationship_type TEXT NOT NULL CHECK (
        relationship_type IN (
            'DUPLICATE_OF', 'AGGREGATOR_OF', 'RELIST_OF', 'REVISION_OF',
            'CANCELS', 'VOIDS'
        )
    ),
    created_at TEXT NOT NULL,
    CHECK (from_observation_id <> to_observation_id),
    UNIQUE (from_observation_id, to_observation_id, relationship_type)
);

CREATE TABLE observation_identity_link (
    id TEXT PRIMARY KEY CHECK (id LIKE 'oilink\_%' ESCAPE '\'),
    observation_id TEXT NOT NULL REFERENCES market_observation(id),
    identity_resolution_id TEXT NOT NULL REFERENCES identity_resolution(id),
    canonical_card_id TEXT REFERENCES canonical_card(id),
    link_role TEXT NOT NULL CHECK (link_role IN ('SUBJECT', 'RESOLVED_AS')),
    created_at TEXT NOT NULL,
    UNIQUE (observation_id, identity_resolution_id, link_role)
);

CREATE TABLE source_record_retrieval (
    id TEXT PRIMARY KEY CHECK (id LIKE 'sretrieval\_%' ESCAPE '\'),
    source_record_id TEXT NOT NULL REFERENCES source_record(id),
    external_object_id TEXT REFERENCES external_object(id),
    retrieved_at TEXT NOT NULL,
    source_updated_at TEXT,
    lineage_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE source_payload (
    payload_sha256 TEXT PRIMARY KEY,
    payload_bytes BYTEA NOT NULL,
    payload_format TEXT NOT NULL CHECK (
        payload_format IN ('CANONICAL_JSON', 'UTF8_TEXT', 'BINARY')
    ),
    byte_length BIGINT NOT NULL CHECK (byte_length >= 0),
    created_at TEXT NOT NULL,
    CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (octet_length(payload_bytes) = byte_length)
);

CREATE TABLE source_record_payload (
    source_record_id TEXT PRIMARY KEY REFERENCES source_record(id),
    payload_sha256 TEXT NOT NULL REFERENCES source_payload(payload_sha256),
    created_at TEXT NOT NULL
);

CREATE INDEX market_observation_card_time_idx
    ON market_observation(canonical_card_id, observed_at);
CREATE INDEX market_observation_upstream_idx
    ON market_observation(upstream_event_object_id);
CREATE INDEX identity_candidate_resolution_idx
    ON identity_candidate(identity_resolution_id, candidate_rank);
CREATE INDEX field_resolution_subject_field_idx
    ON field_resolution(identity_subject_id, field_name, created_at);
CREATE INDEX source_record_retrieval_record_idx
    ON source_record_retrieval(source_record_id, retrieved_at);
CREATE UNIQUE INDEX variant_profile_semantic_key_unique
    ON variant_profile(semantic_key) WHERE semantic_key IS NOT NULL;
CREATE UNIQUE INDEX observation_one_revision_target
    ON observation_relationship(from_observation_id)
    WHERE relationship_type = 'REVISION_OF';
CREATE UNIQUE INDEX identifier_one_proven_mapping
    ON identifier_link(external_identifier_id)
    WHERE resolution_state = 'PROVEN';
CREATE UNIQUE INDEX collectible_instance_certification_unique
    ON collectible_instance(certification_identifier_id)
    WHERE certification_identifier_id IS NOT NULL;
CREATE UNIQUE INDEX observation_one_cancel_or_void_meaning
    ON observation_relationship(from_observation_id, to_observation_id)
    WHERE relationship_type IN ('CANCELS', 'VOIDS');

CREATE FUNCTION kb_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is immutable and append-only', TG_TABLE_NAME
        USING ERRCODE = '23000';
END;
$$;

CREATE FUNCTION kb_variant_profile_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.locked_at IS NOT NULL OR NEW.semantic_key IS NOT NULL THEN
        RAISE EXCEPTION 'variant profiles must begin unlocked without a semantic key'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_variant_profile_update_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE expected_key TEXT;
BEGIN
    IF NOT (
        OLD.locked_at IS NULL AND NEW.locked_at IS NOT NULL
        AND OLD.semantic_key IS NULL AND NEW.semantic_key IS NOT NULL
        AND NEW.id = OLD.id
        AND NEW.fingerprint_sha256 = OLD.fingerprint_sha256
        AND NEW.label IS NOT DISTINCT FROM OLD.label
        AND NEW.created_at = OLD.created_at
    ) THEN
        RAISE EXCEPTION 'variant profiles are immutable after creation'
            USING ERRCODE = '23000';
    END IF;
    SELECT string_agg(d.code || '=' || v.code, '|' ORDER BY d.code)
      INTO expected_key
      FROM variant_assignment AS a
      JOIN variant_dimension AS d ON d.id = a.dimension_id
      JOIN variant_value AS v ON v.id = a.value_id
     WHERE a.profile_id = NEW.id;
    IF expected_key IS NULL THEN
        RAISE EXCEPTION 'locked variant profile requires assignments'
            USING ERRCODE = '23000';
    END IF;
    IF NEW.semantic_key IS DISTINCT FROM expected_key THEN
        RAISE EXCEPTION 'variant semantic key does not match assignments'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_variant_assignment_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT locked_at FROM variant_profile WHERE id = NEW.profile_id) IS NOT NULL THEN
        RAISE EXCEPTION 'locked variant profiles cannot gain assignments'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_canonical_card_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE expected_key TEXT;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM variant_profile AS p
         WHERE p.id = NEW.variant_profile_id
           AND p.locked_at IS NOT NULL AND p.semantic_key IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'canonical card requires a locked semantic variant profile'
            USING ERRCODE = '23000';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM localized_card AS l
        JOIN allowed_variant_combination AS c
          ON c.card_family_id = l.card_family_id
         WHERE l.id = NEW.localized_card_id
           AND c.variant_profile_id = NEW.variant_profile_id
    ) THEN
        RAISE EXCEPTION 'variant profile is not allowed for the card family'
            USING ERRCODE = '23000';
    END IF;
    IF EXISTS (
        SELECT 1 FROM localized_card AS l
        JOIN family_variant_applicability AS a
          ON a.card_family_id = l.card_family_id
         WHERE l.id = NEW.localized_card_id
           AND a.applicability_state IN ('APPLICABLE', 'UNKNOWN')
           AND (
               a.applicability_state = 'UNKNOWN'
               OR NOT EXISTS (
                   SELECT 1 FROM variant_assignment AS va
                    WHERE va.profile_id = NEW.variant_profile_id
                      AND va.dimension_id = a.dimension_id
               )
           )
    ) THEN
        RAISE EXCEPTION 'canonical variant applicability is incomplete'
            USING ERRCODE = '23000';
    END IF;
    IF EXISTS (
        SELECT 1 FROM localized_card AS l
        JOIN family_variant_applicability AS a
          ON a.card_family_id = l.card_family_id
        JOIN variant_assignment AS va
          ON va.profile_id = NEW.variant_profile_id
         AND va.dimension_id = a.dimension_id
        JOIN variant_value AS vv ON vv.id = va.value_id
         WHERE l.id = NEW.localized_card_id
           AND (
               a.applicability_state = 'NOT_APPLICABLE'
               OR (a.applicability_state = 'APPLICABLE' AND vv.code = 'UNKNOWN')
           )
    ) THEN
        RAISE EXCEPTION 'canonical variant assigns an inapplicable or unknown value'
            USING ERRCODE = '23000';
    END IF;
    SELECT 'cardcmp|' || NEW.localized_card_id || '|' || p.semantic_key
      INTO expected_key FROM variant_profile AS p
     WHERE p.id = NEW.variant_profile_id;
    IF NEW.exact_comparison_key IS DISTINCT FROM expected_key THEN
        RAISE EXCEPTION 'exact comparison key is not bound to semantic identity'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_family_applicability_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.applicability_state = 'UNKNOWN' AND EXISTS (
        SELECT 1 FROM localized_card AS l
        JOIN canonical_card AS c ON c.localized_card_id = l.id
         WHERE l.card_family_id = NEW.card_family_id
    ) THEN
        RAISE EXCEPTION 'unknown applicability would invalidate a canonical card'
            USING ERRCODE = '23000';
    END IF;
    IF NEW.applicability_state = 'APPLICABLE' AND EXISTS (
        SELECT 1 FROM localized_card AS l
        JOIN canonical_card AS c ON c.localized_card_id = l.id
         WHERE l.card_family_id = NEW.card_family_id
           AND (
               NOT EXISTS (
                   SELECT 1 FROM variant_assignment AS a
                    WHERE a.profile_id = c.variant_profile_id
                      AND a.dimension_id = NEW.dimension_id
               )
               OR EXISTS (
                   SELECT 1 FROM variant_assignment AS a
                   JOIN variant_value AS v ON v.id = a.value_id
                    WHERE a.profile_id = c.variant_profile_id
                      AND a.dimension_id = NEW.dimension_id
                      AND v.code = 'UNKNOWN'
               )
           )
    ) THEN
        RAISE EXCEPTION 'applicability would invalidate a canonical card'
            USING ERRCODE = '23000';
    END IF;
    IF NEW.applicability_state = 'NOT_APPLICABLE' AND EXISTS (
        SELECT 1 FROM localized_card AS l
        JOIN canonical_card AS c ON c.localized_card_id = l.id
        JOIN variant_assignment AS a
          ON a.profile_id = c.variant_profile_id
         AND a.dimension_id = NEW.dimension_id
         WHERE l.card_family_id = NEW.card_family_id
    ) THEN
        RAISE EXCEPTION 'non-applicability would invalidate a canonical card'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_field_resolution_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.resolution_state IN ('PROVEN', 'SUPPORTED') AND NOT EXISTS (
        SELECT 1 FROM field_claim AS c
         WHERE c.id = NEW.based_on_claim_id
           AND c.claim_role = 'EVIDENCE'
           AND c.claimed_value_json IS NOT NULL
           AND c.identity_subject_id = NEW.identity_subject_id
           AND c.field_name = NEW.field_name
           AND c.claimed_value_json = NEW.resolved_value_json
           AND (
               (NEW.resolution_state = 'PROVEN' AND c.resolution_state = 'PROVEN')
               OR (NEW.resolution_state = 'SUPPORTED'
                   AND c.resolution_state IN ('PROVEN', 'SUPPORTED'))
           )
    ) THEN
        RAISE EXCEPTION 'positive field resolution lacks matching positive evidence'
            USING ERRCODE = '23000';
    END IF;
    IF NEW.resolution_state IN ('UNKNOWN', 'CONFLICT')
       AND NEW.resolved_value_json IS NOT NULL THEN
        RAISE EXCEPTION 'unknown or conflicting field cannot select a truth value'
            USING ERRCODE = '23000';
    END IF;
    IF NEW.supersedes_resolution_id IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM field_resolution AS old
             WHERE old.id = NEW.supersedes_resolution_id
               AND old.identity_subject_id = NEW.identity_subject_id
               AND old.field_name = NEW.field_name
        ) THEN
            RAISE EXCEPTION 'field supersession must stay within subject and field'
                USING ERRCODE = '23000';
        END IF;
        IF EXISTS (
            WITH RECURSIVE chain(id) AS (
                SELECT NEW.supersedes_resolution_id
                UNION ALL
                SELECT f.supersedes_resolution_id
                  FROM field_resolution AS f JOIN chain ON f.id = chain.id
                 WHERE f.supersedes_resolution_id IS NOT NULL
            ) SELECT 1 FROM chain WHERE id = NEW.id
        ) THEN
            RAISE EXCEPTION 'field supersession cycle' USING ERRCODE = '23000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_external_object_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.upstream_market_system_id IS NULL) <>
       (NEW.upstream_native_id IS NULL) THEN
        RAISE EXCEPTION 'upstream marketplace system and native ID must be paired'
            USING ERRCODE = '23000';
    END IF;
    IF NEW.upstream_market_system_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM source_system AS upstream
         WHERE upstream.id = NEW.upstream_market_system_id
           AND upstream.system_role IN ('MARKET', 'LISTING_PLATFORM')
    ) THEN
        RAISE EXCEPTION 'external object upstream system is not a marketplace'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_market_observation_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.lifecycle_state <> 'DRAFT' OR NEW.sealed_at IS NOT NULL THEN
        RAISE EXCEPTION 'market observations must begin as unsealed drafts'
            USING ERRCODE = '23000';
    END IF;
    IF NEW.upstream_market_system_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM source_system AS upstream
         WHERE upstream.id = NEW.upstream_market_system_id
           AND upstream.system_role IN ('MARKET', 'LISTING_PLATFORM')
    ) THEN
        RAISE EXCEPTION 'observation upstream system is not a marketplace'
            USING ERRCODE = '23000';
    END IF;
    IF NEW.upstream_event_object_id IS NOT NULL AND (
        NEW.upstream_market_system_id IS NULL OR NOT EXISTS (
            SELECT 1 FROM external_object AS object
             WHERE object.id = NEW.upstream_event_object_id
               AND (object.source_system_id = NEW.upstream_market_system_id
                    OR object.upstream_market_system_id = NEW.upstream_market_system_id)
        )
    ) THEN
        RAISE EXCEPTION 'upstream event object is incompatible with marketplace'
            USING ERRCODE = '23000';
    END IF;
    IF NEW.revision_of_observation_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM market_observation AS old
         WHERE old.id = NEW.revision_of_observation_id
           AND old.lifecycle_state = 'SEALED'
           AND old.observation_type = NEW.observation_type
           AND old.source_system_id = NEW.source_system_id
           AND old.source_native_record_id = NEW.source_native_record_id
           AND old.upstream_market_system_id IS NOT DISTINCT FROM NEW.upstream_market_system_id
           AND old.upstream_event_object_id IS NOT DISTINCT FROM NEW.upstream_event_object_id
    ) THEN
        RAISE EXCEPTION 'revision target is incompatible or incomplete'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_market_observation_update_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT (
        OLD.lifecycle_state = 'DRAFT' AND NEW.lifecycle_state = 'SEALED'
        AND OLD.sealed_at IS NULL AND NEW.sealed_at IS NOT NULL
        AND NEW.id = OLD.id AND NEW.observation_type = OLD.observation_type
        AND NEW.source_system_id = OLD.source_system_id
        AND NEW.upstream_market_system_id IS NOT DISTINCT FROM OLD.upstream_market_system_id
        AND NEW.source_record_id IS NOT DISTINCT FROM OLD.source_record_id
        AND NEW.source_native_record_id = OLD.source_native_record_id
        AND NEW.upstream_event_object_id IS NOT DISTINCT FROM OLD.upstream_event_object_id
        AND NEW.canonical_card_id IS NOT DISTINCT FROM OLD.canonical_card_id
        AND NEW.idempotency_key = OLD.idempotency_key
        AND NEW.content_sha256 = OLD.content_sha256
        AND NEW.event_at IS NOT DISTINCT FROM OLD.event_at
        AND NEW.event_time_precision = OLD.event_time_precision
        AND NEW.observed_at = OLD.observed_at AND NEW.ingested_at = OLD.ingested_at
        AND NEW.source_updated_at IS NOT DISTINCT FROM OLD.source_updated_at
        AND NEW.revision_of_observation_id IS NOT DISTINCT FROM OLD.revision_of_observation_id
        AND NEW.created_at = OLD.created_at
    ) THEN
        RAISE EXCEPTION 'market observations are immutable except for sealing'
            USING ERRCODE = '23000';
    END IF;
    IF (NEW.observation_type = 'SALE_TRANSACTION'
        AND NOT EXISTS (SELECT 1 FROM sale_transaction WHERE observation_id = NEW.id))
       OR (NEW.observation_type = 'LISTING_SNAPSHOT'
        AND NOT EXISTS (SELECT 1 FROM listing_snapshot WHERE observation_id = NEW.id))
       OR (NEW.observation_type = 'PROVIDER_METRIC_OBSERVATION'
        AND NOT EXISTS (SELECT 1 FROM provider_metric_observation WHERE observation_id = NEW.id))
       OR (NEW.observation_type = 'POPULATION_OBSERVATION'
        AND NOT EXISTS (SELECT 1 FROM population_observation WHERE observation_id = NEW.id))
       OR (NEW.observation_type = 'FX_RATE_OBSERVATION'
        AND NOT EXISTS (SELECT 1 FROM fx_rate_observation WHERE observation_id = NEW.id)) THEN
        RAISE EXCEPTION 'observation cannot seal without its typed fact'
            USING ERRCODE = '23000';
    END IF;
    IF (NEW.revision_of_observation_id IS NULL AND EXISTS (
            SELECT 1 FROM observation_relationship
             WHERE from_observation_id = NEW.id AND relationship_type = 'REVISION_OF'
        )) OR (NEW.revision_of_observation_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM observation_relationship
             WHERE from_observation_id = NEW.id
               AND to_observation_id = NEW.revision_of_observation_id
               AND relationship_type = 'REVISION_OF'
        )) THEN
        RAISE EXCEPTION 'revision column and relationship projection disagree'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_fact_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM market_observation
         WHERE id = NEW.observation_id
           AND observation_type = TG_ARGV[0]
           AND lifecycle_state = 'DRAFT'
    ) THEN
        RAISE EXCEPTION 'typed fact requires a matching draft observation'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_price_component_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM market_observation
         WHERE id = NEW.observation_id AND lifecycle_state = 'DRAFT'
           AND observation_type IN (
               'SALE_TRANSACTION', 'LISTING_SNAPSHOT', 'PROVIDER_METRIC_OBSERVATION'
           )
    ) THEN
        RAISE EXCEPTION 'price component requires a price-bearing draft observation'
            USING ERRCODE = '23000';
    END IF;
    IF NOT (
        (NEW.knowledge_state = 'KNOWN' AND NEW.amount_minor IS NOT NULL
         AND NEW.amount_minor >= 0 AND NEW.currency IS NOT NULL
         AND length(NEW.currency) = 3
         AND NEW.inclusion_state IN ('INCLUDED', 'EXCLUDED', 'UNKNOWN'))
        OR (NEW.knowledge_state = 'UNKNOWN' AND NEW.amount_minor IS NULL
            AND NEW.currency IS NULL AND NEW.inclusion_state = 'UNKNOWN')
        OR (NEW.knowledge_state = 'NOT_APPLICABLE' AND NEW.amount_minor IS NULL
            AND NEW.currency IS NULL AND NEW.inclusion_state = 'NOT_APPLICABLE')
    ) THEN
        RAISE EXCEPTION 'illegal price knowledge/inclusion state'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_observation_relationship_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.relationship_type = 'REVISION_OF' THEN
        IF NOT EXISTS (
            SELECT 1 FROM market_observation AS current
            JOIN market_observation AS old ON old.id = NEW.to_observation_id
             WHERE current.id = NEW.from_observation_id
               AND current.lifecycle_state = 'DRAFT' AND old.lifecycle_state = 'SEALED'
               AND current.revision_of_observation_id = NEW.to_observation_id
               AND current.observation_type = old.observation_type
               AND current.source_system_id = old.source_system_id
               AND current.source_native_record_id = old.source_native_record_id
               AND current.upstream_market_system_id IS NOT DISTINCT FROM old.upstream_market_system_id
               AND current.upstream_event_object_id IS NOT DISTINCT FROM old.upstream_event_object_id
        ) THEN
            RAISE EXCEPTION 'revision relationship disagrees with compatible target'
                USING ERRCODE = '23000';
        END IF;
        IF EXISTS (
            WITH RECURSIVE ancestors(id) AS (
                SELECT NEW.to_observation_id
                UNION ALL
                SELECT r.to_observation_id FROM observation_relationship AS r
                JOIN ancestors ON r.from_observation_id = ancestors.id
                 WHERE r.relationship_type = 'REVISION_OF'
            ) SELECT 1 FROM ancestors WHERE id = NEW.from_observation_id
        ) THEN
            RAISE EXCEPTION 'revision cycle' USING ERRCODE = '23000';
        END IF;
    ELSIF NEW.relationship_type IN ('CANCELS', 'VOIDS') THEN
        IF NOT EXISTS (
            SELECT 1 FROM market_observation AS action
            JOIN market_observation AS target ON target.id = NEW.to_observation_id
            JOIN sale_transaction AS action_sale ON action_sale.observation_id = action.id
             WHERE action.id = NEW.from_observation_id
               AND action.lifecycle_state = 'SEALED' AND target.lifecycle_state = 'SEALED'
               AND action.observation_type = 'SALE_TRANSACTION'
               AND target.observation_type = 'SALE_TRANSACTION'
               AND ((NEW.relationship_type = 'CANCELS'
                     AND action_sale.transaction_status = 'CANCELLED')
                    OR (NEW.relationship_type = 'VOIDS'
                     AND action_sale.transaction_status = 'VOIDED'))
               AND action.source_system_id = target.source_system_id
               AND action.source_native_record_id = target.source_native_record_id
               AND action.upstream_market_system_id IS NOT DISTINCT FROM target.upstream_market_system_id
               AND action.upstream_event_object_id IS NOT DISTINCT FROM target.upstream_event_object_id
               AND action.canonical_card_id IS NOT DISTINCT FROM target.canonical_card_id
        ) THEN
            RAISE EXCEPTION 'cancel/void action status or target is incompatible'
                USING ERRCODE = '23000';
        END IF;
        IF EXISTS (
            WITH RECURSIVE targets(id) AS (
                SELECT NEW.to_observation_id
                UNION ALL
                SELECT r.to_observation_id FROM observation_relationship AS r
                JOIN targets ON r.from_observation_id = targets.id
                 WHERE r.relationship_type IN ('CANCELS', 'VOIDS')
            ) SELECT 1 FROM targets WHERE id = NEW.from_observation_id
        ) THEN
            RAISE EXCEPTION 'cancel/void relationship cycle' USING ERRCODE = '23000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_observation_identity_link_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM identity_resolution AS resolution
        JOIN identity_subject AS subject ON subject.id = resolution.identity_subject_id
        JOIN market_observation AS observation ON observation.id = NEW.observation_id
         WHERE resolution.id = NEW.identity_resolution_id
           AND (
               (observation.source_record_id IS NOT NULL
                AND subject.source_record_id = observation.source_record_id)
               OR (subject.external_object_id IS NOT NULL AND (
                   subject.external_object_id = observation.upstream_event_object_id
                   OR EXISTS (
                       SELECT 1 FROM source_record AS record
                        WHERE record.id = observation.source_record_id
                          AND record.external_object_id = subject.external_object_id
                   ) OR EXISTS (
                       SELECT 1 FROM external_object AS object
                        WHERE object.id = subject.external_object_id
                          AND object.source_system_id = observation.source_system_id
                          AND object.source_native_id = observation.source_native_record_id
                   )
               ))
           )
    ) THEN
        RAISE EXCEPTION 'identity subject is unrelated to observation'
            USING ERRCODE = '23000';
    END IF;
    IF NEW.link_role = 'SUBJECT' AND NEW.canonical_card_id IS NOT NULL THEN
        RAISE EXCEPTION 'subject identity link cannot select a canonical card'
            USING ERRCODE = '23000';
    END IF;
    IF NEW.link_role = 'RESOLVED_AS' AND NOT EXISTS (
        SELECT 1 FROM identity_resolution AS resolution
        JOIN market_observation AS observation ON observation.id = NEW.observation_id
         WHERE resolution.id = NEW.identity_resolution_id
           AND resolution.resolution_state IN ('PROVEN', 'SUPPORTED')
           AND resolution.canonical_card_id = NEW.canonical_card_id
           AND observation.canonical_card_id = NEW.canonical_card_id
           AND NEW.canonical_card_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'resolved observation identity is inconsistent'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_source_record_payload_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM source_record AS record
         WHERE record.id = NEW.source_record_id
           AND record.payload_sha256 = NEW.payload_sha256
    ) THEN
        RAISE EXCEPTION 'source payload reference must match record checksum'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_exact_decimal_valid(
    rate_text TEXT, numerator BIGINT, denominator BIGINT
) RETURNS BOOLEAN
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE digits TEXT; scale_value INTEGER; significant TEXT;
BEGIN
    IF rate_text IS NULL OR rate_text !~ '^[0-9]+(\.[0-9]+)?$' THEN
        RETURN FALSE;
    END IF;
    scale_value := CASE WHEN strpos(rate_text, '.') = 0 THEN 0
                        ELSE length(rate_text) - strpos(rate_text, '.') END;
    digits := replace(rate_text, '.', '');
    significant := regexp_replace(digits, '^0+', '');
    IF scale_value > 18 OR length(significant) NOT BETWEEN 1 AND 18 THEN
        RETURN FALSE;
    END IF;
    RETURN numerator = digits::BIGINT
       AND denominator = power(10::NUMERIC, scale_value)::BIGINT
       AND numerator > 0 AND denominator > 0;
EXCEPTION WHEN numeric_value_out_of_range OR invalid_text_representation THEN
    RETURN FALSE;
END;
$$;

CREATE FUNCTION kb_fx_rate_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT kb_exact_decimal_valid(
        NEW.rate_decimal, NEW.rate_numerator, NEW.rate_denominator
    ) THEN
        RAISE EXCEPTION 'FX rate must use an exact positive decimal representation'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION kb_fx_normalization_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE product_value BIGINT; expected_target BIGINT;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM price_component AS component
        JOIN market_observation AS observation ON observation.id = component.observation_id
         WHERE component.id = NEW.price_component_id
           AND component.observation_id = NEW.observation_id
           AND component.component_type = NEW.component_type
           AND component.knowledge_state = 'KNOWN'
           AND component.amount_minor = NEW.original_amount_minor
           AND component.currency = NEW.original_currency
           AND NEW.original_amount_minor >= 0 AND NEW.target_amount_minor >= 0
           AND length(NEW.original_currency) = 3 AND length(NEW.target_currency) = 3
           AND observation.lifecycle_state = 'DRAFT'
    ) THEN
        RAISE EXCEPTION 'FX normalization does not match its exact price component'
            USING ERRCODE = '23000';
    END IF;
    IF NOT kb_exact_decimal_valid(
        NEW.fx_rate_decimal, NEW.rate_numerator, NEW.rate_denominator
    ) THEN
        RAISE EXCEPTION 'FX normalization rate is not an exact positive decimal'
            USING ERRCODE = '23000';
    END IF;
    IF NEW.rate_observation_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM market_observation AS envelope
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
    ) THEN
        RAISE EXCEPTION 'FX rate observation does not match normalization lineage'
            USING ERRCODE = '23000';
    END IF;
    IF NEW.original_amount_minor > 9223372036854775807 / NEW.rate_numerator THEN
        RAISE EXCEPTION 'FX multiplication exceeds exact integer range'
            USING ERRCODE = '23000';
    END IF;
    product_value := NEW.original_amount_minor * NEW.rate_numerator;
    expected_target := product_value / NEW.rate_denominator
        + CASE WHEN product_value % NEW.rate_denominator
                    >= NEW.rate_denominator / 2 + NEW.rate_denominator % 2
               THEN 1 ELSE 0 END;
    IF NEW.target_amount_minor <> expected_target THEN
        RAISE EXCEPTION 'FX normalization requires exact round-half-up arithmetic'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER variant_profile_insert_state_guard
BEFORE INSERT ON variant_profile FOR EACH ROW
EXECUTE FUNCTION kb_variant_profile_insert_guard();
CREATE TRIGGER variant_profile_update_guard
BEFORE UPDATE ON variant_profile FOR EACH ROW
EXECUTE FUNCTION kb_variant_profile_update_guard();
CREATE TRIGGER variant_assignment_insert_guard
BEFORE INSERT ON variant_assignment FOR EACH ROW
EXECUTE FUNCTION kb_variant_assignment_insert_guard();
CREATE TRIGGER canonical_card_insert_integrity_guard
BEFORE INSERT ON canonical_card FOR EACH ROW
EXECUTE FUNCTION kb_canonical_card_insert_guard();
CREATE TRIGGER family_variant_applicability_insert_guard
BEFORE INSERT ON family_variant_applicability FOR EACH ROW
EXECUTE FUNCTION kb_family_applicability_insert_guard();
CREATE TRIGGER field_resolution_evidence_guard
BEFORE INSERT ON field_resolution FOR EACH ROW
EXECUTE FUNCTION kb_field_resolution_insert_guard();
CREATE TRIGGER external_object_upstream_integrity_guard
BEFORE INSERT ON external_object FOR EACH ROW
EXECUTE FUNCTION kb_external_object_insert_guard();
CREATE TRIGGER market_observation_insert_guard
BEFORE INSERT ON market_observation FOR EACH ROW
EXECUTE FUNCTION kb_market_observation_insert_guard();
CREATE TRIGGER market_observation_update_guard
BEFORE UPDATE ON market_observation FOR EACH ROW
EXECUTE FUNCTION kb_market_observation_update_guard();
CREATE TRIGGER sale_transaction_insert_guard
BEFORE INSERT ON sale_transaction FOR EACH ROW
EXECUTE FUNCTION kb_fact_insert_guard('SALE_TRANSACTION');
CREATE TRIGGER listing_snapshot_insert_guard
BEFORE INSERT ON listing_snapshot FOR EACH ROW
EXECUTE FUNCTION kb_fact_insert_guard('LISTING_SNAPSHOT');
CREATE TRIGGER provider_metric_insert_guard
BEFORE INSERT ON provider_metric_observation FOR EACH ROW
EXECUTE FUNCTION kb_fact_insert_guard('PROVIDER_METRIC_OBSERVATION');
CREATE TRIGGER population_observation_insert_guard
BEFORE INSERT ON population_observation FOR EACH ROW
EXECUTE FUNCTION kb_fact_insert_guard('POPULATION_OBSERVATION');
CREATE TRIGGER fx_rate_observation_type_guard
BEFORE INSERT ON fx_rate_observation FOR EACH ROW
EXECUTE FUNCTION kb_fact_insert_guard('FX_RATE_OBSERVATION');
CREATE TRIGGER fx_rate_observation_exact_guard
BEFORE INSERT ON fx_rate_observation FOR EACH ROW
EXECUTE FUNCTION kb_fx_rate_insert_guard();
CREATE TRIGGER price_component_integrity_guard
BEFORE INSERT ON price_component FOR EACH ROW
EXECUTE FUNCTION kb_price_component_insert_guard();
CREATE TRIGGER fx_normalization_integrity_guard
BEFORE INSERT ON fx_normalization FOR EACH ROW
EXECUTE FUNCTION kb_fx_normalization_insert_guard();
CREATE TRIGGER observation_relationship_insert_guard
BEFORE INSERT ON observation_relationship FOR EACH ROW
EXECUTE FUNCTION kb_observation_relationship_insert_guard();
CREATE TRIGGER observation_identity_link_integrity_guard
BEFORE INSERT ON observation_identity_link FOR EACH ROW
EXECUTE FUNCTION kb_observation_identity_link_insert_guard();
CREATE TRIGGER source_record_payload_insert_guard
BEFORE INSERT ON source_record_payload FOR EACH ROW
EXECUTE FUNCTION kb_source_record_payload_insert_guard();

-- Append-only/immutable tables.  Market observation and variant profile have
-- their narrowly permitted state transitions above; their deletes are still
-- rejected here.
CREATE TRIGGER variant_profile_delete_guard BEFORE DELETE ON variant_profile
FOR EACH ROW EXECUTE FUNCTION kb_reject_mutation();
CREATE TRIGGER market_observation_delete_guard BEFORE DELETE ON market_observation
FOR EACH ROW EXECUTE FUNCTION kb_reject_mutation();

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'variant_assignment', 'variant_dimension', 'variant_value',
        'canonical_card', 'family_variant_applicability',
        'allowed_variant_combination', 'source_record', 'field_claim',
        'field_resolution', 'identity_resolution', 'identity_candidate',
        'identifier_link', 'external_object', 'external_identifier',
        'source_system', 'collectible_instance', 'sale_transaction',
        'listing_snapshot', 'provider_metric_observation',
        'population_observation', 'fx_rate_observation', 'price_component',
        'fx_normalization', 'observation_relationship',
        'observation_identity_link', 'source_record_retrieval',
        'source_payload', 'source_record_payload', 'schema_migration'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_update_guard BEFORE UPDATE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION kb_reject_mutation()',
            table_name, table_name
        );
        EXECUTE format(
            'CREATE TRIGGER %I_delete_guard BEFORE DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION kb_reject_mutation()',
            table_name, table_name
        );
    END LOOP;
END;
$$;
