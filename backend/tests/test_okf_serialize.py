"""Tests for OKF serialization (bundle -> Markdown+YAML files -> zip)."""

import io
import zipfile

import yaml

from okf_weaver.models import OKFBundle, OKFColumn, OKFTable
from okf_weaver.okf.serialize import bundle_to_files, serialize_bundle


def _bundle():
    return OKFBundle(
        tables=[
            OKFTable(
                name="orders",
                description="One row per order.",
                confidence=0.9,
                is_source_of_truth=True,
                columns=[
                    OKFColumn(
                        name="total",
                        definition="Net order value.",
                        confidence=0.7,
                        data_type="numeric",
                        nullable=False,
                    )
                ],
            )
        ]
    )


def test_bundle_to_files_has_manifest_and_one_file_per_table():
    files = bundle_to_files(_bundle())
    assert "okf.yaml" in files
    assert "tables/orders.md" in files


def test_table_file_has_valid_yaml_frontmatter():
    md = bundle_to_files(_bundle())["tables/orders.md"]
    assert md.startswith("---\n")
    frontmatter = md.split("---\n", 2)[1]
    meta = yaml.safe_load(frontmatter)  # must parse as valid YAML
    assert meta["name"] == "orders"
    assert meta["okf_version"] == "0.1"
    assert "Net order value." in md  # column definition made it into the body
    assert "`numeric`" in md  # inferred type surfaced in the output
    assert "not null" in md


def test_serialize_bundle_returns_a_readable_zip():
    data = serialize_bundle(_bundle())
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        assert {"okf.yaml", "tables/orders.md"} <= names
        # manifest re-parses as valid YAML
        manifest = yaml.safe_load(z.read("okf.yaml"))
        assert manifest["tables"] == ["orders"]
