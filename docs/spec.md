# spec.md — OKF Weaver

**Product:** OKF Weaver
**Scope:** v1 / MVP — ingest a schema, generate + validate an OKF bundle, review, download.
**Companion docs:** [PRD.md](./PRD.md), [idea-validation-report.md](./idea-validation-report.md)
**Date:** 2026-07-05

---

## 1. Overview

**AI capability: Generation.** The core AI feature generates curated OKF context (table/column business definitions, source-of-truth hints) from a schema — it produces new semantic content, not a summary, search, or classification of existing text.

OKF Weaver turns a warehouse schema into a curated, validated, portable **Open Knowledge Format (OKF)** bundle. The MVP is a stateless request/response web app: the user supplies raw SQL DDL or a dbt `manifest.json`, an LLM generates OKF context, the output is validated against the OKF spec, the user reviews/edits, and downloads the bundle. No persistence, no accounts, no live warehouse connections (see PRD §5).

**Inputs → Outputs (at a glance):**

- **Input:** raw SQL DDL (`CREATE TABLE …`) _or_ a dbt `manifest.json`, uploaded or pasted.
- **Output:** a downloadable OKF v0.1 bundle (Markdown + YAML, zipped) with per-field confidence, after human review.
- **Acceptance criteria:** see §1a.

**Design principles**

- **Trust is the product.** Nothing is presented as fact without a confidence signal, and nothing is "published" without user approval.
- **Curated context, not raw schema.** The AI produces meaning (definitions, semantics), not a reformatted dump.
- **Format-conformant by construction.** Every downloadable bundle passes OKF validation; invalid output never reaches the user as final.
- **Less code.** Single Python service for backend + AI; thin Next.js UI. Stateless.

---

## 1a. Acceptance Criteria

The MVP is "done" when all of the following hold. Each maps to a test (§8) and to a PRD success metric.

**Inputs**

- Valid SQL DDL **or** a dbt `manifest.json` is accepted and parsed into a `SchemaIR`, returned as a preview before any tokens are spent.
- Malformed / unparseable input returns a **422** with field-level detail — never a 500 or silent truncation.

**Generation (the AI capability)**

- Every table in the input yields exactly one OKF entry; every generated column carries a **confidence score** in `[0, 1]`.
- Generation is constrained by tool use (`emit_okf_table`) and parsed via `OKFTable.model_validate(...)`; a malformed model response is caught and routed to the bounded repair pass, not surfaced raw.
- For long schemas, results **stream** (SSE) table-by-table.

**Validation & output**

- **100% of downloadable bundles pass OKF v0.1 validation** — a bundle is downloadable only if `OKFBundle` construction (incl. `@model_validator` cross-field rules) succeeds.
- The exported artifact is a well-formed OKF Markdown+YAML `.zip` that re-parses as valid YAML/Markdown.

**Trust / human-in-the-loop**

- Nothing is downloadable until the user **approves**; low-confidence fields are surfaced for review first.
- User edits are re-validated through the **same** `OKFBundle` gate as model output.

**End-to-end**

- The full flow (ingest → generate → review → download) completes for a representative multi-table schema.
- The `ANTHROPIC_API_KEY` is never exposed to the browser (all LLM calls are server-side).

---

## 2. System Architecture

```
┌─────────────────────┐      HTTPS/JSON      ┌──────────────────────────────┐
│   Next.js frontend  │  ───────────────────▶│      FastAPI backend         │
│   (React, Vercel)   │◀───────────────────  │      (Python, uv)            │
│                     │                       │                              │
│ • Upload / paste    │                       │  ┌────────────────────────┐  │
│ • Review & edit UI  │                       │  │  Ingestion layer       │  │
│ • Confidence flags  │                       │  │  (DDL parser / dbt)    │  │
│ • Download bundle   │                       │  └───────────┬────────────┘  │
└─────────────────────┘                       │              ▼               │
                                              │  ┌────────────────────────┐  │
                                              │  │  AI module (Claude)    │  │
                                              │  │  generate OKF context  │  │
                                              │  └───────────┬────────────┘  │
                                              │              ▼               │
                                              │  ┌────────────────────────┐  │
                                              │  │  OKF validator         │  │
                                              │  │  (schema + repair)     │  │
                                              │  └───────────┬────────────┘  │
                                              │              ▼               │
                                              │  ┌────────────────────────┐  │
                                              │  │  Bundle serializer     │  │
                                              │  │  (OKF Markdown+YAML)   │  │
                                              │  └────────────────────────┘  │
                                              └──────────────┬───────────────┘
                                                             ▼
                                                   Anthropic API (Claude)
```

**Two deployables:**

- **Frontend** — Next.js (TypeScript, React) on **Vercel**.
- **Backend** — FastAPI (Python, managed with `uv`) on **Render** (via the repo-root `render.yaml` Blueprint). Holds the `ANTHROPIC_API_KEY`; the key never touches the browser.

The frontend is a thin client: all parsing, LLM calls, validation, and serialization happen server-side so the API key and prompt logic stay private.

---

## 3. Components

### 3.1 Ingestion layer (`ingest/`)

Normalizes either input into a common internal representation before the AI ever sees it.

- **Raw SQL DDL parser** — parses `CREATE TABLE` statements into `Table` / `Column` objects (name, type, nullability, PK/FK hints, inline comments). Uses `sqlglot` for dialect-tolerant parsing.
- **dbt manifest parser** — reads `manifest.json`, extracting `nodes` of type `model`/`source`: table names, column names/types, and any existing `description` fields (a strong prior for the AI to build on).
- **Output:** a `SchemaIR` **Pydantic model** (intermediate representation) — a list of `Table` models, each holding `Column` models plus any pre-existing descriptions/relationships. This decouples the AI module from input format, and the parsers construct/validate `SchemaIR` directly so malformed input fails at the boundary with a structured error.

**Pydantic is the validation backbone throughout.** Every data structure that crosses a boundary — `SchemaIR`, the OKF bundle (`OKFBundle` / `OKFTable` / `OKFColumn`), the AI module's per-table tool output, and all API request/response bodies — is a Pydantic v2 model. This gives one place to define each shape, automatic validation with typed errors, and free FastAPI request/response validation and OpenAPI schema. Confidence scores are `confloat(ge=0, le=1)`; enums (input `format`, source-of-truth flags) are `Enum` types.

### 3.2 AI module (`ai/`) — see §4.

### 3.3 OKF validator (`okf/validate.py`)

- Validates the generated bundle against **OKF v0.1** (the initial published spec). Structural validation is expressed as the **`OKFBundle` Pydantic model** — required top-level keys, per-entity required fields, and field types are enforced by the model itself; a bundle that constructs successfully is structurally conformant by definition. Cross-field/referential rules that Pydantic can't express as plain field constraints (e.g. every column belongs to a declared table, YAML frontmatter well-formedness) are added as Pydantic **`@model_validator`** methods on `OKFBundle`. The target version is pinned in one constant (`OKF_SPEC_VERSION = "0.1"`) so a future Google release is a single-point update, not a rewrite.
- On failure, `ValidationError` is caught and converted to a structured, human-readable error report; the pipeline attempts **one bounded repair pass** (feed the errors back to the model) before surfacing to the user. User edits from the review UI are re-validated by re-constructing `OKFBundle`, so the same rules apply to model output and human edits alike.

### 3.4 Bundle serializer (`okf/serialize.py`)

- Renders the validated internal bundle to OKF's Markdown + YAML file layout and zips it for download.

### 3.5 Frontend (`web/`)

- Upload/paste input; trigger generation; render the bundle for **review and inline edit**; show per-definition **confidence flags**; download the final `.zip`.

---

## 4. AI Module Design

The AI module is the core of the product. It converts a `SchemaIR` into curated OKF content.

### 4.1 Model

- **Claude Sonnet 4.6** (`claude-sonnet-4-6`) via the Anthropic Python SDK, using **adaptive thinking** (`thinking={"type": "adaptive"}`). Chosen over Opus 4.6 for the cost/throughput of high-volume per-table generation; Opus 4.6 (`claude-opus-4-6`) is a drop-in upgrade if generation quality proves weak. The model id is configurable via `OKF_MODEL_ID`.
- **Note on "Claude 4.6":** this is not a single model — it resolves to Sonnet 4.6 (default here) or Opus 4.6. Both are on the 4.6 request surface: adaptive thinking, no `budget_tokens`, no assistant prefill.

### 4.2 Strategy: structured generation, chunked by table

Rather than stuffing the whole warehouse into one prompt (which causes the "context rot" the validation report cites), the module generates **per-table**, then assembles:

1. **Chunking** — **one table per model call by default.** This is the safest unit for a trust-first product (no cross-table contamination), gives the finest streaming granularity, and is cheap because the system prompt + OKF field definitions are a cached prefix (~0.1× cost per call via Anthropic prompt caching), so more small calls cost little more than fewer large ones. Calls run with bounded concurrency for latency. **Column-budget batching is a documented optimization, not the default:** if per-call latency on wide schemas becomes a problem, pack small tables together up to **~40–50 columns per call** (hard cap **10 tables/call**), while any table with **> 40 columns always goes solo**. Batching is budgeted on columns, not table count, because output volume — not context window (Sonnet 4.6 has 1M context / 128K output; the schema always fits) — is the binding constraint on structured-output quality.
2. **Per-table generation** — for each table, the model receives: the table's DDL/IR, its columns and types, any existing dbt descriptions, and (for context) the _names_ of related tables. It returns structured JSON: a table description, per-column business definitions, a source-of-truth flag, and a **confidence score** per generated field.
3. **Tool-constrained output** — the model returns JSON matching a fixed schema via **tool use** (a single `emit_okf_table` tool), so parsing is deterministic and we avoid free-text drift. The tool's `input_schema` is generated from the per-table **Pydantic model** (`OKFTable.model_json_schema()`) — one source of truth for the shape — and the model's tool call is parsed back with `OKFTable.model_validate(...)`, so a malformed or hallucinated field is caught immediately and routed into the repair pass. Tool use is fully supported on the 4.6 family; native structured outputs (`output_config.format`) are _not_ on Sonnet 4.6 / Opus 4.6 (they'd require Opus 4.8 / Sonnet 5), so tool use is the constraint mechanism here.
4. **Assembly** — per-table results are merged into a single internal bundle object.
5. **Validation + bounded repair** — the assembled bundle goes through the OKF validator (§3.3); on failure, one repair round-trip is attempted.

### 4.3 Prompt design

- **System prompt** pins the role ("data documentation specialist producing OKF context"), the OKF field definitions, and hard rules: _do not invent columns or tables; if a definition is uncertain, say so and lower confidence; prefer existing dbt descriptions over guesses._
- **Confidence signal** — the model self-reports confidence per field; low-confidence items are flagged in the UI so users review the riskiest definitions first. This directly serves the "accuracy/trust" risk from the validation report's pre-mortem.

### 4.4 Failure handling

- **Anthropic API errors / rate limits** — retry with backoff; surface a clear error to the user.
- **Malformed model output** — caught by structured-output parsing; retried once, then failed gracefully with the partial result preserved.
- **Validation failure after repair** — returned to the user as a reviewable draft with the specific validation errors shown, never as a "final" download.

---

## 5. Data Flow (happy path)

1. User uploads/pastes raw SQL DDL **or** `manifest.json` in the Next.js UI.
2. Frontend `POST`s the raw input to the backend.
3. **Ingestion** parses input → `SchemaIR`.
4. **AI module** generates per-table OKF content with confidence scores. `/generate` **streams** results per table as they complete (SSE), so long schemas show progress in the UI instead of a single long wait; the assembled bundle is finalized at stream end.
5. **Validator** checks the assembled bundle; one repair pass if needed.
6. Backend returns the bundle (JSON) + confidence flags + any residual validation warnings.
7. User **reviews and edits** in the UI; low-confidence fields are highlighted.
8. User clicks download → backend **serializes** the (edited) bundle to OKF Markdown+YAML and returns a `.zip`.

Everything is in-memory per request; nothing is stored after the response.

---

## 6. API (backend)

| Method | Path            | Body                                                   | Returns                                                                                                                                                    |
| ------ | --------------- | ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST` | `/api/ingest`   | `{ content: string, format?: "sql" \| "dbt_manifest" }` — `format` is **auto-detected** when omitted (JSON-ish → dbt manifest, else SQL DDL) | `SchemaIR` (parsed preview) + parse warnings                                                                                                               |
| `POST` | `/api/generate` | `SchemaIR`                                             | **SSE stream** — one `table` event per completed table (partial OKF + confidence), then a final `done` event with the assembled bundle + validation report |
| `POST` | `/api/validate` | OKF bundle (JSON, possibly user-edited)                | validation report (pass/fail + errors)                                                                                                                     |
| `POST` | `/api/download` | OKF bundle (JSON)                                      | `.zip` of OKF Markdown+YAML files                                                                                                                          |
| `GET`  | `/api/health`   | —                                                      | liveness/readiness for CI + deploy                                                                                                                         |

`/ingest` and `/generate` are split so the UI can show a parsed preview before spending tokens, and so `/validate` can be re-run after user edits without regenerating. `/generate` streams (SSE) so large schemas render table-by-table as generation proceeds rather than blocking on the full run; the Anthropic SDK's own streaming feeds each per-table result to the client as it lands.

Every request and response body is a **Pydantic model**, so FastAPI validates input at the boundary (returning 422 with field-level detail on bad payloads) and serializes typed responses — the `SchemaIR` and `OKFBundle` models defined for the pipeline _are_ the API contract, reused directly rather than redefined.

---

## 7. Tech Stack

| Concern               | Choice                                                                                               |
| --------------------- | ---------------------------------------------------------------------------------------------------- |
| Backend               | FastAPI (Python), managed with `uv`                                                                  |
| Validation / models   | **Pydantic v2** — single source of truth for `SchemaIR`, `OKFBundle`, AI tool output, and API bodies |
| AI                    | Anthropic Python SDK (Claude)                                                                        |
| Rate limiting         | `slowapi` (per-client-IP)                                                                            |
| SQL parsing           | `sqlglot`                                                                                            |
| OKF (de)serialization | `PyYAML` + templated Markdown                                                                        |
| Frontend              | Next.js (TypeScript, React)                                                                          |
| Tests                 | `pytest` (backend, TDD), plus a smoke test for the frontend                                          |
| CI/CD                 | GitHub Actions — backend `pytest` + frontend `build` on PRs to `main` (no deploy in CI)              |
| Deploy                | Frontend → Vercel; Backend → Render — each via its own git integration on push to `main`             |
| Config                | `ANTHROPIC_API_KEY` + `OKF_MODEL_ID` via env vars                                                    |

---

## 8. Testing Strategy

Backend follows TDD (red-green-refactor), one test file per module:

- **Ingestion** — DDL parser and dbt-manifest parser produce correct `SchemaIR` for representative inputs, including malformed/partial input (`tests/test_ingest_*.py`).
- **AI module** — the Anthropic call is **mocked**; tests assert prompt assembly, chunking behavior, structured-output parsing, and confidence propagation. One optional live integration test behind a mark for local runs.
- **Validator** — constructing `OKFBundle` from valid data succeeds; each required-field/type/referential violation raises `ValidationError` and is reported; the `@model_validator` cross-field rules and the repair loop are exercised (`tests/test_okf_validate.py`).
- **Serializer** — round-trips a bundle to OKF files and back where feasible; output parses as valid YAML/Markdown.
- **API** — FastAPI `TestClient` covers each endpoint's happy path and failure paths (bad format, empty input, API error), with the AI module mocked.

---

## 9. Non-Functional Notes

- **Security/privacy** — API key server-side only; **stateless: schema and bundle live in memory for the request only, nothing is persisted or logged**. Only schema *metadata* (table/column names + types) is sent to Anthropic — never row data. A UI notice warns users not to paste secrets. No redaction feature in v1 (see PRD §6).
- **Rate limiting** — per-client-IP limits via `slowapi` (`get_remote_address`): `/api/generate` **10/min** (strictest — it spends tokens), `/api/ingest` **30/min**, `/api/download` **30/min**, `/api/validate` **60/min**; `/api/health` is unlimited (deploy/CI probes). `429` responses pass back through the CORS middleware so the browser renders a real "rate limited" error rather than an opaque network failure. The limiter uses an **in-memory store**, which is correct for the single-instance Render deployment; if the backend is ever scaled to multiple instances, point `slowapi` at a shared Redis so limits are global rather than per-instance.
- **Cost/latency** — estimated **<$0.30/bundle, median <60s** for a ~20-table/~200-column schema (guardrail <$0.50); the parsed-preview step lets users abort before spending tokens. Numbers to be confirmed on real inputs (PRD §6).
- **Scale limit** — context window is not the constraint (1 table per call); the cap is practical: **soft limit ~100 tables / ~2,000 columns**, with a warning + "split the schema" suggestion above that.
- **Portability** — the whole point: output is vendor-neutral OKF, downloadable and usable with any agent/MCP server.

---

## 10. Resolved & Open Architecture Questions

**Resolved:**

- **OKF spec version** — validate against **v0.1**, pinned in one constant; bump on each new Google release (§3.3).
- **Model** — `claude-sonnet-4-6` with adaptive thinking, configurable via `OKF_MODEL_ID`; Opus 4.6 as the quality upgrade (§4.1).
- **Streaming** — `/generate` streams partial per-table results over SSE for long schemas (§5, §6).
- **Batching** — **1 table per model call** by default; column-budget batching (~40–50 columns/call, ≤10 tables/call, wide tables solo) is a documented optimization to enable only if wide-schema latency becomes a problem (§4.2).
- **OKF schema source** — the **`OKFBundle` Pydantic model is our machine-readable OKF v0.1 schema**, derived from the published spec text (Google ships prose, not necessarily a JSON Schema). No external schema artifact is required; a known-good bundle fixture guards it against regressions (§3.3, PRD §6).
- **Scale cap** — ~100 tables / ~2,000 columns soft limit; warn + suggest splitting above (§9, PRD §6).
- **Privacy** — stateless, in-memory only, metadata-not-rows to Anthropic (§9, PRD §6).

**Open (to validate / tune):**

- Cost/latency envelope for `claude-sonnet-4-6` — estimated <$0.30/bundle & <60s (§9); confirm on real inputs.
- Concurrency limit for the default 1-table-per-call path (how many parallel Anthropic calls before rate limits or cost pace becomes the constraint).
