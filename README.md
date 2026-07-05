# OKF Weaver

Turn a data warehouse schema into a curated, validated, portable **Open Knowledge Format (OKF)** bundle — trustworthy, machine-readable context for AI agents and analysts.

AI agents and analysts produce confident-but-wrong answers about company data because the semantic context (what a column _means_, how "revenue" is defined, which table is the source of truth) lives in people's heads and scattered docs rather than in a form machines can consume. OKF Weaver ingests a schema, uses Claude to generate curated OKF context with per-field confidence, validates it, lets a human review and approve, and exports a portable OKF bundle.

## Status

v1 / MVP. Upload schema → LLM generates + validates an OKF bundle → review → download.

## Architecture

Two deployables, stateless request/response (no accounts, no persistence in v1):

- **`backend/`** — FastAPI (Python, `uv`) JSON/SSE API. Holds the `ANTHROPIC_API_KEY`; does ingestion, generation, validation, and serialization. **Pydantic v2** models are the single source of truth for every data shape and the validation backbone.
- **`frontend/`** — Next.js (TypeScript, React). Thin client: upload/paste, stream generation, review + inline edit with confidence flags, download.

```text
schema (SQL DDL | dbt manifest.json)
        -> ingest  -> SchemaIR (Pydantic)
        -> AI       -> per-table OKF via Claude tool use (streamed)
        -> validate -> OKFBundle (Pydantic + model_validator, OKF v0.1)
        -> review   -> human approves / edits
        -> serialize-> OKF Markdown+YAML .zip
```

Full detail: [`docs/spec.md`](docs/spec.md).
Product scope: [`docs/PRD.md`](docs/PRD.md).
Market/validation: [`docs/idea-validation-report.md`](docs/idea-validation-report.md).

**AI capability:** generation — schema in, curated OKF context out.

## Quick start

### Backend

```bash
cd backend
uv sync                    # install deps into .venv
export ANTHROPIC_API_KEY=sk-ant-...
uv run uvicorn okf_weaver.main:app --reload
# API on http://127.0.0.1:8000  (docs at /docs)
uv run pytest              # run tests
```

### Frontend

```bash
cd frontend
npm install
npm run dev                # http://localhost:3000
```

## Configuration

| Env var             | Purpose                       | Default             |
| ------------------- | ----------------------------- | ------------------- |
| `ANTHROPIC_API_KEY` | Claude API key (backend only) | — (required)        |
| `OKF_MODEL_ID`      | Claude model id               | `claude-sonnet-4-6` |

## Deployment

CI (GitHub Actions) runs the backend tests and frontend build on every PR against `main`. Deployment is handled by each platform's own Git integration on push to `main` — not by CI.

**Backend → Render.** Connect the repo as a **Blueprint**; [`render.yaml`](render.yaml) defines the service (root `backend/`, `uv sync` + `uvicorn`, health check `/api/health`). Set `ANTHROPIC_API_KEY` in the Render dashboard (kept out of git via `sync: false`).

**Frontend → Vercel.** Import the repo, set **Root Directory** to `frontend/` (Next.js auto-detected). Set `NEXT_PUBLIC_API_BASE` to the Render backend URL. Vercel builds previews on PRs and deploys `main` to production.

Secrets live in the platform dashboards (env vars), never in the repo.

## Documentation

- [`docs/PRD.md`](docs/PRD.md) — product requirements
- [`docs/spec.md`](docs/spec.md) — architecture, AI module design, and acceptance criteria
- [`docs/idea-validation-report.md`](docs/idea-validation-report.md) — market validation (problem, users, market, competition, why-now)
