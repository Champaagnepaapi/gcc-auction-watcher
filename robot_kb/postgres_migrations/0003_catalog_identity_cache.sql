CREATE TABLE catalog_identity_snapshot (
    id TEXT PRIMARY KEY,
    source_system_id TEXT NOT NULL REFERENCES source_system(id),
    source_native_id TEXT NOT NULL,
    language_code TEXT NOT NULL,
    provider_set_id TEXT NOT NULL,
    provider_set_name TEXT NOT NULL,
    provider_card_name TEXT NOT NULL,
    local_id TEXT NOT NULL,
    official_card_count INTEGER,
    variants_json TEXT,
    macro_lookup_key_sha256 TEXT NOT NULL,
    fingerprint_sha256 TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (length(language_code) >= 2),
    CHECK (length(provider_set_id) > 0),
    CHECK (length(provider_set_name) > 0),
    CHECK (length(provider_card_name) > 0),
    CHECK (length(local_id) > 0),
    CHECK (official_card_count IS NULL OR official_card_count > 0),
    UNIQUE(
        source_system_id,
        source_native_id,
        language_code,
        fingerprint_sha256,
        observed_at
    )
);

CREATE INDEX catalog_identity_snapshot_lookup_idx
ON catalog_identity_snapshot(source_system_id, macro_lookup_key_sha256, observed_at DESC);

CREATE INDEX catalog_identity_snapshot_native_idx
ON catalog_identity_snapshot(source_system_id, source_native_id, language_code, observed_at DESC);
