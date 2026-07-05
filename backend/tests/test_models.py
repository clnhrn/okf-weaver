"""Tests for the Pydantic models that are OKF Weaver's validation backbone."""

import pytest
from pydantic import ValidationError

from okf_weaver.models import (
    OKF_SPEC_VERSION,
    Column,
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


def test_okf_bundle_valid_construction_defaults_to_current_version():
    bundle = OKFBundle(tables=[_okf_table()])
    assert bundle.okf_version == OKF_SPEC_VERSION


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
