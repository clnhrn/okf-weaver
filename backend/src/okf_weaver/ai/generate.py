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
from collections.abc import Iterator
from typing import Any, Protocol

from pydantic import ValidationError

from okf_weaver.models import OKFTable, SchemaIR, Table

DEFAULT_MODEL = os.getenv("OKF_MODEL_ID", "claude-sonnet-4-6")
_TOOL_NAME = "emit_okf_table"
_MAX_ATTEMPTS = 2  # initial call + one repair pass

SYSTEM_PROMPT = (
    "You are a data documentation specialist producing Open Knowledge Format "
    "(OKF) v0.1 context for a data warehouse. For the given table, write a clear "
    "business description and a definition for every column.\n"
    "Rules:\n"
    "- Do NOT invent columns or tables. Describe only what you are given.\n"
    "- If a definition is uncertain, say so plainly and lower its confidence.\n"
    "- Prefer any existing description provided over guessing.\n"
    f"- Emit exactly one call to the {_TOOL_NAME} tool; do not reply with prose."
)


class _MessagesClient(Protocol):  # minimal shape we depend on (real or fake)
    messages: Any


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


def generate_table(table: Table, *, client: _MessagesClient, model_id: str = DEFAULT_MODEL) -> OKFTable:
    """Generate one validated `OKFTable` for a source table.

    Raises:
        ValueError: If the model does not call the tool.
        pydantic.ValidationError: If output is still invalid after the repair pass.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": _render_prompt(table)}]
    last_error: ValidationError | None = None

    for _ in range(_MAX_ATTEMPTS):
        response = client.messages.create(
            model=model_id,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=[_tool_definition()],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=messages,
        )
        tool_input = _extract_tool_input(response)
        tool_input["name"] = table.name  # source schema is authoritative for the name
        try:
            return OKFTable.model_validate(tool_input)
        except ValidationError as exc:
            last_error = exc
            messages.append({"role": "user", "content": _repair_prompt(exc)})

    assert last_error is not None
    raise last_error


def generate_bundle(
    schema: SchemaIR, *, client: _MessagesClient, model_id: str = DEFAULT_MODEL
) -> Iterator[OKFTable]:
    """Yield an `OKFTable` per source table (one model call each), in order."""
    for table in schema.tables:
        yield generate_table(table, client=client, model_id=model_id)


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
