"""Tests for the AI generation module (Anthropic client mocked)."""

from types import SimpleNamespace

import pytest

from okf_weaver.ai.generate import generate_bundle, generate_table, usage_summary
from okf_weaver.models import Column, OKFBundle, SchemaIR, SourceFormat, Table


def _tool_use(payload):
    return SimpleNamespace(type="tool_use", input=payload)


class FakeClient:
    """Stand-in for anthropic.Anthropic; returns queued tool-use responses."""

    def __init__(self, *responses, usage_per_call=None):
        self._responses = list(responses)
        self.calls = 0
        self.last_kwargs = None
        self._usage = usage_per_call
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        content = self._responses.pop(0)
        usage = SimpleNamespace(**self._usage) if self._usage else None
        return SimpleNamespace(content=content, usage=usage)


TABLE = Table(
    name="orders",
    columns=[Column(name="id", data_type="int", is_primary_key=True, nullable=False)],
)

GOOD_PAYLOAD = {
    "name": "orders",
    "description": "One row per order.",
    "confidence": 0.9,
    "is_source_of_truth": True,
    "columns": [{"name": "id", "definition": "Order key.", "confidence": 0.9}],
}


def test_generate_table_returns_validated_okf_table():
    client = FakeClient([_tool_use(GOOD_PAYLOAD)])
    result = generate_table(TABLE, client=client, model_id="test-model")
    assert result.name == "orders"
    assert result.columns[0].definition == "Order key."


def test_generate_table_attaches_schema_facts_from_source():
    # The model payload has no type/PK/nullable; they come from the source Table.
    client = FakeClient([_tool_use(GOOD_PAYLOAD)])
    col = generate_table(TABLE, client=client, model_id="test-model").columns[0]
    assert col.data_type == "int"
    assert col.is_primary_key is True
    assert col.nullable is False


def test_generate_table_threads_context_into_system_prompt():
    client = FakeClient([_tool_use(GOOD_PAYLOAD)])
    generate_table(TABLE, client=client, model_id="m", context="Revenue excludes tax.")
    assert "Revenue excludes tax." in client.last_kwargs["system"][0]["text"]


def test_generate_table_without_context_uses_base_system_prompt():
    client = FakeClient([_tool_use(GOOD_PAYLOAD)])
    generate_table(TABLE, client=client, model_id="m")
    assert "Business context" not in client.last_kwargs["system"][0]["text"]


def test_generate_table_passes_through_column_references():
    src = Table(
        name="orders",
        columns=[Column(name="customer_id", data_type="int", references="customers.id")],
    )
    payload = {
        "name": "orders",
        "description": "d",
        "confidence": 0.8,
        "columns": [{"name": "customer_id", "definition": "FK to customer.", "confidence": 0.8}],
    }
    client = FakeClient([_tool_use(payload)])
    col = generate_table(src, client=client, model_id="m").columns[0]
    assert col.references == "customers.id"


def test_generate_accumulates_usage_and_estimates_cost():
    acc: dict = {}
    client = FakeClient(
        [_tool_use(GOOD_PAYLOAD)],
        usage_per_call={
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    )
    generate_table(TABLE, client=client, model_id="claude-sonnet-4-6", usage=acc)
    assert acc["input_tokens"] == 1000 and acc["output_tokens"] == 200
    summary = usage_summary(acc, "claude-sonnet-4-6")
    # (1000*$3 + 200*$15) / 1e6 = 0.006
    assert summary["estimated_cost_usd"] == 0.006


def test_generate_table_sends_cache_control_on_system_prompt():
    client = FakeClient([_tool_use(GOOD_PAYLOAD)])
    generate_table(TABLE, client=client, model_id="m")
    system = client.last_kwargs["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_generate_table_forces_table_name_from_source():
    # Model returns the wrong name; the source name is authoritative.
    payload = {**GOOD_PAYLOAD, "name": "WRONG"}
    client = FakeClient([_tool_use(payload)])
    assert generate_table(TABLE, client=client, model_id="test-model").name == "orders"


def test_generate_table_repairs_invalid_output_once():
    bad = {**GOOD_PAYLOAD, "columns": [{"name": "id", "definition": "x", "confidence": 9}]}
    client = FakeClient([_tool_use(bad)], [_tool_use(GOOD_PAYLOAD)])
    result = generate_table(TABLE, client=client, model_id="test-model")
    assert result.confidence == 0.9
    assert client.calls == 2  # one bad, one repair


def test_generate_table_raises_when_repair_also_fails():
    bad = {**GOOD_PAYLOAD, "confidence": 9}
    client = FakeClient([_tool_use(bad)], [_tool_use(bad)])
    with pytest.raises(Exception):
        generate_table(TABLE, client=client, model_id="test-model")


def test_generate_table_raises_when_model_skips_tool_call():
    client = FakeClient([[SimpleNamespace(type="text", text="hi")]])
    with pytest.raises(ValueError):
        generate_table(TABLE, client=client, model_id="test-model")


def test_generate_bundle_streams_one_table_per_input_and_assembles():
    schema = SchemaIR(
        source_format=SourceFormat.SQL,
        tables=[TABLE, Table(name="customers", columns=[Column(name="id", data_type="int")])],
    )
    client = FakeClient(
        [_tool_use(GOOD_PAYLOAD)],
        [_tool_use({**GOOD_PAYLOAD, "name": "customers"})],
    )
    streamed = list(generate_bundle(schema, client=client, model_id="test-model"))
    assert [t.name for t in streamed] == ["orders", "customers"]
    bundle = OKFBundle(tables=streamed)
    assert {t.name for t in bundle.tables} == {"orders", "customers"}
