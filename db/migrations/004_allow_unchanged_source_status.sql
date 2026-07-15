-- Existing databases created before Step 2 did not allow "unchanged" as a
-- source.last_status value. The ingestion script uses "unchanged" when the
-- downloaded content hash matches the previous content hash.

ALTER TABLE sources
    DROP CONSTRAINT IF EXISTS sources_last_status_check;

ALTER TABLE sources
    ADD CONSTRAINT sources_last_status_check
    CHECK (
        last_status IN (
            'not_started',
            'success',
            'unchanged',
            'failed',
            'quarantined',
            'disabled'
        )
    );
