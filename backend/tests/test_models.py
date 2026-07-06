"""Tests for the Pydantic models that are OKF Weaver's validation backbone."""

import pytest
from pydantic import ValidationError

from okf_weaver.models import (
    MAX_COLUMNS_PER_TABLE,
    MAX_CONTENT_CHARS,
    MAX_CONTEXT_CHARS,
    MAX_TABLES,
    NAME_MAX_LENGTH,
    OKF_SPEC_VERSION,
    Column,
    GenerateRequest,
    IngestRequest,
    OKFBundle,
    OKFColumn,
    OKFTable,
    SchemaIR,
    SourceFormat,
    Table,
)


# --- SchemaIR (ingestion output) ---------------------------------------------


def test_column_defaults():
    col = Column(name="id", data_type="int")
    assert col.nullable is True
    assert col.is_primary_key is False
    assert col.description is None


def test_schema_ir_holds_tables_and_columns():
    schema = SchemaIR(
        source_format=SourceFormat.SQL,
        tables=[
            Table(
                name="orders",
                columns=[
                    Column(name="id", data_type="int", is_primary_key=True, nullable=False),
                    Column(name="total", data_type="numeric"),
                ],
            )
        ],
    )
    assert schema.source_format is SourceFormat.SQL
    assert schema.tables[0].columns[0].is_primary_key is True


def test_source_format_rejects_unknown_value():
    with pytest.raises(ValidationError):
        SchemaIR(source_format="parquet", tables=[])


# --- OKF output models -------------------------------------------------------


def _okf_table(name="orders"):
    return OKFTable(
        name=name,
        description="One row per customer order.",
        confidence=0.9,
        is_source_of_truth=True,
        columns=[
            OKFColumn(name="id", definition="Surrogate order key.", confidence=0.95),
            OKFColumn(name="total", definition="Net order value, tax excluded.", confidence=0.6),
        ],
    )


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0, -1.0])
def test_okf_column_rejects_out_of_range_confidence(bad):
    with pytest.raises(ValidationError):
        OKFColumn(name="x", definition="d", confidence=bad)


@pytest.mark.parametrize("ok", [0.0, 0.5, 1.0])
def test_okf_column_accepts_confidence_in_unit_interval(ok):
    assert OKFColumn(name="x", definition="d", confidence=ok).confidence == ok


def test_okf_column_schema_facts_default_when_unset():
    col = OKFColumn(name="x", definition="d", confidence=0.5)
    assert col.data_type == "unknown"
    assert col.is_primary_key is False
    assert col.nullable is True


def test_okf_bundle_valid_construction_defaults_to_current_version():
    bundle = OKFBundle(tables=[_okf_table()])
    assert bundle.okf_version == OKF_SPEC_VERSION


def test_okf_bundle_name_defaults_and_is_trimmed():
    assert OKFBundle(tables=[_okf_table()]).name == "OKF Bundle"
    assert OKFBundle(name="  Acme  Sales\nWarehouse ", tables=[_okf_table()]).name == (
        "Acme Sales Warehouse"
    )


def test_okf_bundle_blank_name_falls_back_to_default():
    assert OKFBundle(name="   ", tables=[_okf_table()]).name == "OKF Bundle"


def test_okf_bundle_rejects_wrong_okf_version():
    with pytest.raises(ValidationError):
        OKFBundle(okf_version="9.9", tables=[_okf_table()])


def test_okf_bundle_rejects_empty_bundle():
    with pytest.raises(ValidationError):
        OKFBundle(tables=[])


def test_okf_bundle_rejects_duplicate_table_names():
    with pytest.raises(ValidationError):
        OKFBundle(tables=[_okf_table("orders"), _okf_table("orders")])


def test_okf_table_rejects_duplicate_column_names():
    # The rule lives on OKFTable, so the invalid table can't be constructed at all.
    with pytest.raises(ValidationError):
        OKFTable(
            name="orders",
            description="d",
            confidence=0.9,
            columns=[
                OKFColumn(name="id", definition="a", confidence=0.9),
                OKFColumn(name="id", definition="b", confidence=0.9),
            ],
        )


# --- M1: name validators (zip-slip / path traversal) -------------------------


@pytest.mark.parametrize(
    "evil",
    [
        "../../../../tmp/pwned",
        "../index",
        "tables/../x",
        "a/b",
        "a\\b",
        "..",
        "foo/..",
        "with\nnewline",
        "null\x00byte",
    ],
)
def test_okf_table_name_rejects_path_traversal_and_control_chars(evil):
    with pytest.raises(ValidationError):
        OKFTable(
            name=evil,
            description="d",
            confidence=0.9,
            columns=[OKFColumn(name="id", definition="d", confidence=0.9)],
        )


def test_okf_table_name_rejects_blank():
    with pytest.raises(ValidationError):
        OKFTable(name="   ", description="d", confidence=0.9, columns=[])


def test_okf_table_name_rejects_overlong_name():
    with pytest.raises(ValidationError):
        OKFTable(
            name="x" * (NAME_MAX_LENGTH + 1),
            description="d",
            confidence=0.9,
            columns=[OKFColumn(name="id", definition="d", confidence=0.9)],
        )


@pytest.mark.parametrize("ok", ["orders", "Order Details", "dim_customer", "schema.table", "v1.2-beta"])
def test_okf_table_name_accepts_normal_identifiers(ok):
    table = OKFTable(
        name=ok,
        description="d",
        confidence=0.9,
        columns=[OKFColumn(name="id", definition="d", confidence=0.9)],
    )
    assert table.name == ok


@pytest.mark.parametrize("evil", ["../../etc/passwd", "a/b", "bad\x00", ".."])
def test_okf_column_name_rejects_dangerous_values(evil):
    with pytest.raises(ValidationError):
        OKFColumn(name=evil, definition="d", confidence=0.9)


# --- H1 / M2: size caps ------------------------------------------------------


def _col(i):
    return Column(name=f"c{i}", data_type="int")


def test_schema_ir_rejects_more_than_max_tables():
    tables = [Table(name=f"t{i}") for i in range(MAX_TABLES + 1)]
    with pytest.raises(ValidationError):
        SchemaIR(source_format=SourceFormat.SQL, tables=tables)


def test_schema_ir_accepts_max_tables():
    tables = [Table(name=f"t{i}") for i in range(MAX_TABLES)]
    assert len(SchemaIR(source_format=SourceFormat.SQL, tables=tables).tables) == MAX_TABLES


def test_table_rejects_more_than_max_columns():
    with pytest.raises(ValidationError):
        Table(name="wide", columns=[_col(i) for i in range(MAX_COLUMNS_PER_TABLE + 1)])


def test_okf_bundle_rejects_more_than_max_tables():
    with pytest.raises(ValidationError):
        OKFBundle(tables=[_okf_table(f"t{i}") for i in range(MAX_TABLES + 1)])


def test_ingest_request_rejects_overlong_content():
    with pytest.raises(ValidationError):
        IngestRequest(content="x" * (MAX_CONTENT_CHARS + 1))


def test_ingest_request_accepts_content_at_cap():
    assert IngestRequest(content="x" * MAX_CONTENT_CHARS).content


def test_generate_request_rejects_overlong_context():
    schema = SchemaIR(source_format=SourceFormat.SQL, tables=[Table(name="t")])
    with pytest.raises(ValidationError):
        GenerateRequest(schema=schema, context="x" * (MAX_CONTEXT_CHARS + 1))
