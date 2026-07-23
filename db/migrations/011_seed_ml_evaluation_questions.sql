-- Step 9 support: add more evaluation questions so the ML reranker has enough
-- grouped query examples for train/test evaluation.

INSERT INTO evaluation_questions (
    question_text,
    expected_title_contains,
    expected_agency,
    notes
)
VALUES
    (
        'How should organizations map measure and manage AI risks?',
        'NIST AI Risk Management Framework',
        'National Institute of Standards and Technology',
        'NIST AI RMF should rank highly for risk management lifecycle questions.'
    ),
    (
        'What document describes trustworthy AI risk profiles?',
        'NIST AI Risk Management Framework',
        'National Institute of Standards and Technology',
        'NIST AI RMF discusses profiles and trustworthy AI.'
    ),
    (
        'Which framework talks about governing AI risk?',
        'NIST AI Risk Management Framework',
        'National Institute of Standards and Technology',
        'NIST AI RMF should match governance and risk terms.'
    ),
    (
        'What guidance requires Chief AI Officers?',
        'OMB Memorandum M-24-10',
        'Office of Management and Budget',
        'OMB M-24-10 defines agency CAIO requirements.'
    ),
    (
        'Which memo sets minimum risk management practices for agency AI?',
        'OMB Memorandum M-24-10',
        'Office of Management and Budget',
        'OMB M-24-10 includes minimum risk management practices.'
    ),
    (
        'What guidance discusses agency AI governance boards?',
        'OMB Memorandum M-24-10',
        'Office of Management and Budget',
        'OMB M-24-10 discusses agency AI governance boards.'
    ),
    (
        'Which report describes AI accountability practices?',
        'GAO Artificial Intelligence Accountability Framework',
        'Government Accountability Office',
        'GAO accountability framework should match accountability practice questions.'
    ),
    (
        'What source covers AI accountability framework principles?',
        'GAO Artificial Intelligence Accountability Framework',
        'Government Accountability Office',
        'GAO accountability framework should match accountability framework questions.'
    ),
    (
        'Where can auditors find an AI accountability framework?',
        'GAO Artificial Intelligence Accountability Framework',
        'Government Accountability Office',
        'GAO source should match audit/accountability questions.'
    ),
    (
        'Which order directs safe secure and trustworthy AI?',
        'Executive Order 14110',
        'Federal Register',
        'Executive Order 14110 should match safe, secure, trustworthy AI questions.'
    ),
    (
        'What executive order addresses federal AI policy and trustworthy AI?',
        'Executive Order 14110',
        'Federal Register',
        'Executive Order 14110 should match executive order policy questions.'
    ),
    (
        'Where is safe secure trustworthy artificial intelligence ordered?',
        'Executive Order 14110',
        'Federal Register',
        'Executive Order 14110 should match formal order wording.'
    )
ON CONFLICT (question_text) DO UPDATE SET
    expected_title_contains = EXCLUDED.expected_title_contains,
    expected_agency = EXCLUDED.expected_agency,
    notes = EXCLUDED.notes,
    is_active = true;
