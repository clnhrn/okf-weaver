"""Ingestion layer: normalize a schema (SQL DDL or dbt manifest) into SchemaIR."""

from okf_weaver.ingest.dbt_manifest import parse_dbt_manifest
from okf_weaver.ingest.sql_ddl import parse_sql_ddl

__all__ = ["parse_sql_ddl", "parse_dbt_manifest"]
