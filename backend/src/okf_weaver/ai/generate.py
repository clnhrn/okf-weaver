"""Core AI feature: generate curated OKF context from a schema via Claude.

Strategy (spec §4): one table per model call, constrained by a single
`emit_okf_table` tool whose input schema is generated from the `OKFTable`
Pydantic model. The tool call is parsed with `OKFTable.model_validate(...)`;
a malformed response triggers one bounded repair pass. `generate_bundle`
yields tables as they complete so the API can stream them (SSE).
"""

from __future__ import annotations

import json
import os
import queue
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from pydantic import ValidationError

from okf_weaver.models import OKFTable, SchemaIR, Table

DEFAULT_MODEL = os.getenv("OKF_MODEL_ID", "claude-sonnet-4-6")
#: Max concurrent per-table Claude calls. Bounded to respect rate limits and
#: cost pacing; tables still stream as each completes.
MAX_CONCURRENCY = max(1, int(os.getenv("OKF_MAX_CONCURRENCY", "5")))
_TOOL_NAME = "emit_okf_table"
_MAX_ATTEMPTS = 2  # initial call + one repair pass
_WORKER_DONE = object()  # one per worker; counts completion on the consumer thread
_usage_lock = threading.Lock()  # generate_bundle runs tables concurrently

#: USD per million tokens (input, output) for cost estimation.
_PRICING = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-6": (5.0, 25.0),
}
_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)

SYSTEM_PROMPT = (
    "You are a data documentation specialist producing Open Knowledge Format "
    "(OKF) v0.1 context for a relational database. For the given table, write a clear "
    "business description and a definition for every column.\n"
    "Rules:\n"
    "- Do NOT invent columns or tables. Describe only what you are given.\n"
    "- If a definition is uncertain, say so plainly and lower its confidence.\n"
    "- Prefer any existing description provided over guessing.\n"
    "- You only write descriptions, definitions, confidence, and the "
    "source-of-truth flag; column data types and keys are already known.\n"
    f"- Emit exactly one call to the {_TOOL_NAME} tool; do not reply with prose."
)


class _MessagesClient(Protocol):  # minimal shape we depend on (real or fake)
    messages: Any


def _system_prompt(context: str | None) -> str:
    """Base rules, with the user's domain/glossary context appended when given."""
    if context and context.strip():
        return (
            f"{SYSTEM_PROMPT}\n\n"
            "## Business context (authoritative — prefer it over guessing)\n"
            f"{context.strip()}"
        )
    return SYSTEM_PROMPT


def make_client() -> Any:
    """Construct the real Anthropic client (reads ANTHROPIC_API_KEY from env)."""
    import anthropic

    return anthropic.Anthropic()


def _tool_definition() -> dict[str, Any]:
    return {
        "name": _TOOL_NAME,
        "description": "Emit the OKF definition for a single table.",
        "input_schema": OKFTable.model_json_schema(),
    }


def _stream_call(client: _MessagesClient, on_delta: Callable[[str], None] | None, **kwargs: Any) -> Any:
    """Run one streaming Claude call, forwarding tool-call JSON deltas.

    Args:
        on_delta: Called with each `input_json_delta` chunk (partial tool JSON)
            as it streams; ignored for any other event type (e.g. thinking).

    Returns:
        The final assembled message (same `.content`/`.usage` shape as a
        non-streaming `messages.create` response).
    """
    with client.messages.stream(**kwargs) as stream:
        for event in stream:
            if (
                on_delta is not None
                and getattr(event, "type", None) == "content_block_delta"
                and getattr(event.delta, "type", None) == "input_json_delta"
            ):
                on_delta(event.delta.partial_json)
        return stream.get_final_message()


def generate_table(
    table: Table,
    *,
    client: _MessagesClient,
    model_id: str = DEFAULT_MODEL,
    context: str | None = None,
    usage: dict[str, int] | None = None,
    on_delta: Callable[[str], None] | None = None,
) -> OKFTable:
    """Generate one validated `OKFTable` for a source table.

    Args:
        context: Optional free-text domain/glossary notes that steer meaning.
        usage: Optional mutable accumulator; token counts are summed into it.
        on_delta: Optional callback invoked with each partial tool-call JSON
            chunk as the model streams, for live UI display.

    Raises:
        ValueError: If the model does not call the tool.
        pydantic.ValidationError: If output is still invalid after the repair pass.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": _render_prompt(table)}]
    last_error: ValidationError | None = None

    for _ in range(_MAX_ATTEMPTS):
        response = _stream_call(
            client,
            on_delta,
            model=model_id,
            max_tokens=4096,
            # Cache the tools + system prefix (identical across the per-table
            # calls in a request) so calls 2..N read it at ~0.1x input cost.
            system=[
                {
                    "type": "text",
                    "text": _system_prompt(context),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[_tool_definition()],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=messages,
        )
        _accumulate(usage, response)
        tool_input = _extract_tool_input(response)
        tool_input["name"] = table.name  # source schema is authoritative for the name
        try:
            okf_table = OKFTable.model_validate(tool_input)
        except ValidationError as exc:
            last_error = exc
            messages.append({"role": "user", "content": _repair_prompt(exc)})
            continue
        return _attach_schema_facts(okf_table, table)

    assert last_error is not None
    raise last_error


def _attach_schema_facts(okf_table: OKFTable, source: Table) -> OKFTable:
    """Overwrite each column's type/PK/nullability with the ingested facts.

    The model supplies definition + confidence; the structural facts come from
    ingestion so they are authoritative and never hallucinated.
    """
    by_name = {c.name: c for c in source.columns}
    columns = [
        col.model_copy(
            update={
                "data_type": by_name[col.name].data_type,
                "is_primary_key": by_name[col.name].is_primary_key,
                "nullable": by_name[col.name].nullable,
                "references": by_name[col.name].references,
            }
        )
        if col.name in by_name
        else col
        for col in okf_table.columns
    ]
    return okf_table.model_copy(update={"columns": columns})


def generate_bundle(
    schema: SchemaIR,
    *,
    client: _MessagesClient,
    model_id: str = DEFAULT_MODEL,
    context: str | None = None,
    usage: dict[str, int] | None = None,
) -> Iterator[tuple[str, str, Any]]:
    """Yield tagged streaming events for every source table.

    Runs up to `MAX_CONCURRENCY` per-table calls in parallel. Each worker
    pushes onto a shared queue, which this generator drains on the consuming
    thread, so token deltas from concurrent tables interleave without blocking:

    - `("token", table_name, delta)` — partial tool-call JSON as it streams
    - `("table", table_name, okf_table)` — once the table validates

    A table that fails generation re-raises its exception here.
    """
    tables = schema.tables
    if not tables:
        return
    events: queue.Queue[Any] = queue.Queue()

    def run(table: Table) -> None:
        try:
            okf = generate_table(
                table,
                client=client,
                model_id=model_id,
                context=context,
                usage=usage,
                on_delta=lambda delta, name=table.name: events.put(("token", name, delta)),
            )
            events.put(("table", table.name, okf))
        except Exception as exc:  # surfaced on the consuming thread below
            events.put(("error", table.name, exc))
        finally:
            events.put(_WORKER_DONE)

    workers = min(MAX_CONCURRENCY, len(tables))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for table in tables:
            pool.submit(run, table)
        remaining = len(tables)
        while remaining:
            item = events.get()
            if item is _WORKER_DONE:
                remaining -= 1
                continue
            kind, name, payload = item
            if kind == "error":
                raise payload
            yield kind, name, payload


def _accumulate(usage: dict[str, int] | None, response: Any) -> None:
    if usage is None:
        return
    u = getattr(response, "usage", None)
    if u is None:
        return
    with _usage_lock:  # worker threads accumulate into the shared dict
        for field in _USAGE_FIELDS:
            usage[field] = usage.get(field, 0) + (getattr(u, field, 0) or 0)


def usage_summary(usage: dict[str, int], model_id: str = DEFAULT_MODEL) -> dict[str, Any]:
    """Tokens + an estimated USD cost for a generate run."""
    in_rate, out_rate = _PRICING.get(model_id, _PRICING["claude-sonnet-4-6"])
    cost = (
        usage.get("input_tokens", 0) * in_rate
        + usage.get("output_tokens", 0) * out_rate
        + usage.get("cache_read_input_tokens", 0) * in_rate * 0.1
        + usage.get("cache_creation_input_tokens", 0) * in_rate * 1.25
    ) / 1_000_000
    return {
        **{field: usage.get(field, 0) for field in _USAGE_FIELDS},
        "estimated_cost_usd": round(cost, 4),
        "model": model_id,
    }


def _extract_tool_input(response: Any) -> dict[str, Any]:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input)
    raise ValueError(f"model did not call the {_TOOL_NAME} tool")


def _render_prompt(table: Table) -> str:
    cols = [
        {
            "name": c.name,
            "data_type": c.data_type,
            "nullable": c.nullable,
            "is_primary_key": c.is_primary_key,
            "references": c.references,
            "existing_description": c.description,
        }
        for c in table.columns
    ]
    payload = {
        "table": table.name,
        "existing_description": table.description,
        "columns": cols,
    }
    return (
        "Generate OKF context for this table. Only these columns exist:\n"
        f"{json.dumps(payload, indent=2)}"
    )


def _repair_prompt(exc: ValidationError) -> str:
    problems = "\n".join(
        f"- {'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
        for e in exc.errors()
    )
    return (
        "Your previous tool call was invalid. Fix these problems and call "
        f"{_TOOL_NAME} again:\n{problems}"
    )
