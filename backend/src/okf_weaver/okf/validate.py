"""OKF v0.1 validation.

Structural validity *is* successful `OKFBundle` construction (§3.3 of the spec);
this module only wraps that (`build_bundle`), turns Pydantic errors into readable
strings (`format_validation_error`), and adds a non-fatal cross-check against the
source schema to flag hallucinated or missing entities (`check_against_schema`).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from okf_weaver.models import OKFBundle, SchemaIR


def build_bundle(payload: Any) -> OKFBundle:
    """Construct (and thereby validate) an `OKFBundle` from raw data.

    Raises:
        pydantic.ValidationError: If the payload is not a structurally valid
            OKF v0.1 bundle. Callers convert this to a 422 / repair-pass input.
    """
    return OKFBundle.model_validate(payload)


def format_validation_error(exc: ValidationError) -> list[str]:
    """Render a `ValidationError` as a list of human-readable field messages."""
    messages = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        messages.append(f"{loc}: {err['msg']}")
    return messages


def check_against_schema(bundle: OKFBundle, schema: SchemaIR) -> list[str]:
    """Warn about entities in the bundle that don't exist in the source schema.

    This is the "don't invent columns or tables" guard from the spec, run as a
    non-fatal cross-check (the model self-reports, humans review) rather than a
    hard validation error. Also flags source tables missing from the bundle.
    """
    schema_columns = {t.name: {c.name for c in t.columns} for t in schema.tables}
    bundle_tables = {t.name for t in bundle.tables}
    warnings: list[str] = []

    for table in bundle.tables:
        if table.name not in schema_columns:
            warnings.append(f"table '{table.name}' is not in the source schema")
            continue
        for column in table.columns:
            if column.name not in schema_columns[table.name]:
                warnings.append(
                    f"column '{table.name}.{column.name}' is not in the source schema"
                )

    for name in schema_columns:
        if name not in bundle_tables:
            warnings.append(f"table '{name}' from the source schema is missing from the bundle")

    return warnings
