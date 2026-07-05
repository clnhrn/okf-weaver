"""Serialize a validated `OKFBundle` to the OKF Markdown+YAML file layout.

Layout:
    okf.yaml            -- manifest: version + table list
    tables/<name>.md    -- one file per table: YAML frontmatter + Markdown body
"""

from __future__ import annotations

import io
import zipfile

import yaml

from okf_weaver.models import OKFBundle, OKFTable


def bundle_to_files(bundle: OKFBundle) -> dict[str, str]:
    """Render the bundle to a ``{path: text}`` mapping (unzipped)."""
    files: dict[str, str] = {
        "okf.yaml": yaml.safe_dump(
            {"okf_version": bundle.okf_version, "tables": [t.name for t in bundle.tables]},
            sort_keys=False,
        )
    }
    for table in bundle.tables:
        files[f"tables/{table.name}.md"] = _table_markdown(bundle.okf_version, table)
    return files


def serialize_bundle(bundle: OKFBundle) -> bytes:
    """Render the bundle and pack it into a `.zip` archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in bundle_to_files(bundle).items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _table_markdown(okf_version: str, table: OKFTable) -> str:
    frontmatter = yaml.safe_dump(
        {
            "name": table.name,
            "okf_version": okf_version,
            "is_source_of_truth": table.is_source_of_truth,
            "confidence": table.confidence,
        },
        sort_keys=False,
    )
    lines = [f"# {table.name}", "", table.description, "", "## Columns", ""]
    for column in table.columns:
        lines.append(f"- **{column.name}** (confidence {column.confidence:.2f}): {column.definition}")
    body = "\n".join(lines)
    return f"---\n{frontmatter}---\n\n{body}\n"
