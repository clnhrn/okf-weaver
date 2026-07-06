# OKF Weaver

Turn any **relational database** schema — a data warehouse or an operational Postgres/SQL Server/MySQL database — into a curated, validated, portable **Open Knowledge Format (OKF)** bundle: trustworthy, machine-readable context for AI agents, analysts, and the engineers who inherited the database.

AI agents, analysts, and engineers produce confident-but-wrong answers about company data because the semantic context (what a column _means_, how "revenue" is defined, which table is the source of truth) lives in people's heads and scattered docs rather than in a form machines can consume — whether that's an analytics warehouse or an operational database nobody documented. OKF Weaver ingests a schema (raw SQL DDL, including a `pg_dump`/SSMS export, or a dbt `manifest.json`), uses Claude to generate curated OKF context with per-field confidence, validates it, lets a human review and approve, and exports a portable OKF bundle.

**New here?** See the [**user guide**](docs/guide.md) — export your schema, generate a bundle, and put it to work.

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

| Env var                | Purpose                                                              | Default             |
| ---------------------- | ------------------------------------------------------------------- | ------------------- |
| `ANTHROPIC_API_KEY`    | Claude API key (backend only)                                       | — (required)        |
| `OKF_MODEL_ID`         | Claude model id                                                     | `claude-sonnet-4-6` |
| `OKF_ALLOWED_ORIGINS`  | Comma-separated browser origins allowed by CORS                     | Vercel app + localhost |
| `OKF_DAILY_BUDGET_USD` | Estimated-spend ceiling per 24h window; `/generate` refuses above it (`0`/unset disables) | `0` (disabled) |
| `NEXT_PUBLIC_API_BASE` | Backend origin the frontend calls (also drives the CSP `connect-src`) | `http://127.0.0.1:8000` |

For a public deployment, set `OKF_DAILY_BUDGET_USD` (the app-level cost-DoS backstop) **and** a hard spend limit on the API key in the Anthropic Console — the latter is the ultimate wallet guarantee since a stateless, account-less service can't bind abuse to a single user.

## Deployment

CI (GitHub Actions) runs the backend tests and frontend build on every PR against `main`. Deployment is handled by each platform's own Git integration on push to `main` — not by CI.

**Backend → Render.** Connect the repo as a **Blueprint**; [`render.yaml`](render.yaml) defines the service (root `backend/`, `uv sync` + `uvicorn`, health check `/api/health`). Set `ANTHROPIC_API_KEY` in the Render dashboard (kept out of git via `sync: false`).

**Frontend → Vercel.** Import the repo, set **Root Directory** to `frontend/` (Next.js auto-detected). Set `NEXT_PUBLIC_API_BASE` to the Render backend URL. Vercel builds previews on PRs and deploys `main` to production.

Secrets live in the platform dashboards (env vars), never in the repo.

## Documentation

- [`docs/guide.md`](docs/guide.md) — **user guide**: export a schema from your database, generate a bundle, and use/organize it
- [`docs/spec.md`](docs/spec.md) — architecture, AI module design, and acceptance criteria
