-- Disambiguate relation aliases from PL/pgSQL trigger records OLD and NEW.
-- Migration 0001 is already applied and remains immutable; replacing these
-- functions preserves their trigger bindings and business semantics.

CREATE OR REPLACE FUNCTION kb_field_resolution_insert_guard() RETURNS trigger
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
            SELECT 1 FROM field_resolution AS prior_resolution
             WHERE prior_resolution.id = NEW.supersedes_resolution_id
               AND prior_resolution.identity_subject_id = NEW.identity_subject_id
               AND prior_resolution.field_name = NEW.field_name
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

CREATE OR REPLACE FUNCTION kb_market_observation_insert_guard() RETURNS trigger
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
        SELECT 1 FROM market_observation AS prior_observation
         WHERE prior_observation.id = NEW.revision_of_observation_id
           AND prior_observation.lifecycle_state = 'SEALED'
           AND prior_observation.observation_type = NEW.observation_type
           AND prior_observation.source_system_id = NEW.source_system_id
           AND prior_observation.source_native_record_id = NEW.source_native_record_id
           AND prior_observation.upstream_market_system_id IS NOT DISTINCT FROM NEW.upstream_market_system_id
           AND prior_observation.upstream_event_object_id IS NOT DISTINCT FROM NEW.upstream_event_object_id
    ) THEN
        RAISE EXCEPTION 'revision target is incompatible or incomplete'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION kb_observation_relationship_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.relationship_type = 'REVISION_OF' THEN
        IF NOT EXISTS (
            SELECT 1 FROM market_observation AS current_observation
            JOIN market_observation AS target_observation
              ON target_observation.id = NEW.to_observation_id
             WHERE current_observation.id = NEW.from_observation_id
               AND current_observation.lifecycle_state = 'DRAFT'
               AND target_observation.lifecycle_state = 'SEALED'
               AND current_observation.revision_of_observation_id = NEW.to_observation_id
               AND current_observation.observation_type = target_observation.observation_type
               AND current_observation.source_system_id = target_observation.source_system_id
               AND current_observation.source_native_record_id = target_observation.source_native_record_id
               AND current_observation.upstream_market_system_id IS NOT DISTINCT FROM target_observation.upstream_market_system_id
               AND current_observation.upstream_event_object_id IS NOT DISTINCT FROM target_observation.upstream_event_object_id
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
