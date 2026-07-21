-- Step 8: retrieval evaluation.
--
-- These tables create a small gold-question set and store evaluation metrics.
-- The goal is to prove retrieval quality instead of relying on one-off manual
-- searches that only look good in a demo.

CREATE TABLE IF NOT EXISTS evaluation_questions (
    evaluation_question_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_text TEXT NOT NULL UNIQUE,
    expected_title_contains TEXT,
    expected_source_url TEXT,
    expected_agency TEXT,
    notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_evaluation_questions_active
    ON evaluation_questions (is_active);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    evaluation_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retrieval_mode TEXT NOT NULL CHECK (
        retrieval_mode IN ('vector', 'keyword', 'hybrid')
    ),
    embedding_model TEXT NOT NULL,
    top_k INTEGER NOT NULL,
    question_count INTEGER NOT NULL DEFAULT 0,
    hit_count INTEGER NOT NULL DEFAULT 0,
    mean_reciprocal_rank DOUBLE PRECISION NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_evaluation_runs_time
    ON evaluation_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS evaluation_results (
    evaluation_result_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evaluation_run_id UUID NOT NULL REFERENCES evaluation_runs(evaluation_run_id) ON DELETE CASCADE,
    evaluation_question_id UUID NOT NULL REFERENCES evaluation_questions(evaluation_question_id),
    matched BOOLEAN NOT NULL DEFAULT FALSE,
    first_relevant_rank INTEGER,
    top_title TEXT,
    top_source_url TEXT,
    top_hybrid_score DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (evaluation_run_id, evaluation_question_id)
);

CREATE INDEX IF NOT EXISTS idx_evaluation_results_run
    ON evaluation_results (evaluation_run_id);

CREATE INDEX IF NOT EXISTS idx_evaluation_results_matched
    ON evaluation_results (matched);

INSERT INTO evaluation_questions (
    question_text,
    expected_title_contains,
    expected_agency,
    notes
)
VALUES
    (
        'What framework discusses AI risk management?',
        'NIST AI Risk Management Framework',
        'National Institute of Standards and Technology',
        'Should retrieve NIST AI RMF guidance.'
    ),
    (
        'Which memo discusses AI governance boards and Chief AI Officers?',
        'OMB Memorandum M-24-10',
        'Office of Management and Budget',
        'Should retrieve OMB M-24-10 agency governance requirements.'
    ),
    (
        'Where is the AI accountability framework described?',
        'GAO Artificial Intelligence Accountability Framework',
        'Government Accountability Office',
        'Should retrieve the GAO accountability framework.'
    ),
    (
        'Which executive order is about safe secure and trustworthy AI?',
        'Executive Order 14110',
        'Federal Register',
        'Should retrieve Executive Order 14110.'
    )
ON CONFLICT (question_text) DO UPDATE SET
    expected_title_contains = EXCLUDED.expected_title_contains,
    expected_agency = EXCLUDED.expected_agency,
    notes = EXCLUDED.notes,
    is_active = true;
