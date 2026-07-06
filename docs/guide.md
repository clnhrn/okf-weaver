# OKF Weaver — User Guide

OKF Weaver turns a **relational database schema** into a curated, validated, portable **Open Knowledge Format (OKF)** bundle: machine-readable context describing what every table and column actually means. It works for analytics warehouses (Snowflake, BigQuery, Databricks) **and** operational databases (Postgres, SQL Server, MySQL) — including the ones you inherited and nobody documented.

You give it a schema; it generates business descriptions and definitions per table/column with a confidence score, you review and edit, and you export a portable bundle you can hand to an AI agent, an MCP server, or a teammate.

There are three steps: **export your schema → generate & review → use the bundle.**

---

## 1. Export your schema DDL from your database

OKF Weaver needs your schema as **SQL DDL** (`CREATE TABLE` statements) or a dbt `manifest.json`. Only the schema — table/column names, types, keys, relationships — is used; **no row data is ever sent** (see Privacy below). Export schema-only and paste or upload it.

Primary keys and foreign keys are picked up whether they're written inline, as table-level constraints, or as separate `ALTER TABLE ... ADD CONSTRAINT` statements — which is how `pg_dump` and SQL Server emit them — so you can paste a raw dump without cleaning it up.

### PostgreSQL

```bash
# whole database, schema only
pg_dump --schema-only --no-owner --no-privileges mydb > schema.sql

# just a few tables
pg_dump --schema-only --no-owner --no-privileges -t public.orders -t public.customers mydb > schema.sql
```

Indexes, sequences, and grants in the dump are ignored — only `CREATE TABLE` and `ALTER TABLE ... ADD CONSTRAINT` are read.

### SQL Server

**SSMS (GUI):** right-click the database → **Tasks → Generate Scripts** → choose the tables → in **Advanced**, set **Types of data to script = Schema only** → save/copy the script. The `GO` separators and `[bracketed]` identifiers are handled.

**CLI (cross-platform):**

```bash
pip install mssql-scripter
mssql-scripter -S localhost -d mydb -U sa --schema-and-data-flags SchemaOnly > schema.sql
```

### MySQL / MariaDB

```bash
# whole database, schema only
mysqldump --no-data --skip-comments mydb > schema.sql

# just a few tables
mysqldump --no-data mydb orders customers > schema.sql
```

### Other databases

Any `CREATE TABLE` DDL works — the parser is dialect-tolerant (SQLite `.schema`, Oracle `DBMS_METADATA.GET_DDL`, etc.). If a paste doesn't parse, trim it down to just the `CREATE TABLE` and `ALTER TABLE ... ADD CONSTRAINT` statements.

### Already using dbt?

Skip the export — upload your `target/manifest.json` directly. Existing dbt `description` fields are used as a strong prior.

> **Privacy.** Only schema *metadata* (names + types) is sent to the model, never row data, and nothing is stored after the request. Don't paste secrets or connection strings.

---

## 2. Generate and review

1. **Paste** the DDL into the **Source** pane, or **Upload** your `.sql` / `manifest.json`. The format is auto-detected.
2. *(Optional but recommended)* Expand **Context** and add domain notes or a glossary — e.g. *"revenue = net of tax and refunds; `status` ∈ {pending, shipped, cancelled}"*. This is the single biggest accuracy lever and lifts confidence on ambiguous columns.
3. Click **Generate**. Tables stream in as they're written, each column filling in live.
4. **Review** — every field carries a confidence score (High ≥ 0.8 / Medium / Low < 0.5); low-confidence items are surfaced first. Edit any description inline, toggle primary-key / source-of-truth, and fix types. **Nothing is final until you approve it** — human review is the point.
5. **ERD tab** — see the tables and their foreign-key relationships as a diagram, a quick way to sanity-check that the relationships came through and to understand the schema's shape.
6. **Files tab** — preview the exact OKF markdown the download will contain (toggle Rendered / Raw).

---

## 3. Use and organize the bundle

Click **Approve & download** to get `okf-bundle.zip`, a conformant OKF v0.1 directory:

```text
okf-bundle/
├── index.md            # bundle root: okf_version + a linked list of tables
├── log.md              # generation history
└── tables/
    ├── orders.md       # one concept per table: YAML frontmatter + a # Schema
    ├── customers.md    # table (columns, types, definitions, confidence, FK links)
    └── ...
```

Each `tables/<name>.md` has YAML frontmatter (`type`, `title`, description, confidence, source-of-truth) and a `# Schema` table whose foreign keys link to the other tables — so the bundle is a small, browsable knowledge base on its own.

**Organize it:**

- **Commit it to version control** next to the code that owns the database (e.g. `docs/okf/`), or in a dedicated knowledge repo. Because it's plain Markdown + YAML, it diffs cleanly in pull requests.
- **Re-generate when the schema changes.** v1 is one-shot (no live sync), so treat the bundle like any other generated doc: regenerate and commit the diff when tables change.
- **Keep the raw DDL** you exported alongside the bundle so regeneration is reproducible.

**Put it to work:**

- **AI agents / MCP servers / RAG** — point them at the OKF markdown so they answer with grounded table and column meaning instead of guessing, cutting text-to-SQL and analytics hallucinations.
- **Text-to-SQL / copilots** — feed the relevant `tables/*.md` as context so generated queries use the right columns and definitions.
- **Onboarding** — hand it to a teammate learning the database; the descriptions and ERD explain what the schema means far faster than reading raw DDL.

The bundle is **vendor-neutral and portable** — it's just Markdown and YAML, so any framework or teammate can consume it, with no lock-in.

---

See also: [`README.md`](../README.md) for running the app, and [`spec.md`](spec.md) for architecture and the OKF format details.
