# Data Assistant

An offline-first course project that turns PostgreSQL DDL into realistic, relational synthetic
data. It includes a Streamlit interface, PostgreSQL persistence, CSV/ZIP export, safe textual
edits, and a small offline preview of the future “Talk to your data” workflow.

## Current scope

Phase 1 is implemented as a usable vertical slice:

- Upload `.sql`, `.ddl`, or `.txt` PostgreSQL schemas containing up to seven tables.
- Parse columns, PostgreSQL types, nullability, defaults, primary keys, unique constraints,
  foreign keys, and common `CHECK` constraints, including constraints added with `ALTER TABLE`.
- Generate 1–10,000 seeded rows per table with Faker while preserving relational integrity.
- Preview every table and validate required, unique, primary-key, foreign-key, and common
  `CHECK` rules.
- Apply bounded offline edits such as `Regenerate email` or `Make notes 20% null`.
- Download one table as CSV or the entire dataset as a ZIP archive.
- Optionally save versioned datasets in PostgreSQL for the Talk to your data tab.

The Talk to your data tab currently supports the safe offline pattern `show all <table>`. Broader
natural-language SQL, aggregate results, charts, and conversational history belong to Phases 2–3.

## No-cost behavior

The default configuration is fully offline and makes no OpenAI or Langfuse requests. The local
generator, parser, validation, exports, edits, and simple table query do not require API keys.

The optional OpenAI adapter cannot make a request unless all of these are deliberately configured:

1. Install `pip install -e '.[openai]'`.
2. Set `LLM_MODE=openai`.
3. Set `ALLOW_PAID_LLM=true`.
4. Set `OPENAI_API_KEY`.

Langfuse has a lazy optional client factory, but stays disabled unless `ENABLE_LANGFUSE=true` and
both credentials are configured. Never commit a real `.env` file or API key.

## Run locally

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[app,dev]'
cp .env.example .env
streamlit run app.py
```

PostgreSQL persistence is optional. If it is unavailable, uncheck **Save to PostgreSQL**; generated
data remains available in the current session and can still be downloaded.

## Run with Docker Compose

```bash
docker compose up --build
```

Then open `http://localhost:8501`. Compose starts Streamlit and PostgreSQL with development-only
credentials. Stop it with `docker compose down`.

## Quality checks

```bash
pytest -q
ruff check .
ruff format --check .
```

The tests cover paid-API safety gates, DDL parsing, deterministic generation, relational and
`CHECK` validation, exports, textual edits, PostgreSQL type mapping, and the Streamlit workflow.

## Project layout

```text
app.py                         Streamlit UI
examples/library.ddl           Built-in relational demo schema
src/data_assistant/schema      DDL models and parser
src/data_assistant/generation  Generator, validation, editing, and exports
src/data_assistant/persistence PostgreSQL versioned dataset store
src/data_assistant/llm         Offline provider and guarded optional OpenAI adapter
tests                          Unit and Streamlit workflow tests
```

## Known boundaries

- The parser targets ordinary PostgreSQL `CREATE TABLE` and `ALTER TABLE ... ADD CONSTRAINT`
  statements. Generated columns, partitioning, custom enum types, and cross-schema duplicate table
  names are outside the current course scope.
- Common boolean, comparison, range, null, and `IN` checks are validated safely. Unsupported SQL
  expressions are left for PostgreSQL to enforce when persistence is enabled.
- Cyclic foreign keys between different tables are rejected with a clear error; self-references are
  supported.
- The supplied Google Drive sample schemas require access permission, so the repository includes a
  representative library schema and accepts the original files through upload.
