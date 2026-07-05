"""Parse a dbt `manifest.json` (as a dict) into a SchemaIR."""

from __future__ import annotations

from typing import Any

from okf_weaver.models import Column, SchemaIR, SourceFormat, Table

#: dbt resource types we treat as tables.
_TABLE_RESOURCE_TYPES = {"model", "source", "seed", "snapshot"}


def parse_dbt_manifest(manifest: dict[str, Any]) -> SchemaIR:
    """Extract tables and columns from a parsed dbt manifest.

    Args:
        manifest: The deserialized contents of `manifest.json`.

    Returns:
        A `SchemaIR` with ``source_format = SourceFormat.DBT_MANIFEST``. Existing
        dbt `description` fields are preserved as a prior for the AI module.

    Raises:
        ValueError: If no model/source/seed/snapshot nodes are found.
    """
    nodes = {**manifest.get("nodes", {}), **manifest.get("sources", {})}
    tables: list[Table] = []
    for node in nodes.values():
        if node.get("resource_type") not in _TABLE_RESOURCE_TYPES:
            continue
        columns = [
            Column(
                name=col["name"],
                data_type=col.get("data_type") or "unknown",
                description=col.get("description") or None,
            )
            for col in (node.get("columns") or {}).values()
        ]
        tables.append(
            Table(
                name=node["name"],
                columns=columns,
                description=node.get("description") or None,
            )
        )

    if not tables:
        raise ValueError("no model/source/seed/snapshot nodes found in manifest")
    return SchemaIR(source_format=SourceFormat.DBT_MANIFEST, tables=tables)
