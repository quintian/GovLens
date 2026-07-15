-- Seed sources for the first GovLens domain:
-- Federal AI policy, AI workforce guidance, and public-sector AI governance.
--
-- These are not all the documents the final project will ingest.
-- They are a starter set so the registry has real public sources on day one.
--
-- The INSERT uses ON CONFLICT so the seed file is safe to rerun:
-- if a source URL already exists, the metadata is updated instead of creating
-- a duplicate row.

INSERT INTO sources (
    source_name,
    source_url,
    source_type,
    agency,
    domain,
    topic,
    fetch_method,
    refresh_policy,
    priority,
    notes
) VALUES
(
    -- Federal Register HTML page. Good first source because HTML extraction is
    -- easier than scanned PDFs and the document is central to federal AI policy.
    'Executive Order 14110 on Safe, Secure, and Trustworthy AI',
    'https://www.federalregister.gov/documents/2023/11/01/2023-24283/safe-secure-and-trustworthy-development-and-use-of-artificial-intelligence',
    'html',
    'Federal Register',
    'federal_ai_policy',
    'AI governance',
    'http_get',
    'monthly',
    10,
    'Anchor policy document for federal AI governance.'
),
(
    -- Public PDF. This will test the later PDF extraction path.
    'OMB Memorandum M-24-10 on Agency Use of AI',
    'https://www.whitehouse.gov/wp-content/uploads/2024/03/M-24-10-Advancing-Governance-Innovation-and-Risk-Management-for-Agency-Use-of-Artificial-Intelligence.pdf',
    'pdf',
    'Office of Management and Budget',
    'federal_ai_policy',
    'AI governance',
    'http_get',
    'monthly',
    20,
    'Policy memo for agency AI governance, innovation, and risk management.'
),
(
    -- Direct public GAO PDF. The GAO product landing page may block scripted
    -- fetches, but this PDF URL is the raw document we need for ingestion.
    'GAO Artificial Intelligence Accountability Framework',
    'https://www.gao.gov/assets/gao-21-519sp.pdf',
    'pdf',
    'Government Accountability Office',
    'federal_ai_policy',
    'AI accountability',
    'http_get',
    'monthly',
    30,
    'Framework source for AI accountability and governance concepts.'
),
(
    -- Technical PDF often referenced by public-sector AI governance work.
    'NIST AI Risk Management Framework 1.0',
    'https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf',
    'pdf',
    'National Institute of Standards and Technology',
    'federal_ai_policy',
    'AI risk management',
    'http_get',
    'monthly',
    40,
    'Technical framework often referenced by federal AI governance work.'
),
(
    -- API registry entry. Later ingestion will use API-specific logic and
    -- probably an API key for Congress.gov searches.
    'Congress.gov API Root',
    'https://api.congress.gov/v3/',
    'api',
    'Library of Congress',
    'federal_legislation',
    'AI legislation',
    'api_query',
    'weekly',
    50,
    'Registry entry for future bill and legislation search ingestion. Requires API-specific ingestion and likely an API key.'
)
-- source_url is unique, so this makes the seed idempotent.
ON CONFLICT (source_url) DO UPDATE SET
    source_name = EXCLUDED.source_name,
    source_type = EXCLUDED.source_type,
    agency = EXCLUDED.agency,
    domain = EXCLUDED.domain,
    topic = EXCLUDED.topic,
    fetch_method = EXCLUDED.fetch_method,
    refresh_policy = EXCLUDED.refresh_policy,
    priority = EXCLUDED.priority,
    notes = EXCLUDED.notes,
    updated_at = now();
