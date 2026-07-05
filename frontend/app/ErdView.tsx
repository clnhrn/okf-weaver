"use client";

import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import { Background, Controls, ReactFlow } from "@xyflow/react";
import { layoutErd } from "./erd-layout";
import TableNode from "./TableNode";
import type { OKFTable } from "./types";

const nodeTypes = { table: TableNode };

export default function ErdView({ tables }: { tables: OKFTable[] }) {
  const { nodes, edges, externalRefs } = useMemo(() => layoutErd(tables), [tables]);

  if (tables.length === 0) {
    return (
      <div className="state empty">
        <span className="state-icon">{"{ }"}</span>
        <p className="state-title">No bundle to diagram</p>
        <p className="muted">Generate a bundle to see its ERD.</p>
      </div>
    );
  }

  return (
    <div className="erd-wrap">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.15}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} color="var(--border)" />
        <Controls showInteractive={false} />
      </ReactFlow>
      {externalRefs > 0 && (
        <div className="erd-note mono">
          {externalRefs} foreign-key reference{externalRefs === 1 ? "" : "s"} point outside this
          bundle
        </div>
      )}
    </div>
  );
}
