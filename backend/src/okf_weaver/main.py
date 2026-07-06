"""FastAPI app: ingest -> generate (SSE) -> validate -> download.

Stateless and in-memory per request. All request/response bodies are the
Pydantic models from `okf_weaver.models`, so FastAPI validates input at the
boundary (422 with field detail) and the same shapes are reused end to end.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from okf_weaver.ai import generate_bundle, make_client
from okf_weaver.ai.generate import DEFAULT_MODEL, usage_summary
from okf_weaver.ingest import detect_format, parse_dbt_manifest, parse_sql_ddl
from okf_weaver.models import (
    GenerateRequest,
    IngestRequest,
    OKFBundle,
    SchemaIR,
    SourceFormat,
    ValidationResult,
)
from okf_weaver.okf import (
    build_bundle,
    bundle_filename,
    bundle_to_files,
    check_against_schema,
    format_validation_error,
    serialize_bundle,
)

app = FastAPI(title="OKF Weaver", version="0.1.0")

# Rate limiting (per client IP). Generation is the strict one — it spends tokens.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # MVP: thin public client; no cookies/credentials
    allow_methods=["*"],
    allow_headers=["*"],
    # Content-Disposition isn't a CORS-safelisted response header, so without
    # this the browser strips it and the frontend can't read the zip filename.
    expose_headers=["Content-Disposition"],
)


def get_client() -> Any:
    """Anthropic client dependency (overridden in tests)."""
    return make_client()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/ingest")
@limiter.limit("30/minute")
def ingest(request: Request, req: IngestRequest) -> SchemaIR:
    """Parse SQL DDL or a dbt manifest into a `SchemaIR` preview (no tokens spent).

    ``format`` is auto-detected from the content when the request omits it.
    """
    fmt = req.format or detect_format(req.content)
    try:
        if fmt is SourceFormat.SQL:
            return parse_sql_ddl(req.content)
        try:
            manifest = json.loads(req.content)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno}). "
                "Paste the full contents of a dbt manifest.json."
            ) from exc
        return parse_dbt_manifest(manifest)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/generate")
@limiter.limit("10/minute")
def generate(
    request: Request, body: GenerateRequest, client: Any = Depends(get_client)
) -> StreamingResponse:
    """Stream token deltas + one validated OKF table per source table (SSE), then the assembled bundle.

    Optional ``body.context`` is threaded into every per-table prompt.
    """
    schema = body.schema_

    def stream() -> Iterator[str]:
        tables = []
        usage: dict[str, int] = {}
        try:
            for kind, name, payload in generate_bundle(
                schema, client=client, context=body.context, usage=usage
            ):
                if kind == "token":
                    yield _sse("token", {"table": name, "delta": payload})
                else:  # "table" — a validated OKFTable
                    tables.append(payload)
                    yield _sse("table", payload.model_dump())
        except Exception as exc:  # surface mid-stream failure to the client
            yield _sse("error", {"message": f"Generation failed: {exc}"})
            return
        # Tables stream in completion order; the bundle keeps the schema order.
        order = [t.name for t in schema.tables]
        tables.sort(key=lambda t: order.index(t.name))
        bundle = OKFBundle(tables=tables)
        yield _sse(
            "done",
            {
                "bundle": bundle.model_dump(),
                "warnings": check_against_schema(bundle, schema),
                "usage": usage_summary(usage, DEFAULT_MODEL),
            },
        )

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/validate")
@limiter.limit("60/minute")
def validate(request: Request, payload: dict[str, Any] = Body(...)) -> ValidationResult:
    """Re-validate a (possibly user-edited) bundle through the OKFBundle gate."""
    try:
        build_bundle(payload)
    except ValidationError as exc:
        return ValidationResult(valid=False, errors=format_validation_error(exc))
    return ValidationResult(valid=True)


@app.post("/api/preview")
@limiter.limit("60/minute")
def preview(request: Request, bundle: OKFBundle) -> dict[str, dict[str, str]]:
    """Return the exact OKF files (`{path: content}`) that download would zip."""
    return {"files": bundle_to_files(bundle)}


@app.post("/api/download")
@limiter.limit("30/minute")
def download(request: Request, bundle: OKFBundle) -> Response:
    """Serialize an approved bundle to an OKF Markdown+YAML `.zip`."""
    return Response(
        content=serialize_bundle(bundle),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={bundle_filename(bundle)}"},
    )


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
