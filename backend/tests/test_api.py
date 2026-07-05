"""API tests via FastAPI TestClient (Anthropic client overridden)."""

import io
import json
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


class FakeClient:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        return SimpleNamespace(content=self._responses.pop(0))


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


def test_ingest_rejects_unparseable_sql_with_422(client):
    resp = client.post("/api/ingest", json={"format": "sql", "content": "SELECT 1;"})
    assert resp.status_code == 422


def test_ingest_rejects_bad_manifest_json_with_422(client):
    resp = client.post("/api/ingest", json={"format": "dbt_manifest", "content": "{not json"})
    assert resp.status_code == 422


def test_generate_streams_table_and_done_events(client):
    app.dependency_overrides[get_client] = lambda: FakeClient(_tool_use(OKF_TABLE_PAYLOAD))
    try:
        schema = {
            "source_format": "sql",
            "tables": [{"name": "orders", "columns": [{"name": "id", "data_type": "int"}]}],
        }
        resp = client.post("/api/generate", json=schema)
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        assert [e for e, _ in events][:1] == ["table"]
        assert events[-1][0] == "done"
        assert events[-1][1]["bundle"]["tables"][0]["name"] == "orders"
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
        assert "okf.yaml" in z.namelist()


def test_download_rejects_invalid_bundle_with_422(client):
    bad = {"tables": [{**OKF_TABLE_PAYLOAD, "confidence": 5}]}
    assert client.post("/api/download", json=bad).status_code == 422


def test_ingest_is_rate_limited(client):
    body = {"format": "sql", "content": DDL}
    codes = [client.post("/api/ingest", json=body).status_code for _ in range(35)]
    assert codes.count(200) == 30  # limit is 30/minute
    assert 429 in codes  # subsequent requests are rejected


def test_health_is_not_rate_limited(client):
    codes = [client.get("/api/health").status_code for _ in range(40)]
    assert set(codes) == {200}


# --- helpers -----------------------------------------------------------------


def _tool_use(payload):
    return [SimpleNamespace(type="tool_use", input=payload)]


def _parse_sse(text):
    events = []
    for chunk in text.strip().split("\n\n"):
        if not chunk.strip():
            continue
        event = next(l[len("event: ") :] for l in chunk.splitlines() if l.startswith("event: "))
        data = next(l[len("data: ") :] for l in chunk.splitlines() if l.startswith("data: "))
        events.append((event, json.loads(data)))
    return events
