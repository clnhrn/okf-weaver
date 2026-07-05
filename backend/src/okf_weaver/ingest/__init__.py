"""Ingestion layer: normalize a schema (SQL DDL or dbt manifest) into SchemaIR."""

from okf_weaver.ingest.dbt_manifest import parse_dbt_manifest
from okf_weaver.ingest.sql_ddl import parse_sql_ddl
from okf_weaver.models import SourceFormat

__all__ = ["parse_sql_ddl", "parse_dbt_manifest", "detect_format"]


def detect_format(content: str) -> SourceFormat:
    """Infer the input format: JSON-ish content is a dbt manifest, else SQL DDL.

    A dbt manifest is a JSON object; SQL DDL never starts with ``{``/``[``.
    Routing JSON-ish input to the manifest path also means malformed JSON
    surfaces the "Invalid JSON" error rather than a confusing SQL parse error.
    """
    return SourceFormat.DBT_MANIFEST if content.lstrip().startswith(("{", "[")) else SourceFormat.SQL
