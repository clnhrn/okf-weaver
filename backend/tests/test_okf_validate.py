"""Tests for OKF validation helpers (bundle construction + schema cross-check)."""

import pytest
from pydantic import ValidationError

from okf_weaver.models import Column, OKFColumn, OKFTable, SchemaIR, SourceFormat, Table
from okf_weaver.okf.validate import (
    build_bundle,
    check_against_schema,
    format_validation_error,
)


def _valid_payload():
    return {
        "tables": [
            {
                "name": "orders",
                "description": "One row per order.",
                "confidence": 0.9,
                "is_source_of_truth": True,
                "columns": [{"name": "id", "definition": "Order key.", "confidence": 0.9}],
            }
        ]
    }


def test_build_bundle_from_valid_payload():
    bundle = build_bundle(_valid_payload())
    assert bundle.tables[0].name == "orders"


def test_build_bundle_raises_on_bad_confidence():
    payload = _valid_payload()
    payload["tables"][0]["columns"][0]["confidence"] = 5
    with pytest.raises(ValidationError):
        build_bundle(payload)


def test_format_validation_error_is_human_readable():
    payload = _valid_payload()
    payload["tables"][0]["columns"][0]["confidence"] = 5
    try:
        build_bundle(payload)
    except ValidationError as exc:
        messages = format_validation_error(exc)
        assert messages and any("confidence" in m for m in messages)


def _schema():
    return SchemaIR(
        source_format=SourceFormat.SQL,
        tables=[Table(name="orders", columns=[Column(name="id", data_type="int")])],
    )


def test_check_against_schema_clean_when_bundle_matches():
    bundle = build_bundle(_valid_payload())
    assert check_against_schema(bundle, _schema()) == []


def test_check_against_schema_flags_hallucinated_table():
    bundle = build_bundle(
        {"tables": [{"name": "ghosts", "description": "d", "confidence": 0.5}]}
    )
    warnings = check_against_schema(bundle, _schema())
    assert any("ghosts" in w for w in warnings)


def test_check_against_schema_flags_hallucinated_column_and_missing_table():
    bundle = build_bundle(
        {
            "tables": [
                {
                    "name": "orders",
                    "description": "d",
                    "confidence": 0.5,
                    "columns": [{"name": "made_up", "definition": "x", "confidence": 0.5}],
                }
            ]
        }
    )
    warnings = check_against_schema(bundle, _schema())
    assert any("made_up" in w for w in warnings)
