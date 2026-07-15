-- Fixes for the first Step 2 ingestion test.
--
-- 1. Use the direct GAO PDF instead of the GAO product landing page, because
--    the landing page returned 403 to scripted ingestion.
-- 2. Keep Congress.gov in the registry, but mark it inactive for now. It is an
--    API source and should be handled by a later API-specific ingestion path.

UPDATE sources
SET source_url = 'https://www.gao.gov/assets/gao-21-519sp.pdf',
    source_type = 'pdf',
    last_status = 'not_started',
    last_http_status = NULL,
    last_error = NULL,
    current_hash = NULL,
    notes = 'Direct GAO PDF for AI accountability framework. Replaces product landing page for raw ingestion.',
    updated_at = now()
WHERE source_url = 'https://www.gao.gov/products/gao-21-519sp';

UPDATE sources
SET is_active = FALSE,
    last_status = 'disabled',
    last_error = 'Disabled until API-specific Congress.gov ingestion is implemented.',
    updated_at = now()
WHERE source_url = 'https://api.congress.gov/v3/';
