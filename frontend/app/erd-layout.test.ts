import { describe, expect, it } from "vitest";
import { layoutErd } from "./erd-layout";
import type { OKFColumn, OKFTable } from "./types";

function col(name: string, over: Partial<OKFColumn> = {}): OKFColumn {
  return {
    name,
    definition: "",
    confidence: 0.9,
    data_type: "int",
    is_primary_key: false,
    nullable: true,
    references: null,
    ...over,
  };
}

function table(name: string, columns: OKFColumn[]): OKFTable {
  return { name, description: "", confidence: 0.9, is_source_of_truth: false, columns };
}

const TABLES = [
  table("orders", [col("id", { is_primary_key: true }), col("customer_id", { references: "customers.id" })]),
  table("customers", [col("id", { is_primary_key: true })]),
];

describe("layoutErd", () => {
  it("assigns every table a node with finite, distinct dagre positions", () => {
    const { nodes } = layoutErd(TABLES);
    expect(nodes).toHaveLength(2);
    for (const n of nodes) {
      expect(n.type).toBe("table");
      expect(Number.isFinite(n.position.x)).toBe(true);
      expect(Number.isFinite(n.position.y)).toBe(true);
    }
    // LR layout puts the referenced table on a different rank from the referrer.
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n.position]));
    expect(byId.orders.x).not.toBe(byId.customers.x);
  });

  it("carries the foreign-key edges and external-ref count through", () => {
    const { edges, externalRefs } = layoutErd(TABLES);
    expect(edges).toHaveLength(1);
    expect(edges[0]).toMatchObject({ source: "orders", target: "customers", label: "customer_id" });
    expect(externalRefs).toBe(0);
  });

  it("lays out an empty bundle without error", () => {
    expect(layoutErd([])).toEqual({ nodes: [], edges: [], externalRefs: 0 });
  });
});
