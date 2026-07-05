# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

`docs/` holds the tracked design set — `spec.md` (architecture + AI module + acceptance criteria, the authoritative source), `PRD.md` (product scope), `idea-validation-report.md` (market validation). The `backend/` (FastAPI + Pydantic + Anthropic generation) and `frontend/` (Next.js) are implemented with a passing backend suite (`cd backend && uv run pytest`) and a clean `next build`. When code and spec disagree, treat `docs/spec.md` as the source of truth and update it alongside the code. (The assignment brief lives untracked under `archive/`, which is gitignored.)

## What this is

OKF Weaver ingests a warehouse schema (raw SQL DDL **or** a dbt `manifest.json`), uses Claude to generate curated **Open Knowledge Format (OKF)** context per table, validates it, lets a human review/edit, and exports a portable OKF bundle. Stateless: no accounts, no persistence, no live warehouse connectors in v1.

## Commands

Backend (`backend/`, managed with `uv` — never use bare `pip`/`uv pip`):

```bash
cd backend
uv sync                                   # install/sync deps
uv run uvicorn okf_weaver.main:app --reload   # run API (needs ANTHROPIC_API_KEY)
uv run pytest                             # all tests
uv run pytest tests/test_models.py        # one file
uv run pytest tests/test_models.py::test_name -q   # one test
```

Frontend (`frontend/`):

```bash
cd frontend
npm install
npm run dev        # dev server
npm run build      # production build (also what CI runs)
```

`ANTHROPIC_API_KEY` is required by the backend and lives server-side only. `OKF_MODEL_ID` overrides the model (default `claude-sonnet-4-6`).

## Architecture

Two independently deployed services (frontend → Vercel, backend → Render/Railway). The frontend is a thin client; all parsing, LLM calls, validation, and serialization happen server-side so the API key and prompt logic stay private.

Backend pipeline (one direction, in-memory per request):

```text
ingest/  -> SchemaIR ----> ai/ (Claude tool use, streamed) ----> okf/validate.py -> okf/serialize.py
(sql_ddl, dbt_manifest)     per-table OKF + confidence          OKFBundle           Markdown+YAML .zip
```

Ingestion normalizes both input formats into one `SchemaIR` so the AI module is decoupled from input format. `/generate` streams per-table results over **SSE**. The API splits `/ingest`, `/generate`, `/validate`, `/download` so the UI can preview before spending tokens and re-validate edits without regenerating.

## Load-bearing decisions (don't silently change these)

- **Pydantic v2 is the validation backbone and single source of truth for every shape** — `SchemaIR`, `OKFBundle`/`OKFTable`/`OKFColumn`, the AI tool output, and all API bodies are the *same* Pydantic models, reused rather than redefined. Structural OKF validity *is* successful `OKFBundle` construction; referential/cross-field rules are `@model_validator` methods. Model output and human edits pass through the identical gate. This is central to the product's "trust is the product" positioning.
- **Model is `claude-sonnet-4-6` with adaptive thinking.** "Claude 4.6" is not one model (Sonnet 4.6 default, Opus 4.6 is the quality upgrade). Both are on the 4.6 request surface: adaptive thinking, **no `budget_tokens`, no assistant prefill**.
- **Constrained output via tool use, not `output_config.format`.** The 4.6 family does not support native structured outputs, so a single `emit_okf_table` tool carries the schema (generated from `OKFTable.model_json_schema()`) and the tool call is parsed with `OKFTable.model_validate(...)`.
- **OKF v0.1**, pinned in one constant (`OKF_SPEC_VERSION`) so a future Google release is a single-point update.
- **1 table per model call by default** (finest streaming, no cross-table contamination, cheap via prompt caching); column-budget batching (~40–50 cols/call, wide tables solo) is a documented optimization, not the default.
- **Trust guardrails:** never auto-publish without human approval; the model self-reports per-field confidence and low-confidence fields are surfaced first; the system prompt forbids inventing columns/tables and prefers existing dbt descriptions.
- **Deployment is via platform git integration, not CI** — Vercel (frontend) + Render (backend, `render.yaml` at repo root) auto-deploy on push to `main`. GitHub Actions (`.github/workflows/ci.yml`) is tests-on-PR only; do not add deploy steps to it. Setup steps live in the README.

## Conventions

- TDD (red-green-refactor); one test file per module (`okf/validate.py` -> `tests/test_okf_validate.py`); mock the Anthropic call in unit tests, keep any live call behind a mark.
- Commit `uv.lock`. Keep modules under ~500-600 lines.
