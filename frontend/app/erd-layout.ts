import dagre from "@dagrejs/dagre";
import type { Edge, Node } from "@xyflow/react";
import { buildErdGraph, type ErdNodeData } from "./erd-graph";
import type { OKFTable } from "./types";

// Turn a bundle into positioned React Flow nodes + edges via a dagre layout.
// Pure (dagre is headless), so it's unit-testable without React Flow / a DOM.

// Size estimates dagre needs up front; kept in sync with the .erd-node CSS.
const NODE_W = 236;
const HEAD_H = 30;
const ROW_H = 20;
const nodeHeight = (cols: number) => HEAD_H + Math.max(1, cols) * ROW_H + 8;

export type ErdLayout = { nodes: Node<ErdNodeData>[]; edges: Edge[]; externalRefs: number };

export function layoutErd(tables: OKFTable[]): ErdLayout {
  const graph = buildErdGraph(tables);
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 36, ranksep: 90 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of graph.nodes) {
    g.setNode(n.id, { width: NODE_W, height: nodeHeight(n.data.columns.length) });
  }
  for (const e of graph.edges) g.setEdge(e.source, e.target);
  dagre.layout(g);

  const nodes: Node<ErdNodeData>[] = graph.nodes.map((n) => {
    const p = g.node(n.id) as { x: number; y: number };
    const h = nodeHeight(n.data.columns.length);
    return {
      id: n.id,
      type: "table",
      position: { x: p.x - NODE_W / 2, y: p.y - h / 2 },
      data: n.data,
    };
  });
  const edges: Edge[] = graph.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.label,
  }));

  return { nodes, edges, externalRefs: graph.externalRefs };
}
