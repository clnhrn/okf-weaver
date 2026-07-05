import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import MarkdownView from "./MarkdownView";

// A representative OKF table file: YAML frontmatter + a GFM `# Schema` table with
// an inline-code column name and an FK cross-link, exactly as serialize.py emits.
const OKF_TABLE = `---
type: Table
title: orders
description: One row per order.
okf_x_table_confidence: 0.9
---

# Schema

| Column | Type | Description | Confidence |
|---|---|---|---|
| \`customer_id\` | int | FK to [customers](/tables/customers.md). | 0.80 |
`;

const FILES = {
  "tables/orders.md": OKF_TABLE,
  "tables/customers.md": "---\ntype: Table\n---\n\n# Schema\n",
};

function render(content: string) {
  return renderToStaticMarkup(
    <MarkdownView content={content} files={FILES} onNavigate={() => {}} />,
  );
}

describe("MarkdownView", () => {
  it("lifts YAML frontmatter into a metadata strip, not literal --- text", () => {
    const html = render(OKF_TABLE);
    expect(html).toContain("okf_x_table_confidence");
    expect(html).toContain("Table");
    // The raw frontmatter fence must not survive into the rendered body.
    expect(html).not.toContain("---");
  });

  it("renders the GFM schema table as a real <table>", () => {
    const html = render(OKF_TABLE);
    expect(html).toContain("<table>");
    expect(html).toContain("<th>Column</th>");
    expect(html).toContain("<code>customer_id</code>");
  });

  it("resolves an in-bundle cross-link to the target file key", () => {
    const html = render(OKF_TABLE);
    // Internal link keeps its href but points at the bundle file (nav handled onClick).
    expect(html).toContain('href="/tables/customers.md"');
  });

  it("opens an unknown link in a new tab", () => {
    const html = render("[docs](https://example.com)");
    expect(html).toContain('target="_blank"');
    expect(html).toContain('href="https://example.com"');
  });
});
