"""Pydantic models — the single source of truth and validation backbone.

Every data structure that crosses a boundary lives here: the ingestion output
(`SchemaIR`), the OKF output bundle (`OKFBundle` and friends), and the API
request/response bodies. Structural OKF v0.1 validity *is* successful
`OKFBundle` construction; cross-field rules are `@model_validator` methods, so
model output and human edits pass through the identical gate.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

#: OKF spec version this build targets. Bump on each Google OKF release.
OKF_SPEC_VERSION = "0.1"


# --- Ingestion IR ------------------------------------------------------------


class SourceFormat(str, Enum):
    """Accepted schema input formats."""

    SQL = "sql"
    DBT_MANIFEST = "dbt_manifest"


class Column(BaseModel):
    """A column as parsed from the source schema (no generated content yet)."""

    name: str
    data_type: str
    nullable: bool = True
    is_primary_key: bool = False
    description: str | None = None


class Table(BaseModel):
    """A table as parsed from the source schema."""

    name: str
    columns: list[Column] = Field(default_factory=list)
    description: str | None = None


class SchemaIR(BaseModel):
    """Format-agnostic intermediate representation the AI module consumes."""

    source_format: SourceFormat
    tables: list[Table] = Field(default_factory=list)


# --- OKF output --------------------------------------------------------------


class OKFColumn(BaseModel):
    """A generated OKF column definition plus the inferred schema facts.

    `definition` and `confidence` come from the model; `data_type`,
    `is_primary_key`, and `nullable` are carried over from ingestion (never
    invented by the model) so inference decisions travel with the bundle.
    """

    name: str
    definition: str
    confidence: float = Field(ge=0.0, le=1.0)
    data_type: str = "unknown"
    is_primary_key: bool = False
    nullable: bool = True


class OKFTable(BaseModel):
    """A generated OKF table entry."""

    name: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    is_source_of_truth: bool = False
    columns: list[OKFColumn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_column_names(self) -> OKFTable:
        names = [c.name for c in self.columns]
        if len(names) != len(set(names)):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"table {self.name!r} has duplicate columns: {dupes}")
        return self


class OKFBundle(BaseModel):
    """A full OKF v0.1 bundle. Successful construction == structurally valid."""

    okf_version: str = OKF_SPEC_VERSION
    tables: list[OKFTable]

    @model_validator(mode="after")
    def _validate_bundle(self) -> OKFBundle:
        if self.okf_version != OKF_SPEC_VERSION:
            raise ValueError(
                f"unsupported OKF version {self.okf_version!r}; "
                f"this build targets {OKF_SPEC_VERSION!r}"
            )
        if not self.tables:
            raise ValueError("bundle must contain at least one table")
        names = [t.name for t in self.tables]
        if len(names) != len(set(names)):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"duplicate table names in bundle: {dupes}")
        return self


# --- API bodies --------------------------------------------------------------


class IngestRequest(BaseModel):
    """Body for ``POST /api/ingest``. ``format`` is auto-detected when omitted."""

    content: str
    format: SourceFormat | None = None


class ValidationResult(BaseModel):
    """Body for ``POST /api/validate``."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
