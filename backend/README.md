# OKF Weaver — backend

FastAPI service that turns a warehouse schema (SQL DDL or dbt `manifest.json`) into a validated OKF v0.1 bundle. Pydantic v2 models are the single source of truth and the validation backbone. See [`../docs/spec.md`](../docs/spec.md).

## Develop

```bash
uv sync
export ANTHROPIC_API_KEY=sk-ant-...
uv run uvicorn okf_weaver.main:app --reload   # http://127.0.0.1:8000 (docs at /docs)

uv run pytest                                  # all tests (Anthropic mocked)
uv run pytest tests/test_models.py             # one file
uv run pytest -m live                          # live tests (needs a real key)
```

## Layout

```text
src/okf_weaver/
  models.py        # SchemaIR, OKFBundle + friends (Pydantic)  -- the contract
  ingest/          # sql_ddl.py, dbt_manifest.py  -> SchemaIR
  ai/generate.py   # Claude tool-use generation (streamed)
  okf/validate.py  # OKFBundle construction + cross-field rules
  okf/serialize.py # bundle -> OKF Markdown+YAML .zip
  main.py          # FastAPI app + endpoints
tests/
```
