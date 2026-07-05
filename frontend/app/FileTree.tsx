"use client";

import { useMemo } from "react";

type Node = { name: string; path?: string; children?: Node[] };

function buildTree(paths: string[]): Node[] {
  const root: Node = { name: "", children: [] };
  for (const path of [...paths].sort()) {
    const parts = path.split("/");
    let node = root;
    parts.forEach((part, i) => {
      const isFile = i === parts.length - 1;
      let child = node.children!.find((c) => c.name === part);
      if (!child) {
        child = isFile ? { name: part, path } : { name: part, children: [] };
        node.children!.push(child);
      }
      node = child;
    });
  }
  return root.children!;
}

export default function FileTree({
  files,
  selected,
  onSelect,
}: {
  files: Record<string, string>;
  selected: string;
  onSelect: (path: string) => void;
}) {
  const tree = useMemo(() => buildTree(Object.keys(files)), [files]);

  function render(nodes: Node[], depth: number) {
    return nodes.map((n) =>
      n.children ? (
        <div key={n.name}>
          <div className="fdir" style={{ paddingLeft: depth * 12 + 8 }}>
            {n.name}/
          </div>
          {render(n.children, depth + 1)}
        </div>
      ) : (
        <button
          key={n.path}
          className={`ffile ${selected === n.path ? "sel" : ""}`}
          style={{ paddingLeft: depth * 12 + 8 }}
          onClick={() => onSelect(n.path!)}
        >
          {n.name}
        </button>
      ),
    );
  }

  return <div className="ftree mono">{render(tree, 0)}</div>;
}
