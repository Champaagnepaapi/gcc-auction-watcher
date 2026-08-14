-- P1 shadow-sidecar raw evidence retention. Earlier migrations remain frozen.
-- Payload bytes are content-addressed and shared across source records, while
-- each source record keeps an immutable reference and retrieval lineage.

CREATE TABLE kb_sidecar_payload_assertion (
    invariant_name TEXT PRIMARY KEY,
    violation_count INTEGER NOT NULL CHECK (violation_count = 0)
);

INSERT INTO kb_sidecar_payload_assertion
SELECT 'legacy source payload checksum shape', COUNT(*)
FROM source_record
WHERE length(payload_sha256) <> 64
   OR payload_sha256 GLOB '*[^0-9a-f]*';

DROP TABLE kb_sidecar_payload_assertion;

CREATE TABLE source_payload (
    payload_sha256 TEXT PRIMARY KEY,
    payload_bytes BLOB NOT NULL,
    payload_format TEXT NOT NULL CHECK (
        payload_format IN ('CANONICAL_JSON', 'UTF8_TEXT', 'BINARY')
    ),
    byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
    created_at TEXT NOT NULL,
    CHECK (length(payload_sha256) = 64),
    CHECK (payload_sha256 NOT GLOB '*[^0-9a-f]*'),
    CHECK (length(payload_bytes) = byte_length)
);

CREATE TABLE source_record_payload (
    source_record_id TEXT PRIMARY KEY REFERENCES source_record(id),
    payload_sha256 TEXT NOT NULL REFERENCES source_payload(payload_sha256),
    created_at TEXT NOT NULL
);

CREATE TRIGGER source_record_payload_insert_guard
BEFORE INSERT ON source_record_payload
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM source_record AS record
        WHERE record.id = NEW.source_record_id
          AND record.payload_sha256 = NEW.payload_sha256
    ) THEN RAISE(ABORT, 'source payload reference must match record checksum') END;
END;

CREATE TRIGGER source_payload_update_guard
BEFORE UPDATE ON source_payload
BEGIN
    SELECT RAISE(ABORT, 'source payloads are immutable');
END;

CREATE TRIGGER source_payload_delete_guard
BEFORE DELETE ON source_payload
BEGIN
    SELECT RAISE(ABORT, 'source payloads are append-only');
END;

CREATE TRIGGER source_record_payload_update_guard
BEFORE UPDATE ON source_record_payload
BEGIN
    SELECT RAISE(ABORT, 'source payload references are immutable');
END;

CREATE TRIGGER source_record_payload_delete_guard
BEFORE DELETE ON source_record_payload
BEGIN
    SELECT RAISE(ABORT, 'source payload references are append-only');
END;
