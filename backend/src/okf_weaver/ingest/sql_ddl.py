"""Parse raw SQL DDL (`CREATE TABLE ...`) into a SchemaIR via sqlglot.

Handles real database dumps, not just clean ANSI SQL: MySQL (`mysqldump`)
backtick-quoted identifiers, SQL Server (SSMS) `[bracket]` identifiers and `GO`
batch separators, and Postgres `pg_dump` where PKs/FKs arrive as separate
`ALTER TABLE ... ADD CONSTRAINT` statements. The dialect is auto-detected from
the SQL when not given.
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from okf_weaver.models import Column, SchemaIR, SourceFormat, Table


def parse_sql_ddl(ddl: str, *, dialect: str | None = None) -> SchemaIR:
    """Parse `CREATE TABLE` statements into a `SchemaIR`.

    Args:
        ddl: One or more SQL statements. Non-`CREATE TABLE` statements are ignored.
        dialect: Optional sqlglot dialect hint. When ``None``, the dialect is
            auto-detected and a few candidates are tried until one yields tables.

    Returns:
        A `SchemaIR` with ``source_format = SourceFormat.SQL``.

    Raises:
        ValueError: If the input can't be parsed or contains no `CREATE TABLE`.
    """
    cleaned = _strip_batch_separators(ddl)
    candidates = [dialect] if dialect is not None else _candidate_dialects(cleaned)

    last_error: sqlglot.errors.ParseError | None = None
    for read in candidates:
        try:
            statements = sqlglot.parse(cleaned, read=read)
        except sqlglot.errors.ParseError as exc:
            last_error = exc
            continue
        tables = _tables_from(statements)
        if tables:
            return SchemaIR(source_format=SourceFormat.SQL, tables=tables)

    if last_error is not None:
        raise ValueError(_friendly_parse_error(last_error))
    raise ValueError(
        "No CREATE TABLE statements found. Paste your schema as one or more "
        "CREATE TABLE definitions (SQL only, no surrounding text)."
    )


def _strip_batch_separators(ddl: str) -> str:
    """Drop `GO` lines — a SSMS/sqlcmd batch separator that isn't valid SQL."""
    return re.sub(r"(?im)^\s*GO\s*;?\s*$", "", ddl)


def _candidate_dialects(sql: str) -> list[str | None]:
    """Ordered sqlglot dialects to try: detected first, then a fallback sweep."""
    ordered: list[str | None] = []
    if "`" in sql:  # backtick-quoted identifiers -> MySQL
        ordered.append("mysql")
    if re.search(r"\[[A-Za-z_#\[]", sql):  # [bracket] identifiers -> SQL Server
        ordered.append("tsql")
    for dialect in (None, "postgres", "mysql", "tsql"):
        if dialect not in ordered:
            ordered.append(dialect)
    return ordered


def _tables_from(statements: list[exp.Expression]) -> list[Table]:
    """Build `Table`s from CREATE statements, folding in ALTER-added constraints."""
    alter_pks, alter_fks = _alter_constraints(statements)

    tables: list[Table] = []
    for stmt in statements:
        if not isinstance(stmt, exp.Create) or stmt.kind != "TABLE":
            continue
        schema = stmt.this  # exp.Schema: table + column/constraint expressions
        table = schema.find(exp.Table)
        if table is None:
            continue
        pk_cols = _pk_columns(schema) | alter_pks.get(table.name, set())
        fks = {**_inline_refs(schema), **_table_fks(schema), **alter_fks.get(table.name, {})}
        columns = [_column(col_def, pk_cols, fks) for col_def in schema.find_all(exp.ColumnDef)]
        tables.append(Table(name=table.name, columns=columns))
    return tables


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


def _column(col_def: exp.ColumnDef, pk_columns: set[str], fks: dict[str, str]) -> Column:
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
        references=fks.get(col_def.name),
    )


def _alter_constraints(
    statements: list[exp.Expression],
) -> tuple[dict[str, set[str]], dict[str, dict[str, str]]]:
    """Collect PK/FK constraints declared via ``ALTER TABLE ... ADD CONSTRAINT``.

    ``pg_dump`` and SQL Server/SSMS emit bare ``CREATE TABLE``s and attach primary
    and foreign keys afterward as separate ``ALTER TABLE`` statements, so those
    constraints are folded back onto the table by name. Returns ``(pks, fks)``
    keyed by table name.
    """
    pks: dict[str, set[str]] = {}
    fks: dict[str, dict[str, str]] = {}
    for stmt in statements:
        if not isinstance(stmt, exp.Alter):
            continue
        table = stmt.find(exp.Table)
        if table is None:
            continue
        pk_cols = _pk_columns(stmt)
        fk_map = _table_fks(stmt)
        if pk_cols:
            pks.setdefault(table.name, set()).update(pk_cols)
        if fk_map:
            fks.setdefault(table.name, {}).update(fk_map)
    return pks, fks


def _inline_refs(schema: exp.Schema) -> dict[str, str]:
    """Foreign keys written inline on a column: ``col ... REFERENCES t(c)``."""
    refs: dict[str, str] = {}
    for col_def in schema.find_all(exp.ColumnDef):
        for constraint in col_def.args.get("constraints") or []:
            if isinstance(constraint.kind, exp.Reference):
                target = _reference_target(constraint.kind.this)
                if target:
                    refs[col_def.name] = target
    return refs


def _table_fks(expr: exp.Expression) -> dict[str, str]:
    """Table-level ``FOREIGN KEY (col) REFERENCES t(c)`` in a CREATE or ALTER."""
    refs: dict[str, str] = {}
    for fk in expr.find_all(exp.ForeignKey):
        local = [e.name for e in fk.expressions]
        ref = fk.args.get("reference")
        if ref is None:
            continue
        ref_schema = ref.this  # exp.Schema: table + referenced columns
        ref_cols = [e.name for e in ref_schema.expressions]
        ref_table = ref_schema.this.name
        for i, col in enumerate(local):
            ref_col = ref_cols[i] if i < len(ref_cols) else (ref_cols[0] if ref_cols else "id")
            refs[col] = f"{ref_table}.{ref_col}"
    return refs


def _reference_target(ref_schema: exp.Expression) -> str | None:
    """Render an inline ``REFERENCES t(c)`` target as ``"t.c"``."""
    table = ref_schema.find(exp.Table)
    if table is None:
        return None
    cols = [e.name for e in getattr(ref_schema, "expressions", [])]
    return f"{table.name}.{cols[0]}" if cols else f"{table.name}.id"


def _pk_columns(expr: exp.Expression) -> set[str]:
    """Columns named in a table-level PRIMARY KEY, across dialects.

    Covers ANSI/Postgres/MySQL ``PRIMARY KEY (cols)`` and ``ALTER ... ADD ...
    PRIMARY KEY (cols)`` (an ``exp.PrimaryKey`` of bare identifiers) as well as
    SQL Server's ``CONSTRAINT [pk] PRIMARY KEY CLUSTERED ([id] ASC)`` (a
    ``Constraint`` whose columns hang off a sibling clustered-index node).
    """
    names: set[str] = set()
    for pk in expr.find_all(exp.PrimaryKey):
        names |= _pk_constraint_columns(pk)
    for constraint in expr.find_all(exp.Constraint):
        if constraint.find(exp.PrimaryKeyColumnConstraint) is not None:
            names |= _pk_constraint_columns(constraint)
    return names


def _pk_constraint_columns(node: exp.Expression) -> set[str]:
    """Column names referenced by a PK node, ignoring the constraint's own name."""
    cols = {c.name for c in node.find_all(exp.Column) if c.name}
    if cols:
        return cols
    # Postgres/ANSI list PK columns as bare identifiers directly under the node.
    return {
        e.name
        for e in getattr(node, "expressions", [])
        if isinstance(e, exp.Identifier) and e.name
    }
