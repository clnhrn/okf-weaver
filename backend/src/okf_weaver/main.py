"""FastAPI app: ingest -> generate (SSE) -> validate -> download.

Stateless and in-memory per request. All request/response bodies are the
Pydantic models from `okf_weaver.models`, so FastAPI validates input at the
boundary (422 with field detail) and the same shapes are reused end to end.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from okf_weaver import budget
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

logger = logging.getLogger(__name__)

app = FastAPI(title="OKF Weaver", version="0.1.0")

#: Origins allowed to call the API from a browser. Defaults to the deployed
#: frontend plus local dev; override with a comma-separated OKF_ALLOWED_ORIGINS.
_DEFAULT_ORIGINS = "https://okf-weaver.vercel.app,http://localhost:3000,http://127.0.0.1:3000"
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("OKF_ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()
]


def _client_ip(request: Request) -> str:
    """Rate-limit key: the real client IP, not the proxy's.

    Behind Render's edge proxy ``request.client.host`` is the *proxy* for every
    caller, which would collapse all per-IP limits into one shared bucket. The
    trustworthy client IP is the *rightmost* ``X-Forwarded-For`` entry: Render's
    edge is the sole ingress and appends the true socket peer there. Anything to
    its left was supplied by the caller and is forgeable, so keying off the
    leftmost would let an abuser rotate that value to mint a fresh bucket per
    request and slip the limit. Fall back to the socket peer for direct/local
    calls with no forwarding header.

    This assumes exactly one trusted hop (Render's edge). If another trusted
    proxy is ever chained in front, take the Nth-from-right entry instead.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client = forwarded.split(",")[-1].strip()
        if client:
            return client
    return get_remote_address(request)


# Rate limiting (per client IP). Generation is the strict one — it spends tokens.
limiter = Limiter(key_func=_client_ip)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # thin public client; no cookies/credentials
    allow_methods=["GET", "POST"],  # the only verbs the API serves
    allow_headers=["Content-Type"],
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
    except ValidationError as exc:
        # The parser builds a SchemaIR, so exceeding the table/column caps raises
        # here (Pydantic ValidationError is not a ValueError). Surface it cleanly.
        raise HTTPException(status_code=422, detail=format_validation_error(exc)) from exc


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
            # Cost-DoS backstop: refuse before spending tokens if the process-wide
            # spend ceiling for this window is already reached (H1).
            budget.guard.ensure_available()
        except budget.BudgetExceeded as exc:
            logger.warning("generation refused: spend ceiling reached")
            yield _sse("error", {"message": str(exc)})
            return
        try:
            for kind, name, payload in generate_bundle(
                schema, client=client, context=body.context, usage=usage
            ):
                if kind == "token":
                    yield _sse("token", {"table": name, "delta": payload})
                else:  # "table" — a validated OKFTable
                    tables.append(payload)
                    yield _sse("table", payload.model_dump())
        except Exception:  # surface mid-stream failure to the client
            # Log the full exception server-side; send the client only a generic
            # message plus a correlation id (raw text can leak API/validation
            # internals). The id ties a user report back to the server log.
            error_id = uuid.uuid4().hex[:12]
            logger.exception("generate failed (error_id=%s)", error_id)
            # A partial run still spent tokens; debit what completed before failing.
            budget.guard.record(usage_summary(usage, DEFAULT_MODEL)["estimated_cost_usd"])
            yield _sse(
                "error",
                {"message": "Generation failed. Please try again.", "error_id": error_id},
            )
            return
        # Tables stream in completion order; the bundle keeps the schema order.
        order = [t.name for t in schema.tables]
        tables.sort(key=lambda t: order.index(t.name))
        bundle = OKFBundle(tables=tables)
        # Token/cost usage is tracked in backend logs only, never sent to the client.
        summary = usage_summary(usage, DEFAULT_MODEL)
        logger.info("generate usage: %s", summary)
        # Debit the window's spend ceiling by this run's estimated cost (H1).
        budget.guard.record(summary["estimated_cost_usd"])
        yield _sse(
            "done",
            {
                "bundle": bundle.model_dump(),
                "warnings": check_against_schema(bundle, schema),
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
