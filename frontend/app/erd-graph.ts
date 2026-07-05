import type { OKFColumn, OKFTable } from "./types";

// The bundle-derived graph the ERD view renders: one node per table, one edge
// per foreign key that points at another table in the same bundle. Kept pure
// (no React Flow / dagre) so it can be unit-tested on its own.

export type ErdNodeData = {
  name: string;
  confidence: number;
  isSourceOfTruth: boolean;
  columns: OKFColumn[];
};

export type ErdNode = { id: string; data: ErdNodeData };
export type ErdEdge = { id: string; source: string; target: string; label: string };

export type ErdGraph = {
  nodes: ErdNode[];
  edges: ErdEdge[];
  externalRefs: number; // FKs whose target table isn't in this bundle (undrawable)
};

export function buildErdGraph(tables: OKFTable[]): ErdGraph {
  const present = new Set(tables.map((t) => t.name));
  const nodes: ErdNode[] = tables.map((t) => ({
    id: t.name,
    data: {
      name: t.name,
      confidence: t.confidence,
      isSourceOfTruth: t.is_source_of_truth,
      columns: t.columns,
    },
  }));

  const edges: ErdEdge[] = [];
  let externalRefs = 0;
  for (const table of tables) {
    for (const column of table.columns) {
      if (!column.references) continue;
      const target = column.references.split(".")[0];
      if (present.has(target)) {
        edges.push({
          id: `${table.name}.${column.name}->${target}`,
          source: table.name,
          target,
          label: column.name,
        });
      } else {
        externalRefs += 1;
      }
    }
  }

  return { nodes, edges, externalRefs };
}
