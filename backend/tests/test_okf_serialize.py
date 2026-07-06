"""Tests for OKF v0.1 serialization (bundle -> conformant OKF directory -> zip)."""

import io
import zipfile

import yaml

from okf_weaver.models import OKFBundle, OKFColumn, OKFTable
from okf_weaver.okf.serialize import bundle_filename, bundle_to_files, serialize_bundle


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
                    ),
                    OKFColumn(
                        name="customer_id",
                        definition="The buyer.",
                        confidence=0.8,
                        data_type="int",
                        references="customers.id",
                    ),
                ],
            )
        ]
    )


def _frontmatter(md: str) -> dict:
    return yaml.safe_load(md.split("---\n", 2)[1])


def test_bundle_to_files_has_index_and_per_table_concept_files():
    files = bundle_to_files(_bundle())
    assert "index.md" in files  # reserved bundle-root manifest
    assert "log.md" in files  # reserved update history
    assert "tables/orders.md" in files


def test_index_declares_okf_version_and_links_concepts():
    idx = bundle_to_files(_bundle())["index.md"]
    assert _frontmatter(idx)["okf_version"] == "0.1"
    assert "[orders](/tables/orders.md)" in idx


def test_index_uses_bundle_name_as_title_and_frontmatter():
    bundle = OKFBundle(name="Acme Sales Warehouse", tables=_bundle().tables)
    idx = bundle_to_files(bundle)["index.md"]
    assert _frontmatter(idx)["name"] == "Acme Sales Warehouse"
    assert "# Acme Sales Warehouse" in idx


def test_bundle_filename_slugifies_name_with_zip_extension():
    assert bundle_filename(OKFBundle(name="Acme Sales!! Warehouse", tables=_bundle().tables)) == (
        "acme-sales-warehouse.zip"
    )
    # A name that slugifies to nothing falls back rather than yielding ".zip".
    assert bundle_filename(OKFBundle(name="—", tables=_bundle().tables)) == "okf-bundle.zip"


def test_table_frontmatter_has_required_type_and_recommended_fields():
    md = bundle_to_files(_bundle())["tables/orders.md"]
    assert md.startswith("---\n")
    meta = _frontmatter(md)
    assert meta["type"] == "Table"  # the one field OKF requires
    assert meta["title"] == "orders"
    assert meta["description"] == "One row per order."
    assert "timestamp" in meta
    assert meta["okf_x_source_of_truth"] is True  # extension key


def test_table_body_uses_schema_table_with_types_pk_and_fk_links():
    md = bundle_to_files(_bundle())["tables/orders.md"]
    assert "# Schema" in md
    assert "| Column | Type | Description | Confidence |" in md
    assert "`total`" in md and "numeric" in md and "Net order value." in md
    assert "Not null." in md
    # foreign key rendered as a bundle-relative cross-link per the spec
    assert "FK to [customers](/tables/customers.md)." in md


def test_serialize_bundle_returns_zip_of_the_okf_directory():
    data = serialize_bundle(_bundle())
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        assert {"index.md", "log.md", "tables/orders.md"} <= names
        idx = yaml.safe_load(z.read("index.md").decode().split("---\n")[1])
        assert idx["okf_version"] == "0.1"


def test_serialize_never_emits_a_path_that_escapes_the_bundle_dir():
    # Defence in depth: the model gate already rejects traversal names, but if a
    # malicious name ever bypasses it, serialization must still keep every entry
    # inside `tables/` (no `..`, no absolute paths, no reserved-file overwrite).
    evil = OKFTable.model_construct(
        name="../../../../tmp/pwned",
        description="x",
        confidence=0.9,
        is_source_of_truth=False,
        columns=[],
    )
    bundle = OKFBundle.model_construct(okf_version="0.1", name="b", tables=[evil])
    names = zipfile.ZipFile(io.BytesIO(serialize_bundle(bundle))).namelist()
    for name in names:
        assert ".." not in name
        assert name.startswith(("index.md", "log.md", "tables/"))
        assert name.count("/") <= 1  # tables/<file>, never a nested escape
