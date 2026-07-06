"""Pydantic models — the single source of truth and validation backbone.

Every data structure that crosses a boundary lives here: the ingestion output
(`SchemaIR`), the OKF output bundle (`OKFBundle` and friends), and the API
request/response bodies. Structural OKF v0.1 validity *is* successful
`OKFBundle` construction; cross-field rules are `@model_validator` methods, so
model output and human edits pass through the identical gate.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

#: OKF spec version this build targets. Bump on each Google OKF release.
OKF_SPEC_VERSION = "0.1"

#: Fallback bundle name when the user provides none (or only whitespace).
DEFAULT_BUNDLE_NAME = "OKF Bundle"

# --- Resource caps (defence against cost/resource-exhaustion DoS) ------------
# Every paid or memory-bound path is bounded here at the validation gate, so a
# single request can't fan out to thousands of model calls or build a giant
# in-memory zip. Tune these together with the rate limits in `main.py`.

#: Max tables per schema / bundle. Caps per-request Claude fan-out (one call per
#: table) and the number of files serialized into a bundle.
MAX_TABLES = 100
#: Max columns per table (prompt size + serialized rows).
MAX_COLUMNS_PER_TABLE = 500
#: Max characters of raw schema text accepted by ``/api/ingest``. The SQL parser
#: may re-parse this a few times across candidate dialects, so keep it bounded.
MAX_CONTENT_CHARS = 5_000_000
#: Max characters of free-text business context threaded into every prompt.
MAX_CONTEXT_CHARS = 20_000
#: Max length of a table/column name (also blocks pathological 5k-char names).
NAME_MAX_LENGTH = 200

#: Control characters and path separators are illegal in a name: they enable
#: zip-slip / path traversal when a name becomes a file path on serialize.
_ILLEGAL_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f/\\]")


def validate_identifier(value: str, kind: str) -> str:
    """Reject names that could escape their file path or bloat the bundle.

    Args:
        value: The candidate table or column name.
        kind: Human label for the error message (``"table"`` / ``"column"``).

    Returns:
        The unchanged name when it is safe.

    Raises:
        ValueError: If the name is blank, too long, contains control characters
            or path separators, or contains a ``..`` traversal sequence.
    """
    if not value.strip():
        raise ValueError(f"{kind} name must not be blank")
    if len(value) > NAME_MAX_LENGTH:
        raise ValueError(f"{kind} name exceeds {NAME_MAX_LENGTH} characters")
    if _ILLEGAL_NAME_CHARS.search(value):
        raise ValueError(f"{kind} name must not contain control characters or path separators")
    if ".." in value:
        raise ValueError(f"{kind} name must not contain '..'")
    return value


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
    references: str | None = None  # "table.column" if this is a foreign key


class Table(BaseModel):
    """A table as parsed from the source schema."""

    name: str
    columns: list[Column] = Field(default_factory=list, max_length=MAX_COLUMNS_PER_TABLE)
    description: str | None = None


class SchemaIR(BaseModel):
    """Format-agnostic intermediate representation the AI module consumes."""

    source_format: SourceFormat
    tables: list[Table] = Field(default_factory=list, max_length=MAX_TABLES)


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
    references: str | None = None

    @field_validator("name")
    @classmethod
    def _safe_name(cls, value: str) -> str:
        return validate_identifier(value, "column")


class OKFTable(BaseModel):
    """A generated OKF table entry."""

    name: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    is_source_of_truth: bool = False
    columns: list[OKFColumn] = Field(default_factory=list, max_length=MAX_COLUMNS_PER_TABLE)

    @field_validator("name")
    @classmethod
    def _safe_name(cls, value: str) -> str:
        # A table name becomes a file path (`tables/<name>.md`) on serialize;
        # reject anything that could traverse out of the bundle directory.
        return validate_identifier(value, "table")

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
    name: str = DEFAULT_BUNDLE_NAME
    tables: list[OKFTable] = Field(max_length=MAX_TABLES)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        # Collapse whitespace/newlines into a single-line title; cap length so it
        # stays a sane filename and heading. Blank falls back to the default.
        return " ".join(value.split())[:120] or DEFAULT_BUNDLE_NAME

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

    content: str = Field(max_length=MAX_CONTENT_CHARS)
    format: SourceFormat | None = None


class GenerateRequest(BaseModel):
    """Body for ``POST /api/generate``.

    ``context`` is optional free-text domain/business/glossary notes that steer
    generation toward the user's meaning (e.g. how "revenue" is defined).
    """

    schema_: SchemaIR = Field(alias="schema")
    context: str | None = Field(default=None, max_length=MAX_CONTEXT_CHARS)

    model_config = {"populate_by_name": True}


class ValidationResult(BaseModel):
    """Body for ``POST /api/validate``."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
