"""Tests for the ingestion layer (SQL DDL + dbt manifest -> SchemaIR)."""

import pytest

from okf_weaver.ingest import detect_format, parse_dbt_manifest, parse_sql_ddl
from okf_weaver.models import SourceFormat

DDL = """
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    total NUMERIC(12, 2),
    status VARCHAR(20)
);

CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL
);
"""


def test_parse_sql_ddl_extracts_tables_and_columns():
    schema = parse_sql_ddl(DDL)
    assert schema.source_format is SourceFormat.SQL
    assert {t.name for t in schema.tables} == {"orders", "customers"}
    orders = next(t for t in schema.tables if t.name == "orders")
    assert [c.name for c in orders.columns] == ["id", "customer_id", "total", "status"]


def test_parse_sql_ddl_captures_primary_key_and_nullability():
    orders = next(t for t in parse_sql_ddl(DDL).tables if t.name == "orders")
    by_name = {c.name: c for c in orders.columns}
    assert by_name["id"].is_primary_key is True
    assert by_name["customer_id"].nullable is False
    assert by_name["status"].nullable is True


def test_parse_sql_ddl_raises_when_no_create_table():
    with pytest.raises(ValueError):
        parse_sql_ddl("SELECT 1;")


def test_parse_sql_ddl_gives_clean_concise_error_on_malformed_input():
    # Mimics pasted junk: a partial statement / stray prose before real SQL.
    with pytest.raises(ValueError) as exc:
        parse_sql_ddl("SQL DDL: CREATE TABLE t (id INT,")
    msg = str(exc.value)
    assert "\x1b" not in msg  # no ANSI colour/underline escape codes
    assert "line" in msg.lower()  # points at where it failed
    assert len(msg) < 300  # concise, not the whole echoed input


# --- dbt manifest ------------------------------------------------------------

MANIFEST = {
    "nodes": {
        "model.shop.orders": {
            "resource_type": "model",
            "name": "orders",
            "description": "One row per order.",
            "columns": {
                "id": {"name": "id", "data_type": "integer", "description": "Order key."},
                "total": {"name": "total", "data_type": "numeric", "description": ""},
            },
        },
        "test.shop.not_null": {"resource_type": "test", "name": "not_null_orders_id"},
    },
    "sources": {
        "source.shop.raw_events": {
            "resource_type": "source",
            "name": "raw_events",
            "columns": {"event_id": {"name": "event_id"}},
        }
    },
}


def test_parse_dbt_manifest_extracts_models_and_sources():
    schema = parse_dbt_manifest(MANIFEST)
    assert schema.source_format is SourceFormat.DBT_MANIFEST
    assert {t.name for t in schema.tables} == {"orders", "raw_events"}  # test node skipped


def test_parse_dbt_manifest_preserves_descriptions_and_defaults_missing_type():
    orders = next(t for t in parse_dbt_manifest(MANIFEST).tables if t.name == "orders")
    assert orders.description == "One row per order."
    assert orders.columns[0].description == "Order key."
    raw = next(t for t in parse_dbt_manifest(MANIFEST).tables if t.name == "raw_events")
    assert raw.columns[0].data_type == "unknown"  # no data_type in manifest


def test_parse_dbt_manifest_raises_when_no_tables():
    with pytest.raises(ValueError):
        parse_dbt_manifest({"nodes": {}, "sources": {}})


# --- format auto-detection ---------------------------------------------------


@pytest.mark.parametrize("text", ['{"nodes": {}}', '  \n  {"x": 1}', "[1, 2]"])
def test_detect_format_json_is_dbt_manifest(text):
    assert detect_format(text) is SourceFormat.DBT_MANIFEST


@pytest.mark.parametrize("text", [DDL, "  CREATE TABLE t (id INT);", "select 1"])
def test_detect_format_non_json_is_sql(text):
    assert detect_format(text) is SourceFormat.SQL
