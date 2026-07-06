import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { band } from "./types";
import type { ErdNodeData } from "./erd-graph";

type TableNodeType = Node<ErdNodeData, "table">;

// A table entity in the ERD: header (name + confidence + source-of-truth) over a
// column list with PK/FK markers. Plain HTML/CSS, so it inherits the app's
// data-theme variables (light/dark) for free.
export default function TableNode({ data }: NodeProps<TableNodeType>) {
  return (
    <div className="erd-node">
      <Handle type="target" position={Position.Left} />
      <div className="erd-node-head">
        <span className="mono erd-node-name">{data.name}</span>
        {data.isSourceOfTruth && (
          <span className="erd-sot" title="Source of truth">
            SOT
          </span>
        )}
        <span className={`chip conf ${band(data.confidence)}`}>{data.confidence.toFixed(2)}</span>
      </div>
      <div className="erd-node-cols">
        {data.columns.map((c) => (
          <div className="erd-col" key={c.name}>
            <span className={`erd-key ${c.is_primary_key ? "pk" : c.references ? "fk" : ""}`}>
              {c.is_primary_key ? "PK" : c.references ? "FK" : ""}
            </span>
            <span className="mono erd-col-name">{c.name}</span>
            <span className="mono erd-col-type">{c.data_type}</span>
          </div>
        ))}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
