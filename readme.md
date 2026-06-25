# GovLens: Federal AI Policy Data Platform

GovLens is an AI Data Engineering portfolio project that turns public federal policy documents into governed, searchable, AI-ready data.

The project is not meant to be "just another chatbot." The main product is a reliable document intelligence pipeline: ingest public government documents, extract text and metadata, validate quality, version the source records, create chunks and embeddings, and support retrieval with citations and lineage. A small Q&A or briefing UI is only the demonstration layer.

## Why This Project

GovLens shows AI Data Engineering skills because the hard problem is not only generating an answer. The hard problem is building a trusted data foundation for answers:

- Which public sources should be searched?
- Which documents are authoritative and current?
- Which chunks support the answer?
- Are citations traceable to original source URLs?
- Did a document change since the last ingestion run?
- Did extraction, metadata, or embedding quality fail?

This is stronger for an AI Data Engineer role than a simple request-and-answer app because it demonstrates data ingestion, metadata modeling, quality gates, lineage, retrieval evaluation, and production observability.

## Initial Domain

Start with one narrow domain:

**Federal AI policy, AI workforce guidance, and public-sector AI governance.**

Keeping the domain narrow makes the retrieval problem easier to evaluate and makes the project more credible. The first version should ingest a limited corpus of public documents from sources such as OPM pages, GAO reports, Federal Register notices, Congress.gov records, and public agency PDFs related to AI policy and workforce modernization.

## Core Pipeline

```text
Public PDFs / HTML / CSV / APIs
-> source registry
-> raw document storage
-> text extraction
-> metadata extraction
-> deduplication and versioning
-> quality checks
-> chunking
-> embeddings
-> PostgreSQL tables + pgvector index
-> hybrid retrieval API
-> cited answers / briefings
-> lineage and evaluation dashboard
```

## What The System Should Answer

Example user requests:

- "Find recent federal activity related to AI workforce training."
- "Which public sources discuss AI risk management for agencies?"
- "Summarize recent AI governance guidance and cite the source documents."
- "Show documents related to federal AI hiring, skills, and workforce planning."

The answer should include citations and metadata, not just a fluent summary.

## Why Retrieval Is The Hard Part

GovLens retrieval is harder than a normal keyword search because the system has to combine:

- user intent detection;
- source routing;
- keyword search;
- vector similarity search;
- agency/date/document-type filters;
- document version awareness;
- citation ranking;
- source authority checks.

The goal is not only to retrieve similar text. The goal is to retrieve the right evidence from the right public source and prove where the answer came from.

## Data Model Ideas

Minimum useful tables:

- `sources`: source URL, source type, agency, domain, owner, active status.
- `documents`: document ID, title, source URL, agency, publication date, document type, hash, version, ingestion status.
- `raw_objects`: raw PDF/HTML/CSV object path and content hash.
- `extracted_text`: cleaned text, extraction method, extraction quality score.
- `chunks`: document ID, chunk number, text, token count, section heading.
- `embeddings`: chunk ID, model name, embedding version, vector.
- `quality_results`: rule name, pass/fail, severity, message.
- `retrieval_logs`: query, retrieved chunks, scores, filters, latency.
- `lineage_events`: ingestion run, transformation step, source object, output object.

## Quality Gates

Before a document becomes AI-ready, check:

- source URL is reachable;
- document hash is present;
- duplicate documents are detected;
- extracted text length is above a minimum threshold;
- required metadata is present;
- dates and agencies are normalized;
- chunk sizes are valid;
- embeddings exist for the correct document version;
- failed records are quarantined instead of silently indexed.

## AI-Assisted Features

The first version should focus on the data platform. After the pipeline works, add one AI-assisted feature:

- proposed metadata tags with human-review status;
- likely duplicate or superseded document detection;
- contradiction/change detection across versions;
- automatic briefing draft with citations;
- retrieval quality evaluator that flags weak citation support.

This makes the project AI-assisted data engineering, not merely RAG.

## Recommended Architecture

| Layer | Suggested Implementation |
| --- | --- |
| Ingestion | Python + `httpx` |
| Orchestration | Prefect or Dagster |
| Extraction | PyMuPDF / `pypdf`; OCR only if needed |
| Validation | Pydantic + custom quality checks, or Great Expectations |
| Metadata store | PostgreSQL |
| Vector store | PostgreSQL + pgvector |
| Object storage | Local filesystem first, MinIO later |
| API | FastAPI |
| Retrieval | Hybrid PostgreSQL full-text search + pgvector |
| UI | Small Streamlit or simple web UI after pipeline works |
| Observability | Structured logs first; Prometheus/Grafana later |
| CI/CD | Docker Compose, pytest, GitHub Actions or Jenkins |

## MVP Build Order

1. Create the source registry and select 50-100 public AI-policy documents.
2. Ingest source files and store raw objects with hashes.
3. Extract text and metadata into PostgreSQL.
4. Add deduplication, versioning, and quality checks.
5. Chunk documents and generate embeddings.
6. Build hybrid retrieval with metadata filters.
7. Return cited results with source URL, title, agency, and date.
8. Add a small evaluation set of 30-50 questions with expected source documents.
9. Add a run dashboard showing ingestion status, quality failures, and retrieval metrics.
10. Add one AI-assisted metadata or briefing feature.

## Step 1: Source Registry

The first implemented component is a PostgreSQL source registry.

The source registry answers:

- What public sources are allowed in the pipeline?
- What type is each source: PDF, HTML, API, CSV, or other?
- Which agency, domain, and topic does each source belong to?
- How should it be fetched?
- How often should it be refreshed?
- Was the last fetch successful?
- What content hash was last seen?

This is the control table for later ingestion. The pipeline should read from `sources` instead of hardcoding URLs in Python.

### Start The Registry

```bash
cd /Users/quinn/Documents/Workspace-Codex/GovLens
docker compose up -d
```

PostgreSQL is exposed locally on port `5434`:

```text
postgresql://govlens:govlens@localhost:5434/govlens
```

### Inspect Seed Sources

```bash
docker compose exec postgres psql -U govlens -d govlens -c "select source_name, agency, source_type, refresh_policy, last_status from sources order by priority;"
```

### Current Tables

- `sources`: canonical list of public sources the pipeline may ingest.
- `ingestion_runs`: one row per ingestion run.
- `source_fetch_events`: one row per source fetch attempt.

Later steps will add document, raw object, extracted text, chunk, embedding, quality, retrieval, and lineage tables.

## Step 2: Raw Source Ingestion

The second implemented component is a Python ingestion command:

```text
scripts/ingest_sources.py
```

Business process:

1. Read active sources from the `sources` table.
2. Create an `ingestion_runs` row for this batch.
3. Fetch each source URL.
4. Compute a SHA-256 hash of the fetched bytes.
5. If the hash matches the previous hash, mark the source `unchanged`.
6. If the hash is new, save the raw content under `data/raw/`.
7. Insert one `source_fetch_events` row per source.
8. Update the `sources` table with latest hash/status/error.
9. Mark the ingestion run complete with fetched/changed/failed counts.

Install dependencies:

```bash
cd /Users/quinn/Documents/Workspace-Codex/GovLens
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Run ingestion:

```bash
python scripts/ingest_sources.py
```

Run only one source while testing:

```bash
python scripts/ingest_sources.py --limit 1
```

Inspect recent fetch events:

```bash
docker compose exec postgres psql -U govlens -d govlens -c "select s.source_name, e.status, e.http_status, left(e.content_hash, 12) as hash, e.object_path, e.fetched_at from source_fetch_events e join sources s on s.source_id = e.source_id order by e.fetched_at desc limit 10;"
```

## Comparison: GovLens vs Job-Matching App

A job-matching app can also use AI and data engineering. It may ingest resumes, parse skills, normalize job postings, and rank job fit.

GovLens is stronger for an AI Data Engineering portfolio because it naturally emphasizes:

- governed document ingestion;
- metadata and cataloging;
- source versioning;
- document quality checks;
- lineage from answer to original source;
- hybrid retrieval;
- citation grounding;
- retrieval evaluation.

A job app is often more product-oriented. GovLens is more naturally a data platform.

## Resume Positioning

**GovLens: Federal AI Policy Data Platform | Python, FastAPI, PostgreSQL/pgvector, Docker, Prefect, OpenTelemetry**

- Designed an AI-ready document pipeline that ingests public federal PDFs, HTML pages, CSV files, and APIs; extracts text and metadata; validates data quality; and publishes versioned structured and vectorized datasets.
- Implemented source registry, document-version tracking, chunk lineage, embedding metadata, and citation traceability from answer back to original public source.
- Built hybrid keyword/vector retrieval with agency, date, document-type, and source filters for evidence-grounded policy search.
- Added quality gates, failed-record quarantine, evaluation questions, retrieval metrics, and pipeline observability for ingestion reliability and answer grounding.
