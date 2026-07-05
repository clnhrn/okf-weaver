# Token-Level Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the model's output *as it is generated* per table (live-typing description + column definitions), instead of only when each table finishes.

**Architecture:** Each per-table call switches from `messages.create` to `messages.stream`; the streamed `input_json_delta` chunks (partial tool-call JSON) are re-emitted as `token` SSE events tagged with the table name. `generate_bundle` becomes a thread-safe queue fan-in that yields tagged `("token"|"table", name, payload)` events so token deltas from up to `OKF_MAX_CONCURRENCY` concurrent tables interleave without blocking. The frontend accumulates deltas per table, runs a tolerant partial-JSON parser, and renders each table's card filling in live; the validated `OKFTable` replaces the preview when its `table` event lands. The Pydantic validation gate is unchanged — partial JSON is display-only.

**Tech Stack:** FastAPI + SSE, Anthropic Python SDK (`messages.stream`), `concurrent.futures` + `queue.Queue`, Pydantic v2 (backend); Next.js + React, Vitest (frontend).

## Global Constraints

- **Model surface:** `claude-sonnet-4-6` (default, `OKF_MODEL_ID` override). 4.6 request surface only — adaptive thinking, **no `budget_tokens`, no assistant prefill**. Streaming loop must ignore any non-`input_json_delta` events (e.g. thinking deltas).
- **Constrained output stays tool-use:** single forced `emit_okf_table` tool; parse with `OKFTable.model_validate(...)`. Do **not** switch to `output_config.format`.
- **Validation gate is unchanged and authoritative:** only a completed, validated `OKFTable` is ever appended to the bundle, reviewed, or exported. Partial JSON is display-only.
- **Concurrency preserved:** default 5 (`OKF_MAX_CONCURRENCY`); token deltas routed to their own card by table name.
- **TDD:** red-green-refactor, one test file per module. Mock the Anthropic client in unit tests.
- **Backend package manager is `uv`** — never bare `pip`/`uv pip`. Run tests with `uv run pytest` from `backend/`.
- **Commits:** Conventional Commits style. No `Co-Authored-By`/"Generated with" footer.
- Keep modules under ~500–600 lines.

---

## File Structure

**Backend**
- Modify `backend/src/okf_weaver/ai/generate.py` — add `_stream_call`; add `on_delta` param to `generate_table`; rewrite `generate_bundle` as a queue fan-in yielding tagged events.
- Modify `backend/src/okf_weaver/main.py` — map tagged events from `generate_bundle` to `token`/`table`/`done` SSE events.
- Modify `backend/tests/test_ai.py` — `FakeClient` gains a `messages.stream` context manager; new streaming tests; update the bundle test to the tagged-event shape.
- Modify `backend/tests/test_api.py` — `FakeClient` gains `messages.stream`; update the stream-events test and add a `token`-event assertion.

**Frontend**
- Create `frontend/app/partialJson.ts` — tolerant partial-JSON parser (`parsePartial`).
- Create `frontend/app/partialJson.test.ts` — Vitest unit tests for the parser.
- Modify `frontend/package.json` — add `vitest` devDependency + `test` script.
- Modify `frontend/app/page.tsx` — accumulate `token` deltas into `partials` state; clear on `table`; pass `partials` to `BundleTree`.
- Modify `frontend/app/BundleTree.tsx` — render live preview in the pending cards from parsed partials.
- Modify `frontend/app/globals.css` — minimal `.streaming` style for the live-typing text.

---

## Task 1: Backend — token streaming in the per-table call

**Files:**
- Modify: `backend/src/okf_weaver/ai/generate.py`
- Test: `backend/tests/test_ai.py`

**Interfaces:**
- Consumes: `OKFTable`, `Table` (unchanged models).
- Produces:
  - `generate_table(table, *, client, model_id=DEFAULT_MODEL, context=None, usage=None, on_delta: Callable[[str], None] | None = None) -> OKFTable` — now streams; when `on_delta` is given it is called with each partial-JSON chunk string.
  - `_stream_call(client, on_delta, **kwargs) -> Any` — runs `client.messages.stream(**kwargs)`, forwards `input_json_delta` chunks to `on_delta`, returns the final message (same `.content` / `.usage` shape as before).

- [ ] **Step 1: Update the test `FakeClient` to a streaming shape**

Replace the `FakeClient` class in `backend/tests/test_ai.py` (currently exposing `messages.create`) with a streaming version. Keep `_tool_use`, `TABLE`, `GOOD_PAYLOAD` as they are.

```python
import json
from types import SimpleNamespace


def _tool_use(payload):
    return SimpleNamespace(type="tool_use", input=payload)


class _FakeStream:
    """Context-manager stand-in for anthropic's MessageStreamManager."""

    def __init__(self, content, usage):
        self._content = content
        self._usage = usage

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        # Emit each tool_use block's JSON as two input_json_delta chunks so
        # tests exercise partial accumulation.
        for block in self._content:
            if getattr(block, "type", None) == "tool_use":
                text = json.dumps(block.input)
                mid = max(1, len(text) // 2)
                for part in (text[:mid], text[mid:]):
                    yield SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(type="input_json_delta", partial_json=part),
                    )

    def get_final_message(self):
        return SimpleNamespace(content=self._content, usage=self._usage)


class FakeClient:
    """Stand-in for anthropic.Anthropic; returns queued streaming responses."""

    def __init__(self, *responses, usage_per_call=None):
        self._responses = list(responses)
        self.calls = 0
        self.last_kwargs = None
        self._usage = usage_per_call
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        content = self._responses.pop(0)
        usage = SimpleNamespace(**self._usage) if self._usage else None
        return _FakeStream(content, usage)
```

- [ ] **Step 2: Add the failing streaming test**

Append to `backend/tests/test_ai.py`:

```python
def test_generate_table_streams_token_deltas_to_callback():
    client = FakeClient([_tool_use(GOOD_PAYLOAD)])
    chunks: list[str] = []
    generate_table(TABLE, client=client, model_id="m", on_delta=chunks.append)
    assert chunks, "expected at least one partial-JSON delta"
    reassembled = json.loads("".join(chunks))
    assert reassembled["description"] == "One row per order."
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_ai.py::test_generate_table_streams_token_deltas_to_callback -q`
Expected: FAIL — `generate_table()` got an unexpected keyword argument `on_delta` (and/or `FakeClient` has no `messages.create`).

- [ ] **Step 4: Implement `_stream_call` and thread `on_delta` through `generate_table`**

In `backend/src/okf_weaver/ai/generate.py`, add the import and helper, and rewrite the call site inside `generate_table`.

Add to the imports near the top:

```python
from collections.abc import Callable, Iterator
```

(There is already `from collections.abc import Iterator`; replace that line with the one above so `Callable` is available.)

Add this helper (place it just above `generate_table`):

```python
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
```

Change the `generate_table` signature to add the parameter:

```python
def generate_table(
    table: Table,
    *,
    client: _MessagesClient,
    model_id: str = DEFAULT_MODEL,
    context: str | None = None,
    usage: dict[str, int] | None = None,
    on_delta: Callable[[str], None] | None = None,
) -> OKFTable:
```

And add to its docstring `Args:` block:

```
        on_delta: Optional callback invoked with each partial tool-call JSON
            chunk as the model streams, for live UI display.
```

Inside the `for _ in range(_MAX_ATTEMPTS):` loop, replace the `response = client.messages.create(...)` call with `_stream_call`:

```python
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
```

Everything after (`_accumulate`, `_extract_tool_input`, validation, repair) is unchanged.

- [ ] **Step 5: Run the new test plus the full `test_ai.py` to verify green**

Run: `cd backend && uv run pytest tests/test_ai.py -q`
Expected: PASS — the new streaming test passes and all pre-existing `generate_table` tests (context threading, cache-control, repair count, name-forcing, skip-tool ValueError, usage accumulation) still pass on the streaming `FakeClient`.

- [ ] **Step 6: Commit**

```bash
git add backend/src/okf_weaver/ai/generate.py backend/tests/test_ai.py
git commit -m "feat(ai): stream per-table tool-call JSON via messages.stream"
```

---

## Task 2: Backend — `generate_bundle` queue fan-in with tagged events

**Files:**
- Modify: `backend/src/okf_weaver/ai/generate.py`
- Test: `backend/tests/test_ai.py`

**Interfaces:**
- Consumes: `generate_table(..., on_delta=...)` from Task 1.
- Produces: `generate_bundle(schema, *, client, model_id=DEFAULT_MODEL, context=None, usage=None) -> Iterator[tuple[str, str, Any]]` — yields tagged events:
  - `("token", table_name: str, delta: str)` as chunks stream
  - `("table", table_name: str, okf_table: OKFTable)` when a table validates
  - worker exceptions are re-raised on the consuming thread.

- [ ] **Step 1: Update the existing bundle test to the tagged-event shape**

In `backend/tests/test_ai.py`, replace `test_generate_bundle_streams_one_table_per_input_and_assembles` with:

```python
def test_generate_bundle_streams_one_table_per_input_and_assembles():
    schema = SchemaIR(
        source_format=SourceFormat.SQL,
        tables=[TABLE, Table(name="customers", columns=[Column(name="id", data_type="int")])],
    )
    client = FakeClient(
        [_tool_use(GOOD_PAYLOAD)],
        [_tool_use({**GOOD_PAYLOAD, "name": "customers"})],
    )
    events = list(generate_bundle(schema, client=client, model_id="test-model"))
    tables = [payload for kind, _, payload in events if kind == "table"]
    # Runs concurrently -> completion order is not guaranteed; both must appear.
    assert {t.name for t in tables} == {"orders", "customers"}
    bundle = OKFBundle(tables=tables)
    assert {t.name for t in bundle.tables} == {"orders", "customers"}
```

- [ ] **Step 2: Add a failing test for token-before-table ordering**

Append to `backend/tests/test_ai.py`:

```python
def test_generate_bundle_emits_token_events_before_each_table():
    schema = SchemaIR(source_format=SourceFormat.SQL, tables=[TABLE])
    client = FakeClient([_tool_use(GOOD_PAYLOAD)])
    events = list(generate_bundle(schema, client=client, model_id="m"))
    kinds = [kind for kind, _, _ in events]
    assert "token" in kinds
    assert kinds.index("token") < kinds.index("table")
    # Token events are tagged with the table name.
    token_names = {name for kind, name, _ in events if kind == "token"}
    assert token_names == {"orders"}
```

- [ ] **Step 3: Run both to verify they fail**

Run: `cd backend && uv run pytest tests/test_ai.py -k "generate_bundle" -q`
Expected: FAIL — current `generate_bundle` yields bare `OKFTable` objects, so `kind, _, payload` unpacking and `kinds.index("token")` both fail.

- [ ] **Step 4: Rewrite `generate_bundle` as a queue fan-in**

In `backend/src/okf_weaver/ai/generate.py`, add `import queue` near the top imports (with `json`, `os`, `threading`). Add a module-level sentinel just under the existing constants:

```python
_WORKER_DONE = object()  # one per worker; counts completion on the consumer thread
```

Replace the entire `generate_bundle` function body with:

```python
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
```

Remove the now-unused `as_completed` import (change `from concurrent.futures import ThreadPoolExecutor, as_completed` to `from concurrent.futures import ThreadPoolExecutor`).

- [ ] **Step 5: Run to verify green**

Run: `cd backend && uv run pytest tests/test_ai.py -q`
Expected: PASS — all `test_ai.py` tests, including the two updated/added bundle tests.

- [ ] **Step 6: Commit**

```bash
git add backend/src/okf_weaver/ai/generate.py backend/tests/test_ai.py
git commit -m "feat(ai): fan-in per-table streams into tagged token/table events"
```

---

## Task 3: Backend API — map tagged events to `token`/`table`/`done` SSE

**Files:**
- Modify: `backend/src/okf_weaver/main.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `generate_bundle(...) -> Iterator[tuple[str, str, Any]]` from Task 2.
- Produces: `/api/generate` SSE stream — `token` events (`{"table": str, "delta": str}`), a `table` event per validated table (`OKFTable` dump, unchanged), then a final `done` event (unchanged: `{bundle, warnings, usage}`).

- [ ] **Step 1: Update the API `FakeClient` to the streaming shape**

In `backend/tests/test_api.py`, replace the `FakeClient` class (currently exposing `messages.create`) with a streaming version, and keep the `_tool_use` helper at the bottom of the file as-is (it returns `[SimpleNamespace(type="tool_use", input=payload)]`). Add `import json` is already present.

```python
class _FakeStream:
    def __init__(self, content):
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for block in self._content:
            if getattr(block, "type", None) == "tool_use":
                text = json.dumps(block.input)
                mid = max(1, len(text) // 2)
                for part in (text[:mid], text[mid:]):
                    yield SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(type="input_json_delta", partial_json=part),
                    )

    def get_final_message(self):
        return SimpleNamespace(content=self._content, usage=None)


class FakeClient:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        return _FakeStream(self._responses.pop(0))
```

- [ ] **Step 2: Update the stream test to expect token events, and assert token shape**

Replace `test_generate_streams_table_and_done_events` in `backend/tests/test_api.py` with:

```python
def test_generate_streams_token_table_and_done_events(client):
    app.dependency_overrides[get_client] = lambda: FakeClient(_tool_use(OKF_TABLE_PAYLOAD))
    try:
        schema = {
            "source_format": "sql",
            "tables": [{"name": "orders", "columns": [{"name": "id", "data_type": "int"}]}],
        }
        resp = client.post("/api/generate", json={"schema": schema, "context": "B2C shop."})
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        kinds = [e for e, _ in events]
        # token(s) stream first, then the validated table, then done.
        assert "token" in kinds
        assert kinds.index("token") < kinds.index("table") < kinds.index("done")
        first_token = next(d for e, d in events if e == "token")
        assert first_token["table"] == "orders"
        assert isinstance(first_token["delta"], str)
        assert events[-1][0] == "done"
        assert events[-1][1]["bundle"]["tables"][0]["name"] == "orders"
        assert "estimated_cost_usd" in events[-1][1]["usage"]
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd /Users/celine/Documents/AIM/postgraduate_certificate/week-4/okf-weaver && cd backend && uv run pytest tests/test_api.py::test_generate_streams_token_table_and_done_events -q`
Expected: FAIL — the current `/api/generate` iterates `OKFTable` objects from `generate_bundle`, so unpacking `kind, name, payload` in `main.py` raises (no `token` events are emitted).

- [ ] **Step 4: Map tagged events in the `/api/generate` stream generator**

In `backend/src/okf_weaver/main.py`, replace the body of the inner `stream()` generator (inside `generate(...)`) with:

```python
    def stream() -> Iterator[str]:
        tables = []
        usage: dict[str, int] = {}
        for kind, name, payload in generate_bundle(
            schema, client=client, context=body.context, usage=usage
        ):
            if kind == "token":
                yield _sse("token", {"table": name, "delta": payload})
            else:  # "table" — a validated OKFTable
                tables.append(payload)
                yield _sse("table", payload.model_dump())
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
```

Update the `generate` docstring first line to: `"""Stream token deltas + one validated OKF table per source table (SSE), then the assembled bundle."""`

- [ ] **Step 5: Run the API suite to verify green**

Run: `cd backend && uv run pytest tests/test_api.py -q`
Expected: PASS — the new token/table/done test passes and the other endpoint tests (validate, preview, download, ingest, rate limits) are unaffected.

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS — entire backend suite green.

- [ ] **Step 7: Commit**

```bash
git add backend/src/okf_weaver/main.py backend/tests/test_api.py
git commit -m "feat(api): emit token SSE events alongside per-table results"
```

---

## Task 4: Frontend — Vitest setup + tolerant partial-JSON parser

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/app/partialJson.ts`
- Create: `frontend/app/partialJson.test.ts`

**Interfaces:**
- Produces:
  - `type PartialTable = { description?: string; columns: { name?: string; definition?: string }[] }`
  - `parsePartial(raw: string): PartialTable | null` — best-effort parse of an accumulating partial-JSON `OKFTable`; returns `null` when the current fragment can't be safely completed (caller keeps its last good value).

- [ ] **Step 1: Add Vitest tooling to `package.json`**

In `frontend/package.json`, add a `test` script and the `vitest` devDependency:

```json
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "test": "vitest run"
  },
```

Add to `devDependencies` (keep the existing entries):

```json
    "vitest": "^2.1.0"
```

Then install:

Run: `cd frontend && npm install`
Expected: `vitest` added; `node_modules/.bin/vitest` exists.

- [ ] **Step 2: Write the failing parser tests**

Create `frontend/app/partialJson.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { parsePartial } from "./partialJson";

describe("parsePartial", () => {
  it("parses a complete OKFTable payload", () => {
    const full = JSON.stringify({
      name: "orders",
      description: "One row per order.",
      confidence: 0.9,
      columns: [{ name: "id", definition: "Order key.", confidence: 0.9 }],
    });
    const r = parsePartial(full)!;
    expect(r.description).toBe("One row per order.");
    expect(r.columns[0]).toEqual({ name: "id", definition: "Order key." });
  });

  it("recovers a description value truncated mid-string", () => {
    const r = parsePartial('{"name":"orders","description":"One row per ord')!;
    expect(r.description).toBe("One row per ord");
  });

  it("recovers a partial column definition", () => {
    const raw =
      '{"description":"x","columns":[{"name":"id","definition":"The order ke';
    const r = parsePartial(raw)!;
    expect(r.columns[0].name).toBe("id");
    expect(r.columns[0].definition).toBe("The order ke");
  });

  it("strips a trailing comma before closing", () => {
    const r = parsePartial('{"description":"x","confidence":0.9,')!;
    expect(r.description).toBe("x");
  });

  it("handles escaped quotes inside a streaming string", () => {
    const r = parsePartial('{"description":"a \\"quoted\\" word')!;
    expect(r.description).toBe('a "quoted" word');
  });

  it("returns null before the first opening brace", () => {
    expect(parsePartial("")).toBeNull();
    expect(parsePartial("   ")).toBeNull();
  });

  it("ignores non-string field values gracefully", () => {
    const r = parsePartial('{"description":123,"columns":[')!;
    expect(r.description).toBeUndefined();
    expect(r.columns).toEqual([]);
  });
});
```

- [ ] **Step 3: Run to verify the tests fail**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './partialJson'`.

- [ ] **Step 4: Implement the parser**

Create `frontend/app/partialJson.ts`:

```ts
// Tolerant parser for the partial tool-call JSON that streams from /api/generate.
// The model emits an OKFTable object incrementally; this closes the truncated
// fragment (finishes an open string, drops a dangling backslash/comma, balances
// brackets) and extracts the fields we render live. It is best-effort: when a
// fragment cannot be safely completed it returns null and the caller keeps the
// last good value, so the next delta simply fixes it.

export type PartialTable = {
  description?: string;
  columns: { name?: string; definition?: string }[];
};

export function parsePartial(raw: string): PartialTable | null {
  const completed = closeJson(raw);
  if (completed === null) return null;
  let obj: unknown;
  try {
    obj = JSON.parse(completed);
  } catch {
    return null;
  }
  if (typeof obj !== "object" || obj === null) return null;
  const o = obj as Record<string, unknown>;
  const rawCols = Array.isArray(o.columns) ? o.columns : [];
  return {
    description: typeof o.description === "string" ? o.description : undefined,
    columns: rawCols.map((c) => {
      const cc = (c ?? {}) as Record<string, unknown>;
      return {
        name: typeof cc.name === "string" ? cc.name : undefined,
        definition: typeof cc.definition === "string" ? cc.definition : undefined,
      };
    }),
  };
}

function closeJson(raw: string): string | null {
  const start = raw.indexOf("{");
  if (start === -1) return null;
  const s = raw.slice(start);

  const closers: string[] = [];
  let inStr = false;
  let escaped = false;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (inStr) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') inStr = true;
    else if (ch === "{") closers.push("}");
    else if (ch === "[") closers.push("]");
    else if (ch === "}" || ch === "]") closers.pop();
  }

  let out = s;
  if (inStr) {
    if (escaped) out = out.slice(0, -1); // drop a dangling backslash
    out += '"';
  } else {
    out = out.replace(/\s+$/, "");
    if (out.endsWith(",")) out = out.slice(0, -1);
  }
  for (let i = closers.length - 1; i >= 0; i--) out += closers[i];
  return out;
}
```

- [ ] **Step 5: Run to verify green**

Run: `cd frontend && npm test`
Expected: PASS — all `partialJson.test.ts` cases pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/app/partialJson.ts frontend/app/partialJson.test.ts
git commit -m "feat(web): add tolerant partial-JSON parser for streamed tables"
```

---

## Task 5: Frontend — wire `token` events into live table cards

**Files:**
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/app/BundleTree.tsx`
- Modify: `frontend/app/globals.css`

**Interfaces:**
- Consumes: `parsePartial` / `PartialTable` from Task 4; `token` SSE events (`{table, delta}`) from Task 3.
- Produces: `BundleTree` accepts a new prop `partials: Record<string, string>` (raw accumulated delta text keyed by table name) and renders live previews for pending tables.

- [ ] **Step 1: Add `partials` state and reset it on generate**

In `frontend/app/page.tsx`, add the state declaration next to the other `useState` hooks (after the `tables` state on line 30):

```tsx
  const [partials, setPartials] = useState<Record<string, string>>({});
```

Inside `generate()`, add a reset alongside the other resets (near `setTables([]);`):

```tsx
    setPartials({});
```

- [ ] **Step 2: Handle `token` events and clear on `table`**

In `frontend/app/page.tsx`, inside the `readSSE(gen.body, (event, data) => { ... })` callback, add a `token` branch and clear the partial when the validated table lands. Replace the existing `if (event === "table") { ... }` block with:

```tsx
        if (event === "token") {
          const { table, delta } = data as { table: string; delta: string };
          setPartials((prev) => ({ ...prev, [table]: (prev[table] ?? "") + delta }));
        }
        if (event === "table") {
          const t = data as OKFTable;
          setPartials((prev) => {
            const next = { ...prev };
            delete next[t.name];
            return next;
          });
          setTables((prev) =>
            [...prev, t].sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name)),
          );
        }
```

- [ ] **Step 3: Pass `partials` to `BundleTree`**

In `frontend/app/page.tsx`, update the `<BundleTree ... />` usage (around line 308) to pass the new prop:

```tsx
                <BundleTree
                  tables={tables}
                  pending={busy ? pending : []}
                  partials={partials}
                  onTable={editTable}
                  onColumn={editColumn}
                />
```

- [ ] **Step 4: Render the live preview in `BundleTree` pending cards**

In `frontend/app/BundleTree.tsx`, add the import at the top:

```tsx
import { parsePartial } from "./partialJson";
```

Add `partials` to the prop type and destructure it:

```tsx
export default function BundleTree({
  tables,
  pending,
  partials,
  onTable,
  onColumn,
}: {
  tables: OKFTable[];
  pending: string[]; // names still being generated (skeleton rows)
  partials: Record<string, string>; // raw streamed JSON per pending table
  onTable: (ti: number, patch: Partial<OKFTable>) => void;
  onColumn: (ti: number, ci: number, patch: Partial<OKFColumn>) => void;
}) {
```

Replace the existing `{pending.map((name) => ( ... ))}` block at the bottom with:

```tsx
      {pending.map((name) => {
        const preview = parsePartial(partials[name] ?? "");
        const cols = preview?.columns.filter((c) => c.name || c.definition) ?? [];
        const hasContent = Boolean(preview?.description) || cols.length > 0;
        return (
          <section className="node skeleton" key={name}>
            <header className="node-head">
              <span className="chev">▸</span>
              <span className="mono tname">{name}</span>
              <span className="chip pending">generating…</span>
            </header>
            {hasContent ? (
              <div className="node-body">
                {preview?.description && (
                  <p className="mono desc streaming">{preview.description}</p>
                )}
                <div className="cols">
                  {cols.map((c, ci) => (
                    <div className="crow" key={c.name ?? ci}>
                      <span className="cidx mono">{String(ci + 1).padStart(2, "0")}</span>
                      <div className="cbody">
                        <div className="cmeta">
                          <span className="mono cname">{c.name ?? "…"}</span>
                        </div>
                        <p className="mono cdef streaming">{c.definition ?? ""}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="skeleton-rows">
                <span />
                <span />
                <span />
              </div>
            )}
          </section>
        );
      })}
```

- [ ] **Step 5: Add a minimal `.streaming` style**

Append to `frontend/app/globals.css`:

```css
/* Live-typing preview text while a table streams (display-only, pre-validation). */
.streaming {
  opacity: 0.85;
  white-space: pre-wrap;
}
.streaming::after {
  content: "▍";
  opacity: 0.5;
  animation: blink 1s steps(1) infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
```

- [ ] **Step 6: Verify the production build compiles**

Run: `cd frontend && npm run build`
Expected: PASS — `next build` completes with no type errors (the new `partials` prop and `parsePartial` import type-check).

- [ ] **Step 7: Manually verify the live stream in the browser**

Start the backend (`cd backend && uv run uvicorn okf_weaver.main:app --reload`, with `ANTHROPIC_API_KEY` set) and the frontend (`cd frontend && npm run dev`). Load the `schema.sql` example, click Generate, and confirm: each pending table's card shows its description and column definitions typing in live, then swaps to the editable validated card. With a multi-table schema, several cards fill concurrently.

- [ ] **Step 8: Commit**

```bash
git add frontend/app/page.tsx frontend/app/BundleTree.tsx frontend/app/globals.css
git commit -m "feat(web): render live-typing table cards from token stream"
```

---

## Self-Review

**Spec coverage** (`docs/spec.md` token-streaming edits):
- §1a "token-level (live typing) then a validated table event" → Tasks 1–3 (backend token events) + Task 5 (live typing UI). ✓
- §4.2 token-streaming sub-point (`messages.stream` → `input_json_delta` → `token` SSE → tolerant partial-JSON parser → per-card live fields; concurrency by table-name routing; gate unchanged; repair-stall edge) → Task 1 (`_stream_call`), Task 2 (routing + concurrency), Task 3 (SSE), Task 4 (parser), Task 5 (cards). ✓
- §5 step 4 two SSE granularities → Task 3. ✓
- §6 `/api/generate` row + notes (`{table, delta}`) → Task 3. ✓
- §10 Streaming entry (token granularity, display-only partials, gate governs export) → Tasks 1–5; gate untouched (no change to `OKFTable.model_validate` path). ✓
- Repair-stall edge case: partial JSON from a second attempt concatenates and fails to parse → `parsePartial` returns `null` → `BundleTree` falls back to the skeleton until the `table` event replaces it. Behavior is correct by construction (Task 4 returns-null contract + Task 5 `hasContent` fallback); no dedicated automated test. ✓

**Placeholder scan:** No TBD/TODO/"add error handling"/"similar to Task N". All code steps show full code. ✓

**Type consistency:**
- `generate_table(..., on_delta: Callable[[str], None] | None = None)` — defined Task 1, called with `on_delta=lambda ...` in Task 2. ✓
- `generate_bundle(...) -> Iterator[tuple[str, str, Any]]` — defined Task 2, consumed as `for kind, name, payload in ...` in Task 3. ✓
- SSE `token` payload `{table, delta}` — emitted Task 3, consumed as `{ table, delta }` in Task 5. ✓
- `parsePartial(raw) -> PartialTable | null`, `PartialTable.columns: {name?, definition?}[]` — defined Task 4, consumed in Task 5 (`preview?.columns.filter(...)`, `c.name`, `c.definition`). ✓
- `BundleTree` new prop `partials: Record<string, string>` — added to type + destructure (Task 5 Step 4) and passed from `page.tsx` (Task 5 Step 3). ✓
- `_FakeStream.get_final_message()` returns `.content`/`.usage`; `_accumulate` reads `getattr(response, "usage", None)` (API fake sets `usage=None` → skipped; AI fake sets it when `usage_per_call` given). ✓
