import { describe, expect, it } from "vitest";
import { buildErdGraph } from "./erd-graph";
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

describe("buildErdGraph", () => {
  it("makes one node per table and one edge per in-bundle foreign key", () => {
    const tables = [
      table("orders", [
        col("id", { is_primary_key: true }),
        col("customer_id", { references: "customers.id" }),
      ]),
      table("customers", [col("id", { is_primary_key: true })]),
    ];
    const g = buildErdGraph(tables);
    expect(g.nodes.map((n) => n.id).sort()).toEqual(["customers", "orders"]);
    expect(g.edges).toEqual([
      { id: "orders.customer_id->customers", source: "orders", target: "customers", label: "customer_id" },
    ]);
    expect(g.externalRefs).toBe(0);
  });

  it("counts foreign keys pointing outside the bundle instead of drawing them", () => {
    const tables = [table("orders", [col("region_id", { references: "geo.region.id" })])];
    const g = buildErdGraph(tables);
    expect(g.edges).toEqual([]);
    expect(g.externalRefs).toBe(1);
  });

  it("keeps a self-referential foreign key as a self-edge", () => {
    const tables = [
      table("employees", [
        col("id", { is_primary_key: true }),
        col("manager_id", { references: "employees.id" }),
      ]),
    ];
    const g = buildErdGraph(tables);
    expect(g.edges).toEqual([
      { id: "employees.manager_id->employees", source: "employees", target: "employees", label: "manager_id" },
    ]);
  });

  it("produces no edges when there are no foreign keys", () => {
    const g = buildErdGraph([table("t", [col("id", { is_primary_key: true })])]);
    expect(g.edges).toEqual([]);
    expect(g.externalRefs).toBe(0);
  });
});
