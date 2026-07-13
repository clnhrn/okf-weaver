"""API tests via FastAPI TestClient (Anthropic client overridden)."""

import io
import json
import logging
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from okf_weaver.main import app, get_client, limiter

DDL = "CREATE TABLE orders (id INTEGER PRIMARY KEY, total NUMERIC(12,2));"

OKF_TABLE_PAYLOAD = {
    "name": "orders",
    "description": "One row per order.",
    "confidence": 0.9,
    "is_source_of_truth": True,
    "columns": [
        {"name": "id", "definition": "Order key.", "confidence": 0.9},
        {"name": "total", "definition": "Net order value.", "confidence": 0.7},
    ],
}


class _FakeStream:
    def __init__(self, content, usage=None):
        self._content = content
        self._usage = usage

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
        return SimpleNamespace(content=self._content, usage=self._usage)


class FakeClient:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        item = self._responses.pop(0)
        content, usage = item if isinstance(item, tuple) else (item, None)
        return _FakeStream(content, usage)


@pytest.fixture(autouse=True)
def _reset_limiter():
    # Isolate per-IP rate-limit counters so tests don't bleed into each other.
    limiter.reset()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_ingest_sql_returns_schema_ir(client):
    resp = client.post("/api/ingest", json={"format": "sql", "content": DDL})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_format"] == "sql"
    assert body["tables"][0]["name"] == "orders"


def test_ingest_auto_detects_sql_without_format(client):
    resp = client.post("/api/ingest", json={"content": DDL})
    assert resp.status_code == 200
    assert resp.json()["source_format"] == "sql"


def test_ingest_auto_detects_dbt_manifest_without_format(client):
    manifest = json.dumps(
        {"nodes": {"model.s.o": {"resource_type": "model", "name": "o",
                                 "columns": {"id": {"name": "id"}}}}}
    )
    resp = client.post("/api/ingest", json={"content": manifest})
    assert resp.status_code == 200
    assert resp.json()["source_format"] == "dbt_manifest"


def test_ingest_rejects_unparseable_sql_with_422(client):
    resp = client.post("/api/ingest", json={"format": "sql", "content": "SELECT 1;"})
    assert resp.status_code == 422


def test_ingest_over_table_cap_returns_422_not_500(client):
    # Exceeding the SchemaIR table cap raises a Pydantic ValidationError inside
    # the parser; it must surface as a clean 422, never an unhandled 500.
    ddl = "".join(f"CREATE TABLE t{i} (id INT);" for i in range(101))
    resp = client.post("/api/ingest", json={"format": "sql", "content": ddl})
    assert resp.status_code == 422


def test_ingest_rejects_bad_manifest_json_with_422(client):
    resp = client.post("/api/ingest", json={"format": "dbt_manifest", "content": "{not json"})
    assert resp.status_code == 422


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
        # Token/cost usage must not reach the client (it stays server-side).
        assert "usage" not in events[-1][1]
    finally:
        app.dependency_overrides.clear()


def test_generate_logs_usage_server_side_without_sending_it_to_client(client, caplog):
    app.dependency_overrides[get_client] = lambda: FakeClient(_tool_use(OKF_TABLE_PAYLOAD))
    try:
        schema = {
            "source_format": "sql",
            "tables": [{"name": "orders", "columns": [{"name": "id", "data_type": "int"}]}],
        }
        caplog.set_level(logging.INFO)
        resp = client.post("/api/generate", json={"schema": schema})
        events = _parse_sse(resp.text)
        assert "usage" not in events[-1][1]
        # The cost summary is tracked in the backend logs, not the response.
        assert any("estimated_cost_usd" in r.getMessage() for r in caplog.records)
    finally:
        app.dependency_overrides.clear()


def test_generate_emits_error_event_when_a_table_fails(client):
    # A payload that fails OKFTable validation on both the initial call and the
    # repair pass makes generate_table (and thus generate_bundle) raise.
    bad = {**OKF_TABLE_PAYLOAD, "confidence": 9}
    app.dependency_overrides[get_client] = lambda: FakeClient(_tool_use(bad), _tool_use(bad))
    try:
        schema = {
            "source_format": "sql",
            "tables": [{"name": "orders", "columns": [{"name": "id", "data_type": "int"}]}],
        }
        resp = client.post("/api/generate", json={"schema": schema})
        assert resp.status_code == 200
        kinds = [e for e, _ in _parse_sse(resp.text)]
        assert "error" in kinds
        assert "done" not in kinds
    finally:
        app.dependency_overrides.clear()


def test_generate_error_event_hides_internals_and_logs_them(client, caplog):
    # The client must get a generic message + correlation id, never the raw
    # exception text (which can leak Anthropic/validation internals). M3.
    bad = {**OKF_TABLE_PAYLOAD, "confidence": 9}
    app.dependency_overrides[get_client] = lambda: FakeClient(_tool_use(bad), _tool_use(bad))
    try:
        schema = {
            "source_format": "sql",
            "tables": [{"name": "orders", "columns": [{"name": "id", "data_type": "int"}]}],
        }
        caplog.set_level(logging.ERROR)
        resp = client.post("/api/generate", json={"schema": schema})
        error = next(d for e, d in _parse_sse(resp.text) if e == "error")
        assert "error_id" in error
        assert error["error_id"]
        # Generic client message: no raw confidence/validation detail leaks.
        assert "confidence" not in error["message"].lower()
        assert "validation" not in error["message"].lower()
        # The full detail (and the same id) is captured server-side instead.
        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert error["error_id"] in logged
    finally:
        app.dependency_overrides.clear()


def test_validate_reports_valid_bundle(client):
    resp = client.post("/api/validate", json={"tables": [OKF_TABLE_PAYLOAD]})
    assert resp.json() == {"valid": True, "errors": []}


def test_validate_reports_errors_for_bad_bundle(client):
    bad = {"tables": [{**OKF_TABLE_PAYLOAD, "confidence": 5}]}
    body = client.post("/api/validate", json=bad).json()
    assert body["valid"] is False
    assert body["errors"]


def test_download_returns_zip(client):
    resp = client.post("/api/download", json={"tables": [OKF_TABLE_PAYLOAD]})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        assert "index.md" in z.namelist()  # OKF bundle-root manifest


def test_download_names_the_zip_from_the_bundle_name(client):
    resp = client.post(
        "/api/download", json={"name": "Acme Sales Warehouse", "tables": [OKF_TABLE_PAYLOAD]}
    )
    assert resp.status_code == 200
    assert "acme-sales-warehouse.zip" in resp.headers["content-disposition"]


def test_download_exposes_content_disposition_cross_origin(client):
    # The browser can only read the filename from Content-Disposition if the
    # server exposes it via CORS; sending an Origin makes the middleware emit
    # the CORS headers (plain same-origin test requests don't).
    resp = client.post(
        "/api/download",
        json={"name": "Acme Sales Warehouse", "tables": [OKF_TABLE_PAYLOAD]},
        headers={"Origin": "https://okf-weaver.vercel.app"},
    )
    assert resp.status_code == 200
    exposed = resp.headers.get("access-control-expose-headers", "").lower()
    assert "content-disposition" in exposed


def test_download_rejects_invalid_bundle_with_422(client):
    bad = {"tables": [{**OKF_TABLE_PAYLOAD, "confidence": 5}]}
    assert client.post("/api/download", json=bad).status_code == 422


def test_preview_returns_the_serialized_okf_files(client):
    resp = client.post("/api/preview", json={"tables": [OKF_TABLE_PAYLOAD]})
    assert resp.status_code == 200
    files = resp.json()["files"]
    assert "index.md" in files
    assert "tables/orders.md" in files
    assert "type: Table" in files["tables/orders.md"]  # same bytes download would zip


def test_preview_rejects_invalid_bundle_with_422(client):
    bad = {"tables": [{**OKF_TABLE_PAYLOAD, "confidence": 5}]}
    assert client.post("/api/preview", json=bad).status_code == 422


def test_ingest_is_rate_limited(client):
    body = {"format": "sql", "content": DDL}
    codes = [client.post("/api/ingest", json=body).status_code for _ in range(35)]
    assert codes.count(200) == 30  # limit is 30/minute
    assert 429 in codes  # subsequent requests are rejected


def test_rate_limit_buckets_are_per_forwarded_client_ip(client):
    # Behind Render's proxy, request.client.host is the proxy for everyone, so
    # limits must key off the real client IP in X-Forwarded-For. Two distinct
    # clients must not share a bucket, and one client can't drain another's. H2.
    body = {"format": "sql", "content": DDL}

    def hit(ip):
        return client.post(
            "/api/ingest", json=body, headers={"X-Forwarded-For": ip}
        ).status_code

    codes_a = [hit("1.1.1.1") for _ in range(31)]
    assert codes_a.count(200) == 30
    assert codes_a[-1] == 429  # client A is now exhausted
    assert hit("2.2.2.2") == 200  # client B has its own fresh bucket


def test_forwarded_for_spoofed_prefix_cannot_escape_rate_limit(client):
    # A caller can prepend arbitrary values to X-Forwarded-For, but our trusted
    # edge (Render) appends the true socket peer as the *rightmost* entry, which
    # the caller can't forge. Keying off the rightmost entry means rotating the
    # spoofable prefix does not mint fresh buckets: same real client, one bucket,
    # limit still bites. Keying off the leftmost would let it escape entirely. H2.
    body = {"format": "sql", "content": DDL}

    def hit(spoofed_prefix):
        # "3.3.3.3" stands in for the real IP the edge appends; only it counts.
        return client.post(
            "/api/ingest",
            json=body,
            headers={"X-Forwarded-For": f"{spoofed_prefix}, 3.3.3.3"},
        ).status_code

    codes = [hit(f"10.0.0.{i}") for i in range(31)]
    assert codes.count(200) == 30  # one real client, one 30/minute bucket
    assert codes[-1] == 429  # rotating the spoofed prefix bought no new bucket


def test_health_is_not_rate_limited(client):
    codes = [client.get("/api/health").status_code for _ in range(40)]
    assert set(codes) == {200}


def test_cors_allows_configured_origin_and_omits_unknown_ones(client):
    allowed = client.post(
        "/api/validate",
        json={"tables": [OKF_TABLE_PAYLOAD]},
        headers={"Origin": "https://okf-weaver.vercel.app"},
    )
    assert allowed.headers.get("access-control-allow-origin") == "https://okf-weaver.vercel.app"

    evil = client.post(
        "/api/validate",
        json={"tables": [OKF_TABLE_PAYLOAD]},
        headers={"Origin": "https://evil.example"},
    )
    # A non-allowlisted origin gets no ACAO header (browser blocks the read).
    assert "access-control-allow-origin" not in {k.lower() for k in evil.headers}


# --- helpers -----------------------------------------------------------------


def _tool_use(payload, usage=None):
    content = [SimpleNamespace(type="tool_use", input=payload)]
    return (content, usage) if usage is not None else content


def _parse_sse(text):
    events = []
    for chunk in text.strip().split("\n\n"):
        if not chunk.strip():
            continue
        event = next(l[len("event: ") :] for l in chunk.splitlines() if l.startswith("event: "))
        data = next(l[len("data: ") :] for l in chunk.splitlines() if l.startswith("data: "))
        events.append((event, json.loads(data)))
    return events
