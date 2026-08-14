-- P0 Card Knowledge Base Foundation
-- Facts in the market/provenance ledger are append-only. Corrections are new
-- records connected through explicit supersession or revision relationships.

CREATE TABLE source_system (
    id TEXT PRIMARY KEY CHECK (id LIKE 'source_%'),
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    system_role TEXT NOT NULL CHECK (
        system_role IN ('PROVIDER', 'MARKET', 'CATALOG', 'LISTING_PLATFORM', 'HUMAN')
    ),
    created_at TEXT NOT NULL
);

CREATE TABLE variant_dimension (
    id TEXT PRIMARY KEY CHECK (id LIKE 'vdim_%'),
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE variant_value (
    id TEXT PRIMARY KEY CHECK (id LIKE 'vval_%'),
    dimension_id TEXT NOT NULL REFERENCES variant_dimension(id),
    code TEXT NOT NULL,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (dimension_id, code),
    UNIQUE (id, dimension_id)
);

CREATE TABLE variant_profile (
    id TEXT PRIMARY KEY CHECK (id LIKE 'vprofile_%'),
    fingerprint_sha256 TEXT NOT NULL UNIQUE,
    label TEXT,
    created_at TEXT NOT NULL,
    locked_at TEXT
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
    id TEXT PRIMARY KEY CHECK (id LIKE 'set_%'),
    canonical_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    release_date TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE card_family (
    id TEXT PRIMARY KEY CHECK (id LIKE 'family_%'),
    canonical_set_id TEXT NOT NULL REFERENCES canonical_set(id),
    collector_number TEXT NOT NULL,
    family_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (canonical_set_id, collector_number, family_name)
);

CREATE TABLE localized_card (
    id TEXT PRIMARY KEY CHECK (id LIKE 'localized_%'),
    card_family_id TEXT NOT NULL REFERENCES card_family(id),
    language_code TEXT NOT NULL,
    localized_name TEXT NOT NULL,
    localized_set_name TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (card_family_id, language_code)
);

CREATE TABLE family_variant_applicability (
    id TEXT PRIMARY KEY CHECK (id LIKE 'vapp_%'),
    card_family_id TEXT NOT NULL REFERENCES card_family(id),
    dimension_id TEXT NOT NULL REFERENCES variant_dimension(id),
    applicability_state TEXT NOT NULL CHECK (
        applicability_state IN ('APPLICABLE', 'NOT_APPLICABLE', 'UNKNOWN')
    ),
    created_at TEXT NOT NULL,
    UNIQUE (card_family_id, dimension_id)
);

CREATE TABLE allowed_variant_combination (
    id TEXT PRIMARY KEY CHECK (id LIKE 'vcombo_%'),
    card_family_id TEXT NOT NULL REFERENCES card_family(id),
    variant_profile_id TEXT NOT NULL REFERENCES variant_profile(id),
    created_at TEXT NOT NULL,
    UNIQUE (card_family_id, variant_profile_id)
);

CREATE TABLE canonical_card (
    id TEXT PRIMARY KEY CHECK (id LIKE 'card_%'),
    localized_card_id TEXT NOT NULL REFERENCES localized_card(id),
    variant_profile_id TEXT NOT NULL REFERENCES variant_profile(id),
    exact_comparison_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE (localized_card_id, variant_profile_id)
);

CREATE TABLE external_object (
    id TEXT PRIMARY KEY CHECK (id LIKE 'extobj_%'),
    source_system_id TEXT NOT NULL REFERENCES source_system(id),
    object_type TEXT NOT NULL,
    source_native_id TEXT NOT NULL,
    upstream_market_system_id TEXT REFERENCES source_system(id),
    upstream_native_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (source_system_id, object_type, source_native_id)
);

CREATE TABLE external_identifier (
    id TEXT PRIMARY KEY CHECK (id LIKE 'extid_%'),
    external_object_id TEXT NOT NULL REFERENCES external_object(id),
    namespace TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (external_object_id, namespace, identifier_value)
);

CREATE TABLE identifier_link (
    id TEXT PRIMARY KEY CHECK (id LIKE 'idlink_%'),
    external_identifier_id TEXT NOT NULL REFERENCES external_identifier(id),
    canonical_card_id TEXT REFERENCES canonical_card(id),
    resolution_state TEXT NOT NULL CHECK (
        resolution_state IN ('PROVEN', 'SUPPORTED', 'UNKNOWN', 'CONFLICT')
    ),
    created_at TEXT NOT NULL,
    CHECK (resolution_state <> 'PROVEN' OR canonical_card_id IS NOT NULL)
);

CREATE TABLE card_alias (
    id TEXT PRIMARY KEY CHECK (id LIKE 'alias_%'),
    canonical_card_id TEXT NOT NULL REFERENCES canonical_card(id),
    source_system_id TEXT REFERENCES source_system(id),
    alias_text TEXT NOT NULL,
    language_code TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (canonical_card_id, source_system_id, alias_text, language_code)
);

CREATE TABLE source_record (
    id TEXT PRIMARY KEY CHECK (id LIKE 'srecord_%'),
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
    id TEXT PRIMARY KEY CHECK (id LIKE 'subject_%'),
    subject_type TEXT NOT NULL,
    source_record_id TEXT REFERENCES source_record(id),
    external_object_id TEXT REFERENCES external_object(id),
    subject_label TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE identity_resolution (
    id TEXT PRIMARY KEY CHECK (id LIKE 'ires_%'),
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
    CHECK (resolution_state <> 'CONFLICT' OR canonical_card_id IS NULL),
    CHECK (supersedes_resolution_id IS NULL OR supersedes_resolution_id <> id)
);

CREATE TABLE identity_candidate (
    id TEXT PRIMARY KEY CHECK (id LIKE 'candidate_%'),
    identity_resolution_id TEXT NOT NULL REFERENCES identity_resolution(id),
    canonical_card_id TEXT NOT NULL REFERENCES canonical_card(id),
    candidate_rank INTEGER NOT NULL CHECK (candidate_rank >= 0),
    support_score TEXT,
    evidence_summary TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (identity_resolution_id, canonical_card_id)
);

CREATE TABLE field_claim (
    id TEXT PRIMARY KEY CHECK (id LIKE 'claim_%'),
    source_record_id TEXT NOT NULL REFERENCES source_record(id),
    identity_subject_id TEXT NOT NULL REFERENCES identity_subject(id),
    field_name TEXT NOT NULL,
    claimed_value_json TEXT,
    source_kind TEXT NOT NULL CHECK (
        source_kind IN ('PROVIDER', 'CATALOG', 'LISTING', 'HUMAN')
    ),
    evidence_method TEXT NOT NULL CHECK (
        evidence_method IN (
            'STRUCTURED_FIELD', 'TITLE_PARSE', 'OCR',
            'VISUAL_REFERENCE', 'MANUAL', 'DERIVED_RULE'
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
    claim_role TEXT NOT NULL CHECK (
        claim_role IN ('EVIDENCE', 'REQUEST_TARGET')
    ),
    created_at TEXT NOT NULL,
    CHECK (claim_role <> 'REQUEST_TARGET' OR resolution_state = 'UNKNOWN')
);

CREATE TABLE field_resolution (
    id TEXT PRIMARY KEY CHECK (id LIKE 'fres_%'),
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
    CHECK (resolution_state <> 'UNKNOWN' OR resolved_value_json IS NULL),
    CHECK (supersedes_resolution_id IS NULL OR supersedes_resolution_id <> id)
);

CREATE TABLE collectible_instance (
    id TEXT PRIMARY KEY CHECK (id LIKE 'instance_%'),
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
    id TEXT PRIMARY KEY CHECK (id LIKE 'observation_%'),
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
    CHECK (
        revision_of_observation_id IS NULL
        OR revision_of_observation_id <> id
    )
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
    quantity INTEGER CHECK (quantity IS NULL OR quantity >= 0)
);

CREATE TABLE provider_metric_observation (
    observation_id TEXT PRIMARY KEY REFERENCES market_observation(id),
    metric_name TEXT NOT NULL,
    metric_value_minor INTEGER,
    currency TEXT,
    window_started_at TEXT,
    window_ended_at TEXT,
    sample_size INTEGER CHECK (sample_size IS NULL OR sample_size >= 0),
    CHECK ((metric_value_minor IS NULL) = (currency IS NULL))
);

CREATE TABLE population_observation (
    observation_id TEXT PRIMARY KEY REFERENCES market_observation(id),
    grader TEXT NOT NULL,
    grade TEXT NOT NULL,
    qualifier TEXT,
    population_count INTEGER NOT NULL CHECK (population_count >= 0)
);

CREATE TABLE fx_rate_observation (
    observation_id TEXT PRIMARY KEY REFERENCES market_observation(id),
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    rate_decimal TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    rate_source TEXT NOT NULL,
    CHECK (base_currency <> quote_currency)
);

CREATE TABLE price_component (
    id TEXT PRIMARY KEY CHECK (id LIKE 'price_%'),
    observation_id TEXT NOT NULL REFERENCES market_observation(id),
    component_type TEXT NOT NULL CHECK (
        component_type IN (
            'ITEM_PRICE', 'HAMMER_PRICE', 'ACCEPTED_OFFER',
            'BUYER_PREMIUM', 'SHIPPING', 'TAX', 'TOTAL'
        )
    ),
    amount_minor INTEGER,
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
    id TEXT PRIMARY KEY CHECK (id LIKE 'fxnorm_%'),
    observation_id TEXT NOT NULL REFERENCES market_observation(id),
    component_type TEXT NOT NULL,
    original_amount_minor INTEGER NOT NULL,
    original_currency TEXT NOT NULL,
    fx_rate_decimal TEXT NOT NULL,
    rate_observation_id TEXT REFERENCES market_observation(id),
    rate_source TEXT NOT NULL,
    rate_effective_date TEXT NOT NULL,
    target_currency TEXT NOT NULL,
    target_amount_minor INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (original_currency <> target_currency),
    UNIQUE (observation_id, component_type, target_currency)
);

CREATE TABLE observation_relationship (
    id TEXT PRIMARY KEY CHECK (id LIKE 'orel_%'),
    from_observation_id TEXT NOT NULL REFERENCES market_observation(id),
    to_observation_id TEXT NOT NULL REFERENCES market_observation(id),
    relationship_type TEXT NOT NULL CHECK (
        relationship_type IN (
            'DUPLICATE_OF', 'AGGREGATOR_OF', 'RELIST_OF',
            'REVISION_OF', 'CANCELS', 'VOIDS'
        )
    ),
    created_at TEXT NOT NULL,
    CHECK (from_observation_id <> to_observation_id),
    UNIQUE (from_observation_id, to_observation_id, relationship_type)
);

CREATE TABLE observation_identity_link (
    id TEXT PRIMARY KEY CHECK (id LIKE 'oilink_%'),
    observation_id TEXT NOT NULL REFERENCES market_observation(id),
    identity_resolution_id TEXT NOT NULL REFERENCES identity_resolution(id),
    canonical_card_id TEXT REFERENCES canonical_card(id),
    link_role TEXT NOT NULL CHECK (link_role IN ('SUBJECT', 'RESOLVED_AS')),
    created_at TEXT NOT NULL,
    UNIQUE (observation_id, identity_resolution_id, link_role)
);

CREATE INDEX market_observation_card_time_idx
    ON market_observation(canonical_card_id, observed_at);
CREATE INDEX market_observation_upstream_idx
    ON market_observation(upstream_event_object_id);
CREATE INDEX identity_candidate_resolution_idx
    ON identity_candidate(identity_resolution_id, candidate_rank);
CREATE INDEX field_resolution_subject_field_idx
    ON field_resolution(identity_subject_id, field_name, created_at);

CREATE TRIGGER variant_profile_update_guard
BEFORE UPDATE ON variant_profile
WHEN NOT (
    OLD.locked_at IS NULL
    AND NEW.locked_at IS NOT NULL
    AND NEW.id = OLD.id
    AND NEW.fingerprint_sha256 = OLD.fingerprint_sha256
    AND NEW.label IS OLD.label
    AND NEW.created_at = OLD.created_at
)
BEGIN
    SELECT RAISE(ABORT, 'variant profiles are immutable after creation');
END;

CREATE TRIGGER variant_profile_delete_guard
BEFORE DELETE ON variant_profile
BEGIN
    SELECT RAISE(ABORT, 'variant profiles are append-only');
END;

CREATE TRIGGER variant_assignment_insert_guard
BEFORE INSERT ON variant_assignment
WHEN (SELECT locked_at FROM variant_profile WHERE id = NEW.profile_id) IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'locked variant profiles cannot gain assignments');
END;

CREATE TRIGGER variant_assignment_update_guard
BEFORE UPDATE ON variant_assignment
BEGIN
    SELECT RAISE(ABORT, 'variant assignments are immutable');
END;

CREATE TRIGGER variant_assignment_delete_guard
BEFORE DELETE ON variant_assignment
BEGIN
    SELECT RAISE(ABORT, 'variant assignments are append-only');
END;

CREATE TRIGGER field_resolution_evidence_guard
BEFORE INSERT ON field_resolution
WHEN NEW.based_on_claim_id IS NOT NULL
 AND (SELECT claim_role FROM field_claim WHERE id = NEW.based_on_claim_id) = 'REQUEST_TARGET'
BEGIN
    SELECT RAISE(ABORT, 'a request target is not evidence');
END;

CREATE TRIGGER field_resolution_claim_subject_guard
BEFORE INSERT ON field_resolution
WHEN NEW.based_on_claim_id IS NOT NULL
 AND EXISTS (
    SELECT 1 FROM field_claim
    WHERE id = NEW.based_on_claim_id
      AND (
        identity_subject_id <> NEW.identity_subject_id
        OR field_name <> NEW.field_name
      )
 )
BEGIN
    SELECT RAISE(ABORT, 'field resolution evidence must match subject and field');
END;

CREATE TRIGGER sale_transaction_type_guard
BEFORE INSERT ON sale_transaction
WHEN (SELECT observation_type FROM market_observation WHERE id = NEW.observation_id)
     IS NOT 'SALE_TRANSACTION'
BEGIN
    SELECT RAISE(ABORT, 'sale details require a sale observation');
END;

CREATE TRIGGER listing_snapshot_type_guard
BEFORE INSERT ON listing_snapshot
WHEN (SELECT observation_type FROM market_observation WHERE id = NEW.observation_id)
     IS NOT 'LISTING_SNAPSHOT'
BEGIN
    SELECT RAISE(ABORT, 'listing details require a listing observation');
END;

CREATE TRIGGER provider_metric_type_guard
BEFORE INSERT ON provider_metric_observation
WHEN (SELECT observation_type FROM market_observation WHERE id = NEW.observation_id)
     IS NOT 'PROVIDER_METRIC_OBSERVATION'
BEGIN
    SELECT RAISE(ABORT, 'provider metric details require a metric observation');
END;

CREATE TRIGGER population_observation_type_guard
BEFORE INSERT ON population_observation
WHEN (SELECT observation_type FROM market_observation WHERE id = NEW.observation_id)
     IS NOT 'POPULATION_OBSERVATION'
BEGIN
    SELECT RAISE(ABORT, 'population details require a population observation');
END;

CREATE TRIGGER fx_rate_observation_type_guard
BEFORE INSERT ON fx_rate_observation
WHEN (SELECT observation_type FROM market_observation WHERE id = NEW.observation_id)
     IS NOT 'FX_RATE_OBSERVATION'
BEGIN
    SELECT RAISE(ABORT, 'FX details require an FX rate observation');
END;

CREATE TRIGGER fx_normalization_rate_type_guard
BEFORE INSERT ON fx_normalization
WHEN NEW.rate_observation_id IS NOT NULL
 AND (SELECT observation_type FROM market_observation WHERE id = NEW.rate_observation_id)
     IS NOT 'FX_RATE_OBSERVATION'
BEGIN
    SELECT RAISE(ABORT, 'FX normalization rate lineage must reference an FX observation');
END;

-- Append-only fact guards. A correction is a new row with supersession or
-- revision linkage, never an UPDATE/DELETE of history.
CREATE TRIGGER source_record_update_guard BEFORE UPDATE ON source_record
BEGIN SELECT RAISE(ABORT, 'source records are append-only'); END;
CREATE TRIGGER source_record_delete_guard BEFORE DELETE ON source_record
BEGIN SELECT RAISE(ABORT, 'source records are append-only'); END;
CREATE TRIGGER field_claim_update_guard BEFORE UPDATE ON field_claim
BEGIN SELECT RAISE(ABORT, 'field claims are append-only'); END;
CREATE TRIGGER field_claim_delete_guard BEFORE DELETE ON field_claim
BEGIN SELECT RAISE(ABORT, 'field claims are append-only'); END;
CREATE TRIGGER field_resolution_update_guard BEFORE UPDATE ON field_resolution
BEGIN SELECT RAISE(ABORT, 'field resolutions are append-only'); END;
CREATE TRIGGER field_resolution_delete_guard BEFORE DELETE ON field_resolution
BEGIN SELECT RAISE(ABORT, 'field resolutions are append-only'); END;
CREATE TRIGGER identity_resolution_update_guard BEFORE UPDATE ON identity_resolution
BEGIN SELECT RAISE(ABORT, 'identity resolutions are append-only'); END;
CREATE TRIGGER identity_resolution_delete_guard BEFORE DELETE ON identity_resolution
BEGIN SELECT RAISE(ABORT, 'identity resolutions are append-only'); END;
CREATE TRIGGER identity_candidate_update_guard BEFORE UPDATE ON identity_candidate
BEGIN SELECT RAISE(ABORT, 'identity candidates are append-only'); END;
CREATE TRIGGER identity_candidate_delete_guard BEFORE DELETE ON identity_candidate
BEGIN SELECT RAISE(ABORT, 'identity candidates are append-only'); END;
CREATE TRIGGER canonical_card_update_guard BEFORE UPDATE ON canonical_card
BEGIN SELECT RAISE(ABORT, 'canonical cards are immutable'); END;
CREATE TRIGGER canonical_card_delete_guard BEFORE DELETE ON canonical_card
BEGIN SELECT RAISE(ABORT, 'canonical cards are append-only'); END;
CREATE TRIGGER market_observation_update_guard BEFORE UPDATE ON market_observation
BEGIN SELECT RAISE(ABORT, 'market observations are append-only'); END;
CREATE TRIGGER market_observation_delete_guard BEFORE DELETE ON market_observation
BEGIN SELECT RAISE(ABORT, 'market observations are append-only'); END;
CREATE TRIGGER sale_transaction_update_guard BEFORE UPDATE ON sale_transaction
BEGIN SELECT RAISE(ABORT, 'sale facts are append-only'); END;
CREATE TRIGGER sale_transaction_delete_guard BEFORE DELETE ON sale_transaction
BEGIN SELECT RAISE(ABORT, 'sale facts are append-only'); END;
CREATE TRIGGER listing_snapshot_update_guard BEFORE UPDATE ON listing_snapshot
BEGIN SELECT RAISE(ABORT, 'listing facts are append-only'); END;
CREATE TRIGGER listing_snapshot_delete_guard BEFORE DELETE ON listing_snapshot
BEGIN SELECT RAISE(ABORT, 'listing facts are append-only'); END;
CREATE TRIGGER provider_metric_update_guard BEFORE UPDATE ON provider_metric_observation
BEGIN SELECT RAISE(ABORT, 'provider metrics are append-only'); END;
CREATE TRIGGER provider_metric_delete_guard BEFORE DELETE ON provider_metric_observation
BEGIN SELECT RAISE(ABORT, 'provider metrics are append-only'); END;
CREATE TRIGGER population_observation_update_guard BEFORE UPDATE ON population_observation
BEGIN SELECT RAISE(ABORT, 'population facts are append-only'); END;
CREATE TRIGGER population_observation_delete_guard BEFORE DELETE ON population_observation
BEGIN SELECT RAISE(ABORT, 'population facts are append-only'); END;
CREATE TRIGGER fx_rate_observation_update_guard BEFORE UPDATE ON fx_rate_observation
BEGIN SELECT RAISE(ABORT, 'FX facts are append-only'); END;
CREATE TRIGGER fx_rate_observation_delete_guard BEFORE DELETE ON fx_rate_observation
BEGIN SELECT RAISE(ABORT, 'FX facts are append-only'); END;
CREATE TRIGGER price_component_update_guard BEFORE UPDATE ON price_component
BEGIN SELECT RAISE(ABORT, 'price components are append-only'); END;
CREATE TRIGGER price_component_delete_guard BEFORE DELETE ON price_component
BEGIN SELECT RAISE(ABORT, 'price components are append-only'); END;
CREATE TRIGGER fx_normalization_update_guard BEFORE UPDATE ON fx_normalization
BEGIN SELECT RAISE(ABORT, 'FX normalizations are append-only'); END;
CREATE TRIGGER fx_normalization_delete_guard BEFORE DELETE ON fx_normalization
BEGIN SELECT RAISE(ABORT, 'FX normalizations are append-only'); END;
CREATE TRIGGER observation_relationship_update_guard BEFORE UPDATE ON observation_relationship
BEGIN SELECT RAISE(ABORT, 'observation relationships are append-only'); END;
CREATE TRIGGER observation_relationship_delete_guard BEFORE DELETE ON observation_relationship
BEGIN SELECT RAISE(ABORT, 'observation relationships are append-only'); END;

-- Stable generic dimensions. UNKNOWN is an explicit value; it is never
-- replaced with a commercial default because a provider omitted a field.
INSERT INTO variant_dimension(id, code, name, created_at) VALUES
    ('vdim_edition_stamp', 'edition_stamp', 'Edition stamp', '1970-01-01T00:00:00Z'),
    ('vdim_shadow_treatment', 'shadow_treatment', 'Shadow treatment', '1970-01-01T00:00:00Z'),
    ('vdim_print_run', 'print_run', 'Print run', '1970-01-01T00:00:00Z'),
    ('vdim_finish', 'finish', 'Finish', '1970-01-01T00:00:00Z'),
    ('vdim_foil_pattern', 'foil_pattern', 'Foil pattern', '1970-01-01T00:00:00Z'),
    ('vdim_stamp', 'stamp', 'Additional stamp', '1970-01-01T00:00:00Z'),
    ('vdim_promo_type', 'promo_type', 'Promo type', '1970-01-01T00:00:00Z');

INSERT INTO variant_value(id, dimension_id, code, label, created_at) VALUES
    ('vval_edition_first', 'vdim_edition_stamp', 'FIRST_EDITION', 'First Edition', '1970-01-01T00:00:00Z'),
    ('vval_edition_no_first', 'vdim_edition_stamp', 'NO_FIRST_EDITION_STAMP', 'No First Edition stamp', '1970-01-01T00:00:00Z'),
    ('vval_edition_unknown', 'vdim_edition_stamp', 'UNKNOWN', 'Unknown edition stamp', '1970-01-01T00:00:00Z'),
    ('vval_shadowless', 'vdim_shadow_treatment', 'SHADOWLESS', 'Shadowless', '1970-01-01T00:00:00Z'),
    ('vval_shadowed', 'vdim_shadow_treatment', 'SHADOWED', 'Shadowed', '1970-01-01T00:00:00Z'),
    ('vval_shadow_unknown', 'vdim_shadow_treatment', 'UNKNOWN', 'Unknown shadow treatment', '1970-01-01T00:00:00Z'),
    ('vval_print_run_unknown', 'vdim_print_run', 'UNKNOWN', 'Unknown print run', '1970-01-01T00:00:00Z'),
    ('vval_finish_holo', 'vdim_finish', 'HOLO', 'Holo', '1970-01-01T00:00:00Z'),
    ('vval_finish_reverse', 'vdim_finish', 'REVERSE_HOLO', 'Reverse Holo', '1970-01-01T00:00:00Z'),
    ('vval_finish_non_holo', 'vdim_finish', 'NON_HOLO', 'Non-Holo', '1970-01-01T00:00:00Z'),
    ('vval_finish_unknown', 'vdim_finish', 'UNKNOWN', 'Unknown finish', '1970-01-01T00:00:00Z'),
    ('vval_foil_standard', 'vdim_foil_pattern', 'STANDARD', 'Standard foil', '1970-01-01T00:00:00Z'),
    ('vval_foil_cosmos', 'vdim_foil_pattern', 'COSMOS', 'Cosmos foil', '1970-01-01T00:00:00Z'),
    ('vval_foil_galaxy', 'vdim_foil_pattern', 'GALAXY', 'Galaxy foil', '1970-01-01T00:00:00Z'),
    ('vval_foil_cracked_ice', 'vdim_foil_pattern', 'CRACKED_ICE', 'Cracked Ice foil', '1970-01-01T00:00:00Z'),
    ('vval_foil_poke_ball', 'vdim_foil_pattern', 'POKE_BALL', 'Poke Ball foil', '1970-01-01T00:00:00Z'),
    ('vval_foil_master_ball', 'vdim_foil_pattern', 'MASTER_BALL', 'Master Ball foil', '1970-01-01T00:00:00Z'),
    ('vval_foil_unknown', 'vdim_foil_pattern', 'UNKNOWN', 'Unknown foil pattern', '1970-01-01T00:00:00Z'),
    ('vval_stamp_none', 'vdim_stamp', 'NO_ADDITIONAL_STAMP', 'No additional stamp', '1970-01-01T00:00:00Z'),
    ('vval_stamp_prerelease', 'vdim_stamp', 'PRERELEASE', 'Prerelease stamp', '1970-01-01T00:00:00Z'),
    ('vval_stamp_unknown', 'vdim_stamp', 'UNKNOWN', 'Unknown stamp', '1970-01-01T00:00:00Z'),
    ('vval_promo', 'vdim_promo_type', 'PROMO', 'Promo', '1970-01-01T00:00:00Z'),
    ('vval_non_promo', 'vdim_promo_type', 'NON_PROMO', 'Non-promo', '1970-01-01T00:00:00Z'),
    ('vval_promo_unknown', 'vdim_promo_type', 'UNKNOWN', 'Unknown promo type', '1970-01-01T00:00:00Z');
