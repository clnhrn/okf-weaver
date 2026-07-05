"""Parse raw SQL DDL (`CREATE TABLE ...`) into a SchemaIR via sqlglot."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from okf_weaver.models import Column, SchemaIR, SourceFormat, Table


def parse_sql_ddl(ddl: str, *, dialect: str | None = None) -> SchemaIR:
    """Parse `CREATE TABLE` statements into a `SchemaIR`.

    Args:
        ddl: One or more SQL statements. Non-`CREATE TABLE` statements are ignored.
        dialect: Optional sqlglot dialect hint; ``None`` lets sqlglot infer.

    Returns:
        A `SchemaIR` with ``source_format = SourceFormat.SQL``.

    Raises:
        ValueError: If the input can't be parsed or contains no `CREATE TABLE`.
    """
    try:
        statements = sqlglot.parse(ddl, read=dialect)
    except sqlglot.errors.ParseError as exc:
        raise ValueError(_friendly_parse_error(exc)) from exc

    tables: list[Table] = []
    for stmt in statements:
        if not isinstance(stmt, exp.Create) or stmt.kind != "TABLE":
            continue
        schema = stmt.this  # exp.Schema: table + column/constraint expressions
        table = schema.find(exp.Table)
        if table is None:
            continue
        pk_from_table = _table_level_pk_columns(schema)
        columns = [
            _column(col_def, pk_from_table) for col_def in schema.find_all(exp.ColumnDef)
        ]
        tables.append(Table(name=table.name, columns=columns))

    if not tables:
        raise ValueError(
            "No CREATE TABLE statements found. Paste your schema as one or more "
            "CREATE TABLE definitions (SQL only, no surrounding text)."
        )
    return SchemaIR(source_format=SourceFormat.SQL, tables=tables)


def _friendly_parse_error(exc: sqlglot.errors.ParseError) -> str:
    """Turn a raw sqlglot ParseError (ANSI codes, echoed SQL) into a clean message."""
    errors = getattr(exc, "errors", None) or []
    if errors:
        first = errors[0]
        description = (first.get("description") or "invalid syntax").strip()
        line, col = first.get("line"), first.get("col")
        where = f" at line {line}, column {col}" if line and col else ""
        detail = f"{description}{where}"
    else:
        detail = "invalid SQL syntax"
    return (
        f"Could not parse SQL: {detail}. Check for balanced parentheses and a "
        "semicolon after each CREATE TABLE, and paste SQL only (no labels or prose)."
    )


def _column(col_def: exp.ColumnDef, pk_columns: set[str]) -> Column:
    kind = col_def.args.get("kind")
    constraints = col_def.args.get("constraints") or []
    constraint_types = {type(c.kind) for c in constraints}

    is_pk = col_def.name in pk_columns or exp.PrimaryKeyColumnConstraint in constraint_types
    not_null = exp.NotNullColumnConstraint in constraint_types
    return Column(
        name=col_def.name,
        data_type=kind.sql() if kind else "unknown",
        nullable=not (not_null or is_pk),
        is_primary_key=is_pk,
    )


def _table_level_pk_columns(schema: exp.Schema) -> set[str]:
    """Column names named in a table-level ``PRIMARY KEY (...)`` constraint."""
    names: set[str] = set()
    for pk in schema.find_all(exp.PrimaryKey):
        names.update(col.name for col in pk.expressions)
    return names
