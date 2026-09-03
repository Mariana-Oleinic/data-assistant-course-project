# Data Assistant

An offline-first course project for generating constraint-aware synthetic PostgreSQL data and
querying it conversationally.

## Cost-safe defaults

The application defaults to `LLM_MODE=offline`. Merely installing or importing the optional
OpenAI adapter cannot make a request. A paid request is possible only when all of the following
are done deliberately:

1. Install the `openai` optional dependency.
2. Set `LLM_MODE=openai`.
3. Set `ALLOW_PAID_LLM=true`.
4. Provide `OPENAI_API_KEY`.

The committed `.env.example` leaves paid integrations disabled and contains no credentials.
Langfuse is also optional and disabled whenever its key pair is absent.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[app,dev]'
pytest
```

The initial scaffold contains the safe provider boundary and offline implementation. DDL parsing,
bulk data generation, PostgreSQL persistence, and the Streamlit interface will be added in the
next project slices.
